@echo off
REM ============================================================
REM Wealth Engine v4 — RESTART ALL SERVICES
REM ============================================================

call scripts\stop_all.bat
echo.
echo Aguardando 5 segundos...
timeout /t 5 /nobreak
echo.
call scripts\install_startup_complete.bat