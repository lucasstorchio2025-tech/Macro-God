# Analise de Meses Negativos — Backtest Solo Tokyo
**Periodo:** 2021-12 → 2026-06 | **Total de meses:** 55
**Meses negativos:** 20 (36%)
**Soma perdas:** $-475.72 | **Soma ganhos:** $+1,317.84 | **Total:** $+842.11

## Meses Negativos — Detalhado

| mes | pnl_total | trades | win_rate | avg_win | avg_loss | payoff | regime_predominante | direcao_predominante | tp_pct | sl_pct | ptp_pct | max_loss_streak | dd_intra_mes_pct |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2022-03 | $-17.27 | 5 | 20.0% | $+0.79 | $-4.52 | 0.18 | risk_off | BUY | 0.0% | 60.0% | 20.0% | 2 | -3.8% |
| 2022-04 | $-4.10 | 4 | 50.0% | $+10.07 | $-12.12 | 0.83 | normal | BUY | 25.0% | 50.0% | 25.0% | 2 | -4.7% |
| 2022-11 | $-42.77 | 5 | 20.0% | $+4.08 | $-11.71 | 0.35 | normal | BUY | 0.0% | 80.0% | 20.0% | 3 | -9.4% |
| 2023-01 | $-26.28 | 9 | 44.4% | $+13.70 | $-16.22 | 0.84 | normal | BUY | 22.2% | 55.6% | 22.2% | 4 | -9.6% |
| 2023-02 | $-15.19 | 1 | 0.0% | $+0.00 | $-15.19 | 0.00 | normal | BUY | 0.0% | 100.0% | 0.0% | 1 | -2.3% |
| 2023-03 | $-24.63 | 3 | 33.3% | $+4.24 | $-14.44 | 0.29 | normal | BUY | 0.0% | 66.7% | 33.3% | 2 | -5.7% |
| 2023-10 | $-36.49 | 5 | 40.0% | $+5.13 | $-15.58 | 0.33 | normal | SELL | 0.0% | 60.0% | 40.0% | 3 | -7.5% |
| 2023-11 | $-7.55 | 6 | 50.0% | $+10.61 | $-13.12 | 0.81 | normal | BUY | 16.7% | 50.0% | 33.3% | 2 | -4.5% |
| 2024-01 | $-47.04 | 6 | 33.3% | $+5.13 | $-14.33 | 0.36 | normal | BUY | 0.0% | 66.7% | 33.3% | 3 | -6.3% |
| 2024-02 | $-47.28 | 3 | 0.0% | $+0.00 | $-15.76 | 0.00 | normal | SELL | 0.0% | 100.0% | 0.0% | 3 | -6.5% |
| 2024-05 | $-29.00 | 3 | 33.3% | $+4.91 | $-16.95 | 0.29 | normal | BUY | 0.0% | 66.7% | 33.3% | 2 | -5.8% |
| 2024-06 | $-43.17 | 3 | 0.0% | $+0.00 | $-14.39 | 0.00 | normal | SELL | 0.0% | 100.0% | 0.0% | 3 | -4.6% |
| 2024-08 | $-5.48 | 4 | 50.0% | $+4.71 | $-7.46 | 0.63 | normal | BUY | 0.0% | 50.0% | 50.0% | 1 | -4.2% |
| 2024-09 | $-19.99 | 7 | 28.6% | $+12.61 | $-9.04 | 1.39 | normal | BUY | 14.3% | 57.1% | 14.3% | 4 | -4.3% |
| 2025-04 | $-11.52 | 3 | 0.0% | $+0.00 | $-3.84 | 0.00 | risk_off | BUY | 0.0% | 100.0% | 0.0% | 3 | -1.6% |
| 2025-05 | $-1.40 | 4 | 50.0% | $+3.06 | $-3.75 | 0.81 | risk_off | BUY | 25.0% | 50.0% | 25.0% | 2 | -1.0% |
| 2025-06 | $-2.41 | 7 | 57.1% | $+9.92 | $-14.03 | 0.71 | normal | BUY | 14.3% | 42.9% | 42.9% | 1 | -4.3% |
| 2025-07 | $-6.04 | 4 | 50.0% | $+14.10 | $-17.12 | 0.82 | normal | BUY | 25.0% | 50.0% | 25.0% | 1 | -4.4% |
| 2025-11 | $-21.63 | 7 | 57.1% | $+3.84 | $-12.33 | 0.31 | risk_off | BUY | 14.3% | 42.9% | 42.9% | 2 | -4.0% |
| 2026-01 | $-66.47 | 7 | 28.6% | $+16.50 | $-19.89 | 0.83 | normal | BUY | 14.3% | 71.4% | 14.3% | 3 | -8.0% |

