@echo off
title Binance Red Packet Claimer - Stopper
cd /d "%~dp0"

echo =======================================================
echo     BINANCE RED PACKET AUTO-CLAIMER - STOPPER
echo =======================================================
echo.
echo Stopping all running claimer background processes...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$curDir = (Get-Item -Path '%~dp0').FullName.TrimEnd('\').ToLower(); $myPid = $PID; $stoppedAny = $false; Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $myPid -and ($_.Name -eq 'redpacket-claimer.exe' -or ($_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*run.bat*') -or ($_.Name -like '*python*' -and $_.CommandLine -like '*main.py*' -and $_.CommandLine -like ('*' + $curDir + '*'))) } | ForEach-Object { Write-Host ('  [+] Stopping ' + $_.Name + ' (PID ' + $_.ProcessId + ')...') -ForegroundColor Yellow; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $stoppedAny = $true }; $userDataDir = Join-Path $curDir 'user_data'; Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $myPid -and $_.Name -like '*chrome*' -and $_.CommandLine -like ('*' + $userDataDir.ToLower() + '*') } | ForEach-Object { Write-Host ('  [+] Closing browser session (PID ' + $_.ProcessId + ')...') -ForegroundColor Yellow; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $stoppedAny = $true }; try { $task = Get-ScheduledTask -TaskName 'Binance-RedPacket-Claimer' -ErrorAction SilentlyContinue; if ($task -and $task.State -eq 'Running') { Stop-ScheduledTask -TaskName 'Binance-RedPacket-Claimer' -ErrorAction SilentlyContinue; Write-Host '  [+] Stopped running Scheduled Task instance.' -ForegroundColor Yellow; $stoppedAny = $true } } catch {}; Write-Host ''; if ($stoppedAny) { Write-Host '  [✓] All claimer processes and browser sessions stopped successfully!' -ForegroundColor Green } else { Write-Host '  [i] No active claimer processes were found running.' -ForegroundColor Cyan }"

echo.
echo =======================================================
ping -n 4 127.0.0.1 >nul
