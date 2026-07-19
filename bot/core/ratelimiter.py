"""bot.core.ratelimiter — Rate limiter simples para evitar ciclos empilhados.

P0-C item 3: Se run_once anterior ainda está rodando, próximo tick pula.
Implementação thread-safe com threading.Lock + timestamp.
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Optional


class RateLimiter:
    """Garante que apenas 1 ciclo execute por vez.

    - acquire() retorna True se pode prosseguir, False se ciclo anterior ainda roda
    - release() deve ser chamado no finally
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running = False
        self._start_time: Optional[float] = None

    def acquire(self) -> bool:
        """Tenta adquirir o lock. Non-blocking."""
        acquired = self._lock.acquire(blocking=False)
        if acquired:
            self._running = True
            self._start_time = time.monotonic()
            return True
        return False

    def release(self) -> None:
        """Libera o lock."""
        self._running = False
        self._start_time = None
        self._lock.release()

    @contextmanager
    def cycle(self):
        """Context manager para uso em `with ratelimiter.cycle():`."""
        if not self.acquire():
            raise RuntimeError("Ciclo anterior ainda em execução")
        try:
            yield True
        finally:
            self.release()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def elapsed_seconds(self) -> Optional[float]:
        if self._start_time is not None:
            return time.monotonic() - self._start_time
        return None


# Singleton
ratelimiter = RateLimiter()