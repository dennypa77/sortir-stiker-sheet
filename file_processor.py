"""
file_processor.py
Logika inti Aplikasi Sortir Stiker Pack:
  - Baca Excel (Resi, SKU, Jumlah)
  - Cari file desain di folder sumber
  - Salin (duplikat) ke folder output

Mode Normal  : flat copy ke output, nama file = RESI__SKU__001.ext
Mode A3 Round: 1 file per pesanan ke output, nama file diberi label kelipatan
               yang harus diduplikat di CorelDRAW (4x untuk A5, 8x untuk A6).
               Struktur output:
                 output/
                   RESI__SKU-001-VN-A6-B__8x.ext
                   RESI__SKU-002-VN-A5-B__4x.ext
                   ...
"""

import math
import os
import re
import shutil
from datetime import date

import openpyxl

from sheets_sync import sync_orders
from stock_reader import check_stock_availability, consume_stock, fetch_stock


# ─── Konstanta ukuran ─────────────────────────────────────────────────────────
# Jumlah pcs yang muat dalam 1 lembar A3
A3_CAPACITY: dict[str, int] = {
    "A5": 4,
    "A6": 8,
}


def detect_size(sku: str) -> str | None:
    """
    Deteksi ukuran (A5/A6) dari string SKU.

    Format SKU yang didukung: 001-VN-A6-B  →  segmen ke-3 = ukuran
    Fallback: cari pola -A5 / -A6 / _A5 / _A6 di mana pun dalam string.
    Return 'A5', 'A6', atau None jika tidak dikenali.
    """
    # ── Coba parsing berbasis segmen (pisah '-' atau '_') ───────────────────
    segments = re.split(r"[-_]", sku)
    for seg in segments:
        seg_upper = seg.strip().upper()
        if seg_upper in A3_CAPACITY:
            return seg_upper

    # ── Fallback: regex bebas ────────────────────────────────────────────────
    m = re.search(r"[_\-](A[56])[_\-]?", sku, re.IGNORECASE)
    if m:
        return m.group(1).upper()

    return None


def round_up_to_capacity(qty: int, capacity: int) -> int:
    """Bulatkan qty ke kelipatan capacity terdekat (ke atas)."""
    if qty <= 0:
        return capacity
    return math.ceil(qty / capacity) * capacity


def read_pesanan(excel_path: str) -> list[dict]:
    """
    Membaca file Excel pesanan.
    Kolom A = Resi, B = SKU, C = Jumlah.
    Return list of dict: [{'resi': ..., 'sku': ..., 'qty': ..., 'row': ...}, ...]
    """
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    ws = wb.active
    pesanan = []

    for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        resi = row[0]
        sku  = row[1]
        qty  = row[2]

        # Lewati baris kosong
        if resi is None and sku is None:
            continue

        # Konversi ke string aman
        resi = str(resi).strip() if resi is not None else ""
        sku  = str(sku).strip()  if sku  is not None else ""
        try:
            qty = int(qty) if qty is not None else 1
        except (ValueError, TypeError):
            qty = 1

        if not resi or not sku:
            continue

        pesanan.append({
            "resi": resi,
            "sku":  sku,
            "qty":  qty,
            "row":  row_idx,
        })

    wb.close()
    return pesanan


def build_index(source_folder: str, log_callback=None) -> dict[str, str]:
    """
    Pre-indeks semua file di source_folder: {nama_file_lower: full_path}.
    Mempercepat pencarian untuk folder besar / cloud.
    """
    def log(level, msg):
        if log_callback:
            log_callback(level, msg)

    log("info", f"🔍 Mengindeks folder master: {source_folder} ...")
    index: dict[str, str] = {}
    for dirpath, _dirs, files in os.walk(source_folder):
        for fname in files:
            index[fname.lower()] = os.path.join(dirpath, fname)
    log("info", f"📂 Indeks selesai — {len(index)} file ditemukan.")
    return index


def find_design_from_index(sku: str, index: dict[str, str]) -> str | None:
    """Cari file di indeks berdasarkan partial match SKU (case-insensitive)."""
    sku_lower = sku.lower()
    for fname_lower, full_path in index.items():
        if sku_lower in fname_lower:
            return full_path
    return None


def sanitize_filename(name: str) -> str:
    """Menghapus karakter yang tidak valid untuk nama file/folder Windows."""
    invalid_chars = r'\/:*?"<>|'
    for ch in invalid_chars:
        name = name.replace(ch, "_")
    return name.strip()


# ─── Copy helper ──────────────────────────────────────────────────────────────

