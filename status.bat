@echo off
title Binance Auto-Claimer - Background Worker Status
cd /d "%~dp0"

set "PY_CMD="
if exist "%~dp0redpacket-claimer.exe" (
    set "PY_CMD=%~dp0redpacket-claimer.exe"
) else (
    where python >nul 2>&1 && set "PY_CMD=python"
    if not defined PY_CMD (
        where py >nul 2>&1 && set "PY_CMD=py"
    )
)

if not defined PY_CMD (
    echo [!] Python executable not found.
    pause
    exit /b 1
)

"%PY_CMD%" check_worker.py %*
if %errorlevel% neq 0 (
    pause
)
