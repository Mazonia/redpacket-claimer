<# :
@echo off
title Binance Red Packet Claimer - Setup Auto-Start
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$env:SCRIPT_DIR='%~dp0'; $env:BATCH_PATH='%~f0'; $env:SETUP_ARGS='%*'; Invoke-Expression ([System.IO.File]::ReadAllText('%~f0'))"
exit /b %errorlevel%
#>

# Binance Red Packet Auto-Claimer - Setup Auto-Start (Self-Contained Engine)
$Host.UI.RawUI.WindowTitle = "Binance Red Packet Claimer - Setup Auto-Start"

function Write-Step {
    param([string]$Text, [string]$Status = "info")
    switch ($Status) {
        "success" { Write-Host "  [+] $Text" -ForegroundColor Green }
        "warning" { Write-Host "  [!] $Text" -ForegroundColor Yellow }
        "error"   { Write-Host "  [-] $Text" -ForegroundColor Red }
        default   { Write-Host "  [*] $Text" -ForegroundColor Cyan }
    }
}

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "   BINANCE RED PACKET CLAIMER - AUTO-START SETUP" -ForegroundColor Yellow
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "This installer will configure the Binance Auto-Claimer"
Write-Host "to start automatically whenever Windows boots, restarts,"
Write-Host "or wakes up from sleep / hibernation (24/7 resilience)."
Write-Host ""

$scriptDir = $env:SCRIPT_DIR
if (-not $scriptDir) { $scriptDir = (Get-Item -Path ".").FullName }
if ($scriptDir.EndsWith("\")) { $scriptDir = $scriptDir.Substring(0, $scriptDir.Length - 1) }

$batchPath = $env:BATCH_PATH
if (-not $batchPath) { $batchPath = Join-Path $scriptDir "setup_autostart.bat" }

$vbsPath = Join-Path $scriptDir "start_hidden.vbs"
$runBatPath = Join-Path $scriptDir "run.bat"
$claimerExe = Join-Path $scriptDir "redpacket-claimer.exe"

# Ensure redpacket-claimer.exe exists
if (-not (Test-Path $claimerExe)) {
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pyCmd) { $pyCmd = Get-Command py -ErrorAction SilentlyContinue }
    if ($pyCmd) {
        try {
            Copy-Item -Path $pyCmd.Source -Destination $claimerExe -Force
            Write-Step "Created dedicated named executable: redpacket-claimer.exe" "success"
        } catch {
            Write-Step "Could not copy python.exe to redpacket-claimer.exe: $_" "warning"
        }
    }
}

# Check Administrator privileges
$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]$currentIdentity
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Step "Requesting Administrator privileges for full 24/7 registration..." "info"
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "powershell.exe"
        $psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -Command `"`$env:SCRIPT_DIR='$scriptDir'; `$env:BATCH_PATH='$batchPath'; `$env:SETUP_ARGS='$($env:SETUP_ARGS)'; Invoke-Expression ([System.IO.File]::ReadAllText('$batchPath'))`""
        $psi.Verb = "RunAs"
        $psi.UseShellExecute = $true
        $elevatedProc = [System.Diagnostics.Process]::Start($psi)
        $elevatedProc.WaitForExit()
        exit $elevatedProc.ExitCode
    } catch {
        Write-Step "Administrator elevation was cancelled or unavailable." "warning"
        Write-Step "Proceeding with standard user-level autostart (Startup folder + Registry)..." "info"
    }
}

# Layer 1: Register Task Scheduler Task (Logon + Sleep Wakeup triggers - requires Administrator)
$taskRegistered = $false
if ($isAdmin) {
    Write-Host ""
    Write-Host "[1/3] Registering Task Scheduler task (Logon + Sleep Wake triggers)..." -ForegroundColor White
    try {
        $xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
    <EventTrigger>
      <Enabled>true</Enabled>
      <Subscription>&lt;QueryList&gt;&lt;Query Id="0" Path="System"&gt;&lt;Select Path="System"&gt;*[System[Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and EventID=1]]&lt;/Select&gt;&lt;/Query&gt;&lt;/QueryList&gt;</Subscription>
    </EventTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
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
    <AllowStartOnDemand>true</AllowStartOnDemand>
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
  <Actions Context="Author">
    <Exec>
      <Command>wscript.exe</Command>
      <Arguments>"$vbsPath" /silent</Arguments>
      <WorkingDirectory>$scriptDir</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@
        Register-ScheduledTask -TaskName 'Binance-RedPacket-Claimer' -Xml $xml -Force -ErrorAction Stop | Out-Null
        Write-Step "Task Scheduler registered successfully (Logon + Wake-from-sleep)!" "success"
        $taskRegistered = $true
    } catch {
        Write-Step "XML-based Task Scheduler registration failed: $($_.Exception.Message)" "warning"
        Write-Step "Attempting native PowerShell cmdlet fallback..." "info"
        try {
            $action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$vbsPath`" /silent" -WorkingDirectory $scriptDir
            $trigger = New-ScheduledTaskTrigger -AtLogOn
            $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -DontStopOnIdleEnd
            Register-ScheduledTask -TaskName "Binance-RedPacket-Claimer" -Action $action -Trigger $trigger -Settings $settings -Force -ErrorAction Stop | Out-Null
            Write-Step "Task Scheduler registered successfully via fallback!" "success"
            $taskRegistered = $true
        } catch {
            Write-Step "Task Scheduler registration unavailable: $($_.Exception.Message)" "warning"
        }
    }
} else {
    Write-Host ""
    Write-Host "[1/3] Task Scheduler registration skipped (requires Administrator privileges)." -ForegroundColor Gray
    Write-Host "      Using Startup folder shortcut and Registry Run key for standard autostart." -ForegroundColor Gray
}

