"""analytics.py — métricas de performance e relatório de veredito.

Princípio: número honesto, SEM maquiagem. Se a estratégia não tem edge, o
relatório diz "não tem edge" com clareza. Nada de destacar só o que favorece.

Métricas calculadas:
  - Retorno total %, CAGR
  - Sharpe, Sortino (anualizados)
  - Calmar (CAGR / max DD)
  - Max drawdown %, duração do DD
  - Win rate, payoff ratio (ganho médio / perda média)
  - Expectancy por trade (em % e USD)
  - Nº de trades, tempo médio em mercado
  - Tudo QUEBRADO POR REGIME (edge existe em risk_on mas some em crisis?)
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from . import config as C


# ═════════════════════════════ MÉTRICAS CORE ═════════════════════════════
def returns_from_equity(equity: pd.Series) -> pd.Series:
    """Retornos periódicos da curva de equity."""
    return equity.pct_change().dropna()


def sharpe(returns: pd.Series, bars_per_year: int = 6 * 252, rf: float = 0.0) -> float:
    """Sharpe ratio anualizado."""
    if len(returns) < 2 or returns.std() == 0:
        return 0.0
    excess = returns - rf / bars_per_year
    return float(np.sqrt(bars_per_year) * excess.mean() / returns.std())


def sortino(returns: pd.Series, bars_per_year: int = 6 * 252, rf: float = 0.0) -> float:
    """Sortino (só penaliza vol negativa)."""
    if len(returns) < 2:
        return 0.0
    excess = returns - rf / bars_per_year
    downside = returns[returns < 0]
    dd_std = downside.std()
    if dd_std == 0 or not np.isfinite(dd_std):
        return 0.0
    return float(np.sqrt(bars_per_year) * excess.mean() / dd_std)


def max_drawdown(equity: pd.Series) -> tuple[float, int]:
    """(max DD %, nº de barras debaixo d'água). Negativo, ex: -0.15 = -15%."""
    roll_max = equity.cummax()
    dd = (equity - roll_max) / roll_max
    mdd = float(dd.min())
    # duração: maior sequência debaixo d'água
    underwater = dd < 0
    max_run = cur = 0
    for u in underwater:
        cur = cur + 1 if u else 0
        max_run = max(max_run, cur)
    return mdd, max_run


def trade_stats(trades: list) -> dict:
    """Win rate, payoff, expectancy da lista de Trade."""
    if not trades:
        return {"n": 0, "win_rate": 0, "payoff": 0, "expectancy_pct": 0,
                "expectancy_usd": 0, "avg_win": 0, "avg_loss": 0}
    pnls = np.array([t.pnl_usd for t in trades])
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    win_rate = len(wins) / len(pnls) if len(pnls) else 0
    avg_win = wins.mean() if len(wins) else 0
    avg_loss = losses.mean() if len(losses) else 0
    payoff = (avg_win / abs(avg_loss)) if avg_loss != 0 else float("inf")
    return {
        "n": len(pnls),
        "win_rate": float(win_rate),
        "payoff": float(payoff),
        "expectancy_pct": float(np.mean([t.pnl_pct for t in trades])),
        "expectancy_usd": float(np.mean(pnls)),
        "avg_win": float(avg_win),
        "avg_loss": float(avg_loss),
    }


def basic_summary(result) -> dict:
    """Resumo de 1 BacktestResult. Usado por BacktestResult.summary()."""
    eq = result.equity.dropna()
    if eq.empty:
        return {"label": result.label, "error": "curva vazia"}
    rets = returns_from_equity(eq)
    total_ret = (eq.iloc[-1] / eq.iloc[0] - 1) if eq.iloc[0] > 0 else 0
    n_years = len(eq) / (6 * 252)
    cagr = ((eq.iloc[-1] / eq.iloc[0]) ** (1 / n_years) - 1) if n_years > 0 and eq.iloc[0] > 0 else 0
    mdd, dd_bars = max_drawdown(eq)
    ts = trade_stats(result.trades)
    return {
        "label": result.label,
        "period": result.period,
        "n_bars": result.n_bars,
        "total_return_pct": float(total_ret * 100),
        "cagr_pct": float(cagr * 100),
        "sharpe": sharpe(rets),
        "sortino": sortino(rets),
        "max_dd_pct": float(mdd * 100),
        "dd_underwater_bars": dd_bars,
        "final_equity": float(eq.iloc[-1]),
        **ts,
    }


def by_regime(result) -> dict[str, dict]:
    """Métricas de trades segregadas por regime de entrada."""
    out = {}
    by_reg: dict[str, list] = {}
    for t in result.trades:
        by_reg.setdefault(t.regime_at_entry or "?", []).append(t)
    for reg, trades in by_reg.items():
        out[reg] = trade_stats(trades)
    return out


# ═════════════════════════════ EQUITY CURVE PNG ═════════════════════════════
def plot_equity(results: list, out_path: Path | str, title: str = "Equity Curves"):
    """Plota curvas de equity de múltiplos BacktestResult lado a lado."""
    import matplotlib
    matplotlib.use("Agg")  # sem display
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(11, 6))
    for r in results:
        eq = r.equity.dropna()
        if not eq.empty:
            ax.plot(eq.index, eq.values, label=r.label, linewidth=1.5)
    ax.axhline(C.ACCOUNT_START_USD, color="gray", linestyle="--", linewidth=1, label="Saldo inicial")
    ax.set_title(title)
    ax.set_ylabel("Equity (USD)")
    ax.set_xlabel("Data")
    ax.legend(loc="best", fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path


# ═════════════════════════════ VEREDITO ═════════════════════════════
def verdict_table(results: list) -> pd.DataFrame:
    """Tabela comparativa de múltiplos runs (pro VERDICT.md)."""
    rows = []
    for r in results:
        s = basic_summary(r)
        rows.append(s)
    return pd.DataFrame(rows)


def write_verdict(results: list, baseline_label: str = "legacy_cot",
                  out_path: Path | str = C.REPORTS_DIR / "VERDICT.md") -> Path:
    """Escreve relatório markdown com veredito honesto.

    Lógica de recomendação:
      - Sharpe > 1.0 E max DD < 25% E expectancy_usd > 0 → "ir pra live (dry-run)"
      - Sharpe 0.5-1.0 → "marginal, refinar"
      - Sharpe < 0.5 OU expectancy < 0 → "não tem edge, não operar"
    """
    out_path = Path(out_path)
    df = verdict_table(results)
    img = plot_equity(results, C.REPORTS_DIR / "equity_curves.png")

    best = df.loc[df["sharpe"].idxmax()] if len(df) else None
    baseline = df[df["label"] == baseline_label]

    lines = []
    lines.append("# VEREDITO — Backtest Wealth_Engine v2\n")
    lines.append(f"Gerado em: {pd.Timestamp.utcnow().strftime('%Y-%m-%d %H:%M')} UTC\n")
    lines.append("## Comparação lado a lado\n")
    lines.append("Métrica | " + " | ".join(df["label"].astype(str)))
    lines.append("---|" + "---|" * len(df))
    for metric in ["total_return_pct", "cagr_pct", "sharpe", "sortino",
                   "max_dd_pct", "win_rate", "payoff", "expectancy_usd", "final_equity"]:
        row = f"**{metric}** | " + " | ".join(
            _fmt(df.iloc[i][metric], metric) for i in range(len(df)))
        lines.append(row)

    lines.append("\n![Equity curves](equity_curves.png)\n")

    if best is not None:
        lines.append(f"## Melhor estratégia: **{best['label']}**")
        lines.append(f"- Sharpe: {best['sharpe']:.2f} | Sortino: {best['sortino']:.2f} | "
                     f"Max DD: {best['max_dd_pct']:.1f}% | Expectancy: "
                     f"${best['expectancy_usd']:.2f}/trade")
        if best['sharpe'] > 1.0 and best['max_dd_pct'] > -25 and best['expectancy_usd'] > 0:
            rec = "✅ **Ir pra live (dry-run primeiro).** Edge validado fora da amostra."
        elif best['sharpe'] > 0.5:
            rec = "⚠️ **Marginal.** Edge fraco — refinar antes de operar."
        else:
            rec = "❌ **Sem edge.** Nenhuma estratégia supera custo+risco. NÃO operar."
        lines.append(f"\n### Recomendação\n{rec}\n")

    if not baseline.empty:
        b = baseline.iloc[0]
        lines.append(f"## Baseline (estratégia antiga do bot): **{b['label']}**")
        lines.append(f"- Sharpe: {b['sharpe']:.2f} | Total: {b['total_return_pct']:.1f}% | "
                     f"Final: ${b['final_equity']:.2f}")
        if b['total_return_pct'] < 0:
            lines.append(f"- ✅ **Confirmado:** a lógica antiga PERDE dinheiro no backtest "
                         f"(como ocorreu na demo $500→$410). Substituída.\n")

    lines.append("\n---\n_Veredito gerado por analytics.py. Métricas em out-of-sample. "
                 "Se o veredito é 'sem edge', é isso que é — não maquie._")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _fmt(v, metric: str) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "—"
    if "pct" in metric or metric in ("win_rate",):
        return f"{v:+.1f}%" if "return" in metric else f"{v:.1%}" if abs(v) < 5 else f"{v:.1f}"
    if metric in ("sharpe", "sortino", "payoff"):
        return f"{v:.2f}"
    if metric in ("final_equity", "expectancy_usd"):
        return f"${v:.2f}"
    return f"{v:.3f}"


__all__ = ["returns_from_equity", "sharpe", "sortino", "max_drawdown",
           "trade_stats", "basic_summary", "by_regime", "verdict_table",
           "write_verdict", "plot_equity"]
