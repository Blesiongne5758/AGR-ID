@echo off
title AGR.ID Realtime Auction Server (Golang)
echo ========================================================
echo  Menjalankan AGR.ID Realtime Auction Server (Golang)
echo  Port: 8081
echo ========================================================
cd /d "%~dp0services\auction-realtime"
if exist auction-server.exe (
    auction-server.exe
) else (
    echo Mengompilasi dan menjalankan dari source...
    go run .\cmd\server\main.go
)
pause
