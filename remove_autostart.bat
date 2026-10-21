<# :
@echo off
title Binance Red Packet Claimer - Remove Auto-Start
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$env:SCRIPT_DIR='%~dp0'; $env:BATCH_PATH='%~f0'; Invoke-Expression ([System.IO.File]::ReadAllText('%~f0'))"
exit /b %errorlevel%
#>

# Binance Red Packet Auto-Claimer - Remove Auto-Start (Self-Contained Engine)
$Host.UI.RawUI.WindowTitle = "Binance Red Packet Claimer - Remove Auto-Start"

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
Write-Host "   BINANCE RED PACKET CLAIMER - REMOVE AUTO-START" -ForegroundColor Yellow
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""

$scriptDir = $env:SCRIPT_DIR
if (-not $scriptDir) { $scriptDir = (Get-Item -Path ".").FullName }
if ($scriptDir.EndsWith("\")) { $scriptDir = $scriptDir.Substring(0, $scriptDir.Length - 1) }

$batchPath = $env:BATCH_PATH
if (-not $batchPath) { $batchPath = Join-Path $scriptDir "remove_autostart.bat" }

# Check Administrator privileges
$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]$currentIdentity
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Step "Requesting Administrator privileges to remove scheduled task..." "info"
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "powershell.exe"
        $psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -Command `"`$env:SCRIPT_DIR='$scriptDir'; `$env:BATCH_PATH='$batchPath'; Invoke-Expression ([System.IO.File]::ReadAllText('$batchPath'))`""
        $psi.Verb = "RunAs"
        $psi.UseShellExecute = $true
        $elevatedProc = [System.Diagnostics.Process]::Start($psi)
        $elevatedProc.WaitForExit()
        exit $elevatedProc.ExitCode
    } catch {
        Write-Step "Administrator elevation was cancelled or unavailable." "warning"
        Write-Step "Proceeding to remove user-level autostart (Startup folder + Registry)..." "info"
    }
}

# 1. Remove Task Scheduler Task
Write-Host "[1/3] Removing Task Scheduler task..." -ForegroundColor White
try {
    $existing = Get-ScheduledTask -TaskName 'Binance-RedPacket-Claimer' -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName 'Binance-RedPacket-Claimer' -Confirm:$false -ErrorAction Stop
        Write-Step "Task Scheduler task removed." "success"
    } else {
        Write-Step "No Task Scheduler task found or already removed." "info"
    }
} catch {
    $schtasksRes = & schtasks /delete /tn "Binance-RedPacket-Claimer" /f 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Step "Task Scheduler task removed via schtasks." "success"
    } else {
        Write-Step "Task Scheduler task not present or already removed." "info"
    }
}

# 2. Remove Windows Startup Folder Shortcut
Write-Host ""
Write-Host "[2/3] Removing Windows Startup folder shortcut..." -ForegroundColor White
try {
    $startupDir = [Environment]::GetFolderPath('Startup')
    if (-not $startupDir -or -not (Test-Path $startupDir)) {
        $startupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
    }
    $shortcutPath = Join-Path $startupDir "Binance-RedPacket-Claimer.lnk"
    if (Test-Path $shortcutPath) {
        Remove-Item -Path $shortcutPath -Force
        Write-Step "Startup shortcut removed." "success"
    } else {
        Write-Step "No startup shortcut found or already removed." "info"
    }
} catch {
    Write-Step "Could not remove startup shortcut: $($_.Exception.Message)" "warning"
}

# 3. Remove Registry Run Key
Write-Host ""
Write-Host "[3/3] Removing Registry Run entry..." -ForegroundColor White
try {
    $regKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $prop = Get-ItemProperty -Path $regKey -Name "Binance-RedPacket-Claimer" -ErrorAction SilentlyContinue
    if ($prop) {
        Remove-ItemProperty -Path $regKey -Name "Binance-RedPacket-Claimer" -Force
        Write-Step "Registry Run entry removed." "success"
    } else {
        Write-Step "No registry entry found or already removed." "info"
    }
} catch {
    Write-Step "Could not remove registry entry: $($_.Exception.Message)" "warning"
}

Write-Host ""
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "   Auto-Start has been completely disabled." -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Enter to exit..." -ForegroundColor Gray
Read-Host | Out-Null
