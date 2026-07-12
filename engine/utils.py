"""utils.py — funções utilitárias compartilhadas entre os módulos do engine.

Centraliza funções que apareciam duplicadas em backtest.py, full_analysis.py
e executor.py. Evita drift entre as cópias.
"""
from __future__ import annotations

import pandas as pd


# ═════════════════════════════ SESSÃO FOREX ═════════════════════════════
def session_of(ts) -> str:
    """Classifica a hora UTC numa sessão de forex.

    Aceita pd.Timestamp ou datetime.datetime — ambos têm .hour.
    Usado por backtest.py, full_analysis.py e executor.py.

    Usado por backtest.py, full_analysis.py e executor.py para consistência
    nos relatórios e no filtro de sessão (SESSION_FILTER_ALLOW).

    Classificação (horário UTC do candle H4):
      - Sydney:    0h-4h
      - Tokyo:     4h-8h
      - London:    7h-16h  (sobrepõe NY 13h-15h)
      - NewYork:  13h-22h
      - Off:      22h-24h  (transição residual)
    """
    h = ts.hour
    if 0 <= h < 4:
        return "Sydney"
    elif 4 <= h < 8:
        return "Tokyo"
    elif 7 <= h < 16:
        return "London"
    elif 13 <= h < 22:
        return "NewYork"
    else:
        return "Off"


# ═════════════════════════════ ATR MULT POR REGIME ═════════════════════════════
ATR_STOP_MULT_LABELS: dict[str, str] = {
    "risk_on":  "2.0×ATR (largo, winners correm)",
    "normal":   "1.5×ATR (padrão)",
    "risk_off": "1.0×ATR (apertado, sai rápido)",
    "crisis":   "1.5×ATR (não usado — exposição 0)",
}

ATR_STOP_MULT_VALUES: dict[str, float] = {
    "risk_on":  2.0,
    "normal":   1.5,
    "risk_off": 1.0,
    "crisis":   1.5,
}

# Mapa reverso: valor float → label amigável (para análise de distribuição)
ATR_MULT_TO_LABEL: dict[float, str] = {
    2.0: "risk_on (2.0×ATR, largo)",
    1.5: "normal/crisis (1.5×ATR, padrão)",
    1.0: "risk_off (1.0×ATR, apertado)",
}


__all__ = [
    "session_of",
    "ATR_STOP_MULT_LABELS",
    "ATR_STOP_MULT_VALUES",
    "ATR_MULT_TO_LABEL",
]