def _copy_flat(
    src_file: str,
    resi_safe: str,
    sku_safe: str,
    effective_qty: int,
    output_folder: str,
    used_names: set[str],
    log_fn,
) -> int:
    """
    Mode Normal — salin file ke root output_folder.
    Nama file: RESI__SKU__001.ext
    Return jumlah file yang berhasil disalin.
    """
    ext = os.path.splitext(src_file)[1]
    copied = 0
    for copy_num in range(1, effective_qty + 1):
        base_name  = f"{resi_safe}__{sku_safe}__{copy_num:03d}{ext}"
        final_name = base_name
        collision  = 1
        while final_name in used_names:
            final_name = f"{resi_safe}__{sku_safe}__{copy_num:03d}_{collision}{ext}"
            collision += 1

        used_names.add(final_name)
        dst = os.path.join(output_folder, final_name)
        try:
            shutil.copy2(src_file, dst)
            copied += 1
        except Exception as e:
            log_fn("error", f"❌ Gagal salin copy {copy_num}: {e}")
    return copied


def _copy_with_multiplier(
    src_file: str,
    resi_safe: str,
    sku_safe: str,
    multiplier: int,
    output_folder: str,
    used_names: set[str],
    log_fn,
) -> int:
    """
    Mode Pembulatan A3 — salin 1 file ke root output_folder dengan label kelipatan.
    Nama file: RESI__SKU__{N}x.ext  (operator duplikat N kali di CorelDRAW).
    Return 1 jika berhasil, 0 jika gagal.
    """
    ext        = os.path.splitext(src_file)[1]
    base_name  = f"{resi_safe}__{sku_safe}__{multiplier}x{ext}"
    final_name = base_name
    collision  = 1
    while final_name in used_names:
        final_name = f"{resi_safe}__{sku_safe}__{multiplier}x_{collision}{ext}"
        collision += 1

    used_names.add(final_name)
    dst = os.path.join(output_folder, final_name)
    try:
        shutil.copy2(src_file, dst)
        return 1
    except Exception as e:
        log_fn("error", f"❌ Gagal salin file: {e}")
        return 0


# ─── Fungsi utama ─────────────────────────────────────────────────────────────

