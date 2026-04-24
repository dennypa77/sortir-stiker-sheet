"""
sheets_sync.py
Kirim data penjualan ke Google Sheet via Apps Script Web App.

Kalau pengiriman gagal (internet putus / Apps Script error), data di-buffer
ke `.pending_sales.json` lalu di-retry otomatis di run berikutnya.

Tidak boleh import UI — komunikasi balik ke layer atas via log_callback
dengan kontrak yang sama dipakai file_processor.py:
  log_callback(level, message)  level ∈ {"success","error","warning","info"}
"""

import json
import os
import urllib.error
import urllib.request


PENDING_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".pending_sales.json"
)
TIMEOUT_SECONDS = 30


# ─── Buffer helpers ──────────────────────────────────────────────────────────

def _load_pending() -> list[dict]:
    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_pending(rows: list[dict]) -> None:
    try:
        with open(PENDING_FILE, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _clear_pending() -> None:
    try:
        if os.path.exists(PENDING_FILE):
            os.unlink(PENDING_FILE)
    except Exception:
        pass


# ─── HTTP ────────────────────────────────────────────────────────────────────

def _post(webhook_url: str, rows: list[dict]) -> tuple[bool, str]:
    """POST JSON ke Apps Script. Return (ok, message)."""
    payload = json.dumps({"rows": rows}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return False, f"Network error: {e.reason}"
    except Exception as e:
        return False, f"Error tak terduga: {e}"

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        # Apps Script kadang balikin halaman HTML kalau URL salah / belum deploy
        return False, f"Respons bukan JSON (cek URL deployment): {body[:150]}"

    if data.get("status") == "ok":
        return True, f"{data.get('written', len(rows))} baris ditulis"
    return False, f"Apps Script: {data.get('message', body[:150])}"


# ─── Public API ──────────────────────────────────────────────────────────────

def sync_orders(
    webhook_url: str,
    pesanan_list: list[dict],
    today_date: str,
    log_callback=None,
) -> None:
    """
    Kirim `pesanan_list` (+ buffer pending kalau ada) ke Google Sheet.

    Args:
        webhook_url   : URL Apps Script Web App. Kalau kosong, sync di-skip.
        pesanan_list  : list dict dengan minimal key 'resi','sku','qty'.
        today_date    : string tanggal, format bebas (rekomendasi 'YYYY-MM-DD').
        log_callback  : fn(level, msg) untuk lapor balik ke UI.
    """
    def log(level, msg):
        if log_callback:
            log_callback(level, msg)

    if not webhook_url or not webhook_url.strip():
        log("info", "ℹ️  Webhook Google Sheet kosong — sinkronisasi dilewati.")
        return

    new_rows = [
        {
            "tanggal": today_date,
            "resi":    p.get("resi", ""),
            "sku":     p.get("sku", ""),
            "qty":     p.get("qty", 0),
        }
        for p in pesanan_list
    ]

    pending = _load_pending()
    all_rows = pending + new_rows

    if not all_rows:
        return

    if pending:
        log("info",
            f"☁️  Mengirim ke Google Sheet: {len(new_rows)} baris baru "
            f"+ {len(pending)} dari buffer lama...")
    else:
        log("info", f"☁️  Mengirim {len(new_rows)} baris ke Google Sheet...")

    ok, msg = _post(webhook_url.strip(), all_rows)

    if ok:
        log("success", f"✅ Google Sheet ter-update — {msg}")
        _clear_pending()
    else:
        _save_pending(all_rows)
        log("warning",
            f"⚠️  Gagal kirim ke Google Sheet ({msg}). "
            f"{len(all_rows)} baris di-buffer, akan retry di run berikutnya.")
