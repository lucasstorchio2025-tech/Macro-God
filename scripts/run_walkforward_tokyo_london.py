"""
run_walkforward_tokyo_london.py — Walk-Forward com SESSION_FILTER_ALLOW=["Tokyo","London"]

Compara com os resultados de Só Tokyo (OOS médio 0.41, 3/8 > 0.6)
para ver se a adição de London melhora a estabilidade OOS.

Uso: PYTHONIOENCODING=utf-8 python run_walkforward_tokyo_london.py
"""
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

WF_TRAIN_BARS = 1440
WF_TEST_BARS = 720
WF_STEP_BARS = 720

print("=" * 70)
print("  WALK-FORWARD: Validacao 'Tokyo + London'")
print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
print("=" * 70)

# 1. Load data
print("\n[1/4] Carregando dados...")
prices = load_all_prices(timeframe=C.TIMEFRAME, bars=C.BARS_LOOKBACK, align=True)
common_h4 = next(iter(prices.values())).index
vix = load_vix(period="max")
print(f"   {len(prices)} simbolos, {len(common_h4)} barras H4")

dxy_pct, vix_h4 = None, None
try:
    dxy_raw = load_dxy(period="10y")
    dxy_pct = dxy_pct_change_h4(dxy_raw, common_h4, lookback=C.DXY_LIQUIDITY_STRESS_LOOKBACK_BARS)
    vix_h4 = vix.pct_change(5).reindex(common_h4).ffill() * 100.0
except Exception as e:
    print(f"   DXY/VIX H4: {e}")

macro_events = None
try:
    macro_events = get_events_for_backtest(C.START_COMMON, C.END_DEFAULT)
except Exception:
    pass

print("\n[2/4] Montando regime...")
regime = RuleBasedRegime(vix=vix, prices_for_corr=prices)

print("\n[3/4] Calculando D1 momentum...")
d1_momentum = {}
if C.D1_FILTER_ENABLED:
    for sym, df in prices.items():
        daily_close = df["close"].resample("D").last().dropna()
        mom = (daily_close.shift(1) / daily_close.shift(C.D1_MOMENTUM_LOOKBACK_BARS + 1)) - 1.0
        d1_momentum[sym] = mom.reindex(common_h4, method="ffill")

print("\n[4/4] Janelas walk-forward...")
windows = _build_windows(common_h4, train_bars=WF_TRAIN_BARS, test_bars=WF_TEST_BARS, step_bars=WF_STEP_BARS)
print(f"   Janelas: {len(windows)}")

def run_window(prices, regime, d1_momentum, dxy_pct, vix_h4, macro_events,
               start, end, sessions, label):
    """Roda backtest com sessions específicas."""
    orig = deepcopy(C.SESSION_FILTER_ALLOW)
    try:
        C.SESSION_FILTER_ALLOW = sessions
        res = run_backtest(
            prices=prices, strategy=TSMomentumStrategy(),
            regime_provider=regime,
            start=start, end=end,
            account_start=C.ACCOUNT_START_USD,
            max_positions=C.MAX_OPEN_POSITIONS,
            risk_per_trade_pct=C.RISK_PER_TRADE_PCT,
            risk_pct_by_regime=C.RISK_PCT_BY_REGIME,
            d1_momentum=d1_momentum if C.D1_FILTER_ENABLED else None,
            use_costs=True, label=label,
            dxy_pct=dxy_pct, vix_pct=vix_h4,
            macro_events=macro_events,
        )
        return basic_summary(res)
    except Exception as e:
        return {"label": label, "error": str(e), "sharpe": 0.0,
                "total_return_pct": 0.0, "max_dd_pct": 0.0,
                "win_rate": 0.0, "n": 0, "final_equity": C.ACCOUNT_START_USD}
    finally:
        C.SESSION_FILTER_ALLOW = orig

print("\n" + "=" * 70)
print("  EXECUTANDO WALK-FORWARD: Tokyo+London")
print("=" * 70)

is_rows = []
oos_rows = []
total = len(windows)

for i, w in enumerate(windows):
    print(f"\n--- Janela {i+1}/{total} ---")
    print(f"  IS:  {w['train_start']} -> {w['train_end']}")
    print(f"  OOS: {w['test_start']} -> {w['test_end']}")

    # IS
    is_m = run_window(prices, regime, d1_momentum, dxy_pct, vix_h4, macro_events,
                      w["train_start"], w["train_end"],
                      ["Tokyo", "London"], f"TL_IS_w{i+1}")
    print(f"  [IS] Sharpe={is_m.get('sharpe',0):.2f} Ret={is_m.get('total_return_pct',0):+.1f}% DD={is_m.get('max_dd_pct',0):.1f}%")
    is_rows.append(is_m)

    # OOS
    oos_m = run_window(prices, regime, d1_momentum, dxy_pct, vix_h4, macro_events,
                       w["test_start"], w["test_end"],
                       ["Tokyo", "London"], f"TL_OOS_w{i+1}")
    print(f"  [OOS] Sharpe={oos_m.get('sharpe',0):.2f} Ret={oos_m.get('total_return_pct',0):+.1f}% DD={oos_m.get('max_dd_pct',0):.1f}%")
    oos_rows.append(oos_m)

# Compile report
is_sharpes = [r.get("sharpe", 0) for r in is_rows]
oos_sharpes = [r.get("sharpe", 0) for r in oos_rows]
decays = [o - i for i, o in zip(is_sharpes, oos_sharpes)]