## Distribuicao por Regime

| regime | meses | negativos | pct_neg | pnl_total | trades | pnl_por_trade |
|---|---|---|---|---|---|---|---|---|
| normal | 43 | 16 | 37.2% | $+778.04 | 256 | $+3.04 |
| risk_off | 12 | 4 | 33.3% | $+64.08 | 78 | $+0.82 |

> ℹ️ **Nota:** O regime `risk_on` não aparece nesta tabela porque, com o filtro
> `SESSION_FILTER_ALLOW = ["Tokyo"]`, as barras H4 que caem na sessão Tokyo
> simplesmente não coincidiram com os períodos classificados como `risk_on`
> (que exige VIX baixo + correlação gold-equity negativa) no período analisado.
> **Isto não é um bug** — é um artefato real: o regime risk_on foi raro no
> período 2021-2026 filtrado por Tokyo.

## Distribuicao por Direcao Predominante

| direcao | meses | negativos | pct_neg | pnl_total | trades | pnl_por_trade |
|---|---|---|---|---|---|---|
| BUY | 36 | 17 | 47.2% | $+502.68 | 215 | $+2.34 |
| SELL | 19 | 3 | 15.8% | $+339.43 | 119 | $+2.85 |

## Analise de Payoff em Meses Negativos

- **Meses com payoff < 1.0 (ganhadores menores que perdedores):** 19/20
  - Soma do PnL: $-455.73
- **Meses com payoff >= 1.0 (perdeu por volume, nao por qualidade):** 1/20
  - Soma do PnL: $-19.99

### Meses negativos com payoff < 0.5 (pessimos)
| mes | pnl_total | win_rate | payoff | regime_predominante | tp_pct | sl_pct | ptp_pct |
|---|---|---|---|---|---|---|---|
| 2023-02 | $-15.19 | 0.0% | 0.00 | normal | 0.0% | 100.0% | 0.0% |
| 2024-02 | $-47.28 | 0.0% | 0.00 | normal | 0.0% | 100.0% | 0.0% |
| 2024-06 | $-43.17 | 0.0% | 0.00 | normal | 0.0% | 100.0% | 0.0% |
| 2025-04 | $-11.52 | 0.0% | 0.00 | risk_off | 0.0% | 100.0% | 0.0% |
| 2022-03 | $-17.27 | 20.0% | 0.18 | risk_off | 0.0% | 60.0% | 20.0% |
| 2024-05 | $-29.00 | 33.3% | 0.29 | normal | 0.0% | 66.7% | 33.3% |
| 2023-03 | $-24.63 | 33.3% | 0.29 | normal | 0.0% | 66.7% | 33.3% |
| 2025-11 | $-21.63 | 57.1% | 0.31 | risk_off | 14.3% | 42.9% | 42.9% |
| 2023-10 | $-36.49 | 40.0% | 0.33 | normal | 0.0% | 60.0% | 40.0% |
| 2022-11 | $-42.77 | 20.0% | 0.35 | normal | 0.0% | 80.0% | 20.0% |
| 2024-01 | $-47.04 | 33.3% | 0.36 | normal | 0.0% | 66.7% | 33.3% |

## Meses com SL rate > 50%

