"""
stock_reader.py
Baca data stok dari Google Sheet DATABASE_STIKER lewat Apps Script doGet.

Endpoint Apps Script (apps_script.gs::doGet) balikin:
    {"status": "ok", "stock": {"SKU1": 10, "SKU2": 5, ...}, "count": 42}

Aplikasi pakai data ini untuk peringatan kalau stok kurang sebelum sortir
diproses. Tidak memblokir — hanya log warning supaya operator sadar.

Tidak boleh import UI — komunikasi balik ke layer atas via log_callback
dengan kontrak yang sama dipakai file_processor.py:
  log_callback(level, message)  level ∈ {"success","error","warning","info"}
"""

import json
import urllib.error
import urllib.request


TIMEOUT_SECONDS = 30


def fetch_stock(webhook_url: str, log_callback=None) -> dict[str, int]:
    """
    GET stok terkini per SKU dari Apps Script.

    Args:
        webhook_url   : URL Web App (sama dgn yang dipakai sheets_sync).
                        Kalau kosong, return dict kosong (skip silent).
        log_callback  : fn(level, msg) untuk lapor balik ke UI.

    Return: dict {sku_uppercase: qty_int}. Empty kalau gagal / tidak diset.
    """
    def log(level, msg):
        if log_callback:
            log_callback(level, msg)

    if not webhook_url or not webhook_url.strip():
        return {}

    log("info", "📦 Membaca stok dari DATABASE_STIKER...")

    try:
        req = urllib.request.Request(webhook_url.strip(), method="GET")
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        log("warning", f"⚠️  Gagal baca stok (HTTP {e.code}: {e.reason}). Cek stok dilewati.")
        return {}
    except urllib.error.URLError as e:
        log("warning", f"⚠️  Gagal baca stok (network: {e.reason}). Cek stok dilewati.")
        return {}
    except Exception as e:
        log("warning", f"⚠️  Gagal baca stok ({e}). Cek stok dilewati.")
        return {}

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        # Apps Script kadang balikin halaman HTML kalau URL salah / belum deploy
        log("warning", f"⚠️  Respons stok bukan JSON (cek URL deployment): {body[:120]}")
        return {}

    if data.get("status") != "ok":
        log("warning", f"⚠️  Apps Script error: {data.get('message', 'unknown')}")
        return {}

    raw = data.get("stock") or {}
    if not isinstance(raw, dict):
        log("warning", "⚠️  Field 'stock' di respons bukan object.")
        return {}

    # Normalisasi: key uppercase + strip, value int (force ke 0 kalau tidak valid)
    result: dict[str, int] = {}
    for k, v in raw.items():
        key = str(k).strip().upper()
        if not key:
            continue
        try:
            result[key] = int(v)
        except (ValueError, TypeError):
            result[key] = 0

    log("success", f"✅ Stok dimuat: {len(result)} SKU dari DATABASE_STIKER")
    return result


def check_stock_availability(
    stock_map: dict[str, int],
    pesanan_list: list[dict],
    log_callback=None,
) -> None:
    """
    Periksa setiap pesanan terhadap stok terkini. Log warning untuk:
      - SKU yang tidak ada di DATABASE_STIKER
      - SKU yang stoknya kurang (akumulasi qty kalau ada multiple pesanan)

    Tidak memblokir — sortir tetap lanjut. Tujuannya cuma peringatan visual
    supaya operator tahu mana yang perlu produksi tambahan.
    """
    def log(level, msg):
        if log_callback:
            log_callback(level, msg)

    if not stock_map:
        # Kosong = fetch gagal / belum konfigur. Skip diam-diam.
        return

    consumed: dict[str, int] = {}
    not_in_db: list[str] = []
    seen_missing: set[str] = set()

    for p in pesanan_list:
        sku_raw = str(p.get("sku", "")).strip()
        if not sku_raw:
            continue
        key = sku_raw.upper()
        qty = p.get("qty", 0) or 0

        if key not in stock_map:
            if key not in seen_missing:
                seen_missing.add(key)
                not_in_db.append(sku_raw)
            continue

        consumed[key] = consumed.get(key, 0) + qty

    insufficient: list[tuple[str, int, int]] = []
    for sku_key, total_needed in consumed.items():
        available = stock_map[sku_key]
        if total_needed > available:
            insufficient.append((sku_key, total_needed, available))

    if not_in_db:
        log("warning", f"⚠️  {len(not_in_db)} SKU tidak ada di DATABASE_STIKER:")
        for sku in not_in_db:
            log("warning", f"   • {sku}")

    if insufficient:
        log("warning",
            f"⚠️  {len(insufficient)} SKU stok kurang (sortir tetap diproses):")
        for sku, needed, avail in insufficient:
            log("warning", f"   • {sku}: butuh {needed}, sisa {avail}")

    if not not_in_db and not insufficient:
        log("success", "✅ Semua SKU pesanan tersedia di stok DATABASE_STIKER.")
