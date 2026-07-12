# COMPARATIVO — 3 Melhorias no TS-Momentum

**Gerado em:** 2026-07-12 16:57 UTC

**Período:** 2021-10-27 → 2026-06-30 | **Símbolo:** XAUUSDm | **Período H4:** H4

## Tabela Comparativa

| Configuração | Trades | Sharpe | Sortino | Retorno% | CAGR% | MaxDD% | WinRate | Payoff | Expect$/trade | Final$ |
|---|---|---|---|---|---|---|---|---|---|---|
|   1. BASELINE (atual)            |  275 | 0.05 | 0.03 | -1.9% | -0.4% | -40.3% | 60.4% | 0.84 | $+0.92 | $490.55 |
|   2. Partial TP desligado        |  178 | -0.10 | -0.07 | -14.5% | -3.1% | -51.1% | 38.2% | 2.01 | $+1.23 | $427.46 |
|   3. Lookback reduzido           |  356 | 0.23 | 0.19 | +13.2% | +2.5% | -30.9% | 61.0% | 0.85 | $+1.16 | $565.78 |
| ★ 4. Só Tokyo                    |  233 | 1.19 | 0.81 | +114.1% | +16.7% | -18.9% | 67.0% | 0.93 | $+3.33 | $1070.55 |
|   5. TUDO COMBINADO              |  191 | -0.57 | -0.41 | -44.3% | -11.2% | -63.8% | 36.6% | 1.80 | $+0.21 | $278.60 |
|   6. Tokyo + Lookback            |  294 | -0.38 | -0.27 | -29.6% | -6.9% | -50.9% | 58.5% | 0.77 | $+0.26 | $352.09 |

## Configurações Testadas

- **1. BASELINE (atual)**: Configuração atual do config.py
- **2. Partial TP desligado**: PARTIAL_TP_FRACTION=0.0 — trades correm até o TP cheio
- **3. Lookback reduzido**: MOMENTUM=96 (de 264), COOLDOWN=6 (de 12) — +trades
- **4. Só Tokyo**: SESSION_FILTER_ALLOW = só Tokyo (melhor sessão)
- **5. TUDO COMBINADO**: Todas as 3 melhorias juntas
- **6. Tokyo + Lookback**: Tokyo + MOMENTUM=96 + COOLDOWN=6 — sinal mais rapido na melhor sessao

## Detalhamento por Motivo de Saída

| Configuração | TP | Partial TP | SL | TIME | REGIME_EXIT |
|---|---|---|---|---|---|
| 1. BASELINE (atual)            |  68 |  97 | 108 |   0 |   2 |
| 2. Partial TP desligado        |  67 |   0 | 109 |   0 |   2 |
| 3. Lookback reduzido           |  89 | 125 | 137 |   2 |   3 |
| 4. Só Tokyo                    |  68 |  85 |  76 |   1 |   3 |
| 5. TUDO COMBINADO              |  66 |   0 | 119 |   2 |   4 |
| 6. Tokyo + Lookback            |  70 |  98 | 120 |   2 |   4 |

## Frequência de Trades

- **1. BASELINE (atual)           **:  275 trades em 4.7 anos → 59/ano → **1.1/semana**
- **2. Partial TP desligado       **:  178 trades em 4.7 anos → 38/ano → **0.7/semana**
- **3. Lookback reduzido          **:  356 trades em 4.7 anos → 76/ano → **1.5/semana**
- **4. Só Tokyo                   **:  233 trades em 4.7 anos → 50/ano → **1.0/semana**
- **5. TUDO COMBINADO             **:  191 trades em 4.7 anos → 41/ano → **0.8/semana**
- **6. Tokyo + Lookback           **:  294 trades em 4.7 anos → 63/ano → **1.2/semana**

## Análise por Regime (config vencedora)

Detalhamento da melhor: **4. Só Tokyo**

| Regime | Trades | Win Rate | P&L Total | Média |
|--------|--------|----------|-----------|-------|
| normal | 209 | 68.9% | $+782.08 | $+3.74 |
| risk_off | 24 | 50.0% | $-6.27 | $-0.26 |

## Ganho sobre o Baseline

- **2. Partial TP desligado       **: Sharpe 0.05→-0.10 (-0.15) | CAGR -0.4%→-3.1% (-2.7pp) | Final $491→$427 ($-63)
- **3. Lookback reduzido          **: Sharpe 0.05→0.23 (+0.19) | CAGR -0.4%→2.5% (+2.9pp) | Final $491→$566 ($+75)
- **4. Só Tokyo                   **: Sharpe 0.05→1.19 (+1.14) | CAGR -0.4%→16.7% (+17.1pp) | Final $491→$1071 ($+580)
- **5. TUDO COMBINADO             **: Sharpe 0.05→-0.57 (-0.62) | CAGR -0.4%→-11.2% (-10.8pp) | Final $491→$279 ($-212)
- **6. Tokyo + Lookback           **: Sharpe 0.05→-0.38 (-0.43) | CAGR -0.4%→-6.9% (-6.5pp) | Final $491→$352 ($-138)

## Veredito

**Melhor configuração:** 4. Só Tokyo

- Sharpe **1.19** (vs 0.05 do baseline)
- CAGR **16.7%** (vs -0.4%)
- Final **$1071** (vs $491)

✅ **Recomendação:** Sharpe > 1.0. Esta configuração pode ir para dry-run.

## Gráfico

![Equity comparativa](comparativo_equity.png)

---

_Gerado por sweep_comparativo.py_