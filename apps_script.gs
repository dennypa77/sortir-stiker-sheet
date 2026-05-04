/**
 * WMS Stiker Hybrid System - Apps Script V6.10
 *
 * Fitur asli (V6.9 — TIDAK BERUBAH):
 *   - Scanner barcode (Kelola Gudang menu)
 *   - Upload Data Penjualan
 *   - Hard Sync Opname
 *   - Cleanup data lama
 *   - Skip kolom A (formula tanggal) → tulis hanya B/C/D
 *
 * Tambahan untuk Sortir Stiker Pack desktop app:
 *   GET   doGet  → baca stok kolom G (Stok Saat ini) dari DATABASE_STIKER
 *   POST  doPost (action="sync_orders") → append ke DATA_SALES (B,C,D)
 *   POST  doPost (action="consume_stock") → append ke LOG_KELUAR (B,C,D),
 *         stok di kolom G auto-update lewat formula yang sudah ada.
 *
 * Setelah edit script ini, WAJIB:
 *   Deploy → Manage deployments → ⚙️ pada deployment Web app → New version → Deploy.
 *   URL deployment lama otomatis ikut versi baru — tidak perlu ganti URL di app.
 */

function getSS() {
  return SpreadsheetApp.getActiveSpreadsheet();
}

const SH_DATABASE = "DATABASE_STIKER";
const SH_SALES = "DATA_SALES";
const SH_OPNAME = "STOK_OPNAME";
const SH_LOG_MASUK = "LOG_MASUK";
const SH_LOG_KELUAR = "LOG_KELUAR";

// Kolom DATABASE_STIKER (1-indexed)
const STOCK_SKU_COL = 1;  // A — ID SKU
const STOCK_QTY_COL = 7;  // G — Stok Saat ini (formula)

/**
 * Menu Kustom
 */
function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu('📦 Kelola Gudang')
      .addItem('📷 Buka Scanner Kamera', 'showScanner')
      .addSeparator()
      .addItem('📤 Upload Data Penjualan', 'showUploadDialog')
      .addItem('🔄 Hard Sync Opname', 'hardSyncOpname')
      .addItem('🧹 Bersihkan Data Lama (30 Hari)', 'cleanupOldSales')
      .addToUi();
}

/**
 * Menampilkan dialog scanner
 */
function showScanner() {
  const html = HtmlService.createHtmlOutputFromFile('ScannerUI')
      .setWidth(450)
      .setHeight(650)
      .setTitle('Scanner Barcode Gudang');
  SpreadsheetApp.getUi().showModalDialog(html, 'Scanner Barcode');
}

/**
 * Memproses hasil scan
 */
function processScan(type, skuRaw, qty) {
  try {
    const ss = getSS();
    const targetSheetName = (type === 'MASUK') ? SH_LOG_MASUK : SH_LOG_KELUAR;
    const sheet = ss.getSheetByName(targetSheetName);

    if (!sheet) return "❌ Error: Sheet '" + targetSheetName + "' tidak ditemukan!";

    // --- SKU APA ADANYA ---
    let idMaster = skuRaw.trim();
    let multiplier = 1;

    // Logika Multiplier (jika berakhiran 'pcs')
    const lowerSku = skuRaw.toLowerCase();
    if (lowerSku.endsWith('pcs') && lowerSku.includes('-')) {
      const parts = skuRaw.split('-');
      const lastPart = parts[parts.length - 1];
      const matchMul = lastPart.match(/\d+/);
      if (matchMul) {
        multiplier = parseInt(matchMul[0]);
        idMaster = parts.slice(0, -1).join('-').trim();
      }
    }

    const finalQty = (parseInt(qty) || 1) * multiplier;
    const keterangan = "Scanner";

    // --- LOGIKA MENEMUKAN BARIS BERDASARKAN KOLOM B ---
    // Kita cek data di kolom B untuk menentukan baris terakhir yang sebenarnya
    const colBData = sheet.getRange("B:B").getValues();
    let lastRowB = 0;
    while (colBData[lastRowB] && colBData[lastRowB][0] !== "") {
      lastRowB++;
    }
    const nextRow = lastRowB + 1; // Baris kosong berikutnya

    // Tulis hanya ke Kolom B, C, dan D (Mulai kolom ke-2)
    // Kolom A dibiarkan agar Formula Anda bekerja
    sheet.getRange(nextRow, 2, 1, 3).setValues([[idMaster, finalQty, keterangan]]);

    SpreadsheetApp.flush();
    return "✅ Berhasil: " + idMaster + " (" + finalQty + ") di Baris " + nextRow;

  } catch (e) {
    return "❌ Error Server: " + e.toString();
  }
}

