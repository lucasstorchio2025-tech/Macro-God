@echo off
REM stop.bat — Para Wealth Engine graciosamente

cd /d "%~dp0.."
python bot/manager.py stop
pause