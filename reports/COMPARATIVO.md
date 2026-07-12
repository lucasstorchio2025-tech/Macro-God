# COMPARATIVO — 3 Melhorias no TS-Momentum

**Gerado em:** 2026-07-07 15:36 UTC

**Período:** 2021-10-27 → 2026-06-30 | **Símbolo:** XAUUSDm | **Período H4:** H4

## Tabela Comparativa

| Configuração | Trades | Sharpe | Sortino | Retorno% | CAGR% | MaxDD% | WinRate | Payoff | Expect$/trade | Final$ |
|---|---|---|---|---|---|---|---|---|---|---|
|   1. BASELINE (atual)            |  349 | 0.83 | 0.67 | +131.7% | +18.6% | -39.8% | 59.3% | 0.94 | $+1.89 | $1158.38 |
|   2. Partial TP desligado        |  229 | 0.78 | 0.63 | +139.1% | +19.3% | -46.4% | 37.6% | 2.26 | $+3.04 | $1195.43 |
|   3. Lookback reduzido           |  458 | 0.92 | 0.85 | +181.4% | +23.3% | -26.9% | 59.2% | 0.94 | $+1.98 | $1407.00 |
| ★ 4. Só Tokyo                    |  318 | 1.33 | 0.97 | +302.6% | +32.6% | -25.5% | 63.5% | 0.91 | $+4.76 | $2013.16 |
|   5. TUDO COMBINADO              |  254 | 0.86 | 0.69 | +181.6% | +23.3% | -37.4% | 39.0% | 1.99 | $+3.57 | $1407.87 |
|   6. Tokyo + Lookback            |  387 | 0.80 | 0.64 | +135.4% | +18.9% | -33.0% | 59.4% | 0.85 | $+1.75 | $1177.10 |

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
| 1. BASELINE (atual)            |  82 | 118 | 137 |   4 |   8 |
| 2. Partial TP desligado        |  79 |   0 | 138 |   4 |   8 |
| 3. Lookback reduzido           | 109 | 155 | 184 |   2 |   8 |
| 4. Só Tokyo                    |  81 | 111 | 113 |   1 |  12 |
| 5. TUDO COMBINADO              |  91 |   0 | 152 |   1 |  10 |
| 6. Tokyo + Lookback            |  93 | 129 | 154 |   1 |  10 |

## Frequência de Trades

- **1. BASELINE (atual)           **:  349 trades em 4.7 anos → 74/ano → **1.4/semana**
- **2. Partial TP desligado       **:  229 trades em 4.7 anos → 49/ano → **0.9/semana**
- **3. Lookback reduzido          **:  458 trades em 4.7 anos → 97/ano → **1.9/semana**
- **4. Só Tokyo                   **:  318 trades em 4.7 anos → 68/ano → **1.3/semana**
- **5. TUDO COMBINADO             **:  254 trades em 4.7 anos → 54/ano → **1.0/semana**
- **6. Tokyo + Lookback           **:  387 trades em 4.7 anos → 82/ano → **1.6/semana**

## Análise por Regime (config vencedora)

Detalhamento da melhor: **4. Só Tokyo**

| Regime | Trades | Win Rate | P&L Total | Média |
|--------|--------|----------|-----------|-------|
| normal | 134 | 67.2% | $+810.17 | $+6.05 |
| risk_off | 79 | 54.4% | $-26.93 | $-0.34 |
| risk_on | 105 | 65.7% | $+729.92 | $+6.95 |

## Ganho sobre o Baseline

- **2. Partial TP desligado       **: Sharpe 0.83→0.78 (-0.05) | CAGR 18.6%→19.3% (+0.8pp) | Final $1158→$1195 ($+37)
- **3. Lookback reduzido          **: Sharpe 0.83→0.92 (+0.08) | CAGR 18.6%→23.3% (+4.8pp) | Final $1158→$1407 ($+249)
- **4. Só Tokyo                   **: Sharpe 0.83→1.33 (+0.49) | CAGR 18.6%→32.6% (+14.1pp) | Final $1158→$2013 ($+855)
- **5. TUDO COMBINADO             **: Sharpe 0.83→0.86 (+0.03) | CAGR 18.6%→23.3% (+4.8pp) | Final $1158→$1408 ($+249)
- **6. Tokyo + Lookback           **: Sharpe 0.83→0.80 (-0.03) | CAGR 18.6%→18.9% (+0.4pp) | Final $1158→$1177 ($+19)

## Veredito

**Melhor configuração:** 4. Só Tokyo

- Sharpe **1.33** (vs 0.83 do baseline)
- CAGR **32.6%** (vs 18.6%)
- Final **$2013** (vs $1158)

✅ **Recomendação:** Sharpe > 1.0. Esta configuração pode ir para dry-run.

## Gráfico

![Equity comparativa](comparativo_equity.png)

---

_Gerado por sweep_comparativo.py_