"""Testa COOLDOWN_BARS=4 (16h) como compromisso entre 2 (8h) e 12 (48h)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import config as C
from engine.data import load_all_prices, load_vix, load_dxy, dxy_pct_change_h4
from engine.regime import RuleBasedRegime
from engine.signals import TSMomentumStrategy
from engine.backtest import run_backtest
from engine.analytics import basic_summary
from engine.macro_events import get_events_for_backtest

orig = C.COOLDOWN_BARS
C.COOLDOWN_BARS = 4
print(f"COOLDOWN_BARS = {C.COOLDOWN_BARS} (={C.COOLDOWN_BARS * 4}h)")

print("\nCarregando dados...")
prices = load_all_prices(timeframe=C.TIMEFRAME, bars=C.BARS_LOOKBACK, align=True)
common_h4 = next(iter(prices.values())).index
vix = load_vix(period="max")
regime = RuleBasedRegime(vix=vix, prices_for_corr=prices)

dxy_pct, vix_h4 = None, None
try:
    dxy_raw = load_dxy(period="10y")
    dxy_pct = dxy_pct_change_h4(dxy_raw, common_h4, lookback=C.DXY_LIQUIDITY_STRESS_LOOKBACK_BARS)
    vix_pct_ser = vix.pct_change(5) * 100.0
    vix_h4 = vix_pct_ser.reindex(common_h4).ffill()
except: pass

macro_events = None
try: macro_events = get_events_for_backtest(C.START_COMMON, C.END_DEFAULT)
except: pass

d1_momentum = {}
if C.D1_FILTER_ENABLED:
    for sym, df in prices.items():
        dc = df["close"].resample("D").last().dropna()
        mom = (dc.shift(1) / dc.shift(C.D1_MOMENTUM_LOOKBACK_BARS + 1)) - 1.0
        d1_momentum[sym] = mom.reindex(common_h4, method="ffill")

try:
    res = run_backtest(
        prices=prices, strategy=TSMomentumStrategy(), regime_provider=regime,
        start=C.START_COMMON, end=C.END_DEFAULT,
        account_start=C.ACCOUNT_START_USD, max_positions=C.MAX_OPEN_POSITIONS,
        risk_per_trade_pct=C.RISK_PER_TRADE_PCT, risk_pct_by_regime=C.RISK_PCT_BY_REGIME,
        d1_momentum=d1_momentum if C.D1_FILTER_ENABLED else None,
        use_costs=True, label="cooldown4",
        dxy_pct=dxy_pct, vix_pct=vix_h4, macro_events=macro_events,
    )
    s = basic_summary(res)
    print(f"\nCOOLDOWN=4 (16h): Sharpe {s['sharpe']:.2f} | Ret {s['total_return_pct']:+.1f}% | "
          f"DD {s['max_dd_pct']:.1f}% | Trades {s['n']} | Final ${s['final_equity']:.2f}")
    
    print(f"\nTabela comparativa:")
    print(f"{'Config':<20} {'Sharpe':>8} {'Ret%':>10} {'DD%':>8} {'Trades':>8} {'Final$':>8}")
    print("-" * 64)
    print(f"{'COOLDOWN=12 (48h)':<20} {'1.19':>8} {'+114.1%':>10} {'-18.9%':>8} {'233':>8} {'$1,070':>8}")
    print(f"{'COOLDOWN=4 (16h)':<20} {s['sharpe']:>8.2f} {s['total_return_pct']:>+9.1f}% {s['max_dd_pct']:>7.1f}% {s['n']:>8} ${s['final_equity']:>5.0f}")
    print(f"{'COOLDOWN=2 (8h)':<20} {'0.24':>8} {'+13.7%':>10} {'-36.1%':>8} {'387':>8} {'$568':>8}")

finally:
    C.COOLDOWN_BARS = orig