/**
 * Memproses data penjualan massal (Upload)
 */
function processSalesData(rawInput) {
  try {
    const ss = getSS();
    const sheetSales = ss.getSheetByName(SH_SALES);
    if (!sheetSales) return;

    const rows = rawInput.split('\n').filter(r => r.trim() !== "").map(r => r.split('\t'));
    let processedData = [];

    rows.forEach(row => {
      if (row.length < 3) return;
      let resi = row.length === 3 ? row[0] : row[1];
      let skuRaw = row.length === 3 ? row[1] : row[2];
      let qtyRaw = row.length === 3 ? row[2] : row[3];

      let idMaster = skuRaw.trim();
      let multiplier = 1;

      if (skuRaw.toLowerCase().endsWith('pcs') && skuRaw.includes('-')) {
        const parts = skuRaw.split('-');
        const lastPart = parts[parts.length - 1];
        const matchMul = lastPart ? lastPart.match(/\d+/) : null;
        if (matchMul) {
          multiplier = parseInt(matchMul[0]);
          idMaster = parts.slice(0, -1).join('-').trim();
        }
      }

      // Format untuk tab Sales: Resi (B), ID SKU (C), Qty (D)
      // Tanggal (A) diasumsikan pakai formula juga
      processedData.push([resi, idMaster, (parseInt(qtyRaw) || 0) * multiplier]);
    });

    if (processedData.length > 0) {
      const colBData = sheetSales.getRange("B:B").getValues();
      let lastRowB = 0;
      while (colBData[lastRowB] && colBData[lastRowB][0] !== "") {
        lastRowB++;
      }
      const nextRow = lastRowB + 1;

      sheetSales.getRange(nextRow, 2, processedData.length, 3).setValues(processedData);
      SpreadsheetApp.getUi().alert('✅ Berhasil mengunggah ' + processedData.length + ' baris.');
    }

  } catch(e) {
    SpreadsheetApp.getUi().alert("❌ Error Upload: " + e.toString());
  }
}

/**
 * Sinkronisasi Opname
 */
function hardSyncOpname() {
  const ss = getSS();
  const dbSheet = ss.getSheetByName(SH_DATABASE);
  const opnameSheet = ss.getSheetByName(SH_OPNAME);

  if (!dbSheet || !opnameSheet) {
    SpreadsheetApp.getUi().alert("❌ Tab DATABASE_STIKER atau STOK_OPNAME tidak ditemukan.");
    return;
  }

  const dbData = dbSheet.getDataRange().getValues();
  const opnameData = opnameSheet.getDataRange().getValues();

  let latestOpname = {};
  for (let i = 1; i < opnameData.length; i++) {
    let sku = String(opnameData[i][1]).trim();
    latestOpname[sku] = opnameData[i][2];
  }

  const headers = dbData[0];
  const idxSku = headers.indexOf("ID SKU");
  const idxMasuk = headers.indexOf("Total Masuk");
  const idxKeluar = headers.indexOf("Total Keluar");
  const idxAdj = headers.indexOf("Adj Opname");

  for (let i = 1; i < dbData.length; i++) {
    const sku = String(dbData[i][idxSku]).trim();
    if (latestOpname[sku] !== undefined) {
      const adjustment = latestOpname[sku] - ((dbData[i][idxMasuk] || 0) - (dbData[i][idxKeluar] || 0));
      dbSheet.getRange(i + 1, idxAdj + 1).setValue(adjustment);
    }
  }
  SpreadsheetApp.getUi().alert("✅ Hard Sync Selesai.");
}

/**
 * Hapus data lama (>30 hari)
 */
function cleanupOldSales() {
  const ss = getSS();
  const sheet = ss.getSheetByName(SH_SALES);
  if (!sheet) return;
  const data = sheet.getDataRange().getValues();
  if (data.length <= 1) return;

  const now = new Date().getTime();
  const filtered = data.filter((row, idx) => {
    if (idx === 0) return true;
    const rowDate = new Date(row[0]).getTime(); // Mengasumsikan kolom A adalah tanggal statis hasil formula
    return isNaN(rowDate) || (now - rowDate) < 30 * 24 * 60 * 60 * 1000;
  });

  sheet.clearContents();
  if (filtered.length > 0) {
    sheet.getRange(1, 1, filtered.length, filtered[0].length).setValues(filtered);
  }
}

