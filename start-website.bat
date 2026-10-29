@echo off
setlocal enabledelayedexpansion
title AGR.ID System Launcher (Flask + Golang Realtime Auction)

echo ===================================================================
echo   AGR.ID - Marketplace Pertanian & Lelang Terbuka Real-Time
echo   Starting Golang Auction WebSocket Server + Flask Web App...
echo ===================================================================

:: 1. Jalankan Golang Realtime Auction Server di Background (Port 8081)
cd /d "%~dp0services\auction-realtime"
if exist "auction-server.exe" (
    echo [1/3] Menjalankan Golang Auction Server (Port 8081)...
    start "AGR.ID - Golang Auction Service" /min "%~dp0services\auction-realtime\auction-server.exe"
) else (
    echo [1/3] Mengompilasi dan menjalankan Golang Auction Server...
    start "AGR.ID - Golang Auction Service" /min go run .\cmd\server\main.go
)

:: 2. Persiapan Python Virtual Environment & Dependencies
cd /d "%~dp0"
set VENV_DIR=%~dp0.venv
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [2/3] Membuat virtual environment Python (.venv)...
    py -m venv "%VENV_DIR%" 2>nul || python -m venv "%VENV_DIR%"
)

if exist "%VENV_DIR%\Scripts\activate.bat" (
    call "%VENV_DIR%\Scripts\activate.bat"
    pip install -r agrid\requirements.txt --quiet
)

:: 3. Buka Browser & Jalankan Flask Server (Port 5000)
echo [3/3] Menjalankan Server Utama AGR.ID di http://localhost:5000...
start "" "http://localhost:5000/lelang"
cd /d "%~dp0agrid"
if exist "%VENV_DIR%\Scripts\python.exe" (
    "%VENV_DIR%\Scripts\python.exe" app.py
) else (
    py app.py 2>nul || python app.py
)

pause
