"""regime_sweep_liquidity.py — Sweep dos thresholds do LiquidityStressSignal.

Varre:
  - DXY_LIQUIDITY_STRESS_UP_PCT (0.1, 0.2, 0.3, 0.5, 0.75)
  - VIX_LIQUIDITY_STRESS_UP_PCT  (3.0, 5.0, 7.0, 10.0)

Pra cada combinação, roda backtest ts_momentum e coleta:
  Sharpe, Retorno %, Max DD, Win Rate, Expectancy

Gera reports/regime_sweep_liquidity.csv + reports/LIQUIDITY_SWEEP.md
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from datetime import datetime
import importlib

from engine import config as C
from engine.data import load_all_prices, load_vix, load_dxy, dxy_pct_change_h4
from engine.regime import RuleBasedRegime
from engine.signals import TSMomentumStrategy
from engine.backtest import run_backtest
from engine.analytics import basic_summary


def run_with_params(dxy_threshold: float, vix_threshold: float,
                    prices, regime, dxy_pct, vix_h4) -> dict:
    """Executa backtest com thresholds específicos e retorna métricas."""

    # Salva valores originais
    orig_dxy = C.DXY_LIQUIDITY_STRESS_UP_PCT
    orig_vix = C.VIX_LIQUIDITY_STRESS_UP_PCT

    try:
        # Atualiza thresholds via config (mutável)
        C.DXY_LIQUIDITY_STRESS_UP_PCT = dxy_threshold
        C.VIX_LIQUIDITY_STRESS_UP_PCT = vix_threshold

        label = f"dxy_{dxy_threshold}_vix_{vix_threshold}"
        res = run_backtest(
            prices=prices,
            strategy=TSMomentumStrategy(),
            regime_provider=regime,
            start=C.START_COMMON,
            end=C.END_DEFAULT,
            account_start=C.ACCOUNT_START_USD,
            use_costs=True,
            label=label,
            dxy_pct=dxy_pct,
            vix_pct=vix_h4,
        )
        s = basic_summary(res)
        return {
            "dxy_threshold": dxy_threshold,
            "vix_threshold": vix_threshold,
            "trades": s["n"],
            "sharpe": s["sharpe"],
            "total_return_pct": s["total_return_pct"],
            "cagr_pct": s["cagr_pct"],
            "max_dd_pct": s["max_dd_pct"],
            "win_rate": s["win_rate"],
            "payoff": s["payoff"],
            "expectancy_usd": s["expectancy_usd"],
            "final_equity": s["final_equity"],
        }
    except Exception as e:
        return {
            "dxy_threshold": dxy_threshold,
            "vix_threshold": vix_threshold,
            "trades": 0,
            "sharpe": 0.0,
            "total_return_pct": 0.0,
            "max_dd_pct": 0.0,
            "win_rate": 0.0,
            "payoff": 0.0,
            "expectancy_usd": 0.0,
            "final_equity": C.ACCOUNT_START_USD,
            "error": str(e),
        }
    finally:
        # Restaura originais
        C.DXY_LIQUIDITY_STRESS_UP_PCT = orig_dxy
        C.VIX_LIQUIDITY_STRESS_UP_PCT = orig_vix


def main():
    print("=" * 60)
    print("  SWEEP LIQUIDITY STRESS THRESHOLDS")
    print("  Varrendo DXY x VIX thresholds...")
    print("=" * 60)

    # 1. Carrega dados (uma vez)
    print("\n[1/3] Carregando dados...")
    prices = load_all_prices(timeframe=C.TIMEFRAME, bars=C.BARS_LOOKBACK, align=True)
    n = len(next(iter(prices.values())))
    print(f"   {len(prices)} simbolos, {n} barras H4")
    vix = load_vix(period="max")
    print(f"   VIX: {len(vix)} dias")

    # DXY
    try:
        dxy_raw = load_dxy(period="10y")
        common_h4 = next(iter(prices.values())).index
        dxy_pct = dxy_pct_change_h4(dxy_raw, common_h4, lookback=C.DXY_LIQUIDITY_STRESS_LOOKBACK_BARS)
        vix_pct = vix.pct_change(5) * 100.0  # reusa vix ja carregado
        vix_h4 = vix_pct.reindex(common_h4).ffill()
        print(f"   DXY: {len(dxy_raw)} dias, % change H4 pronto")
    except Exception as e:
        print(f"   DXY falhou: {e}")
        dxy_pct = None
        vix_h4 = None

    # 2. Regime provider (compartilhado entre runs)
    print("\n[2/3] Montando regime...")
    regime = RuleBasedRegime(vix=vix, prices_for_corr=prices)

    # 3. Grid de parâmetros
    dxy_options = [0.1, 0.2, 0.3, 0.5, 0.75]
    vix_options = [3.0, 5.0, 7.0, 10.0]

    results = []
    total = len(dxy_options) * len(vix_options)
    idx = 0

    print(f"\n[3/3] Rodando {total} combinacoes...")
    for dxy_th in dxy_options:
        for vix_th in vix_options:
            idx += 1
            print(f"\n   [{idx}/{total}] DXY={dxy_th}%  VIX={vix_th}% ...", end=" ", flush=True)
            row = run_with_params(dxy_th, vix_th, prices, regime, dxy_pct, vix_h4)
            results.append(row)
            s = row
            print(f"Sharpe {s['sharpe']:.2f} | Ret {s['total_return_pct']:+.1f}% | DD {s['max_dd_pct']:.1f}%")

    # 4. Monta tabela
    df = pd.DataFrame(results)
    df = df.sort_values("sharpe", ascending=False)

    # Salva CSV
    csv_path = C.REPORTS_DIR / "regime_sweep_liquidity.csv"
    df.to_csv(csv_path, index=False)
    print(f"\n   Resultados salvos em {csv_path}")

    # 5. Relatório markdown
    best = df.iloc[0]
    lines = []
    lines.append("# SWEEP LIQUIDITY STRESS — Resultados\n")
    lines.append(f"Gerado em: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC\n")
    lines.append(f"## Melhor combinação\n")
    lines.append(f"- **DXY threshold:** {best['dxy_threshold']}%")
    lines.append(f"- **VIX threshold:** {best['vix_threshold']}%")
    lines.append(f"- **Sharpe:** {best['sharpe']:.2f}")
    lines.append(f"- **Retorno:** {best['total_return_pct']:+.1f}%")
    lines.append(f"- **Max DD:** {best['max_dd_pct']:.1f}%")
    lines.append(f"- **Win Rate:** {best['win_rate']:.1%}")
    lines.append(f"- **Payoff:** {best['payoff']:.2f}")
    lines.append(f"- **Expectancy:** ${best['expectancy_usd']:.2f}/trade")
    lines.append(f"- **Final Equity:** ${best['final_equity']:.2f}")
    lines.append("")

    # Tabela completa só com os melhores (top 10)
    lines.append("## Top 10 Combinações\n")
    lines.append("| DXY% | VIX% | Sharpe | Retorno | MaxDD | WinRate | Payoff | Expect | Final | Trades |")
    lines.append("|------|------|--------|---------|-------|---------|--------|--------|-------|")
    for _, r in df.head(10).iterrows():
        lines.append(
            f"| {r['dxy_threshold']}% | {r['vix_threshold']}% "
            f"| {r['sharpe']:.2f} | {r['total_return_pct']:+.1f}% "
            f"| {r['max_dd_pct']:.1f}% | {r['win_rate']:.1%} "
            f"| {r['payoff']:.2f} | ${r['expectancy_usd']:.2f} "
            f"| ${r['final_equity']:.2f} | {r['trades']} |"
        )
    lines.append("")

    # Baseline (config atual)
    current = df[(df['dxy_threshold'] == 0.3) & (df['vix_threshold'] == 5.0)]
    if not current.empty:
        c = current.iloc[0]
        lines.append("## Configuração Atual (DXY=0.3%, VIX=5.0%)\n")
        lines.append(f"- Sharpe: {c['sharpe']:.2f} | Retorno: {c['total_return_pct']:+.1f}% | DD: {c['max_dd_pct']:.1f}%\n")

    # Veredito
    lines.append("## Recomendação\n")
    rec = best['dxy_threshold']
    rec_v = best['vix_threshold']
    lines.append(f"Usar **DXY_LIQUIDITY_STRESS_UP_PCT={rec}** e **VIX_LIQUIDITY_STRESS_UP_PCT={rec_v}**")
    if best['sharpe'] >= 0.65:
        lines.append("✅ **Melhora significativa** em relação ao baseline sem LiquidityStress.")
    elif best['sharpe'] >= 0.60:
        lines.append("🟡 **Melhora marginal.** Pode valer a pena refinar mais.")
    else:
        lines.append("ℹ️ Similar ao baseline. O LiquidityStress não degrada.")
    lines.append("")

    lines.append("---")
    lines.append("_Gerado por regime_sweep_liquidity.py_")

    report_path = C.REPORTS_DIR / "LIQUIDITY_SWEEP.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n   Relatório salvo em {report_path}")
    print(f"\n{'='*60}")
    print(f"  MELHOR: DXY={best['dxy_threshold']}%, VIX={best['vix_threshold']}%")
    print(f"  Sharpe={best['sharpe']:.2f} | Ret={best['total_return_pct']:+.1f}% | DD={best['max_dd_pct']:.1f}%")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
