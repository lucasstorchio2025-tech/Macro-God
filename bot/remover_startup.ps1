# remover_startup.ps1
# Remove o Wealth Engine da inicialização do Windows

$ErrorActionPreference = "Stop"

$startupPath = [Environment]::GetFolderPath("Startup")
$shortcutPaths = @(
    (Join-Path $startupPath "Wealth_Engine_System.lnk"),
    (Join-Path $startupPath "Wealth_Engine_Dashboard.lnk")
)

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  WEALTH ENGINE — Remover da Inicializacao" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

$found = $false
foreach ($path in $shortcutPaths) {
    if (Test-Path $path) {
        Remove-Item $path -Force
        Write-Host "  [REMOVED] $path" -ForegroundColor Yellow
        $found = $true
    }
}

if (-not $found) {
    Write-Host "  Nenhum atalho do Wealth Engine encontrado na Startup." -ForegroundColor Green
    Write-Host "  O sistema ja nao inicia automaticamente." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "  [OK] Wealth Engine removido da inicializacao do Windows." -ForegroundColor Green
    Write-Host "  O sistema nao iniciara mais automaticamente ao ligar o PC." -ForegroundColor Green
    Write-Host ""
    Write-Host "  Para re-instalar, execute:" -ForegroundColor Yellow
    Write-Host "    bot\instalar_startup_completo.ps1" -ForegroundColor Yellow
}

pause
