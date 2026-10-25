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

# Layer 1: Register Task Scheduler Task (Direct 24/7 Background Service - requires Administrator)
$taskRegistered = $false
if ($isAdmin) {
    Write-Host ""
    Write-Host "[1/2] Registering Task Scheduler 24/7 background service..." -ForegroundColor White
    try {
        $xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Delay>PT15S</Delay>
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
    <Hidden>true</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>999</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$claimerExe</Command>
      <Arguments>main.py --headless</Arguments>
      <WorkingDirectory>$scriptDir</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@
        Register-ScheduledTask -TaskName 'Binance-RedPacket-Claimer' -Xml $xml -Force -ErrorAction Stop | Out-Null
        Write-Step "Task Scheduler registered successfully (Direct 24/7 background service)!" "success"
        Write-Step "Configured with 15s boot network delay and sleep-resume auto-wake triggers." "success"
        $taskRegistered = $true

        # Clean up any conflicting legacy Startup shortcuts or Registry Run entries so they do not collide
        try {
            $startupDir = [Environment]::GetFolderPath('Startup')
            if ($startupDir) {
                $oldShortcut = Join-Path $startupDir "Binance-RedPacket-Claimer.lnk"
                if (Test-Path $oldShortcut) { Remove-Item $oldShortcut -Force -ErrorAction SilentlyContinue }
            }
            Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "Binance-RedPacket-Claimer" -ErrorAction SilentlyContinue
        } catch {}
    } catch {
        Write-Step "XML-based Task Scheduler registration failed: $($_.Exception.Message)" "warning"
        Write-Step "Attempting native PowerShell cmdlet fallback..." "info"
        try {
            $action = New-ScheduledTaskAction -Execute $claimerExe -Argument "main.py --headless" -WorkingDirectory $scriptDir
            $trigger = New-ScheduledTaskTrigger -AtLogOn
            $trigger.Delay = 'PT15S'
            $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -DontStopOnIdleEnd -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
            Register-ScheduledTask -TaskName "Binance-RedPacket-Claimer" -Action $action -Trigger $trigger -Settings $settings -Force -ErrorAction Stop | Out-Null
            Write-Step "Task Scheduler registered successfully via fallback!" "success"
            $taskRegistered = $true
        } catch {
            Write-Step "Task Scheduler registration unavailable: $($_.Exception.Message)" "warning"
        }
    }
}

# Layer 2: Register Windows Startup Folder Shortcut (Fallback for standard non-admin setup)
$startupShortcutCreated = $false
if (-not $taskRegistered) {
    Write-Host ""
    Write-Host "[2/2] Creating Windows Startup folder shortcut (User-level fallback)..." -ForegroundColor White
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
}

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
if ($taskRegistered -or $startupShortcutCreated) {
    Write-Host "   SUCCESS! Auto-Start is Active and Verified!" -ForegroundColor Green
} else {
    Write-Host "   WARNING: Could not activate auto-start layers." -ForegroundColor Red
}
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Active Auto-Start Engine:"
if ($taskRegistered) {
    Write-Host "  [OK] Windows Task Scheduler Service (24/7 persistent background worker)" -ForegroundColor Green
    Write-Host "       - Auto-starts 15s after PC logon" -ForegroundColor Gray
    Write-Host "       - Auto-resumes when PC wakes from sleep / hibernation" -ForegroundColor Gray
    Write-Host "       - Auto-restarts within 1m if network recovers from interruption" -ForegroundColor Gray
} elseif ($startupShortcutCreated) {
    Write-Host "  [OK] Windows Startup Folder Shortcut (User-level fallback)" -ForegroundColor Green
}
Write-Host ""

$isNonInteractive = ($env:SETUP_ARGS -match 'noninteractive|silent|-y|/y') -or [Console]::IsInputRedirected
if (-not $isNonInteractive) {
    $ans = Read-Host "Do you want to launch the Auto-Claimer in the background right now? (Y/N)"
    if ($ans -and $ans.Trim().ToUpper() -eq "Y") {
        Write-Host "Starting Binance Auto-Claimer in background..." -ForegroundColor Cyan
        if ($taskRegistered) {
            Start-ScheduledTask -TaskName 'Binance-RedPacket-Claimer' -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 3
        } else {
            Start-Process "wscript.exe" -ArgumentList "`"$vbsPath`" /silent"
            Start-Sleep -Seconds 3
        }
        Write-Step "Auto-Claimer triggered in background!" "success"
    }
    Write-Host ""
    Write-Host "Running background worker health and status check..." -ForegroundColor Cyan
    Start-Sleep -Seconds 2
    if (Test-Path (Join-Path $scriptDir "check_worker.py")) {
        & "$claimerExe" (Join-Path $scriptDir "check_worker.py") --check
    }
    Write-Host ""
    Write-Host "Tip: Run 'status.bat' anytime to test the background worker & see the last code redeemed." -ForegroundColor Yellow
    Write-Host "Press Enter to exit..." -ForegroundColor Gray
    Read-Host | Out-Null
}
