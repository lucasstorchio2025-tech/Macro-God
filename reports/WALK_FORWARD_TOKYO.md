# WALK-FORWARD: Validacao Configuracao 'So Tokyo'

**Gerado em:** 2026-07-12 16:57 UTC

**Periodo total:** 2021-10-27 -> 2026-07-10

**Janelas:** 8 (IS: 1440b ~6m, OOS: 720b ~3m, Step: 720b ~3m)

## Resultados por Janela

| Janela | IS Periodo | OOS Periodo | Tokyo IS Sharpe | Tokyo IS Ret% | Tokyo IS DD% | Tokyo OOS Sharpe | Tokyo OOS Ret% | Tokyo OOS DD% | OOS Trades | Decaimento | Baseline OOS Sharpe | Ganho vs Base |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2021-10-27->2022-09-21 | 2022-09-21->2023-03-06 | 1.29 | +5.0% | -2.3% | -1.32 | -5.6% | -9.4% | 9 | -2.61 ❌ | -1.21 | -0.12 ❌ |
| 2 | 2022-04-11->2023-03-06 | 2023-03-06->2023-08-16 | -0.93 | -5.6% | -9.4% | 2.30 | +23.4% | -6.8% | 35 | +3.24 ✅ | 1.84 | +0.46 ✅ |
| 3 | 2022-09-21->2023-08-16 | 2023-08-17->2024-01-30 | 0.70 | +9.5% | -13.7% | 1.40 | +10.1% | -6.4% | 30 | +0.70 ✅ | -0.67 | +2.07 ✅ |
| 4 | 2023-03-06->2024-01-30 | 2024-01-30->2024-07-11 | 1.92 | +37.7% | -6.8% | -1.57 | -11.1% | -13.7% | 25 | -3.50 ❌ | -2.49 | +0.91 ✅ |
| 5 | 2023-08-17->2024-07-11 | 2024-07-11->2024-12-20 | 0.14 | +1.0% | -14.7% | -0.04 | -0.8% | -11.9% | 34 | -0.18 ✅ | 0.53 | -0.57 ❌ |
| 6 | 2024-01-30->2024-12-20 | 2024-12-20->2025-06-05 | -0.85 | -12.4% | -20.2% | 1.76 | +11.7% | -6.6% | 24 | +2.61 ✅ | -1.40 | +3.16 ✅ |
| 7 | 2024-07-11->2025-06-05 | 2025-06-05->2025-11-14 | 0.82 | +10.8% | -11.9% | 1.90 | +15.6% | -5.6% | 31 | +1.08 ✅ | -0.37 | +2.27 ✅ |
| 8 | 2024-12-20->2025-11-14 | 2025-11-14->2026-04-30 | 1.80 | +28.8% | -9.7% | 1.88 | +12.2% | -9.0% | 25 | +0.08 ✅ | 1.50 | +0.38 ✅ |

## Estatisticas Agregadas

| Metrica | Valor |
|---------|-------|
| **Sharpe IS medio** | 0.61 |
| **Sharpe OOS medio (Tokyo)** | 0.79 |
| **Sharpe OOS medio (Baseline)** | -0.28 |
| **Decaimento medio** | +0.18 |
| **Janelas com OOS Sharpe > 1.0** | 5/8 |
| **Janelas com OOS Sharpe > 0.8** | 5/8 |
| **Janelas com OOS Sharpe > 0.6** | 5/8 |
| **Menor Sharpe OOS** | -1.57 |
| **Maior Sharpe OOS** | 2.30 |
| **Tokyo superou Baseline em** | 6/8 janelas |

## Veredito

### Veredito Tokyo
⚠️ **ACEITAVEL.** O Sharpe OOS medio (0.79) e razoavel, mas ha variacao entre janelas (decaimento +0.18). Usar com cautela.

### Comparacao com Baseline
✅ **Tokyo SUPEROU o Baseline consistentemente.** Ganho medio de 1.07 Sharpe.

## Conclusao Final

⚠️ **ACEITAVEL COM CAUTELA.**\n\nA configuracao 'So Tokyo' apresenta desempenho razoavel fora-da-amostra, mas com variacao entre janelas. Recomendacoes:\n- Implementar no config.py mas monitorar o drawdown\n- Se o Sharpe cair abaixo de 0.5 em producao, reverter\n- Considerar re-otimizacao periodica

---
_Gerado por walk_forward_tokyo.py_