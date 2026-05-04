"""
app.py
Aplikasi Sortir Stiker Pack — GUI berbasis tkinter
Jalankan: python app.py
"""

import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from file_processor import process_orders
from resi_checker import lookup_resi
from stock_reader import consume_stock
from updater import UpdateOrchestrator
from version import __version__

# ─── Config ───────────────────────────────────────────────────────────────────
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_config(data: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ─── Palette warna ────────────────────────────────────────────────────────────
BG_DARK        = "#0f0f1a"
BG_PANEL       = "#1a1a2e"
BG_CARD        = "#16213e"
BG_INPUT       = "#0d1b2a"
BORDER_COLOR   = "#1e3a5f"

ACCENT         = "#6c63ff"   # ungu-biru
ACCENT_HOVER   = "#5a52db"
ACCENT_GLOW    = "#3a33aa"

SUCCESS_COLOR  = "#00d26a"   # hijau neon
ERROR_COLOR    = "#ff4d6d"   # merah coral
WARNING_COLOR  = "#ffd166"   # kuning
INFO_COLOR     = "#48cae4"   # biru terang
MUTED_COLOR    = "#7b8db4"   # abu-biru

TEXT_PRIMARY   = "#e8f0fe"
TEXT_SECONDARY = "#94a3b8"

BTN_SECONDARY  = "#1e3a5f"
BTN_SEC_HOVER  = "#2a4d7a"

MODE_NORMAL_BG    = "#1a2744"
MODE_NORMAL_SEL   = "#1e3d6b"
MODE_A3_BG        = "#1f1830"
MODE_A3_SEL       = "#2d1f4e"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Sortir Stiker Pack — v{__version__}")
        self.geometry("900x780")
        self.minsize(760, 640)
        self.configure(bg=BG_DARK)
        self.resizable(True, True)

        # State
        self.source_folder = tk.StringVar()
        self.excel_path    = tk.StringVar()
        self.output_folder = tk.StringVar()
        self.webhook_url   = tk.StringVar()
        self.mode_var      = tk.StringVar(value="normal")  # "normal" | "a3_round"
        self._processing   = False

        # Auto-deduct (dipakai oleh Eksekusi & Scanner tab — sumbernya satu)
        # Default True: operator yg sehari-hari ingin stok auto terpotong saat sortir.
        self.auto_deduct_var = tk.BooleanVar(value=True)
        self.scan_input      = tk.StringVar()

        # Update state
        self._active_orchestrator = None
        self._restart_cancelled   = False
        self._banner_state        = "hidden"
        self._pending_sortir_args = None  # (src, excel, output, mode, webhook) — diisi saat klik Start, dipakai setelah cek update selesai

        self._build_ui()
        self._load_saved_paths()
        self._center_window()

        # Kalau baru saja di-update, tampilkan popup konfirmasi (tampil setelah UI paint)
        self.after(500, self._check_post_update_notification)

        # Manual force-check via shortcut (auto-check sekarang dipicu oleh klik Start)
        self.bind("<Control-Shift-U>", lambda _e: self._start_update_check(force=True))

    # ── Center window ─────────────────────────────────────────────────────────
    def _center_window(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        sw   = self.winfo_screenwidth()
        sh   = self.winfo_screenheight()
        x    = (sw - w) // 2
        y    = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    # ── Build UI ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Style global (clam + progressbar + notebook) ──────────────────────
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Stiker.Horizontal.TProgressbar",
            troughcolor = BG_INPUT,
            background  = ACCENT,
            thickness   = 12,
            borderwidth = 0,
        )
        style.configure(
            "Stiker.TNotebook",
            background  = BG_DARK,
            borderwidth = 0,
            tabmargins  = [0, 0, 0, 0],
        )
        style.configure(
            "Stiker.TNotebook.Tab",
            background  = BG_PANEL,
            foreground  = TEXT_SECONDARY,
            padding     = [22, 9],
            font        = ("Segoe UI", 9, "bold"),
            borderwidth = 0,
        )
        style.map(
            "Stiker.TNotebook.Tab",
            background = [("selected", BG_CARD), ("active", BTN_SEC_HOVER)],
            foreground = [("selected", TEXT_PRIMARY), ("active", TEXT_PRIMARY)],
        )

        self.progress_var = tk.DoubleVar(value=0)

        # ── Footer (pack dulu di bawah, supaya banner bisa pack `before=`) ────
        self.footer_frame = tk.Frame(self, bg=BG_DARK, pady=6)
        self.footer_frame.pack(fill="x", side="bottom")
        tk.Label(
            self.footer_frame,
            text="Sortir Stiker Pack  ·  Mode Normal & Pembulatan A3",
            font=("Segoe UI", 7),
            fg=MUTED_COLOR, bg=BG_DARK,
        ).pack()

        # ── Notebook (Konfigurasi  /  Eksekusi) ───────────────────────────────
        self.notebook = ttk.Notebook(self, style="Stiker.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=20, pady=(14, 6))

        tab_config = tk.Frame(self.notebook, bg=BG_DARK)
        self.notebook.add(tab_config, text="  ⚙  Konfigurasi  ")
        self._build_config_tab(tab_config)

        tab_exec = tk.Frame(self.notebook, bg=BG_DARK)
        self.notebook.add(tab_exec, text="  ▶  Eksekusi  ")
        self._build_exec_tab(tab_exec)

        tab_scan = tk.Frame(self.notebook, bg=BG_DARK)
        self.notebook.add(tab_scan, text="  🔎  Cek Stok Resi  ")
        self._build_scanner_tab(tab_scan)

        # Auto-focus scan entry saat tab scanner dipilih
        self.notebook.bind("<<NotebookTabChanged>>", self._on_notebook_tab_change)

        # Default ke tab Eksekusi (yang dipakai sehari-hari)
        self.notebook.select(tab_exec)

        # Update banner (hidden by default — muncul saat ada update berjalan)
        self._build_update_banner()

    # ── Tab: Konfigurasi ──────────────────────────────────────────────────────
    def _build_config_tab(self, parent):
        path_panel = tk.Frame(parent, bg=BG_PANEL, padx=22, pady=18)
        path_panel.pack(fill="x", padx=4, pady=(12, 0))

        tk.Label(
            path_panel,
            text="KONFIGURASI PATH",
            font=("Segoe UI", 8, "bold"),
            fg=MUTED_COLOR, bg=BG_PANEL,
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        self._make_path_row(path_panel, 1, "📁  Folder Sumber Desain",
                            self.source_folder, self._browse_source)
        self._make_path_row(path_panel, 2, "📋  File Pesanan Excel  (.xlsx)",
                            self.excel_path,    self._browse_excel)
        self._make_path_row(path_panel, 3, "📤  Folder Output",
                            self.output_folder, self._browse_output)
        self._make_text_row(path_panel, 4,
                            "🔗  Webhook Google Sheet  (URL Apps Script Web App — opsional)",
                            self.webhook_url)
        path_panel.columnconfigure(0, weight=1)

        tk.Label(
            parent,
            text="ℹ  Pengaturan disimpan otomatis. Pindah ke tab Eksekusi untuk menjalankan.",
            font=("Segoe UI", 8),
            fg=MUTED_COLOR, bg=BG_DARK,
        ).pack(pady=(14, 0))

    # ── Tab: Eksekusi ─────────────────────────────────────────────────────────
    def _build_exec_tab(self, parent):
        # Mode output
        mode_outer = tk.Frame(parent, bg=BG_DARK, pady=10)
        mode_outer.pack(fill="x")

        tk.Label(
            mode_outer,
            text="MODE OUTPUT",
            font=("Segoe UI", 8, "bold"),
            fg=MUTED_COLOR, bg=BG_DARK,
            anchor="w",
        ).pack(fill="x", pady=(0, 8))

        mode_cards = tk.Frame(mode_outer, bg=BG_DARK)
        mode_cards.pack(fill="x")
        mode_cards.columnconfigure(0, weight=1)
        mode_cards.columnconfigure(1, weight=1)

        self._build_mode_card(
            parent   = mode_cards,
            col      = 0,
            value    = "normal",
            icon     = "1️⃣",
            title    = "Mode Normal",
            subtitle = "Salin sesuai jumlah order",
            desc     = "Setiap file disalin tepat N kali sesuai kolom\n"
                        "Jumlah di Excel. Contoh: order 3 → salin 3.",
            bg_normal = MODE_NORMAL_BG,
            bg_sel    = MODE_NORMAL_SEL,
            accent    = "#48cae4",
        )
        self._build_mode_card(
            parent   = mode_cards,
            col      = 1,
            value    = "a3_round",
            icon     = "2️⃣",
            title    = "Mode Pembulatan A3",
            subtitle = "1 file dengan label kelipatan",
            desc     = "A5 → label 4x  |  A6 → label 8x\n"
                        "Cukup duplikat di CorelDRAW sesuai label.",
            bg_normal = MODE_A3_BG,
            bg_sel    = MODE_A3_SEL,
            accent    = "#6c63ff",
        )

        # Opsi: Auto Potong Stok (dicek default — sama seperti perilaku lama)
        opt_frame = tk.Frame(parent, bg=BG_DARK, pady=10)
        opt_frame.pack(fill="x")

        cb_auto_deduct = tk.Checkbutton(
            opt_frame,
            text=" Auto Potong Stok  (potong DATABASE_STIKER + tulis LOG_KELUAR sebelum cetak)",
            variable=self.auto_deduct_var,
            font=("Segoe UI", 9, "bold"),
            bg=BG_DARK, fg=ACCENT,
            selectcolor=BG_INPUT,
            activebackground=BG_DARK, activeforeground=ACCENT,
            cursor="hand2",
            command=self._on_auto_deduct_change,
        )
        cb_auto_deduct.pack(anchor="w", padx=4)

        tk.Label(
            opt_frame,
            text=("Centang: SKU yang ada stoknya diambil dari gudang dulu, sisanya baru dicetak.   "
                  "Kosongkan: cetak semua, gudang tidak disentuh."),
            font=("Segoe UI", 8),
            fg=MUTED_COLOR, bg=BG_DARK,
            anchor="w", justify="left",
        ).pack(anchor="w", padx=24, pady=(2, 0))

        # Progress
        prog_frame = tk.Frame(parent, bg=BG_DARK)
        prog_frame.pack(fill="x", pady=(8, 0))

        self.progressbar = ttk.Progressbar(
            prog_frame,
            variable = self.progress_var,
            maximum  = 100,
            style    = "Stiker.Horizontal.TProgressbar",
        )
        self.progressbar.pack(fill="x")

        self.progress_label = tk.Label(
            prog_frame,
            text="",
            font=("Segoe UI", 8),
            fg=MUTED_COLOR, bg=BG_DARK,
            anchor="e",
        )
        self.progress_label.pack(fill="x")

        # Tombol mulai + shortcut Folder Output
        btn_frame = tk.Frame(parent, bg=BG_DARK, pady=6)
        btn_frame.pack()

        self.btn_start = tk.Button(
            btn_frame,
            text="▶  Mulai Sortir",
            font=("Segoe UI", 10, "bold"),
            bg=ACCENT, fg="white",
            activebackground=ACCENT_HOVER, activeforeground="white",
            relief="flat", cursor="hand2",
            padx=22, pady=6,
            command=self._start_process,
        )
        self.btn_start.pack(side="left")
        self._bind_hover(self.btn_start, ACCENT, ACCENT_HOVER)

        self.btn_open_output = tk.Button(
            btn_frame,
            text="📂  Folder Output",
            font=("Segoe UI", 9),
            bg=BTN_SECONDARY, fg=TEXT_PRIMARY,
            activebackground=BTN_SEC_HOVER, activeforeground=TEXT_PRIMARY,
            relief="flat", cursor="hand2",
            padx=14, pady=6,
            command=self._open_output_folder,
        )
        self.btn_open_output.pack(side="left", padx=(8, 0))
        self._bind_hover(self.btn_open_output, BTN_SECONDARY, BTN_SEC_HOVER)

        # Area log — sub-notebook dengan dua tab: Log Proses + Log Gudang
        log_outer = tk.Frame(parent, bg=BG_DARK, pady=6)
        log_outer.pack(fill="both", expand=True)

        log_header = tk.Frame(log_outer, bg=BG_DARK)
        log_header.pack(fill="x", pady=(0, 6))

        self.stat_label = tk.Label(
            log_header,
            text="",
            font=("Segoe UI", 9),
            fg=INFO_COLOR, bg=BG_DARK,
        )
        self.stat_label.pack(side="left")

        btn_clear = tk.Button(
            log_header,
            text="Bersihkan Log",
            font=("Segoe UI", 8),
            bg=BTN_SECONDARY, fg=TEXT_SECONDARY,
            activebackground=BTN_SEC_HOVER, activeforeground=TEXT_PRIMARY,
            relief="flat", cursor="hand2",
            padx=10, pady=3,
            command=self._clear_log,
        )
        btn_clear.pack(side="right")
        self._bind_hover(btn_clear, BTN_SECONDARY, BTN_SEC_HOVER)

        log_notebook = ttk.Notebook(log_outer, style="Stiker.TNotebook")
        log_notebook.pack(fill="both", expand=True)
        self.log_notebook = log_notebook

        # Tab 1: Log Proses (default, semua log selama eksekusi)
        tab_proses = tk.Frame(log_notebook, bg=BG_DARK)
        log_notebook.add(tab_proses, text="  📋  Log Proses  ")
        self.log_text = self._build_log_pane(tab_proses)

        # Tab 2: Log Gudang (terisi setelah proses selesai —
        # khusus SKU yang diambil dari gudang)
        tab_gudang = tk.Frame(log_notebook, bg=BG_DARK)
        log_notebook.add(tab_gudang, text="  🏪  Log Gudang  ")
        self.log_gudang_text = self._build_log_pane(tab_gudang)

    def _build_log_pane(self, parent) -> tk.Text:
        """Bikin satu kotak log (Text + Scrollbar) yang siap di-tag-warna."""
        log_box = tk.Frame(parent, bg=BG_INPUT, relief="flat",
                           highlightbackground=BORDER_COLOR, highlightthickness=1)
        log_box.pack(fill="both", expand=True)

        text = tk.Text(
            log_box,
            font=("Consolas", 11),
            bg=BG_INPUT, fg=TEXT_PRIMARY,
            relief="flat",
            padx=14, pady=10,
            state="disabled",
            wrap="word",
            cursor="arrow",
            spacing1=2,
            spacing3=2,
        )
        scrollbar = tk.Scrollbar(
            log_box, command=text.yview,
            bg=BG_PANEL, troughcolor=BG_INPUT, width=12,
        )
        text.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)

        text.tag_configure("success", foreground=SUCCESS_COLOR)   # hijau — dari gudang
        text.tag_configure("printed", foreground=TEXT_PRIMARY)    # putih — file dicetak
        text.tag_configure("error",   foreground=ERROR_COLOR)
        text.tag_configure("warning", foreground=WARNING_COLOR)
        text.tag_configure("info",    foreground=INFO_COLOR)
        text.tag_configure("muted",   foreground=MUTED_COLOR)
        return text

    # ── Mode card (radio button bergaya) ──────────────────────────────────────
    def _build_mode_card(self, parent, col, value, icon, title, subtitle, desc,
                         bg_normal, bg_sel, accent):
        padx = (0, 6) if col == 0 else (6, 0)

        card = tk.Frame(parent, bg=bg_normal,
                        highlightbackground=BORDER_COLOR, highlightthickness=1,
                        padx=14, pady=12, cursor="hand2")
        card.grid(row=0, column=col, sticky="nsew", padx=padx)

        header_row = tk.Frame(card, bg=bg_normal)
        header_row.pack(fill="x")

        icon_lbl = tk.Label(header_row, text=icon, font=("Segoe UI Emoji", 18),
                            bg=bg_normal)
        icon_lbl.pack(side="left")

        txt_frame = tk.Frame(header_row, bg=bg_normal)
        txt_frame.pack(side="left", padx=(8, 0))

        title_lbl = tk.Label(txt_frame, text=title,
                             font=("Segoe UI", 11, "bold"),
                             fg=TEXT_PRIMARY, bg=bg_normal, anchor="w")
        title_lbl.pack(anchor="w")

        sub_lbl = tk.Label(txt_frame, text=subtitle,
                           font=("Segoe UI", 8),
                           fg=accent, bg=bg_normal, anchor="w")
        sub_lbl.pack(anchor="w")

        desc_lbl = tk.Label(card, text=desc,
                            font=("Segoe UI", 8),
                            fg=TEXT_SECONDARY, bg=bg_normal,
                            justify="left", anchor="w")
        desc_lbl.pack(fill="x", pady=(8, 0))

        # Radio hidden (tapi fungsional)
        radio = tk.Radiobutton(
            card, variable=self.mode_var, value=value,
            bg=bg_normal, activebackground=bg_sel,
            command=lambda: self._on_mode_change(),
        )
        # Sembunyikan widget default, biarkan full card menjadi klikable
        radio.place(relx=1, rely=0, anchor="ne")

        def on_click(_e=None):
            self.mode_var.set(value)
            self._on_mode_change()

        for w in [card, header_row, icon_lbl, txt_frame, title_lbl, sub_lbl, desc_lbl]:
            w.bind("<Button-1>", on_click)

        # Simpan ref card untuk highlight
        setattr(self, f"_card_{value}", card)
        setattr(self, f"_card_{value}_all",
                [card, header_row, icon_lbl, txt_frame, title_lbl, sub_lbl, desc_lbl, radio])
        setattr(self, f"_card_{value}_bg_normal", bg_normal)
        setattr(self, f"_card_{value}_bg_sel",    bg_sel)

        self._refresh_mode_cards()

    def _on_mode_change(self):
        self._refresh_mode_cards()
        # Simpan pilihan mode ke config
        cfg = load_config()
        cfg["mode"] = self.mode_var.get()
        save_config(cfg)

    def _refresh_mode_cards(self):
        selected = self.mode_var.get()
        for val in ["normal", "a3_round"]:
            try:
                widgets   = getattr(self, f"_card_{val}_all")
                bg_normal = getattr(self, f"_card_{val}_bg_normal")
                bg_sel    = getattr(self, f"_card_{val}_bg_sel")
                bg        = bg_sel if val == selected else bg_normal
                border    = ACCENT if val == selected else BORDER_COLOR

                card = getattr(self, f"_card_{val}")
                card.configure(highlightbackground=border)
                for w in widgets:
                    try:
                        w.configure(bg=bg)
                    except Exception:
                        pass
            except AttributeError:
                pass

    # ── Path row helper ───────────────────────────────────────────────────────
    def _make_path_row(self, parent, row, label_text, var, command):
        pad_y = (0, 10)

        tk.Label(
            parent,
            text=label_text,
            font=("Segoe UI", 8, "bold"),
            fg=TEXT_SECONDARY, bg=BG_PANEL,
            anchor="w",
        ).grid(row=row * 2 - 1, column=0, columnspan=2, sticky="w", pady=(0, 2))

        entry = tk.Entry(
            parent,
            textvariable=var,
            font=("Segoe UI", 9),
            bg=BG_INPUT, fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY,
            relief="flat", bd=0,
            highlightbackground=BORDER_COLOR, highlightthickness=1,
        )
        entry.grid(row=row * 2, column=0, sticky="ew", ipady=6,
                   padx=(0, 8), pady=pad_y)

        btn = tk.Button(
            parent,
            text="Pilih…",
            font=("Segoe UI", 8),
            bg=BTN_SECONDARY, fg=TEXT_PRIMARY,
            activebackground=BTN_SEC_HOVER, activeforeground=TEXT_PRIMARY,
            relief="flat", cursor="hand2",
            padx=12, pady=4,
            command=command,
        )
        btn.grid(row=row * 2, column=1, pady=pad_y)
        self._bind_hover(btn, BTN_SECONDARY, BTN_SEC_HOVER)

    # ── Text-only row (untuk URL / value yang ditik manual) ──────────────────
    def _make_text_row(self, parent, row, label_text, var):
        tk.Label(
            parent,
            text=label_text,
            font=("Segoe UI", 8, "bold"),
            fg=TEXT_SECONDARY, bg=BG_PANEL,
            anchor="w",
        ).grid(row=row * 2 - 1, column=0, columnspan=2, sticky="w", pady=(0, 2))

        entry = tk.Entry(
            parent,
            textvariable=var,
            font=("Segoe UI", 9),
            bg=BG_INPUT, fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY,
            relief="flat", bd=0,
            highlightbackground=BORDER_COLOR, highlightthickness=1,
        )
        entry.grid(row=row * 2, column=0, columnspan=2, sticky="ew",
                   ipady=6, pady=(0, 0))
        # Persist setiap perubahan (paste/ketik) — bulletproof, nggak gantung pada FocusOut
        var.trace_add("write", lambda *_a: self._save_paths())

    # ── Hover helper ──────────────────────────────────────────────────────────
    @staticmethod
    def _bind_hover(widget, normal, hover):
        widget.bind("<Enter>", lambda _: widget.config(bg=hover))
        widget.bind("<Leave>", lambda _: widget.config(bg=normal))

    # ── Config: load & save ───────────────────────────────────────────────────
    def _load_saved_paths(self):
        cfg = load_config()
        if cfg.get("source_folder"):
            self.source_folder.set(cfg["source_folder"])
        if cfg.get("excel_path"):
            self.excel_path.set(cfg["excel_path"])
        if cfg.get("output_folder"):
            self.output_folder.set(cfg["output_folder"])
        if cfg.get("webhook_url"):
            self.webhook_url.set(cfg["webhook_url"])
        if cfg.get("mode") in ("normal", "a3_round"):
            self.mode_var.set(cfg["mode"])
            self._refresh_mode_cards()
        if "auto_deduct" in cfg:
            self.auto_deduct_var.set(bool(cfg["auto_deduct"]))

    def _save_paths(self):
        # Merge supaya field config lain (mis. last_known_version dari updater) tidak hilang.
        cfg = load_config()
        cfg.update({
            "source_folder": self.source_folder.get(),
            "excel_path":    self.excel_path.get(),
            "output_folder": self.output_folder.get(),
            "webhook_url":   self.webhook_url.get().strip(),
            "mode":          self.mode_var.get(),
        })
        save_config(cfg)

    # ── Browse callbacks ──────────────────────────────────────────────────────
    def _browse_source(self):
        init = self.source_folder.get() or None
        path = filedialog.askdirectory(title="Pilih Folder Sumber Desain", initialdir=init)
        if path:
            self.source_folder.set(path)
            self._save_paths()

    def _browse_excel(self):
        init_dir = os.path.dirname(self.excel_path.get()) if self.excel_path.get() else None
        path = filedialog.askopenfilename(
            title="Pilih File Pesanan Excel",
            initialdir=init_dir,
            filetypes=[("Excel Files", "*.xlsx *.xls *.xlsm"), ("All Files", "*.*")],
        )
        if path:
            self.excel_path.set(path)
            self._save_paths()

    def _browse_output(self):
        init = self.output_folder.get() or None
        path = filedialog.askdirectory(title="Pilih Folder Output", initialdir=init)
        if path:
            self.output_folder.set(path)
            self._save_paths()

    # ── Shortcut buka folder output di File Explorer ─────────────────────────
    def _open_output_folder(self):
        output = self.output_folder.get().strip()
        if not output:
            messagebox.showwarning(
                "Folder Output Belum Diset",
                "Belum ada folder output. Set dulu di tab ⚙ Konfigurasi."
            )
            return
        if not os.path.isdir(output):
            if not messagebox.askyesno(
                "Folder Belum Ada",
                f"Folder belum ada:\n\n{output}\n\nBuat sekarang?"
            ):
                return
            try:
                os.makedirs(output, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Gagal Membuat Folder", str(e))
                return
        try:
            os.startfile(output)
        except Exception as e:
            messagebox.showerror("Gagal Membuka Folder", str(e))

    # ── Log helpers ───────────────────────────────────────────────────────────
    def _log(self, level: str, message: str):
        """Thread-safe log ke Text widget."""
        self.after(0, self._append_log, level, message)

    def _append_log(self, level: str, message: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n", level)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _append_log_gudang(self, level: str, message: str):
        self.log_gudang_text.configure(state="normal")
        self.log_gudang_text.insert("end", message + "\n", level)
        self.log_gudang_text.see("end")
        self.log_gudang_text.configure(state="disabled")

    def _clear_log(self):
        for txt in (self.log_text, self.log_gudang_text):
            txt.configure(state="normal")
            txt.delete("1.0", "end")
            txt.configure(state="disabled")
        self.stat_label.config(text="")

    # ── Progress ──────────────────────────────────────────────────────────────
    def _update_progress(self, current: int, total: int):
        pct = (current / total * 100) if total > 0 else 0
        self.after(0, lambda: self.progress_var.set(pct))
        self.after(0, lambda: self.progress_label.config(
            text=f"{current} / {total}   ({pct:.0f}%)"
        ))

    # ── Start process ─────────────────────────────────────────────────────────
    def _start_process(self):
        if self._processing:
            return

        src    = self.source_folder.get().strip()
        excel  = self.excel_path.get().strip()
        output = self.output_folder.get().strip()
        mode   = self.mode_var.get()

        # Validasi input
        errors = []
        if not src:
            errors.append("• Folder Sumber Desain belum dipilih.")
        elif not os.path.isdir(src):
            errors.append("• Folder Sumber Desain tidak ditemukan.")

        if not excel:
            errors.append("• File Pesanan Excel belum dipilih.")
        elif not os.path.isfile(excel):
            errors.append("• File Pesanan Excel tidak ditemukan.")

        if not output:
            errors.append("• Folder Output belum dipilih.")

        if errors:
            messagebox.showerror("Input Tidak Lengkap", "\n".join(errors))
            return

        os.makedirs(output, exist_ok=True)

        # Persist field webhook (jaga-jaga user belum pindah fokus dari entry)
        self._save_paths()
        webhook = self.webhook_url.get().strip()

        self._processing = True
        self.stat_label.config(text="")
        self._clear_log()
        self.progress_var.set(0)
        self.progress_label.config(text="")

        # Simpan args untuk dipakai setelah cek update selesai
        self._pending_sortir_args = (src, excel, output, mode, webhook)

        # Cek update dulu — kalau ada update, restart cycle akan jalan
        # dan _proceed_with_sortir tidak dipanggil. Kalau up-to-date, lanjut sortir.
        self.btn_start.config(text="🔄  Memeriksa update…", state="disabled")
        self._log("info", "🔄  Memeriksa pembaruan dari GitHub sebelum mulai...")
        self._start_update_check(force=True, done_callback=self._after_update_check_for_sortir)

    def _after_update_check_for_sortir(self, was_cancelled: bool):
        """
        Dipanggil di UI thread setelah UpdateOrchestrator selesai (dipicu dari klik Start).
        - Kalau .update_pending/ ada → restart cycle in-progress, biarkan jalan.
        - Kalau user batalin download → reset tombol, jangan sortir.
        - Lainnya → lanjut sortir dengan args yang disimpan.
        """
        project_root = os.path.dirname(os.path.abspath(__file__))
        pending_dir  = os.path.join(project_root, ".update_pending")

        if os.path.exists(pending_dir):
            # Update sudah di-stage. _schedule_restart sudah dipanggil sebelum
            # callback ini, jadi countdown berjalan. Tombol stay disabled.
            self._log("info", "ℹ️  Update siap — aplikasi akan restart untuk memasang versi baru.")
            return

        if was_cancelled:
            self._processing = False
            self._pending_sortir_args = None
            self.btn_start.config(text="▶   MULAI SORTIR", state="normal")
            self._log("warning", "⚠️  Sortir dibatalkan karena pengecekan update di-cancel.")
            return

        # Up-to-date / offline / GitHub belum dikonfigurasi → lanjut sortir
        self._proceed_with_sortir()

    def _proceed_with_sortir(self):
        """Kick off thread sortir setelah cek update kelar tanpa update."""
        if self._pending_sortir_args is None:
            # State inconsistent — reset
            self._processing = False
            self.btn_start.config(text="▶   MULAI SORTIR", state="normal")
            return

        src, excel, output, mode, webhook = self._pending_sortir_args
        self._pending_sortir_args = None

        self.btn_start.config(text="⏳  Memproses…", state="disabled")
        self._log("info", "▶️  Memulai proses sortir...")

        thread = threading.Thread(
            target=self._run_process,
            args=(src, excel, output, mode, webhook),
            daemon=True,
        )
        thread.start()

    def _run_process(self, src, excel, output, mode, webhook):
        result = {"total": 0, "berhasil": 0, "tidak_ditemukan": []}
        try:
            result = process_orders(
                source_folder     = src,
                excel_path        = excel,
                output_folder     = output,
                mode              = mode,
                progress_callback = self._update_progress,
                log_callback      = self._log,
                webhook_url       = webhook,
                auto_deduct       = bool(self.auto_deduct_var.get()),
            )
        except Exception as e:
            self._log("error", f"❌ Error tidak terduga: {e}")
        finally:
            self.after(0, self._on_process_done, result)

    def _on_process_done(self, result: dict):
        self._processing = False
        self.btn_start.config(text="▶   MULAI SORTIR", state="normal")
        self._log("info", "✔️  Proses selesai.")

        total  = result.get("total", 0)
        ok     = result.get("berhasil", 0)
        errors = len(result.get("tidak_ditemukan", []))
        gudang = result.get("dari_gudang", 0)
        if total > 0:
            stat = f"✅ {ok} berhasil  |  📦 {gudang} dari gudang  |  ❌ {errors} tidak ditemukan  |  {total} total"
            self.stat_label.config(text=stat)

        self._populate_log_gudang(result)

    def _populate_log_gudang(self, result: dict):
        """
        Isi tab Log Gudang dari hasil proses sortir.
        Hanya entri yang from_stock > 0 (ada qty diambil dari DATABASE_STIKER).
        """
        # Bersihkan dulu sebelum re-populate (proses kedua tidak boleh nimpa list lama)
        self.log_gudang_text.configure(state="normal")
        self.log_gudang_text.delete("1.0", "end")
        self.log_gudang_text.configure(state="disabled")

        items = [b for b in result.get("berhasil_list", [])
                 if (b.get("from_stock") or 0) > 0]

        if not items:
            self._append_log_gudang("muted",
                "Tidak ada SKU yang diambil dari gudang pada proses ini.\n"
                "(Semua pesanan dicetak ulang atau stok kosong.)")
            return

        total_taken = sum(b["from_stock"] for b in items)
        header = (
            f"📦  {len(items)} pesanan diambil dari gudang  |  "
            f"total {total_taken} pcs\n"
            f"{'─' * 70}"
        )
        self._append_log_gudang("info", header)

        for b in items:
            resi   = b.get("resi", "")
            sku    = b.get("sku", "")
            qty    = b.get("qty_order", 0)
            taken  = b.get("from_stock", 0)
            copied = b.get("qty_copied", 0)

            if copied == 0:
                # Fully terlayani gudang — tidak ada copy
                line = f"✅ [{resi}]  {sku}  →  ambil {taken} dari gudang  (file desain tidak diduplikasi)"
                self._append_log_gudang("success", line)
            else:
                # Sebagian gudang, sebagian dicetak
                line = (f"✅ [{resi}]  {sku}  →  ambil {taken} dari gudang  "
                        f"+ cetak ulang {copied} (qty order {qty})")
                self._append_log_gudang("success", line)

    # ── Tab: Cek Stok Resi (Scanner) ──────────────────────────────────────────
    def _build_scanner_tab(self, parent):
        # Info panel
        info_panel = tk.Frame(parent, bg=BG_PANEL, padx=22, pady=14)
        info_panel.pack(fill="x", padx=4, pady=(12, 0))

        tk.Label(
            info_panel,
            text="📡  SCANNER RESI  →  CEK STOK GUDANG",
            font=("Segoe UI", 9, "bold"),
            fg=MUTED_COLOR, bg=BG_PANEL,
            anchor="w",
        ).pack(fill="x", pady=(0, 6))

        tk.Label(
            info_panel,
            text=(
                "Scan resi yang sudah dicetak. Sistem cari pesanan di DATA_SALES, "
                "lalu cek stok\nsetiap SKU di DATABASE_STIKER. Jika 'Auto Potong "
                "Stok' dicentang, qty yang\ntersedia langsung ditulis ke "
                "LOG_KELUAR (kolom B/C/D)."
            ),
            font=("Segoe UI", 8),
            fg=TEXT_SECONDARY, bg=BG_PANEL,
            justify="left", anchor="w",
        ).pack(fill="x")

        # Checkbox: Auto Potong Stok
        cb_outer = tk.Frame(parent, bg=BG_DARK, pady=8)
        cb_outer.pack(fill="x")

        cb = tk.Checkbutton(
            cb_outer,
            text=" Auto Potong Stok  (tulis LOG_KELUAR otomatis saat stok tersedia)",
            variable=self.auto_deduct_var,
            font=("Segoe UI", 9, "bold"),
            bg=BG_DARK, fg=ACCENT,
            selectcolor=BG_INPUT,
            activebackground=BG_DARK, activeforeground=ACCENT,
            cursor="hand2",
            command=self._on_auto_deduct_change,
        )
        cb.pack(anchor="w", padx=4)

        # Scanner input panel
        scan_panel = tk.Frame(parent, bg=BG_PANEL, padx=22, pady=14)
        scan_panel.pack(fill="x", padx=4, pady=(4, 0))

        tk.Label(
            scan_panel,
            text="📥  SCAN / KETIK RESI  (scanner barcode auto-Enter, atau ketik manual + Enter)",
            font=("Segoe UI", 8, "bold"),
            fg=TEXT_SECONDARY, bg=BG_PANEL,
            anchor="w",
        ).pack(fill="x", pady=(0, 6))

        self.scan_entry = tk.Entry(
            scan_panel,
            textvariable=self.scan_input,
            font=("Consolas", 14, "bold"),
            bg=BG_INPUT, fg=ACCENT,
            insertbackground=ACCENT,
            relief="flat", bd=0,
            highlightbackground=ACCENT, highlightthickness=2,
        )
        self.scan_entry.pack(fill="x", ipady=10)
        self.scan_entry.bind("<Return>", lambda _e: self._on_scan_submit())

        self.scan_status = tk.Label(
            scan_panel,
            text="Siap — silakan scan / tempel resi.",
            font=("Segoe UI", 8),
            fg=MUTED_COLOR, bg=BG_PANEL,
            anchor="w",
        )
        self.scan_status.pack(fill="x", pady=(6, 0))

        # Header + tombol bersihkan
        result_header = tk.Frame(parent, bg=BG_DARK, pady=8)
        result_header.pack(fill="x")

        tk.Label(
            result_header,
            text="HASIL SCAN",
            font=("Segoe UI", 8, "bold"),
            fg=MUTED_COLOR, bg=BG_DARK,
            anchor="w",
        ).pack(side="left")

        btn_clear_scan = tk.Button(
            result_header,
            text="Bersihkan",
            font=("Segoe UI", 8),
            bg=BTN_SECONDARY, fg=TEXT_SECONDARY,
            activebackground=BTN_SEC_HOVER, activeforeground=TEXT_PRIMARY,
            relief="flat", cursor="hand2",
            padx=10, pady=3,
            command=self._clear_scan_log,
        )
        btn_clear_scan.pack(side="right")
        self._bind_hover(btn_clear_scan, BTN_SECONDARY, BTN_SEC_HOVER)

        # Result text area
        result_box = tk.Frame(parent, bg=BG_INPUT, relief="flat",
                              highlightbackground=BORDER_COLOR, highlightthickness=1)
        result_box.pack(fill="both", expand=True, pady=(0, 4))

        self.scan_result_text = tk.Text(
            result_box,
            font=("Consolas", 11),
            bg=BG_INPUT, fg=TEXT_PRIMARY,
            relief="flat",
            padx=14, pady=10,
            state="disabled",
            wrap="word",
            cursor="arrow",
            spacing1=2, spacing3=2,
        )
        sb = tk.Scrollbar(result_box, command=self.scan_result_text.yview,
                          bg=BG_PANEL, troughcolor=BG_INPUT, width=12)
        self.scan_result_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.scan_result_text.pack(side="left", fill="both", expand=True)

        self.scan_result_text.tag_configure("success", foreground=SUCCESS_COLOR)
        self.scan_result_text.tag_configure("error",   foreground=ERROR_COLOR)
        self.scan_result_text.tag_configure("warning", foreground=WARNING_COLOR)
        self.scan_result_text.tag_configure("info",    foreground=INFO_COLOR)
        self.scan_result_text.tag_configure("muted",   foreground=MUTED_COLOR)
        self.scan_result_text.tag_configure("printed", foreground=TEXT_PRIMARY)
        self.scan_result_text.tag_configure(
            "header", foreground=ACCENT, font=("Consolas", 11, "bold"))

    def _on_notebook_tab_change(self, _event=None):
        try:
            tab_text = self.notebook.tab(self.notebook.select(), "text") or ""
        except Exception:
            return
        if "Cek Stok Resi" in tab_text:
            try:
                self.scan_entry.focus_set()
            except Exception:
                pass

    def _on_auto_deduct_change(self):
        cfg = load_config()
        cfg["auto_deduct"] = bool(self.auto_deduct_var.get())
        save_config(cfg)

    def _append_scan_text(self, level: str, message: str):
        self.scan_result_text.configure(state="normal")
        self.scan_result_text.insert("end", message + "\n", level)
        self.scan_result_text.see("end")
        self.scan_result_text.configure(state="disabled")

    def _clear_scan_log(self):
        self.scan_result_text.configure(state="normal")
        self.scan_result_text.delete("1.0", "end")
        self.scan_result_text.configure(state="disabled")
        self.scan_status.config(text="Siap — silakan scan / tempel resi.",
                                fg=MUTED_COLOR)
        try:
            self.scan_entry.focus_set()
        except Exception:
            pass

    def _on_scan_submit(self):
        resi = self.scan_input.get().strip()
        # Clear segera supaya scanner berikutnya bisa langsung mengetik
        self.scan_input.set("")
        if not resi:
            return

        webhook = self.webhook_url.get().strip()
        if not webhook:
            self._append_scan_text(
                "error",
                "❌ Webhook Google Sheet belum dikonfigurasi. "
                "Set di tab ⚙ Konfigurasi dulu."
            )
            self.scan_status.config(text="❌ Webhook belum diset",
                                    fg=ERROR_COLOR)
            return

        auto_deduct = bool(self.auto_deduct_var.get())
        self.scan_status.config(text=f"⏳  Mencari resi {resi} ...",
                                fg=INFO_COLOR)

        threading.Thread(
            target=self._do_scan_resi,
            args=(webhook, resi, auto_deduct),
            daemon=True,
        ).start()

    def _do_scan_resi(self, webhook: str, resi: str, auto_deduct: bool):
        """Worker thread: lookup_resi → optionally consume_stock."""
        # Buffer log dari modul (resi_checker / stock_reader) supaya
        # nyaru di scan_result_text, bukan ke log proses utama.
        scan_logs: list[tuple[str, str]] = []

        def cb(level, msg):
            scan_logs.append((level, msg))

        try:
            data = lookup_resi(webhook, resi, log_callback=cb)
        except Exception as e:
            self.after(0, self._on_scan_done, resi, "error",
                       [], False, scan_logs, str(e))
            return

        if data is None:
            self.after(0, self._on_scan_done, resi, "error",
                       [], False, scan_logs, "")
            return

        items = data.get("items") or []
        stock = data.get("stock") or {}

        if not items:
            self.after(0, self._on_scan_done, resi, "not_found",
                       [], False, scan_logs, "")
            return

        # Bangun rows dgn rencana potong (per SKU)
        rows: list[dict] = []
        deduct_items: list[dict] = []
        for it in items:
            sku = it["sku"]
            qty = it["qty"]
            avail = stock.get(sku.upper())
            taken_planned = 0
            if avail is None:
                rstatus = "no_db"
            elif avail <= 0:
                rstatus = "empty"
            elif avail >= qty:
                rstatus = "ok"
                taken_planned = qty
            else:
                rstatus = "partial"
                taken_planned = avail

            rows.append({
                "sku": sku,
                "qty": qty,
                "avail": avail,
                "status": rstatus,
                "taken_planned": taken_planned,
                "taken": 0,            # diisi setelah consume_stock
                "deduct_index": None,  # diisi kalau item dikirim ke server
            })

            if auto_deduct and taken_planned > 0:
                rows[-1]["deduct_index"] = len(deduct_items)
                deduct_items.append({
                    "sku": sku,
                    "qty": taken_planned,
                    "ket": resi,
                })

        # Panggil consume_stock kalau perlu
        if auto_deduct and deduct_items:
            try:
                consumed = consume_stock(webhook, deduct_items, log_callback=cb)
            except Exception as e:
                consumed = None
                scan_logs.append(("error", f"❌ consume_stock error: {e}"))

            if consumed is None:
                # Total failure — tandai semua rencana gagal
                for r in rows:
                    if r["deduct_index"] is not None:
                        r["status"] = "deduct_fail"
            else:
                for r in rows:
                    di = r["deduct_index"]
                    if di is None or di >= len(consumed):
                        continue
                    res = consumed[di]
                    if res.get("ok"):
                        r["taken"] = int(res.get("taken", r["taken_planned"]))
                        r["sisa_after"] = res.get("sisa")
                    else:
                        r["status"] = "deduct_fail"
                        r["fail_msg"] = res.get("message", "unknown")

        self.after(0, self._on_scan_done, resi, "ok",
                   rows, auto_deduct, scan_logs, "")

    def _on_scan_done(
        self,
        resi: str,
        status: str,
        rows: list,
        auto_deduct: bool,
        scan_logs: list,
        error_msg: str,
    ):
        # Header per scan
        self._append_scan_text("muted", "")
        self._append_scan_text("header", f"📋  RESI: {resi}")
        self._append_scan_text("muted", "─" * 70)

        if status == "error":
            for level, msg in scan_logs:
                self._append_scan_text(level, f"  {msg}")
            if error_msg:
                self._append_scan_text("error", f"  ❌ {error_msg}")
            self.scan_status.config(text="❌  Lookup resi gagal",
                                    fg=ERROR_COLOR)
            self._refocus_scan_entry()
            return

        if status == "not_found":
            self._append_scan_text(
                "warning",
                "  ⚠️  Resi tidak ditemukan di DATA_SALES."
            )
            self._append_scan_text(
                "muted",
                "      (Pastikan operator sudah klik 'Mulai Sortir' "
                "supaya DATA_SALES ter-update dulu.)"
            )
            self.scan_status.config(
                text=f"⚠️  Resi {resi} tidak ada di DATA_SALES",
                fg=WARNING_COLOR,
            )
            self._refocus_scan_entry()
            return

        # status == "ok" → tampilkan tiap row
        ok_count = 0
        empty_count = 0
        deducted_total = 0

        for r in rows:
            sku = r["sku"]
            qty = r["qty"]
            avail = r["avail"]
            rstatus = r["status"]

            if rstatus == "no_db":
                self._append_scan_text(
                    "error",
                    f"  ❌ {sku}  butuh {qty}  →  TIDAK ADA di DATABASE_STIKER"
                )
                empty_count += 1
            elif rstatus == "empty":
                self._append_scan_text(
                    "error",
                    f"  ❌ {sku}  butuh {qty}  →  STOK KOSONG (sisa 0)"
                )
                empty_count += 1
            elif rstatus == "ok":
                if auto_deduct:
                    sisa_after = r.get("sisa_after")
                    if sisa_after is None:
                        sisa_after = (avail or 0) - r["taken"]
                    self._append_scan_text(
                        "success",
                        f"  ✅ {sku}  butuh {qty}  →  POTONG {r['taken']}  "
                        f"(sisa setelah: {sisa_after})"
                    )
                    deducted_total += r["taken"]
                else:
                    self._append_scan_text(
                        "success",
                        f"  ✅ {sku}  butuh {qty}  →  STOK TERSEDIA {avail}  "
                        f"[tidak dipotong — checkbox off]"
                    )
                ok_count += 1
            elif rstatus == "partial":
                if auto_deduct:
                    sisa_after = r.get("sisa_after")
                    if sisa_after is None:
                        sisa_after = (avail or 0) - r["taken"]
                    self._append_scan_text(
                        "warning",
                        f"  ⚠️  {sku}  butuh {qty}  →  POTONG SEBAGIAN {r['taken']} "
                        f"(stok cuma {avail}, sisa setelah: {sisa_after})"
                    )
                    deducted_total += r["taken"]
                else:
                    self._append_scan_text(
                        "warning",
                        f"  ⚠️  {sku}  butuh {qty}  →  STOK CUMA {avail}  "
                        f"[tidak dipotong — checkbox off]"
                    )
                empty_count += 1
            elif rstatus == "deduct_fail":
                msg = r.get("fail_msg", "unknown")
                self._append_scan_text(
                    "error",
                    f"  ❌ {sku}  butuh {qty}  →  GAGAL POTONG ({msg})"
                )
                empty_count += 1

        # Tampilkan log dari modul (warning consume_stock dll)
        for level, msg in scan_logs:
            # Skip success log konsume_stock yg redundant — info utama sudah di rows
            if level in ("success", "info"):
                continue
            self._append_scan_text(level, f"      {msg}")

        # Status bar bawah scan input
        if auto_deduct and deducted_total > 0:
            summary = (f"✅ {ok_count} OK  |  {empty_count} kurang  |  "
                       f"📦 {deducted_total} pcs dipotong dari gudang")
            color = SUCCESS_COLOR if empty_count == 0 else WARNING_COLOR
        else:
            summary = (f"✅ {ok_count} tersedia  |  {empty_count} kurang/kosong  |  "
                       f"{len(rows)} total SKU")
            color = SUCCESS_COLOR if empty_count == 0 else WARNING_COLOR
        self.scan_status.config(text=summary, fg=color)

        self._refocus_scan_entry()

    def _refocus_scan_entry(self):
        try:
            self.scan_entry.focus_set()
        except Exception:
            pass

    # ── Post-update notification ──────────────────────────────────────────────
    def _check_post_update_notification(self):
        """
        Kalau last_known_version di config berbeda dari __version__ saat ini,
        artinya kita baru di-update oleh run.bat. Tampilkan popup konfirmasi
        dengan release notes (dibaca dari .update_backup/_manifest.json).
        """
        cfg = load_config()
        last_known = cfg.get("last_known_version")
        current = __version__

        if last_known is None:
            # First launch — record dan selesai (tidak ada update event)
            cfg["last_known_version"] = current
            save_config(cfg)
            return

        if last_known == current:
            return  # Tidak ada update sejak session terakhir

        # We just got updated from `last_known` → `current`
        notes = self._read_update_release_notes()

        # Log ke pane (selalu terlihat kalau user buka log)
        self._log("success", f"✅  Update berhasil: v{last_known}  →  v{current}")
        for n in notes:
            self._log("info", f"    • {n}")

        # Update last_known DULU supaya popup tidak muncul lagi di next launch
        # (meskipun user nutup popup tanpa klik OK)
        cfg["last_known_version"] = current
        save_config(cfg)

        # Popup — delay sedikit supaya muncul di atas window yang sudah visible
        title = "Update Berhasil"
        body = f"Aplikasi berhasil di-update ke versi terbaru.\n\n    v{last_known}   →   v{current}"
        if notes:
            body += "\n\nPerubahan di versi ini:"
            for n in notes:
                body += f"\n  •  {n}"
        body += "\n\nKlik OK untuk mulai menggunakan aplikasi."
        self.after(300, lambda: messagebox.showinfo(title, body))

    def _read_update_release_notes(self) -> list:
        """Baca release_notes dari .update_backup/_manifest.json kalau ada."""
        project_dir = os.path.dirname(os.path.abspath(__file__))
        backup_manifest = os.path.join(project_dir, ".update_backup", "_manifest.json")
        if not os.path.isfile(backup_manifest):
            return []
        try:
            with open(backup_manifest, "r", encoding="utf-8") as f:
                m = json.load(f)
            notes = m.get("release_notes")
            if isinstance(notes, list):
                return [n for n in notes if isinstance(n, str) and n.strip()]
        except Exception:
            pass
        return []

    # ── Update banner UI ──────────────────────────────────────────────────────
    def _build_update_banner(self):
        """Frame kecil di atas footer. Tersembunyi sampai ada update berjalan."""
        self.update_banner = tk.Frame(self, bg=BG_PANEL, pady=6, padx=12)
        # Tidak di-pack — hidden by default

        self._banner_icon = tk.Label(
            self.update_banner, text="", font=("Segoe UI Emoji", 12),
            bg=BG_PANEL, fg=ACCENT,
        )
        self._banner_icon.pack(side="left", padx=(0, 6))

        self._banner_label = tk.Label(
            self.update_banner, text="", font=("Segoe UI", 9),
            bg=BG_PANEL, fg=TEXT_PRIMARY, anchor="w",
        )
        self._banner_label.pack(side="left", fill="x", expand=True)

        self._banner_btn = tk.Button(
            self.update_banner, text="Batal",
            font=("Segoe UI", 8),
            bg=BTN_SECONDARY, fg=TEXT_PRIMARY,
            activebackground=BTN_SEC_HOVER, activeforeground=TEXT_PRIMARY,
            relief="flat", cursor="hand2", padx=10, pady=3,
            command=self._on_banner_action,
        )
        self._banner_btn.pack(side="right")
        self._bind_hover(self._banner_btn, BTN_SECONDARY, BTN_SEC_HOVER)

    def _update_banner_state(self, state: str, pct=None):
        """Thread-safe wrapper — dipanggil dari updater thread."""
        self.after(0, self._apply_banner_state, state, pct)

    def _apply_banner_state(self, state: str, pct):
        """UI thread — apply state ke banner widget."""
        if state == "hidden":
            if self._banner_state != "hidden":
                self.update_banner.pack_forget()
                self._banner_state = "hidden"
            return

        # Tampilkan banner (di atas footer)
        if self._banner_state == "hidden":
            self.update_banner.pack(fill="x", before=self.footer_frame, padx=20, pady=(0, 4))

        if state == "checking":
            self._banner_icon.configure(text="🔍")
            self._banner_label.configure(text="Memeriksa pembaruan...")
            self._banner_btn.configure(text="", state="disabled")
        elif state == "downloading":
            self._banner_icon.configure(text="⬇")
            if pct is not None:
                blocks = max(0, min(10, pct // 10))
                bar = "■" * blocks + "□" * (10 - blocks)
                self._banner_label.configure(text=f"Mengunduh update  {bar}  {pct}%")
            else:
                self._banner_label.configure(text="Mengunduh update...")
            self._banner_btn.configure(text="Batal", state="normal")
        elif state == "validating":
            self._banner_icon.configure(text="🔒")
            self._banner_label.configure(text="Memvalidasi file update...")
            self._banner_btn.configure(text="", state="disabled")
        elif state == "ready":
            self._banner_icon.configure(text="✔")
            if pct is not None and pct > 0:
                self._banner_label.configure(
                    text=f"Update siap. Mulai ulang dalam {pct} detik..."
                )
            else:
                self._banner_label.configure(text="Update siap. Mulai ulang aplikasi...")
            self._banner_btn.configure(text="Tunda", state="normal")
        elif state == "cancelled":
            self._banner_icon.configure(text="✖")
            self._banner_label.configure(text="Update dibatalkan.")
            self._banner_btn.configure(text="Tutup", state="normal")
            self.after(2500, lambda: self._apply_banner_state("hidden", None))

        self._banner_state = state

    def _on_banner_action(self):
        """Dispatch tombol banner sesuai state saat ini."""
        if self._banner_state == "downloading":
            self._on_banner_cancel_download()
        elif self._banner_state == "ready":
            self._on_banner_postpone_restart()
        elif self._banner_state == "cancelled":
            self._apply_banner_state("hidden", None)

    def _on_banner_cancel_download(self):
        if self._active_orchestrator is not None:
            self._active_orchestrator.cancel()

    def _on_banner_postpone_restart(self):
        self._restart_cancelled = True
        self._apply_banner_state("hidden", None)
        self._log("info", "ℹ️  Update ditunda — akan dipasang saat aplikasi dibuka lagi.")

    # ── Update check entry point ──────────────────────────────────────────────
    def _start_update_check(self, force: bool = False, done_callback=None):
        """
        Spawn background thread yang jalankan UpdateOrchestrator.

        done_callback: optional fn(was_cancelled: bool) — dipanggil di UI thread
        setelah orch.run() selesai. Dipakai oleh tombol Start untuk lanjut sortir
        kalau tidak ada update.
        """
        if self._active_orchestrator is not None:
            # Sudah ada cek yang jalan — kalau pemanggil pasang callback,
            # informasikan bahwa cek tidak dilakukan oleh kita (treat as not-cancelled).
            if done_callback is not None:
                self.after(0, done_callback, False)
            return

        project_root = os.path.dirname(os.path.abspath(__file__))
        orch = UpdateOrchestrator(
            project_root=project_root,
            installed_version=__version__,
            load_config_fn=load_config,
            save_config_fn=save_config,
            log=self._log,
            banner=self._update_banner_state,
            on_ready_to_restart=self._schedule_restart,
            force=force,
        )
        self._active_orchestrator = orch

        def _runner():
            cancelled = False
            try:
                orch.run()
                cancelled = orch.cancel_event.is_set()
            finally:
                self.after(0, self._clear_active_orchestrator)
                if done_callback is not None:
                    self.after(0, done_callback, cancelled)

        threading.Thread(target=_runner, daemon=True).start()

    def _clear_active_orchestrator(self):
        self._active_orchestrator = None

    # ── Restart orchestration ─────────────────────────────────────────────────
    def _schedule_restart(self, new_version: str):
        """Dipanggil dari updater thread saat .update_pending/ siap."""
        self.after(0, self._begin_countdown, new_version)

    def _begin_countdown(self, new_version: str):
        self._restart_cancelled = False
        self._do_countdown(new_version, 3)

    def _do_countdown(self, new_version: str, remaining: int):
        if self._restart_cancelled:
            return
        if remaining <= 0:
            self._spawn_run_bat_detached()
            return
        self._apply_banner_state("ready", remaining)
        self.after(1000, self._do_countdown, new_version, remaining - 1)

    def _spawn_run_bat_detached(self):
        """
        Spawn launcher sebagai detached process lalu destroy window.
        Prefer run.vbs (cara user normally launch) supaya restart konsisten —
        kalau tidak ada, fallback ke run.bat dengan 'hidden' arg.
        """
        project_dir = os.path.dirname(os.path.abspath(__file__))
        run_vbs = os.path.join(project_dir, "run.vbs")
        run_bat = os.path.join(project_dir, "run.bat")
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        CREATE_NO_WINDOW = 0x08000000
        try:
            if os.path.isfile(run_vbs):
                # wscript runs the VBS without a console window inherently
                subprocess.Popen(
                    ["wscript", run_vbs],
                    creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                    close_fds=True,
                    cwd=project_dir,
                )
            else:
                subprocess.Popen(
                    ["cmd", "/c", run_bat, "hidden"],
                    creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW,
                    close_fds=True,
                    cwd=project_dir,
                )
        except Exception as e:
            self._log("error", f"❌  Gagal memulai ulang aplikasi: {e}")
            self._apply_banner_state("hidden", None)
            return
        self.destroy()
        sys.exit(0)


# ─── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()
