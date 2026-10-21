@echo off
title Binance Red Packet Claimer - Setup Auto-Start
cd /d "%~dp0"

echo =======================================================
echo    BINANCE RED PACKET CLAIMER - AUTO-START SETUP
echo =======================================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_autostart.ps1"

if %errorlevel% neq 0 (
    echo.
    echo [!] Setup exited with code %errorlevel%.
    pause
)
