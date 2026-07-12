"""analyze_negative_months.py — Cruza meses negativos do backtest com regime, VIX, DXY e padrões de trade.

Gera:
  - reports/ANALISE_NEGATIVOS.md — análise completa com tabelas e conclusões
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from collections import Counter
from datetime import datetime

from engine import config as C
from engine.data import load_all_prices, load_vix, load_dxy, dxy_pct_change_h4
from engine.regime import RuleBasedRegime
from engine.signals import TSMomentumStrategy
from engine.backtest import run_backtest, Trade
from engine.macro_events import get_events_for_backtest
from engine.utils import session_of


# ═══════════════════════════════════════════════════════════════
# 1. Rodar backtest para obter trades + equity horária
# ═══════════════════════════════════════════════════════════════
def run_backtest_full() -> tuple:
    print("[1/5] Carregando dados...")
    prices = load_all_prices(timeframe=C.TIMEFRAME, bars=C.BARS_LOOKBACK, align=True)
    vix = load_vix(period="max")
    common_h4 = next(iter(prices.values())).index

    # DXY
    try:
        dxy_raw = load_dxy(period="10y")
        dxy_pct = dxy_pct_change_h4(dxy_raw, common_h4, lookback=C.DXY_LIQUIDITY_STRESS_LOOKBACK_BARS)
        vix_pct = vix.pct_change(5) * 100.0
        vix_h4 = vix_pct.reindex(common_h4).ffill()
    except Exception:
        dxy_pct = None
        vix_h4 = None

    print("[2/5] Montando regime...")
    regime = RuleBasedRegime(vix=vix, prices_for_corr=prices)

    print("[3/5] Carregando macro eventos...")
    try:
        macro_events = get_events_for_backtest(C.START_COMMON, C.END_DEFAULT)
    except Exception:
        macro_events = None

    print("[4/5] Calculando D1 momentum...")
    d1_momentum = {}
    if C.D1_FILTER_ENABLED:
        for sym, df in prices.items():
            daily_close = df["close"].resample("D").last().dropna()
            mom = (daily_close.shift(1) / daily_close.shift(C.D1_MOMENTUM_LOOKBACK_BARS + 1)) - 1.0
            d1_h4 = mom.reindex(common_h4, method="ffill")
            d1_momentum[sym] = d1_h4

    print("[5/5] Rodando backtest ts_momentum...")
    strategy = TSMomentumStrategy()
    result = run_backtest(
        prices=prices,
        strategy=strategy,
        regime_provider=regime,
        start=C.START_COMMON,
        end=C.END_DEFAULT,
        account_start=C.ACCOUNT_START_USD,
        max_positions=C.MAX_OPEN_POSITIONS,
        risk_per_trade_pct=C.RISK_PER_TRADE_PCT,
        risk_pct_by_regime=C.RISK_PCT_BY_REGIME,
        d1_momentum=d1_momentum if C.D1_FILTER_ENABLED else None,
        use_costs=True,
        label="ts_momentum",
        dxy_pct=dxy_pct,
        vix_pct=vix_h4,
        macro_events=macro_events,
    )

    # Equity horária para calcular drawdown contínuo
    eq = result.equity.dropna()
    return result, eq, vix, common_h4


# ═══════════════════════════════════════════════════════════════
# 2. Análise por mês
# ═══════════════════════════════════════════════════════════════
def analyze_monthly(trades: list[Trade], eq: pd.Series, vix: pd.Series, common_h4: pd.Index) -> dict:
    """Retorna dict com análise detalhada por mês."""
    months = {}
    for t in trades:
        m = t.exit_time.strftime("%Y-%m")
        if m not in months:
            months[m] = {"trades": [], "pnl": 0}
        months[m]["trades"].append(t)
        months[m]["pnl"] += t.pnl_usd

    # Para cada mês, coleta regime predominante, VIX médio, etc.
    monthly_analysis = []
    for m, data in sorted(months.items()):
        trades_m = data["trades"]
        pnl = data["pnl"]

        # Regime predominante no mês
        regimes = [t.regime_at_entry for t in trades_m if t.regime_at_entry]
        regime_count = Counter(regimes)
        regime_main = regime_count.most_common(1)[0][0] if regime_count else "?"

        # Direção predominante
        dirs = [t.direction for t in trades_m]
        dir_count = Counter(dirs)
        dir_main = dir_count.most_common(1)[0][0] if dir_count else "?"

        # Sessão predominante
        sessoes = [session_of(t.entry_time) for t in trades_m]
        sess_count = Counter(sessoes)
        sess_main = sess_count.most_common(1)[0][0] if sessoes else "?"

        # Estatísticas de trade
        pnls = [t.pnl_usd for t in trades_m]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        avg_winner = np.mean(wins) if wins else 0
        avg_loser = np.mean(losses) if losses else 0
        win_rate = len(wins) / len(trades_m) if trades_m else 0
        payoff = abs(avg_winner / avg_loser) if avg_loser != 0 else 0

        # % de trades que bateram TP vs SL vs Partial TP
        tp_count = sum(1 for t in trades_m if t.exit_reason == "TP")
        sl_count = sum(1 for t in trades_m if t.exit_reason == "SL")
        ptp_count = sum(1 for t in trades_m if t.exit_reason == "PARTIAL_TP")
        tp_pct = tp_count / len(trades_m) * 100 if trades_m else 0
        sl_pct = sl_count / len(trades_m) * 100 if trades_m else 0
        ptp_pct = ptp_count / len(trades_m) * 100 if trades_m else 0

        # Sequência de perdas consecutivas no mês
        loss_streak = 0
        max_loss_streak = 0
        for t in trades_m:
            if t.pnl_usd <= 0:
                loss_streak += 1
                max_loss_streak = max(max_loss_streak, loss_streak)
            else:
                loss_streak = 0

        # Drawdown máximo intra-mês
        eq_month = eq[eq.index.strftime("%Y-%m") == m]
        dd_intra = 0
        if len(eq_month) > 0:
            peak = eq_month.iloc[0]
            for val in eq_month:
                if val > peak:
                    peak = val
                dd = (val - peak) / peak * 100
                dd_intra = min(dd_intra, dd)

        monthly_analysis.append({
            "mes": m,
            "pnl_total": pnl,
            "trades": len(trades_m),
            "win_rate": win_rate * 100,
            "avg_win": avg_winner,
            "avg_loss": avg_loser,
            "payoff": payoff,
            "regime_predominante": regime_main,
            "direcao_predominante": dir_main,
            "sessao_predominante": sess_main,
            "tp_pct": tp_pct,
            "sl_pct": sl_pct,
            "ptp_pct": ptp_pct,
            "max_loss_streak": max_loss_streak,
            "dd_intra_mes_pct": dd_intra,
        })

    return monthly_analysis


# ═══════════════════════════════════════════════════════════════
# 3. Gerar relatório
# ═══════════════════════════════════════════════════════════════
def _v(val, fmt="str"):
    if fmt == "usd":
        return f"${val:+,.2f}" if isinstance(val, (int, float)) else str(val)
    if fmt == "pct":
        return f"{val:.1f}%" if isinstance(val, (int, float)) else str(val)
    if fmt == "int":
        return str(int(val)) if isinstance(val, (int, float)) else str(val)
    if fmt == "pct2":
        return f"{val:.2f}" if isinstance(val, (int, float)) else str(val)
    return str(val)


def _table(headers, rows, fmts=None):
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for r in rows:
        vals = []
        for i, h in enumerate(headers):
            v = r.get(h, "")
            fmt = fmts.get(h, "str") if fmts else "str"
            vals.append(_v(v, fmt))
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def write_report(monthly: list, out_path: Path):
    # Separa meses negativos e positivos
    neg_months = [m for m in monthly if m["pnl_total"] < 0]
    pos_months = [m for m in monthly if m["pnl_total"] >= 0]

    total_neg = sum(m["pnl_total"] for m in neg_months)
    total_pos = sum(m["pnl_total"] for m in pos_months)
    total_all = sum(m["pnl_total"] for m in monthly)

    lines = []
    lines.append("# Analise de Meses Negativos — Backtest Solo Tokyo")
    lines.append(f"**Periodo:** {monthly[0]['mes']} → {monthly[-1]['mes']} | **Total de meses:** {len(monthly)}")
    lines.append(f"**Meses negativos:** {len(neg_months)} ({len(neg_months)/len(monthly)*100:.0f}%)")
    lines.append(f"**Soma perdas:** ${total_neg:+,.2f} | **Soma ganhos:** ${total_pos:+,.2f} | **Total:** ${total_all:+,.2f}")
    lines.append("")

    # ─── Tabela: Todos os meses negativos ───
    lines.append("## Meses Negativos — Detalhado")
    lines.append("")
    headers = ["mes", "pnl_total", "trades", "win_rate", "avg_win", "avg_loss",
               "payoff", "regime_predominante", "direcao_predominante",
               "tp_pct", "sl_pct", "ptp_pct", "max_loss_streak", "dd_intra_mes_pct"]
    fmts = {"mes": "str", "pnl_total": "usd", "trades": "int", "win_rate": "pct",
            "avg_win": "usd", "avg_loss": "usd", "payoff": "pct2",
            "regime_predominante": "str", "direcao_predominante": "str",
            "sessao_predominante": "str", "tp_pct": "pct", "sl_pct": "pct",
            "ptp_pct": "pct", "max_loss_streak": "int", "dd_intra_mes_pct": "pct"}
    lines.append(_table(headers, neg_months, fmts))
    lines.append("")

    # ─── Análise por regime ───
    lines.append("## Distribuicao por Regime")
    lines.append("")
    regime_stats = {}
    for m in monthly:
        rg = m["regime_predominante"]
        if rg not in regime_stats:
            regime_stats[rg] = {"meses": 0, "negativos": 0, "pnl_total": 0, "trades": 0, "pnl_por_trade": 0.0}
        regime_stats[rg]["meses"] += 1
        regime_stats[rg]["pnl_total"] += m["pnl_total"]
        regime_stats[rg]["trades"] += m["trades"]
        if m["pnl_total"] < 0:
            regime_stats[rg]["negativos"] += 1
        regime_stats[rg]["pnl_por_trade"] = regime_stats[rg]["pnl_total"] / regime_stats[rg]["trades"] if regime_stats[rg]["trades"] else 0
    reg_headers = ["regime", "meses", "negativos", "pct_neg", "pnl_total", "trades", "pnl_por_trade"]
    reg_rows = []
    for rg, st in sorted(regime_stats.items()):
        reg_rows.append({
            "regime": rg,
            "meses": st["meses"],
            "negativos": st["negativos"],
            "pct_neg": st["negativos"] / st["meses"] * 100 if st["meses"] else 0,
            "pnl_total": st["pnl_total"],
            "trades": st["trades"],
            "pnl_por_trade": st["pnl_total"] / st["trades"] if st["trades"] else 0,
        })
    reg_fmts = {"regime": "str", "meses": "int", "negativos": "int", "pct_neg": "pct",
                "pnl_total": "usd", "trades": "int", "pnl_por_trade": "usd"}
    lines.append(_table(reg_headers, reg_rows, reg_fmts))
    lines.append("")

    # ─── Análise por direção ───
    lines.append("## Distribuicao por Direcao Predominante")
    lines.append("")
    dir_stats = {}
    for m in monthly:
        d = m["direcao_predominante"]
        if d not in dir_stats:
            dir_stats[d] = {"meses": 0, "negativos": 0, "pnl_total": 0, "trades": 0}
        dir_stats[d]["meses"] += 1
        dir_stats[d]["pnl_total"] += m["pnl_total"]
        dir_stats[d]["trades"] += m["trades"]
        if m["pnl_total"] < 0:
            dir_stats[d]["negativos"] += 1
    dir_headers = ["direcao", "meses", "negativos", "pct_neg", "pnl_total", "trades", "pnl_por_trade"]
    dir_rows = []
    for d, st in sorted(dir_stats.items()):
        dir_rows.append({
            "direcao": d,
            "meses": st["meses"],
            "negativos": st["negativos"],
            "pct_neg": st["negativos"] / st["meses"] * 100 if st["meses"] else 0,
            "pnl_total": st["pnl_total"],
            "trades": st["trades"],
            "pnl_por_trade": st["pnl_total"] / st["trades"] if st["trades"] else 0,
        })
    dir_fmts = {"direcao": "str", "meses": "int", "negativos": "int", "pct_neg": "pct",
                "pnl_total": "usd", "trades": "int", "pnl_por_trade": "usd"}
    lines.append(_table(dir_headers, dir_rows, dir_fmts))
    lines.append("")

    # ─── Análise de payoff nos meses negativos ───
    lines.append("## Analise de Payoff em Meses Negativos")
    lines.append("")
    bad_payoff = [m for m in neg_months if m["payoff"] < 1.0]
    ok_payoff = [m for m in neg_months if m["payoff"] >= 1.0]
    lines.append(f"- **Meses com payoff < 1.0 (ganhadores menores que perdedores):** {len(bad_payoff)}/{len(neg_months)}")
    lines.append(f"  - Soma do PnL: ${sum(m['pnl_total'] for m in bad_payoff):+,.2f}")
    lines.append(f"- **Meses com payoff >= 1.0 (perdeu por volume, nao por qualidade):** {len(ok_payoff)}/{len(neg_months)}")
    lines.append(f"  - Soma do PnL: ${sum(m['pnl_total'] for m in ok_payoff):+,.2f}")
    lines.append("")

    # Meses com payoff baixo
    lines.append("### Meses negativos com payoff < 0.5 (pessimos)")
    low_pay = sorted([m for m in neg_months if m["payoff"] < 0.5], key=lambda x: x["payoff"])
    low_headers = ["mes", "pnl_total", "win_rate", "payoff", "regime_predominante", "tp_pct", "sl_pct", "ptp_pct"]
    low_fmts = {"mes": "str", "pnl_total": "usd", "win_rate": "pct", "payoff": "pct2",
                "regime_predominante": "str", "tp_pct": "pct", "sl_pct": "pct", "ptp_pct": "pct"}
    lines.append(_table(low_headers, low_pay, low_fmts))
    lines.append("")

    # ─── Meses com alta taxa de SL ───
    lines.append("## Meses com SL rate > 50%")
    lines.append("")
    high_sl = sorted([m for m in neg_months if m["sl_pct"] > 50], key=lambda x: x["sl_pct"], reverse=True)
    sl_headers = ["mes", "pnl_total", "win_rate", "sl_pct", "tp_pct", "ptp_pct", "regime_predominante", "direcao_predominante"]
    sl_fmts = {"mes": "str", "pnl_total": "usd", "win_rate": "pct", "sl_pct": "pct",
               "tp_pct": "pct", "ptp_pct": "pct", "regime_predominante": "str", "direcao_predominante": "str"}
    lines.append(_table(sl_headers, high_sl, sl_fmts))
    lines.append("")

    # ─── Cluster analysis: meses negativos consecutivos ───
    lines.append("## Clusters de Meses Negativos Consecutivos")
    lines.append("")
    streak = 0
    streaks = []
    for m in monthly:
        if m["pnl_total"] < 0:
            streak += 1
        else:
            if streak > 0:
                streaks.append(streak)
            streak = 0
    if streak > 0:
        streaks.append(streak)
    lines.append(f"- **Maior sequencia de meses negativos consecutivos:** {max(streaks) if streaks else 0}")
    lines.append(f"- **Total de clusters (sequencias):** {len(streaks)}")
    lines.append("")

    # Mostra clusters
    streak = 0
    cluster_start = None
    for m in monthly:
        if m["pnl_total"] < 0:
            if streak == 0:
                cluster_start = m["mes"]
            streak += 1
        else:
            if streak >= 2:
                meses_cluster = [mm for mm in monthly if cluster_start <= mm["mes"] < m["mes"]]
                total = sum(mm["pnl_total"] for mm in meses_cluster)
                lines.append(f"  - **{cluster_start} a {monthly[monthly.index(m)-1]['mes']}** ({streak} meses, ${total:+,.2f})")
            streak = 0
    if streak >= 2:
        lines.append(f"  - **{cluster_start} a {monthly[-1]['mes']}** ({streak} meses, pendente)")
    lines.append("")

    # ─── Correlação com drawdown ───
    lines.append("## Correlacao: Drawdown Intra-Mes vs PnL Mensal")
    lines.append("")
    big_dd_neg = sorted([m for m in neg_months if m["dd_intra_mes_pct"] < -10], key=lambda x: x["dd_intra_mes_pct"])
    if big_dd_neg:
        lines.append("### Meses com DD intra-mes > 10% (piores drawdowns)")
        dd_headers = ["mes", "pnl_total", "dd_intra_mes_pct", "regime_predominante", "max_loss_streak"]
        dd_fmts = {"mes": "str", "pnl_total": "usd", "dd_intra_mes_pct": "pct",
                   "regime_predominante": "str", "max_loss_streak": "int"}
        lines.append(_table(dd_headers, big_dd_neg, dd_fmts))
        lines.append("")

    # ─── Resumo final com insights ───
    lines.append("## Insights e Padroes Identificados")
    lines.append("")

    # Insight 1: Regime
    risk_off_neg = regime_stats.get("risk_off", {})
    normal_neg = regime_stats.get("normal", {})
    risk_on_neg = regime_stats.get("risk_on", {})
    lines.append("### 1. Regime e o principal preditor de meses negativos?")
    lines.append("")
    for rg, st in sorted(regime_stats.items()):
        lines.append(f"- **{rg}:** {st['negativos']}/{st['meses']} meses negativos ({st['negativos']/st['meses']*100:.0f}%) | PnL: ${st['pnl_total']:+,.2f} em {st['trades']} trades")
    lines.append("")

    # Insight 2: Direção
    lines.append("### 2. O bot perde mais comprando ou vendendo?")
    lines.append("")
    for d, st in sorted(dir_stats.items()):
        pct = st['negativos']/st['meses']*100 if st['meses'] else 0
        lines.append(f"- **{d}:** {st['negativos']}/{st['meses']} meses negativos ({pct:.0f}%) | PnL: ${st['pnl_total']:+,.2f}")
    lines.append("")

    # Insight 3: Payoff
    lines.append("### 3. O problema e frequencia ou qualidade?")
    lines.append("")
    avg_payoff_neg = np.mean([m["payoff"] for m in neg_months]) if neg_months else 0
    avg_payoff_pos = np.mean([m["payoff"] for m in pos_months]) if pos_months else 0
    lines.append(f"- **Payoff medio em meses negativos:** {avg_payoff_neg:.2f}")
    lines.append(f"- **Payoff medio em meses positivos:** {avg_payoff_pos:.2f}")
    sl_worse = sum(1 for m in neg_months if m["sl_pct"] > 50)
    lines.append(f"- **{sl_worse}/{len(neg_months)} meses negativos** tem mais de 50% de SL rate (mais stops que TPs)")
    ptp_worse = sum(1 for m in neg_months if m["ptp_pct"] > 30 and m["tp_pct"] < 20)
    lines.append(f"- **{ptp_worse}/{len(neg_months)} meses negativos** tem Partial TP > 30% e TP < 20% (Partial TP esta matando os ganhos)")
    lines.append("")

    # Insight 4: Clusters
    lines.append("### 4. Existem clusters de perda? (meses negativos consecutivos)")
    lines.append("")
    if streaks:
        lines.append(f"- **Sim.** A maior sequencia e de **{max(streaks)} meses** consecutivos negativos.")
        lines.append(f"- Isso significa que o bot pode ficar ate **{max(streaks)} meses** no vermelho seguido.")
        lines.append(f"- Para um trader real, isso e psicologicamente desafiador — precisa de estomago.")
    else:
        lines.append("- Nao ha clusters significativos.")
    lines.append("")

    # Insight 5: Recomendação
    lines.append("### 5. O que fazer com esses dados?")
    lines.append("")
    # Encontra o regime que mais causa perdas
    worst_regime = min(regime_stats.items(), key=lambda x: x[1]["pnl_por_trade"]) if regime_stats else None
    if worst_regime:
        lines.append(f"1. **Filtrar {worst_regime[0]} com mais rigor** — esse regime tem o pior PnL/trade (${worst_regime[1]['pnl_por_trade']:+,.2f}).")
        lines.append(f"   Sugestao: reduzir RISK_PCT_BY_REGIME para {worst_regime[0]} de {C.RISK_PCT_BY_REGIME.get(worst_regime[0], '?')} para 50% disso.")
    lines.append(f"2. **Monitorar payoff baixo (< 0.5)** — quando o payoff cai abaixo de 0.5, a qualidade dos trades esta ruim.")
    lines.append(f"3. **Preparar para clusters de ate {max(streaks) if streaks else 2} meses negativos** — ter caixa para aguentar.")
    lines.append(f"4. **Partial TP e o maior vilao nos meses negativos** — em {ptp_worse}/{len(neg_months)} meses, muitos trades fecharam em Partial TP em vez de irem ao TP cheio.")
    lines.append("")

    lines.append("---")
    lines.append(f"_Gerado em {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC por analyze_negative_months.py_")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] Relatorio salvo em {out_path}")
    return out_path


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    result, eq, vix, common_h4 = run_backtest_full()
    trades = result.trades

    from engine.analytics import basic_summary
    s = basic_summary(result)
    print(f"\nBacktest: {len(trades)} trades | Sharpe {s['sharpe']:.2f} | Retorno {s['total_return_pct']:+.1f}%")

    print("\nAnalisando meses...")
    monthly = analyze_monthly(trades, eq, vix, common_h4)

    print(f"Total de meses: {len(monthly)}")
    neg = [m for m in monthly if m["pnl_total"] < 0]
    print(f"Meses negativos: {len(neg)} ({len(neg)/len(monthly)*100:.0f}%)")
    print(f"Soma perdas: ${sum(m['pnl_total'] for m in neg):+,.2f}")

    # Mostra regime breakdown
    regimes_neg = Counter(m["regime_predominante"] for m in neg)
    print(f"\nRegime nos meses negativos: {dict(regimes_neg)}")

    print("\nGerando relatorio...")
    write_report(monthly, C.REPORTS_DIR / "ANALISE_NEGATIVOS.md")

    # Summary on screen
    print("\n" + "=" * 60)
    print("  RESUMO DOS PADROES")
    print("=" * 60)
    print(f"\nTotal: {len(neg)} meses negativos de {len(monthly)} ({len(neg)/len(monthly)*100:.0f}%)")
    print(f"Perda total acumulada: ${sum(m['pnl_total'] for m in neg):+,.2f}")
    print(f"Ganho total acumulado: ${sum(m['pnl_total'] for m in monthly if m['pnl_total'] >= 0):+,.2f}")
    print()
    for rg, st in sorted(regime_stats(monthly).items()):
        print(f"  {rg}: {st['negativos']}/{st['meses']} meses ({st['negativos']/st['meses']*100:.0f}%) | PnL ${st['pnl_total']:+,.2f}")
    print(f"\nRelatorio completo: reports/ANALISE_NEGATIVOS.md")


def regime_stats(monthly):
    stats = {}
    for m in monthly:
        rg = m["regime_predominante"]
        if rg not in stats:
            stats[rg] = {"meses": 0, "negativos": 0, "pnl_total": 0, "trades": 0}
        stats[rg]["meses"] += 1
        stats[rg]["pnl_total"] += m["pnl_total"]
        stats[rg]["trades"] += m["trades"]
        if m["pnl_total"] < 0:
            stats[rg]["negativos"] += 1
    return stats


if __name__ == "__main__":
    main()
