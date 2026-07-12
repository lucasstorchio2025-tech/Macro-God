"""Testa VIX_MAX_LEVEL=22 no WFO (1 cenario)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from copy import deepcopy
from datetime import datetime
import numpy as np
from engine import config as C
from engine.data import load_all_prices, load_vix, load_dxy, dxy_pct_change_h4
from engine.regime import RuleBasedRegime
from engine.signals import TSMomentumStrategy
from engine.backtest import run_backtest
from engine.analytics import basic_summary
from engine.macro_events import get_events_for_backtest
from engine.walk_forward_validate import _build_windows

WF_TRAIN_BARS, WF_TEST_BARS, WF_STEP_BARS = 1440, 720, 720

prices = load_all_prices(timeframe=C.TIMEFRAME, bars=C.BARS_LOOKBACK, align=True)
common_h4 = next(iter(prices.values())).index
vix = load_vix(period="max")
dxy_pct, vix_h4 = None, None
try:
    dxy_raw = load_dxy(period="10y")
    dxy_pct = dxy_pct_change_h4(dxy_raw, common_h4, lookback=C.DXY_LIQUIDITY_STRESS_LOOKBACK_BARS)
    vix_pct_ser = vix.pct_change(5) * 100.0; vix_h4 = vix_pct_ser.reindex(common_h4).ffill()
except: pass
macro_events = None
try: macro_events = get_events_for_backtest(C.START_COMMON, C.END_DEFAULT)
except: pass

regime = RuleBasedRegime(vix=vix, prices_for_corr=prices)
d1_momentum = {}
if C.D1_FILTER_ENABLED:
    for sym, df in prices.items():
        dc = df["close"].resample("D").last().dropna()
        mom = (dc.shift(1) / dc.shift(C.D1_MOMENTUM_LOOKBACK_BARS + 1)) - 1.0
        d1_momentum[sym] = mom.reindex(common_h4, method="ffill")

windows = _build_windows(common_h4, train_bars=WF_TRAIN_BARS, test_bars=WF_TEST_BARS, step_bars=WF_STEP_BARS)

def run_oos(w, label):
    orig = {"SESSION_FILTER_ALLOW": deepcopy(C.SESSION_FILTER_ALLOW)}
    C.SESSION_FILTER_ALLOW = ["Tokyo"]
    try:
        res = run_backtest(prices=prices, strategy=TSMomentumStrategy(), regime_provider=regime,
            start=w["test_start"], end=w["test_end"], account_start=C.ACCOUNT_START_USD,
            max_positions=C.MAX_OPEN_POSITIONS, risk_per_trade_pct=C.RISK_PER_TRADE_PCT,
            risk_pct_by_regime=C.RISK_PCT_BY_REGIME,
            d1_momentum=d1_momentum if C.D1_FILTER_ENABLED else None,
            use_costs=True, label=label, dxy_pct=dxy_pct, vix_pct=vix_h4, macro_events=macro_events)
        return basic_summary(res)
    finally:
        for k, v in orig.items(): setattr(C, k, v)

orig_vix = C.VIX_MAX_LEVEL
C.VIX_MAX_LEVEL = 22

print("Rodando WFO c/ VIX_MAX_LEVEL=22...")
sharpes = []
for i, w in enumerate(windows):
    s = run_oos(w, f"vix22_w{i+1}")
    sharpes.append(s["sharpe"])
    print(f"  Janela {i+1}: OOS Sharpe {s['sharpe']:.2f}")

C.VIX_MAX_LEVEL = orig_vix

oos_medio = np.mean(sharpes)
oos_06 = sum(1 for s in sharpes if s > 0.6)
print(f"\nVIX_MAX_LEVEL=22: OOS medio {oos_medio:.2f}, >0.6: {oos_06}/8")
print(f"Sharpes: {' '.join(f'{s:.2f}' for s in sharpes)}")
print(f"\nComparacao:")
print(f"  VIX=20: OOS 0.79, >0.6: 5/8")
print(f"  VIX=22: OOS {oos_medio:.2f}, >0.6: {oos_06}/8")
print(f"  VIX=22 {'MELHOR' if oos_medio > 0.79 else 'PIOR (ou igual)'} que VIX=20")
