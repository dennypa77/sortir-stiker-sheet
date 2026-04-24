"""
updater.py
Auto-update logic untuk Sortir Stiker Pack.

Sumber update: **GitHub Releases**.
- Tiap kali aplikasi di-launch, orchestrator cek `/releases/latest` di repo.
- Kalau tag_name (semver) lebih baru dari __version__, download asset ZIP,
  validasi, extract, lalu atomic-rename ke .update_pending/ supaya run.bat
  apply di launch berikutnya.
- Cancellation lewat threading.Event. Cancel di tengah download = aborted.

Zero Tk import. UI interaction via callbacks (log, banner, on_ready).
UpdateOrchestrator.run() never raises — semua error ditangkap dan dilog ke file.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import socket
import threading
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Callable, Optional

# ── Type aliases ──────────────────────────────────────────────────────────────
LogCallback = Callable[[str, str], None]                # (level, message)
BannerCallback = Callable[[str, Optional[int]], None]   # (state, pct)
ReadyCallback = Callable[[str], None]                   # (new_version)
LoadConfigFn = Callable[[], dict]
SaveConfigFn = Callable[[dict], None]

# ── Konstanta ─────────────────────────────────────────────────────────────────
STAGING_DIR = ".update_staging"
PENDING_DIR = ".update_pending"
LOGS_DIR = ".update_logs"
LOG_FILE = "update.log"
REQUIRED_FILES = {"app.py", "file_processor.py", "sheets_sync.py", "version.py", "requirements.txt"}
INTERNAL_MANIFEST_NAME = "_manifest.json"
CHUNK_SIZE = 65536  # 64 KB

GITHUB_API_TIMEOUT = 10
GITHUB_DOWNLOAD_TIMEOUT = 30
GITHUB_USER_AGENT = "SortirStikerPack-Updater/1.0"
ASSET_NAME_PREFIX = "sortir-stiker-pack-"
ASSET_NAME_SUFFIX = ".zip"


# ── Pure helpers ──────────────────────────────────────────────────────────────
_VERSION_RE = re.compile(r"^\d+(\.\d+)*$")


def parse_version(s: str) -> tuple[int, ...]:
    """'v1.10.2' → (1, 10, 2). Invalid → ()."""
    s = (s or "").strip().lstrip("vV")
    if not _VERSION_RE.match(s):
        return ()
    return tuple(int(p) for p in s.split("."))


def compare_versions(a: str, b: str) -> int:
    """Return -1 / 0 / 1. Invalid input → 0."""
    ta, tb = parse_version(a), parse_version(b)
    if not ta or not tb:
        return 0
    maxlen = max(len(ta), len(tb))
    ta += (0,) * (maxlen - len(ta))
    tb += (0,) * (maxlen - len(tb))
    return (ta > tb) - (ta < tb)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_safe_zip_names(zip_path: str) -> bool:
    """Reject ZIP dengan path absolute atau '..' (zip slip prevention)."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                if not name:
                    continue
                if name.startswith(("/", "\\")):
                    return False
                if ":" in name:
                    return False
                normalized = os.path.normpath(name).replace("\\", "/")
                if normalized.startswith(".."):
                    return False
                if "/../" in normalized:
                    return False
    except (zipfile.BadZipFile, OSError):
        return False
    return True


