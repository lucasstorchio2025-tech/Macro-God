"""Analisa as 8 janelas WFO: regime, vol, VIX vs Sharpe OOS.

Cruzamento: o que as 3 janelas com OOS Sharpe > 0.6 têm em comum
que as outras 5 não têm?
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd
from datetime import datetime

from engine import config as C
from engine.data import load_all_prices, load_vix, load_dxy, dxy_pct_change_h4
from engine.regime import RuleBasedRegime
from engine.signals import TSMomentumStrategy
from engine.backtest import run_backtest
from engine.analytics import basic_summary
from engine.macro_events import get_events_for_backtest
from engine.walk_forward_validate import _build_windows

# ─── Config ───
WF_TRAIN_BARS = 1440
WF_TEST_BARS = 720
WF_STEP_BARS = 720

print("=" * 70)
print("  ANALISE WFO: Regime/Vol por Janela vs Sharpe OOS")
print("=" * 70)

# ─── 1. Dados ───
print("\n[1/4] Carregando dados...")
prices = load_all_prices(timeframe=C.TIMEFRAME, bars=C.BARS_LOOKBACK, align=True)
common_h4 = next(iter(prices.values())).index
vix = load_vix(period="max")
print(f"   {len(common_h4)} barras H4, {len(vix)} dias VIX")

dxy_pct, vix_h4 = None, None
try:
    dxy_raw = load_dxy(period="10y")
    dxy_pct = dxy_pct_change_h4(dxy_raw, common_h4, lookback=C.DXY_LIQUIDITY_STRESS_LOOKBACK_BARS)
    vix_pct_ser = vix.pct_change(5) * 100.0
    vix_h4 = vix_pct_ser.reindex(common_h4).ffill()
except Exception:
    pass

regime = RuleBasedRegime(vix=vix, prices_for_corr=prices)

# ─── 2. Pré-computa VIX nível no índice H4 ───
vix_h4_level = vix.reindex(common_h4, method="ffill")
# Regime por barra H4 (amostragem pra cada janela)
regime_h4 = {}
for ts in common_h4:
    # Regime com ctx mínimo
    ctx = {"ts": ts, "prices": {}, "balance": 500, "open": [], "digits": {}}
    if dxy_pct is not None and ts in dxy_pct.index:
        ctx["dxy_pct_change"] = float(dxy_pct.loc[ts])
    if vix_h4 is not None and ts in vix_h4.index:
        ctx["vix_pct_change"] = float(vix_h4.loc[ts])
    regime_h4[ts] = regime.at(ts, ctx)

regime_series = pd.Series(regime_h4, name="regime")

# ATR ao longo do tempo (proxies de volatilidade)
from engine.indicators import atr as atr_fn
xau = prices.get("XAUUSDm")
atr_series = atr_fn(xau) if xau is not None else pd.Series(dtype=float)

print(f"   Regime computado para {len(regime_series)} barras")
print(f"   ATR computado para {len(atr_series)} barras")

# ─── 3. Janelas WFO ───
print("\n[2/4] Montando janelas WFO...")
windows = _build_windows(common_h4, train_bars=WF_TRAIN_BARS, test_bars=WF_TEST_BARS, step_bars=WF_STEP_BARS)
print(f"   {len(windows)} janelas")

# ─── 4. Rodar backtest OOS + coletar stats por janela ───
print("\n[3/4] Rodando backtest OOS + coletando stats...")

# D1 momentum
d1_momentum = {}
if C.D1_FILTER_ENABLED:
    for sym, df in prices.items():
        daily_close = df["close"].resample("D").last().dropna()
        mom = (daily_close.shift(1) / daily_close.shift(C.D1_MOMENTUM_LOOKBACK_BARS + 1)) - 1.0
        d1_h4 = mom.reindex(common_h4, method="ffill")
        d1_momentum[sym] = d1_h4

macro_events = None
try:
    macro_events = get_events_for_backtest(C.START_COMMON, C.END_DEFAULT)
except Exception:
    pass

window_stats = []
for i, w in enumerate(windows):
    print(f"\n  Janela {i+1}/{len(windows)}: {w['test_start']} -> {w['test_end']}", flush=True)

    # Roda backtest OOS (mesmo que walk_forward_tokyo.py)
    orig = {"SESSION_FILTER_ALLOW": ["Tokyo"]}
    C.SESSION_FILTER_ALLOW = ["Tokyo"]
    try:
        res = run_backtest(
            prices=prices,
            strategy=TSMomentumStrategy(),
            regime_provider=regime,
            start=w["test_start"], end=w["test_end"],
            account_start=C.ACCOUNT_START_USD,
            max_positions=C.MAX_OPEN_POSITIONS,
            risk_per_trade_pct=C.RISK_PER_TRADE_PCT,
            risk_pct_by_regime=C.RISK_PCT_BY_REGIME,
            d1_momentum=d1_momentum if C.D1_FILTER_ENABLED else None,
            use_costs=True,
            label=f"Janela_{i+1}",
            dxy_pct=dxy_pct,
            vix_pct=vix_h4,
            macro_events=macro_events,
        )
        s = basic_summary(res)
        for k, v in orig.items():
            setattr(C, k, v)
    except Exception as e:
        s = {"sharpe": 0, "total_return_pct": 0, "max_dd_pct": 0, "n": 0, "final_equity": 500}
        print(f"    ERRO: {e}")

    # Stats da janela OOS
    ts_start = pd.Timestamp(w["test_start"], tz="UTC")
    ts_end = pd.Timestamp(w["test_end"], tz="UTC")

    mask = (regime_series.index >= ts_start) & (regime_series.index <= ts_end)
    window_regime = regime_series[mask]

    # Distribuição de regime na janela
    regime_counts = window_regime.value_counts()
    total_bars = len(window_regime)
    regime_dist = {r: f"{regime_counts.get(r, 0)/total_bars*100:.0f}%" if total_bars else "0%"
                   for r in ["risk_on", "normal", "risk_off", "crisis"]}

    # VIX médio na janela
    vix_window = vix_h4_level[mask].dropna()
    vix_mean = vix_window.mean() if len(vix_window) else None

    # ATR médio na janela
    atr_window = atr_series[mask].dropna()
    atr_mean = atr_window.mean() if len(atr_window) else None

    # Volatilidade do retorno (desvio padrão dos retornos diários)
    xau_window = xau.loc[ts_start:ts_end] if xau is not None else None
    ret_vol = xau_window["close"].pct_change().std() * np.sqrt(252) if xau_window is not None and len(xau_window) > 20 else None

    stats = {
        "janela": i + 1,
        "periodo": f"{w['test_start']} a {w['test_end']}",
        "oos_sharpe": s["sharpe"],
        "oos_ret": s["total_return_pct"],
        "oos_dd": s["max_dd_pct"],
        "oos_trades": s["n"],
        "risk_on_pct": regime_dist.get("risk_on", "0%"),
        "normal_pct": regime_dist.get("normal", "0%"),
        "risk_off_pct": regime_dist.get("risk_off", "0%"),
        "crisis_pct": regime_dist.get("crisis", "0%"),
        "vix_medio": round(vix_mean, 1) if vix_mean else "N/A",
        "atr_medio": round(atr_mean, 1) if atr_mean else "N/A",
        "vol_anual": f"{ret_vol:.1%}" if ret_vol else "N/A",
    }
    window_stats.append(stats)
    print(f"    OOS Sharpe={s['sharpe']:.2f} | VIX={vix_mean:.1f} | "
          f"Regime: {regime_dist.get('risk_on')} risk_on, {regime_dist.get('normal')} normal, "
          f"{regime_dist.get('risk_off')} risk_off")

# ─── 5. Análise comparativa ───
print("\n\n" + "=" * 70)
print("  RESULTADOS POR JANELA")
print("=" * 70)

# Tabela
print(f"{'Jan':>4} {'Periodo':<28} {'Sharpe':>7} {'Ret%':>7} {'DD%':>6} {'Trd':>4} "
      f"{'risk_on':>8} {'normal':>8} {'risk_off':>8} {'VIX':>6} {'ATR':>6} {'VolAnual':>9}")
print("-" * 110)
for st in window_stats:
    star = " ★" if st["oos_sharpe"] > 0.6 else "  "
    print(f"{st['janela']:>3d}{star} {st['periodo']:<28s} {st['oos_sharpe']:>7.2f} "
          f"{st['oos_ret']:>+6.1f}% {st['oos_dd']:>5.1f}% {st['oos_trades']:>4d} "
          f"{st['risk_on_pct']:>8s} {st['normal_pct']:>8s} {st['risk_off_pct']:>8s} "
          f"{str(st['vix_medio']):>6s} {str(st['atr_medio']):>6s} {str(st['vol_anual']):>9s}")

# Comparação: boas (Sharpe > 0.6) vs ruins
print("\n\n" + "=" * 70)
print("  COMPARACAO: Janelas BOAS (Sharpe OOS > 0.6) vs RUINS")
print("=" * 70)

boas = [w for w in window_stats if w["oos_sharpe"] > 0.6]
ruins = [w for w in window_stats if w["oos_sharpe"] <= 0.6]

print(f"\n  Janelas BOAS ({len(boas)}): {', '.join(str(w['janela']) for w in boas)}")
print(f"  Janelas RUINS ({len(ruins)}): {', '.join(str(w['janela']) for w in ruins)}")

def media_metricas(janelas, campo):
    vals = []
    for w in janelas:
        v = w[campo]
        if isinstance(v, (int, float)):
            vals.append(v)
    return np.mean(vals) if vals else None

print(f"\n  {'Metrica':<20} {'BOAS':>10} {'RUINS':>10} {'Diferenca':>12}")
print(f"  {'-'*52}")
for campo, label in [("vix_medio", "VIX medio"), ("atr_medio", "ATR medio")]:
    b = media_metricas(boas, campo)
    r = media_metricas(ruins, campo)
    d = (b - r) if b is not None and r is not None else None
    if d is not None:
        print(f"  {label:<20} {b:>10.1f} {r:>10.1f} {d:>+11.1f}")

# Regime distribution comparison
for regime in ["risk_on", "normal", "risk_off"]:
    b_pcts = [float(w.get(f"{regime}_pct", "0%").replace("%", "")) for w in boas]
    r_pcts = [float(w.get(f"{regime}_pct", "0%").replace("%", "")) for w in ruins]
    b_mean = np.mean(b_pcts) if b_pcts else 0
    r_mean = np.mean(r_pcts) if r_pcts else 0
    diff = b_mean - r_mean
    print(f"  {f'{regime}%':<20} {b_mean:>9.1f}% {r_mean:>9.1f}% {diff:>+11.1f}pp")

print(f"\n\n  {'='*70}")
print(f"  CONCLUSAO:")
print(f"  {'='*70}")
if boas:
    b_sharpes = [w["oos_sharpe"] for w in boas]
    b_vix = [w["vix_medio"] for w in boas if isinstance(w["vix_medio"], (int, float))]
    r_vix = [w["vix_medio"] for w in ruins if isinstance(w["vix_medio"], (int, float))]
    print(f"  Janelas boas: Sharpe medio {np.mean(b_sharpes):.2f}")
    if b_vix and r_vix:
        print(f"  VIX medio boas: {np.mean(b_vix):.1f} vs ruins: {np.mean(r_vix):.1f}")
        if np.mean(b_vix) < np.mean(r_vix):
            print(f"  → Janelas boas tem VIX MENOR (menos estresse, momentum funciona)")
        else:
            print(f"  → Janelas boas tem VIX MAIOR (estresse favorece reversao)")
else:
    print("  Nenhuma janela boa encontrada.")

# Salva relatório
lines = []
lines.append("# ANALISE WFO: Regime/Vol por Janela vs Sharpe OOS\n")
lines.append(f"**Gerado em:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC\n")
lines.append(f"**Total de janelas:** {len(window_stats)} | **Boas (OOS > 0.6):** {len(boas)} | **Ruins:** {len(ruins)}\n")

lines.append("## Tabela por Janela\n")
lines.append("| Janela | Periodo | OOS Sharpe | OOS Ret% | OOS DD% | Trades | risk_on% | normal% | risk_off% | crisis% | VIX | ATR | VolAnual |")
lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for st in window_stats:
    star = "★" if st["oos_sharpe"] > 0.6 else " "
    lines.append(f"| {st['janela']}{star} | {st['periodo']} | {st['oos_sharpe']:.2f} | {st['oos_ret']:+.1f}% | "
                 f"{st['oos_dd']:.1f}% | {st['oos_trades']} | {st['risk_on_pct']} | {st['normal_pct']} | "
                 f"{st['risk_off_pct']} | {st['crisis_pct']} | {st['vix_medio']} | {st['atr_medio']} | {st['vol_anual']} |")
lines.append("")

lines.append("## Comparacao BOAS vs RUINS\n")
lines.append(f"| Metrica | BOAS (n={len(boas)}) | RUINS (n={len(ruins)}) | Diferenca |")
lines.append("|---|---|---|---|")
for campo, label in [("vix_medio", "VIX medio"), ("atr_medio", "ATR medio")]:
    b = media_metricas(boas, campo)
    r = media_metricas(ruins, campo)
    d = (b - r) if b is not None and r is not None else None
    if d is not None:
        lines.append(f"| {label} | {b:.1f} | {r:.1f} | {d:+.1f} |")
for regime in ["risk_on", "normal", "risk_off"]:
    b_pcts = [float(w.get(f"{regime}_pct", "0%").replace("%", "")) for w in boas]
    r_pcts = [float(w.get(f"{regime}_pct", "0%").replace("%", "")) for w in ruins]
    b_mean = np.mean(b_pcts) if b_pcts else 0
    r_mean = np.mean(r_pcts) if r_pcts else 0
    d = b_mean - r_mean
    lines.append(f"| {regime}% | {b_mean:.1f}% | {r_mean:.1f}% | {d:+.1f}pp |")
lines.append("")

# Conclusao
lines.append("## Conclusao\n")
b_vix = [w["vix_medio"] for w in boas if isinstance(w["vix_medio"], (int, float))]
r_vix = [w["vix_medio"] for w in ruins if isinstance(w["vix_medio"], (int, float))]
if b_vix and r_vix and np.mean(b_vix) < np.mean(r_vix):
    lines.append("**Padrao encontrado:** Janelas com OOS > 0.6 tendem a ter VIX MENOR.\n")
    lines.append("Nestas janelas, o momentum funciona porque nao ha estresse de mercado.\n")
    lines.append("Nas janelas ruins, o VIX mais alto indica estresse — o momentum quebra\n")
    lines.append("porque as reversoes sao abruptas.\n")
    lines.append("**Implicacao:** Um filtro de VIX maximo (ex: VIX < 20) poderia melhorar\n")
    lines.append("o WFO, mas reduziria o numero de trades.")
else:
    lines.append("Nao foi identificado um padrao claro entre as janelas.\n")
    lines.append("O overfit parece ser estrutural (parametrizacao excessiva), nao\n")
    lines.append("relacionado a regime de mercado.")

report_path = C.REPORTS_DIR / "WFO_ANALISE.md"
report_path.write_text("\n".join(lines), encoding="utf-8")
print(f"\n\n  [OK] Relatorio salvo: {report_path}")
print("\n" + "=" * 70)
print("  FIM DA ANALISE")
print("=" * 70)
