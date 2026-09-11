#Requires -Version 5.1
<#
.SYNOPSIS
  Start Realm Pal local stack: Qdrant + Redis, API, and web.
.NOTES
  Run from repo root:  .\start_services.ps1
  Stop with:           .\stop_services.ps1
#>
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

$RunDir = Join-Path $Root ".run"
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Ensure-EnvFiles {
    $rootEnv = Join-Path $Root ".env"
    $rootExample = Join-Path $Root ".env.example"
    if (-not (Test-Path $rootEnv)) {
        if (-not (Test-Path $rootExample)) {
            throw "Missing .env.example - cannot create .env"
        }
        Copy-Item $rootExample $rootEnv
        Write-Host "Created .env from .env.example - set ANTHROPIC_API_KEY and JWT_SECRET" -ForegroundColor Yellow
    }

    $webEnv = Join-Path $Root "web\.env.local"
    $webExample = Join-Path $Root "web\.env.local.example"
    if (-not (Test-Path $webEnv)) {
        if (-not (Test-Path $webExample)) {
            throw "Missing web\.env.local.example - cannot create web\.env.local"
        }
        Copy-Item $webExample $webEnv
        Write-Host "Created web\.env.local from example" -ForegroundColor Yellow
    }
}

function Import-DotEnv([string]$Path) {
    if (-not (Test-Path $Path)) { return }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $idx = $line.IndexOf("=")
        if ($idx -lt 1) { return }
        $name = $line.Substring(0, $idx).Trim()
        $value = $line.Substring($idx + 1).Trim()
        # Strip inline comments and surrounding quotes
        if ($value -match '^(.*?)\s+#' ) { $value = $Matches[1].Trim() }
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        Set-Item -Path "Env:$name" -Value $value
    }
}

function Test-PortInUse([int]$Port) {
    try {
        $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        return $null -ne $listeners
    } catch {
        return $false
    }
}

function Assert-Docker {
    try {
        docker info 1>$null 2>$null
        if ($LASTEXITCODE -ne 0) { throw "docker info failed" }
    } catch {
        throw "Docker is not running. Start Docker Desktop, wait until it is ready, then re-run .\start_services.ps1"
    }
}

Write-Step "Checking environment files"
Ensure-EnvFiles
Import-DotEnv (Join-Path $Root ".env")

if (-not $env:ANTHROPIC_API_KEY -or $env:ANTHROPIC_API_KEY -like "sk-ant-...*") {
    Write-Host "Warning: ANTHROPIC_API_KEY looks unset in .env" -ForegroundColor Yellow
}

Write-Step "Starting Qdrant + Redis (Docker)"
Assert-Docker
docker compose -p realmpal up -d qdrant redis
if ($LASTEXITCODE -ne 0) {
    throw "docker compose failed (exit $LASTEXITCODE)"
}

# --- API ---
$ApiDir = Join-Path $Root "api"
$VenvPython = Join-Path $ApiDir ".venv\Scripts\python.exe"
$VenvUvicorn = Join-Path $ApiDir ".venv\Scripts\uvicorn.exe"

Write-Step "Preparing API virtualenv"
if (-not (Test-Path $VenvPython)) {
    Push-Location $ApiDir
    try {
        python -m venv .venv
        & $VenvPython -m pip install --upgrade pip
        & $VenvPython -m pip install -r requirements.txt
        & $VenvPython -m playwright install chromium
    } finally {
        Pop-Location
    }
}

# Port 8000 has a persistent phantom listener on this machine (a
# LISTENING socket bound to a PID that no longer exists | not fixable
# short of a reboot), so local dev runs the API on 8001 instead. web/.env.
# local's NEXT_PUBLIC_API_URL/API_URL already point here to match.
$ApiPort = 8001

if (Test-PortInUse $ApiPort) {
    Write-Host "Port $ApiPort already in use - skipping API launch" -ForegroundColor Yellow
} else {
    Write-Step "Launching API on http://localhost:$ApiPort"
    # Run as package api.main from repo root so relative imports work.
    # No --reload: on Windows, uvicorn's --reload supervisor leaves the
    # worker on a SelectorEventLoop, which can't spawn subprocesses | and
    # the scraper's Playwright browser is a subprocess. That combo raises
    # NotImplementedError on every scrape. Restart the script manually after
    # backend changes instead.
    $apiCmd = @"
`$Host.UI.RawUI.WindowTitle = 'Realm Pal API'
Set-Location '$Root'
`$env:PYTHONPATH = '$Root'
& '$VenvUvicorn' api.main:app --host 127.0.0.1 --port $ApiPort
"@
    $apiProc = Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-NoExit", "-NoProfile", "-Command", $apiCmd) `
        -PassThru `
        -WorkingDirectory $Root
    Set-Content -Path (Join-Path $RunDir "api.pid") -Value $apiProc.Id -Encoding ascii
}

# --- Web ---
$WebDir = Join-Path $Root "web"

Write-Step "Preparing web dependencies"
if (-not (Test-Path (Join-Path $WebDir "node_modules"))) {
    Push-Location $WebDir
    try {
        npm install
    } finally {
        Pop-Location
    }
}

if (Test-PortInUse 3000) {
    Write-Host "Port 3000 already in use - skipping web launch" -ForegroundColor Yellow
} else {
    Write-Step "Launching web on http://localhost:3000"
    $webCmd = @"
`$Host.UI.RawUI.WindowTitle = 'Realm Pal Web'
Set-Location '$WebDir'
npm run dev
"@
    $webProc = Start-Process -FilePath "powershell.exe" `
        -ArgumentList @("-NoExit", "-NoProfile", "-Command", $webCmd) `
        -PassThru `
        -WorkingDirectory $WebDir
    Set-Content -Path (Join-Path $RunDir "web.pid") -Value $webProc.Id -Encoding ascii
}

Write-Host ""
Write-Host "Realm Pal is starting:" -ForegroundColor Green
Write-Host "  Web  http://localhost:3000"
Write-Host "  API  http://localhost:$ApiPort"
Write-Host "  Docs http://localhost:$ApiPort/docs  (when DEBUG=true)"
Write-Host ""
Write-Host "Stop with:  .\stop_services.ps1"