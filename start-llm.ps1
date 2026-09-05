#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$HostAddr = "127.0.0.1"
$Port = 8080
$Health = "http://${HostAddr}:${Port}/v1/models"
$Ctx = if ($env:N2L_LLM_CTX) { $env:N2L_LLM_CTX } else { "32768" }

function Test-HttpOk([string]$Url) {
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        return $resp.StatusCode -ge 200 -and $resp.StatusCode -lt 400
    } catch {
        return $false
    }
}

function Resolve-FlashNextDir {
    if ($env:N2L_FLASH_NEXT_DIR -and (Test-Path -LiteralPath $env:N2L_FLASH_NEXT_DIR)) {
        return (Resolve-Path -LiteralPath $env:N2L_FLASH_NEXT_DIR).Path
    }
    $parent = "D:\Download\Quark\DownloadFiles"
    $hit = Get-ChildItem -LiteralPath $parent -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "*Flash-Next*" } |
        Select-Object -First 1
    if (-not $hit) {
        throw "Flash-Next folder not found under $parent. Set N2L_FLASH_NEXT_DIR."
    }
    return $hit.FullName
}

if (Test-HttpOk $Health) {
    Write-Host "Flash-Next already running: $Health"
    exit 0
}

$modelRoot = Resolve-FlashNextDir
$llamaDir = Join-Path $modelRoot "llama.cpp"
$exe = Join-Path $llamaDir "llama-server.exe"
$model = Join-Path $llamaDir "models\Qwen3.8-Flash-Next-UD-IQ4_XS-00001-of-00003.gguf"
if (-not (Test-Path -LiteralPath $exe)) {
    throw "Missing $exe - extract llama.cpp package first."
}
if (-not (Test-Path -LiteralPath $model)) {
    throw "Missing $model"
}

Write-Host "Starting Qwen3.8-Flash-Next-UD-IQ4_XS on :$Port (ctx=$Ctx)..."
$argList = @(
    "-m", $model,
    "-c", $Ctx,
    "-cmoe",
    "-b", "1024", "-ub", "1024",
    "-ngl", "999",
    "--port", "$Port",
    "--host", $HostAddr,
    "-fa", "on",
    "-rea", "off",
    "--reasoning-format", "none",
    "--context-shift",
    "-a", "qwen3.8-flash-next",
    "--jinja"
)
$quoted = foreach ($a in $argList) {
    if ($a -match '\s') { '"' + $a + '"' } else { $a }
}
$argLine = $quoted -join " "
$cmd = 'title novel2Lens Flash-Next && "' + $exe + '" ' + $argLine
Start-Process -FilePath "cmd.exe" -WorkingDirectory $llamaDir -ArgumentList @("/k", $cmd)

$deadline = (Get-Date).AddMinutes(15)
while ((Get-Date) -lt $deadline) {
    if (Test-HttpOk $Health) {
        Write-Host "Flash-Next ready: $Health"
        exit 0
    }
    Start-Sleep -Seconds 2
}
throw "Flash-Next failed to become ready within 15 minutes."
