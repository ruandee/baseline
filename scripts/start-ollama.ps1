param(
    [ValidateSet('arm64','amd64')][string]$Architecture = 'arm64',
    [string]$Model = 'qwen3.5:0.8b',
    [switch]$TextOnly
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
if ($TextOnly) {
    # Pinned primary Q8_0 weights from the official qwen3.5:0.8b manifest.
    $modelHash = '889ea3b9143cdc32146c7d530ce5f3d452ec18069086f6f4167ce9ae72a9691f'
    $modelBlob = Join-Path $env:OLLAMA_MODELS "blobs/sha256-$modelHash"
    New-Item -ItemType Directory -Force (Split-Path $modelBlob -Parent) | Out-Null
    if (!(Test-Path $modelBlob)) {
        Invoke-WebRequest "https://registry.ollama.ai/v2/library/qwen3.5/blobs/sha256:$modelHash" -OutFile "$modelBlob.download"
        if ((Get-FileHash "$modelBlob.download" -Algorithm SHA256).Hash -ne $modelHash) { throw 'Model checksum mismatch' }
        Move-Item -LiteralPath "$modelBlob.download" -Destination $modelBlob
    }
    if ((Get-FileHash $modelBlob -Algorithm SHA256).Hash -ne $modelHash) { throw 'Model checksum mismatch' }
    $licenseHash = '50cbab8a892c5f2993b8c7351a99182507472def3b1374558308605d99b86b32'
    $licenseFile = Join-Path $toolRoot 'model-license.txt'
    Invoke-WebRequest "https://registry.ollama.ai/v2/library/qwen3.5/blobs/sha256:$licenseHash" -OutFile $licenseFile
    if ((Get-FileHash $licenseFile -Algorithm SHA256).Hash -ne $licenseHash) { throw 'License checksum mismatch' }
    $licenseText = [IO.File]::ReadAllText($licenseFile)
    $modelDefinition = "FROM `"$modelBlob`"`nPARAMETER num_ctx 8192`nLICENSE `"`"`"`n$licenseText`n`"`"`"`n"
    $modelDefinitionPath = Join-Path $toolRoot 'Modelfile-text-only'
    [IO.File]::WriteAllText($modelDefinitionPath, $modelDefinition)
    $created = Start-Process -FilePath $ollamaExe -ArgumentList @('create','patient-memory-qwen35:0.8b','-f',('"'+$modelDefinitionPath+'"')) `
        -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput (Join-Path $toolRoot 'create.log') `
        -RedirectStandardError (Join-Path $toolRoot 'create-error.log')
    if ($created.ExitCode -ne 0) { throw 'Text-only model import failed; inspect .tools/ollama/create-error.log' }
    Write-Output 'Use PM_PROVIDER_MODEL=patient-memory-qwen35:0.8b for the text-only import.'
    return
}
$pulled = Start-Process -FilePath $ollamaExe -ArgumentList @('pull',$Model) -WindowStyle Hidden -Wait -PassThru `
    -RedirectStandardOutput (Join-Path $toolRoot 'pull.log') -RedirectStandardError (Join-Path $toolRoot 'pull-error.log')
if ($pulled.ExitCode -ne 0) { throw 'Model download failed; inspect .tools/ollama/pull-error.log and rerun to resume' }
Write-Output "Ollama is serving $Model on loopback port 11434. Model files are under .models/."
