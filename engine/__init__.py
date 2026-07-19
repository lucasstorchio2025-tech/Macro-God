"""Wealth_Engine v2 — núcleo de análise e backtest + SISTEMA AUTÔNOMO.

Este pacote é independente do bot ao vivo: nada aqui abre ordem.
Tudo é puro cálculo sobre histórico, testável e reproduzível.

Módulos:
    config      — todos os parâmetros num só lugar (sem números mágicos).
    data        — carrega histórico (MT5 + cache local) e COT histórico.
    indicators  — ATR, vol realizada, momentum, correlação rolante.
    regime      — detector de regime por regras + interface plugável (seam p/ HMM).
    sizing      — vol-targeting + cap por correlação + exposição USD agregada.
    signals     — interface de estratégia + TS-momentum + COT-contrarian-zscore.
    backtest    — motor walk-forward com custo de spread e zero lookahead.
    analytics   — Sharpe/Sortino/Calmar/DD/expectancy, quebrado por regime.
    
    ═══ MÓDULOS AUTÔNOMOS (IA COMMANDER) ═══
    autonomous_oracle  — Oráculo macro global: intermarket, liquidez, regimes, tese via LLM.
    self_evolution     — Auto-evolução: tuning de parâmetros, seleção de estratégia, otimização contínua.
    commander          — Comandante autônomo: IA central que decide TUDO (estratégia, risco, timing).
        Uso: commander.cycle(intel, prices, meta, signals, balance, ...)
        Retorna: CommanderOrder com action, direction, risk_pct, reasoning, etc.
"""
