@echo off
REM restart.bat — Reinicia Wealth Engine

cd /d "%~dp0.."
python bot/manager.py restart
pause