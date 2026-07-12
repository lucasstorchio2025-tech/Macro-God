"""run_verdict.py — roda as 3 estratégias no mesmo período e escreve VERDICT.md.

Uso:  python -m engine.run_verdict
  (ou:  python engine/run_verdict.py)

Compara, em OUT-OF-SAMPLE (a parte do histórico reservada, não vista no treino):
  1. legacy_cot       — a lógica ATUAL do bot (espera-se que perca)
  2. ts_momentum      — time-series momentum cross-asset
  3. cot_contrarian   — COT contrarian em extremos (z-score >= 2)

Cada uma roda COM regime + sizing + custos reais. O número decide.
"""
import sys
from pathlib import Path

# permite rodar como script direto ou como módulo
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import config as C
from engine.data import load_all_prices, load_vix, load_cot_history
from engine.regime import RuleBasedRegime, AlwaysNormalRegime
from engine.signals import TSMomentumStrategy, COTContrarianStrategy, LegacyCOTStrategy
from engine.backtest import run_backtest
from engine.analytics import write_verdict, basic_summary


def main(start: str = C.START_COMMON, end: str = C.END_DEFAULT):
    print("=" * 60)
    print("  WEALTH_ENGINE v2 — VEREDICT RUN")
    print(f"  período: {start} → {end}")
    print("=" * 60)

    # 1. Dados
    print("\n[1/4] Carregando dados...")
    prices = load_all_prices(timeframe=C.TIMEFRAME, bars=C.BARS_LOOKBACK, align=True)
    n = len(next(iter(prices.values())))
    print(f"   {len(prices)} símbolos, {n} barras H4 alinhadas")
    vix = load_vix(period="max")
    print(f"   VIX: {len(vix)} dias  ({vix.index[0].date()} → {vix.index[-1].date()})")
    cot = load_cot_history(weeks=C.COT_ZSCORE_LOOKBACK_WEEKS)
    print(f"   COT: {len(cot)} semanas, moedas: {list(cot.columns)}")

    # 2. Regime provider (VIX + correlação entre pares)
    print("\n[2/4] Montando detector de regime...")
    regime = RuleBasedRegime(vix=vix, prices_for_corr=prices)
    # amostra de regimes p/ confirmar variação
    sample_ts = prices["EURUSDm"].index[::500]
    regimes_seen = {regime.at(t, {}) for t in sample_ts[:50]}
    print(f"   regimes detectados na amostra: {regimes_seen}")

    # 3. Roda as 3 estratégias
    results = []
    strategies = [
        ("legacy_cot",     LegacyCOTStrategy(cot)),
        ("ts_momentum",    TSMomentumStrategy()),
        ("cot_contrarian", COTContrarianStrategy(cot)),
    ]

    print("\n[3/4] Rodando backtest de cada estratégia...")
    for name, strat in strategies:
        print(f"   → {name}...", end=" ", flush=True)
        try:
            res = run_backtest(
                prices=prices,
                strategy=strat,
                regime_provider=regime,
                start=start, end=end,
                account_start=C.ACCOUNT_START_USD,
                use_costs=True,
                label=name,
            )
            results.append(res)
            s = basic_summary(res)
            print(f"{len(res.trades)} trades | Sharpe {s['sharpe']:.2f} | "
                  f"ret {s['total_return_pct']:+.1f}% | DD {s['max_dd_pct']:.1f}%")
        except Exception as e:
            import traceback
            print(f"FALHOU: {type(e).__name__}: {e}")
            traceback.print_exc()

    # 4. Veredito
    print("\n[4/4] Escrevendo VERDICT.md...")
    if results:
        out = write_verdict(results, baseline_label="legacy_cot")
        print(f"   ✓ {out}")
        print("\n" + "=" * 60)
        print("  VEREDICTO PRONTO — ver reports/VERDICT.md")
        print("=" * 60)
    else:
        print("   ✗ nenhum resultado válido")


if __name__ == "__main__":
    main()
