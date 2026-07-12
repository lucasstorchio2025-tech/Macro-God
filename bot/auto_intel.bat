@echo off
rem WEALTH_ENGINE — Auto Intelligence + Post-Trade Analysis
rem Roda o pipeline de inteligencia e a analise pos-trade.
rem Ideal para agendar no Windows Task Scheduler a cada 4h.
title Wealth_Engine_Intel_Pipeline
cd /d C:\Users\lucas\Wealth_Engine
set PYTHON_EXE=C:\Users\lucas\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe
if not exist "%PYTHON_EXE%" set PYTHON_EXE=python

echo [%date% %time%] ========================================
echo [%date% %time%] WEALTH ENGINE — Intel + Post-Trade
echo [%date% %time%] ========================================

echo.
echo [%date% %time%] --- 1/3: Intelligence Hub ---
"%PYTHON_EXE%" -u scripts/run_intelligence.py
if %ERRORLEVEL% NEQ 0 (
    echo [%date% %time%] [AVISO] Intelligence pipeline retornou erro %ERRORLEVEL%
)

echo.
echo [%date% %time%] --- 2/3: Post-Trade Analysis ---
"%PYTHON_EXE%" -u bot/post_trade_analysis.py
if %ERRORLEVEL% NEQ 0 (
    echo [%date% %time%] [AVISO] Post-trade analysis retornou erro %ERRORLEVEL%
)

echo.
echo [%date% %time%] --- 3/3: Verificando se o executor esta rodando ---
tasklist /FI "IMAGENAME eq python.exe" /V 2>nul | findstr /I "executor.py" >nul
if %ERRORLEVEL% NEQ 0 (
    echo [%date% %time%] [AVISO] Executor NAO esta rodando! Iniciando...
    start /min "" "C:\Users\lucas\Wealth_Engine\bot\run_executor.bat"
    echo [%date% %time%] Executor iniciado.
) else (
    echo [%date% %time%] Executor esta rodando. OK.
)

echo.
echo [%date% %time%] ========================================
echo [%date% %time%] Pipeline completo.
echo [%date% %time%] ========================================
