@echo off
REM start.bat — Inicia Wealth Engine (executor + opcional dashboard)
REM Uso: duplo-clique ou cmd

cd /d "%~dp0.."
python bot/manager.py start --components=executor
if %errorLevel% neq 0 (
    echo [ERRO] Falha ao iniciar. Verifique logs em bot\run\wealth-manager.log
)
pause