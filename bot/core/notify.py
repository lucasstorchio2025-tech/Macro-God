"""bot.core.notify — Telegram bridge com retry exponencial + queue.

P0-D: substitui `notify()` inline do executor.py (urllib get + except: pass).
- requests.post com retry (3 tentativas: 2s, 4s, 8s)
- timeout 10s
- queue in-memory até 50 msgs (descarta overflow, loga)
- níveis: info | warn | alert | crisis | trade_open | trade_closed
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import requests

from bot.core.config import settings

logger = logging.getLogger(__name__)


class Level(Enum):
    INFO = "info"
    WARN = "warn"
    ALERT = "alert"
    CRISIS = "crisis"
    TRADE_OPEN = "trade_open"
    TRADE_CLOSED = "trade_closed"


ICONS = {
    Level.INFO: "[INFO]",
    Level.WARN: "[AVISO]",
    Level.ALERT: "[ALERTA]",
    Level.CRISIS: "[CRISIS]",
    Level.TRADE_OPEN: "[TRADE]",
    Level.TRADE_CLOSED: "[TRADE]",
}

EMOJI = {
    Level.INFO: "ℹ️",
    Level.WARN: "🟡",
    Level.ALERT: "🟠",
    Level.CRISIS: "🚨",
    Level.TRADE_OPEN: "🟢",
    Level.TRADE_CLOSED: "🔴",
}


@dataclass(frozen=True, slots=True)
class TelegramMessage:
    text: str
    level: Level


class TelegramNotifier:
    """Thread-safe notifier com queue + worker dedicado."""

    MAX_QUEUE = 50
    RETRIES = 3
    BASE_DELAY = 2.0  # 2, 4, 8 seconds
    TIMEOUT = 10

    def __init__(self, token: str = "", chat_id: str = "") -> None:
        self._token = token or settings.telegram_bot_token
        self._chat_id = chat_id or settings.telegram_chat_id
        self._enabled = settings.telegram_configured
        self._queue: queue.Queue[Optional[TelegramMessage]] = queue.Queue(maxsize=self.MAX_QUEUE)
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._stop = threading.Event()
        if self._enabled:
            self._worker.start()
            logger.info("TelegramNotifier iniciado (worker thread ativo)")
        else:
            logger.warning("TelegramNotifier: credenciais não configuradas — loga só no stdout")

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                msg = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if msg is None:  # sentinel para shutdown
                break
            self._send_with_retry(msg)
            self._queue.task_done()

    def _send_with_retry(self, msg: TelegramMessage) -> None:
        if not self._enabled:
            self._print_fallback(msg)
            return

        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": msg.text[:4000],  # Telegram limit
            "parse_mode": "HTML",
        }

        for attempt in range(self.RETRIES):
            try:
                resp = requests.post(url, json=payload, timeout=self.TIMEOUT)
                if resp.status_code == 200:
                    return
                logger.warning("Telegram send falhou (status %s): %s",
                              resp.status_code, resp.text[:200])
            except requests.RequestException as exc:
                logger.warning("Telegram request exception (tentativa %d): %s",
                              attempt + 1, exc)

            delay = self.BASE_DELAY * (2 ** attempt)
            time.sleep(delay)

        # Esgotou retries
        logger.error("Telegram: %d retries esgotados — descartando mensagem", self.RETRIES)
        self._print_fallback(msg)

    def _print_fallback(self, msg: TelegramMessage) -> None:
        icon = ICONS.get(msg.level, "[?]")
        print(f"{icon} {msg.text}", flush=True)

    # ── API pública ─────────────────────────────────────────────────────
    def _send(self, text: str, level: Level) -> None:
        """Enfileira mensagem (non-blocking). Se queue cheia, loga warning e descarta."""
        msg = TelegramMessage(text=text, level=level)
        try:
            self._queue.put_nowait(msg)
        except queue.Full:
            logger.warning("Telegram queue cheia (%d) — descartando: %s",
                          self.MAX_QUEUE, text[:80])

    def notify(self, text: str, level: str = "info") -> None:
        """Compatível com `notify(msg, level)` do executor antigo."""
        try:
            lvl = Level[level.upper()]
        except KeyError:
            lvl = Level.INFO
        self._send(text, lvl)

    def info(self, text: str) -> None:
        self._send(text, Level.INFO)

    def warn(self, text: str) -> None:
        self._send(text, Level.WARN)

    def alert(self, text: str) -> None:
        self._send(text, Level.ALERT)

    def crisis(self, text: str) -> None:
        self._send(text, Level.CRISIS)

    def trade_open(self, text: str) -> None:
        self._send(text, Level.TRADE_OPEN)

    def trade_closed(self, text: str) -> None:
        self._send(text, Level.TRADE_CLOSED)

    def heartbeat_dead(self, seconds: int) -> None:
        self.crisis(f"⚠️ Bot sem heartbeat há {seconds}s — última vida às ...")

    def dd_warning(self, current_pct: float, limit_pct: float) -> None:
        self.warn(f"🟡 DD diário {current_pct:.1f}% do limite ({limit_pct}%)")

    def shutdown(self) -> None:
        """Para worker thread graciosamente."""
        if self._enabled:
            self._stop.set()
            self._queue.put_nowait(None)
            self._worker.join(timeout=5)


# Singleton
notifier = TelegramNotifier()