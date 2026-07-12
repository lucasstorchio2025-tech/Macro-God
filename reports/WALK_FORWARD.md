# WALK-FORWARD VALIDATION
**Gerado em:** 2026-07-06 14:30 UTC

## Objetivo
Validar que os parametros otimizados do LiquidityStressSignal 
(**DXY=0.5%, VIX=10.0%**) nao sao overfit no periodo completo,
testando seu desempenho fora-da-amostra (OOS) em janelas sequenciais.

## Periodo Analisado
- Barras H4 disponiveis: 7488
- Periodo completo: 2021-10-27 -> 2026-07-06
- Janelas walk-forward: 8

## Validacao 1: Parametros Fixos em OOS
Testa os parametros **DXY=0.5%, VIX=10.0%** em cada janela, 
comparando desempenho IS (treino) vs OOS (teste).

*Criterio: se Sharpe OOS > 0.8 na maioria das janelas e o decaimento medio e pequeno, os parametros sao robustos.*

### Tabela por Janela

| Janela | IS Periodo | OOS Periodo | IS Sharpe | IS Ret% | IS DD% | OOS Sharpe | OOS Ret% | OOS DD% | Decaimento |
|---|---|---|---|---|---|---|---|---|---|
| 1 |  |  |  |  |  |  |  |  |  |
| 2 |  |  |  |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |  |  |  |
| 4 |  |  |  |  |  |  |  |  |  |
| 5 |  |  |  |  |  |  |  |  |  |
| 6 |  |  |  |  |  |  |  |  |  |
| 7 |  |  |  |  |  |  |  |  |  |
| 8 |  |  |  |  |  |  |  |  |  |

### Estatisticas Agregadas
- **Sharpe IS medio:** 0.39
- **Sharpe OOS medio:** 0.90
- **Decaimento medio:** +0.51
- **Janelas com OOS Sharpe > 0.8:** 4/8
- **Janelas com OOS Sharpe > 0.6:** 4/8
- **Menor Sharpe OOS:** -0.83
- **Maior Sharpe OOS:** 3.33

**Veredito:** ✅ **ROBUSTO.** Os parametros generalizam bem fora-da-amostra.

## Baseline: LiquidityStress DESATIVADO
Compara o desempenho OOS com sinal (DXY=0.5%, VIX=10.0%) vs 
sem sinal (thresholds inatingiveis DXY=99%, VIX=99%).

*Se o sinal adiciona valor, o Sharpe com sinal deve ser 
superior ao sem sinal na maioria das janelas.*

### Tabela por Janela

| Janela | OOS Periodo | Com Sinal Sharpe | Com Sinal Ret% | Sem Sinal Sharpe | Sem Sinal Ret% | Ganho Sharpe |
|---|---|---|---|---|---|---|
| 1 |  |  |  |  |  |  |
| 2 |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |
| 4 |  |  |  |  |  |  |
| 5 |  |  |  |  |  |  |
| 6 |  |  |  |  |  |  |
| 7 |  |  |  |  |  |  |
| 8 |  |  |  |  |  |  |

### Estatisticas
- **Ganho medio de Sharpe:** +0.00
- **Janelas onde sinal > sem sinal:** 0/8
**Veredito:** ❌ **SINAL NAO AGREGA VALOR.** O baseline sem LiquidityStress e melhor ou equivalente na maioria das janelas.

## Validacao 2: Sweep por Janela
Para cada janela, varre **todos os thresholds** no IS e testa 
o melhor encontrado no OOS. Compara com o threshold fixo 0.5/10.0.

*Se os thresholds 'vencedores' por janela se agrupam ao redor 
de DXY=0.5% e VIX=10.0%, o sweep original nao foi overfit.*

### Tabela por Janela

| Janela | IS Periodo | OOS Periodo | Melhor IS | IS Sharpe | OOS Sweep Sharpe | OOS Sweep Ret% | OOS Fixo Sharpe | OOS Fixo Ret% | Melhor |
|---|---|---|---|---|---|---|---|---|---|
| 1 |  |  |  |  |  |  |  |  | empate |
| 2 |  |  |  |  |  |  |  |  | empate |
| 3 |  |  |  |  |  |  |  |  | empate |
| 4 |  |  |  |  |  |  |  |  | empate |
| 5 |  |  |  |  |  |  |  |  | empate |
| 6 |  |  |  |  |  |  |  |  | empate |
| 7 |  |  |  |  |  |  |  |  | empate |
| 8 |  |  |  |  |  |  |  |  | empate |

### Distribuicao dos Thresholds Vencedores por Janela
- Janela 1: DXY=0.1%  VIX=3.0%   
- Janela 1: DXY=0.1%  VIX=3.0%   
- Janela 1: DXY=0.1%  VIX=3.0%   
- Janela 1: DXY=0.1%  VIX=3.0%   
- Janela 1: DXY=0.1%  VIX=3.0%   
- Janela 1: DXY=0.1%  VIX=3.0%   
- Janela 1: DXY=0.1%  VIX=3.0%   
- Janela 1: DXY=0.1%  VIX=3.0%   

- **Thresholds exatos (DXY=0.5%, VIX=10.0%) vencedores:** 0/8 janelas
- **Thresholds proximos (DXY≈0.5%, VIX≈10.0%):** 0/8 janelas

### Comparacao no OOS
- **Media Sweep OOS:** 0.90
- **Media Fixo OOS:** 0.90
- Praticamente empatados (+0.00) — 
  o parametro fixo 0.5/10.0 e tao bom quanto re-otimizar.

**Veredito:** ❌ **OVERFIT.** Cada janela elege thresholds diferentes — sweep geral e instavel.

## Conclusao Final

### Metricas Consolidadas
- **OOS Sharpe medio (parametros fixos):** 0.90
- **Janelas com Sharpe > 0.6:** 4/8
- **Decaimento medio IS->OOS:** +0.51

### Veredito Final
⚠️ **PARCIALMENTE ROBUSTO — USAR COM CAUTELA.**

O desempenho OOS e razoavel, mas ha variacao significativa entre janelas. Recomendacoes:
- Usar os parametros 0.5/10.0 mas monitorar o drawdown de perto
- Considerar re-otimizacao periodica (a cada 3-6 meses)
- Implementar um stop-loss de regime (se Sharpe rolling cair de 0.5, pausar)

---
_Gerado por walk_forward_validate.py_