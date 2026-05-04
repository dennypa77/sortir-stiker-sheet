# Sortir Stiker Pack

Aplikasi desktop untuk **otomatisasi sortir desain stiker** berdasarkan pesanan harian, terintegrasi dengan **WMS (Warehouse Management System)** di Google Sheet.

Operator update Excel pesanan → klik tombol → aplikasi cari file desain di folder cloud, potong stok yang ada di gudang, copy file yang perlu dicetak ke folder output, dan log seluruh transaksi ke Google Sheet.

---

## Daftar Isi

1. [Gambaran Sistem](#1-gambaran-sistem)
2. [Persyaratan](#2-persyaratan)
3. [Setup Pertama Kali](#3-setup-pertama-kali)
4. [SOP Harian — Operator](#4-sop-harian--operator)
5. [Tab & Fitur](#5-tab--fitur)
6. [Format Data](#6-format-data)
7. [Auto-Update](#7-auto-update)
8. [Troubleshooting](#8-troubleshooting)
9. [File & Folder](#9-file--folder)
10. [Untuk Admin / Developer](#10-untuk-admin--developer)

---

## 1. Gambaran Sistem

```
┌────────────────┐         ┌──────────────────┐
│ Excel Pesanan  │         │  Folder Cloud    │
│ pesanan_*.xlsx │         │  CDR / Desain    │
└───────┬────────┘         └─────────┬────────┘
        │ baca                       │ copy
        ▼                            ▼
   ┌──────────────────────────────────────┐
   │   APLIKASI SORTIR (Python/Tkinter)   │
   │  - Cek stok                          │
   │  - Sortir & copy file desain         │
   │  - Verifikasi via scanner barcode    │
   └────┬─────────────────────────┬───────┘
        │ webhook                 │ output
        ▼                         ▼
   ┌──────────────────────┐  ┌─────────────┐
   │ Google Sheet (WMS)   │  │ Folder      │
   │ - DATABASE_STIKER    │  │ Output      │
   │ - DATA_SALES         │  │ (siap cetak)│
   │ - LOG_KELUAR         │  └─────────────┘
   │ - LOG_MASUK          │
   │ - STOK_OPNAME        │
   └──────────────────────┘
```

**Komponen:**
- **Aplikasi desktop** (`app.py`) — GUI Tkinter, jalan di workstation operator
- **Apps Script Web App** (`apps_script.gs`) — backend di Google Sheet, expose 4 endpoint
- **GitHub Releases** — distribusi update (auto-applied saat operator buka aplikasi)

---

## 2. Persyaratan

| Komponen | Keterangan |
|---|---|
| OS | Windows 10 / 11 |
| Python | 3.10+ (dibundel di `.venv` saat pertama kali `run.bat`) |
| Internet | Wajib — untuk webhook Google Sheet + auto-update |
| Folder cloud | Berisi semua file desain (CDR/AI/PNG/dst). Contoh: Google Drive di-mount sebagai drive `H:\` |
| Google Sheet | Tab wajib: `DATABASE_STIKER`, `DATA_SALES`, `LOG_KELUAR`. Tab tambahan dipakai fitur Kelola Gudang: `LOG_MASUK`, `STOK_OPNAME` |
| Scanner barcode | Opsional — bisa pakai keyboard manual + Enter |

Satu-satunya runtime Python dependency: **`openpyxl`** (auto-install via `run.bat`).

---

## 3. Setup Pertama Kali

### 3.1. Setup Google Sheet (admin sheet)

1. Buka Google Sheet WMS yang sudah ada (DATABASE_STIKER, DATA_SALES, LOG_KELUAR sudah ter-setup).
2. **Extensions → Apps Script** → buka editor.
3. Copy seluruh isi `apps_script.gs` dari repo, paste menimpa kode lama → **Save** (Ctrl+S).
4. **Deploy → New deployment** (kalau belum pernah) atau **Deploy → Manage deployments** (kalau sudah ada):
   - Type: **Web app**
   - Execute as: **Me**
   - Who has access: **Anyone with the link** (atau "Anyone" — internal-only kalau Google Workspace)
   - Klik **Deploy**
5. **Salin URL Web App** yang muncul. Format: `https://script.google.com/macros/s/AKfy.../exec`

> **Penting:** Setiap kali `apps_script.gs` di-update di repo, sheet admin harus **redeploy**: Manage deployments → ⚙ → Edit → Version: New version → Deploy. URL deployment **tidak berubah**, jadi workstation operator tidak perlu setting ulang.

### 3.2. Setup Workstation Operator

1. Clone / download repo project ke folder lokal (mis. `D:\Project\Sortir Stiker Pack`).
2. Pastikan folder cloud desain sudah ter-mount (Google Drive Desktop, dll).
3. Double-click `run.bat` — pertama kali akan bootstrap `.venv` (~30 detik).
4. Setelah GUI muncul, klik tab **⚙ Konfigurasi**:

   | Field | Isi dengan |
   |---|---|
   | 📁 Folder Sumber Desain | Folder cloud berisi file desain (mis. `H:/My Drive/STIKER PACK PREMIUM/CDR MENTAH`) |
   | 📋 File Pesanan Excel | Path ke file Excel pesanan harian (`.xlsx`) |
   | 📤 Folder Output | Folder kosong untuk hasil sortir — **jangan pilih folder berisi data penting** karena akan di-wipe setiap run |
   | 🔗 Webhook Google Sheet | URL Apps Script Web App dari step 3.1 |

   Semua field auto-save saat di-edit.

5. Pindah ke tab **▶ Eksekusi**, sistem siap dipakai.

> **Untuk shortcut tanpa console window:** pakai `run.vbs` (double-click). Behaviornya sama dengan `run.bat`, tapi tidak buka jendela cmd hitam.

---

## 4. SOP Harian — Operator

### 4.1. Workflow Utama: Sortir Pesanan

```
1. Update Excel pesanan harian
        ↓
2. Buka aplikasi (run.bat atau run.vbs)
        ↓
3. Tab ▶ Eksekusi → cek mode + checkbox Auto Potong Stok
        ↓
4. Klik ▶ MULAI SORTIR
        ↓
5. Tunggu ringkasan (3 berhasil | 1 dari gudang | 0 tidak ditemukan)
        ↓
6. Klik 📂 Folder Output → ambil file → cetak
        ↓
7. (Opsional) Tab 🔎 Cek Stok Resi → scan resi yang sudah dicetak untuk verifikasi
```

**Detail langkah:**

1. **Update Excel pesanan harian** dengan format:

   | A (No Resi) | B (ID SKU) | C (Jumlah) |
   |---|---|---|
   | REF0001234567890 | 001-VN-A6-A | 5 |

   Header di row 1, data mulai row 2. Kolom selain A/B/C diabaikan.

2. **Buka aplikasi** — `run.bat` atau `run.vbs` (atau shortcut desktop).

3. **Tab ▶ Eksekusi**, perhatikan:
   - **Mode Output:**
     - **Mode Normal** — file di-copy N kali sesuai qty (mis. qty 3 → 3 file di output)
     - **Mode Pembulatan A3** — 1 file dengan label kelipatan A3 (`A5 → 4x`, `A6 → 8x`), operator duplikat di CorelDRAW
   - **Auto Potong Stok** ✓ — default sudah tercentang. Centang artinya: SKU yang ada stoknya di DATABASE_STIKER akan diambil dari gudang dulu, sisanya baru dicetak. Tulis ke LOG_KELUAR otomatis.

4. **Klik ▶ MULAI SORTIR.** Aplikasi akan:
   1. Cek update GitHub (kalau ada update, restart otomatis)
   2. Bersihkan folder Output
   3. Baca Excel pesanan
   4. Tarik stok terkini dari DATABASE_STIKER
   5. Untuk SKU dengan stok cukup → ambil dari gudang (potong stok kolom G via append ke LOG_KELUAR), sisanya cetak
   6. Untuk SKU stok kurang → cetak semuanya
   7. Cari file desain di folder sumber (substring match SKU di nama file, case-insensitive)
   8. Copy ke folder Output dengan format nama `RESI__SKU__001.ext`
   9. Sync seluruh pesanan ke DATA_SALES (untuk audit trail)

5. **Cek hasilnya:**
   - **Tab Log Proses** — log lengkap setiap pesanan
   - **Tab Log Gudang** — khusus pesanan yang berhasil diambil dari gudang
   - **Status bar** atas log: `✅ X berhasil | 📦 Y dari gudang | ❌ Z tidak ditemukan | N total`

6. **Klik 📂 Folder Output** → file desain siap dicetak. Format nama:
   - Mode Normal: `RESI__SKU__001.ext`, `RESI__SKU__002.ext`, ...
   - Mode A3: `RESI__SKU__8x.ext` (operator duplikat 8x di CorelDRAW)

7. **Setelah cetak**, kalau perlu verifikasi resi sebelum kirim → buka tab **🔎 Cek Stok Resi** dan scan resi (lihat 4.2).

### 4.2. Workflow Verifikasi: Cek Stok via Scanner

```
1. Tab 🔎 Cek Stok Resi
        ↓
2. Tunggu status "✅ Snapshot dimuat" (~1-2 detik, sekali per buka tab)
        ↓
3. Scan barcode resi (atau ketik manual + Enter)
        ↓
4. Hasil instan: tiap SKU di resi tsb, status stok di gudang
        ↓
5. (Kalau data sheet berubah) klik 🔄 Refresh
```

**Catatan workflow:**
- Tab ini **READ-ONLY** — hanya tampilkan ketersediaan, **tidak menulis** ke LOG_KELUAR. Auto-potong stok hanya terjadi via tab Eksekusi.
- Cache dimuat sekali saat tab pertama kali dibuka (atau saat klik Refresh). Setiap scan setelah itu **instan** karena lookup di RAM, bukan HTTP.
- Klik **🔄 Refresh** kalau ada operator lain yang baru klik Mulai Sortir di workstation lain (DATA_SALES bertambah baris).

**Format hasil scan:**

```
📋  RESI: REF0001234567890
──────────────────────────────────────────────────────────
  ✅ 001-VN-A6-A  butuh 2  →  STOK TERSEDIA 15
  ⚠️  141-VN-A5-B  butuh 5  →  STOK CUMA 3  [kurang]
  ❌ 999-VN-XX-Z  butuh 1  →  TIDAK ADA di DATABASE_STIKER
```

---

## 5. Tab & Fitur

### Tab ⚙ Konfigurasi

Set 4 path + webhook URL. Auto-save tiap perubahan.

### Tab ▶ Eksekusi (workflow harian utama)

- **Mode Output**: pilih Normal / Pembulatan A3 (klik kartu).
- **Auto Potong Stok**: checkbox di atas progress bar.
  - Default **ON setiap launch** (tidak persisted ke config — sengaja, supaya operator selalu dapat default yang aman).
  - Toggle off hanya berlaku untuk session berjalan. Launch berikutnya kembali ON.
- **▶ MULAI SORTIR**: tombol utama.
- **📂 Folder Output**: shortcut buka folder Output di File Explorer.
- **Bersihkan Log**: clear tab Log Proses & Log Gudang.
- **Sub-tab Log Proses**: log lengkap selama sortir.
- **Sub-tab Log Gudang**: ringkasan SKU yang diambil dari gudang.

### Tab 🔎 Cek Stok Resi (verifikasi)

- **Status cache** (atas): jumlah pesanan + SKU + waktu fetch.
- **🔄 Refresh**: re-pull snapshot dari Google Sheet.
- **Input scanner**: auto-focus saat tab dibuka. Scanner barcode auto-Enter langsung trigger lookup.
- **Hasil scan**: kronologis, latest di bawah. Tiap scan punya header `📋 RESI: ...` lalu list per SKU.
- **Bersihkan**: clear hasil scan.

---

## 6. Format Data

### Excel Pesanan

Hardcoded kolom **A=Resi, B=SKU, C=Jumlah**, mulai row 2.

| A (No Resi) | B (ID SKU) | C (Jumlah) |
|---|---|---|
| REF0001234567890 | 001-VN-A6-A | 5 |
| REF0009876543210 | 141-VN-A5-B | 2 |

Baris kosong di-skip. Kolom lain diabaikan. Excel dibaca dengan `data_only=True` (formula tanpa cached value akan jadi `None`).

### Google Sheet — DATA_SALES

| A (Tanggal) | B (No Resi) | C (ID SKU) | D (Qty) |
|---|---|---|---|
| =formula_tanggal | REF000... | 001-VN-A6-A | 5 |

Aplikasi tulis B/C/D saja. Kolom A diisi formula sheet (TODAY/NOW/dll) — **jangan diganggu**.

### Google Sheet — DATABASE_STIKER

Kolom yang dipakai aplikasi:
- **A (ID SKU)** — primary key, case-insensitive matching
- **G (Stok Saat ini)** — biasanya formula `D - E + F` (Total Masuk - Total Keluar + Adj Opname)

Kolom B-F & H+ untuk metadata WMS (ADS, Reorder Point, dst) — tidak dibaca oleh aplikasi.

### Google Sheet — LOG_KELUAR

| A (Tanggal) | B (ID SKU) | C (Qty) | D (Keterangan) |
|---|---|---|---|
| =formula_tanggal | 001-VN-A6-A | 5 | REF000... |

Aplikasi tulis B/C/D saja. Keterangan diisi dengan **No Resi** saat dari Mulai Sortir. Diisi `"Scanner"` saat dari fitur Kelola Gudang scanner sheet (terpisah dari aplikasi desktop).

### Format SKU untuk Mode A3

Untuk Mode Pembulatan A3, SKU **harus** mengandung segmen ukuran:

| Pattern | Ukuran terdeteksi | Pembulatan |
|---|---|---|
| `001-VN-A6-A`, `001_VN_A6_A` | A6 | kelipatan 8 |
| `141-VN-A5-B`, `141_VN_A5_B` | A5 | kelipatan 4 |

Pemisah `-` atau `_` keduanya didukung. Case-insensitive. Kalau ukuran tidak terdeteksi, mode A3 fallback ke qty asli + log warning.

---

## 7. Auto-Update

- Cek update **setiap launch** ke `https://api.github.com/repos/<owner>/<repo>/releases/latest`.
- Banner muncul kalau `tag_name` lebih besar dari `__version__` lokal.
- Update ZIP di-stage ke `.update_pending/`, lalu `run.bat` apply saat restart (backup ke `.update_backup/`).
- Kalau aplikasi crash setelah update, `run.bat` otomatis rollback dari `.update_backup/`.
- Setelah update sukses, popup `Update Berhasil` muncul dengan release notes.

**Shortcut:**
- `Ctrl+Shift+U` — force re-check update di session berjalan (juga aktifkan verbose log: outcome up-to-date / offline ditampilkan, biasanya disembunyikan).

**Konfigurasi update di `config.json`:**
- `github_repo` (wajib) — format `"owner/repo"`. Kalau tidak ada, update di-skip silent.
- `github_token` (opsional) — Personal Access Token untuk private repo.

---

## 8. Troubleshooting

### ❌ Apps Script error: "Field 'rows' harus array"

**Penyebab:** Apps Script Web App belum di-redeploy ke versi terbaru. Endpoint baru (`lookup_resi`, `bulk_snapshot`, dst) tidak dikenali → request fallback ke handler default `sync_orders` yang expect `body.rows`.

**Solusi:** Sheet → Extensions → Apps Script → Deploy → Manage deployments → ⚙ → Edit → Version: **New version** → Deploy. URL tetap sama, tidak perlu update di workstation.

### ❌ Stok tidak terpotong padahal ada di DATABASE_STIKER

**Cek:**
1. Checkbox **Auto Potong Stok** di tab Eksekusi tercentang? Default ON setiap launch.
2. Log Proses ada baris `📦 Membaca stok dari DATABASE_STIKER...`? Kalau tidak: webhook salah / Apps Script error / checkbox off.
3. SKU di Excel pesanan & DATABASE persis sama? (case-insensitive, tapi karakter & whitespace harus match).
4. Di v1.0.7 ke bawah ada bug: nilai `auto_deduct: false` bisa nyangkut di config. v1.0.8+ auto-cleanup. Kalau masih bermasalah: tutup app, hapus `config.json` (akan di-re-create), atau hapus key `auto_deduct` manual.

### ⚠️ Resi tidak ditemukan di Cek Stok Resi

**Penyebab:** Resi belum ada di tab DATA_SALES. Resi tertulis ke DATA_SALES hanya saat operator klik **Mulai Sortir**.

**Solusi:**
1. Pastikan operator sudah klik Mulai Sortir untuk batch yang berisi resi tsb.
2. Klik **🔄 Refresh** di tab Cek Stok Resi untuk re-pull snapshot.

### ❌ Cache snapshot gagal load

**Penyebab umum:**
1. Apps Script belum di-redeploy (lihat error pertama di atas).
2. Internet putus.
3. Webhook URL salah / Apps Script return non-JSON.
4. DATA_SALES terlalu besar → Apps Script timeout (>6 menit).

**Solusi:**
1. Cek pesan error di area hasil scan.
2. Klik 🔄 Refresh untuk retry.
3. Kalau DATA_SALES > 10K baris: di sheet, **menu Kelola Gudang → Bersihkan Data Lama (30 Hari)**.

### 🗑️ Folder Output isinya hilang

By design — folder Output **di-wipe setiap klik Mulai Sortir**. Jangan simpan apapun di folder Output. Kalau mau arsip hasil sortir, copy ke folder lain dulu sebelum run berikutnya.

### 🔧 Update gagal / app tidak buka setelah update

`run.bat` punya auto-rollback dari `.update_backup/`. Kalau gagal juga:

1. Cek `.update_logs/update.log` untuk error detail.
2. Manual recovery:
   - Buka `https://github.com/<owner>/<repo>/releases`
   - Download ZIP rilis terakhir yang stabil
   - Extract ke folder app, overwrite `app.py`, `file_processor.py`, `updater.py`, `version.py`, `requirements.txt`, `resi_checker.py`, `stock_reader.py`, `sheets_sync.py`
   - Hapus folder `.update_pending/` dan `.update_backup/`
   - Run `run.bat` lagi

### 🐌 Aplikasi lambat saat startup

- Pertama kali jalan: `run.bat` bootstrap `.venv` (~30 detik). Wajar.
- Berikutnya seharusnya <3 detik.
- Cek update jalan async (3 detik setelah UI paint) — tidak block UI.

### 📂 SKU di Excel ada tapi file tidak ditemukan

**Penyebab:** Substring match SKU di nama file gagal. Contoh: SKU di Excel `001-VN-A6-A` tapi nama file `001VNA6A.cdr` (tanpa dash) → tidak match.

**Solusi:** Standarkan format nama file = format SKU di Excel. Substring matching case-insensitive, jadi case tidak masalah. Yang penting karakter (terutama dash/underscore/space) harus konsisten.

---

## 9. File & Folder

### File source code

| File | Fungsi |
|---|---|
| `app.py` | GUI utama (Tkinter) |
| `file_processor.py` | Logika sortir & copy file |
| `stock_reader.py` | Client stok (fetch + consume_stock ke Apps Script) |
| `resi_checker.py` | Client lookup resi + bulk_snapshot |
| `sheets_sync.py` | Client sync DATA_SALES + buffer pending kalau offline |
| `updater.py` | Auto-updater dari GitHub Releases |
| `version.py` | Single source of truth untuk versi (`__version__`) |
| `apps_script.gs` | Backend di Google Sheet (di-paste ke Apps Script editor) |
| `release.py` | Build & publish release (admin only) |
| `preflight.py` | Health check sebelum bootstrap |

### File konfigurasi & runtime

| File / Folder | Fungsi |
|---|---|
| `config.json` | Settings (path, webhook, dll). **Jangan edit manual** — pakai tab Konfigurasi |
| `requirements.txt` | Daftar dep Python (`openpyxl` saja) |
| `pesanan_harian.xlsx` | File pesanan default. Bisa pilih file lain via tab Konfigurasi |
| `Output/` | **Folder hasil sortir — DI-WIPE setiap run!** |
| `.venv/` | Virtual environment Python (auto-created) |
| `.update_staging/` | Working dir saat download update — auto-managed |
| `.update_pending/` | Update yang siap apply, ditangani `run.bat` saat next launch |
| `.update_backup/` | Backup file lama, auto-restore kalau update gagal |
| `.update_logs/update.log` | Rotating log untuk debugging update (3 backup × 256 KB) |
| `.pending_sales.json` | Buffer DATA_SALES kalau webhook offline. Retry otomatis di run berikutnya |

### Launcher

| File | Cara pakai |
|---|---|
| `run.bat` | Double-click — buka jendela cmd hitam + GUI |
| `run.vbs` | Double-click — buka GUI saja, tanpa cmd window |
| `install.bat` | Setup awal (jalankan sekali kalau dapat folder fresh) |

---

## 10. Untuk Admin / Developer

### 10.1. Release Workflow (publish update baru)

```bash
# 1. Edit code, test lokal
.venv\Scripts\python app.py

# 2. Bump version + build ZIP + (opsional) auto-publish
python release.py 1.x.y --notes "Bullet 1" "Bullet 2"
# Atau langsung publish via gh CLI:
python release.py 1.x.y --notes "..." --publish

# 3. Commit version bump (kalau tanpa --publish)
git add version.py
git commit -m "Bump version: A.B.C -> X.Y.Z"
git push

# 4. Publish manual kalau tidak pakai --publish
gh release create vX.Y.Z dist/sortir-stiker-pack-X.Y.Z.zip \
  --title "Release vX.Y.Z" \
  --notes "$(cat <<'EOF'
- Bullet 1
- Bullet 2
EOF
)"
```

**Catatan:**
- ZIP name harus match pattern `sortir-stiker-pack-*.zip` supaya updater pickup. `release.py` auto-generate nama yang benar.
- Release body (markdown) ditampilkan sebagai release notes di popup post-update. Pakai bullet `-` atau `*`.
- ZIP **tidak boleh** punya wrapper folder — file harus langsung di root.

### 10.2. Wajib Setelah Edit `apps_script.gs`

Apps Script di Google Sheet **terpisah dari deployment**. Kalau edit `apps_script.gs` di repo, sheet admin **wajib redeploy** Web App-nya:

1. Sheet → Extensions → Apps Script
2. Paste isi `apps_script.gs` terbaru → Save
3. Deploy → Manage deployments → ⚙ pada deployment Web app → Edit
4. Version: **New version** → Deploy

URL Web App **tidak berubah**, jadi `webhook_url` di workstation operator tetap.

### 10.3. Apps Script Endpoints

| Action | Method | Body | Response |
|---|---|---|---|
| (read stok) | GET | – | `{status, stock:{SKU:qty}, count}` |
| `sync_orders` (default) | POST | `{rows:[{tanggal, resi, sku, qty}]}` | `{status, written}` |
| `consume_stock` | POST | `{action, items:[{sku, qty, ket}]}` | `{status, consumed:[{sku, ok, taken, sisa}], count}` |
| `lookup_resi` | POST | `{action, resi}` | `{status, items:[{sku, qty}], stock:{SKU:qty}, count}` |
| `bulk_snapshot` | POST | `{action}` | `{status, sales:[{resi, sku, qty}], stock:{SKU:qty}, sales_count, stock_count, timestamp}` |

Semua POST: `Content-Type: application/json`. Lock dipasang di `consume_stock` supaya tidak race.

### 10.4. Kontrak antar Layer (Python)

- `log_callback(level, message)` — level ∈ `{"success", "error", "warning", "info"}`. Modul logic murni (`file_processor`, `stock_reader`, `resi_checker`, `sheets_sync`) **tidak boleh** import UI.
- `progress_callback(current, total)` — dipakai `file_processor` untuk update progress bar.
- `process_orders(...)` return `{total, berhasil, dari_gudang, tidak_ditemukan, berhasil_list}`.
- `fetch_snapshot(...)` return `{by_resi, stock, sales_count, stock_count, fetched_at}` atau `None`.

### 10.5. Aturan File Replacement

**Running Python TIDAK BOLEH menulis ke `app.py`/`file_processor.py`/`version.py`/dll.** File replacement **eksklusif** tugas `run.bat`. Python updater hanya stage ke `.update_staging/` → atomic-rename ke `.update_pending/`. Ini mencegah Windows file-lock edge cases.

### 10.6. Security

- **Repo write access = trust boundary**. Siapa pun yang punya write access bisa publish release yang auto-install di semua workstation. Tidak ada code signing.
- Mitigasi: pakai **private repo** + collaborator list yang dibatasi.
- Transport: HTTPS ke `api.github.com`, `github.com`, dan `script.google.com` — cukup untuk integrity.

### 10.7. Quick Reference: Bahasa & Konvensi

- UI strings: **bahasa Indonesia**. Pertahankan saat edit.
- Code comments: campuran Indonesia + English (technical terms).
- Log levels (tag widget): `success`, `error`, `warning`, `info`, `printed`, `muted`, `header`. Tambah tag baru → register di `_build_log_pane`.
- Banner states: `hidden`, `checking`, `downloading`, `validating`, `ready`, `cancelled`. Tambah state baru → handle di `_apply_banner_state`.

---

## Lisensi & Kontak

Repo internal — tidak open-source. Issue & request fitur via GitHub Issues di repo.
