$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or -not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    throw 'Для обработки нужны ffmpeg и ffprobe в PATH. На компьютере разработки они уже установлены.'
}
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv --system-site-packages .venv
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось создать Python-окружение.' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Ошибка установки Python-зависимостей.' }
Push-Location -LiteralPath frontend
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw 'Ошибка установки npm-зависимостей.' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Ошибка сборки интерфейса.' }
} finally { Pop-Location }
& '.\.venv\Scripts\python.exe' -m scripts.prepare_demo
if ($LASTEXITCODE -ne 0) { throw 'Ошибка подготовки примера.' }
Write-Output 'Установка завершена. Запуск: .\start.ps1'
