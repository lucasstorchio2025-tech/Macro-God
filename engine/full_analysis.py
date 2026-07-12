"""full_analysis.py — backtest completo + análise detalhada por sessão, mês, par, ganhos/perdas.

Gera:
  - reports/ANALYSIS.md   — relatório completo em markdown
  - reports/analysis_charts.png — gráficos (equity, PnL por mês, por par, drawdown)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from datetime import datetime
from engine import config as C
from engine.data import load_all_prices, load_vix, load_cot_history, load_dxy, dxy_pct_change_h4, load_spy, gold_equity_corr
from engine.regime import RuleBasedRegime
from engine.signals import TSMomentumStrategy, COTContrarianStrategy, LegacyCOTStrategy
from engine.backtest import run_backtest, Trade
from engine.analytics import basic_summary, trade_stats, max_drawdown
from engine.macro_events import get_events_for_backtest
from engine.utils import session_of, ATR_MULT_TO_LABEL


# ═════════════════════════════ ANÁLISE POR CORTE ═════════════════════════════
def analyze_by(trades: list[Trade], key_fn, label: str) -> list[dict]:
    """Agrupa trades por uma chave (mês, símbolo, sessão, regime) e calcula stats."""
    groups: dict[str, list[Trade]] = {}
    for t in trades:
        k = key_fn(t)
        groups.setdefault(k, []).append(t)
    rows = []
    for k, group in sorted(groups.items()):
        pnls = [t.pnl_usd for t in group]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        rows.append({
            label: k,
            "trades": len(group),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(group) * 100 if group else 0,
            "pnl_total": sum(pnls),
            "avg_pnl": np.mean(pnls),
            "best": max(pnls),
            "worst": min(pnls),
            "long": sum(1 for t in group if t.direction == "BUY"),
            "short": sum(1 for t in group if t.direction == "SELL"),
        })
    return rows


# ═════════════════════════════ DISTRIBUIÇÃO DE DURAÇÃO ═════════════════════════════
def duration_buckets(trades: list[Trade]) -> list[dict]:
    buckets = {"<1 dia": 0, "1-3 dias": 0, "3-7 dias": 0, "7-14 dias": 0, "14-30 dias": 0, ">30 dias": 0}
    for t in trades:
        hours = (t.exit_time - t.entry_time).total_seconds() / 3600
        days = hours / 24
        if days < 1:
            buckets["<1 dia"] += 1
        elif days < 3:
            buckets["1-3 dias"] += 1
        elif days < 7:
            buckets["3-7 dias"] += 1
        elif days < 14:
            buckets["7-14 dias"] += 1
        elif days < 30:
            buckets["14-30 dias"] += 1
        else:
            buckets[">30 dias"] += 1
    return [{"duracao": k, "trades": v} for k, v in buckets.items()]


# ═════════════════════════════ SAÍDAS POR MOTIVO ═════════════════════════════
def exit_reasons(trades: list[Trade]) -> list[dict]:
    groups: dict[str, list[Trade]] = {}
    for t in trades:
        groups.setdefault(t.exit_reason, []).append(t)
    rows = []
    for reason in ["TP", "SL", "PARTIAL_TP", "TIME", "REGIME_EXIT", "SIGNAL_FLIP"]:
        group = groups.get(reason, [])
        if not group:
            continue
        pnls = [t.pnl_usd for t in group]
        rows.append({
            "motivo": reason,
            "n": len(group),
            "pct": len(group) / len(trades) * 100 if trades else 0,
            "pnl_total": sum(pnls),
            "avg_pnl": np.mean(pnls),
        })
    return rows


# ═════════════════════════════ TABLES PRA MARKDOWN ═════════════════════════════
def _table(headers: list[str], rows: list[dict]) -> str:
    """Formata lista de dicts como tabela markdown. Usa keys dos dicts (primeira key = primeiro header)."""
    lines = []
    # pega as keys na ordem dos dicts (primeiro dict dita a ordem)
    keys = list(rows[0].keys()) if rows else headers
    # mapeia header -> key (case insensitive)
    key_map = {h.lower(): k for k in keys for h in [k, k.lower()]}
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for r in rows:
        vals = []
        for h in headers:
            # busca key que casa com o header
            found = r.get(h, None)
            if found is None:
                for k, v in r.items():
                    if k.lower() == h.lower() or k.lower().replace("_", "") == h.lower().replace("_", ""):
                        found = v
                        break
            vals.append(found if found is not None else "")
        lines.append("| " + " | ".join(_v(val) for val in vals) + " |")
    return "\n".join(lines)


def _v(x) -> str:
    """Formata valor pra célula de tabela. Strings passam direto."""
    if isinstance(x, str):
        return x
    if isinstance(x, float):
        return f"${x:,.2f}"
    if isinstance(x, int):
        return str(x)
    return str(x)


def _fmt_row(row: dict, schema: dict) -> dict:
    """Aplica formato por coluna. schema = {key: 'int'|'pct'|'usd'|'str'}."""
    out = {}
    for k, v in row.items():
        fmt = schema.get(k, "str")
        if fmt == "int":
            out[k] = str(int(v))
        elif fmt == "pct":
            out[k] = f"{v:.1f}%"
        elif fmt == "usd":
            out[k] = f"${v:,.2f}"
        else:
            out[k] = v
    return out


def _pct(x) -> str:
    return f"{x:.1f}%"


# ═════════════════════════════ CHARTS ═════════════════════════════
def make_charts(result, trades: list[Trade], out_path: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    fig, axes = plt.subplots(3, 2, figsize=(16, 14))
    fig.suptitle(f"Wealth_Engine — Análise Completa: {result.label}", fontsize=14, fontweight="bold")

    # 1. Equity curve
    ax = axes[0, 0]
    eq = result.equity.dropna()
    ax.plot(eq.index, eq.values, linewidth=1.2, color="#2196F3")
    ax.axhline(C.ACCOUNT_START_USD, color="gray", linestyle="--", alpha=0.6)
    ax.set_title("Equity Curve")
    ax.set_ylabel("USD")
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")

    # 2. PnL por mês (barras)
    ax = axes[0, 1]
    monthly = analyze_by(trades, lambda t: t.exit_time.strftime("%Y-%m"), "mes")
    months = [m["mes"] for m in monthly]
    pnls = [m["pnl_total"] for m in monthly]
    colors = ["#4CAF50" if p >= 0 else "#F44336" for p in pnls]
    ax.bar(range(len(months)), pnls, color=colors, width=0.8)
    ax.set_xticks(range(len(months)))
    ax.set_xticklabels(months, rotation=45, ha="right", fontsize=7)
    ax.set_title("P&L por Mês")
    ax.set_ylabel("USD")
    ax.axhline(0, color="black", linewidth=0.5)
    ax.grid(True, alpha=0.3, axis="y")

    # 3. PnL por símbolo (pizza)
    ax = axes[1, 0]
    by_sym = analyze_by(trades, lambda t: t.symbol, "symbol")
    syms = [s["symbol"] for s in by_sym]
    sym_pnls = [s["pnl_total"] for s in by_sym]
    colors_sym = ["#4CAF50" if p >= 0 else "#F44336" for p in sym_pnls]
    wedges, texts, autotexts = ax.pie(
        [abs(p) for p in sym_pnls], labels=syms, autopct=_pct,
        colors=colors_sym, startangle=90, pctdistance=0.85
    )
    for t in autotexts:
        t.set_fontsize(9)
    ax.set_title("P&L por Símbolo (verde=ganho, vermelho=perda)")

    # 4. Drawdown
    ax = axes[1, 1]
    roll_max = eq.cummax()
    dd = (eq - roll_max) / roll_max * 100
    ax.fill_between(dd.index, dd.values, 0, color="#F44336", alpha=0.4)
    ax.plot(dd.index, dd.values, color="#F44336", linewidth=0.7)
    ax.set_title("Drawdown (%)")
    ax.set_ylabel("DD %")
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")

    # 5. Trades por sessão (barras)
    ax = axes[2, 0]
    by_session = analyze_by(trades, lambda t: session_of(t.entry_time), "sessao")
    sess = [s["sessao"] for s in by_session]
    sess_pnls = [s["pnl_total"] for s in by_session]
    colors_s = ["#4CAF50" if p >= 0 else "#F44336" for p in sess_pnls]
    ax.bar(sess, sess_pnls, color=colors_s)
    ax.set_title("P&L por Sessão de Abertura")
    ax.set_ylabel("USD")
    ax.axhline(0, color="black", linewidth=0.5)
    ax.grid(True, alpha=0.3, axis="y")

    # 6. Distribuição de RR realizado (histograma)
    ax = axes[2, 1]
    rrs = [t.rr_realized for t in trades]
    ax.hist(rrs, bins=50, color="#2196F3", edgecolor="white", alpha=0.8)
    ax.axvline(0, color="red", linewidth=1.5, linestyle="--", label="Breakeven")
    ax.axvline(1, color="green", linewidth=1, linestyle=":", label="RR=1 (ganho)")
    ax.axvline(-1, color="red", linewidth=1, linestyle=":", label="RR=-1 (stop)")
    ax.set_title("Distribuição de RR Realizado")
    ax.set_xlabel("RR")
    ax.set_ylabel("Frequência")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out_path


# ═════════════════════════════ RELATÓRIO MARKDOWN ═════════════════════════════
def write_analysis(result, trades: list[Trade], out_path: Path):
    s = basic_summary(result)

    lines = []
    lines.append(f"# ANÁLISE COMPLETA — {result.label}")
    lines.append(f"**Período:** {result.period[0]} → {result.period[1]} | **Trades:** {len(trades)}")
    lines.append(f"**Saldo inicial:** ${C.ACCOUNT_START_USD:.0f} | **Final:** ${s['final_equity']:.2f}")
    lines.append(f"**Retorno:** {s['total_return_pct']:+.1f}% | **CAGR:** {s['cagr_pct']:.1f}%")
    lines.append(f"**Sharpe:** {s['sharpe']:.2f} | **Sortino:** {s['sortino']:.2f}")
    lines.append(f"**Max DD:** {s['max_dd_pct']:.1f}% | **Expectancy:** ${s['expectancy_usd']:.2f}/trade")
    lines.append(f"**Win Rate:** {s['win_rate']:.1%} | **Payoff:** {s['payoff']:.2f}")
    lines.append("")

    # ── Por Mês ──
    lines.append("## 📅 P&L por Mês")
    lines.append("")
    monthly = analyze_by(trades, lambda t: t.exit_time.strftime("%Y-%m"), "mes")
    schema_m = {"mes": "str", "trades": "int", "wins": "int", "losses": "int",
                "win_rate": "pct", "pnl_total": "usd", "avg_pnl": "usd",
                "best": "usd", "worst": "usd"}
    lines.append(_table(
        ["mes", "trades", "wins", "losses", "win_rate", "pnl_total", "avg_pnl", "best", "worst"],
        [_fmt_row(m, schema_m) for m in monthly]
    ))
    lines.append("")

    # running cumulative
    cumul = 0
    lines.append("### Curva Acumulada por Mês")
    for m in monthly:
        cumul += m["pnl_total"]
        bar = "█" * max(1, int(abs(cumul) / 50)) if cumul >= 0 else "░" * max(1, int(abs(cumul) / 50))
        sign = "+" if cumul >= 0 else ""
        lines.append(f"`{m['mes']}` ${cumul:,.0f} {sign} {bar}")
    lines.append("")

    # ── Por ATR Stop Multiplier (regime) ──
    lines.append("## 🎯 Distribuição de Stop por Regime (ATR mult)")
    lines.append("")
    by_stop = analyze_by(trades, lambda t: str(t.atr_stop_mult) if t.atr_stop_mult > 0 else "desconhecido", "atr_mult")
    schema_stop = {"atr_mult": "str", "trades": "int", "wins": "int", "losses": "int",
                    "win_rate": "pct", "pnl_total": "usd", "avg_pnl": "usd"}
    stop_rows = []
    for r in by_stop:
        mult = float(r["atr_mult"])
        # Usa os labels de utils.py (fonte única da verdade)
        label = ATR_MULT_TO_LABEL.get(mult, f"{mult}×ATR")
        stop_rows.append({**r, "atr_mult": label})
    lines.append(_table(
        ["atr_mult", "trades", "wins", "losses", "win_rate", "pnl_total", "avg_pnl"],
        [_fmt_row(r, schema_stop) for r in stop_rows]
    ))
    lines.append("")

    # ── Por Símbolo ──
    lines.append("## 📊 P&L por Símbolo")
    lines.append("")
    by_sym = analyze_by(trades, lambda t: t.symbol, "symbol")
    schema_s = {"symbol": "str", "trades": "int", "wins": "int", "losses": "int",
                "win_rate": "pct", "pnl_total": "usd", "avg_pnl": "usd",
                "long": "int", "short": "int"}
    lines.append(_table(
        ["symbol", "trades", "wins", "losses", "win_rate", "pnl_total", "avg_pnl", "long", "short"],
        [_fmt_row(s, schema_s) for s in by_sym]
    ))
    lines.append("")

    # ── Por Sessão ──
    lines.append("## 🌍 P&L por Sessão (hora de entrada)")
    lines.append("")
    by_session = analyze_by(trades, lambda t: session_of(t.entry_time), "sessao")
    schema_se = {"sessao": "str", "trades": "int", "wins": "int", "losses": "int",
                 "win_rate": "pct", "pnl_total": "usd", "avg_pnl": "usd"}
    lines.append(_table(
        ["sessao", "trades", "wins", "losses", "win_rate", "pnl_total", "avg_pnl"],
        [_fmt_row(s, schema_se) for s in by_session]
    ))
    lines.append("")

    # ── Por Regime ──
    lines.append("## 🔄 P&L por Regime na Entrada")
    lines.append("")
    by_regime = analyze_by(trades, lambda t: t.regime_at_entry or "?", "regime")
    lines.append(_table(
        ["regime", "trades", "wins", "losses", "win_rate", "pnl_total", "avg_pnl"],
        [_fmt_row(r, schema_se) for r in by_regime]
    ))
    lines.append("")

    # ── Por Motivo de Saída ──
    lines.append("## 🚪 Motivo de Saída")
    lines.append("")
    reasons = exit_reasons(trades)
    schema_r = {"motivo": "str", "n": "int", "pct": "pct", "pnl_total": "usd", "avg_pnl": "usd"}
    lines.append(_table(
        ["motivo", "n", "pct", "pnl_total", "avg_pnl"],
        [_fmt_row(r, schema_r) for r in reasons]
    ))
    lines.append("")

    # ── Duração dos Trades ──
    lines.append("## ⏱ Duração dos Trades")
    lines.append("")
    durs = duration_buckets(trades)
    schema_d = {"duracao": "str", "trades": "int"}
    lines.append(_table(
        ["duracao", "trades"],
        [_fmt_row(d, schema_d) for d in durs]
    ))
    avg_hours = np.mean([(t.exit_time - t.entry_time).total_seconds() / 3600 for t in trades]) if trades else 0
    lines.append(f"\n**Duração média:** {avg_hours:.0f} horas ({avg_hours/24:.1f} dias)")
    lines.append("")

    # ── TOP 10 Melhores e Piores ──
    lines.append("## 🏆 Top 10 Melhores Trades")
    lines.append("")
    top_wins = sorted(trades, key=lambda t: t.pnl_usd, reverse=True)[:10]
    lines.append("| # | Símbolo | Dir | Entrada | Saída | Duração | P&L | RR | Motivo |")
    lines.append("|---|---------|-----|---------|--------|---------|-----|-----|--------|")
    for i, t in enumerate(top_wins, 1):
        d = (t.exit_time - t.entry_time).total_seconds() / 3600
        lines.append(f"| {i} | {t.symbol} | {t.direction} | {t.entry_time.strftime('%Y-%m-%d')} | "
                     f"{t.exit_time.strftime('%Y-%m-%d')} | {d:.0f}h | ${t.pnl_usd:+.2f} | "
                     f"{t.rr_realized:.2f} | {t.exit_reason} |")
    lines.append("")

    lines.append("## 💀 Top 10 Piores Trades")
    lines.append("")
    top_losses = sorted(trades, key=lambda t: t.pnl_usd)[:10]
    lines.append("| # | Símbolo | Dir | Entrada | Saída | Duração | P&L | RR | Motivo |")
    lines.append("|---|---------|-----|---------|--------|---------|-----|-----|--------|")
    for i, t in enumerate(top_losses, 1):
        d = (t.exit_time - t.entry_time).total_seconds() / 3600
        lines.append(f"| {i} | {t.symbol} | {t.direction} | {t.entry_time.strftime('%Y-%m-%d')} | "
                     f"{t.exit_time.strftime('%Y-%m-%d')} | {d:.0f}h | ${t.pnl_usd:+.2f} | "
                     f"{t.rr_realized:.2f} | {t.exit_reason} |")
    lines.append("")

    # ── Sequências ──
    lines.append("## 📈 Sequências (streaks)")
    streaks = []
    cur_win = cur_loss = 0
    max_win = max_loss = 0
    for t in trades:
        if t.pnl_usd > 0:
            cur_win += 1; cur_loss = 0; max_win = max(max_win, cur_win)
        else:
            cur_loss += 1; cur_win = 0; max_loss = max(max_loss, cur_loss)
    lines.append(f"- **Maior sequência de ganhos:** {max_win} trades")
    lines.append(f"- **Maior sequência de perdas:** {max_loss} trades")
    lines.append("")

    # ── Estatísticas de Risco ──
    lines.append("## ⚠ Estatísticas de Risco")
    lines.append(f"- **Max drawdown:** {s['max_dd_pct']:.1f}%")
    lines.append(f"- **Duração máxima underwater:** {s['dd_underwater_bars']} barras H4 ({s['dd_underwater_bars']/6:.0f} dias)")

    # drawdowns por mês
    eq = result.equity.dropna().resample("M").last()
    monthly_dd = []
    peak = eq.iloc[0] if not eq.empty else C.ACCOUNT_START_USD
    for val in eq:
        dd_pct = (val - peak) / peak * 100 if peak > 0 else 0
        if val > peak:
            peak = val
            dd_pct = 0
        monthly_dd.append({"mes": eq.index[len(monthly_dd)].strftime("%Y-%m"), "dd": dd_pct})
    worst_month = min(monthly_dd, key=lambda x: x["dd"]) if monthly_dd else None
    if worst_month:
        lines.append(f"- **Pior mês (drawdown):** {worst_month['mes']} ({worst_month['dd']:.1f}%)")
    lines.append(f"- **Drawdown atual (fim do backtest):** {monthly_dd[-1]['dd']:.1f}%" if monthly_dd else "")
    lines.append("")

    # ── Gráficos ──
    lines.append("## 📉 Gráficos")
    lines.append("![Análise](analysis_charts.png)")
    lines.append("")

    lines.append("---")
    lines.append(f"_Gerado em {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC por full_analysis.py_")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


# ═════════════════════════════ MAIN ═════════════════════════════
def main():
    print("=" * 60)
    print("  WEALTH_ENGINE - ANALISE COMPLETA")
    print(f"  periodo: {C.START_COMMON} -> {C.END_DEFAULT}")
    print("=" * 60)

    # 1. Dados
    print("\n[1/3] Carregando dados...")
    prices = load_all_prices(timeframe=C.TIMEFRAME, bars=C.BARS_LOOKBACK, align=True)
    n = len(next(iter(prices.values())))
    print(f"   {len(prices)} símbolos, {n} barras H4 alinhadas")
    vix = load_vix(period="max")
    print(f"   VIX: {len(vix)} dias")
    cot = load_cot_history(weeks=C.COT_ZSCORE_LOOKBACK_WEEKS)
    print(f"   COT: {len(cot)} semanas")

    # 1b. DXY para detector de liquidez/stress
    print("\n   Carregando DXY...")
    try:
        dxy_raw = load_dxy(period="10y")
        common_h4 = next(iter(prices.values())).index
        dxy_pct = dxy_pct_change_h4(dxy_raw, common_h4, lookback=C.DXY_LIQUIDITY_STRESS_LOOKBACK_BARS)
        vix_pct = vix.pct_change(5) * 100.0  # ~5 dias de lookback (reusa vix já carregado)
        vix_h4 = vix_pct.reindex(common_h4).ffill()
        print(f"   DXY: {len(dxy_raw)} dias, série de % change H4 pronta")
    except Exception as e:
        print(f"   DXY indisponível ({e}) — liquidity stress desativado")
        dxy_pct = None
        vix_h4 = None

    # 1c. SPY e correlação ouro×ações para regime risk_on genuíno
    print("\n   Carregando SPY (S&P500) e calculando correlação ouro×ações...")
    spy_data = None
    ge_corr = None
    try:
        spy_data = load_spy(period="10y")
        # Calcula retornos diários do XAUUSD (usando preços H4 reamostrados para diário)
        common_h4 = next(iter(prices.values())).index
        xau_h4 = prices.get("XAUUSDm")
        if xau_h4 is not None and spy_data is not None:
            xau_daily = xau_h4["close"].resample("D").last().dropna()
            ge_corr = gold_equity_corr(spy_data, xau_daily, window=C.GE_CORR_WINDOW_DAYS)
            print(f"   SPY: {len(spy_data)} dias, correlação gold×ações calculada ({len(ge_corr)} dias)")
        else:
            print("   [AVISO] XAUUSD ou SPY indisponível — correlação gold×ações desativada")
    except Exception as e:
        print(f"   [AVISO] SPY indisponível ({e}) — correlação gold×ações desativada")
        spy_data = None
        ge_corr = None

    # 2. Regime
    print("\n[2/3] Montando regime...")
    regime = RuleBasedRegime(vix=vix, prices_for_corr=prices, gold_equity_corr=ge_corr)

    # 1c. Macro events para backtest
    print("   Carregando calendário de eventos macro...")
    try:
        macro_events = get_events_for_backtest(C.START_COMMON, C.END_DEFAULT)
        print(f"      {len(macro_events)} eventos gerados (FOMC, NFP, CPI, etc)")
        if macro_events:
            print(f"      Primeiro: {macro_events[0]['time'].strftime('%Y-%m-%d %H:%M')} - {macro_events[0]['event']}")
            print(f"      Último:  {macro_events[-1]['time'].strftime('%Y-%m-%d %H:%M')} - {macro_events[-1]['event']}")
    except Exception as e:
        print(f"      Aviso: eventos macro indisponíveis ({e})")
        macro_events = None

    # 3. Calcula D1 momentum para filtro de tendência diária
    print("\n   Calculando D1 momentum (filtro de tendência)...")
    d1_momentum = {}
    if C.D1_FILTER_ENABLED:
        common_h4 = next(iter(prices.values())).index
        for sym, df in prices.items():
            # Reamostra H4 -> D1: pega o close da última barra H4 de cada dia
            daily_close = df["close"].resample("D").last().dropna()
            # Momentum D1: retorno em D1_MOMENTUM_LOOKBACK_BARS dias, shiftado pra evitar lookahead
            mom = (daily_close.shift(1) / daily_close.shift(C.D1_MOMENTUM_LOOKBACK_BARS + 1)) - 1.0
            # Alinha ao índice H4 (forward-fill: cada barra H4 usa o D1 momentum mais recente)
            d1_h4 = mom.reindex(common_h4, method="ffill")
            d1_momentum[sym] = d1_h4
        print(f"      D1 momentum calculado para {len(d1_momentum)} símbolos")

    # 4. Roda ts_momentum (a vencedora)
    print("\n[3/3] Rodando backtest ts_momentum...")
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
    trades = result.trades
    s = basic_summary(result)
    print(f"   {len(trades)} trades | Sharpe {s['sharpe']:.2f} | Ret {s['total_return_pct']:+.1f}% | DD {s['max_dd_pct']:.1f}%")
    print(f"   Win Rate {s['win_rate']:.1%} | Payoff {s['payoff']:.2f} | Expect ${s['expectancy_usd']:.2f}/trade")

    # 5. Gráficos
    print("\nGerando gráficos...")
    chart_path = make_charts(result, trades, C.REPORTS_DIR / "analysis_charts.png")
    print(f"   [OK] Grafico salvo em {chart_path}")

    # 6. Relatório
    print("\nGerando relatório...")
    report_path = write_analysis(result, trades, C.REPORTS_DIR / "ANALYSIS.md")
    print(f"   [OK] Relatorio salvo em {report_path}")

    print("\n" + "=" * 60)
    print(f"  ANÁLISE PRONTA — ver reports/ANALYSIS.md")
    print("=" * 60)


if __name__ == "__main__":
    main()
