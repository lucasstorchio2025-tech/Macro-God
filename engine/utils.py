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

    Classificação (horário UTC):
      - Sydney:   21h-24h (abre ~22:00 UTC, AEST sem DST)
      - Tokyo:     0h-7h  (sessão asiática + overlap Sydney)
      - London:    7h-13h (Europa, BST=UTC+1)
      - NewYork:  13h-21h (EUA, EDT=UTC-4)
      Sem "Off" — forex é 24h em dias úteis.
    """
    h = ts.hour
    if 21 <= h < 24:
        return "Sydney"        # Sydney abre ~22:00 UTC (AEST, sem DST)
    elif 0 <= h < 7:
        return "Tokyo"         # Tokyo 00:00-06:00 UTC + overlap Sydney
    elif 7 <= h < 13:
        return "London"        # Europa (BST=UTC+1: 07:00-16:00)
    else:  # 13 <= h < 21
        return "NewYork"       # EUA (EDT=UTC-4: 12:00-21:00)


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
