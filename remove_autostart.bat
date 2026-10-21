@echo off
title Binance Red Packet Claimer - Remove Auto-Start
cd /d "%~dp0"

echo =======================================================
echo    BINANCE RED PACKET CLAIMER - REMOVE AUTO-START
echo =======================================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0remove_autostart.ps1"

if %errorlevel% neq 0 (
    echo.
    echo [!] Removal exited with code %errorlevel%.
    pause
)
