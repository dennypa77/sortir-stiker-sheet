"""
resi_checker.py
Lookup pesanan berdasarkan No Resi via Apps Script.

Endpoint Apps Script:
  POST  action="lookup_resi"  body={"resi": "<no_resi>"}
        → {"status":"ok",
           "items":[{"sku":..., "qty":...}, ...],
           "stock":{"SKU_UPPER": qty_int, ...}}

Kontrak log_callback sama dgn modul lain di project ini:
  log_callback(level, message)  level ∈ {"success","error","warning","info"}
"""

import json
import urllib.error
import urllib.request


TIMEOUT_SECONDS = 30


def lookup_resi(webhook_url: str, resi: str, log_callback=None) -> dict | None:
    """
    Cari pesanan dengan No Resi = `resi` di tab DATA_SALES.

    Args:
        webhook_url  : URL Apps Script Web App. Kosong = return None.
        resi         : No Resi yang dicari (case + spasi di-strip server-side).
        log_callback : fn(level, msg) untuk lapor balik ke UI.

    Return:
        {"items":[{"sku","qty"}], "stock":{SKU_UPPER: int}} kalau sukses.
        None kalau call gagal (network/HTTP/parse) — caller harus tampilkan
        warning ke operator, bukan crash.

        items kosong kalau resi tidak ditemukan di DATA_SALES (bukan error).
    """
    def log(level, msg):
        if log_callback:
            log_callback(level, msg)

    if not webhook_url or not webhook_url.strip():
        log("warning", "⚠️  Webhook Google Sheet belum dikonfigurasi.")
        return None

    resi_clean = str(resi or "").strip()
    if not resi_clean:
        return {"items": [], "stock": {}}

    payload = json.dumps(
        {"action": "lookup_resi", "resi": resi_clean},
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
        log("error", f"❌ Gagal lookup resi (HTTP {e.code}: {e.reason}).")
        return None
    except urllib.error.URLError as e:
        log("error", f"❌ Gagal lookup resi (network: {e.reason}).")
        return None
    except Exception as e:
        log("error", f"❌ Gagal lookup resi ({e}).")
        return None

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        log("error", f"❌ Respons lookup_resi bukan JSON: {body[:120]}")
        return None

    if data.get("status") != "ok":
        log("error", f"❌ Apps Script error: {data.get('message','unknown')}")
        return None

    raw_items = data.get("items") or []
    raw_stock = data.get("stock") or {}

    # Normalisasi items
    items: list[dict] = []
    for it in raw_items:
        sku_raw = str(it.get("sku", "")).strip() if isinstance(it, dict) else ""
        if not sku_raw:
            continue
        try:
            qty = int(it.get("qty", 0)) if isinstance(it, dict) else 0
        except (ValueError, TypeError):
            qty = 0
        items.append({"sku": sku_raw, "qty": qty})

    # Normalisasi stock: key uppercase + strip, value int
    stock: dict[str, int] = {}
    if isinstance(raw_stock, dict):
        for k, v in raw_stock.items():
            key = str(k).strip().upper()
            if not key:
                continue
            try:
                stock[key] = int(v)
            except (ValueError, TypeError):
                stock[key] = 0

    return {"items": items, "stock": stock}
