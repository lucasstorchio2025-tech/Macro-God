@echo off
REM install_service.bat — Instala Wealth Engine como Windows Service (NSSM)
REM Uso: clique duas vezes ou rode no cmd/powershell como Administrador

echo ==========================================
echo Wealth Engine v4 - Windows Service Install
echo ==========================================
echo.

REM Verifica se é Admin
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERRO] Precisa rodar como Administrador!
    echo Clique com botao direito no cmd/powershell > "Executar como administrador"
    pause
    exit /b 1
)

REM Detecta python.exe do ambiente atual
for %%i in ("%~dp0..\") do set PROJECT_ROOT=%%~fi
cd /d "%PROJECT_ROOT%"

echo Projeto: %PROJECT_ROOT%
echo Python:  %~dp0..\..\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe  (ajuste se necessário)

REM Chama o manager.py install
python bot/manager.py install

if %errorLevel% equ 0 (
    echo.
    echo [OK] Servico instalado com sucesso!
    echo Para iniciar:   python bot/manager.py service-start
    echo Para status:    python bot/manager.py status
    echo Para logs:      type bot\run\service.log
    echo Para remover:   python bot/manager.py uninstall
) else (
    echo.
    echo [FALHA] Verifique os logs acima.
)

pause