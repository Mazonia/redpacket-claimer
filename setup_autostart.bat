@echo off
title Binance Red Packet Claimer - Setup Auto-Start
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo =======================================================
echo    BINANCE RED PACKET CLAIMER - AUTO-START SETUP
echo =======================================================
echo.
echo This installer will configure the Binance Auto-Claimer
echo to start automatically whenever Windows boots, restarts,
echo or wakes up from sleep / hibernation (24/7 resilience).
echo.

:: 1. Auto-elevate to Administrator via UAC for Task Scheduler
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [i] Requesting Administrator privileges for 24/7 background registration...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

:: Ensure dedicated named executable exists
for /f "delims=" %%i in ('where python') do set "SYSTEM_PY=%%i" & goto :found_py
:found_py
if defined SYSTEM_PY (
    if not exist "%~dp0redpacket-claimer.exe" copy "!SYSTEM_PY!" "%~dp0redpacket-claimer.exe" >nul
)

set "CUR_DIR=%~dp0"
set "CUR_DIR=%CUR_DIR:~0,-1%"

:: 2. Register Windows Task Scheduler Task (Layer 1: Boot + Wake-from-sleep + Battery immune)
echo [1/3] Registering Task Scheduler task (Logon + Sleep Wake triggers)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { try { $dir = '%CUR_DIR%'; $vbs = \"$dir\start_hidden.vbs\"; $xml = @\"
<?xml version=\"1.0\" encoding=\"UTF-16\"?>
<Task version=\"1.2\" xmlns=\"http://schemas.microsoft.com/windows/2004/02/mit/task\">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
    <EventTrigger>
      <Enabled>true</Enabled>
      <Subscription>&lt;QueryList&gt;&lt;Query Id=\"0\" Path=\"System\"&gt;&lt;Select Path=\"System\"&gt;*[System[Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and EventID=1]]&lt;/Select&gt;&lt;/Query&gt;&lt;/QueryList&gt;</Subscription>
    </EventTrigger>
  </Triggers>
  <Principals>
    <Principal id=\"Author\">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowDemandStart>true</AllowDemandStart>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context=\"Author\">
    <Exec>
      <Command>wscript.exe</Command>
      <Arguments>\"\"\"$vbs\"\"\"</Arguments>
      <WorkingDirectory>$dir</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
\"@; Register-ScheduledTask -TaskName 'Binance-RedPacket-Claimer' -Xml $xml -Force | Out-Null; Write-Host '    [+] Task Scheduler task registered successfully!' } catch { Write-Host '    [!] Task Scheduler fallback: ' + $_.Exception.Message } }"

:: 3. Register Windows Startup Folder Shortcut (Layer 2)
echo [2/3] Creating Windows Startup folder shortcut...
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut('%STARTUP_DIR%\Binance-RedPacket-Claimer.lnk'); $sc.TargetPath = 'wscript.exe'; $sc.Arguments = '\"%CUR_DIR%\start_hidden.vbs\"'; $sc.WorkingDirectory = '%CUR_DIR%'; $sc.Description = 'Binance Red Packet & Feed Auto-Claimer'; $sc.Save(); }" >nul 2>&1
echo     [+] Startup folder shortcut created!

:: 4. Register Windows Registry Run Key (Layer 3)
echo [3/3] Registering in Windows CurrentUser Run registry...
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "Binance-RedPacket-Claimer" /t REG_SZ /d "wscript.exe \"%CUR_DIR%\start_hidden.vbs\"" /f >nul 2>&1
echo     [+] Registry Run entry registered!

echo.
echo =======================================================
echo    SUCCESS! Triple-layer Auto-Start is Active!
echo =======================================================
echo.
echo The Binance Auto-Claimer will now run automatically:
echo  1. On system reboot / user login.
echo  2. On wake-up from sleep or hibernation.
echo  3. Battery-immune: will NOT be terminated when unplugged.
echo  4. Auto-restarts continuously if internet drops or re-attaches.
echo.

set /p LAUNCH_NOW="Do you want to launch the Auto-Claimer in the background right now? (Y/N): "
if /i "%LAUNCH_NOW%"=="Y" (
    echo Starting Binance Auto-Claimer in background...
    wscript.exe "%CUR_DIR%\start_hidden.vbs"
    timeout /t 2 >nul
    echo [+] Auto-Claimer is running silently in the background!
)

echo.
echo Press any key to exit.
pause >nul
