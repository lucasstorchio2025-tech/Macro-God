@echo off
title Wealth_Engine_System
cd /d C:\Users\lucas\Wealth_Engine

set PYTHON_EXE=C:\Users\lucas\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe
if not exist "%PYTHON_EXE%" set PYTHON_EXE=python

echo ============================================
echo     WEALTH ENGINE — INICIANDO SISTEMA
echo     %date% %time%
echo ============================================

:: ─── 1. Dashboard (delega pro abrir_dashboard.bat que ja funciona) ───
echo  [..] Verificando Dashboard Mestre...
netstat -ano | findstr ":8501" >nul 2>&1
if %errorlevel%==0 (
    echo  [OK] Dashboard ja esta rodando na porta 8501
) else (
    echo  [..] Iniciando Dashboard Mestre...
    start /min "Wealth_Dashboard" cmd /c "C:\Users\lucas\Wealth_Engine\bot\abrir_dashboard.bat"
    echo  [OK] Dashboard inicializando... (http://localhost:8501)
)

:: ─── 2. Watchdog (monitora o executor) ───
echo  [..] Iniciando Watchdog...
start /min "Wealth_Engine_Watchdog_v2" cmd /c "C:\Users\lucas\Wealth_Engine\bot\watchdog_supervisor.bat"
echo  [OK] Watchdog iniciado (monitora executor 24/7)

:: ─── 3. Intel inicial ───
echo  [..] Rodando intelligence inicial...
start /min "Wealth_Intel" cmd /c ""%PYTHON_EXE%" -u scripts/run_intelligence.py"
echo  [OK] Intelligence inicial rodando em segundo plano

echo.
echo ============================================
echo     WEALTH ENGINE — SISTEMA INICIADO!
echo     %date% %time%
echo.
echo     📍 Dashboard: http://localhost:8501
echo     📍 Status:    bot\status.bat
echo ============================================
