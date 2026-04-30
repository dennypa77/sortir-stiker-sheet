"""
stock_reader.py
Baca + potong stok dari Google Sheet DATABASE_STIKER lewat Apps Script.

Endpoint Apps Script:
  GET   doGet                       → {"status":"ok","stock":{SKU:qty,...}}
  POST  action="consume_stock"      → potong stok kolom G + tulis LOG_KELUAR
                                       balas {"status":"ok",
                                              "consumed":[{sku,ok,taken,sisa},...]}

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


def consume_stock(
    webhook_url: str,
    items: list[dict],
    log_callback=None,
) -> list[dict] | None:
    """
    POST batch konsumsi stok ke Apps Script. Server akan:
      - Potong qty dari kolom G di DATABASE_STIKER per item.
      - Append (SKU, qty, ket) ke kolom B/C/D di tab LOG_KELUAR.
        Kolom A (Tanggal) dibiarkan kosong — diisi otomatis oleh formula sheet.

    Args:
        webhook_url : URL Apps Script Web App (sama dgn endpoint sync).
        items       : list of {"sku": str, "qty": int, "ket": str}.
        log_callback: fn(level, msg) untuk lapor balik ke UI.

    Return:
        list per-item result [{"sku","ok","taken","sisa","message"?}, ...]
        urutan sama dgn `items`. Length sama dgn input.
        None kalau call gagal total (network/HTTP/parse) — caller harus
        fallback ke "print semua" demi keamanan customer.
    """
    def log(level, msg):
        if log_callback:
            log_callback(level, msg)

    if not webhook_url or not webhook_url.strip():
        return None
    if not items:
        return []

    payload = json.dumps(
        {"action": "consume_stock", "items": items},
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        webhook_url.strip(),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        log("warning", f"⚠️  Gagal update stok (HTTP {e.code}: {e.reason}). Cetak semua.")
        return None
    except urllib.error.URLError as e:
        log("warning", f"⚠️  Gagal update stok (network: {e.reason}). Cetak semua.")
        return None
    except Exception as e:
        log("warning", f"⚠️  Gagal update stok ({e}). Cetak semua.")
        return None

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        log("warning", f"⚠️  Respons update stok bukan JSON: {body[:120]}")
        return None

    if data.get("status") != "ok":
        log("warning", f"⚠️  Apps Script error update stok: {data.get('message','unknown')}")
        return None

    consumed = data.get("consumed")
    if not isinstance(consumed, list):
        log("warning", "⚠️  Field 'consumed' di respons bukan array.")
        return None

    return consumed
