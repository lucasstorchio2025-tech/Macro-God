"""Testa WFO com filtro VIX: levels 25 e 20, compara com baseline.

Uso: python run_wfo_vix_test.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from copy import deepcopy
from datetime import datetime

import numpy as np
import pandas as pd

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
print("  WFO TEST: VIX_MAX_LEVEL Filter Comparison")
print("=" * 70)

# Carregar dados (uma vez)
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

regime = RuleBasedRegime(vix=vix, prices_for_corr=prices)

d1_momentum = {}
if C.D1_FILTER_ENABLED:
    for sym, df in prices.items():
        daily_close = df["close"].resample("D").last().dropna()
        mom = (daily_close.shift(1) / daily_close.shift(C.D1_MOMENTUM_LOOKBACK_BARS + 1)) - 1.0
        d1_h4 = mom.reindex(common_h4, method="ffill")
        d1_momentum[sym] = d1_h4

# Janelas
print("\n[2/4] Montando janelas...")
windows = _build_windows(common_h4, train_bars=WF_TRAIN_BARS, test_bars=WF_TEST_BARS, step_bars=WF_STEP_BARS)
print(f"  {len(windows)} janelas")

def run_window_oos(w, label):
    """Roda backtest OOS com SESSION_FILTER_ALLOW=[Tokyo]."""
    orig = {"SESSION_FILTER_ALLOW": deepcopy(C.SESSION_FILTER_ALLOW)}
    C.SESSION_FILTER_ALLOW = ["Tokyo"]
    try:
        res = run_backtest(
            prices=prices, strategy=TSMomentumStrategy(), regime_provider=regime,
            start=w["test_start"], end=w["test_end"],
            account_start=C.ACCOUNT_START_USD,
            max_positions=C.MAX_OPEN_POSITIONS,
            risk_per_trade_pct=C.RISK_PER_TRADE_PCT,
            risk_pct_by_regime=C.RISK_PCT_BY_REGIME,
            d1_momentum=d1_momentum if C.D1_FILTER_ENABLED else None,
            use_costs=True, label=label,
            dxy_pct=dxy_pct, vix_pct=vix_h4, macro_events=macro_events,
        )
        return basic_summary(res)
    except Exception as e:
        return {"sharpe": 0, "total_return_pct": 0, "max_dd_pct": 0, "n": 0,
                "final_equity": C.ACCOUNT_START_USD, "cagr_pct": 0, "label": label}
    finally:
        for k, v in orig.items():
            setattr(C, k, v)

def run_full_wfo(vix_level, label):
    """Roda WFO completo com VIX_MAX_LEVEL especificado."""
    orig_vix = C.VIX_MAX_LEVEL
    C.VIX_MAX_LEVEL = vix_level
    print(f"\n  Rodando WFO c/ VIX_MAX_LEVEL={vix_level}... ", end="", flush=True)

    oos_rows = []
    for i, w in enumerate(windows):
        s = run_window_oos(w, f"{label}_w{i+1}")
        oos_rows.append(s)

    sharpes = [r.get("sharpe", 0) for r in oos_rows]
    oos_medio = np.mean(sharpes)
    oos_acima_06 = sum(1 for s in sharpes if s > 0.6)
    oos_acima_08 = sum(1 for s in sharpes if s > 0.8)
    decay_medio = np.mean([r.get("sharpe", 0) - 0 for r in oos_rows])  # placeholder

    C.VIX_MAX_LEVEL = orig_vix

    return {
        "label": label,
        "vix_level": vix_level,
        "oos_medio": oos_medio,
        "oos_acima_06": oos_acima_06,
        "oos_acima_08": oos_acima_08,
        "todos_sharpes": sharpes,
        "por_janela": oos_rows,
    }

# Rodar 3 cenarios
cenarios = [
    ("Baseline (sem filtro)", 0),
    ("VIX_MAX_LEVEL=25", 25),
    ("VIX_MAX_LEVEL=20", 20),
]

resultados = []
for label, vix_level in cenarios:
    print(f"\n--- {label} ---")
    r = run_full_wfo(vix_level, label)
    resultados.append(r)
    print(f"  OOS medio: {r['oos_medio']:.2f} | >0.6: {r['oos_acima_06']}/8 | >0.8: {r['oos_acima_08']}/8")

# Tabela comparativa
print("\n" + "=" * 70)
print("  TABELA COMPARATIVA")
print("=" * 70)
print(f"{'Cenario':<25} {'OOS Medio':>10} {'>0.6':>6} {'>0.8':>6}  Sharpes por janela")
print("-" * 85)
for r in resultados:
    sharpes_str = " ".join(f"{s:.2f}" for s in r["todos_sharpes"])
    print(f"{r['label']:<25} {r['oos_medio']:>10.2f} {r['oos_acima_06']:>3d}/8 {r['oos_acima_08']:>3d}/8  {sharpes_str}")

# Melhor cenario
best = max(resultados, key=lambda r: r["oos_medio"])
print(f"\n🏆 Melhor: {best['label']} (OOS medio {best['oos_medio']:.2f})")

# Conclusao
print(f"\n{'='*70}")
print("  CONCLUSAO")
print(f"{'='*70}")
baseline = resultados[0]
for r in resultados[1:]:
    diff = r["oos_medio"] - baseline["oos_medio"]
    melhorou = diff > 0.05
    status = "✅ MELHOROU" if melhorou else "❌ PIOROU (ou empatou)"
    print(f"  {r['label']}: OOS {r['oos_medio']:.2f} vs baseline {baseline['oos_medio']:.2f} ({diff:+.2f}) — {status}")

# Salva relatorio
lines = []
lines.append("# WFO TEST: VIX_MAX_LEVEL Filter Comparison\n")
lines.append(f"**Gerado em:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC\n")
lines.append(f"**Janelas:** {len(windows)} | **Periodo:** {common_h4[0].date()} -> {common_h4[-1].date()}\n")

lines.append("## Resultados\n")
lines.append("| Cenario | VIX_MAX | OOS Medio | >0.6 | >0.8 | Janela Sharpes |")
lines.append("|---|---|---|---|---|---|")
for r in resultados:
    sharpes_str = ", ".join(f"{s:.2f}" for s in r["todos_sharpes"])
    lines.append(f"| {r['label']} | {r['vix_level']} | {r['oos_medio']:.2f} | {r['oos_acima_06']}/8 | {r['oos_acima_08']}/8 | {sharpes_str} |")
lines.append("")

# Conclusao
baseline = resultados[0]
lines.append("## Conclusao\n")
for r in resultados[1:]:
    diff = r["oos_medio"] - baseline["oos_medio"]
    if diff > 0.05:
        v = "✅ Melhorou"
    elif diff > -0.05:
        v = "⚖️  Empate tecnico"
    else:
        v = "❌ Piorou"
    lines.append(f"- **{r['label']}**: {v} (OOS {r['oos_medio']:.2f} vs {baseline['oos_medio']:.2f}, delta {diff:+.2f})")
lines.append("")

best = max(resultados, key=lambda r: r["oos_medio"])
lines.append(f"**Melhor cenario:** {best['label']} (OOS medio {best['oos_medio']:.2f})")
if best["oos_medio"] >= 0.6:
    lines.append("✅ Filtro VIX pode ser uma melhoria real.")
else:
    lines.append("❌ Nenhum filtro VIX testado resolveu o overfit.")

report_path = C.REPORTS_DIR / "WFO_VIX_FILTER.md"
report_path.write_text("\n".join(lines), encoding="utf-8")
print(f"\n[OK] Relatorio salvo: {report_path}")
