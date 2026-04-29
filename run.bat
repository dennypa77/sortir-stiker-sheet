@echo off
title Sortir Stiker Pack
cd /d "%~dp0"

rem ── Mode hidden (dipanggil dari run.vbs) — skip pause biar nggak hang ─
set HIDDEN=
if /i "%~1"=="hidden" set HIDDEN=1

rem Flag: apakah session ini yang apply update. Penting supaya OLD run.bat
rem (yang nunggu pythonw lama selesai saat restart) TIDAK sentuh .update_backup
rem yang dibuat oleh NEW run.bat secara bersamaan.
set APPLIED=0

rem ── Bootstrap virtual environment kalau belum ada ────────────────────
rem (harus dulu sebelum preflight — preflight pakai Python)
if not exist ".venv\Scripts\python.exe" (
    echo [Setup] Membuat virtual environment...
    python -m venv .venv
    echo [Setup] Menginstal dependensi...
    .venv\Scripts\pip install -r requirements.txt --quiet
)

rem ── Pre-flight update check ───────────────────────────────────────────
rem Cek GitHub, download versi baru kalau ada, stage ke .update_pending/.
rem preflight.py never raises, selalu exit 0.
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python preflight.py
)

rem ── Apply pending update (kalau preflight / session sebelumnya stage) ──
if exist ".update_pending\extracted\version.py" (
    set APPLIED=1
    echo [Update] Memasang versi baru...

    if exist ".update_backup" rmdir /s /q ".update_backup"
    mkdir ".update_backup" 2>nul

    rem Backup file saat ini (sebelum diganti)
    for %%F in (*.py) do copy /y "%%F" ".update_backup\%%F" >nul
    if exist "requirements.txt" copy /y "requirements.txt" ".update_backup\requirements.txt" >nul

    rem Copy file baru ke project root
    for %%F in (.update_pending\extracted\*.py) do copy /y "%%F" "%%~nxF" >nul
    if exist ".update_pending\extracted\requirements.txt" copy /y ".update_pending\extracted\requirements.txt" "requirements.txt" >nul

    rem Simpan snapshot manifest untuk audit + popup
    if exist ".update_pending\extracted\_manifest.json" copy /y ".update_pending\extracted\_manifest.json" ".update_backup\_manifest.json" >nul

    rem Bersihkan folder staging & pending
    rmdir /s /q ".update_pending" 2>nul
    rmdir /s /q ".update_staging" 2>nul

    rem Reinstall dependencies kalau requirements berubah
    if exist ".venv\Scripts\pip.exe" (
        .venv\Scripts\pip install -r requirements.txt --quiet --disable-pip-version-check
    )

    echo [Update] Selesai. Menjalankan aplikasi versi baru...
)

rem ── Launch GUI (pythonw = tanpa console window) ──────────────────────
.venv\Scripts\pythonw app.py
set EXIT_CODE=%errorlevel%

rem ── Auto-rollback kalau versi baru gagal start ───────────────────────
rem Hanya sentuh .update_backup kalau session ini yang apply (APPLIED=1).
rem Kalau bukan (APPLIED=0), kita mungkin session LAMA yang lagi nunggu
rem pythonw selesai saat restart — jangan sentuh .update_backup NEW session.
if "%APPLIED%"=="1" (
    if exist ".update_backup\app.py" (
        if not "%EXIT_CODE%"=="0" (
            echo [Rollback] Aplikasi gagal start ^(exit code %EXIT_CODE%^).
            echo [Rollback] Mengembalikan versi lama...
            for %%F in (.update_backup\*.py) do copy /y "%%F" "%%~nxF" >nul
            if exist ".update_backup\requirements.txt" (
                copy /y ".update_backup\requirements.txt" "requirements.txt" >nul
                .venv\Scripts\pip install -r requirements.txt --quiet --disable-pip-version-check
            )
            rmdir /s /q ".update_backup"
            echo [Rollback] Selesai. Silakan jalankan run.bat lagi.
            if not defined HIDDEN pause
            exit /b 1
        )
        rem Sukses — hapus backup
        rmdir /s /q ".update_backup" 2>nul
    )
) else (
    rem Session ini tidak apply update. Kalau crash, kasih info user,
    rem tapi JANGAN sentuh .update_backup (mungkin milik session lain).
    if not "%EXIT_CODE%"=="0" (
        echo [Error] Aplikasi keluar dengan error. Exit code=%EXIT_CODE%
        if not defined HIDDEN pause
        exit /b %EXIT_CODE%
    )
)

exit /b 0
