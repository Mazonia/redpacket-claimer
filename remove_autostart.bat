@echo off
title Binance Red Packet Claimer - Remove Auto-Start
cd /d "%~dp0"

echo =======================================================
echo    BINANCE RED PACKET CLAIMER - REMOVE AUTO-START
echo =======================================================
echo.

:: Check Administrator for Task Scheduler removal
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [i] Requesting Administrator privileges to remove scheduled task...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo [1/3] Removing Task Scheduler task...
schtasks /delete /tn "Binance-RedPacket-Claimer" /f >nul 2>&1
if %errorlevel% equ 0 (
    echo     [+] Task Scheduler task removed.
) else (
    echo     [i] No Task Scheduler task found or already removed.
)

echo [2/3] Removing Windows Startup folder shortcut...
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if exist "%STARTUP_DIR%\Binance-RedPacket-Claimer.lnk" (
    del /f /q "%STARTUP_DIR%\Binance-RedPacket-Claimer.lnk" >nul 2>&1
    echo     [+] Startup shortcut removed.
) else (
    echo     [i] No startup shortcut found.
)

echo [3/3] Removing Registry Run entry...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "Binance-RedPacket-Claimer" /f >nul 2>&1
if %errorlevel% equ 0 (
    echo     [+] Registry Run entry removed.
) else (
    echo     [i] No registry entry found.
)

echo.
echo =======================================================
echo    Auto-Start has been completely disabled.
echo =======================================================
echo.
pause
