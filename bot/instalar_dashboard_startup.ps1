# instalar_dashboard_startup.ps1 (DEPRECATED)
# ⚠️  Use instalar_startup_completo.ps1 para iniciar o SISTEMA COMPLETO
#    (Dashboard + Watchdog + Executor + Intel)
#
# Este script cria atalho APENAS do Dashboard Mestre.
# Para o sistema completo, execute:
#   bot\instalar_startup_completo.ps1

Write-Host "============================================" -ForegroundColor Yellow
Write-Host "  ⚠️  SCRIPT DEPRECATED " -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Este script instala APENAS o Dashboard Mestre." -ForegroundColor Yellow
Write-Host "  Para iniciar o SISTEMA COMPLETO ao ligar o PC:" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Recomendado: instalar_startup_completo.ps1" -ForegroundColor Green
Write-Host "  (Dashboard + Watchdog + Executor + Intelligence)" -ForegroundColor Green
Write-Host ""
Write-Host "  Deseja continuar instalando apenas o Dashboard?" -ForegroundColor Yellow
$choice = Read-Host "  (S/N, padrão=N)"
if ($choice -ne "S" -and $choice -ne "s") {
    Write-Host ""
    Write-Host "  Use o novo script completo:" -ForegroundColor Cyan
    Write-Host "    bot\instalar_startup_completo.ps1" -ForegroundColor Cyan
    exit 0
}

$startupPath = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupPath "Wealth_Engine_Dashboard.lnk"

if (Test-Path $shortcutPath) {
    Write-Host ""
    Write-Host "Atalho ja existe: $shortcutPath" -ForegroundColor Yellow
    exit 0
}

$wshShell = New-Object -ComObject WScript.Shell
$shortcut = $wshShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "$env:USERPROFILE\Wealth_Engine\bot\abrir_dashboard.bat"
$shortcut.WorkingDirectory = "$env:USERPROFILE\Wealth_Engine"
$shortcut.WindowStyle = 7
$shortcut.Description = "Wealth Engine - Painel Mestre (inicia automaticamente ao ligar o PC)"
$shortcut.Save()

Write-Host ""
Write-Host "Atalho criado: $shortcutPath" -ForegroundColor Green
Write-Host ""
Write-Host "O Dashboard Mestre agora inicia automaticamente ao ligar o PC!"
Write-Host "Acesse em: http://localhost:8501" -ForegroundColor Cyan
Write-Host ""
Write-Host "💡 Dica: para iniciar o SISTEMA COMPLETO, use:" -ForegroundColor Yellow
Write-Host "   bot\instalar_startup_completo.ps1" -ForegroundColor Yellow
