param(
    [ValidateSet('arm64','amd64')][string]$Architecture = 'arm64',
    [string]$Model = 'qwen3.5:0.8b'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$toolRoot = Join-Path $projectRoot '.tools/ollama'
$runtimeRoot = Join-Path $toolRoot 'runtime'
$version = 'v0.40.5'
$asset = "ollama-windows-$Architecture.zip"
New-Item -ItemType Directory -Force $toolRoot | Out-Null
if (!(Test-Path (Join-Path $runtimeRoot 'ollama.exe'))) {
    $base = "https://github.com/ollama/ollama/releases/download/$version"
    Invoke-WebRequest "$base/$asset" -OutFile (Join-Path $toolRoot $asset)
    Invoke-WebRequest "$base/sha256sum.txt" -OutFile (Join-Path $toolRoot 'sha256sum.txt')
    $line = Get-Content (Join-Path $toolRoot 'sha256sum.txt') | Where-Object { $_.EndsWith("./$asset") }
    if (!$line) { throw 'Release checksum entry is missing' }
    $expectedHash = ($line -split '\s+')[0]
    $actualHash = (Get-FileHash (Join-Path $toolRoot $asset) -Algorithm SHA256).Hash
    if ($actualHash -ne $expectedHash) { throw 'Ollama release checksum mismatch' }
    Expand-Archive -LiteralPath (Join-Path $toolRoot $asset) -DestinationPath $runtimeRoot
}
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_MODELS = Join-Path $projectRoot '.models'
$ollamaExe = Join-Path $runtimeRoot 'ollama.exe'
try { Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 | Out-Null }
catch {
    Start-Process -FilePath $ollamaExe -ArgumentList 'serve' -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $toolRoot 'server.log') `
        -RedirectStandardError (Join-Path $toolRoot 'server-error.log') | Out-Null
    for ($attempt=0; $attempt -lt 20; $attempt++) {
        try { Invoke-RestMethod 'http://127.0.0.1:11434/api/version' -TimeoutSec 2 | Out-Null; break }
        catch { Start-Sleep -Seconds 1 }
    }
}
& $ollamaExe pull $Model
if ($LASTEXITCODE -ne 0) { throw 'Model download failed; rerun to resume' }
Write-Output "Ollama is serving $Model on loopback port 11434. Model files are under .models/."
