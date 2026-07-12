@echo off
rem Wealth_Engine Auto-Trader (demo)
rem Roda em loop a cada 5 min. Logs em %~dp0
title Wealth_Engine_AutoTrader
set PYTHON_EXE=C:\Users\lucas\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe
if not exist "%PYTHON_EXE%" set PYTHON_EXE=python
cd /d %~dp0..
echo [%date% %time%] Iniciando Wealth_Engine executor...
"%PYTHON_EXE%" -u bot\executor.py
echo [%date% %time%] Executor finalizado.
pause
