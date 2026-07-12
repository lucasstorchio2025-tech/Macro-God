@echo off
rem Watchdog externo - relanca o executor se cair + atualiza intel a cada ~4h
rem Usa WMIC (mais confiavel) com fallback pra tasklist
title Wealth_Engine_Watchdog_v2
cd /d %~dp0..

set /a intel_counter=0
set /a intel_interval=120

:loop
rem ---- 1. Verifica se executor esta vivo ----
rem Metodo 1: WMIC busca por linha de comando (mais preciso)
wmic process where "name='python.exe' and commandline like '%%executor.py%%'" get processid 2>nul | findstr /r "[0-9]" >nul
set DETECTED=%ERRORLEVEL%

rem Metodo 2 (fallback): tasklist por window title (se wmic falhar)
if %DETECTED% NEQ 0 (
    tasklist /FI "WINDOWTITLE eq Wealth_Engine_AutoTrader" 2>nul | findstr /I "python" >nul
    set DETECTED=%ERRORLEVEL%
)

if %DETECTED% NEQ 0 (
    echo [%date% %time%] Executor NAO detectado. Relancando...
    start /min "Wealth_Engine_AutoTrader" cmd /c "%~dp0run_executor.bat"
    echo [%date% %time%] Relancado. Aguardando 60s.
    timeout /t 60 /nobreak >nul
) else (
    echo [%date% %time%] Executor vivo.
    timeout /t 30 /nobreak >nul
)

rem ---- 2. A cada ~4h, atualiza intelligence + analise pos-trade ----
set /a intel_counter+=1
if %intel_counter% GEQ %intel_interval% (
    echo [%date% %time%] --- Atualizando intelligence ---
    start /min "Wealth_Intel" cmd /c "%~dp0auto_intel.bat"
    set /a intel_counter=0
)

goto loop
