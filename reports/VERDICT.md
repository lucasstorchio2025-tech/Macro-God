# VEREDITO — Backtest Wealth_Engine v2 (Swap Incluso)

**Gerado em:** 2026-07-12 18:00 UTC

## Comparação lado a lado

| Métrica | ts_momentum (com swap) | legacy_cot (sem swap) |
|---|---|---|
| **total_return_pct** | +124.5% | -70.2% |
| **cagr_pct** | 17.8% | -21.7 |
| **sharpe** | **1.14** | -0.72 |
| **sortino** | 0.86 | -0.55 |
| **max_dd_pct** | **-18.9%** | -77.6 |
| **win_rate** | 63.2% | 39.5% |
| **payoff** | 0.94 | 1.12 |
| **expectancy_usd** | $2.52 | $-0.58 |
| **final_equity** | $1,122.50 | $149.18 |

## Melhor estratégia: **ts_momentum** (filtro Tokyo, swap incluso)
- Sharpe: **1.14** | Sortino: **0.86** | Max DD: **-18.9%** | Expectancy: **$2.52/trade**
- 334 trades | 63.2% WR | Payoff 0.94
- **Swap custo incluso:** custo de rollover overnight aplicado no backtest

### Recomendação
⚠️ **ATENÇÃO: vereditos contraditórios entre relatórios.**

O backtest no período completo (VERDICT.md/COMPARATIVO.md) mostra Sharpe 1.14 — indicando edge.
**Porém**, a validação walk-forward (WALK_FORWARD_TOKYO.md) — que testa fora-da-amostra —
conclui **OVERFIT** (OOS Sharpe médio 0.41, apenas 3/8 janelas > 0.6).

**O teste rigoroso diz NÃO. O teste simples diz SIM.**

Recomendações:
1. **NÃO ir pra live** até que a contradição seja resolvida.
2. Explorar alternativas: sessões múltiplas, parâmetros menos agressivos.
3. Se for testar em dry-run, monitorar drawdown semanal de perto.

> ⚠️ **Nota sobre Sortino:** O valor real é 0.86 (de ANALYSIS.md/COMPARATIVO.md).
> O Sortino 1.38 reportado anteriormente foi um erro de estimativa manual.
> O Sharpe caiu de 1.30→1.14 com a inclusão do custo de swap (correção honesta).

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