#Requires -Version 5.1
<#
.SYNOPSIS
  Stop Realm Pal local stack started by start_services.ps1.
.NOTES
  Run from repo root:  .\stop_services.ps1
#>
$ErrorActionPreference = "Continue"
$Root = $PSScriptRoot
Set-Location $Root

$RunDir = Join-Path $Root ".run"

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Stop-TrackedWindow([string]$PidFile, [string]$Label) {
    $path = Join-Path $RunDir $PidFile
    if (-not (Test-Path $path)) { return }
    $procId = (Get-Content $path -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if (-not $procId) { return }
    try {
        $proc = Get-Process -Id ([int]$procId) -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "Stopping $Label (PID $procId)..."
            # Kill the PowerShell window and its child tree (uvicorn / next)
            taskkill /PID $procId /T /F 1>$null 2>$null
        }
    } catch {
        # already gone
    }
    Remove-Item $path -Force -ErrorAction SilentlyContinue
}

function Stop-ListenersOnPort([int]$Port, [string]$Label) {
    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if (-not $conns) { return }
        $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($procId in $pids) {
            if ($procId -le 4) { continue }
            Write-Host "Stopping $Label listener on port $Port (PID $procId)..."
            taskkill /PID $procId /T /F 1>$null 2>$null
        }
    } catch {
        # ignore
    }
}

Write-Step "Stopping API / web windows"
Stop-TrackedWindow "api.pid" "API"
Stop-TrackedWindow "web.pid" "Web"

# Fallback if windows were closed but servers kept running.
# Local dev runs the API on 8001, not 8000 | see start_services.ps1.
Stop-ListenersOnPort 8001 "API"
Stop-ListenersOnPort 3000 "Web"

Write-Step "Stopping Docker infra (Qdrant + Redis)"
try {
    docker compose -p realmpal stop qdrant redis 2>$null
    if ($LASTEXITCODE -ne 0) {
        # Fall back to default project name from this folder
        docker compose stop qdrant redis 2>$null
    }
} catch {
    Write-Host "Docker not available or already stopped." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Services stopped." -ForegroundColor Green
Write-Host "Tip: use 'docker compose -p realmpal down' to also remove containers."
