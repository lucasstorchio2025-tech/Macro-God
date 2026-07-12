"""walk_forward_validate.py — Validação Walk-Forward dos parâmetros do LiquidityStressSignal.

Duas validações independentes:

  1. VALIDAÇÃO FIXA (rápida — ~2 min):
     Usa os parâmetros DXY=0.5%, VIX=10.0% em TODAS as janelas OOS.
     Se o Sharpe OOS for consistentemente > 0.8 e próximo do IS -> robusto.

  2. SWEEP POR JANELA (mais rigorosa — ~10 min):
     Para cada janela, varre DXY x VIX thresholds no IS e testa o melhor OOS.
     Se os thresholds ótimos por janela se agrupam ao redor de 0.5/10.0 -> não overfit.

Métricas reportadas por janela: Sharpe, retorno %, Max DD, Win Rate.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from datetime import datetime
from typing import Optional

from engine import config as C
from engine.data import load_all_prices, load_vix, load_dxy, dxy_pct_change_h4
from engine.regime import RuleBasedRegime
from engine.signals import TSMomentumStrategy
from engine.backtest import run_backtest
from engine.analytics import basic_summary, trade_stats


# ═════════════════════════════ CARREGAMENTO ÚNICO DE DADOS ═════════════════════════════
_DATA_CACHE = {}


def _ensure_data():
    """Carrega dados uma vez e cacheia."""
    if _DATA_CACHE:
        return _DATA_CACHE
    print("  Carregando dados...")
    prices = load_all_prices(timeframe=C.TIMEFRAME, bars=C.BARS_LOOKBACK, align=True)
    vix = load_vix(period="max")
    common_h4 = next(iter(prices.values())).index
    n = len(common_h4)
    print(f"      {len(prices)} simbolos, {n} barras H4 ({common_h4[0].date()} -> {common_h4[-1].date()})")



    # DXY
    try:
        dxy_raw = load_dxy(period="10y")
        dxy_pct = dxy_pct_change_h4(dxy_raw, common_h4, lookback=C.DXY_LIQUIDITY_STRESS_LOOKBACK_BARS)
        vix_pct = vix.pct_change(5) * 100.0
        vix_h4 = vix_pct.reindex(common_h4).ffill()
        print(f"     DXY: OK")
    except Exception as e:
        print(f"     DXY falhou: {e}")
        dxy_pct = None
        vix_h4 = None

    # Regime provider (compartilhado)
    regime = RuleBasedRegime(vix=vix, prices_for_corr=prices)

    _DATA_CACHE.update(dict(
        prices=prices, vix=vix, common_h4=common_h4,
        dxy_pct=dxy_pct, vix_h4=vix_h4, regime=regime,
    ))
    return _DATA_CACHE


# ═════════════════════════════ BACKTEST COM PARÂMETROS ═════════════════════════════
def _run_backtest(prices, regime, dxy_pct, vix_h4,
                   start: str, end: str, label: str,
                   dxy_th: float = 0.5, vix_th: float = 10.0) -> dict:
    """Roda backtest com thresholds específicos de LiquidityStress."""
    orig_dxy = C.DXY_LIQUIDITY_STRESS_UP_PCT
    orig_vix = C.VIX_LIQUIDITY_STRESS_UP_PCT
    try:
        C.DXY_LIQUIDITY_STRESS_UP_PCT = dxy_th
        C.VIX_LIQUIDITY_STRESS_UP_PCT = vix_th
        res = run_backtest(
            prices=prices,
            strategy=TSMomentumStrategy(),
            regime_provider=regime,
            start=start, end=end,
            account_start=C.ACCOUNT_START_USD,
            use_costs=True,
            label=label,
            dxy_pct=dxy_pct,
            vix_pct=vix_h4,
        )
        return basic_summary(res)
    finally:
        C.DXY_LIQUIDITY_STRESS_UP_PCT = orig_dxy
        C.VIX_LIQUIDITY_STRESS_UP_PCT = orig_vix


def _run_fixed_params(prices, regime, dxy_pct, vix_h4,
                      start: str, end: str, label: str) -> dict:
    """Roda com parâmetros otimizados DXY=0.5%, VIX=10.0%."""
    return _run_backtest(prices, regime, dxy_pct, vix_h4,
                          start, end, label, dxy_th=0.5, vix_th=10.0)


def _run_disabled(prices, regime, dxy_pct, vix_h4,
                  start: str, end: str, label: str) -> dict:
    """Roda com LiquidityStress DESATIVADO (thresholds inatingíveis)."""
    return _run_backtest(prices, regime, dxy_pct, vix_h4,
                          start, end, label, dxy_th=99.0, vix_th=99.0)


def _run_sweep_on(prices, regime, dxy_pct, vix_h4,
                  start: str, end: str) -> dict:
    """Varre thresholds no período e retorna o melhor resultado + o melhor params."""
    dxy_options = [0.1, 0.2, 0.3, 0.5, 0.75]
    vix_options = [3.0, 5.0, 7.0, 10.0]

    orig_dxy = C.DXY_LIQUIDITY_STRESS_UP_PCT
    orig_vix = C.VIX_LIQUIDITY_STRESS_UP_PCT

    best = {"sharpe": -999}
    results = []
    try:
        for dxy_th in dxy_options:
            for vix_th in vix_options:
                C.DXY_LIQUIDITY_STRESS_UP_PCT = dxy_th
                C.VIX_LIQUIDITY_STRESS_UP_PCT = vix_th
                try:
                    res = run_backtest(
                        prices=prices,
                        strategy=TSMomentumStrategy(),
                        regime_provider=regime,
                        start=start, end=end,
                        account_start=C.ACCOUNT_START_USD,
                        use_costs=True,
                        label=f"sweep_{dxy_th}_{vix_th}",
                        dxy_pct=dxy_pct,
                        vix_pct=vix_h4,
                    )
                    s = basic_summary(res)
                    row = {"dxy": dxy_th, "vix": vix_th,
                           "sharpe": s["sharpe"],
                           "ret": s["total_return_pct"],
                           "dd": s["max_dd_pct"]}
                    results.append(row)
                    if s["sharpe"] > best["sharpe"]:
                        best = {"dxy": dxy_th, "vix": vix_th,
                                "sharpe": s["sharpe"],
                                "ret": s["total_return_pct"],
                                "dd": s["max_dd_pct"]}
                except Exception as e:
                    continue
    finally:
        C.DXY_LIQUIDITY_STRESS_UP_PCT = orig_dxy
        C.VIX_LIQUIDITY_STRESS_UP_PCT = orig_vix

    return {
        "best": best,
        "all": results,
        "n_tested": len(results),
    }


# ═════════════════════════════ WALK-FORWARD WINDOWS ═════════════════════════════
def _build_windows(common_h4: pd.DatetimeIndex,
                   train_bars: int = 1440,
                   test_bars: int = 720,
                   step_bars: int = 720):
    """Gera lista de (train_start, train_end, test_start, test_end) como strings."""
    n = len(common_h4)
    windows = []
    pos = 0
    while pos + train_bars + test_bars < n:
        train_start = str(common_h4[pos].date())
        train_end = str(common_h4[pos + train_bars - 1].date())
        test_start = str(common_h4[pos + train_bars].date())
        test_end = str(common_h4[pos + train_bars + test_bars - 1].date())
        windows.append({
            "train_start": train_start, "train_end": train_end,
            "test_start": test_start, "test_end": test_end,
            "train_bars": train_bars, "test_bars": test_bars,
        })
        pos += step_bars
    return windows


# ═════════════════════════════ VALIDAÇÃO 1: PARÂMETROS FIXOS ═════════════════════════════
def validate_fixed_params(data: dict, windows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Testa parâmetros DXY=0.5%, VIX=10.0% em IS e OOS de cada janela.
    Retorna (resultados_com_sinal, resultados_sem_sinal).
    """
    print("\n[WALK-FORWARD] Validacao 1: Parametros fixos (DXY=0.5%, VIX=10.0%)")
    print("=" * 60)

    rows_com = []
    rows_sem = []
    total = len(windows)
    for i, w in enumerate(windows):
        print(f"\n  Janela {i+1}/{total}:")
        print(f"    IS:  {w['train_start']} -> {w['train_end']}  ({w['train_bars']} barras)")
        print(f"    OOS: {w['test_start']} -> {w['test_end']}  ({w['test_bars']} barras)")

        # IS com sinal
        is_metrics = _run_fixed_params(
            data["prices"], data["regime"], data["dxy_pct"], data["vix_h4"],
            start=w["train_start"], end=w["train_end"],
            label=f"IS_w{i+1}",
        )
        print(f"    [IS COM SINAL] Sharpe={is_metrics['sharpe']:.2f}  "
              f"Ret={is_metrics['total_return_pct']:+.1f}%  "
              f"DD={is_metrics['max_dd_pct']:.1f}%  "
              f"Trades={is_metrics['n']}")

        # OOS com sinal
        oos_metrics = _run_fixed_params(
            data["prices"], data["regime"], data["dxy_pct"], data["vix_h4"],
            start=w["test_start"], end=w["test_end"],
            label=f"OOS_w{i+1}",
        )
        print(f"    [OOS COM SINAL] Sharpe={oos_metrics['sharpe']:.2f}  "
              f"Ret={oos_metrics['total_return_pct']:+.1f}%  "
              f"DD={oos_metrics['max_dd_pct']:.1f}%  "
              f"Trades={oos_metrics['n']}")

        # OOS SEM sinal (baseline - liquidez desativada)
        oos_sem = _run_disabled(
            data["prices"], data["regime"], data["dxy_pct"], data["vix_h4"],
            start=w["test_start"], end=w["test_end"],
            label=f"OOS_SEM_w{i+1}",
        )
        ganho_sinal = oos_metrics['sharpe'] - oos_sem['sharpe']
        print(f"    [OOS SEM SINAL] Sharpe={oos_sem['sharpe']:.2f}  "
              f"Ret={oos_sem['total_return_pct']:+.1f}%  "
              f"DD={oos_sem['max_dd_pct']:.1f}%")
        print(f"    Ganho do sinal no OOS: {ganho_sinal:+.2f} Sharpe")

        # Decaimento IS -> OOS
        decay = oos_metrics['sharpe'] - is_metrics['sharpe']
        label_dec = "[OK]" if decay > -0.3 else "[ATENCAO]" if decay > -0.5 else "[RUIM]"
        print(f"    {label_dec} Decaimento Sharpe: {decay:+.2f}")

        rows_com.append({
            "janela": i + 1,
            "is_periodo": f"{w['train_start']}->{w['train_end']}",
            "oos_periodo": f"{w['test_start']}->{w['test_end']}",
            "is_sharpe": round(is_metrics['sharpe'], 3),
            "is_ret_pct": round(is_metrics['total_return_pct'], 1),
            "is_dd_pct": round(is_metrics['max_dd_pct'], 1),
            "is_win_rate": round(is_metrics['win_rate'], 3),
            "is_trades": is_metrics['n'],
            "oos_sharpe": round(oos_metrics['sharpe'], 3),
            "oos_ret_pct": round(oos_metrics['total_return_pct'], 1),
            "oos_dd_pct": round(oos_metrics['max_dd_pct'], 1),
            "oos_win_rate": round(oos_metrics['win_rate'], 3),
            "oos_trades": oos_metrics['n'],
            "sharpe_decay": round(decay, 2),
        })
        rows_sem.append({
            "janela": i + 1,
            "oos_periodo": f"{w['test_start']}->{w['test_end']}",
            "oos_sharpe_sem": round(oos_sem['sharpe'], 3),
            "oos_ret_sem": round(oos_sem['total_return_pct'], 1),
            "oos_dd_sem": round(oos_sem['max_dd_pct'], 1),
            "ganho_sharpe": round(ganho_sinal, 2),
        })

    return rows_com, rows_sem


