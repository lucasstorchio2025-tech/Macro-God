"""regime_sweep.py — testa diferentes gates de regime pra achar o ótimo.

A análise mostrou que ts_momentum SÓ tem edge em risk_on (+$900).
Fora disso perde (crisis -$47, normal -$130, risk_off -$45).

Este script roda o backtest com várias configurações de EXPOSURE_SCALE
e compara Sharpe/Retorno/DD pra validar qual gate é o melhor.
NÃO muda o config — só testa. A decisão fica pro usuário.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from engine import config as C
from engine.data import load_all_prices, load_vix, load_cot_history
from engine.regime import RuleBasedRegime
from engine.signals import TSMomentumStrategy
from engine.backtest import run_backtest
from engine.analytics import basic_summary


# Configurações de EXPOSURE_SCALE pra testar
# Formato: {risk_on, normal, risk_off, crisis}
CONFIGS = {
    "ATUAL (1.0/0.75/0.40/0.10)":  {"risk_on": 1.0, "normal": 0.75, "risk_off": 0.40, "crisis": 0.10},
    "SÓ risk_on (resto 0)":         {"risk_on": 1.0, "normal": 0.0,  "risk_off": 0.0,  "crisis": 0.0},
    "risk_on + normal fraco":       {"risk_on": 1.0, "normal": 0.30, "risk_off": 0.0,  "crisis": 0.0},
    "risk_on + normal cheio":       {"risk_on": 1.0, "normal": 0.50, "risk_off": 0.0,  "crisis": 0.0},
    "Tudo reduzido pela metade":   {"risk_on": 0.5, "normal": 0.25, "risk_off": 0.0,  "crisis": 0.0},
    "risk_on conservador":          {"risk_on": 0.7, "normal": 0.0,  "risk_off": 0.0,  "crisis": 0.0},
}


def run_sweep():
    print("=" * 70)
    print("  REGIME GATE SWEEP — qual configuração de EXPOSURE_SCALE é ótima?")
    print("=" * 70)

    # Carrega dados UMA vez
    print("\nCarregando dados...")
    prices = load_all_prices(timeframe=C.TIMEFRAME, bars=C.BARS_LOOKBACK, align=True)
    vix = load_vix(period="max")
    print(f"  {len(prices)} símbolos, {len(next(iter(prices.values())))} barras")

    regime = RuleBasedRegime(vix=vix, prices_for_corr=prices)

    results = []
    for label, scales in CONFIGS.items():
        print(f"\n→ Testando: {label}")
        # Monkey-patch o config temporariamente
        original = dict(C.EXPOSURE_SCALE)
        C.EXPOSURE_SCALE.clear()
        C.EXPOSURE_SCALE.update(scales)
        C.EXPOSURE_SCALE.update({"default": 0.5})

        try:
            res = run_backtest(
                prices=prices,
                strategy=TSMomentumStrategy(),
                regime_provider=regime,
                start=C.START_COMMON,
                end=C.END_DEFAULT,
                account_start=C.ACCOUNT_START_USD,
                use_costs=True,
                label=label,
            )
            s = basic_summary(res)
            print(f"  {len(res.trades)} trades | Ret {s['total_return_pct']:+.1f}% | "
                  f"Sharpe {s['sharpe']:.2f} | DD {s['max_dd_pct']:.1f}% | "
                  f"Win {s['win_rate']:.1%} | Final ${s['final_equity']:.0f}")
            results.append({
                "config": label,
                "scales": scales,
                "n_trades": len(res.trades),
                "total_return_pct": s["total_return_pct"],
                "cagr_pct": s["cagr_pct"],
                "sharpe": s["sharpe"],
                "sortino": s["sortino"],
                "max_dd_pct": s["max_dd_pct"],
                "win_rate": s["win_rate"],
                "payoff": s["payoff"],
                "expectancy_usd": s["expectancy_usd"],
                "final_equity": s["final_equity"],
            })
        except Exception as e:
            print(f"  ✗ ERRO: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # restaura config original
            C.EXPOSURE_SCALE.clear()
            C.EXPOSURE_SCALE.update(original)

    # Tabela comparativa
    print("\n" + "=" * 70)
    print("  RESULTADO COMPARATIVO")
    print("=" * 70)
    df = pd.DataFrame(results)

    # ordena por Sharpe decrescente
    df = df.sort_values("sharpe", ascending=False)

    print(f"\n{'Config':<32} {'Trades':>7} {'Ret%':>8} {'CAGR%':>7} {'Sharpe':>7} "
          f"{'Sortino':>8} {'MaxDD%':>8} {'Win%':>6} {'Final':>9}")
    print("-" * 105)
    for _, r in df.iterrows():
        print(f"{r['config']:<32} {r['n_trades']:>7} {r['total_return_pct']:>+7.1f}% "
              f"{r['cagr_pct']:>+6.1f}% {r['sharpe']:>7.2f} {r['sortino']:>8.2f} "
              f"{r['max_dd_pct']:>+7.1f}% {r['win_rate']*100:>5.1f}% ${r['final_equity']:>8.0f}")

    # Ranking e recomendação
    best = df.iloc[0]
    print(f"\n{'─'*70}")
    print(f"  🏆 MELHOR CONFIG POR SHARPE: {best['config']}")
    print(f"     Sharpe {best['sharpe']:.2f} | Ret {best['total_return_pct']:+.1f}% | "
          f"DD {best['max_dd_pct']:.1f}% | ${best['final_equity']:.0f}")
    print(f"     Escala: {best['scales']}")

    # comparação com ATUAL
    atual = df[df["config"].str.startswith("ATUAL")].iloc[0] if len(df[df["config"].str.startswith("ATUAL")]) else None
    if atual is not None and best["config"] != atual["config"]:
        delta_sharpe = best["sharpe"] - atual["sharpe"]
        delta_ret = best["total_return_pct"] - atual["total_return_pct"]
        delta_dd = best["max_dd_pct"] - atual["max_dd_pct"]
        print(f"\n  📈 GANHO vs ATUAL:")
        print(f"     Sharpe: {atual['sharpe']:.2f} → {best['sharpe']:.2f} ({delta_sharpe:+.2f})")
        print(f"     Retorno: {atual['total_return_pct']:+.1f}% → {best['total_return_pct']:+.1f}% ({delta_ret:+.1f}pp)")
        print(f"     Max DD: {atual['max_dd_pct']:.1f}% → {best['max_dd_pct']:.1f}% ({delta_dd:+.1f}pp)")

    # salva
    out = C.REPORTS_DIR / "regime_sweep.csv"
    df.to_csv(out, index=False)
    print(f"\n  Resultado salvo em: {out}")

    return df


if __name__ == "__main__":
    run_sweep()
