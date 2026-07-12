@echo off
title Wealth_Engine_Diagnostico
cd /d C:\Users\lucas\Wealth_Engine
echo ============================================
echo   WEALTH ENGINE - DIAGNOSTICO RAPIDO
echo   %date% %time%
echo ============================================
echo.

echo [1/5] Verificando processos python com executor.py...
wmic process where "name='python.exe' and commandline like '%%executor.py%%'" get processid,commandline /format:list 2>nul | findstr /r "[0-9]"
if %errorlevel%==0 (echo  [OK] Executor encontrado!) else (echo  [FALHA] Nenhum processo executor.py rodando)
echo.

echo [2/5] Testando streamlit...
python -c "import streamlit; print('  streamlit versao:', streamlit.__version__)" 2>&1
if %errorlevel% NEQ 0 (echo  [FALHA] streamlit nao disponivel! & echo  Execute: pip install streamlit)
echo.

echo [3/5] Testando se wealth_dashboard.py importa sem erros...
python -c "import sys; sys.path.insert(0,'.'); exec(open('wealth_dashboard.py').read().split('if __name__')[0])" 2>&1 | findstr /V "^\s*$"
if %errorlevel%==0 (echo  [OK] Dashboard importa sem erros) else (echo  [FALHA] Erro ao importar dashboard)
echo.

echo [4/5] Verificando porta 8501...
netstat -ano | findstr ":8501" >nul 2>&1
if %errorlevel%==0 (echo  [OK] Porta 8501 ocupada - dashboard rodando) else (echo  [INFO] Porta 8501 livre - dashboard nao esta rodando)
echo.

echo [5/5] Verificando arquivos essenciais...
for %%f in (
    bot\executor.py
    bot\run_executor.bat
    bot\watchdog_supervisor.bat
    bot\start_all.bat
    wealth_dashboard.py
    engine\config.py
) do (
    if exist %%f (echo  [OK] %%f) else (echo  [FALTA] %%f)
)
echo.

echo ============================================
echo   DIAGNOSTICO CONCLUIDO
echo ============================================
pause
