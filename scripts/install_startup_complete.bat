@echo off
REM ============================================================
REM Wealth Engine v4 — STARTUP MANAGER (CORRIGIDO)
REM Desativa lixo, inicia stack na ordem correta
REM Execute como ADMINISTRADOR
REM ============================================================

set PROJECT_ROOT=C:\Users\lucas\Wealth_Engine
set PYTHON=%PROJECT_ROOT%\venv\Scripts\python.exe
set NSSM=C:\Program Files\nssm\nssm.exe

echo [1/7] Desativando programas desnecessários no startup...

REM --- Steam ---
reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "Steam" /d "" /f 2>nul
schtasks /Change /TN "Steam Login" /DISABLE 2>nul

REM --- Discord ---
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "Discord" /f 2>nul
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v "Discord" /f 2>nul

REM --- AnyDesk ---
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "AnyDesk" /f 2>nul
sc config "AnyDesk" start= disabled 2>nul

REM --- CrewAI / AutoGPT / etc ---
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "CrewAI" /f 2>nul
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "AutoGPT" /f 2>nul

REM --- OneDrive (opcional, comenta se usa) ---
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "OneDrive" /f 2>nul

REM --- Teams ---
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "Teams" /f 2>nul
schtasks /Change /TN "Microsoft\Office\OfficeTelemetryAgentLogOn" /DISABLE 2>nul

echo [2/7] Verificando NSSM...
if not exist "%NSSM%" (
    echo NSSM nao encontrado em %NSSM%
    echo Baixe de https://nssm.cc/download e coloque em C:\Program Files\nssm\nssm.exe
    pause
    exit /b 1
)

echo [3/7] Instalando servicos Windows (ordem de dependencia)...

REM ============================================================
REM SERVIÇO 1: Ollama (precisa subir antes do bot)
REM ============================================================
"%NSSM%" install WealthEngine_Ollama "C:\Users\lucas\AppData\Local\Programs\Ollama\ollama.exe" "serve"
"%NSSM%" set WealthEngine_Ollama AppDirectory "C:\Users\lucas\AppData\Local\Programs\Ollama"
"%NSSM%" set WealthEngine_Ollama AppStdout "C:\Users\lucas\Wealth_Engine\bot\run\ollama.log"
"%NSSM%" set WealthEngine_Ollama AppStderr "C:\Users\lucas\Wealth_Engine\bot\run\ollama.log"
"%NSSM%" set WealthEngine_Ollama AppRotateFiles 1
"%NSSM%" set WealthEngine_Ollama AppRotateOnline 1
"%NSSM%" set WealthEngine_Ollama AppRotateSeconds 86400
"%NSSM%" set WealthEngine_Ollama Start SERVICE_AUTO_START
"%NSSM%" set WealthEngine_Ollama DependOnService ""
sc failure WealthEngine_Ollama reset=86400 actions=restart/5000/restart/10000/restart/30000

REM ============================================================
REM SERVIÇO 2: MT5 Terminal (Exness) - Task Scheduler (precisa UI)
REM ============================================================
echo Criando tarefa MT5_Exness_Startup...
REM Ajuste o caminho do terminal64.exe se estiver em outro lugar
schtasks /Create /TN "WealthEngine_MT5_Startup" /TR "\"C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe\"" /SC ONLOGON /RL HIGHEST /F 2>nul
REM Para login automático, edite a tarefa no Task Scheduler ou use .env

REM ============================================================
REM SERVIÇO 3: Bot Executor (depende de Ollama)
REM ============================================================
"%NSSM%" install WealthEngine_Bot "%PYTHON%" "-u bot/executor.py"
"%NSSM%" set WealthEngine_Bot AppDirectory "%PROJECT_ROOT%"
"%NSSM%" set WealthEngine_Bot AppStdout "%PROJECT_ROOT%\bot\run\executor.log"
"%NSSM%" set WealthEngine_Bot AppStderr "%PROJECT_ROOT%\bot\run\executor.log"
"%NSSM%" set WealthEngine_Bot AppRotateFiles 1
"%NSSM%" set WealthEngine_Bot AppRotateOnline 1
"%NSSM%" set WealthEngine_Bot AppRotateSeconds 86400
"%NSSM%" set WealthEngine_Bot Start SERVICE_AUTO_START
"%NSSM%" set WealthEngine_Bot DependOnService "WealthEngine_Ollama"
sc failure WealthEngine_Bot reset=86400 actions=restart/5000/restart/10000/restart/30000

