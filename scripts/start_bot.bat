@echo off
REM ============================================================
REM Wealth Engine v4 — BOT START (Task Scheduler at logon)
REM Robusto: sem timeout, sem start /B, sem deteção falha de PID
REM ============================================================

cd /d "C:\Users\lucas\Wealth_Engine"

REM Se já existe launcher.pid com processo vivo, sai
if exist "bot\run\launcher.pid" (
    for /F "tokens=*" %%P in (bot\run\launcher.pid) do (
        tasklist /FI "PID eq %%P" /NH 2>nul | find "%%P" >nul 2>&1
        if not errorlevel 1 (
            echo Bot ja rodando PID %%P
            exit /b 0
        )
    )
    del /f /q "bot\run\launcher.pid" 2>nul
)

REM Kill launcher.log velho pra nao confundir dashboard
if exist "bot\run\launcher.log" del /f /q "bot\run\launcher.log" 2>nul
if exist "bot\run\heartbeat.json" del /f /q "bot\run\heartbeat.json" 2>nul

REM Aguarda 20s pra MT5 estar pronto (powershell sleep)
powershell -NoProfile -Command "Start-Sleep -Seconds 20" 2>nul

REM Start bot FOREGROUND (bloqueia até travar/morrer, Task restart se crashed)
"venv\Scripts\python.exe" -u "bot\launcher.py"
echo Bot exited with code %ERRORLEVEL%
exit /b %ERRORLEVEL%