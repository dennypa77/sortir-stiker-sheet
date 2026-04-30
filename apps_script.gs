/**
 * Sortir Stiker Pack — Sales Sync + Stock Reader/Consumer Webhook
 * ──────────────────────────────────────────────────────
 * Paste seluruh file ini ke Apps Script editor (Extensions → Apps Script)
 * di Google Sheet target, lalu Deploy → New deployment → Web app:
 *   - Description : Sortir Stiker Pack Sync
 *   - Execute as  : Me (akun pemilik sheet)
 *   - Who has access : Anyone with the link
 *
 * Endpoints:
 *   POST  (default / action="sync_orders")
 *         → tulis baris penjualan ke tab DATA_SALES
 *   POST  (action="consume_stock")
 *         → potong stok di DATABASE_STIKER (kolom G) + tulis ke LOG_KELUAR
 *           (kolom B=SKU, C=Qty, D=Ket; kolom A=Tanggal otomatis terisi).
 *   GET   → baca stok dari tab DATABASE_STIKER, balas {status, stock: {SKU: qty}}
 *
 * Re-deploy (Manage deployments → edit → New version) setiap kali edit script ini —
 * URL deployment lama tidak otomatis dapat versi baru.
 */

const SHEET_NAME = 'DATA_SALES';
const EXPECTED_HEADER = ['Tanggal', 'No Resi', 'ID SKU', 'Qty'];

// Tab inventaris yang dibaca via doGet
const STOCK_SHEET_NAME = 'DATABASE_STIKER';
const STOCK_SKU_COL = 1;  // A — ID SKU
const STOCK_QTY_COL = 7;  // G — Stok Saat ini

// Tab log keluar — A=Tanggal (auto), B=SKU, C=Qty, D=Ket
const STOCK_LOG_SHEET_NAME = 'LOG_KELUAR';

function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return _json({status: 'error', message: 'Empty body'});
    }

    const body = JSON.parse(e.postData.contents);
    const action = body.action || 'sync_orders';

    if (action === 'consume_stock') {
      return _consumeStock(body.items);
    }
    return _syncOrders(body.rows);
  } catch (err) {
    return _json({status: 'error', message: String(err)});
  }
}

function _syncOrders(rows) {
  if (!Array.isArray(rows)) {
    return _json({status: 'error', message: 'Field "rows" harus array'});
  }
  if (rows.length === 0) {
    return _json({status: 'ok', written: 0, message: 'no rows'});
  }

  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
  if (!sheet) {
    return _json({status: 'error', message: 'Tab "' + SHEET_NAME + '" tidak ditemukan'});
  }

  const values = rows.map(function(r) {
    return [
      r.tanggal != null ? r.tanggal : '',
      r.resi    != null ? r.resi    : '',
      r.sku     != null ? r.sku     : '',
      r.qty     != null ? r.qty     : '',
    ];
  });

  const startRow = Math.max(sheet.getLastRow() + 1, 2);
  sheet.getRange(startRow, 1, values.length, 4).setValues(values);

  return _json({status: 'ok', written: values.length});
}

function _consumeStock(items) {
  if (!Array.isArray(items)) {
    return _json({status: 'error', message: 'Field "items" harus array'});
  }
  if (items.length === 0) {
    return _json({status: 'ok', consumed: [], count: 0});
  }

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const stockSheet = ss.getSheetByName(STOCK_SHEET_NAME);
  if (!stockSheet) {
    return _json({status: 'error', message: 'Tab "' + STOCK_SHEET_NAME + '" tidak ditemukan'});
  }
  const logSheet = ss.getSheetByName(STOCK_LOG_SHEET_NAME);
  if (!logSheet) {
    return _json({status: 'error', message: 'Tab "' + STOCK_LOG_SHEET_NAME + '" tidak ditemukan'});
  }

  const lastRow = stockSheet.getLastRow();
  if (lastRow < 2) {
    return _json({status: 'error', message: 'DATABASE_STIKER kosong'});
  }

  // Pre-load semua SKU sekali, build index → row number
  const numRows = lastRow - 1;
  const skuValues = stockSheet.getRange(2, STOCK_SKU_COL, numRows, 1).getValues();
  const skuToRow = {};
  for (let i = 0; i < numRows; i++) {
    const sku = String(skuValues[i][0] == null ? '' : skuValues[i][0]).trim().toUpperCase();
    if (sku) skuToRow[sku] = i + 2;  // +2 karena range mulai row 2
  }

  const results = [];
  const logRows = [];

  for (let i = 0; i < items.length; i++) {
    const item = items[i] || {};
    const sku = String(item.sku == null ? '' : item.sku).trim().toUpperCase();
    const qty = Number(item.qty);
    const ket = String(item.ket == null ? '' : item.ket);

    if (!sku || !qty || qty <= 0 || isNaN(qty)) {
      results.push({sku: sku, ok: false, message: 'sku/qty invalid'});
      continue;
    }

    const row = skuToRow[sku];
    if (!row) {
      results.push({sku: sku, ok: false, message: 'SKU tidak ada di DATABASE_STIKER'});
      continue;
    }

    const cell = stockSheet.getRange(row, STOCK_QTY_COL);
    const currentStock = Number(cell.getValue()) || 0;
    if (currentStock < qty) {
      results.push({
        sku: sku, ok: false,
        message: 'stok kurang (sisa ' + currentStock + ', minta ' + qty + ')'
      });
      continue;
    }

    cell.setValue(currentStock - qty);
    // Skip kolom A (Tanggal) supaya formula auto-fill jalan.
    logRows.push([sku, qty, ket]);
    results.push({sku: sku, ok: true, taken: qty, sisa: currentStock - qty});
  }

  if (logRows.length > 0) {
    const startRow = Math.max(logSheet.getLastRow() + 1, 2);
    logSheet.getRange(startRow, 2, logRows.length, 3).setValues(logRows);
  }

  return _json({status: 'ok', consumed: results, count: logRows.length});
}

function doGet(e) {
  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(STOCK_SHEET_NAME);
    if (!sheet) {
      return _json({
        status: 'error',
        message: 'Tab "' + STOCK_SHEET_NAME + '" tidak ditemukan'
      });
    }

    const lastRow = sheet.getLastRow();
    if (lastRow < 2) {
      return _json({status: 'ok', stock: {}, count: 0});
    }

    const numRows = lastRow - 1;
    const skus = sheet.getRange(2, STOCK_SKU_COL, numRows, 1).getValues();
    const qtys = sheet.getRange(2, STOCK_QTY_COL, numRows, 1).getValues();

    const stock = {};
    for (let i = 0; i < numRows; i++) {
      const sku = String(skus[i][0] == null ? '' : skus[i][0]).trim();
      if (!sku) continue;
      // Normalisasi key ke uppercase supaya match-nya case-insensitive di sisi Python
      const key = sku.toUpperCase();
      const qty = Number(qtys[i][0]);
      stock[key] = isNaN(qty) ? 0 : qty;
    }

    return _json({
      status: 'ok',
      stock: stock,
      count: Object.keys(stock).length
    });
  } catch (err) {
    return _json({status: 'error', message: String(err)});
  }
}

function _json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
