# Register the DeepSeek Audit Daemon as a Windows Scheduled Task
# Run this once to set up hourly automatic audits.
#
# Usage (in an elevated PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\install_scheduled_task.ps1
#
# To remove later:
#   schtasks /delete /tn "DeepSeekAuditDaemon" /f

$ErrorActionPreference = "Stop"

$TaskName   = "DeepSeekAuditDaemon"
$ProjectDir = Split-Path -Parent $PSScriptRoot
$PythonExe  = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$ScriptPath = Join-Path $ProjectDir "scripts\run_audit_once.py"
$LogDir     = Join-Path $ProjectDir "deepseek_code\metrics"

# Ensure log directory exists
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Write-Host "=== DeepSeek Audit Daemon — Scheduled Task Installer ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Project:   $ProjectDir"
Write-Host "  Python:    $PythonExe"
Write-Host "  Script:    $ScriptPath"
Write-Host "  Schedule:  Every 1 hour"
Write-Host ""

# Guard: venv must exist before creating the task
if (-not (Test-Path $PythonExe)) {
    Write-Host ""
    Write-Host "✗ Virtual environment not found at:" -ForegroundColor Red
    Write-Host "    $PythonExe" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Run 'Install and Run - Windows.bat' first to create the environment." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# Remove any existing task with the same name
$existing = schtasks /query /tn $TaskName 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[*] Removing existing scheduled task..." -ForegroundColor Yellow
    schtasks /delete /tn $TaskName /f
}

# Create the scheduled task
# Runs every hour, starting at the next round hour
Write-Host "[*] Creating scheduled task..." -ForegroundColor Green

$action    = "$PythonExe"
$arguments = "`"$ScriptPath`""

$schtasksArgs = @(
    "/create",
    "/tn", $TaskName,
    "/tr", "`"$action`" $arguments",
    "/sc", "HOURLY",
    "/mo", "1",
    "/st", "00:00",
    "/f",
    "/rl", "LIMITED"
)

$result = & schtasks @schtasksArgs 2>&1
$exitCode = $LASTEXITCODE

if ($exitCode -eq 0) {
    Write-Host ""
    Write-Host "✓ Scheduled task 'DeepSeekAuditDaemon' installed successfully!" -ForegroundColor Green
    Write-Host "  It will run every hour starting at the next round hour." -ForegroundColor Green
    Write-Host ""
    Write-Host "  Check status:  schtasks /query /tn DeepSeekAuditDaemon /v"
    Write-Host "  Run now:       schtasks /run /tn DeepSeekAuditDaemon"
    Write-Host "  Remove:        schtasks /delete /tn DeepSeekAuditDaemon /f"
    Write-Host ""
    Write-Host "  Audit log:     deepseek_code\audit.log"
    Write-Host "  Metrics:       deepseek_code\metrics\time_series.jsonl"
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "✗ Failed to create scheduled task (exit code: $exitCode)" -ForegroundColor Red
    Write-Host $result

    Write-Host ""
    Write-Host "Try running this script as Administrator." -ForegroundColor Yellow
    Write-Host "Or create the task manually via Task Scheduler GUI." -ForegroundColor Yellow
}
