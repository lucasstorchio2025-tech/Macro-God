@echo off
REM ============================================================
REM Wealth Engine v4 — STOP ALL SERVICES
REM ============================================================

set NSSM=C:\Program Files\nssm\nssm.exe

echo [1/4] Parando servicos WealthEngine...
net stop WealthEngine_API 2>nul
net stop WealthEngine_Dashboard 2>nul
net stop WealthEngine_Bot 2>nul
net stop WealthEngine_Ollama 2>nul

echo [2/4] Matando processos remanescentes...
taskkill /F /IM "ollama.exe" 2>nul
taskkill /F /IM "python.exe" 2>nul
taskkill /F /IM "streamlit.exe" 2>nul
taskkill /F /IM "uvicorn.exe" 2>nul

echo [3/4] Enviando Telegram de shutdown...
C:\Users\lucas\Wealth_Engine\venv\Scripts\python.exe -c "
import sys; sys.path.insert(0, r'C:\Users\lucas\Wealth_Engine')
from bot.core.notify import notifier
notifier.crisis('🔴 WEALTH ENGINE v4 PARADO - Shutdown completo')
" 2>nul

echo [4/4] Verificando...
sc query WealthEngine_Ollama | find "STOPPED" && echo Ollama: PARADO || echo Ollama: AINDA RODANDO
sc query WealthEngine_Bot | find "STOPPED" && echo Bot: PARADO || echo Bot: AINDA RODANDO
sc query WealthEngine_Dashboard | find "STOPPED" && echo Dashboard: PARADO || echo Dashboard: AINDA RODANDO
sc query WealthEngine_API | find "STOPPED" && echo API: PARADO || echo API: AINDA RODANDO

echo.
echo Todos servicos WealthEngine parados.
pause