# ═════════════════════════════ VALIDAÇÃO 2: SWEEP POR JANELA ═════════════════════════════
def validate_sweep_per_window(data: dict, windows: list[dict]) -> list[dict]:
    """Para cada janela, varre thresholds no IS, testa o melhor no OOS."""
    print("\n[WALK-FORWARD] Validacao 2: Sweep por janela (mais rigorosa)")
    print("=" * 60)
    print("  (pode levar varios minutos)")

    rows = []
    total = len(windows)
    for i, w in enumerate(windows):
        print(f"\n  Janela {i+1}/{total}:")
        print(f"    IS:  {w['train_start']} -> {w['train_end']}")
        print(f"    OOS: {w['test_start']} -> {w['test_end']}")

        # Sweep no IS
        print(f"    Varrendo {len([0.1,0.2,0.3,0.5,0.75]) * len([3.0,5.0,7.0,10.0])} combinacoes no IS...")
        sweep_result = _run_sweep_on(
            data["prices"], data["regime"], data["dxy_pct"], data["vix_h4"],
            start=w["train_start"], end=w["train_end"],
        )
        best = sweep_result["best"]
        print(f"    Melhor no IS: DXY={best['dxy']}%  VIX={best['vix']}%  "
              f"Sharpe={best['sharpe']:.2f}")

        # Testa o melhor no OOS
        orig_dxy = C.DXY_LIQUIDITY_STRESS_UP_PCT
        orig_vix = C.VIX_LIQUIDITY_STRESS_UP_PCT
        try:
            C.DXY_LIQUIDITY_STRESS_UP_PCT = best["dxy"]
            C.VIX_LIQUIDITY_STRESS_UP_PCT = best["vix"]
            oos_res = run_backtest(
                prices=data["prices"],
                strategy=TSMomentumStrategy(),
                regime_provider=data["regime"],
                start=w["test_start"], end=w["test_end"],
                account_start=C.ACCOUNT_START_USD,
                use_costs=True,
                label=f"sweep_oos_w{i+1}",
                dxy_pct=data["dxy_pct"],
                vix_pct=data["vix_h4"],
            )
            oos_metrics = basic_summary(oos_res)
        finally:
            C.DXY_LIQUIDITY_STRESS_UP_PCT = orig_dxy
            C.VIX_LIQUIDITY_STRESS_UP_PCT = orig_vix

        print(f"    [OOS] DXY={best['dxy']}%  VIX={best['vix']}%  "
              f"Sharpe={oos_metrics['sharpe']:.2f}  "
              f"Ret={oos_metrics['total_return_pct']:+.1f}%  "
              f"DD={oos_metrics['max_dd_pct']:.1f}%")

        # Testa o threshold FIXO (0.5/10.0) no OOS da mesma janela para comparar
        fix_metrics = _run_fixed_params(
            data["prices"], data["regime"], data["dxy_pct"], data["vix_h4"],
            start=w["test_start"], end=w["test_end"],
            label=f"fix_oos_w{i+1}",
        )
        diff = oos_metrics['sharpe'] - fix_metrics['sharpe']
        melhor = "sweep" if diff > 0.05 else "fixo" if diff < -0.05 else "empate"
        print(f"    [FIXO] DXY=0.5%  VIX=10.0%  "
              f"Sharpe={fix_metrics['sharpe']:.2f}  "
              f"({melhor})")

        rows.append({
            "janela": i + 1,
            "is_periodo": f"{w['train_start']}->{w['train_end']}",
            "oos_periodo": f"{w['test_start']}->{w['test_end']}",
            "is_best_dxy": best["dxy"],
            "is_best_vix": best["vix"],
            "is_best_sharpe": round(best["sharpe"], 3),
            "is_best_ret": round(best["ret"], 1),
            "is_best_dd": round(best["dd"], 1),
            "oos_sweep_sharpe": round(oos_metrics['sharpe'], 3),
            "oos_sweep_ret": round(oos_metrics['total_return_pct'], 1),
            "oos_sweep_dd": round(oos_metrics['max_dd_pct'], 1),
            "oos_fixo_sharpe": round(fix_metrics['sharpe'], 3),
            "oos_fixo_ret": round(fix_metrics['total_return_pct'], 1),
            "oos_fixo_dd": round(fix_metrics['max_dd_pct'], 1),
            "melhor": melhor,
        })

    return rows


