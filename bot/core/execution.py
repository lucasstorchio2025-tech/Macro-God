"""bot.core.execution — TradeExecutor: execução de ordens.

P0-A: extrai open_trade, close_trade, close_all_on_crisis, sync_orphan_closes
do executor monolítico.

Contrato público:
  TradeExecutor.execute(signal) -> OrderResult
  TradeExecutor.flatten_all() -> int
  TradeExecutor.sync_closed_deals(state) -> None
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import MetaTrader5 as mt5

from bot.core.config import settings
from bot.core.mt5_bridge import MT5Bridge, OrderRequest, OrderResult
from bot.core.state import store
from bot.core.notify import notifier
from bot.core.logging_utils import log_event

from engine import config as C

logger = logging.getLogger(__name__)

BOT_DIR = Path(__file__).resolve().parents[1]
LOG_PATH = BOT_DIR / "trade_log.jsonl"
MAGIC = C.EXNESS_MAGIC
COMMENT_TAG = C.COMMENT_TAG
SYMBOLS = C.SYMBOLS


@dataclass(frozen=True, slots=True)
class Signal:
    """Sinal de decisão padronizado."""
    symbol: str
    direction: str  # "BUY" | "SELL"
    lot: float
    entry: float
    sl: float
    tp: float
    comment: str = ""


class TradeExecutor:
    """Executa ordens via MT5Bridge. Não decide — só executa."""

    def __init__(self, bridge: MT5Bridge | None = None):
        self._bridge = bridge or MT5Bridge()

    def execute(self, signal: Signal, dry_run: bool = False) -> OrderResult:
        """Abre ordem market com SL/TP. Se dry_run=True, só simula."""
        if not self._bridge.ensure_connected():
            return OrderResult(False, -1, "MT5 não conectado")

        info = self._bridge.symbol_info(signal.symbol)
        tick = self._bridge.symbol_info_tick(signal.symbol)
        if not info or not tick:
            return OrderResult(False, -1, f"symbol_info/tick falhou: {signal.symbol}")

        if signal.direction == "BUY":
            order_type = mt5.ORDER_TYPE_BUY
            entry = tick.ask
        else:
            order_type = mt5.ORDER_TYPE_SELL
            entry = tick.bid

        req = OrderRequest(
            symbol=signal.symbol,
            action=mt5.TRADE_ACTION_DEAL,
            type=order_type,
            volume=signal.lot,
            price=entry,
            sl=signal.sl,
            tp=signal.tp,
            deviation=30,
            magic=MAGIC,
            comment=f"{COMMENT_TAG}_{signal.direction}",
        )

        # order_check
        check = mt5.order_check(req.__dict__)
        if check is None or check.retcode != 0:
            msg = check.comment if check else "order_check retornou None"
            logger.warning("ORDER_CHECK_FAIL %s: %s", signal.symbol, msg)
            return OrderResult(False, check.retcode if check else -1, msg)

        if dry_run:
            logger.info("[DRY-RUN] Would open %s %s %s @ %s SL=%s TP=%s",
                       signal.direction, signal.lot, signal.symbol, entry, signal.sl, signal.tp)
            return OrderResult(True, 0, "dry_run", order=0, deal=0, volume=signal.lot, price=entry)

        result = self._bridge.send(req)

        if result.success:
            notifier.trade_open(
                f"🟢 {signal.direction} {signal.lot} {signal.symbol} @ {entry:.5f} | SL {signal.sl:.5f} TP {signal.tp:.5f} | ticket {result.order}"
            )
        else:
            notifier.notify(
                f"❌ Falha ao abrir {signal.direction} {signal.symbol}: {result.comment} (retcode {result.retcode})",
                "error"
            )
        return result

    def close(self, ticket: int, symbol: str, volume: float,
              direction: int, price: float, dry_run: bool = False) -> bool:
        """Fecha posição a mercado."""
        if not self._bridge.ensure_connected():
            return False

        if dry_run:
            logger.info("[DRY-RUN] Would close ticket %s %s %s", ticket, symbol, volume)
            return True

        ok = self._bridge.close(
            ticket=ticket,
            symbol=symbol,
            volume=volume,
            direction=direction,
            price=price,
            magic=MAGIC,
            comment=f"{COMMENT_TAG}_CLOSE",
        )

        if ok:
            notifier.trade_closed(
                f"🔴 Closed {symbol} {volume} lot | profit=... (need PnL)"
            )
        else:
            notifier.notify(
                f"❌ Falha ao fechar ticket {ticket}: {symbol}",
                "error"
            )
        return ok

    def flatten_all(self, dry_run: bool = False) -> int:
        """Fecha TODAS as posições do nosso magic. Retorna quantas fechou."""
        if not self._bridge.ensure_connected():
            return 0

        positions = self._bridge.positions(MAGIC)
        closed = 0
        for pos in positions:
            info = self._bridge.symbol_info(pos.symbol)
            tick = self._bridge.symbol_info_tick(pos.symbol)
            if not info or not tick:
                continue

            if dry_run:
                logger.info("[DRY-RUN] Would flatten %s %s", pos.symbol, pos.volume)
                closed += 1
                continue

            close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
            price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask

            if self.close(pos.ticket, pos.symbol, pos.volume, pos.type, price, dry_run=False):
                closed += 1

        if closed and not dry_run:
            notifier.crisis(f"🚨 FLATTEN ALL: {closed} posições fechadas defensivamente")
        return closed

    def sync_closed_deals(self, state: dict) -> int:
        """Detecta deals fechados automaticamente (SL/TP) e atualiza cooldown + meta-state.
        Retorna quantos deals novos encontrou."""
        if not self._bridge.ensure_connected():
            return 0

        deals = mt5.history_deals_get(
            datetime.now(timezone.utc) - timedelta(hours=72),
            datetime.now(timezone.utc)
        )
        if not deals:
            return 0

        # Carrega deals já logados
        logged = set()
        try:
            for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
                try:
                    ev = json.loads(line)
                    if ev.get("payload", {}).get("deal"):
                        logged.add(ev["payload"]["deal"])
                except Exception:
                    pass
        except Exception:
            pass

        new_deals = 0
        for d in deals:
            if d.magic != MAGIC:
                continue
            if d.ticket in logged:
                continue
            if d.type not in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
                continue

            # Loga o deal
            from bot.core.logging_utils import log_event
            log_event("DEAL_FOUND", {
                "deal": d.ticket, "order": d.order, "symbol": d.symbol,
                "type": d.type, "volume": d.volume, "price": d.price,
                "profit": d.profit, "comment": d.comment,
            })

            # Atualiza cooldown no state
            exits = state.setdefault("last_exit_ts", {})
            exits[d.symbol] = datetime.now(timezone.utc).isoformat()

            new_deals += 1

        return new_deals


# Singleton
executor = TradeExecutor()