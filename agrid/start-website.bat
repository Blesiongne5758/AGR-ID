@echo off
REM ============================================================
REM  AGR.ID - Marketplace Pertanian, Perkebunan, Perikanan,
REM  Peternakan - Start Webapp pada Server Lokal (Windows)
REM  Cara pakai: klik dua kali file ini (atau jalankan dari CMD)
REM ============================================================
setlocal EnableExtensions
title AGR.ID - Webapp Server

REM Pindah ke folder tempat file .bat ini berada
cd /d "%~dp0"

REM ---- Konfigurasi (silakan ubah bila perlu) ----
set PORT=5000
set VENV=.venv

echo.
echo ============================================
echo   MEMULAI WEBSAPP AGR.ID
echo ============================================
echo.

REM ---- Cari Python ----
where python >nul 2>nul
if %errorlevel%==0 (
    set "PY=python"
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        set "PY=py -3"
    ) else (
        echo [X] Python tidak ditemukan di sistem Anda.
        echo     Download dan install dari https://www.python.org/downloads/
        echo     PENTING: centang "Add Python to PATH" saat instalasi.
        echo.
        pause
        exit /b 1
    )
)

echo [*] Menggunakan interpreter: %PY%
%PY% --version
echo.

REM ---- Buat virtual environment bila belum ada ----
if not exist "%VENV%\Scripts\python.exe" (
    echo [*] Membuat virtual environment ^(%VENV%^)...
    %PY% -m venv %VENV%
    if errorlevel 1 (
        echo [X] Gagal membuat virtual environment.
        pause
        exit /b 1
    )
)

call "%VENV%\Scripts\activate.bat"
set "PY_RUN=%VENV%\Scripts\python.exe"

REM ---- Install dependency bila Flask belum tersedia ----
"%PY_RUN%" -c "import flask, flask_sqlalchemy" >nul 2>nul
if errorlevel 1 (
    echo [*] Menginstall dependency ^(Flask, SQLAlchemy, Werkzeug^)...
    "%PY_RUN%" -m pip install --upgrade pip >nul 2>nul
    "%PY_RUN%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [X] Gagal menginstall dependency. Periksa koneksi internet Anda.
        pause
        exit /b 1
    )
)

REM ---- Jalankan server ----
echo.
echo ============================================
echo   Server berjalan di http://localhost:%PORT%
echo   Tekan CTRL+C untuk menghentikan server
echo   Demo: penjual@agr.id/penjual123
echo         pembeli@agr.id/pembeli123
echo         admin@agr.id/admin123
echo ============================================
echo.

REM Buka browser otomatis setelah 3 detik (non-blocking)
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:%PORT%"

set PORT=%PORT%
"%PY_RUN%" app.py

echo.
echo [!] Server AGR.ID telah berhenti.
pause
endlocal
