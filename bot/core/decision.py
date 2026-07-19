"""bot.core.decision — DecisionEngine: lógica de sinal TS-Momentum.

P0-A: extrai o bloco de decisão (~200 linhas) do run_once do executor.py.
O executor chama DecisionEngine.analyze() -> Signal | None.

Contrato público:
  DecisionEngine.analyze(balance, state, intel, positions) -> Signal | None
  Signal = dataclass(symbol, direction, lot, entry, sl, tp)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import MetaTrader5 as mt5
import numpy as np

from bot.core.config import settings
from bot.core.mt5_bridge import MT5Bridge
from bot.core.risk import RiskManager
from bot.core.execution import TradeExecutor
from bot.core.logging_utils import log_event
from bot.core.notify import notifier

from engine import config as C
from engine.config import RunConfig as BotConfig
from bot.decision_log import build_decision_context, log_decision
from bot.strategy_bridge import compute_signals_with_detail, get_current_regime

logger = logging.getLogger(__name__)

SYMBOLS = C.SYMBOLS
MAGIC = C.EXNESS_MAGIC
RISK_PER_TRADE_PCT = C.RISK_PER_TRADE_PCT
MIN_RR = C.MIN_REWARD_RISK
ATR_STOP_MULT = C.ATR_STOP_MULT
ATR_STOP_MULT_BY_REGIME = C.ATR_STOP_MULT_BY_REGIME
DRY_RUN_MODE = C.DRY_RUN_MODE


@dataclass(frozen=True, slots=True)
class Signal:
    """Sinal de trade pronto para execução."""
    symbol: str
    direction: str  # "BUY" | "SELL"
    lot: float
    entry: float
    sl: float
    tp: float
    atr: float
    regime: str
    confidence: float
    detail: dict  # detalhes do signal_bridge para log


class DecisionEngine:
    """Encapsula toda a lógica de decisão (filtros + sizing + SL/TP)."""

    def __init__(
        self,
        bridge: MT5Bridge | None = None,
        risk: RiskManager | None = None,
        executor: TradeExecutor | None = None,
    ) -> None:
        self._bridge = bridge or MT5Bridge()
        self._risk = risk or RiskManager()
        self._executor = executor or TradeExecutor(self._bridge)

    def analyze(
        self,
        balance: float,
        state: dict,
        intel: dict,
        open_positions: int,
        open_symbols: set[str],
    ) -> Optional[Signal]:
        """
        Executa pipeline completo de decisão para um ciclo.
        Retorna Signal se há trade válido, None caso contrário.
        Loga cada decisão (mesmo bloqueadas) via decision_log.
        """
        if not self._bridge.ensure_connected():
            return None

        # Carrega regime atual
        try:
            regime = get_current_regime()
        except Exception:
            regime = "unknown"

        # Computa sinais para TODOS os símbolos
        sigs, details, _ = compute_signals_with_detail(self._bridge)

        # Itera símbolos em ordem de preferência (SYMBOLS config)
        for sym in SYMBOLS:
            detail = details.get(sym, {})
            sig = sigs.get(sym, "NONE")

            decision_ctx = build_decision_context(intel, None, state, balance)

            # Filtros de risco (exceto max_positions que já sabemos)
            # 1. DD check
            dd_ok, dd_reason = self._risk.check_daily_weekly_dd(balance, state).ok, ""
            if not dd_ok:
                log_decision(decision_ctx, sym, "NONE", "blocked_filter",
                           {"reason": dd_reason}, filter_blocked="dd_check")
                continue

            # 2. Cooldown
            cool_ok, cool_reason = self._risk.check_cooldown(sym, state).ok, ""
            if not cool_ok:
                log_decision(decision_ctx, sym, "NONE", "blocked_filter",
                           {"reason": cool_reason}, filter_blocked="cooldown")
                continue

            # 3. Regime gate
            reg_ok, reg_info = self._risk.check_regime_gate().ok, ""
            if not reg_ok:
                log_decision(decision_ctx, sym, "NONE", "blocked_filter",
                           {"reason": reg_info}, filter_blocked="crisis")
                continue

            # 4. Macro blockers
            macro_ok, macro_reason = self._risk.check_macro_blockers(intel).ok, ""
            if not macro_ok:
                log_decision(decision_ctx, sym, "NONE", "blocked_filter",
                           {"reason": macro_reason}, filter_blocked="macro_blockers")
                continue

            # 5. VIX
            vix_ok, vix_reason = self._risk.check_vix(intel).ok, ""
            if not vix_ok:
                log_decision(decision_ctx, sym, "NONE", "blocked_filter",
                           {"reason": vix_reason}, filter_blocked="vix_max_level")
                continue

            # 6. Session
            sess_ok, sess_reason = self._risk.check_session().ok, ""
            if not sess_ok:
                log_decision(decision_ctx, sym, "NONE", "blocked_filter",
                           {"reason": sess_reason}, filter_blocked="session")
                continue

            # 7. Anti-stacking: já tem posição no símbolo?
            if sym in open_symbols:
                log_decision(decision_ctx, sym, "NONE", "blocked_filter",
                           {"reason": "Posição aberta no mesmo símbolo (anti-empilhamento)"},
                           filter_blocked="anti_stack")
                continue

            # Sinal fraco / none
            if sig == "NONE":
                log_decision(decision_ctx, sym, "NONE", "no_signal",
                           detail.get("reason", "Sem sinal do engine"))
                continue

            # Direção do sinal
            direction = "BUY" if sig == "BUY" else "SELL"

            # Calcula SL/TP/lote via sizing (engine/sizing.py)
            try:
                from engine.sizing import compute_sizing
                sizing = compute_sizing(
                    symbol=sym,
                    direction=direction,
                    balance=balance,
                    risk_pct=RISK_PER_TRADE_PCT,
                    atr_mult=ATR_STOP_MULT,
                    regime=regime,
                )
            except Exception as exc:
                logger.exception("compute_sizing falhou para %s: %s", sym, exc)
                log_decision(decision_ctx, sym, "NONE", "error",
                           {"reason": f"sizing error: {exc}"})
                continue

            if sizing is None:
                log_decision(decision_ctx, sym, "NONE", "blocked_filter",
                           {"reason": "Sizing retornou None (dados insuficientes)"},
                           filter_blocked="sizing")
                continue

            # Constrói Signal final
            signal = Signal(
                symbol=sym,
                direction=direction,
                lot=sizing.lot,
                entry=sizing.entry,
                sl=sizing.sl,
                tp=sizing.tp,
                atr=sizing.atr,
                regime=regime,
                confidence=sizing.confidence,
                detail=detail,
            )

            # Log decisão positiva
            log_decision(decision_ctx, sym, direction, "signal",
                       {
                           "lot": signal.lot,
                           "entry": signal.entry,
                           "sl": signal.sl,
                           "tp": signal.tp,
                           "atr": signal.atr,
                           "regime": signal.regime,
                           "confidence": signal.confidence,
                       })
            return signal

        return None

    def execute(self, signal: Signal, dry_run: bool = False) -> Optional[ExecSignal]:
        """Executa o sinal (delega para TradeExecutor)."""
        exec_sig = ExecSignal(
            symbol=signal.symbol,
            direction=signal.direction,
            lot=signal.lot,
            entry=signal.entry,
            sl=signal.sl,
            tp=signal.tp,
        )
        result = self._executor.execute(exec_sig, dry_run=dry_run)
        return exec_sig if result.success else None


# Singleton
decision_engine = DecisionEngine()