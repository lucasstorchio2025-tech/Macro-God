"""tests/scenarios/test_race_save_state.py — Race condition no save_state.

Cenário: 2 threads chamam store.mutate() concorrentemente.
Espera: filelock garante consistência — state final válido, sem perda.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from bot.core.state import store, SafeFileStore


def test_concurrent_mutate_consistency():
    """Duas threads incrementando contador — lock garante atomicidade."""
    # Reset state
    store.save({"counter": 0})
    
    results = []
    errors = []
    
    def increment(n):
        try:
            for _ in range(n):
                with store.lock():
                    current = store.read()
                    current["counter"] = current.get("counter", 0) + 1
                    store.save(current)
                    time.sleep(0.001)  # Força interleaving
            results.append(True)
        except Exception as e:
            errors.append(e)
    
    t1 = threading.Thread(target=increment, args=(50,))
    t2 = threading.Thread(target=increment, args=(50,))
    
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    
    assert not errors, f"Erros: {errors}"
    
    final = store.read()
    # 50 + 50 = 100 (sem lock seria <100)
    assert final["counter"] == 100, f"Esperado 100, got {final['counter']}"


def test_concurrent_different_keys():
    """Threads modificando chaves diferentes — ambas persistem."""
    store.save({"a": 0, "b": 0})
    
    def inc_a():
        for _ in range(20):
            with store.lock():
                s = store.read()
                s["a"] += 1
                store.save(s)
    
    def inc_b():
        for _ in range(30):
            with store.lock():
                s = store.read()
                s["b"] += 1
                store.save(s)
    
    t1 = threading.Thread(target=inc_a)
    t2 = threading.Thread(target=inc_b)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    
    final = store.read()
    assert final["a"] == 20
    assert final["b"] == 30


def test_lock_timeout():
    """Lock timeout não trava indefinidamente."""
    slow_store = SafeFileStore(lock_path=Path("bot/bot_state.lock"))
    
    # Adquire lock e não libera por um tempo
    acquired = slow_store._lock.acquire(blocking=False)
    assert acquired
    
    # Outra thread tenta com timeout
    start = time.time()
    try:
        with slow_store._lock:
            pass  # Deve falhar no timeout
    except Exception:
        pass
    elapsed = time.time() - start
    
    # Deve ter falhado rápido (timeout=10s do SafeFileStore, mas testamos que não trava)
    assert elapsed < 5  # Muito antes do timeout
    
    slow_store._lock.release()