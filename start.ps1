param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$dataPath = Join-Path $projectRoot 'data'
if (-not (Test-Path -LiteralPath $pythonPath) -or -not (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend\dist\index.html'))) {
    throw 'Сначала выполните setup.ps1 в папке проекта.'
}
$ready = $false
try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 2
    $ready = $health.app_id -eq 'parking-warm-map'
} catch { $ready = $false }
if (-not $ready) {
    $listener = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
    if ($listener) { throw 'Порт 8765 занят другим процессом. Освободите его перед запуском.' }
    New-Item -ItemType Directory -Path $dataPath -Force | Out-Null
    $process = Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn','backend.app:app','--host','127.0.0.1','--port','8765') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dataPath 'server.log') -RedirectStandardError (Join-Path $dataPath 'server-error.log')
    Set-Content -LiteralPath (Join-Path $dataPath 'server.pid') -Value $process.Id
    for ($attempt=0; $attempt -lt 40; $attempt++) {
        Start-Sleep -Milliseconds 250
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 2
            if ($health.app_id -eq 'parking-warm-map') { $ready=$true; break }
        } catch { if ($process.HasExited) { break } }
    }
    if (-not $ready) { throw 'Сервер не запустился. Проверьте data\server-error.log.' }
}
Write-Output 'Парковка: http://127.0.0.1:8765'
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:8765' }
