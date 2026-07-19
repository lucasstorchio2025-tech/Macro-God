"""bot.core.mt5_bridge — ponte MT5 isolada, testável, com retry.

P0-A: extrai mt5_connect, positions_get, account_info, order_send,
symbol_info, symbol_info_tick, copy_rates do executor monolítico.

Contrato público:
  MT5Bridge.connect()           -> bool
  MT5Bridge.ensure_connected()  -> bool (reconecta se caiu)
  MT5Bridge.account()           -> AccountInfo | None
  MT5Bridge.positions()         -> list[Position]
  MT5Bridge.symbol_info(sym)    -> SymbolInfo | None
  MT5Bridge.symbol_info_tick(sym) -> Tick | None
  MT5Bridge.rates(sym, tf, n)   -> np.ndarray | None
  MT5Bridge.send(order)         -> OrderResult | None
  MT5Bridge.close(ticket)       -> bool
  MT5Bridge.shutdown()          -> None

Tudo síncrono (mt5 lib é sync). Retry com backoff exponencial em connect.
"""
from __future__ import annotations

import time
import logging
from dataclasses import dataclass
from typing import Any

import MetaTrader5 as mt5
import numpy as np

from bot.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """Request imutável para envio de ordem."""
    symbol: str
    action: int
    type: int
    volume: float
    price: float
    sl: float
    tp: float
    deviation: int = 20
    magic: int = 0
    comment: str = ""
    type_filling: int = mt5.ORDER_FILLING_IOC
    type_time: int = mt5.ORDER_TIME_GTC


@dataclass(frozen=True, slots=True)
class OrderResult:
    """Resultado padronizado de order_send."""
    success: bool
    retcode: int
    comment: str
    order: int | None = None
    deal: int | None = None
    volume: float = 0.0
    price: float = 0.0


class MT5Bridge:
    """Wrapper thread-safe (best-effort) ao redor de MetaTrader5."""

    _connected: bool = False
    _connect_attempts: int = 0
    _max_attempts: int = 5
    _base_delay: float = 1.0  # segundos

    def __init__(self) -> None:
        self._login = int(settings.exness_login)
        self._password = settings.exness_password
        self._server = settings.exness_server

    # ── Conexão ─────────────────────────────────────────────────────────
    def connect(self) -> bool:
        """Conecta uma vez. Retry exponencial até _max_attempts."""
        if self._connected:
            return True

        while self._connect_attempts < self._max_attempts:
            self._connect_attempts += 1
            try:
                ok = mt5.initialize(
                    login=self._login,
                    password=self._password,
                    server=self._server,
                    timeout=15000,
                )
                if ok:
                    ti = mt5.terminal_info()
                    if ti and ti.connected and ti.trade_allowed and not ti.tradeapi_disabled:
                        self._connected = True
                        logger.info("MT5 conectado (login=%s server=%s)", self._login, self._server)
                        return True
                    logger.warning("MT5 inicializado mas terminal não permite trade")
                else:
                    logger.warning("mt5.initialize falhou: %s", mt5.last_error())
            except Exception as exc:
                logger.exception("Exceção em mt5.initialize: %s", exc)

            delay = self._base_delay * (2 ** (self._connect_attempts - 1))
            logger.info("Tentativa %d/%d — aguardando %.1fs antes de retry",
                       self._connect_attempts, self._max_attempts, delay)
            time.sleep(delay)

        logger.error("MT5: excedeu %d tentativas de conexão", self._max_attempts)
        return False

    def ensure_connected(self) -> bool:
        """Garante conexão ativa; reconecta se caiu."""
        if self._connected:
            ti = mt5.terminal_info()
            if ti and ti.connected:
                return True
            logger.warning("MT5 conexão perdida — reconectando")
            self._connected = False
        return self.connect()

    def shutdown(self) -> None:
        """Fecha conexão MT5."""
        if self._connected:
            mt5.shutdown()
            self._connected = False
            logger.info("MT5 shutdown")

    # ── Dados de conta / posições ───────────────────────────────────────
    def account(self) -> Any | None:
        """Retorna mt5.account_info() ou None."""
        if not self.ensure_connected():
            return None
        return mt5.account_info()

    def positions(self, magic: int | None = None) -> list[Any]:
        """Todas as posições abertas (opcionalmente filtradas por magic)."""
        if not self.ensure_connected():
            return []
        try:
            poss = mt5.positions_get()
            if not poss:
                return []
            if magic is not None:
                return [p for p in poss if p.magic == magic]
            return list(poss)
        except Exception as exc:
            logger.exception("positions_get falhou: %s", exc)
            return []

    def open_symbols(self, magic: int) -> set[str]:
        """Símbolos com posição aberta para dado magic."""
        return {p.symbol for p in self.positions(magic)}

    # ── Market data ─────────────────────────────────────────────────────
    def symbol_info(self, symbol: str) -> Any | None:
        if not self.ensure_connected():
            return None
        return mt5.symbol_info(symbol)

    def symbol_info_tick(self, symbol: str) -> Any | None:
        if not self.ensure_connected():
            return None
        return mt5.symbol_info_tick(symbol)

    def rates(self, symbol: str, timeframe: int, count: int) -> np.ndarray | None:
        """Retorna rates como np.ndarray (copy_rates_from_pos) ou None."""
        if not self.ensure_connected():
            return None
        try:
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
            return rates if rates is not None and len(rates) > 0 else None
        except Exception as exc:
            logger.exception("copy_rates_from_pos(%s) falhou: %s", symbol, exc)
            return None

    # ── Execução ────────────────────────────────────────────────────────
    def send(self, req: OrderRequest) -> OrderResult:
        """Envia ordem via mt5.order_send; retorna OrderResult padronizado."""
        if not self.ensure_connected():
            return OrderResult(False, -1, "MT5 não conectado")

        order_dict = {
            "action": req.action,
            "symbol": req.symbol,
            "type": req.type,
            "volume": req.volume,
            "price": req.price,
            "sl": req.sl,
            "tp": req.tp,
            "deviation": req.deviation,
            "magic": req.magic or settings.magic,
            "comment": req.comment,
            "type_filling": req.type_filling,
            "type_time": req.type_time,
        }

        try:
            result = mt5.order_send(order_dict)
        except Exception as exc:
            logger.exception("order_send exceção: %s", exc)
            return OrderResult(False, -1, f"exception: {exc}")

        if result is None:
            return OrderResult(False, -1, "mt5.order_send retornou None")

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.warning("order_send retcode=%s comment=%s", result.retcode, result.comment)
            return OrderResult(
                success=False,
                retcode=result.retcode,
                comment=result.comment or "sem comment",
            )

        return OrderResult(
            success=True,
            retcode=result.retcode,
            comment=result.comment or "",
            order=result.order,
            deal=result.deal,
            volume=result.volume,
            price=result.price,
        )

    def close(self, ticket: int, symbol: str, volume: float,
              direction: int, price: float, magic: int, comment: str = "") -> bool:
        """Fecha posição específica."""
        if not self.ensure_connected():
            return False

        opp_type = mt5.ORDER_TYPE_SELL if direction == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "type": opp_type,
            "volume": volume,
            "price": price,
            "position": ticket,
            "deviation": 20,
            "magic": magic,
            "comment": comment or f"close {ticket}",
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(req)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.warning("close position %s falhou: retcode=%s comment=%s",
                          ticket, result.retcode if result else None,
                          result.comment if result else "None")
            return False
        return True


# Instância singleton para uso direto (compatibilidade gradual)
bridge = MT5Bridge()