# Layer 2: Register Windows Startup Folder Shortcut
Write-Host ""
Write-Host "[2/3] Creating Windows Startup folder shortcut..." -ForegroundColor White
$startupShortcutCreated = $false
try {
    $startupDir = [Environment]::GetFolderPath('Startup')
    if (-not $startupDir -or -not (Test-Path $startupDir)) {
        $startupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
    }
    if (-not (Test-Path $startupDir)) {
        New-Item -ItemType Directory -Path $startupDir -Force | Out-Null
    }
    $shortcutPath = Join-Path $startupDir "Binance-RedPacket-Claimer.lnk"
    
    $wsh = New-Object -ComObject WScript.Shell
    $shortcut = $wsh.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = "wscript.exe"
    $shortcut.Arguments = "`"$vbsPath`" /silent"
    $shortcut.WorkingDirectory = $scriptDir
    $shortcut.Description = "Binance Red Packet & Feed Auto-Claimer"
    $shortcut.Save()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($wsh) | Out-Null
    
    Write-Step "Startup folder shortcut created at: $shortcutPath" "success"
    $startupShortcutCreated = $true
} catch {
    Write-Step "Startup shortcut creation failed: $($_.Exception.Message)" "warning"
}

# Layer 3: Register Windows Registry Run Key
Write-Host ""
Write-Host "[3/3] Registering in Windows CurrentUser Run registry..." -ForegroundColor White
$registryCreated = $false
try {
    $regKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $regValue = "wscript.exe `"$vbsPath`" /silent"
    Set-ItemProperty -Path $regKey -Name "Binance-RedPacket-Claimer" -Value $regValue -Force
    Write-Step "Registry Run entry registered successfully!" "success"
    $registryCreated = $true
} catch {
    Write-Step "Registry Run entry failed: $($_.Exception.Message)" "warning"
}

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
if ($taskRegistered -or $startupShortcutCreated -or $registryCreated) {
    Write-Host "   SUCCESS! Multi-layer Auto-Start is Active!" -ForegroundColor Green
} else {
    Write-Host "   WARNING: Could not activate auto-start layers." -ForegroundColor Red
}
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Active Auto-Start Layers:"
if ($taskRegistered) { Write-Host "  [OK] Task Scheduler (Logon + Sleep Wakeup triggers)" -ForegroundColor Green }
if ($startupShortcutCreated) { Write-Host "  [OK] Windows Startup Folder Shortcut" -ForegroundColor Green }
if ($registryCreated) { Write-Host "  [OK] Windows Registry Run Key (Current User)" -ForegroundColor Green }
Write-Host ""

$isNonInteractive = ($env:SETUP_ARGS -match 'noninteractive|silent|-y|/y') -or [Console]::IsInputRedirected
if (-not $isNonInteractive) {
    $ans = Read-Host "Do you want to launch the Auto-Claimer in the background right now? (Y/N)"
    if ($ans -and $ans.Trim().ToUpper() -eq "Y") {
        Write-Host "Starting Binance Auto-Claimer in background..." -ForegroundColor Cyan
        Start-Process "wscript.exe" -ArgumentList "`"$vbsPath`""
        Start-Sleep -Seconds 2
        Write-Step "Auto-Claimer triggered in background!" "success"
    }
    Write-Host ""
    Write-Host "Press Enter to exit..." -ForegroundColor Gray
    Read-Host | Out-Null
}