def process_orders(
    source_folder: str,
    excel_path: str,
    output_folder: str,
    mode: str = "normal",           # "normal" | "a3_round"
    progress_callback=None,          # fn(current, total)
    log_callback=None,               # fn(level, message)
    webhook_url: str = "",           # Apps Script Web App URL — kosong = skip sync
) -> dict:
    """
    Proses utama:
      1. Bersihkan folder output
      2. Baca Excel
      3. Bangun indeks master desain
      4. Cari & salin setiap file desain sesuai mode

    Mode Normal  → copy flat ke output (RESI__SKU__001.ext)
    Mode A3 Round → 1 file per pesanan dengan label kelipatan (RESI__SKU__8x.ext)

    Return ringkasan dict.
    """

    def log(level, msg):
        if log_callback:
            log_callback(level, msg)

    def progress(cur, total):
        if progress_callback:
            progress_callback(cur, total)

    # ── 1. Bersihkan output ──────────────────────────────────────────────────
    if os.path.exists(output_folder):
        log("info", f"🗑️  Membersihkan folder output: {output_folder}")
        for item in os.listdir(output_folder):
            item_path = os.path.join(output_folder, item)
            try:
                if os.path.isfile(item_path) or os.path.islink(item_path):
                    os.unlink(item_path)
                elif os.path.isdir(item_path):
                    shutil.rmtree(item_path)
            except Exception as e:
                log("warning", f"⚠️  Gagal hapus {item_path}: {e}")
    else:
        os.makedirs(output_folder, exist_ok=True)

    # ── Tampilkan mode aktif ─────────────────────────────────────────────────
    if mode == "a3_round":
        log("info",
            "⚙️  Mode: Pembulatan A3  "
            "(A5 → label 4x | A6 → label 8x)  "
            "· 1 file per pesanan, duplikat di CorelDRAW")
    else:
        log("info", "⚙️  Mode: Normal  (jumlah copy = jumlah order)  · Output flat")

    # ── 2. Baca Excel ────────────────────────────────────────────────────────
    log("info", f"📋 Membaca file pesanan: {excel_path}")
    try:
        pesanan_list = read_pesanan(excel_path)
    except Exception as e:
        log("error", f"❌ Gagal membaca Excel: {e}")
        return {"total": 0, "berhasil": 0, "tidak_ditemukan": [], "berhasil_list": []}

    if not pesanan_list:
        log("warning", "⚠️  Tidak ada data pesanan yang valid di Excel.")
        return {"total": 0, "berhasil": 0, "tidak_ditemukan": [], "berhasil_list": []}

    log("info", f"📦 Total pesanan: {len(pesanan_list)} baris")

    # ── Cek stok di DATABASE_STIKER + bikin plan konsumsi gudang ───────────
    # Plan: untuk setiap pesanan tentukan from_stock (ambil dari gudang) +
    # to_print (cetak ulang). Kalau seluruh qty bisa diambil dari stok,
    # to_print=0 → file desain tidak diduplikasi sama sekali.
    stock_map: dict[str, int] = {}
    try:
        stock_map = fetch_stock(webhook_url, log_callback)
        check_stock_availability(stock_map, pesanan_list, log_callback)
    except Exception as e:
        log("warning", f"⚠️  Cek stok gagal tak terduga: {e}")

    plan: list[dict] = []
    working_stock = dict(stock_map)
    for p in pesanan_list:
        qty = p["qty"]
        sku_key = p["sku"].strip().upper()
        avail = working_stock.get(sku_key, 0)
        from_stock = min(qty, avail) if avail > 0 else 0
        if from_stock > 0:
            working_stock[sku_key] = avail - from_stock
        plan.append({
            "pesanan":    p,
            "from_stock": from_stock,
            "to_print":   qty - from_stock,
        })

    # ── Konsumsi stok ke Apps Script (server-of-truth) ──────────────────────
    items = []
    plan_idx_for_item: list[int] = []
    for i, entry in enumerate(plan):
        if entry["from_stock"] > 0:
            items.append({
                "sku": entry["pesanan"]["sku"],
                "qty": entry["from_stock"],
                "ket": entry["pesanan"]["resi"],
            })
            plan_idx_for_item.append(i)

    if items:
        log("info", f"🏪 Mengambil {sum(it['qty'] for it in items)} pcs dari gudang "
                    f"({len(items)} pesanan) — update DATABASE_STIKER + LOG_KELUAR...")
        try:
            results = consume_stock(webhook_url, items, log_callback)
        except Exception as e:
            log("warning", f"⚠️  Update stok gagal tak terduga: {e}. Cetak semua.")
            results = None

        if results is None:
            # Total failure — fallback: cetak semua
            for entry in plan:
                entry["to_print"]   = entry["pesanan"]["qty"]
                entry["from_stock"] = 0
        else:
            taken_total = 0
            for idx_item, res in enumerate(results):
                pidx  = plan_idx_for_item[idx_item]
                entry = plan[pidx]
                if res.get("ok"):
                    taken_total += int(res.get("taken", 0))
                else:
                    # Server tolak (stok ternyata kurang / SKU tak ada) →
                    # rollback ke "cetak semua qty" untuk pesanan ini.
                    log("warning",
                        f"⚠️  [{entry['pesanan']['sku']}] tidak bisa dipotong "
                        f"({res.get('message','unknown')}) — cetak {entry['pesanan']['qty']} pcs.")
                    entry["to_print"]   = entry["pesanan"]["qty"]
                    entry["from_stock"] = 0
            if taken_total > 0:
                log("success", f"✅ Stok terpotong {taken_total} pcs di DATABASE_STIKER + LOG_KELUAR.")

    # ── Sync ke Google Sheet (sebelum copy, supaya log penjualan tetap masuk
    #    walau copy file gagal di tengah jalan) ──────────────────────────────
    try:
        sync_orders(webhook_url, pesanan_list, date.today().isoformat(), log_callback)
    except Exception as e:
        log("warning", f"⚠️  Sync Google Sheet gagal tak terduga: {e}")

    # Deteksi duplikat resi (peringatan saja, tetap diproses)
    resi_count: dict[str, int] = {}
    for p in pesanan_list:
        resi_count[p["resi"]] = resi_count.get(p["resi"], 0) + 1
    for resi, count in resi_count.items():
        if count > 1:
            log("warning", f"⚠️  Resi [{resi}] muncul {count}x — semua akan diproses")

    # ── 3. Bangun indeks master ──────────────────────────────────────────────
    try:
        file_index = build_index(source_folder, log_callback)
    except Exception as e:
        log("error", f"❌ Gagal mengindeks folder sumber: {e}")
        return {"total": 0, "berhasil": 0, "tidak_ditemukan": [], "berhasil_list": []}

    # ── 4. Proses setiap pesanan ─────────────────────────────────────────────
    total           = len(pesanan_list)
    berhasil        = 0
    dari_gudang     = 0          # pesanan yang fully terlayani gudang (to_print=0)
    tidak_ditemukan = []
    berhasil_list   = []
    used_names: set[str] = set()   # anti-collision nama file di mode normal & a3_round

    for idx, entry in enumerate(plan, start=1):
        pesanan    = entry["pesanan"]
        from_stock = entry["from_stock"]
        to_print   = entry["to_print"]
        resi = pesanan["resi"]
        sku  = pesanan["sku"]
        qty  = pesanan["qty"]

        progress(idx, total)

        # ── Pesanan fully terlayani gudang → tidak perlu cari/copy file ─────
        if from_stock > 0 and to_print == 0:
            berhasil   += 1
            dari_gudang += 1
            berhasil_list.append({
                "resi":       resi,
                "sku":        sku,
                "qty_order":  qty,
                "qty_copied": 0,
                "from_stock": from_stock,
                "multiplier": None,
                "src":        None,
            })
            log("success",
                f"📦 Ambil {from_stock} dari gudang | Resi: {resi} | SKU: {sku}  "
                f"(file desain tidak diduplikasi)")
            continue

        # ── Sebagian / semua harus dicetak ──────────────────────────────────
        if from_stock > 0:
            log("info",
                f"📦 [{sku}] ambil {from_stock}/{qty} dari gudang, "
                f"sisa {to_print} dicetak | Resi: {resi}")

        # ── Tentukan jumlah copy untuk yang dicetak ─────────────────────────
        if mode == "a3_round":
            size = detect_size(sku)
            if size is None:
                log("warning",
                    f"⚠️  Ukuran tidak terdeteksi pada SKU [{sku}]  "
                    f"→ pastikan SKU mengandung segmen 'A5' atau 'A6' (contoh: 001-VN-A6-B). "
                    f"Menggunakan qty cetak ({to_print}).")
                effective_qty = to_print
            else:
                capacity      = A3_CAPACITY[size]
                effective_qty = round_up_to_capacity(to_print, capacity)
                if effective_qty != to_print:
                    log("info",
                        f"🔄 [{sku}]  ukuran {size}  →  {to_print} dibulatkan ke "
                        f"{effective_qty} (kelipatan {capacity})")
                else:
                    log("info",
                        f"✔  [{sku}]  ukuran {size}  →  {to_print} sudah pas (kelipatan {capacity})")
        else:
            effective_qty = to_print

        # ── Cari file desain ─────────────────────────────────────────────────
        src_file = find_design_from_index(sku, file_index)

        if src_file is None:
            log("error", f"❌ Tidak ditemukan | Resi: {resi} | SKU: {sku}")
            tidak_ditemukan.append({"resi": resi, "sku": sku})
            continue

        resi_safe = sanitize_filename(resi)
        sku_safe  = sanitize_filename(sku)

        # ── Salin file ───────────────────────────────────────────────────────
        if mode == "a3_round":
            copied_count = _copy_with_multiplier(
                src_file, resi_safe, sku_safe, effective_qty,
                output_folder, used_names, log
            )
        else:
            copied_count = _copy_flat(
                src_file, resi_safe, sku_safe, effective_qty,
                output_folder, used_names, log
            )

        if copied_count > 0:
            berhasil += 1
            berhasil_list.append({
                "resi":       resi,
                "sku":        sku,
                "qty_order":  qty,
                "qty_copied": copied_count,
                "from_stock": from_stock,
                "multiplier": effective_qty if mode == "a3_round" else None,
                "src":        src_file,
            })

            stock_note = f" (+{from_stock} dari gudang)" if from_stock > 0 else ""
            extra = f" (dibulatkan dari {to_print})" if effective_qty != to_print else ""
            if mode == "a3_round":
                log("success",
                    f"✅ Label {effective_qty}x{extra}{stock_note} | Resi: {resi} | SKU: {sku}  "
                    f"← {os.path.basename(src_file)}")
            else:
                label = f"{copied_count}x" if copied_count > 1 else "1x"
                log("success",
                    f"✅ {label}{extra}{stock_note} | Resi: {resi} | SKU: {sku}  "
                    f"← {os.path.basename(src_file)}")

    # ── 5. Ringkasan ─────────────────────────────────────────────────────────
    progress(total, total)
    log("info", "─" * 60)
    log("info",
        f"📊 RINGKASAN: {berhasil} berhasil | "
        f"{dari_gudang} dari gudang (tanpa copy) | "
        f"{len(tidak_ditemukan)} tidak ditemukan | "
        f"Total {total} pesanan")

    if tidak_ditemukan:
        log("warning", "📋 SKU tidak ditemukan:")
        for td in tidak_ditemukan:
            log("warning", f"   • [{td['resi']}] {td['sku']}")

    return {
        "total":           total,
        "berhasil":        berhasil,
        "dari_gudang":     dari_gudang,
        "tidak_ditemukan": tidak_ditemukan,
        "berhasil_list":   berhasil_list,
    }
