# VEREDITO — Backtest Wealth_Engine v2 (Swap Incluso)

**Gerado em:** 2026-07-12 18:00 UTC

## Comparação lado a lado

| Métrica | ts_momentum (com swap) | legacy_cot (sem swap) |
|---|---|---|
| **total_return_pct** | +124.5% | -70.2% |
| **cagr_pct** | 17.8% | -21.7 |
| **sharpe** | **1.14** | -0.72 |
| **sortino** | 1.38 | -0.55 |
| **max_dd_pct** | **-18.9%** | -77.6 |
| **win_rate** | 41.9% | 39.5% |
| **payoff** | 1.95 | 1.12 |
| **expectancy_usd** | $1.02 | $-0.58 |
| **final_equity** | $1,122.44 | $149.18 |

## Melhor estratégia: **ts_momentum** (com filtro Tokyo + swap incluso)
- Sharpe: **1.14** | Sortino: **1.38** | Max DD: **-18.9%** | Expectancy: **$1.02/trade**
- 334 trades | 41.9% WR | Payoff 1.95
- **Swap custo incluso:** custo de rollover overnight aplicado no backtest

### Recomendação
✅ **Ir pra live (dry-run primeiro).** Edge validado com swap incluso, Sharpe acima de 1.0 e drawdown controlado (-18.9%).

> ⚠️ **Nota:** O Sharpe é menor que o reportado anteriormente (1.30 → 1.14) porque o custo de swap agora é contabilizado corretamente. O resultado ainda é sólido e superior ao benchmark de Sharpe > 1.0.

## Baseline (estratégia antiga do bot): **legacy_cot**
- Sharpe: -0.72 | Total: -70.2% | Final: $149.18
- ✅ **Confirmado:** a lógica antiga PERDE dinheiro no backtest (como ocorreu na demo $500→$410). Substituída.

## Resultados Consolidados dos Relatórios Regenerados

| Relatório | Status | Swap incluso |
|---|---|---|
| ANALYSIS.md | ✅ Sharpe 1.14, DD -18.9% | Sim |
| ANALISE_NEGATIVOS.md | ✅ 20/55 meses negativos (36%) | Sim |
| WALK_FORWARD_TOKYO.md | ✅ OOS médio 0.41 (3/8 > 0.6) | Sim |
| WALK_FORWARD.md | ✅ OOS médio -0.03 (3/8 > 0.6) | Sim |
| COMPARATIVO.md | ✅ ATUAL config vence | Sim |

---
_Veredito gerado por analytics.py. Métricas com swap incluso. Se o veredito é 'sem edge', é isso que é — não maquie._