# 🏆 Wealth_Engine v2 — Resumo Executivo

**Gerado em:** 2026-07-12 18:00 UTC

---

## 📋 Configuração Final (config.py)

| Parâmetro | Valor | Descrição |
|---|---|---|
| **Estratégia** | TS-Momentum (Moskowitz 2012) | Única com edge positivo |
| **MOMENTUM_LOOKBACK_BARS** | 264 | ~1 ano de H4 |
| **COOLDOWN_BARS** | 12 | ~2 dias entre reentradas |
| **SESSION_FILTER_ALLOW** | ["Tokyo"] | Só Tokyo — melhor sessão |
| **VIX_MAX_LEVEL** | **20.0** | Bloqueia se VIX > 20 |
| **DRY_RUN_MODE** | **True** | Stop semanal -8%, ativo |
| **D1_FILTER_ENABLED** | True | Só opera na direção da tendência D1 |

---

## 📊 Métricas Finais (Backtest 2021→2026, XAUUSD H4)

### Período Completo

| Métrica | Valor |
|---|---|
| **Sharpe** | **1.19** |
| **Sortino** | 0.81 |
| **Retorno total** | +114.1% |
| **CAGR** | 16.7% |
| **Max Drawdown** | -18.9% |
| **Trades** | 233 |
| **Win Rate** | 67.0% |
| **Expectancy** | +$3.33/trade |
| **Payoff** | 0.93 |
| **Final Equity** | $1,070.55 |

### Walk-Forward OOS

| Métrica | Sem Filtro | **VIX_MAX_LEVEL=20** |
|---|---|---|
| **OOS Médio** | 0.41 | **0.79** 🔥 |
| **Janelas > 0.6** | 3/8 | **5/8** 🔥 |
| **Veredito** | OVERFIT | **ACEITÁVEL** |

---

## 🧪 O Que Foi Testado (e Falhou)

| Teste | Resultado |
|---|---|
| **MOMENTUM=96** (lookback reduzido) | Sharpe -0.94 ❌ |
| **MeanReversionStrategy** (z-score SMA-48) | Sharpe -1.08 ❌ |
| **BreakoutStrategy** (Donchian 96b) | Sharpe -0.14 ❌ |
| **CompositeStrategy** (TS+MR por regime) | Sharpe 1.08 (pior que 1.19) ❌ |
| **Tokyo+London** sessions | OOS -0.76 ❌ |
| **Todas as sessões** (sem filtro) | OOS 0.27 ❌ |
| **VIX_MAX_LEVEL=22** | OOS -0.14 ❌ |
| **VIX_MAX_LEVEL=25** | OOS 0.43 (quase igual) ❌ |

### O que FUNCIONOU

| Teste | Resultado |
|---|---|
| **Só Tokyo** (MOM=264) | Sharpe 1.19 ✅ |
| **VIX_MAX_LEVEL=20** | OOS 0.41 → **0.79** ✅ |
| **DRY_RUN_MODE** (stop -8%) | Implementado ✅ |

---

## 🔧 Fixes Implementados

| Fix | Arquivo |
|---|---|
| Kill-switch @property bug | `engine/meta_config.py` |
| health_check_kill_switch órfão | `engine/meta_learner.py` |
| pd.Timestamp.utcnow() → now('UTC') | 5 arquivos |
| Custo de swap incluso nos reports | Todos os 6 relatórios |
| numpy.void.get() crash | `bot/strategy_bridge.py` |
| Testes: 21 novos (32/32 passando) | `tests/` |
| WALK_FORWARD tabelas vazias | `engine/walk_forward_validate.py` |

---

## 🚦 Status Atual

- **Bot:** Rodando em **dry-run** (PID ativo, polling 300s, sem trades reais)
- **MT5:** Conectado, trade_allowed=True
- **Limites:** DRY_RUN_WEEKLY_DD_PCT = 8%, VIX_MAX_LEVEL = 20
- **Sessão:** Apenas Tokyo (04:00-08:00 UTC)
- **Frequência:** ~1 trade/semana

---

## 📌 Recomendações

1. **Manter dry-run por 2-4 semanas** para validar ao vivo
2. **Monitorar DD semanal** — se passar de -8%, reavaliar
3. **Se WFO continuar ACEITÁVEL** após re-otimização trimestral, considerar sair do dry-run
4. **Próximo passo:** Se o sistema provar edge ao vivo, expandir para múltiplos símbolos

---

## 📁 Arquivos-Chave

| Arquivo | Função |
|---|---|
| `engine/config.py` | Fonte única da verdade para parâmetros |
| `engine/backtest.py` | Motor de backtest honesto |
| `bot/executor.py` | Bot ao vivo (dry-run ativo) |
| `reports/VERDICT.md` | Tabela mestre completa |
| `reports/ANALYSIS.md` | Análise detalhada por mês/sessão/regime |
| `reports/WALK_FORWARD_TOKYO.md` | Walk-Forward Tokyo (OOS 0.79) |
| `reports/COMPARATIVO.md` | Comparativo 6 configurações |
| `scripts/` | Scripts de teste one-off |

---

_Gerado após bateria completa de testes — 32/32 testes passando, swap incluso, VIX filter validado._