REM Variaveis de ambiente do bot
"%NSSM%" set WealthEngine_Bot AppEnvironmentExtra "WEALTH_POLL_SECONDS=30;DRY_RUN_MODE=False;PYTHONPATH=%PROJECT_ROOT%"

REM ============================================================
REM SERVIÇO 4: Dashboard Streamlit (opcional, so localhost)
REM ============================================================
"%NSSM%" install WealthEngine_Dashboard "%PYTHON%" "-m streamlit run wealth_dashboard.py --server.address=127.0.0.1 --server.port=8501 --server.headless=true"
"%NSSM%" set WealthEngine_Dashboard AppDirectory "%PROJECT_ROOT%"
"%NSSM%" set WealthEngine_Dashboard AppStdout "%PROJECT_ROOT%\bot\run\dashboard.log"
"%NSSM%" set WealthEngine_Dashboard AppStderr "%PROJECT_ROOT%\bot\run\dashboard.log"
"%NSSM%" set WealthEngine_Dashboard Start SERVICE_AUTO_START
"%NSSM%" set WealthEngine_Dashboard DependOnService "WealthEngine_Bot"

REM ============================================================
REM SERVIÇO 5: FastAPI Read-only (para cron/monitoramento)
REM ============================================================
"%NSSM%" install WealthEngine_API "%PYTHON%" "-m uvicorn bot.api.server:app --host 127.0.0.1 --port 8000"
"%NSSM%" set WealthEngine_API AppDirectory "%PROJECT_ROOT%"
"%NSSM%" set WealthEngine_API AppStdout "%PROJECT_ROOT%\bot\run\api.log"
"%NSSM%" set WealthEngine_API AppStderr "%PROJECT_ROOT%\bot\run\api.log"
"%NSSM%" set WealthEngine_API Start SERVICE_AUTO_START
"%NSSM%" set WealthEngine_API DependOnService "WealthEngine_Bot"

REM ============================================================
REM SERVIÇO 6: Hermes Cron (auto-improvement) - ja existe no Hermes
REM ============================================================
echo Hermes cron ja configurado via hermes-agent (0 3 * * *)

echo [4/7] Iniciando servicos na ordem...
net start WealthEngine_Ollama
timeout /t 10 /nobreak
net start WealthEngine_Bot
timeout /t 5 /nobreak
net start WealthEngine_Dashboard
net start WealthEngine_API

echo [5/7] Verificando status...
sc query WealthEngine_Ollama | find "RUNNING" && echo Ollama: OK || echo Ollama: FALHOU
sc query WealthEngine_Bot | find "RUNNING" && echo Bot: OK || echo Bot: FALHOU
sc query WealthEngine_Dashboard | find "RUNNING" && echo Dashboard: OK || echo Dashboard: FALHOU
sc query WealthEngine_API | find "RUNNING" && echo API: OK || echo API: FALHOU

echo [6/7] Testando healthchecks...
timeout /t 5 /nobreak
curl -s http://127.0.0.1:9090/health && echo  Manager healthcheck OK || echo  Manager healthcheck FALHOU
curl -s http://127.0.0.1:8000/health && echo  API healthcheck OK || echo  API healthcheck FALHOU

echo [7/7] Enviando Telegram de startup...
%PYTHON% -c "
import sys; sys.path.insert(0, r'%PROJECT_ROOT%')
from bot.core.notify import notifier
notifier.crisis('🟢 WEALTH ENGINE v4 INICIADO - Boot completo')
" 2>nul

echo.
echo ============================================================
echo  WEALTH ENGINE v4 — STARTUP CONCLUIDO
echo ============================================================
echo Servicos instalados e rodando:
echo   1. WealthEngine_Ollama      (auto, depende: -)
echo   2. WealthEngine_MT5_Startup (Task Scheduler, logon)
echo   3. WealthEngine_Bot         (auto, depende: Ollama)
echo   4. WealthEngine_Dashboard   (auto, depende: Bot)
echo   5. WealthEngine_API         (auto, depende: Bot)
echo   6. Hermes Cron              (hermes-agent, 03:00 UTC)
echo.
echo Logs em: %PROJECT_ROOT%\bot\run\
echo Para parar tudo: scripts\stop_all.bat
echo Para reiniciar: scripts\restart_all.bat
echo ============================================================
pause