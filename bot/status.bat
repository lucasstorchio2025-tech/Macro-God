@echo off
title Wealth_Engine_Status
cd /d C:\Users\lucas\Wealth_Engine
set PYTHON_EXE=C:\Users\lucas\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe
if not exist "%PYTHON_EXE%" set PYTHON_EXE=python
if not exist "%PYTHON_EXE%" set PYTHON_EXE=python

echo ============================================
echo        WEALTH ENGINE - STATUS
echo ============================================
echo.

"%PYTHON_EXE%" -c "
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import Counter

BOT_DIR = Path.cwd() / 'bot'   # cwd ja foi setado como raiz do projeto pelo cd /d %~dp0..
STATE = json.loads((BOT_DIR / 'bot_state.json').read_text(encoding='utf-8')) if (BOT_DIR / 'bot_state.json').exists() else {}
INTEL = json.loads((BOT_DIR.parent / 'market_intelligence.json').read_text(encoding='utf-8')) if (BOT_DIR.parent / 'market_intelligence.json').exists() else {}

# ── Bot running? ──
last_run = STATE.get('last_run_utc', '')
if last_run:
    try:
        dt = datetime.fromisoformat(last_run.replace('Z', '+00:00'))
        secs = (datetime.now(timezone.utc) - dt).total_seconds()
        if secs < 600:
            print(f'  🤖 Bot: RODANDO (ultimo ciclo ha {int(secs//60)}min)')
        else:
            print(f'  ⏸️  Bot: PARADO (ultimo ciclo ha {int(secs//3600)}h)')
    except:
        print(f'  🤖 Bot: {last_run[:19]}')
else:
    print('  ❌ Bot: NUNCA RODOU')

# ── Account ──
try:
    import os
    from dotenv import load_dotenv
    load_dotenv(str(Path.home() / '.hermes' / '.env'), override=False)
    import MetaTrader5 as mt5
    mt5.initialize(login=int(os.environ['EXNESS_LOGIN']), password=os.environ['EXNESS_PASSWORD'], server=os.environ['EXNESS_SERVER'], timeout=15000)
    acc = mt5.account_info()
    if acc:
        print(f'  💰 Saldo: ${acc.balance:.2f}  Equity: ${acc.equity:.2f}  Lucro: ${acc.profit:+.2f}')
    positions = mt5.positions_get(magic=999888777) or []
    print(f'  📦 Posicoes abertas: {len(positions)}/3')
    for p in positions:
        d = 'BUY' if p.type==0 else 'SELL'
        print(f'      ticket={p.ticket} {p.symbol} {d} {p.volume} lot @ {p.price_open:.5f} | profit ${p.profit:+.2f}')
    mt5.shutdown()
except Exception as e:
    print(f'  ⚠️  MT5: {e}')
    print(f'  💰 Saldo: ${STATE.get(\"starting_balance_today\", 0):.2f} (do state cache)')

# ── Regime + VIX + DXY ──
def _ago(dt):
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 60: return f'ha {int(secs)}s'
    elif secs < 3600: return f'ha {int(secs//60)}min'
    elif secs < 86400: return f'ha {int(secs//3600)}h'
    else: return f'ha {int(secs//86400)}d'

rs = INTEL.get('risk_sentiment', {})
vix = rs.get('vix', '?')
vix_chg = rs.get('vix_pct_change', '')
dxy = rs.get('dollar_index', '?')
dxy_chg = rs.get('dollar_index_pct_change', '')
print(f'  🌡️  VIX: {vix} ({vix_chg:+.1f}%)' if isinstance(vix_chg, (int,float)) else f'  🌡️  VIX: {vix}')
print(f'  💵 DXY: {dxy} ({dxy_chg:+.2f}%)' if isinstance(dxy_chg, (int,float)) else f'  💵 DXY: {dxy}')

# ── Drawdown ──
bal = STATE.get('starting_balance_today', 0)
if bal > 0:
    dd_dia = ((bal - bal) / bal * 100)  # precisa do saldo ATUAL do mt5, nao temos aqui
    print(f'  📉 DD Diario: N/A (veja o dashboard)  |  Caps: 8%% / 15%%')

# ── Cooldown ──
exits = STATE.get('last_exit_ts', {})
for sym, ts in exits.items():
    try:
        dt_exit = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        remaining = (dt_exit.replace(tzinfo=timezone.utc) + __import__('datetime').timedelta(hours=48) - datetime.now(timezone.utc)).total_seconds()
        if remaining > 0:
            print(f'  ⏳ Cooldown {sym}: {int(remaining//3600)}h{int((remaining%3600)//60)}m restantes')
    except:
        pass

# ── DECISION LOG SUMMARY ──
print()
print('  --- ULTIMAS DECISOES ---')
log_path = BOT_DIR / 'decision_log.jsonl'
if log_path.exists():
    try:
        lines = log_path.read_text(encoding='utf-8').splitlines()
        lines = [json.loads(l) for l in lines if l.strip()]
        last_n = lines[-50:]
        
        opened = sum(1 for d in last_n if d.get('payload',{}).get('result') == 'opened')
        blocked = sum(1 for d in last_n if d.get('payload',{}).get('result') == 'blocked_filter')
        nosig = sum(1 for d in last_n if d.get('payload',{}).get('result') == 'no_signal')
        
        print(f'  ✅ Abertos: {opened}  🚫 Bloqueios: {blocked}  📉 Sem sinal: {nosig}')
        
        # Conta bloqueios por filtro
        filtros = Counter()
        for d in last_n:
            f = d.get('payload',{}).get('filter_blocked', '')
            if f:
                # simplifica
                if f.startswith('rr_'): f = 'RR < minimo'
                elif f.startswith('session_'): f = 'Sessao bloqueada'
                elif f == 'exposure_check': f = 'Exposicao total'
                elif f == 'dd_check': f = 'Drawdown diario/semanal'
                elif f == 'macro_blockers': f = 'Evento economico'
                elif f == 'already_open': f = 'Ja aberto (anti-empilhamento)'
                elif f == 'cooldown': f = 'Cooldown do simbolo'
                elif f == 'risk_cap': f = 'Risco por trade > cap'
                elif f == 'crisis': f = 'Regime crisis'
                elif f == 'max_positions': f = 'Max posicoes abertas'
                elif f == 'mt5_connect': f = 'Conexao MT5'
                elif f == 'account_info': f = 'Info da conta'
                else: f = f[:30]
                filtros[f] += 1
        
        if filtros:
            print(f'  Top bloqueios:')
            for f, c in filtros.most_common(5):
                print(f'    {f}: {c}x')
        
        # Ultimo motivo
        for d in reversed(last_n):
            if d.get('payload',{}).get('result') == 'blocked_filter':
                motivo = d.get('payload',{}).get('reasoning',{}).get('reason', '')
                if motivo:
                    print(f'  Ultimo bloqueio: {motivo[:100]}')
                break
        
        # Ultima decisao (timestamp)
        if lines:
            last_ts = lines[-1].get('ts_utc', '')
            if last_ts:
                try:
                    dt = datetime.fromisoformat(last_ts.replace('Z', '+00:00'))                print(f'  Ultima decisao: {_ago(dt)}')
            except:
                print(f'  Ultima decisao: {last_ts[:19]}')
    except Exception as e:
        print(f'  Erro lendo decision_log: {e}')
else:
    print('  (decision_log.jsonl vazio)')
"

echo.
echo ============================================
echo  Dica: de duplo clique em bot\abrir_dashboard.bat
echo  para abrir o painel grafico completo!
echo ============================================
pause
