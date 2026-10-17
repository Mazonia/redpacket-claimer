@echo off
title RedPacket-Auto-Claimer
cd /d "%~dp0"

echo ==============================================
echo       BINANCE RED PACKET AUTO-CLAIMER
echo ==============================================
echo.

:: Create dedicated named executable so Task Manager displays 'redpacket-claimer.exe' instead of generic 'python.exe'
for /f "delims=" %%i in ('where python') do set SYSTEM_PY=%%i & goto :found_py
:found_py

if not exist redpacket-claimer.exe (
    copy "%SYSTEM_PY%" redpacket-claimer.exe >nul
)

:run_loop
echo [%TIME%] Starting Red Packet Claimer as [redpacket-claimer.exe]...
redpacket-claimer.exe main.py %*
set EXIT_CODE=%errorlevel%

echo.
if %EXIT_CODE% equ 0 (
    echo [%TIME%] Claimer process stopped cleanly.
    exit /b 0
)

if %EXIT_CODE% equ 42 (
    echo [%TIME%] Another instance is already active. Exiting.
    exit /b 0
)

echo [%TIME%] [!] Claimer process exited with code %EXIT_CODE%.
echo [%TIME%] Auto-restarting in 3 seconds (Press Ctrl+C to stop)...
timeout /t 3 /nobreak >nul
goto :run_loop
