"""
release.py — Build release artifact untuk Sortir Stiker Pack.

Sumber update sekarang adalah **GitHub Releases**.
Script ini:
  1. Bump version.py ke versi baru
  2. Build dist/sortir-stiker-pack-X.Y.Z.zip dengan 5 file package
  3. Print instruksi publish ke GitHub (via `gh` CLI atau web UI)

Usage:
    python release.py 1.1.0 --notes "Tambah fitur X" "Perbaikan bug Y"
    python release.py 1.1.0 --notes "..." --dry-run
    python release.py 1.2.0 --notes "..." --publish   (auto-publish via gh CLI)

Dry-run → output ke _test_updates/, version.py TIDAK dimodifikasi.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
PACKAGE_FILES = [
    "app.py",
    "file_processor.py",
    "sheets_sync.py",
    "stock_reader.py",
    "updater.py",
    "version.py",
    "requirements.txt",
]

PROJECT_ROOT = Path(__file__).resolve().parent
VERSION_FILE = PROJECT_ROOT / "version.py"


def parse_semver(s: str) -> tuple[int, int, int]:
    if not VERSION_RE.match(s):
        raise ValueError(f"Versi harus format semver X.Y.Z: {s!r}")
    parts = s.split(".")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def read_current_version() -> str:
    content = VERSION_FILE.read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
    if not m:
        raise RuntimeError("Tidak bisa baca __version__ dari version.py")
    return m.group(1).strip()


def write_version(new_version: str) -> None:
    VERSION_FILE.write_text(f'__version__ = "{new_version}"\n', encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_zip(new_version: str, out_dir: Path) -> Path:
    missing = [f for f in PACKAGE_FILES if not (PROJECT_ROOT / f).exists()]
    if missing:
        raise FileNotFoundError(f"File package tidak ditemukan: {missing}")

    out_dir.mkdir(parents=True, exist_ok=True)
    zip_name = f"sortir-stiker-pack-{new_version}.zip"
    zip_path = out_dir / zip_name

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in PACKAGE_FILES:
            zf.write(PROJECT_ROOT / f, arcname=f)

    return zip_path


def gh_cli_available() -> bool:
    try:
        subprocess.run(["gh", "--version"], capture_output=True, check=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def publish_via_gh(new_version: str, zip_path: Path, notes: list[str]) -> bool:
    """Jalankan `gh release create`. Return True kalau sukses."""
    tag = f"v{new_version}"
    # Gabungkan notes jadi markdown bullets
    body = "\n".join(f"- {n}" for n in notes)
    try:
        subprocess.run([
            "gh", "release", "create", tag,
            str(zip_path),
            "--title", f"Release {tag}",
            "--notes", body,
        ], check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"\n⚠️  gh release create gagal (exit {e.returncode})")
        print("     Pastikan sudah `gh auth login` dan repo sudah benar.")
        return False
    except FileNotFoundError:
        print("\n⚠️  gh CLI tidak ditemukan.")
        return False


def print_publish_instructions(new_version: str, zip_path: Path, notes: list[str]) -> None:
    tag = f"v{new_version}"
    notes_md = "\n".join(f"- {n}" for n in notes)

    print()
    print("=" * 70)
    print("  PUBLISH KE GITHUB RELEASES")
    print("=" * 70)
    print()
    print("  Option A — via `gh` CLI (paling cepat):")
    print()
    print(f'    gh release create {tag} \\')
    print(f'      "{zip_path}" \\')
    print(f'      --title "Release {tag}" \\')
    print(f'      --notes "{notes_md.replace(chr(10), chr(92) + "n")}"')
    print()
    print("  Option B — via GitHub web UI:")
    print()
    print(f"    1. Buka: https://github.com/<OWNER>/<REPO>/releases/new")
    print(f"    2. Tag: {tag}")
    print(f"    3. Title: Release {tag}")
    print(f"    4. Upload file: {zip_path.name}")
    print(f"    5. Release notes (gunakan bullet `-`):")
    for n in notes:
        print(f"         - {n}")
    print(f"    6. Klik 'Publish release'")
    print()
    print("  Karyawan akan dapat update otomatis saat buka aplikasi.")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("version", help="Versi baru (semver X.Y.Z)")
    parser.add_argument(
        "--notes", nargs="+", required=True,
        help="Release notes (bisa multi argument, satu bullet per argument)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Output ke _test_updates/ dan TIDAK modify version.py (testing lokal)",
    )
    parser.add_argument(
        "--publish", action="store_true",
        help="Auto-publish ke GitHub via `gh` CLI (perlu `gh auth login` lebih dulu)",
    )
    args = parser.parse_args()

    if args.dry_run and args.publish:
        print("❌ --dry-run dan --publish tidak bisa dipakai bersamaan.")
        sys.exit(1)

    new_version = args.version.strip().lstrip("vV")
    try:
        new_tuple = parse_semver(new_version)
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)

    current = read_current_version()
    try:
        current_tuple = parse_semver(current)
    except ValueError:
        print(f"❌ version.py berisi versi invalid: {current!r}")
        sys.exit(1)

    if new_tuple <= current_tuple:
        print(f"❌ Versi baru ({new_version}) harus lebih besar dari versi saat ini ({current}).")
        sys.exit(1)

    out_dir = PROJECT_ROOT / ("_test_updates" if args.dry_run else "dist")

    # Build ZIP. Saat dry-run, temp-tulis version.py lalu restore.
    if args.dry_run:
        original = VERSION_FILE.read_text(encoding="utf-8")
        try:
            write_version(new_version)
            zip_path = build_zip(new_version, out_dir)
        finally:
            VERSION_FILE.write_text(original, encoding="utf-8")
    else:
        write_version(new_version)
        print(f"  version.py bumped: {current}  ->  {new_version}")
        zip_path = build_zip(new_version, out_dir)

    size_kb = zip_path.stat().st_size / 1024
    sha = sha256_file(zip_path)
    print(f"  Built:   {zip_path.relative_to(PROJECT_ROOT)}  ({size_kb:.1f} KB)")
    print(f"  SHA-256: {sha}")

    if args.dry_run:
        print()
        print(f"[DRY-RUN] Output di {out_dir.relative_to(PROJECT_ROOT)}/")
        print(f"          version.py TIDAK dimodifikasi.")
        print(f"          ZIP ini BELUM di-publish ke GitHub — hanya verifikasi build.")
        return

    if args.publish:
        print()
        print(f"Publishing ke GitHub Release v{new_version}...")
        if publish_via_gh(new_version, zip_path, args.notes):
            print(f"\n✅  Release v{new_version} published. Karyawan akan dapat update otomatis.")
        else:
            print_publish_instructions(new_version, zip_path, args.notes)
    else:
        print_publish_instructions(new_version, zip_path, args.notes)


if __name__ == "__main__":
    main()
