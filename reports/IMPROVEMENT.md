# CICLO DE MELHORIA CONTINUA
**Gerado em:** 2026-07-08 15:51 UTC
**Ciclo:** #4
**Duração:** 0.2s

## Estado Atual do Sistema

| Métrica | Valor |
|---------|-------|
| Último run do bot | 2026-07-08T15:51:01.581044+00:00 |
| Saldo início do dia | $409.99 |
| Trades abertos (total) | 10 |
| Trades fechados | 0 |
| P&L Real | $+0.00 |
| Win Rate Real | 100.0% |

## Backtest (ts_momentum)

| Métrica | Valor |
|---------|-------|
| Trades | ? |
| Retorno | +198.2% |
| Sharpe | 1.51 |
| Max DD | -15.4% |
| Win Rate | 63.2% |
| Expectancy | $+2.97/trade |
| Equidade Final | $1491.01 |

## Decisoes Recentes

**Total de decisões:** 583
- [OK] Trades abertos: 1
- [DRY] Dry-run: 1
- [BLOQ] Bloqueados por filtro: 559
  - exposure_check: 215
  - max_positions: 13
  - risk_cap: 1
  - RR abaixo do mínimo: 1

## Recomendacoes

[CRITICO] exposure_check bloqueou 215x. Isso indica que o TOTAL_RISK_CAP_PCT esta muito baixo para o lote minimo do simbolo. Verificar RISK_OVERRIDE_PCT e TOTAL_RISK_CAP_PCT no config.py.

## Historico de Ciclos

| Ciclo | Data | Sharpe BT | Retorno BT | P&L Real | Ações |
|-------|------|-----------|------------|----------|-------|
| 1 | 2026-07-07T10:30 | 0.83 | +131.7% | $-89.93 | 3 rec |
| 2 | 2026-07-07T10:31 | 0.83 | +131.7% | $-89.93 | 3 rec |
| 3 | 2026-07-08T15:32 | 1.51 | +198.2% | $-89.93 | 2 rec |

---
_Relatório gerado por auto_improve.py em 2026-07-08 15:51 UTC_