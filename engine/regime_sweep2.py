"""regime_sweep2.py — investigação profunda do paradoxo do regime.

A análise por-regime disse: edge SÓ em risk_on (+$900).
Mas o sweep de gates disse: cortar fora risk_off não ajuda.

PARADOXO. As duas coisas não podem ser verdade ao mesmo tempo.
Este script resolve o paradoxo investigando 3 hipóteses:

  H1: PERÍODO. Risk_on foi lucrativo por causa de QUANDO ocorreu
      (bull market 2023-2024), não porque a estratégia é boa nele.
  H2: SIZING. O gate reduz tamanho em risk_off, mas as perdas em USD
      contam como "edge negativo" mesmo com pouco tamanho.
  H3: OUTROS PARÂMETROS. O problema não é regime, é símbolo (EURUSD)
      ou cooldown curto demais.

Testa cada hipótese com fatias dos dados.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from engine import config as C
from engine.data import load_all_prices, load_vix
from engine.regime import RuleBasedRegime
from engine.signals import TSMomentumStrategy
from engine.backtest import run_backtest
from engine.analytics import basic_summary


def analyze_regime_by_period(prices, vix, regime):
    """H1: divide o backtest em janelas anuais e vê edge por regime em cada."""
    print("\n" + "=" * 70)
    print("  H1: EDGE POR REGIME EM CADA PERÍODO (anual)")
    print("=" * 70)

    periods = [
        ("2022", "2022-01-01", "2022-12-31"),
        ("2023", "2023-01-01", "2023-12-31"),
        ("2024", "2024-01-01", "2024-12-31"),
        ("2025", "2025-01-01", "2025-12-31"),
        ("2026", "2026-01-01", "2026-06-30"),
    ]

    for label, start, end in periods:
        res = run_backtest(
            prices=prices, strategy=TSMomentumStrategy(),
            regime_provider=regime, start=start, end=end,
            account_start=C.ACCOUNT_START_USD, use_costs=True, label=label,
        )
        # segrega trades por regime de entrada
        by_reg = {}
        for t in res.trades:
            by_reg.setdefault(t.regime_at_entry or "?", []).append(t.pnl_usd)

        print(f"\n  {label} ({len(res.trades)} trades):")
        for reg, pnls in sorted(by_reg.items()):
            total = sum(pnls)
            wins = sum(1 for p in pnls if p > 0)
            wr = wins / len(pnls) * 100 if pnls else 0
            print(f"    {reg:<10} {len(pnls):>3} trades | WR {wr:>5.1f}% | P&L ${total:>+8.2f} | méd ${total/len(pnls):>+6.2f}")


def analyze_symbol_filter(prices, vix, regime):
    """H3a: roda backtest SEM EURUSD (o par perdedor) e compara."""
    print("\n" + "=" * 70)
    print("  H3a: FILTRO POR SÍMBOLO (sem EURUSD, o perdedor)")
    print("=" * 70)

    prices_no_eurusd = {k: v for k, v in prices.items() if k != "EURUSDm"}

    res = run_backtest(
        prices=prices_no_eurusd, strategy=TSMomentumStrategy(),
        regime_provider=regime, start=C.START_COMMON, end=C.END_DEFAULT,
        account_start=C.ACCOUNT_START_USD, use_costs=True, label="sem_eurusd",
    )
    s = basic_summary(res)
    print(f"  Sem EURUSD: {len(res.trades)} trades | Ret {s['total_return_pct']:+.1f}% | "
          f"Sharpe {s['sharpe']:.2f} | DD {s['max_dd_pct']:.1f}% | Final ${s['final_equity']:.0f}")
    print(f"  (ATUAL com EURUSD: 1261 trades | +135.5% | Sharpe 0.62 | DD -37.8% | $1178)")

    # só XAU + JPY?
    prices_xau_jpy = {k: v for k, v in prices.items() if k in ("XAUUSDm", "USDJPYm")}
    res2 = run_backtest(
        prices=prices_xau_jpy, strategy=TSMomentumStrategy(),
        regime_provider=regime, start=C.START_COMMON, end=C.END_DEFAULT,
        account_start=C.ACCOUNT_START_USD, use_costs=True, label="xau_jpy",
    )
    s2 = basic_summary(res2)
    print(f"\n  Só XAU+JPY: {len(res2.trades)} trades | Ret {s2['total_return_pct']:+.1f}% | "
          f"Sharpe {s2['sharpe']:.2f} | DD {s2['max_dd_pct']:.1f}% | Final ${s2['final_equity']:.0f}")


def analyze_cooldown(prices, vix, regime):
    """H3b: testa cooldowns mais longos pra reduzir overtrading."""
    print("\n" + "=" * 70)
    print("  H3b: COOLDOWN — quanto tempo esperar entre trades do mesmo par?")
    print("=" * 70)

    cooldowns = [12, 24, 48, 96]  # barras H4 (12=2dias, 96=16dias)
    for cd in cooldowns:
        original = C.COOLDOWN_BARS
        C.COOLDOWN_BARS = cd
        res = run_backtest(
            prices=prices, strategy=TSMomentumStrategy(),
            regime_provider=regime, start=C.START_COMMON, end=C.END_DEFAULT,
            account_start=C.ACCOUNT_START_USD, use_costs=True, label=f"cd_{cd}",
        )
        s = basic_summary(res)
        dias = cd * 4 / 24
        print(f"  Cooldown {cd:>3} barras ({dias:>4.0f} dias): {len(res.trades):>4} trades | "
              f"Ret {s['total_return_pct']:>+6.1f}% | Sharpe {s['sharpe']:.2f} | "
              f"DD {s['max_dd_pct']:>6.1f}% | Exp ${s['expectancy_usd']:>+5.2f} | ${s['final_equity']:>6.0f}")
        C.COOLDOWN_BARS = original


def main():
    print("Carregando dados...")
    prices = load_all_prices(timeframe=C.TIMEFRAME, bars=C.BARS_LOOKBACK, align=True)
    vix = load_vix(period="max")
    regime = RuleBasedRegime(vix=vix, prices_for_corr=prices)

    analyze_regime_by_period(prices, vix, regime)
    analyze_symbol_filter(prices, vix, regime)
    analyze_cooldown(prices, vix, regime)

    print("\n" + "=" * 70)
    print("  CONCLUSÃO DO DIAGNÓSTICO")
    print("=" * 70)


if __name__ == "__main__":
    main()
