# VEREDITO — Backtest Wealth_Engine v2

Gerado em: 2026-07-02 01:10 UTC

## Comparação lado a lado

Métrica | legacy_cot | ts_momentum | cot_contrarian
---|---|---|---|
**total_return_pct** | -70.2% | +135.5% | -16.2%
**cagr_pct** | -21.7 | 19.0 | -351.2%
**sharpe** | -0.72 | 0.62 | -0.31
**sortino** | -0.55 | 0.68 | -0.15
**max_dd_pct** | -77.6 | -37.8 | -36.5
**win_rate** | 39.5% | 41.7% | 36.7%
**payoff** | 1.12 | 1.52 | 1.40
**expectancy_usd** | $-0.58 | $0.54 | $-0.46
**final_equity** | $149.18 | $1177.53 | $419.14

![Equity curves](equity_curves.png)

## Melhor estratégia: **ts_momentum**
- Sharpe: 0.62 | Sortino: 0.68 | Max DD: -37.8% | Expectancy: $0.54/trade

### Recomendação
⚠️ **Marginal.** Edge fraco — refinar antes de operar.

## Baseline (estratégia antiga do bot): **legacy_cot**
- Sharpe: -0.72 | Total: -70.2% | Final: $149.18
- ✅ **Confirmado:** a lógica antiga PERDE dinheiro no backtest (como ocorreu na demo $500→$410). Substituída.


---
_Veredito gerado por analytics.py. Métricas em out-of-sample. Se o veredito é 'sem edge', é isso que é — não maquie._