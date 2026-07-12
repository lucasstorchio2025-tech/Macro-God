# WALK-FORWARD: Validacao 'Tokyo + London'\n
**Gerado em:** 2026-07-12 16:17 UTC\n
**Periodo total:** 2021-10-27 -> 2026-07-10\n
**Janelas:** 8 (IS: 1440b ~6m, OOS: 720b ~3m)\n

## Resultados por Janela\n
| Janela | IS Periodo | OOS Periodo | IS Sharpe | IS Ret% | IS DD% | OOS Sharpe | OOS Ret% | OOS DD% | OOS Trades | Decaimento |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2021-10-27->2022-09-21 | 2022-09-21->2023-03-06 | 1.44 | +15.9% | -10.5% | -0.07 | -1.4% | -10.1% | 43 | -1.51 ❌ |
| 2 | 2022-04-11->2023-03-06 | 2023-03-06->2023-08-16 | 0.72 | +10.3% | -10.0% | 1.93 | +17.6% | -9.9% | 38 | +1.21 ✅ |
| 3 | 2022-09-21->2023-08-16 | 2023-08-17->2024-01-30 | 0.73 | +11.7% | -17.3% | -1.93 | -15.4% | -17.5% | 36 | -2.66 ❌ |
| 4 | 2023-03-06->2024-01-30 | 2024-01-30->2024-07-11 | 0.26 | +3.0% | -16.4% | -1.29 | -10.3% | -15.9% | 29 | -1.55 ❌ |
| 5 | 2023-08-17->2024-07-11 | 2024-07-11->2024-12-20 | -1.74 | -25.2% | -29.0% | 0.26 | +1.3% | -14.5% | 37 | +2.00 ✅ |
| 6 | 2024-01-30->2024-12-20 | 2024-12-20->2025-06-05 | -0.59 | -9.5% | -21.2% | -0.91 | -6.4% | -11.4% | 41 | -0.32 ⚠️ |
| 7 | 2024-07-11->2025-06-05 | 2025-06-05->2025-11-14 | -0.31 | -5.1% | -14.5% | 0.86 | +7.5% | -13.5% | 38 | +1.17 ✅ |
| 8 | 2024-12-20->2025-11-14 | 2025-11-14->2026-04-30 | 0.02 | -1.1% | -22.2% | 3.00 | +20.3% | -4.5% | 44 | +2.99 ✅ |

## Estatisticas Agregadas\n
| Metrica | Tokyo+London | So Tokyo (ref) | Diferenca |
|---------|-------------|----------------|-----------|
| **Sharpe IS medio** | 0.07 | 0.84 | -0.77 |
| **Sharpe OOS medio** | 0.23 | 0.41 | -0.18 |
| **Decaimento medio** | +0.17 | -0.43 | +0.60 |
| **OOS Sharpe > 1.0** | 2/8 | 3/8 | |
| **OOS Sharpe > 0.8** | 3/8 | 3/8 | |
| **OOS Sharpe > 0.6** | 3/8 | 3/8 | |
| **Menor Sharpe OOS** | -1.93 | -1.57 | |
| **Maior Sharpe OOS** | 3.00 | 1.90 | |

## Veredito\n
### Veredito Tokyo+London\n❌ **OVERFIT.** Sharpe OOS medio baixo com decaimento alto.\n
### Comparacao com 'So Tokyo'\n
- So Tokyo: OOS medio **0.41** (OVERFIT)
- Tokyo+London: OOS medio **0.23** (-0.18 vs Tokyo)
- ❌ **Piorou.** So Tokyo ainda e a melhor opcao.

---
_Gerado por run_walkforward_tokyo_london.py_