def validate_extracted_tree(extract_dir: str, expected_version: str) -> bool:
    """Pastikan file wajib ada dan version.py berisi versi yang match."""
    try:
        entries = set(os.listdir(extract_dir))
    except OSError:
        return False
    if not REQUIRED_FILES.issubset(entries):
        return False
    version_path = os.path.join(extract_dir, "version.py")
    try:
        with open(version_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return False
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
    if not m:
        return False
    return compare_versions(m.group(1), expected_version) == 0


def parse_release_notes(body: str) -> list[str]:
    """
    Parse GitHub release body (markdown) jadi list bullet.
    Support bullet style: `- `, `* `, `• `. Fallback: 5 non-empty lines pertama.
    """
    if not body:
        return []
    notes = []
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith(("- ", "* ", "• ")):
            notes.append(line[2:].strip())
        elif line.startswith(("-", "*", "•")) and len(line) > 1 and not line[1].isalnum():
            notes.append(line[1:].strip())
    if not notes and body.strip():
        notes = [ln.strip() for ln in body.splitlines() if ln.strip()][:5]
    return [n for n in notes if n]


def _build_github_headers(token: Optional[str], accept_json: bool = True) -> dict:
    headers = {"User-Agent": GITHUB_USER_AGENT}
    if accept_json:
        headers["Accept"] = "application/vnd.github+json"
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def fetch_latest_release(repo: str, token: Optional[str] = None,
                         timeout: int = GITHUB_API_TIMEOUT) -> Optional[dict]:
    """
    GET https://api.github.com/repos/{repo}/releases/latest

    Return normalized dict atau None kalau gagal.
        {
            "latest_version": "1.0.1",            # dari tag_name, tanpa 'v'
            "tag_name": "v1.0.1",
            "release_date": "2026-04-24",
            "release_notes": [..],
            "release_notes_raw": str,
            "asset_url": str (browser_download_url),
            "asset_api_url": str (untuk private repo via API),
            "asset_name": str,
            "asset_size": int,
        }
    """
    if not repo or "/" not in repo:
        return None

    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(url, headers=_build_github_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except (urllib.error.URLError, urllib.error.HTTPError,
            socket.timeout, json.JSONDecodeError, ConnectionError, OSError):
        return None

    if not isinstance(data, dict):
        return None

    tag = (data.get("tag_name") or "").strip()
    version = tag.lstrip("vV")
    if parse_version(version) == ():
        return None

    assets = data.get("assets") or []
    if not isinstance(assets, list):
        return None

    # Prefer asset dengan naming convention `sortir-stiker-pack-*.zip`
    chosen = None
    for a in assets:
        if not isinstance(a, dict):
            continue
        name = a.get("name") or ""
        if name.startswith(ASSET_NAME_PREFIX) and name.endswith(ASSET_NAME_SUFFIX):
            chosen = a
            break
    if chosen is None:
        # Fallback: asset *.zip pertama
        for a in assets:
            if isinstance(a, dict) and (a.get("name") or "").endswith(ASSET_NAME_SUFFIX):
                chosen = a
                break
    if chosen is None:
        return None

    body = data.get("body") or ""
    published = (data.get("published_at") or "")[:10]

    return {
        "latest_version": version,
        "tag_name": tag,
        "release_date": published or "?",
        "release_notes_raw": body,
        "release_notes": parse_release_notes(body),
        "asset_url": chosen.get("browser_download_url") or "",
        "asset_api_url": chosen.get("url") or "",
        "asset_name": chosen.get("name") or "",
        "asset_size": int(chosen.get("size") or 0),
    }


def download_to_file(
    url: str,
    dst_path: str,
    token: Optional[str] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    cancel_cb: Optional[Callable[[], bool]] = None,
    timeout: int = GITHUB_DOWNLOAD_TIMEOUT,
) -> tuple[bool, int]:
    """
    Download URL ke dst_path. Return (success, total_bytes_copied).
    Kalau cancel_cb() return True di tengah jalan → stop, return (False, partial).
    """
    headers = _build_github_headers(token, accept_json=False)
    # Kalau ada token, URL asset API perlu accept octet-stream untuk unduh binary
    if token and "api.github.com" in url:
        headers["Accept"] = "application/octet-stream"

    req = urllib.request.Request(url, headers=headers)
    copied = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            try:
                total = int(resp.headers.get("Content-Length", "0"))
            except (TypeError, ValueError):
                total = 0
            with open(dst_path, "wb") as f:
                while True:
                    if cancel_cb and cancel_cb():
                        return False, copied
                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    copied += len(chunk)
                    if progress_cb and total > 0:
                        progress_cb(copied, total)
        return True, copied
    except (urllib.error.URLError, urllib.error.HTTPError,
            socket.timeout, ConnectionError, OSError):
        return False, copied


# ── File logger (rotating, untuk debug) ───────────────────────────────────────
def _get_file_logger(project_root: str) -> logging.Logger:
    logger = logging.getLogger("sortir_updater")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        logs_dir = os.path.join(project_root, LOGS_DIR)
        os.makedirs(logs_dir, exist_ok=True)
        handler = RotatingFileHandler(
            os.path.join(logs_dir, LOG_FILE),
            maxBytes=256 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
    except OSError:
        logger.addHandler(logging.NullHandler())
    return logger


def cancel_pending_update(project_root: str) -> bool:
    """Hapus .update_pending/. Return True jika sukses."""
    pending = os.path.join(project_root, PENDING_DIR)
    try:
        if os.path.exists(pending):
            shutil.rmtree(pending, ignore_errors=True)
        return True
    except Exception:
        return False


# ── Orkestrator ───────────────────────────────────────────────────────────────
class UpdateOrchestrator:
    """
    Dipakai oleh background thread. run() never raises.
    UI marshalling adalah tanggung jawab callback, bukan kita.

    `force`: True → log tiap outcome (up-to-date, offline, error). Dipakai oleh
    manual trigger (Ctrl+Shift+U) supaya user dapat feedback.
    """

    def __init__(
        self,
        project_root: str,
        installed_version: str,
        load_config_fn: LoadConfigFn,
        save_config_fn: SaveConfigFn,
        log: LogCallback,
        banner: BannerCallback,
        on_ready_to_restart: ReadyCallback,
        force: bool = False,
    ):
        self.project_root = project_root
        self.installed_version = installed_version
        self.load_config_fn = load_config_fn
        self.save_config_fn = save_config_fn
        self.log_cb = log
        self.banner_cb = banner
        self.on_ready_cb = on_ready_to_restart
        self.force = force
        self.cancel_event = threading.Event()
        self.file_logger = _get_file_logger(project_root)

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        try:
            self._run_inner()
        except Exception:
            self.file_logger.exception("Unexpected error di updater")
            self._safe_banner("hidden", None)

    # ── safe wrappers ─────────────────────────────────────────────────────────
    def _is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def _safe_log(self, level: str, message: str) -> None:
        try:
            self.log_cb(level, message)
        except Exception:
            pass

    def _log_if_force(self, level: str, message: str) -> None:
        if self.force:
            self._safe_log(level, message)

    def _safe_banner(self, state: str, pct: Optional[int] = None) -> None:
        try:
            self.banner_cb(state, pct)
        except Exception:
            pass

    # ── core flow ─────────────────────────────────────────────────────────────
    def _run_inner(self) -> None:
        try:
            cfg = self.load_config_fn() or {}
        except Exception:
            cfg = {}

        repo = (cfg.get("github_repo") or "").strip()
        token = cfg.get("github_token") or None

        if not repo or "/" not in repo:
            self._log_if_force(
                "warning",
                "⚠️  Cek update dilewati — 'github_repo' belum diset di config.json."
                ' (Contoh: "owner/nama-repo")'
            )
            self.file_logger.info("github_repo tidak dikonfigurasi.")
            return

        self._log_if_force("info", f"ℹ️  Memeriksa pembaruan di GitHub ({repo})...")
        self._safe_banner("checking", None)

        release = fetch_latest_release(repo, token)
        if release is None:
            self._log_if_force(
                "info",
                "ℹ️  Tidak dapat menghubungi GitHub (offline?) atau release belum ada."
            )
            self.file_logger.warning("fetch_latest_release gagal: repo=%s", repo)
            self._safe_banner("hidden", None)
            return

        latest = release["latest_version"]
        cmp_result = compare_versions(latest, self.installed_version)

        if cmp_result == 0:
            self._log_if_force("success", f"✅  Aplikasi up-to-date (v{self.installed_version}).")
            self.file_logger.info("Up-to-date: v%s", self.installed_version)
            self._safe_banner("hidden", None)
            return

        if cmp_result < 0:
            self._log_if_force(
                "warning",
                f"⚠️  Versi remote (v{latest}) lebih tua dari terpasang. Dilewati."
            )
            self.file_logger.warning("Remote lebih tua: %s < %s", latest, self.installed_version)
            self._safe_banner("hidden", None)
            return

        # Update tersedia
        release_date = release.get("release_date", "?")
        self._safe_log("info", f"ℹ️  Update v{latest} tersedia (rilis {release_date}).")
        for note in release.get("release_notes", []):
            self._safe_log("info", f"    • {note}")

        if self._is_cancelled():
            self._safe_banner("cancelled", None)
            return

        staging = os.path.join(self.project_root, STAGING_DIR)
        pending = os.path.join(self.project_root, PENDING_DIR)

        if os.path.exists(staging):
            shutil.rmtree(staging, ignore_errors=True)
        try:
            os.makedirs(staging, exist_ok=True)
        except OSError as e:
            self.file_logger.error("Staging dir gagal: %s", e)
            self._safe_log("error", "❌  Gagal menyiapkan folder update.")
            self._safe_banner("hidden", None)
            return

        local_zip = os.path.join(staging, "update.zip")

        # Download — kalau private repo, pakai asset_api_url (otherwise browser_download_url)
        download_url = release["asset_url"]
        if token and release.get("asset_api_url"):
            download_url = release["asset_api_url"]

        asset_size = release.get("asset_size") or 0
        self._safe_banner("downloading", 0)
        size_label = f"{asset_size} byte" if asset_size else "ukuran tidak diketahui"
        self._safe_log("info", f"ℹ️  Mengunduh {release.get('asset_name')} ({size_label})...")

        def _progress(current: int, total: int) -> None:
            if total <= 0:
                return
            pct = int((current / total) * 100)
            self._safe_banner("downloading", min(99, pct))

        ok, copied = download_to_file(
            download_url, local_zip, token=token,
            progress_cb=_progress, cancel_cb=self._is_cancelled,
        )

        if self._is_cancelled():
            shutil.rmtree(staging, ignore_errors=True)
            self._safe_log("info", "ℹ️  Update dibatalkan.")
            self._safe_banner("cancelled", None)
            return

        if not ok:
            shutil.rmtree(staging, ignore_errors=True)
            self._safe_log("error", "❌  Gagal mengunduh update. Coba lagi nanti.")
            self._safe_banner("hidden", None)
            return

        # Sanity check size
        if asset_size and os.path.getsize(local_zip) != asset_size:
            self.file_logger.warning(
                "Size mismatch: got %d, expected %d", os.path.getsize(local_zip), asset_size
            )
            shutil.rmtree(staging, ignore_errors=True)
            self._safe_log("error", "❌  File update tidak lengkap.")
            self._safe_banner("hidden", None)
            return

        # Validate ZIP
        self._safe_banner("validating", None)
        if not ensure_safe_zip_names(local_zip):
            self.file_logger.error("ZIP path tidak aman.")
            self._safe_log("error", "❌  File update ditolak (keamanan).")
            shutil.rmtree(staging, ignore_errors=True)
            self._safe_banner("hidden", None)
            return

        try:
            with zipfile.ZipFile(local_zip) as zf:
                bad = zf.testzip()
                if bad is not None:
                    raise zipfile.BadZipFile(f"corrupt: {bad}")
        except (zipfile.BadZipFile, OSError) as e:
            self.file_logger.error("ZIP testzip gagal: %s", e)
            self._safe_log("error", "❌  File update korup.")
            shutil.rmtree(staging, ignore_errors=True)
            self._safe_banner("hidden", None)
            return

        # Extract
        extract_dir = os.path.join(staging, "extracted")
        try:
            with zipfile.ZipFile(local_zip) as zf:
                zf.extractall(extract_dir)
        except (zipfile.BadZipFile, OSError) as e:
            self.file_logger.error("Extract gagal: %s", e)
            self._safe_log("error", "❌  Gagal ekstrak file update.")
            shutil.rmtree(staging, ignore_errors=True)
            self._safe_banner("hidden", None)
            return

        # Validate tree
        if not validate_extracted_tree(extract_dir, latest):
            self.file_logger.error("Extracted tree tidak valid.")
            self._safe_log("error", "❌  File update tidak lengkap atau versi tidak match tag.")
            shutil.rmtree(staging, ignore_errors=True)
            self._safe_banner("hidden", None)
            return

        # Write internal manifest (dipakai UI untuk popup post-update + run.bat audit)
        internal_manifest = {
            "latest_version": latest,
            "tag_name": release.get("tag_name"),
            "release_date": release_date,
            "release_notes": release.get("release_notes", []),
            "release_notes_raw": release.get("release_notes_raw", ""),
            "staged_at": self._now_iso(),
            "from_version": self.installed_version,
            "source": "github",
            "repo": repo,
        }
        try:
            with open(os.path.join(extract_dir, INTERNAL_MANIFEST_NAME), "w", encoding="utf-8") as f:
                json.dump(internal_manifest, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

        # Atomic rename
        if os.path.exists(pending):
            shutil.rmtree(pending, ignore_errors=True)
        try:
            os.rename(staging, pending)
        except OSError as e:
            self.file_logger.error("Rename ke pending gagal: %s", e)
            self._safe_log("error", "❌  Gagal menyiapkan update final.")
            shutil.rmtree(staging, ignore_errors=True)
            self._safe_banner("hidden", None)
            return

        self._safe_log("success", f"✅  Update v{latest} siap dipasang.")
        self.file_logger.info("Update v%s staged dari %s", latest, repo)
        self._safe_banner("ready", None)
        try:
            self.on_ready_cb(latest)
        except Exception:
            self.file_logger.exception("on_ready callback error")

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()