| mes | pnl_total | win_rate | sl_pct | tp_pct | ptp_pct | regime_predominante | direcao_predominante |
|---|---|---|---|---|---|---|---|
| 2023-02 | $-15.19 | 0.0% | 100.0% | 0.0% | 0.0% | normal | BUY |
| 2024-02 | $-47.28 | 0.0% | 100.0% | 0.0% | 0.0% | normal | SELL |
| 2024-06 | $-43.17 | 0.0% | 100.0% | 0.0% | 0.0% | normal | SELL |
| 2025-04 | $-11.52 | 0.0% | 100.0% | 0.0% | 0.0% | risk_off | BUY |
| 2022-11 | $-42.77 | 20.0% | 80.0% | 0.0% | 20.0% | normal | BUY |
| 2026-01 | $-66.47 | 28.6% | 71.4% | 14.3% | 14.3% | normal | BUY |
| 2023-03 | $-24.63 | 33.3% | 66.7% | 0.0% | 33.3% | normal | BUY |
| 2024-01 | $-47.04 | 33.3% | 66.7% | 0.0% | 33.3% | normal | BUY |
| 2024-05 | $-29.00 | 33.3% | 66.7% | 0.0% | 33.3% | normal | BUY |
| 2022-03 | $-17.27 | 20.0% | 60.0% | 0.0% | 20.0% | risk_off | BUY |
| 2023-10 | $-36.49 | 40.0% | 60.0% | 0.0% | 40.0% | normal | SELL |
| 2024-09 | $-19.99 | 28.6% | 57.1% | 14.3% | 14.3% | normal | BUY |
| 2023-01 | $-26.28 | 44.4% | 55.6% | 22.2% | 22.2% | normal | BUY |

## Clusters de Meses Negativos Consecutivos

- **Maior sequencia de meses negativos consecutivos:** 4
- **Total de clusters (sequencias):** 10

  - **2022-03 a 2022-04** (2 meses, $-21.38)
  - **2023-01 a 2023-03** (3 meses, $-66.11)
  - **2023-10 a 2023-11** (2 meses, $-44.04)
  - **2024-01 a 2024-02** (2 meses, $-94.32)
  - **2024-05 a 2024-06** (2 meses, $-72.17)
  - **2024-08 a 2024-09** (2 meses, $-25.48)
  - **2025-04 a 2025-07** (4 meses, $-21.37)

## Correlacao: Drawdown Intra-Mes vs PnL Mensal

## Insights e Padroes Identificados

### 1. Regime e o principal preditor de meses negativos?

- **normal:** 16/43 meses negativos (37%) | PnL: $+778.04 em 256 trades
- **risk_off:** 4/12 meses negativos (33%) | PnL: $+64.08 em 78 trades

### 2. O bot perde mais comprando ou vendendo?

- **BUY:** 17/36 meses negativos (47%) | PnL: $+502.68
- **SELL:** 3/19 meses negativos (16%) | PnL: $+339.43

### 3. O problema e frequencia ou qualidade?

- **Payoff medio em meses negativos:** 0.49
- **Payoff medio em meses positivos:** 0.95
- **13/20 meses negativos** tem mais de 50% de SL rate (mais stops que TPs)
- **8/20 meses negativos** tem Partial TP > 30% e TP < 20% (Partial TP esta matando os ganhos)

### 4. Existem clusters de perda? (meses negativos consecutivos)

- **Sim.** A maior sequencia e de **4 meses** consecutivos negativos.
- Isso significa que o bot pode ficar ate **4 meses** no vermelho seguido.
- Para um trader real, isso e psicologicamente desafiador — precisa de estomago.

### 5. O que fazer com esses dados?

1. **Filtrar risk_off com mais rigor** — esse regime tem o pior PnL/trade ($+0.82).
   Sugestao: reduzir RISK_PCT_BY_REGIME para risk_off de 3.0 para 50% disso.
2. **Monitorar payoff baixo (< 0.5)** — quando o payoff cai abaixo de 0.5, a qualidade dos trades esta ruim.
3. **Preparar para clusters de ate 4 meses negativos** — ter caixa para aguentar.
4. **Partial TP e o maior vilao nos meses negativos** — em 8/20 meses, muitos trades fecharam em Partial TP em vez de irem ao TP cheio.

---
_Gerado em 2026-07-12 15:35 UTC por analyze_negative_months.py_