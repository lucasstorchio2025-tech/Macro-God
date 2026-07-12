# COMPARATIVO — 3 Melhorias no TS-Momentum

**Gerado em:** 2026-07-12 15:40 UTC

**Período:** 2021-10-27 → 2026-06-30 | **Símbolo:** XAUUSDm | **Período H4:** H4

## Tabela Comparativa

| Configuração | Trades | Sharpe | Sortino | Retorno% | CAGR% | MaxDD% | WinRate | Payoff | Expect$/trade | Final$ |
|---|---|---|---|---|---|---|---|---|---|---|
|   1. BASELINE (atual)            |  381 | 0.26 | 0.21 | +15.7% | +3.0% | -36.4% | 60.6% | 0.86 | $+1.02 | $578.44 |
|   2. Partial TP desligado        |  245 | 0.02 | 0.01 | -6.8% | -1.4% | -50.1% | 38.4% | 1.99 | $+1.21 | $466.13 |
|   3. Lookback reduzido           |  513 | 0.04 | 0.04 | -4.9% | -1.0% | -32.6% | 59.6% | 0.85 | $+0.74 | $475.56 |
| ★ 4. Só Tokyo                    |  334 | 1.14 | 0.86 | +124.5% | +17.8% | -18.9% | 63.2% | 0.94 | $+2.52 | $1122.50 |
|   5. TUDO COMBINADO              |  276 | -0.41 | -0.33 | -39.2% | -9.6% | -67.0% | 36.2% | 1.87 | $+0.34 | $303.78 |
|   6. Tokyo + Lookback            |  426 | -0.41 | -0.33 | -34.5% | -8.2% | -59.9% | 57.5% | 0.79 | $+0.21 | $327.27 |

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
| 1. BASELINE (atual)            |  93 | 133 | 146 |   1 |   8 |
| 2. Partial TP desligado        |  89 |   0 | 147 |   1 |   8 |
| 3. Lookback reduzido           | 124 | 175 | 204 |   2 |   8 |
| 4. Só Tokyo                    |  86 | 116 | 120 |   1 |  11 |
| 5. TUDO COMBINADO              |  92 |   0 | 173 |   1 |  10 |
| 6. Tokyo + Lookback            |  98 | 139 | 178 |   1 |  10 |

## Frequência de Trades

- **1. BASELINE (atual)           **:  381 trades em 4.7 anos → 81/ano → **1.6/semana**
- **2. Partial TP desligado       **:  245 trades em 4.7 anos → 52/ano → **1.0/semana**
- **3. Lookback reduzido          **:  513 trades em 4.7 anos → 109/ano → **2.1/semana**
- **4. Só Tokyo                   **:  334 trades em 4.7 anos → 71/ano → **1.4/semana**
- **5. TUDO COMBINADO             **:  276 trades em 4.7 anos → 59/ano → **1.1/semana**
- **6. Tokyo + Lookback           **:  426 trades em 4.7 anos → 91/ano → **1.7/semana**

## Análise por Regime (config vencedora)

Detalhamento da melhor: **4. Só Tokyo**

| Regime | Trades | Win Rate | P&L Total | Média |
|--------|--------|----------|-----------|-------|
| normal | 256 | 66.8% | $+870.92 | $+3.40 |
| risk_off | 78 | 51.3% | $-28.81 | $-0.37 |

## Ganho sobre o Baseline

- **2. Partial TP desligado       **: Sharpe 0.26→0.02 (-0.25) | CAGR 3.0%→-1.4% (-4.4pp) | Final $578→$466 ($-112)
- **3. Lookback reduzido          **: Sharpe 0.26→0.04 (-0.22) | CAGR 3.0%→-1.0% (-4.0pp) | Final $578→$476 ($-103)
- **4. Só Tokyo                   **: Sharpe 0.26→1.14 (+0.87) | CAGR 3.0%→17.8% (+14.8pp) | Final $578→$1122 ($+544)
- **5. TUDO COMBINADO             **: Sharpe 0.26→-0.41 (-0.68) | CAGR 3.0%→-9.6% (-12.6pp) | Final $578→$304 ($-275)
- **6. Tokyo + Lookback           **: Sharpe 0.26→-0.41 (-0.68) | CAGR 3.0%→-8.2% (-11.2pp) | Final $578→$327 ($-251)

## Veredito

**Melhor configuração:** 4. Só Tokyo

- Sharpe **1.14** (vs 0.26 do baseline)
- CAGR **17.8%** (vs 3.0%)
- Final **$1122** (vs $578)

⚠️ **RESSALVA:** Sharpe 1.14 é no período completo. A validação walk-forward
(WALK_FORWARD_TOKYO.md) mostra OOS médio 0.41 e conclui **OVERFIT**.
**Não ir pra live sem resolver essa contradição.**

## Gráfico

![Equity comparativa](comparativo_equity.png)

---

_Gerado por sweep_comparativo.py_