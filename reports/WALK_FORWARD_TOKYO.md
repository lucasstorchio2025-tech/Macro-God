# WALK-FORWARD: Validacao Configuracao 'So Tokyo'

**Gerado em:** 2026-07-12 15:35 UTC

**Periodo total:** 2021-10-27 -> 2026-07-10

**Janelas:** 8 (IS: 1440b ~6m, OOS: 720b ~3m, Step: 720b ~3m)

## Resultados por Janela

| Janela | IS Periodo | OOS Periodo | Tokyo IS Sharpe | Tokyo IS Ret% | Tokyo IS DD% | Tokyo OOS Sharpe | Tokyo OOS Ret% | Tokyo OOS DD% | OOS Trades | Decaimento | Baseline OOS Sharpe | Ganho vs Base |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2021-10-27->2022-09-21 | 2022-09-21->2023-03-06 | 2.53 | +28.8% | -6.9% | 0.16 | +0.6% | -13.8% | 39 | -2.36 ❌ | -0.11 | +0.27 ✅ |
| 2 | 2022-04-11->2023-03-06 | 2023-03-06->2023-08-16 | 1.44 | +22.9% | -13.6% | 1.53 | +14.8% | -9.2% | 38 | +0.09 ✅ | 1.38 | +0.15 ✅ |
| 3 | 2022-09-21->2023-08-16 | 2023-08-17->2024-01-30 | 0.81 | +13.7% | -19.9% | -0.18 | -2.2% | -11.0% | 31 | -1.00 ❌ | -0.98 | +0.79 ✅ |
| 4 | 2023-03-06->2024-01-30 | 2024-01-30->2024-07-11 | 0.79 | +13.7% | -10.9% | -1.57 | -11.1% | -13.7% | 25 | -2.37 ❌ | -2.49 | +0.91 ✅ |
| 5 | 2023-08-17->2024-07-11 | 2024-07-11->2024-12-20 | -0.69 | -11.1% | -17.1% | 0.06 | -0.1% | -11.3% | 34 | +0.75 ✅ | 0.98 | -0.92 ❌ |
| 6 | 2024-01-30->2024-12-20 | 2024-12-20->2025-06-05 | -0.81 | -11.6% | -19.6% | 1.70 | +11.4% | -7.1% | 33 | +2.52 ✅ | -1.30 | +3.00 ✅ |
| 7 | 2024-07-11->2025-06-05 | 2025-06-05->2025-11-14 | 0.87 | +11.3% | -11.3% | 1.90 | +16.7% | -7.9% | 35 | +1.03 ✅ | 0.12 | +1.77 ✅ |
| 8 | 2024-12-20->2025-11-14 | 2025-11-14->2026-04-30 | 1.79 | +29.8% | -11.6% | -0.27 | -2.2% | -14.5% | 33 | -2.06 ❌ | 1.63 | -1.90 ❌ |

## Estatisticas Agregadas

| Metrica | Valor |
|---------|-------|
| **Sharpe IS medio** | 0.84 |
| **Sharpe OOS medio (Tokyo)** | 0.41 |
| **Sharpe OOS medio (Baseline)** | -0.09 |
| **Decaimento medio** | -0.43 |
| **Janelas com OOS Sharpe > 1.0** | 3/8 |
| **Janelas com OOS Sharpe > 0.8** | 3/8 |
| **Janelas com OOS Sharpe > 0.6** | 3/8 |
| **Menor Sharpe OOS** | -1.57 |
| **Maior Sharpe OOS** | 1.90 |
| **Tokyo superou Baseline em** | 6/8 janelas |

## Veredito

### Veredito Tokyo
❌ **OVERFIT.** Sharpe OOS medio (0.41) com decaimento de -0.43. Nao usar em producao.

### Comparacao com Baseline
✅ **Tokyo SUPEROU o Baseline consistentemente.** Ganho medio de 0.51 Sharpe.

## Conclusao Final

❌ **NAO IMPLEMENTAR.**\n\nO Sharpe 1.33 observado no periodo completo foi produto de overfit. A configuracao 'So Tokyo' nao resiste a validacao walk-forward.

---
_Gerado por walk_forward_tokyo.py_