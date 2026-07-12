"""walk_forward_tokyo.py — Walk-Forward Validation da config 'Só Tokyo'.

Testa se o Sharpe 1.33 é ROBUSTO ou OVERFIT.

Metodologia:
  - Divide o período inteiro em janelas IS (treino, 6 meses) + OOS (teste, 3 meses)
  - Rola a janela a cada 3 meses (step)
  - Para cada janela, roda backtest COMPLETO (regime, sizing, custos, filtros)
    com SESSION_FILTER_ALLOW = ["Tokyo"]
  - Compara Sharpe IS vs OOS
  - Se Sharpe OOS médio > 0.8 e decaimento < 0.3 → ROBUSTO
  - Se Sharpe OOS médio > 0.6 e decaimento < 0.5 → ACEITÁVEL
  - Senão → OVERFIT

Uso:  python engine/walk_forward_tokyo.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from copy import deepcopy
from datetime import datetime

import numpy as np
import pandas as pd

from engine import config as C
from engine.data import load_all_prices, load_vix, load_dxy, dxy_pct_change_h4
from engine.regime import RuleBasedRegime
from engine.signals import TSMomentumStrategy
from engine.backtest import run_backtest
from engine.analytics import basic_summary, trade_stats
from engine.macro_events import get_events_for_backtest
from engine.walk_forward_validate import _build_windows


# ─── Configurações ───
WF_TRAIN_BARS = 1440  # IS: ~6 meses
WF_TEST_BARS = 720    # OOS: ~3 meses
WF_STEP_BARS = 720    # Step: 3 meses (rolamento sem gaps)

# Nomes das configurações para comparação
TOKYO_LABEL = "So_Tokyo"
BASELINE_LABEL = "Baseline"


def _apply_tokyo():
    """Aplica config Só Tokyo, retorna dict de originais pra restaurar."""
    orig = {
        "SESSION_FILTER_ALLOW": deepcopy(C.SESSION_FILTER_ALLOW),
    }
    C.SESSION_FILTER_ALLOW = ["Tokyo"]
    return orig


def _apply_baseline():
    """Aplica config Baseline (atual), retorna originais."""
    orig = {
        "SESSION_FILTER_ALLOW": deepcopy(C.SESSION_FILTER_ALLOW),
    }
    C.SESSION_FILTER_ALLOW = ["London", "NewYork", "Tokyo"]
    return orig


def _restore(orig: dict):
    """Restaura configuração original."""
    for key, val in orig.items():
        setattr(C, key, val)


def _run_backtest_window(prices, regime, d1_momentum, dxy_pct, vix_h4,
                          macro_events, start, end, label) -> dict:
    """Roda backtest com config atual (já aplicada externamente). Retorna dict de métricas."""
    try:
        res = run_backtest(
            prices=prices,
            strategy=TSMomentumStrategy(),
            regime_provider=regime,
            start=start, end=end,
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
        return basic_summary(res)
    except Exception as e:
        return {"label": label, "error": str(e), "sharpe": 0.0,
                "total_return_pct": 0.0, "max_dd_pct": 0.0,
                "win_rate": 0.0, "n": 0, "final_equity": C.ACCOUNT_START_USD,
                "cagr_pct": 0.0}


def main():
    print("=" * 70)
    print("  WALK-FORWARD: Validacao 'So Tokyo' (Sharpe 1.33)")
    print(f"  {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
    print("=" * 70)

    # ─── 1. Carregar dados (uma vez) ───
    print("\n[1/4] Carregando dados...")
    prices = load_all_prices(timeframe=C.TIMEFRAME, bars=C.BARS_LOOKBACK, align=True)
    common_h4 = next(iter(prices.values())).index
    n_total = len(common_h4)
    print(f"   {len(prices)} simbolos, {n_total} barras H4")
    print(f"   Periodo: {common_h4[0].date()} -> {common_h4[-1].date()}")

    vix = load_vix(period="max")
    print(f"   VIX: {len(vix)} dias")

    # DXY + VIX H4
    dxy_pct, vix_h4 = None, None
    try:
        dxy_raw = load_dxy(period="10y")
        dxy_pct = dxy_pct_change_h4(dxy_raw, common_h4, lookback=C.DXY_LIQUIDITY_STRESS_LOOKBACK_BARS)
        vix_pct_ser = vix.pct_change(5) * 100.0
        vix_h4 = vix_pct_ser.reindex(common_h4).ffill()
        print(f"   DXY + VIX H4: OK")
    except Exception as e:
        print(f"   DXY/VIX H4: {e}")

    # Macro events
    macro_events = None
    try:
        macro_events = get_events_for_backtest(C.START_COMMON, C.END_DEFAULT)
        print(f"   Eventos macro: {len(macro_events)} gerados")
    except Exception as e:
        print(f"   Eventos macro: {e}")

    # ─── 2. Regime provider (compartilhado) ───
    print("\n[2/4] Montando regime...")
    regime = RuleBasedRegime(vix=vix, prices_for_corr=prices)

    # ─── 3. D1 momentum (compartilhado) ───
    print("\n[3/4] Calculando D1 momentum...")
    d1_momentum = {}
    if C.D1_FILTER_ENABLED:
        for sym, df in prices.items():
            daily_close = df["close"].resample("D").last().dropna()
            mom = (daily_close.shift(1) / daily_close.shift(C.D1_MOMENTUM_LOOKBACK_BARS + 1)) - 1.0
            d1_h4 = mom.reindex(common_h4, method="ffill")
            d1_momentum[sym] = d1_h4
        print(f"   D1 momentum calculado para {len(d1_momentum)} simbolos")

    # ─── 4. Janelas walk-forward ───
    print("\n[4/4] Montando janelas walk-forward...")
    windows = _build_windows(
        common_h4,
        train_bars=WF_TRAIN_BARS,
        test_bars=WF_TEST_BARS,
        step_bars=WF_STEP_BARS,
    )
    print(f"   Janelas: {len(windows)}")
    print(f"   IS:  {WF_TRAIN_BARS} barras (~{WF_TRAIN_BARS//6:.0f} dias)")
    print(f"   OOS: {WF_TEST_BARS} barras (~{WF_TEST_BARS//6:.0f} dias)")
    print(f"   Step: {WF_STEP_BARS} barras (rolamento ~3 meses)")

    # ─── 5. Rodar walk-forward ───
    print("\n" + "=" * 70)
    print("  EXECUTANDO WALK-FORWARD")
    print("=" * 70)

    tokyo_is_rows = []
    tokyo_oos_rows = []
    baseline_oos_rows = []

    total = len(windows)
    for i, w in enumerate(windows):
        print(f"\n--- Janela {i+1}/{total} ---")
        print(f"  IS:  {w['train_start']} -> {w['train_end']}")
        print(f"  OOS: {w['test_start']} -> {w['test_end']}")

        # ── Tokyo IS ──
        print(f"  [Tokyo] IS...", end=" ", flush=True)
        orig_tokyo = _apply_tokyo()
        try:
            is_metrics = _run_backtest_window(
                prices, regime, d1_momentum, dxy_pct, vix_h4, macro_events,
                start=w["train_start"], end=w["train_end"],
                label=f"Tokyo_IS_w{i+1}",
            )
            print(f"Sharpe={is_metrics.get('sharpe', 0):.2f}  "
                  f"Ret={is_metrics.get('total_return_pct', 0):+.1f}%  "
                  f"DD={is_metrics.get('max_dd_pct', 0):.1f}%  "
                  f"Trades={is_metrics.get('n', 0)}")
            tokyo_is_rows.append(is_metrics)
        finally:
            _restore(orig_tokyo)

        # ── Tokyo OOS ──
        print(f"  [Tokyo] OOS...", end=" ", flush=True)
        orig_tokyo = _apply_tokyo()
        try:
            oos_metrics = _run_backtest_window(
                prices, regime, d1_momentum, dxy_pct, vix_h4, macro_events,
                start=w["test_start"], end=w["test_end"],
                label=f"Tokyo_OOS_w{i+1}",
            )
            print(f"Sharpe={oos_metrics.get('sharpe', 0):.2f}  "
                  f"Ret={oos_metrics.get('total_return_pct', 0):+.1f}%  "
                  f"DD={oos_metrics.get('max_dd_pct', 0):.1f}%  "
                  f"Trades={oos_metrics.get('n', 0)}")
            tokyo_oos_rows.append(oos_metrics)
        finally:
            _restore(orig_tokyo)

        # ── Baseline OOS (pra comparar) ──
        print(f"  [Baseline] OOS...", end=" ", flush=True)
        orig_bl = _apply_baseline()
        try:
            bl_metrics = _run_backtest_window(
                prices, regime, d1_momentum, dxy_pct, vix_h4, macro_events,
                start=w["test_start"], end=w["test_end"],
                label=f"Base_OOS_w{i+1}",
            )
            print(f"Sharpe={bl_metrics.get('sharpe', 0):.2f}  "
                  f"Ret={bl_metrics.get('total_return_pct', 0):+.1f}%  "
                  f"DD={bl_metrics.get('max_dd_pct', 0):.1f}%")
            baseline_oos_rows.append(bl_metrics)
        finally:
            _restore(orig_bl)

    # ─── 6. Relatório ───
    print("\n" + "=" * 70)
    print("  GERANDO RELATORIO...")
    print("=" * 70)

    # Extrai séries
    tokyo_is_sharpes = [r.get("sharpe", 0) for r in tokyo_is_rows]
    tokyo_oos_sharpes = [r.get("sharpe", 0) for r in tokyo_oos_rows]
    baseline_oos_sharpes = [r.get("sharpe", 0) for r in baseline_oos_rows]

    decays = [o - i for i, o in zip(tokyo_is_sharpes, tokyo_oos_sharpes)]

    lines = []
    lines.append("# WALK-FORWARD: Validacao Configuracao 'So Tokyo'\n")
    lines.append(f"**Gerado em:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC\n")
    lines.append(f"**Periodo total:** {common_h4[0].date()} -> {common_h4[-1].date()}\n")
    lines.append(f"**Janelas:** {len(windows)} (IS: {WF_TRAIN_BARS}b ~6m, "
                 f"OOS: {WF_TEST_BARS}b ~3m, Step: {WF_STEP_BARS}b ~3m)\n")

    lines.append("## Resultados por Janela\n")
    lines.append("| Janela | IS Periodo | OOS Periodo |"
                 " Tokyo IS Sharpe | Tokyo IS Ret% | Tokyo IS DD% |"
                 " Tokyo OOS Sharpe | Tokyo OOS Ret% | Tokyo OOS DD% |"
                 " OOS Trades | Decaimento |"
                 " Baseline OOS Sharpe | Ganho vs Base |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|")

    for i in range(len(windows)):
        is_r = tokyo_is_rows[i]
        oos_r = tokyo_oos_rows[i]
        bl_r = baseline_oos_rows[i]
        w = windows[i]
        decay = decays[i]
        ganho = oos_r.get("sharpe", 0) - bl_r.get("sharpe", 0)

        decay_label = f"{decay:+.2f}"
        if decay > -0.3:
            decay_label += " ✅"
        elif decay > -0.5:
            decay_label += " ⚠️"
        else:
            decay_label += " ❌"

        ganho_label = f"{ganho:+.2f}"
        if ganho > 0:
            ganho_label += " ✅"
        elif ganho > -0.1:
            ganho_label += " ⚖️"
        else:
            ganho_label += " ❌"

        lines.append(
            f"| {i+1} | {w['train_start']}->{w['train_end']} | {w['test_start']}->{w['test_end']} |"
            f" {is_r.get('sharpe', 0):.2f} | {is_r.get('total_return_pct', 0):+.1f}% | {is_r.get('max_dd_pct', 0):.1f}% |"
            f" {oos_r.get('sharpe', 0):.2f} | {oos_r.get('total_return_pct', 0):+.1f}% | {oos_r.get('max_dd_pct', 0):.1f}% |"
            f" {oos_r.get('n', 0)} | {decay_label} |"
            f" {bl_r.get('sharpe', 0):.2f} | {ganho_label} |"
        )
    lines.append("")

    # Estatísticas agregadas
    lines.append("## Estatisticas Agregadas\n")

    oos_medio = np.mean(tokyo_oos_sharpes)
    is_medio = np.mean(tokyo_is_sharpes)
    decay_medio = np.mean(decays)
    oos_acima_08 = sum(1 for s in tokyo_oos_sharpes if s > 0.8)
    oos_acima_06 = sum(1 for s in tokyo_oos_sharpes if s > 0.6)
    oos_acima_10 = sum(1 for s in tokyo_oos_sharpes if s > 1.0)

    lines.append(f"| Metrica | Valor |")
    lines.append(f"|---------|-------|")
    lines.append(f"| **Sharpe IS medio** | {is_medio:.2f} |")
    lines.append(f"| **Sharpe OOS medio (Tokyo)** | {oos_medio:.2f} |")
    lines.append(f"| **Sharpe OOS medio (Baseline)** | {np.mean(baseline_oos_sharpes):.2f} |")
    lines.append(f"| **Decaimento medio** | {decay_medio:+.2f} |")
    lines.append(f"| **Janelas com OOS Sharpe > 1.0** | {oos_acima_10}/{len(windows)} |")
    lines.append(f"| **Janelas com OOS Sharpe > 0.8** | {oos_acima_08}/{len(windows)} |")
    lines.append(f"| **Janelas com OOS Sharpe > 0.6** | {oos_acima_06}/{len(windows)} |")
    lines.append(f"| **Menor Sharpe OOS** | {min(tokyo_oos_sharpes):.2f} |")
    lines.append(f"| **Maior Sharpe OOS** | {max(tokyo_oos_sharpes):.2f} |")
    lines.append(f"| **Tokyo superou Baseline em** | {sum(1 for t, b in zip(tokyo_oos_sharpes, baseline_oos_sharpes) if t > b)}/{len(windows)} janelas |")
    lines.append("")

    # Veredito
    lines.append("## Veredito\n")

    # Critério para Tokyo\n
    if oos_medio >= 0.8 and decay_medio > -0.3:
        tokyo_v = "✅ **ROBUSTO.** O Sharpe OOS medio e alto ({:.2f}) e o decaimento e pequeno ({:+.2f}). " \
                   "A configuracao 'So Tokyo' generaliza bem fora-da-amostra.".format(oos_medio, decay_medio)
    elif oos_medio >= 0.6 and decay_medio > -0.5:
        tokyo_v = "⚠️ **ACEITAVEL.** O Sharpe OOS medio ({:.2f}) e razoavel, mas ha " \
                   "variacao entre janelas (decaimento {:+.2f}). Usar com cautela.".format(oos_medio, decay_medio)
    else:
        tokyo_v = "❌ **OVERFIT.** Sharpe OOS medio ({:.2f}) com decaimento de {:+.2f}. " \
                   "Nao usar em producao.".format(oos_medio, decay_medio)
    lines.append(f"### Veredito Tokyo\n{tokyo_v}\n")

    # Comparacao com Baseline
    ganhos_tokyo = [t - b for t, b in zip(tokyo_oos_sharpes, baseline_oos_sharpes)]
    ganho_medio = np.mean(ganhos_tokyo)
    n_superou = sum(1 for g in ganhos_tokyo if g > 0)
    if n_superou >= len(windows) * 0.6 and ganho_medio > 0.1:
        base_v = "✅ **Tokyo SUPEROU o Baseline consistentemente.** Ganho medio de {:.2f} Sharpe.".format(ganho_medio)
    elif ganho_medio > 0:
        base_v = "🟡 **Tokyo superou o Baseline na media** ({:.2f}) mas nem sempre ({} de {} janelas)." \
                 "".format(ganho_medio, n_superou, len(windows))
    else:
        base_v = "❌ **Tokyo NAO superou o Baseline.** O filtro de sessao pode nao ser a melhor melhoria."
    lines.append(f"### Comparacao com Baseline\n{base_v}\n")

    # Conclusão final
    lines.append("## Conclusao Final\n")
    if oos_medio >= 0.8 and n_superou >= len(windows) * 0.5:
        lines.append(
            "✅ **CONFIGURACAO VALIDADA.**\\n\\n"
            "A configuracao 'So Tokyo' (SESSION_FILTER_ALLOW = [\"Tokyo\"]) apresenta desempenho "
            "consistente fora-da-amostra:\\n"
            f"- Sharpe OOS medio de {oos_medio:.2f}\\n"
            f"- Decaimento medio de {decay_medio:+.2f}\\n"
            f"- Supera o Baseline em {n_superou}/{len(windows)} janelas\\n\\n"
            "Pode implementar no config.py com seguranca e seguir para dry-run."
        )
    elif oos_medio >= 0.6:
        lines.append(
            "⚠️ **ACEITAVEL COM CAUTELA.**\\n\\n"
            "A configuracao 'So Tokyo' apresenta desempenho razoavel fora-da-amostra, "
            "mas com variacao entre janelas. Recomendacoes:\\n"
            "- Implementar no config.py mas monitorar o drawdown\\n"
            "- Se o Sharpe cair abaixo de 0.5 em producao, reverter\\n"
            "- Considerar re-otimizacao periodica"
        )
    else:
        lines.append(
            "❌ **NAO IMPLEMENTAR.**\\n\\n"
            "O Sharpe 1.33 observado no periodo completo foi produto de overfit. "
            "A configuracao 'So Tokyo' nao resiste a validacao walk-forward."
        )
    lines.append("")

    lines.append("---")
    lines.append("_Gerado por walk_forward_tokyo.py_")

    # Salva relatório
    report_path = C.REPORTS_DIR / "WALK_FORWARD_TOKYO.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  [OK] Relatorio salvo: {report_path}")

    # Resumo rápido
    print(f"\n{'='*70}")
    print(f"  RESUMO WALK-FORWARD TOKYO:")
    print(f"    Sharpe IS medio:  {is_medio:.2f}")
    print(f"    Sharpe OOS medio: {oos_medio:.2f}")
    print(f"    Decaimento medio: {decay_medio:+.2f}")
    print(f"    Tokyo > Baseline: {n_superou}/{len(windows)} janelas")
    print(f"    OOS Sharpe > 1.0: {oos_acima_10}/{len(windows)}")
    print(f"    OOS Sharpe > 0.8: {oos_acima_08}/{len(windows)}")
    print(f"    OOS Sharpe > 0.6: {oos_acima_06}/{len(windows)}")
    if oos_medio >= 0.8 and n_superou >= len(windows) * 0.5:
        print(f"  ✅ VEREDITO: ROBUSTO — Pode implementar.")
    elif oos_medio >= 0.6:
        print(f"  ⚠️ VEREDITO: ACEITAVEL — Monitorar em producao.")
    else:
        print(f"  ❌ VEREDITO: OVERFIT — Nao implementar.")
    print(f"{'='*70}")
    print(f"  Relatorio completo: {report_path}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