function showUploadDialog() {
  const ui = SpreadsheetApp.getUi();
  const response = ui.prompt('Upload Data Penjualan', 'Tempel data (Resi, SKU, Qty):', ui.ButtonSet.OK_CANCEL);
  if (response.getSelectedButton() == ui.Button.OK) processSalesData(response.getResponseText());
}


// ════════════════════════════════════════════════════════════════════════════
// ▼▼▼ WEBHOOK UNTUK DESKTOP APP "Sortir Stiker Pack" ▼▼▼
// Endpoint dipanggil oleh aplikasi Python di komputer karyawan.
// ════════════════════════════════════════════════════════════════════════════

/**
 * GET endpoint — baca stok dari DATABASE_STIKER kolom G untuk semua SKU.
 * Response: {"status":"ok", "stock": {"SKU1": 10, "SKU2": 5, ...}, "count": 42}
 */
function doGet(e) {
  try {
    const sheet = getSS().getSheetByName(SH_DATABASE);
    if (!sheet) {
      return _json({status: 'error', message: 'Tab "' + SH_DATABASE + '" tidak ditemukan'});
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
      // Normalisasi key uppercase supaya match case-insensitive di sisi Python
      const key = sku.toUpperCase();
      const qty = Number(qtys[i][0]);
      stock[key] = isNaN(qty) ? 0 : qty;
    }

    return _json({status: 'ok', stock: stock, count: Object.keys(stock).length});
  } catch (err) {
    return _json({status: 'error', message: String(err)});
  }
}

/**
 * POST endpoint — dispatch by action.
 *   default / "sync_orders" → tulis pesanan ke DATA_SALES (B,C,D)
 *   "consume_stock"          → tulis ke LOG_KELUAR (B,C,D), validasi stok dulu
 *   "lookup_resi"            → cari pesanan di DATA_SALES by No Resi, balas
 *                              {items:[{sku,qty}], stock:{SKU:qty}}
 */
function doPost(e) {
  try {
    if (!e || !e.postData || !e.postData.contents) {
      return _json({status: 'error', message: 'Empty body'});
    }
    const body = JSON.parse(e.postData.contents);
    const action = body.action || 'sync_orders';

    if (action === 'consume_stock') {
      return _consumeStockWebhook(body.items);
    }
    if (action === 'lookup_resi') {
      return _lookupResiWebhook(body.resi);
    }
    if (action === 'bulk_snapshot') {
      return _bulkSnapshotWebhook();
    }
    return _syncOrdersWebhook(body.rows);
  } catch (err) {
    return _json({status: 'error', message: String(err)});
  }
}

/**
 * Tulis pesanan ke DATA_SALES — B=Resi, C=SKU, D=Qty.
 * Kolom A (Tanggal) dilewati supaya formula auto-fill jalan.
 */
function _syncOrdersWebhook(rows) {
  if (!Array.isArray(rows)) {
    return _json({status: 'error', message: 'Field "rows" harus array'});
  }
  if (rows.length === 0) {
    return _json({status: 'ok', written: 0, message: 'no rows'});
  }

  const sheet = getSS().getSheetByName(SH_SALES);
  if (!sheet) {
    return _json({status: 'error', message: 'Tab "' + SH_SALES + '" tidak ditemukan'});
  }

  const values = rows.map(function(r) {
    return [
      r.resi != null ? r.resi : '',
      r.sku  != null ? r.sku  : '',
      r.qty  != null ? r.qty  : '',
    ];
  });

  // Pakai cara yang sama dgn processScan/processSalesData: cari baris kosong
  // berdasarkan kolom B supaya tidak nabrak formula di kolom A.
  const colBData = sheet.getRange("B:B").getValues();
  let lastRowB = 0;
  while (colBData[lastRowB] && colBData[lastRowB][0] !== "") {
    lastRowB++;
  }
  const nextRow = lastRowB + 1;

  sheet.getRange(nextRow, 2, values.length, 3).setValues(values);
  return _json({status: 'ok', written: values.length});
}

/**
 * Potong stok lewat append ke LOG_KELUAR (B=SKU, C=Qty, D=Ket).
 * Kolom G di DATABASE_STIKER auto-recalc karena formula yang sudah ada.
 *
 * Validasi tetap dilakukan: stok terkini (kolom G) harus >= qty diminta.
 * Untuk multiple item dgn SKU sama, kita track decrement secara lokal
 * supaya item ke-2 dst tidak nge-double-spend stok yang sama.
 */
