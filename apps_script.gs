/**
 * Sortir Stiker Pack — Sales Sync Webhook
 * ─────────────────────────────────────────
 * Paste seluruh file ini ke Apps Script editor (Extensions → Apps Script)
 * di Google Sheet target, lalu Deploy → New deployment → Web app:
 *   - Description : Sortir Stiker Pack Sync
 *   - Execute as  : Me (akun pemilik sheet)
 *   - Who has access : Anyone with the link  (atau "Anyone" — yg penting URL bisa di-POST tanpa auth)
 *
 * Copy URL deployment, paste ke field "Webhook Google Sheet" di aplikasi.
 *
 * Re-deploy (Manage deployments → edit → New version) setelah edit script ini —
 * URL deployment lama tidak otomatis dapat versi baru.
 */

const SHEET_NAME = 'DATA_SALES';
const EXPECTED_HEADER = ['Tanggal', 'No Resi', 'ID SKU', 'Qty'];

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

function doGet() {
  return _json({status: 'ok', message: 'Sortir Stiker Pack webhook is alive. Use POST.'});
}

function _json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
