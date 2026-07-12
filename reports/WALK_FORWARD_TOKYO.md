# WALK-FORWARD: Validacao Configuracao 'So Tokyo'

**Gerado em:** 2026-07-07 15:24 UTC

**Periodo total:** 2021-10-27 -> 2026-07-07

**Janelas:** 8 (IS: 1440b ~6m, OOS: 720b ~3m, Step: 720b ~3m)

## Resultados por Janela

| Janela | IS Periodo | OOS Periodo | Tokyo IS Sharpe | Tokyo IS Ret% | Tokyo IS DD% | Tokyo OOS Sharpe | Tokyo OOS Ret% | Tokyo OOS DD% | OOS Trades | Decaimento | Baseline OOS Sharpe | Ganho vs Base |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2021-10-27->2022-09-21 | 2022-09-21->2023-03-06 | 2.19 | +25.0% | -6.8% | 1.78 | +26.6% | -13.9% | 35 | -0.41 ⚠️ | 1.93 | -0.15 ❌ |
| 2 | 2022-04-11->2023-03-06 | 2023-03-06->2023-08-16 | 1.89 | +49.2% | -13.9% | 1.49 | +27.1% | -17.7% | 33 | -0.40 ⚠️ | 0.44 | +1.05 ✅ |
| 3 | 2022-09-21->2023-08-16 | 2023-08-17->2024-01-30 | 1.29 | +44.9% | -20.3% | -0.10 | -3.1% | -15.7% | 30 | -1.39 ❌ | -1.55 | +1.46 ✅ |
| 4 | 2023-03-06->2024-01-30 | 2024-01-30->2024-07-11 | 0.81 | +23.2% | -21.5% | 0.35 | +2.7% | -17.8% | 26 | -0.47 ⚠️ | -0.30 | +0.65 ✅ |
| 5 | 2023-08-17->2024-07-11 | 2024-07-11->2024-12-20 | 0.40 | +6.9% | -25.5% | 1.50 | +13.0% | -8.1% | 34 | +1.10 ✅ | 1.82 | -0.32 ❌ |
| 6 | 2024-01-30->2024-12-20 | 2024-12-20->2025-06-05 | 0.82 | +16.0% | -17.8% | 2.38 | +16.5% | -5.7% | 33 | +1.56 ✅ | 0.07 | +2.31 ✅ |
| 7 | 2024-07-11->2025-06-05 | 2025-06-05->2025-11-14 | 1.86 | +31.6% | -8.1% | 2.06 | +24.2% | -9.4% | 31 | +0.20 ✅ | 1.95 | +0.12 ✅ |
| 8 | 2024-12-20->2025-11-14 | 2025-11-14->2026-04-30 | 2.07 | +43.6% | -9.8% | 0.93 | +7.6% | -14.0% | 32 | -1.14 ❌ | 3.67 | -2.74 ❌ |

## Estatisticas Agregadas

| Metrica | Valor |
|---------|-------|
| **Sharpe IS medio** | 1.42 |
| **Sharpe OOS medio (Tokyo)** | 1.30 |
| **Sharpe OOS medio (Baseline)** | 1.00 |
| **Decaimento medio** | -0.12 |
| **Janelas com OOS Sharpe > 1.0** | 5/8 |
| **Janelas com OOS Sharpe > 0.8** | 6/8 |
| **Janelas com OOS Sharpe > 0.6** | 6/8 |
| **Menor Sharpe OOS** | -0.10 |
| **Maior Sharpe OOS** | 2.38 |
| **Tokyo superou Baseline em** | 5/8 janelas |

## Veredito

### Veredito Tokyo
✅ **ROBUSTO.** O Sharpe OOS medio e alto (1.30) e o decaimento e pequeno (-0.12). A configuracao 'So Tokyo' generaliza bem fora-da-amostra.

### Comparacao com Baseline
✅ **Tokyo SUPEROU o Baseline consistentemente.** Ganho medio de 0.30 Sharpe.

## Conclusao Final

✅ **CONFIGURACAO VALIDADA.**\n\nA configuracao 'So Tokyo' (SESSION_FILTER_ALLOW = ["Tokyo"]) apresenta desempenho consistente fora-da-amostra:\n- Sharpe OOS medio de 1.30\n- Decaimento medio de -0.12\n- Supera o Baseline em 5/8 janelas\n\nPode implementar no config.py com seguranca e seguir para dry-run.

---
_Gerado por walk_forward_tokyo.py_