# ═════════════════════════════ RELATÓRIO ═════════════════════════════
def _fmt_tabela(headers: list[str], rows: list[dict]) -> str:
    if not rows:
        return "(sem dados)"
    lines = []
    keys = list(rows[0].keys())
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for r in rows:
        vals = []
        for h in headers:
            # match key
            found = None
            for k in keys:
                if k.lower() == h.lower() or k.lower().replace("_", "") == h.lower().replace("_", ""):
                    found = r.get(k, "")
                    break
            if found is None:
                found = r.get(h, "")
            vals.append(str(found))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def gerar_relatorio(result_fixo: list[dict],
                    result_sweep: list[dict],
                    result_sem_sinal: list[dict] | None = None) -> str:
    lines = []

    lines.append("# WALK-FORWARD VALIDATION")
    lines.append(f"**Gerado em:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC")
    lines.append("")
    lines.append("## Objetivo")
    lines.append("Validar que os parametros otimizados do LiquidityStressSignal ")
    lines.append("(**DXY=0.5%, VIX=10.0%**) nao sao overfit no periodo completo,")
    lines.append("testando seu desempenho fora-da-amostra (OOS) em janelas sequenciais.")
    lines.append("")

    # ── Resumo do período ──
    lines.append("## Periodo Analisado")
    data = _ensure_data()
    all_idx = data["common_h4"]
    lines.append(f"- Barras H4 disponiveis: {len(all_idx)}")
    lines.append(f"- Periodo completo: {all_idx[0].date()} -> {all_idx[-1].date()}")
    n_windows = len(result_fixo) if result_fixo else 0
    lines.append(f"- Janelas walk-forward: {n_windows}")
    lines.append("")

    # ── Validação 1: Parâmetros Fixos ──
    lines.append("## Validacao 1: Parametros Fixos em OOS")
    lines.append("Testa os parametros **DXY=0.5%, VIX=10.0%** em cada janela, ")
    lines.append("comparando desempenho IS (treino) vs OOS (teste).")
    lines.append("")
    lines.append("*Criterio: se Sharpe OOS > 0.8 na maioria das janelas e "
                 "o decaimento medio e pequeno, os parametros sao robustos.*")
    lines.append("")

    if result_fixo:
        lines.append("### Tabela por Janela")
        lines.append("")
        lines.append(_fmt_tabela(
            ["Janela", "IS Periodo", "OOS Periodo",
             "IS Sharpe", "IS Ret%", "IS DD%",
             "OOS Sharpe", "OOS Ret%", "OOS DD%",
             "Decaimento"],
            [dict(r, **{"janela": str(r["janela"]),
                        "is_sharpe": f"{r['is_sharpe']:.2f}",
                        "is_ret_pct": f"{r['is_ret_pct']:+.1f}",
                        "is_dd_pct": f"{r['is_dd_pct']:.1f}",
                        "oos_sharpe": f"{r['oos_sharpe']:.2f}",
                        "oos_ret_pct": f"{r['oos_ret_pct']:+.1f}",
                        "oos_dd_pct": f"{r['oos_dd_pct']:.1f}",
                        "sharpe_decay": f"{r['sharpe_decay']:+.2f}"})
             for r in result_fixo]
        ))
        lines.append("")

        # Estatísticas agregadas
        is_sharpes = [r["is_sharpe"] for r in result_fixo]
        oos_sharpes = [r["oos_sharpe"] for r in result_fixo]
        decays = [r["sharpe_decay"] for r in result_fixo]
        oos_acima_08 = sum(1 for s in oos_sharpes if s > 0.8)
        oos_acima_06 = sum(1 for s in oos_sharpes if s > 0.6)

        lines.append("### Estatisticas Agregadas")
        lines.append(f"- **Sharpe IS medio:** {np.mean(is_sharpes):.2f}")
        lines.append(f"- **Sharpe OOS medio:** {np.mean(oos_sharpes):.2f}")
        lines.append(f"- **Decaimento medio:** {np.mean(decays):+.2f}")
        lines.append(f"- **Janelas com OOS Sharpe > 0.8:** {oos_acima_08}/{len(result_fixo)}")
        lines.append(f"- **Janelas com OOS Sharpe > 0.6:** {oos_acima_06}/{len(result_fixo)}")
        lines.append(f"- **Menor Sharpe OOS:** {min(oos_sharpes):.2f}")
        lines.append(f"- **Maior Sharpe OOS:** {max(oos_sharpes):.2f}")
        lines.append("")

        # Veredito Validação 1
        decay_medio = np.mean(decays)
        oos_medio = np.mean(oos_sharpes)
        if oos_medio >= 0.8 and decay_medio > -0.3:
            v1 = "✅ **ROBUSTO.** Os parametros generalizam bem fora-da-amostra."
        elif oos_medio >= 0.6 and decay_medio > -0.5:
            v1 = "⚠️ **ACEITAVEL.** Desempenho OOS razoavel, mas ha janelas com degradacao."
        else:
            v1 = "❌ **OVERFIT.** Os parametros nao generalizam para dados nao vistos."
        lines.append(f"**Veredito:** {v1}")
        lines.append("")
    else:
        lines.append("_(dados nao disponiveis)_")
        lines.append("")

    # ── Baseline: Sem Sinal ──
    if result_sem_sinal:
        lines.append("## Baseline: LiquidityStress DESATIVADO")
        lines.append("Compara o desempenho OOS com sinal (DXY=0.5%, VIX=10.0%) vs ")
        lines.append("sem sinal (thresholds inatingiveis DXY=99%, VIX=99%).")
        lines.append("")
        lines.append("*Se o sinal adiciona valor, o Sharpe com sinal deve ser ")
        lines.append("superior ao sem sinal na maioria das janelas.*")
        lines.append("")
        lines.append("### Tabela por Janela")
        lines.append("")
        lines.append(_fmt_tabela(
            ["Janela", "OOS Periodo",
             "Com Sinal Sharpe", "Com Sinal Ret%",
             "Sem Sinal Sharpe", "Sem Sinal Ret%",
             "Ganho Sharpe"],
            [dict(r, **{"janela": str(r["janela"]),
                        "oos_sharpe_sem": f"{r['oos_sharpe_sem']:.2f}",
                        "oos_ret_sem": f"{r['oos_ret_sem']:+.1f}%",
                        "ganho_sharpe": f"{r['ganho_sharpe']:+.2f}"})
             for r in result_sem_sinal]
        ))
        lines.append("")

        # Agregado sem sinal
        ganhos = [r["ganho_sharpe"] for r in result_sem_sinal]
        n_ganho = sum(1 for g in ganhos if g > 0)
        n_total_sem = len(result_sem_sinal)
        lines.append("### Estatisticas")
        lines.append(f"- **Ganho medio de Sharpe:** {np.mean(ganhos):+.2f}")
        lines.append(f"- **Janelas onde sinal > sem sinal:** {n_ganho}/{n_total_sem}")
        if n_ganho >= n_total_sem * 0.6 and np.mean(ganhos) > 0.1:
            bl = "✅ **SINAL AGREGA VALOR.** O LiquidityStress melhora o Sharpe "
            bl += "consistentemente fora-da-amostra."
        elif np.mean(ganhos) > 0:
            bl = "⚠️ **SINAL MARGINAL.** O LiquidityStress ajuda na media, mas "
            bl += "nem sempre. Pode valer refinar."
        else:
            bl = "❌ **SINAL NAO AGREGA VALOR.** O baseline sem LiquidityStress "
            bl += "e melhor ou equivalente na maioria das janelas."
        lines.append(f"**Veredito:** {bl}")
        lines.append("")

    # ── Validação 2: Sweep por Janela ──
    lines.append("## Validacao 2: Sweep por Janela")
    lines.append("Para cada janela, varre **todos os thresholds** no IS e testa ")
    lines.append("o melhor encontrado no OOS. Compara com o threshold fixo 0.5/10.0.")
    lines.append("")
    lines.append("*Se os thresholds 'vencedores' por janela se agrupam ao redor ")
    lines.append("de DXY=0.5% e VIX=10.0%, o sweep original nao foi overfit.*")
    lines.append("")

    if result_sweep:
        lines.append("### Tabela por Janela")
        lines.append("")
        lines.append(_fmt_tabela(
            ["Janela", "IS Periodo", "OOS Periodo",
             "Melhor IS", "IS Sharpe",
             "OOS Sweep Sharpe", "OOS Sweep Ret%",
             "OOS Fixo Sharpe", "OOS Fixo Ret%",
             "Melhor"],
            [dict(r, **{"janela": str(r["janela"]),
                        "is_best_dxy": f"DXY={r['is_best_dxy']}% VIX={r['is_best_vix']}%",
                        "is_best_sharpe": f"{r['is_best_sharpe']:.2f}",
                        "oos_sweep_sharpe": f"{r['oos_sweep_sharpe']:.2f}",
                        "oos_sweep_ret": f"{r['oos_sweep_ret']:+.1f}%",
                        "oos_fixo_sharpe": f"{r['oos_fixo_sharpe']:.2f}",
                        "oos_fixo_ret": f"{r['oos_fixo_ret']:+.1f}%"})
             for r in result_sweep]
        ))
        lines.append("")

        # Estatísticas de thresholds
        dxy_vals = [r["is_best_dxy"] for r in result_sweep]
        vix_vals = [r["is_best_vix"] for r in result_sweep]
        lines.append("### Distribuicao dos Thresholds Vencedores por Janela")
        for d, v in zip(dxy_vals, vix_vals):
            match = "★" if (abs(d - 0.5) < 0.01 and abs(v - 10.0) < 0.01) else " "
            lines.append(f"- Janela {len([x for x in dxy_vals[:dxy_vals.index(d)+1]])}: "
                         f"DXY={d}%  VIX={v}%  {match}")
        lines.append("")

        # Quantas janelas tiveram DXY=0.5 como vencedor?
        # (Considerando que o grid tem 0.1, 0.2, 0.3, 0.5, 0.75)
        n_proximo = sum(1 for d, v in zip(dxy_vals, vix_vals)
                        if abs(d - 0.5) < 0.15 and v >= 7.0)
        n_exato = sum(1 for d, v in zip(dxy_vals, vix_vals)
                      if abs(d - 0.5) < 0.01 and abs(v - 10.0) < 0.01)
        lines.append(f"- **Thresholds exatos (DXY=0.5%, VIX=10.0%) vencedores:** "
                     f"{n_exato}/{len(result_sweep)} janelas")
        lines.append(f"- **Thresholds proximos (DXY≈0.5%, VIX≈10.0%):** "
                     f"{n_proximo}/{len(result_sweep)} janelas")
        lines.append("")

        # Comparação: sweep vs fixo no OOS
        oos_sweep_med = np.mean([r["oos_sweep_sharpe"] for r in result_sweep])
        oos_fixo_med = np.mean([r["oos_fixo_sharpe"] for r in result_sweep])
        lines.append(f"### Comparacao no OOS")
        lines.append(f"- **Media Sweep OOS:** {oos_sweep_med:.2f}")
        lines.append(f"- **Media Fixo OOS:** {oos_fixo_med:.2f}")
        diff = oos_sweep_med - oos_fixo_med
        if diff > 0.1:
            lines.append(f"- O sweep por janela supera o fixo em {diff:+.2f} — "
                         f"pode haver overfit no parametro unico.")
            lines.append(f"- Sugestao: usar sweep rolling (re-otimizar a cada 3 meses).")
        elif diff < -0.1:
            lines.append(f"- O parametro fixo supera o sweep em {diff:+.2f} — ")
            lines.append(f"  forte evidencia contra overfit. 0.5/10.0 e robusto.")
        else:
            lines.append(f"- Praticamente empatados ({diff:+.2f}) — ")
            lines.append(f"  o parametro fixo 0.5/10.0 e tao bom quanto re-otimizar.")
        lines.append("")

        if n_exato >= len(result_sweep) * 0.5:
            v2 = "✅ **ROBUSTO.** Os thresholds 0.5/10.0 vencem na maioria das janelas."
        elif n_proximo >= len(result_sweep) * 0.5:
            v2 = "⚠️ **PARCIALMENTE ROBUSTO.** Os thresholds variam mas ficam na vizinhanca."
        else:
            v2 = "❌ **OVERFIT.** Cada janela elege thresholds diferentes — sweep geral e instavel."
        lines.append(f"**Veredito:** {v2}")
        lines.append("")
    else:
        lines.append("_(dados nao disponiveis)_")
        lines.append("")

    # ── Conclusão Final ──
    lines.append("## Conclusao Final")
    lines.append("")
    if result_fixo and result_sweep:
        oos_medio_final = np.mean([r["oos_sharpe"] for r in result_fixo])
        n_positivo = sum(1 for r in result_fixo if r["oos_sharpe"] > 0.6)
        n_total = len(result_fixo)

        lines.append(f"### Metricas Consolidadas")
        lines.append(f"- **OOS Sharpe medio (parametros fixos):** {oos_medio_final:.2f}")
        lines.append(f"- **Janelas com Sharpe > 0.6:** {n_positivo}/{n_total}")
        lines.append(f"- **Decaimento medio IS->OOS:** {np.mean([r['sharpe_decay'] for r in result_fixo]):+.2f}")
        lines.append("")

        if (oos_medio_final >= 0.7 and n_positivo >= n_total * 0.6
                and np.mean([r['sharpe_decay'] for r in result_fixo]) > -0.4):
            conclusao = (
                "✅ **OS PARAMETROS SAO ROBUSTOS.**\n\n"
                "O LiquidityStressSignal com DXY=0.5% e VIX=10.0% apresenta desempenho "
                "consistente fora-da-amostra em janelas sequenciais:\n"
                f"- Sharpe OOS medio de {oos_medio_final:.2f}\n"
                f"- Decaimento medio de apenas {np.mean([r['sharpe_decay'] for r in result_fixo]):+.2f}\n"
                f"- Boa estabilidade dos thresholds vencedores por janela\n\n"
                "Pode seguir para producao (dry-run) com os parametros atuais "
                "sem medo de overfit."
            )
        elif (oos_medio_final >= 0.5 and n_positivo >= n_total * 0.4
              and np.mean([r['sharpe_decay'] for r in result_fixo]) > -0.6):
            conclusao = (
                "⚠️ **PARCIALMENTE ROBUSTO — USAR COM CAUTELA.**\n\n"
                "O desempenho OOS e razoavel, mas ha variacao significativa entre janelas. "
                "Recomendacoes:\n"
                "- Usar os parametros 0.5/10.0 mas monitorar o drawdown de perto\n"
                "- Considerar re-otimizacao periodica (a cada 3-6 meses)\n"
                "- Implementar um stop-loss de regime (se Sharpe rolling cair de 0.5, pausar)"
            )
        else:
            conclusao = (
                "❌ **OVERFIT DETECTADO — NAO USAR EM PRODUCAO.**\n\n"
                "Os parametros 0.5/10.0 nao resistem a validacao walk-forward. "
                "Recomendacoes:\n"
                "- Remover o LiquidityStressSignal ou usar thresholds mais conservadores\n"
                "- Tentar parametros menos agressivos (ex: DXY=0.75%, VIX=15%)\n"
                "- Considerar que o flight-to-dollar pode ser raro demais pra otimizar"
            )
        lines.append(f"### Veredito Final\n{conclusao}")
    else:
        lines.append("_(dados insuficientes para conclusao)_")
    lines.append("")

    lines.append("---")
    lines.append("_Gerado por walk_forward_validate.py_")

    return "\n".join(lines)