function _consumeStockWebhook(items) {
  if (!Array.isArray(items)) {
    return _json({status: 'error', message: 'Field "items" harus array'});
  }
  if (items.length === 0) {
    return _json({status: 'ok', consumed: [], count: 0});
  }

  const ss = getSS();
  const stockSheet = ss.getSheetByName(SH_DATABASE);
  if (!stockSheet) {
    return _json({status: 'error', message: 'Tab "' + SH_DATABASE + '" tidak ditemukan'});
  }
  const logSheet = ss.getSheetByName(SH_LOG_KELUAR);
  if (!logSheet) {
    return _json({status: 'error', message: 'Tab "' + SH_LOG_KELUAR + '" tidak ditemukan'});
  }

  // Lock supaya tidak race dgn scanner / consume call lain
  const lock = LockService.getDocumentLock();
  if (!lock.tryLock(10000)) {
    return _json({status: 'error', message: 'Sheet sedang sibuk, coba lagi.'});
  }

  try {
    const lastRow = stockSheet.getLastRow();
    if (lastRow < 2) {
      return _json({status: 'error', message: 'DATABASE_STIKER kosong'});
    }

    // Bulk-load SKU + Stok Saat ini
    const numRows = lastRow - 1;
    const skuValues = stockSheet.getRange(2, STOCK_SKU_COL, numRows, 1).getValues();
    const qtyValues = stockSheet.getRange(2, STOCK_QTY_COL, numRows, 1).getValues();
    const skuToAvail = {};
    for (let i = 0; i < numRows; i++) {
      const sku = String(skuValues[i][0] == null ? '' : skuValues[i][0]).trim().toUpperCase();
      if (!sku) continue;
      const q = Number(qtyValues[i][0]);
      skuToAvail[sku] = isNaN(q) ? 0 : q;
    }

    const results = [];
    const logRows = [];

    for (let i = 0; i < items.length; i++) {
      const item = items[i] || {};
      const skuRaw = String(item.sku == null ? '' : item.sku).trim();
      const sku = skuRaw.toUpperCase();
      const qty = Number(item.qty);
      const ket = String(item.ket == null ? '' : item.ket);

      if (!sku || !qty || qty <= 0 || isNaN(qty)) {
        results.push({sku: sku, ok: false, message: 'sku/qty invalid'});
        continue;
      }

      if (!(sku in skuToAvail)) {
        results.push({sku: sku, ok: false, message: 'SKU tidak ada di DATABASE_STIKER'});
        continue;
      }

      const avail = skuToAvail[sku];
      if (avail < qty) {
        results.push({
          sku: sku, ok: false,
          message: 'stok kurang (sisa ' + avail + ', minta ' + qty + ')'
        });
        continue;
      }

      // Track decrement lokal (supaya item ke-2 SKU sama tidak double-spend)
      skuToAvail[sku] = avail - qty;
      // Tulis SKU asli (preserve case dari client) ke LOG_KELUAR
      logRows.push([skuRaw, qty, ket]);
      results.push({sku: sku, ok: true, taken: qty, sisa: avail - qty});
    }

    if (logRows.length > 0) {
      // Sama kayak processScan: cari baris kosong berdasarkan kolom B
      const colBData = logSheet.getRange("B:B").getValues();
      let lastRowB = 0;
      while (colBData[lastRowB] && colBData[lastRowB][0] !== "") {
        lastRowB++;
      }
      const startRow = lastRowB + 1;
      logSheet.getRange(startRow, 2, logRows.length, 3).setValues(logRows);
      SpreadsheetApp.flush();
    }

    return _json({status: 'ok', consumed: results, count: logRows.length});
  } finally {
    lock.releaseLock();
  }
}

/**
 * Cari pesanan di DATA_SALES berdasarkan No Resi (kolom B).
 * Return semua row yang match → list {sku, qty}, plus stok saat ini
 * untuk setiap SKU yang muncul (dibaca dari DATABASE_STIKER kolom G).
 *
 * Dipakai oleh fitur "Cek Stok Resi" di desktop app: operator scan barcode
 * resi, app cari di sini, lalu tampilkan ketersediaan stok per SKU.
 */
