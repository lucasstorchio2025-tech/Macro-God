"""Comparativo: TS-Momentum vs MeanReversion vs Breakout (XAUUSD H4).

Uso: python run_compare_strategies.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from datetime import datetime
import numpy as np

from engine import config as C
from engine.data import load_all_prices, load_vix, load_dxy, dxy_pct_change_h4
from engine.regime import RuleBasedRegime
from engine.signals import TSMomentumStrategy, MeanReversionStrategy, BreakoutStrategy
from engine.backtest import run_backtest
from engine.analytics import basic_summary
from engine.macro_events import get_events_for_backtest

print("=" * 60)
print("COMPARATIVO: TS-Momentum vs MeanReversion vs Breakout")
print("=" * 60)

# ── 1. Carregar dados ──
print("\n[1/4] Carregando dados...")
prices = load_all_prices(timeframe=C.TIMEFRAME, bars=C.BARS_LOOKBACK, align=True)
common_h4 = next(iter(prices.values())).index
vix = load_vix(period="max")
print(f"  {len(common_h4)} barras H4")

dxy_pct, vix_h4 = None, None
try:
    dxy_raw = load_dxy(period="10y")
    dxy_pct = dxy_pct_change_h4(dxy_raw, common_h4, lookback=C.DXY_LIQUIDITY_STRESS_LOOKBACK_BARS)
    vix_pct_ser = vix.pct_change(5) * 100.0
    vix_h4 = vix_pct_ser.reindex(common_h4).ffill()
except Exception:
    pass

macro_events = None
try:
    macro_events = get_events_for_backtest(C.START_COMMON, C.END_DEFAULT)
except Exception:
    pass

# ── 2. Regime ──
print("[2/4] Montando regime...")
regime = RuleBasedRegime(vix=vix, prices_for_corr=prices)

# ── 3. D1 momentum ──
print("[3/4] Calculando D1 momentum...")
d1_momentum = {}
if C.D1_FILTER_ENABLED:
    for sym, df in prices.items():
        daily_close = df["close"].resample("D").last().dropna()
        mom = (daily_close.shift(1) / daily_close.shift(C.D1_MOMENTUM_LOOKBACK_BARS + 1)) - 1.0
        d1_h4 = mom.reindex(common_h4, method="ffill")
        d1_momentum[sym] = d1_h4

# ── 4. Rodar backtests ──
strategies = {
    "TS-Momentum": TSMomentumStrategy(),
    "MeanReversion": MeanReversionStrategy(),
    "Breakout": BreakoutStrategy(),
}

results = {}
print("[4/4] Rodando backtests...")
for name, strat in strategies.items():
    print(f"\n  >>> {name}...", end=" ", flush=True)
    try:
        res = run_backtest(
            prices=prices,
            strategy=strat,
            regime_provider=regime,
            start=C.START_COMMON,
            end=C.END_DEFAULT,
            account_start=C.ACCOUNT_START_USD,
            max_positions=C.MAX_OPEN_POSITIONS,
            risk_per_trade_pct=C.RISK_PER_TRADE_PCT,
            risk_pct_by_regime=C.RISK_PCT_BY_REGIME,
            d1_momentum=d1_momentum if C.D1_FILTER_ENABLED else None,
            use_costs=True,
            label=name,
            dxy_pct=dxy_pct,
            vix_pct=vix_h4,
            macro_events=macro_events,
        )
        s = basic_summary(res)
        results[name] = s
        print(f"Sharpe {s['sharpe']:.2f} | Ret {s['total_return_pct']:+.1f}% | "
              f"DD {s['max_dd_pct']:.1f}% | Trades {s['n']}")
    except Exception as e:
        import traceback
        print(f"ERRO: {e}")
        traceback.print_exc()
        results[name] = None

# ── 5. Tabela final ──
print("\n" + "=" * 60)
print("TABELA COMPARATIVA")
print("=" * 60)
print(f"{'Estrategia':<18} {'Sharpe':>8} {'Ret%':>10} {'DD%':>8} {'Trades':>8} {'WinRate':>8}")
print("-" * 60)
best_name, best_sharpe = None, -999
for name in ["TS-Momentum", "MeanReversion", "Breakout"]:
    s = results.get(name)
    if s:
        sharpe = s['sharpe']
        print(f"{name:<18} {sharpe:>8.2f} {s['total_return_pct']:>9.1f}% "
              f"{s['max_dd_pct']:>7.1f}% {s['n']:>8} {s['win_rate']:>7.1%}")
        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_name = name
    else:
        print(f"{name:<18} {'ERRO':>8}")

print()
if best_name:
    print(f"🏆 VENCEDOR: {best_name} (Sharpe {best_sharpe:.2f})")
else:
    print("❌ Nenhuma estrategia executou com sucesso")
