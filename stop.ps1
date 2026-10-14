$ErrorActionPreference = 'Stop'
$health = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/health' -TimeoutSec 3
if ($health.app_id -ne 'parking-warm-map') { throw 'На этом порту не найден сервер проекта. Другие процессы не останавливаются.' }
$parkingListener = Get-NetTCPConnection -LocalPort 8765 -State Listen | Select-Object -First 1
$parkingProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($parkingListener.OwningProcess)"
if ($parkingProcess.CommandLine -notmatch 'uvicorn backend.app:app') { throw 'Неожиданный процесс; остановка отменена.' }
Stop-Process -Id $parkingListener.OwningProcess
Write-Output 'Веб-сервер остановлен. Активный анализ остановите кнопкой «Отменить» перед закрытием сайта.'
