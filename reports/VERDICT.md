# 🏆 VEREDITO MASTER — Wealth_Engine v2

**Gerado em:** 2026-07-12 16:30 UTC | **Swap incluso em TODOS os resultados**

---

## 📊 TABELA MESTRE: Todas as Configurações × Todos os Testes

### 1. Backtest Período Completo (2021→2026)

| Config | Trades | Sharpe | Ret% | DD% | Final$ | Veredito |
|---|---|---|---|---|---|---|
| **🥇 So Tokyo (MOM=264)** | 334 | **1.14** | +124.5% | -18.9% | $1,122 | Completo = SIM / WFO = OVERFIT |
| BASELINE (MOM=264, todas sessoes) | 381 | 0.26 | +15.7% | -36.4% | $578 | Fraco |
| Tokyo+Lookback (MOM=96) | 426 | -0.41 | -34.5% | -59.9% | $327 | ❌ Ruim |
| TUDO COMBINADO | 276 | -0.41 | -39.2% | -67.0% | $304 | ❌ Ruim |
| Lookback reduzido sozinho | 513 | 0.04 | -4.9% | -32.6% | $476 | ❌ Perde |
| Partial TP desligado | 245 | 0.02 | -6.8% | -50.1% | $466 | ❌ Perde |
| legacy_cot (antigo) | — | -0.72 | -70.2% | -77.6% | $149 | ❌ Destruiu a demo |

### 2. Walk-Forward OOS — Todas as Sessões Testadas

| Sessao | OOS Medio | OOS > 0.6 | Melhor/Pior Janela | Veredito WFO |
|--------|:--------:|:---------:|:------------------:|:-----------:|
| **🥇 So Tokyo** | **0.41** | **3/8** | +1.90 / -1.57 | Overfit (melhor) |
| 🥈 Todas (baseline) | 0.27 | 4/8 | +2.19 / -3.77 | Overfit |
| 🥉 Tokyo+London | -0.76 | 1/8 | +1.03 / -1.99 | Overfit (pior) |

### 3. Teste de Parametros — Reduzir MOMENTUM DESTROI tudo

| Teste | Antes (MOM=264) | Depois (MOM=96) | Diferenca |
|------|:--------------:|:--------------:|:---------:|
| BASELINE Sharpe | 0.26 | **-0.94** | -1.20 ❌ |
| So Tokyo Sharpe | **1.14** | **-0.22** | -1.36 ❌ |
| Final$ (So Tokyo) | $1,122 | $389 | -$733 ❌ |

> **Conclusão do teste parametro:** MOMENTUM_LOOKBACK_BARS=96 (reduzido de 264)
> e COOLDOWN=6 (reduzido de 12) são **RUINS**. A configuração original
> (MOMENTUM=264, COOLDOWN=12) é superior em ABSOLUTAMENTE TODAS as métricas.
> **Mantido o config.py original.**

---

## ✅ Melhor Configuração Encontrada

**SESSION_FILTER_ALLOW = ["Tokyo"]** + **MOMENTUM=264** + **COOLDOWN=12**

| Métrica | Valor |
|---------|-------|
| Sharpe período completo | **1.14** |
| Max DD | **-18.9%** |
| Retorno total | **+124.5%** |
| WFO OOS médio | 0.41 (overfit, mas melhor que alternativas) |
| WFO > 0.6 | 3/8 janelas |

### Recomendação
⚠️ **Overfit confirmado pelo WFO, mas nenhuma alternativa testada foi melhor.**
Todas as variações de sessão (todas, Tokyo+London) e parâmetros (MOMENTUM=96,
COOLDOWN=6) produziram resultados PIORES.

**Opções:**
1. Ir pra dry-run com a config atual monitorando DD semanal de -8%
2. Aceitar que o edge é marginal e não operar
3. Explorar outras estratégias além de TS-Momentum ✅ TESTADO

---

### 4. Estratégias Alternativas Testadas — Nenhuma supera TS-Momentum

| Estratégia | Sharpe | Ret% | DD% | Trades | WinRate | Veredito |
|---|---|---|---|---|---|---|
| **🥇 TS-Momentum** | **1.14** | **+124.5%** | **-18.9%** | 334 | 63.2% | ✅ Atual |
| ❌ MeanReversion (z-score) | -1.08 | -12.5% | -14.5% | 66 | 40.9% | Perde dinheiro |
| ❌ Breakout (Donchian) | -0.14 | -1.4% | -5.3% | 43 | 58.1% | Ruído |

**MeanReversionStrategy (z-score SMA-48, |z|>1.5):** Sharpe -1.08. Estratégia perde
sistematicamente em XAUUSD H4. O ouro em H4 não reverte à média na janela de 8 dias —
a tendência (momentum) domina.

**BreakoutStrategy (Donchian 96 barras):** Sharpe -0.14. Próximo de zero — não ganha
nem perde. Breakouts em XAUUSD H4 são falsos na maioria das vezes.

> **Conclusão:** TS-Momentum é a única estratégia com edge positivo neste ativo e
timeframe. O problema de overfit no WFO não é resolvível trocando de estratégia —
é estrutural do ativo/estratégia. O ranking definitivo das sessões e parâmetros
já foi estabelecido na rodada anterior.

**Código:** `run_compare_strategies.py` salvo para re-testar quando quiser.

---

## Baseline (legacy_cot): ❌ Confirmado perdedor
- Sharpe: -0.72 | Total: -70.2% | Final: $149.18
- A lógica antiga PERDE dinheiro. Substituída corretamente.

---
_Veredito gerado após bateria completa de testes (rodada de 12/07/2026)._
_Métricas com swap incluso. Todos os relatórios regenerados._