# ═════════════════════════════ MAIN ═════════════════════════════
def main():
    print("=" * 70)
    print("  WALK-FORWARD VALIDATION — LiquidityStressSignal")
    print(f"  Parametros: DXY_LIQUIDITY_STRESS_UP_PCT = {C.DXY_LIQUIDITY_STRESS_UP_PCT}%")
    print(f"              VIX_LIQUIDITY_STRESS_UP_PCT  = {C.VIX_LIQUIDITY_STRESS_UP_PCT}%")
    print("=" * 70)

    # 1. Dados
    data = _ensure_data()
    all_idx = data["common_h4"]
    n_total = len(all_idx)

    # 2. Janelas
    windows = _build_windows(
        all_idx,
        train_bars=C.WF_TRAIN_BARS,
        test_bars=C.WF_TEST_BARS,
        step_bars=C.WF_STEP_BARS,
    )
    print(f"\nJanelas walk-forward: {len(windows)}")
    print(f"  IS:  {C.WF_TRAIN_BARS} barras (~{C.WF_TRAIN_BARS//6:.0f} dias)")
    print(f"  OOS: {C.WF_TEST_BARS} barras (~{C.WF_TEST_BARS//6:.0f} dias)")
    print(f"  Step: {C.WF_STEP_BARS} barras (rolamento)")
    print(f"  Cobertura: ~{len(windows)*C.WF_TEST_BARS/n_total:.0%} do periodo total")

    # 3. Validação 1: Parâmetros fixos (rápida)
    result_fixo, result_sem_sinal = validate_fixed_params(data, windows)

    # 4. Validação 2: Sweep por janela (mais lenta)
    result_sweep = validate_sweep_per_window(data, windows)

    # 5. Relatório
    md = gerar_relatorio(result_fixo, result_sweep, result_sem_sinal)
    report_path = C.REPORTS_DIR / "WALK_FORWARD.md"
    report_path.write_text(md, encoding="utf-8")
    print(f"\n{'='*70}")
    print(f"  Relatorio salvo em {report_path}")
    print(f"{'='*70}")

    # Resumo rápido
    print(f"\n  RESUMO:")
    if result_fixo:
        oos_sharpes = [r["oos_sharpe"] for r in result_fixo]
        print(f"    OOS Sharpe medio: {np.mean(oos_sharpes):.2f}")
        print(f"    OOS Sharpe min:   {min(oos_sharpes):.2f}")
        print(f"    OOS Sharpe max:   {max(oos_sharpes):.2f}")
        n_ok = sum(1 for s in oos_sharpes if s > 0.6)
        print(f"    Janelas com Sharpe > 0.6: {n_ok}/{len(result_fixo)}")
        if result_sem_sinal:
            ganhos = [r["ganho_sharpe"] for r in result_sem_sinal]
            print(f"    Ganho medio sobre baseline: {np.mean(ganhos):+.2f} Sharpe")
    print(f"  Veja reports/WALK_FORWARD.md para detalhes.")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()

__all__ = ["_build_windows", "validate_fixed_params", "validate_sweep_per_window",
           "gerar_relatorio", "main"]