function _lookupResiWebhook(resi) {
  if (resi == null || String(resi).trim() === '') {
    return _json({status: 'error', message: 'Field "resi" kosong'});
  }
  const targetResi = String(resi).trim();

  const ss = getSS();
  const salesSheet = ss.getSheetByName(SH_SALES);
  if (!salesSheet) {
    return _json({status: 'error', message: 'Tab "' + SH_SALES + '" tidak ditemukan'});
  }

  const lastRow = salesSheet.getLastRow();
  if (lastRow < 2) {
    return _json({status: 'ok', items: [], stock: {}, count: 0});
  }

  // B = No Resi, C = ID SKU, D = Qty
  const data = salesSheet.getRange(2, 2, lastRow - 1, 3).getValues();

  const items = [];
  const skuKeys = {};
  for (let i = 0; i < data.length; i++) {
    const r = String(data[i][0] == null ? '' : data[i][0]).trim();
    if (r !== targetResi) continue;
    const sku = String(data[i][1] == null ? '' : data[i][1]).trim();
    if (!sku) continue;
    const qty = Number(data[i][2]) || 0;
    items.push({sku: sku, qty: qty});
    skuKeys[sku.toUpperCase()] = true;
  }

  // Lookup stok terkini hanya untuk SKU yg muncul di resi ini
  const stock = {};
  const dbSheet = ss.getSheetByName(SH_DATABASE);
  if (dbSheet) {
    const dbLast = dbSheet.getLastRow();
    if (dbLast >= 2) {
      const numRows = dbLast - 1;
      const dbSkus = dbSheet.getRange(2, STOCK_SKU_COL, numRows, 1).getValues();
      const dbQtys = dbSheet.getRange(2, STOCK_QTY_COL, numRows, 1).getValues();
      for (let i = 0; i < numRows; i++) {
        const k = String(dbSkus[i][0] == null ? '' : dbSkus[i][0]).trim().toUpperCase();
        if (k && skuKeys[k]) {
          const q = Number(dbQtys[i][0]);
          stock[k] = isNaN(q) ? 0 : q;
        }
      }
    }
  }

  return _json({status: 'ok', items: items, stock: stock, count: items.length});
}

/**
 * Bulk snapshot — read DATA_SALES (B,C,D) + DATABASE_STIKER (A,G) sekali jalan.
 *
 * Dipakai oleh fitur "Cek Stok Resi" di desktop app: client tarik snapshot
 * sekali saat tab dibuka / klik Refresh, lalu semua scan resi jadi lookup
 * lokal O(1) tanpa HTTP roundtrip per scan.
 *
 * Response: {
 *   status: 'ok',
 *   sales: [{resi, sku, qty}, ...],     // semua baris non-kosong
 *   stock: {SKU_UPPER: qty, ...},        // semua SKU di DATABASE_STIKER
 *   sales_count, stock_count, timestamp
 * }
 */
function _bulkSnapshotWebhook() {
  const ss = getSS();

  // ── DATA_SALES (B=Resi, C=SKU, D=Qty) ────────────────────────────────────
  const sales = [];
  const salesSheet = ss.getSheetByName(SH_SALES);
  if (salesSheet) {
    const lastRow = salesSheet.getLastRow();
    if (lastRow >= 2) {
      const data = salesSheet.getRange(2, 2, lastRow - 1, 3).getValues();
      for (let i = 0; i < data.length; i++) {
        const resi = String(data[i][0] == null ? '' : data[i][0]).trim();
        if (!resi) continue;
        const sku = String(data[i][1] == null ? '' : data[i][1]).trim();
        if (!sku) continue;
        const qty = Number(data[i][2]) || 0;
        sales.push({resi: resi, sku: sku, qty: qty});
      }
    }
  }

  // ── DATABASE_STIKER (A=ID SKU, G=Stok Saat ini) ─────────────────────────
  const stock = {};
  let stockCount = 0;
  const dbSheet = ss.getSheetByName(SH_DATABASE);
  if (dbSheet) {
    const dbLast = dbSheet.getLastRow();
    if (dbLast >= 2) {
      const numRows = dbLast - 1;
      const dbSkus = dbSheet.getRange(2, STOCK_SKU_COL, numRows, 1).getValues();
      const dbQtys = dbSheet.getRange(2, STOCK_QTY_COL, numRows, 1).getValues();
      for (let i = 0; i < numRows; i++) {
        const k = String(dbSkus[i][0] == null ? '' : dbSkus[i][0]).trim().toUpperCase();
        if (!k) continue;
        const q = Number(dbQtys[i][0]);
        stock[k] = isNaN(q) ? 0 : q;
        stockCount++;
      }
    }
  }

  return _json({
    status: 'ok',
    sales: sales,
    stock: stock,
    sales_count: sales.length,
    stock_count: stockCount,
    timestamp: Date.now(),
  });
}

function _json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
