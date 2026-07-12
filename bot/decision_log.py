"""
decision_log.py — logging ESTRUTURADO de cada decisão do bot.

Cada linha do decision_log.jsonl documenta:
  - Timestamp da decisão
  - Símbolo e direção (BUY/SELL/NONE)
  - Contexto completo do mercado no momento (regime, VIX, DXY, COT, momentum, notícias)
  - Por que a decisão foi tomada (bias_score, contribuições por moeda, sessão)
  - Resultado da tentativa (aberto, bloqueado por filtro, erro, etc.)
  - Métricas de risco calculadas (lot, SL, TP, risk_pct, RR)

USO:
  from decision_log import log_decision, build_decision_context

  ctx = build_decision_context(mt5, intel, news, state)
  log_decision(ctx, symbol, direction, result, risk_info)

Isso é chamado DENTRO do executor.run_once() para CADA símbolo avaliado.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

BOT_DIR = Path(__file__).resolve().parent
DECISION_LOG_PATH = BOT_DIR / "decision_log.jsonl"


# ═════════════════════════════ BUILD CONTEXT ═════════════════════════════
def build_decision_context(intel: dict, news_data: Optional[dict],
                           state: dict, balance: float) -> dict:
    """Monta o snapshot completo do mercado e do bot no momento da decisão.

    Chamado uma vez por ciclo, antes de avaliar símbolos individuais.
    """
    now = datetime.now(timezone.utc)
    
    # ── Regime ──
    regime_str = "unknown"
    try:
        from bot.strategy_bridge import get_current_regime
        regime_str = get_current_regime()
    except Exception:
        pass

    # ── VIX / DXY ──
    rs = intel.get("risk_sentiment", {}) if intel else {}
    vix = rs.get("vix")
    vix_chg = rs.get("vix_pct_change")
    dxy = rs.get("dollar_index")
    dxy_chg = rs.get("dollar_index_pct_change")

    # ── Sessão ──
    h = now.hour
    if 0 <= h < 4:
        session = "Sydney"
    elif 4 <= h < 8:
        session = "Tokyo"
    elif 7 <= h < 16:
        session = "London"
    elif 13 <= h < 22:
        session = "NewYork"
    else:
        session = "Off"

    # ── COT positioning bruto ──
    cot = intel.get("cot_positioning", {}) if intel else {}

    # ── Dia da semana ──
    weekday = now.strftime("%A")

    # ── Drawdown state ──
    base_dia = state.get("starting_balance_today")
    base_sem = state.get("starting_balance_week")
    dd_dia = ((balance - base_dia) / base_dia * 100) if base_dia and base_dia > 0 else 0
    dd_sem = ((balance - base_sem) / base_sem * 100) if base_sem and base_sem > 0 else 0

    return {
        "ts_utc": now.isoformat(),
        "balance": round(balance, 2),
        "regime": regime_str,
        "session": session,
        "weekday": weekday,
        "vix": round(vix, 2) if vix is not None else None,
        "vix_pct_change": round(vix_chg, 2) if vix_chg is not None else None,
        "dxy": round(dxy, 2) if dxy is not None else None,
        "dxy_pct_change": round(dxy_chg, 2) if dxy_chg is not None else None,
        "cot_positioning": {
            cur: {
                "net": info.get("net"),
                "vies": info.get("vies"),
            }
            for cur, info in cot.items() if isinstance(info, dict)
        },
        "dd_daily_pct": round(dd_dia, 2),
        "dd_weekly_pct": round(dd_sem, 2),
        "open_positions_count": state.get("trades_opened_total", 0),
    }


# ═════════════════════════════ LOG DECISION ═════════════════════════════
def log_decision(
    ctx: dict,
    symbol: str,
    direction: str,           # "BUY" | "SELL" | "NONE"
    result: str,               # "opened" | "dry_run" | "no_signal" | "blocked_filter" | "error"
    detail: dict,              # informações específicas do símbolo
    risk_info: Optional[dict] = None,  # lot, sl, tp, risk_pct, rr se aplicável
    filter_blocked: Optional[str] = None,  # qual filtro bloqueou, se foi bloqueado
):
    """Append uma linha de decisão detalhada no decision_log.jsonl.

    Parâmetros:
      ctx: contexto global do mercado (build_decision_context)
      symbol: EURUSDm, GBPUSDm, etc.
      direction: BUY / SELL / NONE
      result: outcome padronizado
      detail: dict com reasoning específico (bias_score, contributions, etc.)
      risk_info: lot, SL, TP, risk_pct, RR se o trade foi calculado
      filter_blocked: string descrevendo qual filtro barrou, se for o caso
    """
    event = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "type": "DECISION",
        "payload": {
            "symbol": symbol,
            "direction": direction,
            "result": result,
            "filter_blocked": filter_blocked,
            "market_context": {
                "regime": ctx.get("regime"),
                "session": ctx.get("session"),
                "weekday": ctx.get("weekday"),
                "vix": ctx.get("vix"),
                "vix_pct_change": ctx.get("vix_pct_change"),
                "dxy": ctx.get("dxy"),
                "dxy_pct_change": ctx.get("dxy_pct_change"),
                "cot": ctx.get("cot_positioning"),
                "dd_daily_pct": ctx.get("dd_daily_pct"),
                "dd_weekly_pct": ctx.get("dd_weekly_pct"),
            },
            "reasoning": detail,
            "risk": risk_info,
            "balance_at_decision": ctx.get("balance"),
        },
    }

    try:
        with open(DECISION_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        print(f"[decision_log] erro ao escrever: {e}", flush=True)


# ═════════════════════════════ READ BACK ═════════════════════════════
def read_decisions(n_last: int = 100) -> list[dict]:
    """Lê as últimas N decisões do log. Retorna lista de dicts."""
    if not DECISION_LOG_PATH.exists():
        return []
    try:
        lines = DECISION_LOG_PATH.read_text(encoding="utf-8").splitlines()
        lines = lines[-n_last:]
        return [json.loads(l) for l in lines if l.strip()]
    except Exception as e:
        print(f"[decision_log] erro ao ler: {e}")
        return []


def get_decisions_by_symbol(symbol: str, n_last: int = 500) -> list[dict]:
    """Filtra decisões por símbolo."""
    all_decisions = read_decisions(n_last)
    return [d for d in all_decisions
            if d.get("payload", {}).get("symbol") == symbol]


def get_decisions_by_result(result: str, n_last: int = 500) -> list[dict]:
    """Filtra decisões por resultado."""
    all_decisions = read_decisions(n_last)
    return [d for d in all_decisions
            if d.get("payload", {}).get("result") == result]


__all__ = [
    "build_decision_context", "log_decision",
    "read_decisions", "get_decisions_by_symbol", "get_decisions_by_result",
    "DECISION_LOG_PATH",
]
