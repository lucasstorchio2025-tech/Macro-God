# WALK-FORWARD: Validacao 'Tokyo + London'
**Gerado em:** 2026-07-12 16:24 UTC
**Periodo total:** 2021-10-27 -> 2026-07-10
**Janelas:** 8 (IS: 1440b ~6m, OOS: 720b ~3m)

> ⚠️ **AVISO:** Este relatório foi gerado com `MOMENTUM_LOOKBACK_BARS=96`
> (parâmetro reduzido). **Não reflete a config atual do config.py** (que é
> MOMENTUM=264, COOLDOWN=12). Os resultados abaixo são válidos apenas para
> o teste de parâmetros, não para a configuração de produção.
> Para resultados com MOMENTUM=264, ver WALK_FORWARD_TOKYO.md.

## Resultados por Janela
| Janela | IS Periodo | OOS Periodo | IS Sharpe | IS Ret% | IS DD% | OOS Sharpe | OOS Ret% | OOS DD% | OOS Trades | Decaimento |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2021-10-27->2022-09-21 | 2022-09-21->2023-03-06 | -0.32 | -5.9% | -13.1% | 1.03 | +10.4% | -10.5% | 60 | +1.35 ✅ |
| 2 | 2022-04-11->2023-03-06 | 2023-03-06->2023-08-16 | 0.39 | +5.8% | -16.1% | -0.21 | -3.8% | -17.0% | 52 | -0.60 ❌ |
| 3 | 2022-09-21->2023-08-16 | 2023-08-17->2024-01-30 | 0.43 | +7.3% | -16.6% | -1.99 | -18.2% | -21.7% | 47 | -2.42 ❌ |
| 4 | 2023-03-06->2024-01-30 | 2024-01-30->2024-07-11 | -1.12 | -23.3% | -33.3% | -0.55 | -5.3% | -18.9% | 44 | +0.57 ✅ |
| 5 | 2023-08-17->2024-07-11 | 2024-07-11->2024-12-20 | -1.52 | -25.6% | -28.1% | -1.61 | -13.9% | -19.9% | 48 | -0.09 ✅ |
| 6 | 2024-01-30->2024-12-20 | 2024-12-20->2025-06-05 | -1.27 | -20.7% | -31.3% | -1.48 | -10.6% | -12.3% | 55 | -0.21 ✅ |
| 7 | 2024-07-11->2025-06-05 | 2025-06-05->2025-11-14 | -1.65 | -24.3% | -30.1% | 0.08 | -0.4% | -12.6% | 65 | +1.73 ✅ |
| 8 | 2024-12-20->2025-11-14 | 2025-11-14->2026-04-30 | -0.59 | -12.0% | -21.5% | -1.32 | -11.3% | -12.9% | 60 | -0.73 ❌ |

## Estatisticas Agregadas
| Metrica | Tokyo+London | So Tokyo (ref) | Diferenca |
|---------|-------------|----------------|-----------|
| **Sharpe IS medio** | -0.70 | 0.84 | -1.54 |
| **Sharpe OOS medio** | -0.76 | 0.41 | -1.17 |
| **Decaimento medio** | -0.05 | -0.43 | +0.38 |
| **OOS Sharpe > 1.0** | 1/8 | 3/8 | |
| **OOS Sharpe > 0.8** | 1/8 | 3/8 | |
| **OOS Sharpe > 0.6** | 1/8 | 3/8 | |
| **Menor Sharpe OOS** | -1.99 | -1.57 | |
| **Maior Sharpe OOS** | 1.03 | 1.90 | |

## Veredito
### Veredito Tokyo+London
❌ **OVERFIT.** Sharpe OOS medio baixo com decaimento alto.
### Comparacao com 'So Tokyo'
- So Tokyo: OOS medio **0.41** (OVERFIT)
- Tokyo+London: OOS medio **-0.76** (-1.17 vs Tokyo)
- ❌ **Piorou.** So Tokyo ainda e a melhor opcao.

---
_Gerado por run_walkforward_tokyo_london.py_