@echo off
rem Atualiza intelligence + tenta news. Se ollama falhar, segue com intelligence limpo.
title Wealth_Engine_News
cd /d %~dp0..
echo [%date% %time%] Atualizando intelligence hub...
python run_intel_now.py >nul 2>&1
echo [%date% %time%] Tentando news aggregator (pode falhar se ollama cair)...
python scripts\files\news_aggregator.py 2>&1 | findstr /V "Fail\|Error"
echo [%date% %time%] Concluido.
