"""bot.core.risk — RiskManager: todos os filtros hard do bot.

P0-A: extrai check_daily_weekly_dd, check_max_positions, check_total_exposure,
check_cooldown, check_regime_gate, check_macro_blockers do executor.py.

Contrato público:
  RiskManager.can_trade(balance, state, intel) -> RiskVerdict
  RiskVerdict.ok, RiskVerdict.reason, RiskVerdict.filter_name
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import MetaTrader5 as mt5

from bot.core.config import settings
from engine import config as C
from engine.utils import session_of

logger = logging.getLogger(__name__)


# Constantes importadas do engine.config (evita dependência circular no runtime)
SYMBOLS = C.SYMBOLS
MAX_OPEN_POSITIONS = C.MAX_OPEN_POSITIONS
TOTAL_RISK_CAP_PCT = C.TOTAL_RISK_CAP_PCT
RISK_PER_TRADE_PCT = C.RISK_PER_TRADE_PCT
RISK_OVERRIDE_PCT = C.RISK_OVERRIDE_PCT
MIN_REWARD_RISK = C.MIN_REWARD_RISK
DAILY_DD_PCT = C.DAILY_DD_PCT
WEEKLY_DD_PCT = C.WEEKLY_DD_PCT
MAGIC = C.EXNESS_MAGIC
COMMENT_TAG = C.COMMENT_TAG
COOLDOWN_SECONDS = C.COOLDOWN_BARS * 4 * 3600
DRY_RUN_MODE = C.DRY_RUN_MODE


@dataclass(frozen=True, slots=True)
class RiskVerdict:
    """Resultado de um filtro de risco."""
    ok: bool
    reason: str = ""
    filter_name: str = ""

    @property
    def blocked(self) -> bool:
        return not self.ok


class RiskManager:
    """Agrega todos os hard-filters do bot."""

    def __init__(self) -> None:
        self._vix_max = C.VIX_MAX_LEVEL

    # ── Filtros individuais ─────────────────────────────────────────────
    def check_daily_weekly_dd(self, balance: float, state: dict) -> RiskVerdict:
        """Retorna (pode_operar, motivo). Reseta contadores diariamente/semanalmente."""
        now = datetime.now(timezone.utc)
        weekday = now.weekday()
        today_str = now.date().isoformat()
        week_str = now.strftime("%Y-W%V")

        effective_daily = C.DRY_RUN_DAILY_DD_PCT if DRY_RUN_MODE else DAILY_DD_PCT
        effective_weekly = C.DRY_RUN_WEEKLY_DD_PCT if DRY_RUN_MODE else WEEKLY_DD_PCT

        if state.get("last_reset_day") != today_str:
            state["starting_balance_today"] = balance
            state["last_reset_day"] = today_str
        if weekday == 0 and state.get("last_reset_week") != week_str:
            state["starting_balance_week"] = balance
            state["last_reset_week"] = week_str
        if state.get("starting_balance_today") is None:
            state["starting_balance_today"] = balance
        if state.get("starting_balance_week") is None:
            state["starting_balance_week"] = balance

        base_dia = state["starting_balance_today"]
        base_sem = state["starting_balance_week"]
        dd_dia_pct = (balance - base_dia) / base_dia * 100 if base_dia else 0
        dd_sem_pct = (balance - base_sem) / base_sem * 100 if base_sem else 0

        if dd_dia_pct <= -effective_daily:
            return RiskVerdict(
                False,
                f"DD diario {dd_dia_pct:.2f}% <= {effective_daily}%. Bot pausado ate amanha.",
                "daily_dd"
            )
        if dd_sem_pct <= -effective_weekly:
            return RiskVerdict(
                False,
                f"DD semanal {dd_sem_pct:.2f}% <= {effective_weekly}%. Bot pausado ate segunda.",
                "weekly_dd"
            )
        return RiskVerdict(True)

    def check_max_positions(self) -> RiskVerdict:
        """Quantas posições abertas temos (com nosso magic)."""
        try:
            positions = mt5.positions_get() or []
            our = [p for p in positions if p.magic == MAGIC]
            return RiskVerdict(
                len(our) < MAX_OPEN_POSITIONS,
                f"Max posições {MAX_OPEN_POSITIONS} atingido" if len(our) >= MAX_OPEN_POSITIONS else "",
                "max_positions"
            )
        except Exception as exc:
            logger.exception("check_max_positions falhou: %s", exc)
            return RiskVerdict(False, "erro MT5", "max_positions_error")

    def get_open_symbols(self) -> set[str]:
        """Símbolos que já temos posição aberta."""
        try:
            positions = mt5.positions_get() or []
            return {p.symbol for p in positions if p.magic == MAGIC}
        except Exception:
            return set()

    def check_total_exposure(self, balance: float) -> RiskVerdict:
        """Soma do risco aberto <= TOTAL_RISK_CAP_PCT do saldo."""
        try:
            positions = mt5.positions_get() or []
            our = [p for p in positions if p.magic == MAGIC]
            total_risk = 0.0
            for p in our:
                info = mt5.symbol_info(p.symbol)
                if not info:
                    continue
                risk_per_unit = mt5.order_calc_profit(p.type, p.symbol, info.volume_min, p.price_open, p.sl)
                if risk_per_unit is None:
                    continue
                units = p.volume / info.volume_min
                total_risk += abs(risk_per_unit) * units
            total_risk_pct = (total_risk / balance * 100) if balance else 0
            return RiskVerdict(
                total_risk_pct < TOTAL_RISK_CAP_PCT,
                f"Exposicao aberta {total_risk_pct:.2f}% >= cap {TOTAL_RISK_CAP_PCT}%",
                "exposure"
            )
        except Exception as exc:
            logger.exception("check_total_exposure falhou: %s", exc)
            return RiskVerdict(False, "erro MT5", "exposure_error")

    def check_macro_blockers(self, intel: dict) -> RiskVerdict:
        """Se tem evento de alto impacto em < 2h, não opera."""
        cal = intel.get("economic_calendar_next_48h", [])
        if not isinstance(cal, list):
            return RiskVerdict(True)
        now = datetime.now(timezone.utc)
        for ev in cal:
            try:
                ev_time = datetime.fromisoformat(str(ev.get("time", "")).replace("Z", "+00:00"))
                minutes_to = (ev_time - now).total_seconds() / 60
                if 0 <= minutes_to <= 120:
                    return RiskVerdict(
                        False,
                        f"Evento de alto impacto em {int(minutes_to)} min: "
                        f"{ev.get('event','?')} ({ev.get('country','?')})",
                        "macro_blocker"
                    )
            except Exception:
                continue
        return RiskVerdict(True)

    def check_cooldown(self, symbol: str, state: dict) -> RiskVerdict:
        """True se símbolo está fora do cooldown."""
        last = state.get("last_exit_ts", {}).get(symbol)
        if not last:
            return RiskVerdict(True)
        try:
            last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
            elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
            return RiskVerdict(elapsed >= COOLDOWN_SECONDS, "", "cooldown")
        except Exception:
            return RiskVerdict(True)

    def check_regime_gate(self) -> RiskVerdict:
        """Gate de regime: se crisis, não opera (vai flat)."""
        try:
            from bot.strategy_bridge import get_current_regime
            regime = get_current_regime()
            if regime == "crisis":
                return RiskVerdict(False, f"Regime = crisis. Bot flat.", "crisis")
            return RiskVerdict(True, f"regime={regime}", "regime")
        except Exception as e:
            logger.warning("regime gate indisponível (%s), prosseguindo", type(e).__name__)
            return RiskVerdict(True, f"regime indisponível ({type(e).__name__})", "regime_unavailable")

    def check_vix_max(self, intel: dict) -> RiskVerdict:
        """Bloqueia se VIX > limite configurado."""
        if self._vix_max <= 0 or not intel:
            return RiskVerdict(True)
        vix = intel.get("risk_sentiment", {}).get("vix")
        if vix is not None and vix > self._vix_max:
            return RiskVerdict(
                False,
                f"VIX {vix:.1f} > {self._vix_max} (VIX_MAX_LEVEL). Bloqueado.",
                "vix_max"
            )
        return RiskVerdict(True)

    def check_session_filter(self) -> RiskVerdict:
        """Respeita SESSION_FILTER_ALLOW."""
        if not C.SESSION_FILTER_ALLOW:
            return RiskVerdict(True)
        sess = session_of(datetime.now(timezone.utc))
        return RiskVerdict(
            sess in C.SESSION_FILTER_ALLOW,
            f"Sessão {sess} bloqueada por SESSION_FILTER_ALLOW",
            f"session_{sess}"
        )

    def check_already_open(self, symbol: str, open_symbols: set) -> RiskVerdict:
        """Anti-empilhamento: não abre no mesmo símbolo."""
        if symbol in open_symbols:
            return RiskVerdict(False, f"Já existe posição aberta em {symbol}", "already_open")
        return RiskVerdict(True)

    # ── API principal ────────────────────────────────────────────────────
    def can_trade(self, balance: float, state: dict, intel: dict) -> RiskVerdict:
        """Executa todos os filtros em ordem. Para no primeiro que bloqueia."""
        # Ordem igual ao executor original (filtros 1..8)
        checks = [
            ("dd", lambda: self.check_daily_weekly_dd(balance, state)),
            ("max_positions", self.check_max_positions),
            ("exposure", lambda: self.check_total_exposure(balance)),
            ("macro", lambda: self.check_macro_blockers(intel)),
            ("regime", self.check_regime_gate),
            ("vix", lambda: self.check_vix_max(intel)),
            ("session", self.check_session_filter),
        ]
        for name, fn in checks:
            verdict = fn()
            if not verdict.ok:
                logger.info("Risk filter %s blocked: %s", name, verdict.reason)
                return verdict
        return RiskVerdict(True)


# Instância singleton
risk = RiskManager()