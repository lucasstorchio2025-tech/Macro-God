# instalar_startup_completo.ps1
# Instala o Wealth Engine completo na inicializacao do Windows
# Inicia: Dashboard + Watchdog + Executor automaticamente ao ligar o PC

$ErrorActionPreference = "Stop"

$startupPath = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupPath "Wealth_Engine_System.lnk"
$targetPath = "C:\Users\lucas\Wealth_Engine\bot\start_all.bat"
$workingDir  = "C:\Users\lucas\Wealth_Engine"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  WEALTH ENGINE - Instalar Startup Completa" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Verifica se start_all.bat existe
if (-not (Test-Path $targetPath)) {
    Write-Host "[ERRO] start_all.bat nao encontrado" -ForegroundColor Red
    Write-Host "  $targetPath" -ForegroundColor Red
    exit 1
}

# Verifica se atalho ja existe
if (Test-Path $shortcutPath) {
    $choice = Read-Host "Ja existe. Recriar? (S/N)"
    if ($choice -ne "S" -and $choice -ne "s") {
        Write-Host "[OK] Mantido. Sistema ja inicia automaticamente." -ForegroundColor Green
        exit 0
    }
}

# Cria o atalho
try {
    $wshShell = New-Object -ComObject WScript.Shell
    $shortcut = $wshShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $targetPath
    $shortcut.WorkingDirectory = $workingDir
    $shortcut.WindowStyle = 7
    $shortcut.Description = "Wealth Engine - Sistema Completo (Dashboard + Bot + Intel)"
    $shortcut.Save()

    Write-Host "[OK] Atalho criado:" -ForegroundColor Green
    Write-Host "  $shortcutPath" -ForegroundColor Green
    Write-Host ""
    Write-Host "Ao ligar o PC, o sistema inicia automaticamente:"
    Write-Host "  - Dashboard Mestre (http://localhost:8501)"
    Write-Host "  - Watchdog (monitora o executor 24/7)"
    Write-Host "  - Executor Auto-Trader"
    Write-Host "  - Intelligence Pipeline (a cada ~4h)"
    Write-Host ""

    $testNow = Read-Host "Iniciar o sistema AGORA? (S/N)"
    if ($testNow -eq "S" -or $testNow -eq "s") {
        Start-Process -FilePath $targetPath -WindowStyle Minimized
        Write-Host "[OK] Sistema iniciado! Abra http://localhost:8501" -ForegroundColor Green
    }
}
catch {
    Write-Host "[ERRO] Nao foi possivel criar o atalho:" -ForegroundColor Red
    Write-Host "  $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "Tente executar como Administrador (clique direito)" -ForegroundColor Yellow
    exit 1
}
