# ============================================================
#  VPNBot — развёртывание серверов из servers.json
# ============================================================
#  Вся логика теперь в deploy.py (asyncssh, без sshpass).
#  Просто запусти:
#      powershell -ExecutionPolicy Bypass -File deploy-vps.ps1
# ============================================================

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  VPNBot — автоустановка 3x-ui" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Проверяем Python
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

Write-Host "Python: $python" -ForegroundColor Gray
Write-Host "Серверы берутся из servers.json / servers.txt" -ForegroundColor Gray
Write-Host ""

& $python deploy.py --deploy --no-run

Write-Host ""
Write-Host "Готово. Запусти бота:" -ForegroundColor Yellow
Write-Host "  $python -m app.main" -ForegroundColor White
