@echo off
title RedPacket-Auto-Claimer
cd /d "%~dp0"

echo ==============================================
echo       BINANCE RED PACKET AUTO-CLAIMER
echo ==============================================
echo.

:: Ensure dedicated named executable exists so Task Manager displays 'redpacket-claimer.exe' instead of generic 'python.exe'
set "PY_EXE="
if exist "%~dp0redpacket-claimer.exe" (
    set "PY_EXE=%~dp0redpacket-claimer.exe"
) else (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        set "SYSTEM_PY=%%i"
        goto :copy_py
    )
    for /f "delims=" %%i in ('where py 2^>nul') do (
        set "SYSTEM_PY=%%i"
        goto :copy_py
    )
    goto :no_py

    :copy_py
    copy "%SYSTEM_PY%" "%~dp0redpacket-claimer.exe" >nul 2>&1
    if exist "%~dp0redpacket-claimer.exe" (
        set "PY_EXE=%~dp0redpacket-claimer.exe"
    ) else (
        set "PY_EXE=%SYSTEM_PY%"
    )
)

goto :run_loop

:no_py
echo [%TIME%] [!] ERROR: Python executable not found in PATH or directory.
echo [%TIME%] Please install Python from python.org and add it to your system PATH.
exit /b 1

:run_loop
echo [%TIME%] Starting Red Packet Claimer as [%PY_EXE%]...
"%PY_EXE%" main.py %*
set EXIT_CODE=%errorlevel%

echo.
if %EXIT_CODE% equ 0 (
    echo [%TIME%] Claimer process stopped cleanly.
    exit /b 0
)

if %EXIT_CODE% equ 42 (
    echo [%TIME%] Another instance is already active. Exiting cleanly.
    exit /b 0
)

echo [%TIME%] [!] Claimer process exited with code %EXIT_CODE%.
echo [%TIME%] Auto-restarting in 3 seconds (Press Ctrl+C to stop)...
ping -n 4 127.0.0.1 >nul 2>&1
goto :run_loop
