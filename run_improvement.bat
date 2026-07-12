@echo off
title Wealth_Engine - Improvement Loop
cd /d "%~dp0"

echo ============================================================
echo   WEALTH ENGINE - CICLO DE MELHORIA CONTINUA
echo   %date% %time%
echo ============================================================
echo.

:: Verifica se o Python esta disponivel
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERRO] Python nao encontrado no PATH
    pause
    exit /b 1
)

:: Menu rapido
if "%1"=="--loop" goto :loop
if "%1"=="--quick" goto :quick
if "%1"=="--tune" goto :tune
if "%1"=="--help" goto :help
if "%1"=="--all" goto :all
goto :default

:default
:: 1 ciclo completo (analise + backtest)
echo.
echo [1/3] Rodando analise pos-trade...
python bot\post_trade_analysis.py
if %errorlevel% neq 0 echo [AVISO] post_trade_analysis falhou
echo.

echo [2/3] Rodando backtest completo...
python engine\full_analysis.py
if %errorlevel% neq 0 echo [AVISO] full_analysis falhou
echo.

echo [3/3] Rodando auto-improve (recomendacoes)...
python auto_improve.py
if %errorlevel% neq 0 echo [AVISO] auto_improve falhou
echo.

echo ============================================================
echo   CICLO CONCLUIDO - veja reports\IMPROVEMENT.md
echo ============================================================
goto :end

:quick
:: So analise + recomendacoes (pula backtest)
echo.
echo [1/2] Rodando analise pos-trade...
python bot\post_trade_analysis.py
echo.

echo [2/2] Rodando auto-improve (modo rapido)...
python auto_improve.py --quick
echo.

echo ============================================================
echo   ANALISE RAPIDA CONCLUIDA
echo ============================================================
goto :end

:tune
:: Tuning de parametros
echo.
echo [1/2] Rodando sweep de parametros...
python auto_tune.py --apply
echo.

echo [2/2] Rodando backtest com novos parametros...
python engine\full_analysis.py
echo.

echo ============================================================
echo   TUNING CONCLUIDO
echo ============================================================
goto :end

:all
:: Ciclo completo + tuning
echo.
echo [1/4] Rodando analise pos-trade...
python bot\post_trade_analysis.py
echo.

echo [2/4] Rodando backtest completo...
python engine\full_analysis.py
echo.

echo [3/4] Rodando sweep de parametros...
python auto_tune.py --apply
echo.

echo [4/4] Rodando auto-improve...
python auto_improve.py
echo.

echo ============================================================
echo   CICLO COMPLETO CONCLUIDO - veja reports\IMPROVEMENT.md
echo ============================================================
goto :end

:loop
:: Modo loop infinito
echo.
echo Modo LOOP: executando a cada 6 horas
echo Pressione Ctrl+C para parar
echo.
:loop_start
echo.
echo === Ciclo em %date% %time% ===
python auto_improve.py --quick
echo.
echo Proximo ciclo em 6 horas...
timeout /t 21600 /nobreak >nul
goto loop_start

:help
echo.
echo Uso: run_improvement [opcao]
echo.
echo Opcoes:
echo   (sem args)   1 ciclo completo (analise + backtest + recomendacoes)
echo   --quick      So analise rapida (pula backtest)
echo   --tune       Tuning de parametros + backtest
echo   --all        Ciclo completo + tuning
echo   --loop       Modo loop (a cada 6h, modo rapido)
echo   --help       Esta tela
echo.
goto :end

:end
echo.
echo Relatorios disponiveis:
echo   - reports\POST_TRADE.md       (analise de trades reais)
echo   - reports\ANALYSIS.md          (backtest completo)
echo   - reports\IMPROVEMENT.md       (recomendacoes do ciclo)
echo   - reports\TUNE_RESULT.json     (resultado do tuning)
echo.
