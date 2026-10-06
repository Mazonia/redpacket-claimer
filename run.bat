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

echo Starting Red Packet Claimer as [redpacket-claimer.exe]...
redpacket-claimer.exe main.py %*
pause
