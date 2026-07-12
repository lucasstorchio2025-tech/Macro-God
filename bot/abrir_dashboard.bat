@echo off
title Wealth_Engine_Dashboard
cd /d C:\Users\lucas\Wealth_Engine

set PYTHON_EXE=C:\Users\lucas\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe
if not exist "%PYTHON_EXE%" set PYTHON_EXE=python

echo ============================================
echo     Painel Mestre Wealth Engine
echo ============================================
echo.

REM Verifica se ja tem streamlit rodando na porta 8501
netstat -ano | findstr ":8501" >nul 2>&1
if %errorlevel%==0 (
    echo  ✅ Dashboard ja esta rodando!
) else (
    echo  Iniciando servidor Streamlit em segundo plano...
    echo  (acessivel via rede local: http://SEU_IP:8501)
    start /min "Wealth_Dashboard" "%PYTHON_EXE%" -m streamlit run wealth_dashboard.py --server.port 8501 --server.address=0.0.0.0
    echo  Aguardando servidor iniciar...
    timeout /t 5 /nobreak >nul
)

echo  Abrindo navegador...
start "" http://localhost:8501

echo.
echo ============================================
echo  ✅ Painel Mestre aberto!
echo.
echo  📍 Neste PC:    http://localhost:8501
echo  📍 Rede local:  http://SEU_IP_AQUI:8501
echo     (descubra seu IP com: ipconfig)
echo.
echo  Para fechar o servidor depois:
echo    feche a janela "Wealth_Dashboard"
echo    (rodando minimizada no tray)
echo ============================================