oos_medio = np.mean(oos_sharpes)
is_medio = np.mean(is_sharpes)
decay_medio = np.mean(decays)
oos_acima_06 = sum(1 for s in oos_sharpes if s > 0.6)
oos_acima_08 = sum(1 for s in oos_sharpes if s > 0.8)
oos_acima_10 = sum(1 for s in oos_sharpes if s > 1.0)

# Generate markdown
lines = []
lines.append("# WALK-FORWARD: Validacao 'Tokyo + London'")
lines.append(f"**Gerado em:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
lines.append(f"**Periodo total:** {common_h4[0].date()} -> {common_h4[-1].date()}")
lines.append(f"**Janelas:** {len(windows)} (IS: {WF_TRAIN_BARS}b ~6m, OOS: {WF_TEST_BARS}b ~3m)")
lines.append("")

lines.append("## Resultados por Janela")
lines.append("| Janela | IS Periodo | OOS Periodo | IS Sharpe | IS Ret% | IS DD% | OOS Sharpe | OOS Ret% | OOS DD% | OOS Trades | Decaimento |")
lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
for i in range(len(windows)):
    decay = decays[i]
    decay_label = f"{decay:+.2f} {'✅' if decay > -0.3 else '⚠️' if decay > -0.5 else '❌'}"
    lines.append(
        f"| {i+1} | {windows[i]['train_start']}->{windows[i]['train_end']} | {windows[i]['test_start']}->{windows[i]['test_end']} |"
        f" {is_rows[i].get('sharpe',0):.2f} | {is_rows[i].get('total_return_pct',0):+.1f}% | {is_rows[i].get('max_dd_pct',0):.1f}% |"
        f" {oos_rows[i].get('sharpe',0):.2f} | {oos_rows[i].get('total_return_pct',0):+.1f}% | {oos_rows[i].get('max_dd_pct',0):.1f}% |"
        f" {oos_rows[i].get('n',0)} | {decay_label} |"
    )
lines.append("")

lines.append("## Estatisticas Agregadas")
lines.append("| Metrica | Tokyo+London | So Tokyo (ref) | Diferenca |")
lines.append("|---------|-------------|----------------|-----------|")
lines.append(f"| **Sharpe IS medio** | {is_medio:.2f} | 0.84 | {is_medio - 0.84:+.2f} |")
lines.append(f"| **Sharpe OOS medio** | {oos_medio:.2f} | 0.41 | {oos_medio - 0.41:+.2f} |")
lines.append(f"| **Decaimento medio** | {decay_medio:+.2f} | -0.43 | {decay_medio + 0.43:+.2f} |")
lines.append(f"| **OOS Sharpe > 1.0** | {oos_acima_10}/{len(windows)} | 3/8 | |")
lines.append(f"| **OOS Sharpe > 0.8** | {oos_acima_08}/{len(windows)} | 3/8 | |")
lines.append(f"| **OOS Sharpe > 0.6** | {oos_acima_06}/{len(windows)} | 3/8 | |")
lines.append(f"| **Menor Sharpe OOS** | {min(oos_sharpes):.2f} | -1.57 | |")
lines.append(f"| **Maior Sharpe OOS** | {max(oos_sharpes):.2f} | 1.90 | |")
lines.append("")

# Veredito
lines.append("## Veredito")
if oos_medio >= 0.8 and decay_medio > -0.3:
    v = "✅ **ROBUSTO.** O Sharpe OOS medio e alto e o decaimento e pequeno."
elif oos_medio >= 0.6 and decay_medio > -0.5:
    v = "⚠️ **ACEITAVEL.** Sharpe OOS medio razoavel, mas ha variacao entre janelas."
else:
    v = "❌ **OVERFIT.** Sharpe OOS medio baixo com decaimento alto."
lines.append(f"### Veredito Tokyo+London")
lines.append(v)

# Comparacao com So Tokyo
melhorou = oos_medio - 0.41
lines.append(f"### Comparacao com 'So Tokyo'")
lines.append(f"- So Tokyo: OOS medio **0.41** (OVERFIT)")
lines.append(f"- Tokyo+London: OOS medio **{oos_medio:.2f}** ({melhorou:+.2f} vs Tokyo)")
if melhorou > 0.2:
    lines.append(f"- ✅ **Melhora significativa.** Adicionar London parece reduzir o overfit.")
elif melhorou > 0:
    lines.append(f"- 🟡 **Melhora marginal.** Ainda insuficiente pra considerar robusto.")
else:
    lines.append(f"- ❌ **Piorou.** So Tokyo ainda e a melhor opcao.")
lines.append("")

lines.append("---")
lines.append("_Gerado por run_walkforward_tokyo_london.py_")

report_path = Path("reports") / "WALK_FORWARD_TOKYO_LONDON.md"
report_path.write_text("\n".join(lines), encoding="utf-8")
print(f"\n[OK] Relatorio salvo: {report_path}")

print(f"\n{'='*70}")
print(f"  RESUMO:")
print(f"    IS medio:        {is_medio:.2f}")
print(f"    OOS medio:       {oos_medio:.2f}  (Tokyo puro: 0.41)")
print(f"    Decaimento:      {decay_medio:+.2f}  (Tokyo puro: -0.43)")
print(f"    OOS > 0.6:       {oos_acima_06}/{len(windows)}  (Tokyo puro: 3/8)")
print(f"    OOS > 0.8:       {oos_acima_08}/{len(windows)}  (Tokyo puro: 3/8)")
print(f"    Melhoria vs So Tokyo: {melhorou:+.2f} Sharpe")
if melhorou > 0.2:
    print(f"  ✅ Veredito: Melhora significativa!")
elif melhorou > 0:
    print(f"  🟡 Veredito: Melhora marginal.")
else:
    print(f"  ❌ Veredito: Piorou.")
print(f"{'='*70}")
