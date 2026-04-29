/**
 * Sortir Stiker Pack — Sales Sync + Stock Reader Webhook
 * ──────────────────────────────────────────────────────
 * Paste seluruh file ini ke Apps Script editor (Extensions → Apps Script)
 * di Google Sheet target, lalu Deploy → New deployment → Web app:
 *   - Description : Sortir Stiker Pack Sync
 *   - Execute as  : Me (akun pemilik sheet)
 *   - Who has access : Anyone with the link
 *
 * Endpoints:
 *   POST  → tulis baris penjualan ke tab DATA_SALES
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

function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return _json({status: 'error', message: 'Empty body'});
    }

    const body = JSON.parse(e.postData.contents);
    const rows = body.rows;

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
  } catch (err) {
    return _json({status: 'error', message: String(err)});
  }
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
