#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ApiHost = "127.0.0.1"
$ApiPort = 8790
$UiPort = 5176
$ApiUrl = "http://${ApiHost}:${ApiPort}/api/health"
$UiUrl = "http://${ApiHost}:${UiPort}/"

function Test-HttpOk([string]$Url) {
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        return $resp.StatusCode -ge 200 -and $resp.StatusCode -lt 400
    } catch {
        return $false
    }
}

function Get-VenvPython {
    $venvPy = Join-Path $Root "backend\.venv\Scripts\python.exe"
    if (Test-Path $venvPy) { return $venvPy }
    $sys = Get-Command python -ErrorAction SilentlyContinue
    if (-not $sys) { throw "Python 3.12+ is required." }
    Write-Host "Creating backend\.venv ..."
    & $sys.Source -m venv (Join-Path $Root "backend\.venv")
    if (-not (Test-Path $venvPy)) { throw "Failed to create backend\.venv" }
    return $venvPy
}

function Assert-Node {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "npm / Node.js 18+ is required."
    }
}

function Ensure-BackendDeps([string]$Python) {
    $fastapi = Join-Path $Root "backend\.venv\Lib\site-packages\fastapi"
    if (Test-Path $fastapi) { return }
    Write-Host "Installing backend dependencies (first run)..."
    Push-Location (Join-Path $Root "backend")
    try {
        & $Python -m pip install -e ".[dev]"
        if ($LASTEXITCODE -ne 0) { throw "Backend dependency install failed." }
    } finally {
        Pop-Location
    }
}

function Ensure-FrontendDeps {
    if (Test-Path (Join-Path $Root "frontend\node_modules\vite")) { return }
    Write-Host "Installing frontend dependencies (first run)..."
    Push-Location (Join-Path $Root "frontend")
    try {
        npm install
        if ($LASTEXITCODE -ne 0) { throw "Frontend dependency install failed." }
    } finally {
        Pop-Location
    }
}

function Start-Backend([string]$Python) {
    if (Test-HttpOk $ApiUrl) {
        Write-Host "API already running: $ApiUrl"
        return
    }
    $line = 'title novel2Lens API && "' + $Python + '" -m uvicorn app.main:app --host ' + $ApiHost + ' --port ' + $ApiPort
    Start-Process -FilePath "cmd.exe" -WorkingDirectory (Join-Path $Root "backend") -ArgumentList @("/k", $line)
}

function Start-Frontend {
    if (Test-HttpOk $UiUrl) {
        Write-Host "UI already running: $UiUrl"
        return
    }
    Start-Process -FilePath "cmd.exe" -WorkingDirectory (Join-Path $Root "frontend") -ArgumentList @("/k", "title novel2Lens UI && npm run dev")
}

function Wait-Service([string]$Name, [string]$Url, [int]$Seconds = 45) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpOk $Url) {
            Write-Host "$Name ready: $Url"
            return
        }
        Start-Sleep -Milliseconds 400
    }
    throw "$Name failed to start within ${Seconds}s: $Url"
}

Write-Host "novel2Lens one-shot start"
$python = Get-VenvPython
Assert-Node
Ensure-BackendDeps $python
Ensure-FrontendDeps
Start-Backend $python
Start-Frontend
Wait-Service "API" $ApiUrl
Wait-Service "UI" $UiUrl
Start-Process $UiUrl
Write-Host "Opened $UiUrl"
Write-Host "Close the novel2Lens API / novel2Lens UI windows to stop."
