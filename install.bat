@echo off
title Sortir Stiker Pack - Installer
cd /d "%~dp0"

echo ===============================================
echo  Sortir Stiker Pack - Installer
echo ===============================================
echo.

rem ── Pastikan Python terinstal di sistem ───────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python tidak ditemukan di PATH.
    echo.
    echo Silakan install Python 3.10+ dari https://www.python.org/downloads/
    echo PENTING: centang "Add Python to PATH" saat install.
    echo.
    pause
    exit /b 1
)

echo [1/3] Python terdeteksi:
python --version
echo.

rem ── Hapus .venv lama kalau ada (mungkin rusak / dari komputer lain) ───
if exist ".venv" (
    echo [2/3] Menghapus virtual environment lama...
    rmdir /s /q ".venv"
)

rem ── Bikin .venv baru di komputer ini ──────────────────────────────────
echo [2/3] Membuat virtual environment baru...
python -m venv .venv
if errorlevel 1 (
    echo [ERROR] Gagal membuat virtual environment.
    pause
    exit /b 1
)

rem ── Install dependencies ──────────────────────────────────────────────
echo.
echo [3/3] Menginstal dependensi dari requirements.txt...
.venv\Scripts\python -m pip install --upgrade pip --quiet --disable-pip-version-check
.venv\Scripts\pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
    echo [ERROR] Gagal menginstal dependensi.
    pause
    exit /b 1
)

echo.
echo ===============================================
echo  Instalasi selesai!
echo ===============================================
echo.
echo Jalankan aplikasi dengan: run.bat ^(atau klik run.vbs untuk tanpa konsol^)
echo.
pause
exit /b 0
