"""
preflight.py — Dipanggil oleh run.bat SEBELUM `pythonw app.py`.

Tujuan: cek GitHub Releases, download update kalau ada versi baru,
stage ke `.update_pending/` supaya run.bat langsung apply di step berikutnya.

Berbeda dari update check dalam app (via Ctrl+Shift+U): preflight ini jalan
di foreground sebelum GUI muncul, jadi karyawan cuma lihat satu kali window
buka (sudah di versi terbaru). Tidak perlu restart cycle.

Exit code SELALU 0 — apapun yang terjadi (GitHub offline, disk full, dll),
kita tidak mau memblokir launch aplikasi.
"""

from __future__ import annotations

import os
import sys

# Pastikan module di folder ini bisa di-import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json  # noqa: E402
from updater import UpdateOrchestrator  # noqa: E402
from version import __version__  # noqa: E402


CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_config(data: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ── Console callbacks (no Tk) ─────────────────────────────────────────────────
_LEVEL_ICON = {
    "success": "[OK]    ",
    "error":   "[ERROR] ",
    "warning": "[WARN]  ",
    "info":    "[INFO]  ",
}

_BANNER_PROGRESS_LAST = {"pct": -10}


def console_log(level: str, message: str) -> None:
    icon = _LEVEL_ICON.get(level, "        ")
    try:
        # Strip emoji untuk console Windows yang encoding-nya cp437/cp1252
        safe = message.encode("ascii", "ignore").decode("ascii").strip()
        if not safe:
            safe = message
        print(f"{icon} {safe}", flush=True)
    except Exception:
        pass


def console_banner(state: str, pct) -> None:
    # Print progress setiap 10% (supaya tidak spam console saat download)
    if state == "downloading" and isinstance(pct, int):
        step = (pct // 10) * 10
        if step > _BANNER_PROGRESS_LAST["pct"]:
            _BANNER_PROGRESS_LAST["pct"] = step
            print(f"         Progress: {step}%", flush=True)
    elif state in ("checking", "validating"):
        _BANNER_PROGRESS_LAST["pct"] = -10  # reset


def noop_on_ready(_new_version: str) -> None:
    # Kita JANGAN restart — kita ARE run.bat, about to launch aplikasi.
    # Yang penting .update_pending/ sudah terbuat; run.bat step berikutnya yang apply.
    pass


def main() -> int:
    cfg = load_config()
    if not (cfg.get("github_repo") or "").strip():
        # Silent skip — employee tidak perlu tahu
        return 0

    print("[Preflight] Cek update di GitHub...", flush=True)

    try:
        orch = UpdateOrchestrator(
            project_root=os.path.dirname(os.path.abspath(__file__)),
            installed_version=__version__,
            load_config_fn=load_config,
            save_config_fn=save_config,
            log=console_log,
            banner=console_banner,
            on_ready_to_restart=noop_on_ready,
            force=True,   # verbose mode di console
        )
        orch.run()  # never raises
    except Exception as e:
        # Paranoid fallback — orch.run() sudah internally safe tapi jaga-jaga
        print(f"[Preflight] Error tak terduga: {e}", flush=True)

    print("[Preflight] Selesai.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
