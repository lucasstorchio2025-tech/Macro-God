"""sweep_comparativo.py — Compara 3 melhorias no ts_momentum lado a lado.

Melhorias testadas:
  1. PARTIAL TP DESLIGADO     (PARTIAL_TP_FRACTION = 0.0)
  2. LOOKBACK REDUZIDO        (MOMENTUM_LOOKBACK_BARS = 96, COOLDOWN_BARS = 6)
  3. SÓ TOKYO                 (SESSION_FILTER_ALLOW = ["Tokyo"])

Gera reports/COMPARATIVO.md com tabela de resultados + equity curves.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from copy import deepcopy
from datetime import datetime

import numpy as np
import pandas as pd

from engine import config as C
from engine.data import load_all_prices, load_vix, load_cot_history, load_dxy, dxy_pct_change_h4
from engine.regime import RuleBasedRegime
from engine.signals import TSMomentumStrategy
from engine.backtest import run_backtest
from engine.analytics import basic_summary, trade_stats, plot_equity
from engine.macro_events import get_events_for_backtest

# ─── Configurações a testar ───
CONFIGS = {
    "1. BASELINE (atual)": {
        "PARTIAL_TP_FRACTION": 0.3,
        "PARTIAL_TP_RR": 1.0,
        "MOMENTUM_LOOKBACK_BARS": 264,
        "MOMENTUM_SKIP_BARS": 24,
        "COOLDOWN_BARS": 12,
        "SESSION_FILTER_ALLOW": ["London", "NewYork", "Tokyo"],
        "desc": "Configuração atual do config.py",
    },
    "2. Partial TP desligado": {
        "PARTIAL_TP_FRACTION": 0.0,
        "PARTIAL_TP_RR": 0.0,
        "MOMENTUM_LOOKBACK_BARS": 264,
        "MOMENTUM_SKIP_BARS": 24,
        "COOLDOWN_BARS": 12,
        "SESSION_FILTER_ALLOW": ["London", "NewYork", "Tokyo"],
        "desc": "PARTIAL_TP_FRACTION=0.0 — trades correm até o TP cheio",
    },
    "3. Lookback reduzido": {
        "PARTIAL_TP_FRACTION": 0.3,
        "PARTIAL_TP_RR": 1.0,
        "MOMENTUM_LOOKBACK_BARS": 96,
        "MOMENTUM_SKIP_BARS": 8,
        "COOLDOWN_BARS": 6,
        "SESSION_FILTER_ALLOW": ["London", "NewYork", "Tokyo"],
        "desc": "MOMENTUM=96 (de 264), COOLDOWN=6 (de 12) — +trades",
    },
    "4. Só Tokyo": {
        "PARTIAL_TP_FRACTION": 0.3,
        "PARTIAL_TP_RR": 1.0,
        "MOMENTUM_LOOKBACK_BARS": 264,
        "MOMENTUM_SKIP_BARS": 24,
        "COOLDOWN_BARS": 12,
        "SESSION_FILTER_ALLOW": ["Tokyo"],
        "desc": "SESSION_FILTER_ALLOW = só Tokyo (melhor sessão)",
    },
    "5. TUDO COMBINADO": {
        "PARTIAL_TP_FRACTION": 0.0,
        "PARTIAL_TP_RR": 0.0,
        "MOMENTUM_LOOKBACK_BARS": 96,
        "MOMENTUM_SKIP_BARS": 8,
        "COOLDOWN_BARS": 6,
        "SESSION_FILTER_ALLOW": ["Tokyo"],
        "desc": "Todas as 3 melhorias juntas",
    },
    "6. Tokyo + Lookback": {
        "PARTIAL_TP_FRACTION": 0.3,
        "PARTIAL_TP_RR": 1.0,
        "MOMENTUM_LOOKBACK_BARS": 96,
        "MOMENTUM_SKIP_BARS": 8,
        "COOLDOWN_BARS": 6,
        "SESSION_FILTER_ALLOW": ["Tokyo"],
        "desc": "Tokyo + MOMENTUM=96 + COOLDOWN=6 — sinal mais rapido na melhor sessao",
    },
}


def _apply_config(label: str, params: dict):
    """Aplica parâmetros de configuração para uma rodada."""
    originals = {}
    for key, val in params.items():
        if hasattr(C, key):
            originals[key] = deepcopy(getattr(C, key))
            setattr(C, key, deepcopy(val))
    return originals


def _restore_config(originals: dict):
    """Restaura configuração original."""
    for key, val in originals.items():
        setattr(C, key, val)


def _run_one(label: str, params: dict, prices, regime, d1_momentum,
             dxy_pct, vix_h4, macro_events) -> dict:
    """Roda 1 backtest com parâmetros específicos."""
    orig = _apply_config(label, params)
    try:
        res = run_backtest(
            prices=prices,
            strategy=TSMomentumStrategy(),
            regime_provider=regime,
            start=C.START_COMMON,
            end=C.END_DEFAULT,
            account_start=C.ACCOUNT_START_USD,
            max_positions=C.MAX_OPEN_POSITIONS,
            risk_per_trade_pct=C.RISK_PER_TRADE_PCT,
            risk_pct_by_regime=C.RISK_PCT_BY_REGIME,
            d1_momentum=d1_momentum if C.D1_FILTER_ENABLED else None,
            use_costs=True,
            label=label,
            dxy_pct=dxy_pct,
            vix_pct=vix_h4,
            macro_events=macro_events,
        )
        s = basic_summary(res)
        return {
            "result": res,
            "metrics": s,
            "trades": res.trades,
        }
    finally:
        _restore_config(orig)


def _tabela_campo(rows: list[dict], campo: str) -> str:
    """Gera tabela markdown de uma linha simples."""
    if not rows:
        return "(sem dados)"
    lines = []
    lines.append("| " + " | ".join(rows[0].keys()) + " |")
    lines.append("|" + "|".join(["---"] * len(rows[0].keys())) + "|")
    for r in rows:
        vals = []
        for k in r.keys():
            v = r[k]
            if isinstance(v, float):
                vals.append(f"{v:+.2f}" if "delta" in k or "ret" in k.lower() else f"{v:.2f}")
            elif isinstance(v, int):
                vals.append(str(v))
            else:
                vals.append(str(v))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def main():
    print("=" * 70)
    print("  SWEEP COMPARATIVO — 3 Melhorias no TS-Momentum")
    print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
    print("=" * 70)

    # ─── 1. Carregar dados ───
    print("\n[1/4] Carregando dados...")
    prices = load_all_prices(timeframe=C.TIMEFRAME, bars=C.BARS_LOOKBACK, align=True)
    n_barras = len(next(iter(prices.values())))
    print(f"   {len(prices)} simbolos, {n_barras} barras H4")
    vix = load_vix(period="max")
    print(f"   VIX: {len(vix)} dias")

    # DXY + VIX H4
    dxy_pct, vix_h4 = None, None
    try:
        dxy_raw = load_dxy(period="10y")
        common_h4 = next(iter(prices.values())).index
        dxy_pct = dxy_pct_change_h4(dxy_raw, common_h4, lookback=C.DXY_LIQUIDITY_STRESS_LOOKBACK_BARS)
        vix_pct_ser = vix.pct_change(5) * 100.0
        vix_h4 = vix_pct_ser.reindex(common_h4).ffill()
        print(f"   DXY + VIX H4: OK")
    except Exception as e:
        print(f"   DXY/VIX H4: {e} (desativado)")

    # Macro events
    macro_events = None
    try:
        macro_events = get_events_for_backtest(C.START_COMMON, C.END_DEFAULT)
        print(f"   Eventos macro: {len(macro_events)} gerados")
    except Exception as e:
        print(f"   Eventos macro: {e}")

    # ─── 2. Regime (compartilhado) ───
    print("\n[2/4] Montando regime...")
    regime = RuleBasedRegime(vix=vix, prices_for_corr=prices)
    print(f"   Regime provider: OK")

    # ─── 3. D1 Momentum (compartilhado) ───
    print("\n[3/4] Calculando D1 momentum...")
    d1_momentum = {}
    if C.D1_FILTER_ENABLED:
        common_h4 = next(iter(prices.values())).index
        for sym, df in prices.items():
            daily_close = df["close"].resample("D").last().dropna()
            mom = (daily_close.shift(1) / daily_close.shift(C.D1_MOMENTUM_LOOKBACK_BARS + 1)) - 1.0
            d1_h4 = mom.reindex(common_h4, method="ffill")
            d1_momentum[sym] = d1_h4
        print(f"   D1 momentum calculado para {len(d1_momentum)} simbolos")

    # ─── 4. Rodar todos ───
    print("\n[4/4] Rodando backtests...")
    results = []
    total = len(CONFIGS)
    for idx, (label, params) in enumerate(CONFIGS.items(), 1):
        print(f"\n  [{idx}/{total}] {label}")
        print(f"     {params['desc']}")
        try:
            data = _run_one(label, params, prices, regime, d1_momentum,
                            dxy_pct, vix_h4, macro_events)
            s = data["metrics"]
            trades = data["trades"]

            # Detalhamento de saidas
            saidas = {}
            for t in trades:
                saidas[t.exit_reason] = saidas.get(t.exit_reason, 0) + 1

            print(f"     {s['n']} trades | Sharpe {s['sharpe']:.2f} | "
                  f"Ret {s['total_return_pct']:+.1f}% | CAGR {s['cagr_pct']:.1f}%")
            print(f"     DD {s['max_dd_pct']:.1f}% | Win {s['win_rate']:.1%} | "
                  f"Payoff {s['payoff']:.2f} | Expect ${s['expectancy_usd']:.2f}")
            print(f"     Saidas: {dict(saidas)}")
            print(f"     Final: ${s['final_equity']:.2f}")

            results.append(data)
        except Exception as e:
            import traceback
            print(f"     ERRO: {type(e).__name__}: {e}")
            traceback.print_exc()

    # ─── 5. Relatório ───
    print("\n" + "=" * 70)
    print("  GERANDO RELATORIO COMPARATIVO...")
    print("=" * 70)

    # Equity curves
    equity_results = [r["result"] for r in results]
    try:
        plot_equity(equity_results, C.REPORTS_DIR / "comparativo_equity.png",
                    title="Comparativo: 3 Melhorias no TS-Momentum")
        print("  [OK] Gráfico salvo: reports/comparativo_equity.png")
    except Exception as e:
        print(f"  [AVISO] Grafico: {e}")

    # Monta relatório markdown
    lines = []
    lines.append("# COMPARATIVO — 3 Melhorias no TS-Momentum\n")
    lines.append(f"**Gerado em:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC\n")
    lines.append(f"**Período:** {C.START_COMMON} → {C.END_DEFAULT} | "
                 f"**Símbolo:** {C.SYMBOLS[0]} | **Período H4:** H4\n")

    # Tabela principal
    lines.append("## Tabela Comparativa\n")
    lines.append("| Configuração | Trades | Sharpe | Sortino | Retorno% | CAGR% | "
                 "MaxDD% | WinRate | Payoff | Expect$/trade | Final$ |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")

    best_sharpe = max(results, key=lambda r: r["metrics"]["sharpe"])
    for r in results:
        s = r["metrics"]
        is_best = r is best_sharpe
        label_star = "★ " if is_best else "  "
        lines.append(
            f"| {label_star}{s['label'][:30]:30s} | {s['n']:>4d} | {s['sharpe']:.2f} | "
            f"{s['sortino']:.2f} | {s['total_return_pct']:+.1f}% | "
            f"{s['cagr_pct']:+.1f}% | {s['max_dd_pct']:.1f}% | "
            f"{s['win_rate']:.1%} | {s['payoff']:.2f} | "
            f"${s['expectancy_usd']:+.2f} | ${s['final_equity']:.2f} |"
        )
    lines.append("")

    # Descrições
    lines.append("## Configurações Testadas\n")
    for label, params in CONFIGS.items():
        lines.append(f"- **{label}**: {params['desc']}")
    lines.append("")

    # Detalhe das saídas
    lines.append("## Detalhamento por Motivo de Saída\n")
    lines.append("| Configuração | TP | Partial TP | SL | TIME | REGIME_EXIT |")
    lines.append("|---|---|---|---|---|---|")
    for r in results:
        label = r["metrics"]["label"]
        saidas = {}
        for t in r["trades"]:
            saidas[t.exit_reason] = saidas.get(t.exit_reason, 0) + 1
        tp = saidas.get("TP", 0)
        ptp = saidas.get("PARTIAL_TP", 0)
        sl = saidas.get("SL", 0)
        ti = saidas.get("TIME", 0)
        re = saidas.get("REGIME_EXIT", 0)
        lines.append(f"| {label[:30]:30s} | {tp:>3d} | {ptp:>3d} | {sl:>3d} | {ti:>3d} | {re:>3d} |")
    lines.append("")

    # Trades/semana
    lines.append("## Frequência de Trades\n")
    anos = 4.7
    for r in results:
        s = r["metrics"]
        trades_ano = s["n"] / anos
        trades_sem = trades_ano / 52
        lines.append(f"- **{s['label'][:30]:30s}**: {s['n']:>4d} trades em {anos:.1f} anos → "
                     f"{trades_ano:.0f}/ano → **{trades_sem:.1f}/semana**")
    lines.append("")

    # Análise por regime
    lines.append("## Análise por Regime (config vencedora)\n")
    best = best_sharpe["metrics"]["label"]
    best_result = best_sharpe["result"]
    regimes = {}
    for t in best_result.trades:
        regimes.setdefault(t.regime_at_entry or "?", []).append(t)
    lines.append(f"Detalhamento da melhor: **{best}**\n")
    lines.append("| Regime | Trades | Win Rate | P&L Total | Média |")
    lines.append("|--------|--------|----------|-----------|-------|")
    for reg, trades in sorted(regimes.items()):
        pnls = [t.pnl_usd for t in trades]
        wins = sum(1 for p in pnls if p > 0)
        wr = wins / len(pnls) * 100 if pnls else 0
        total = sum(pnls)
        med = np.mean(pnls) if pnls else 0
        lines.append(f"| {reg} | {len(pnls)} | {wr:.1f}% | ${total:+.2f} | ${med:+.2f} |")
    lines.append("")

    # Ganho sobre baseline
    lines.append("## Ganho sobre o Baseline\n")
    baseline = results[0]
    bl_sharpe = baseline["metrics"]["sharpe"]
    bl_cagr = baseline["metrics"]["cagr_pct"]
    bl_eq = baseline["metrics"]["final_equity"]

    for r in results[1:]:
        s = r["metrics"]
        d_sharpe = s["sharpe"] - bl_sharpe
        d_cagr = s["cagr_pct"] - bl_cagr
        d_eq = s["final_equity"] - bl_eq
        pct_melhor = f"+{d_cagr:.1f}pp" if d_cagr > 0 else f"{d_cagr:.1f}pp"
        lines.append(
            f"- **{s['label'][:30]:30s}**: Sharpe {bl_sharpe:.2f}→{s['sharpe']:.2f} "
            f"({d_sharpe:+.2f}) | CAGR {bl_cagr:.1f}%→{s['cagr_pct']:.1f}% ({pct_melhor}) | "
            f"Final ${bl_eq:.0f}→${s['final_equity']:.0f} (${d_eq:+.0f})"
        )
    lines.append("")

    # Veredito
    lines.append("## Veredito\n")
    best_s = best_sharpe["metrics"]
    best_label = best_s["label"]
    lines.append(f"**Melhor configuração:** {best_label}\n")
    lines.append(f"- Sharpe **{best_s['sharpe']:.2f}** (vs {bl_sharpe:.2f} do baseline)")
    lines.append(f"- CAGR **{best_s['cagr_pct']:.1f}%** (vs {bl_cagr:.1f}%)")
    lines.append(f"- Final **${best_s['final_equity']:.0f}** (vs ${bl_eq:.0f})")
    lines.append("")

    if best_s["sharpe"] > 1.0:
        lines.append("✅ **Recomendação:** Sharpe > 1.0. Esta configuração pode ir para dry-run.")
    elif best_s["sharpe"] > 0.8:
        lines.append("👍 **Recomendação:** Sharpe > 0.8. Melhora significativa sobre o baseline. "
                     "Considere adotar esta configuração.")
    elif best_s["sharpe"] > 0.6:
        lines.append("🟡 **Recomendação:** Melhora marginal. Vale refinar mais os parâmetros.")
    else:
        lines.append("ℹ️ Nenhuma configuração superou significativamente o baseline.")

    lines.append("")

    # Equity chart
    lines.append("## Gráfico\n")
    lines.append("![Equity comparativa](comparativo_equity.png)\n")
    lines.append("---\n")
    lines.append(f"_Gerado por sweep_comparativo.py_")

    # Salva
    report_path = C.REPORTS_DIR / "COMPARATIVO.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  [OK] Relatório salvo: {report_path}")
    print(f"\n{'='*70}")
    print(f"  RESUMO:")
    for r in results:
        s = r["metrics"]
        star = "★ " if r is best_sharpe else "  "
        print(f"  {star}{s['label'][:35]:35s} Sharpe {s['sharpe']:.2f} | "
              f"{s['total_return_pct']:+.1f}% | ${s['final_equity']:.2f}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
