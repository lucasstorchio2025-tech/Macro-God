#!/usr/bin/env python3
"""bot/launcher.py — Launcher final Wealth Engine v4.

Executa como usuário Lucas (não SYSTEM), conecta MT5, inicia ciclo.
Escreve heartbeat.json a cada ciclo para o Dashboard mostrar status.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(PROJECT_ROOT / "bot" / "run" / "launcher.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("wealth.launcher")

_shutdown = False
_cycle = 0


def _handle_sigterm(signum, frame):
    global _shutdown
    _shutdown = True
    logger.info("SIGTERM received, graceful shutdown...")


signal.signal(signal.SIGTERM, _handle_sigterm)


def _write_heartbeat(alive: bool = True, components: list | None = None):
    """Atualiza heartbeat.json para o Dashboard mostrar status real."""
    global _cycle
    hb_path = PROJECT_ROOT / "bot" / "run" / "heartbeat.json"
    hb_data = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "cycle": _cycle,
        "alive": alive,
        "components": components or [],
    }
    try:
        hb_path.write_text(json.dumps(hb_data, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"Não consegui escrever heartbeat: {e}")


def main():
    global _cycle
    logger.info("Wealth Engine v4 Launcher — iniciando...")
    _write_heartbeat(alive=True, components=["bot"])

    # Import executor
    from bot.executor import main_loop as _exec_main_loop, run_once
    import bot.executor as _executor
    from bot.core.notify import notifier

    # Patch: a cada ciclo, escreve heartbeat
    _orig_run_once = _executor.run_once

    def _instrumented_run_once(cycle_num):
        global _cycle
        _cycle = cycle_num
        _write_heartbeat(alive=True, components=["bot", "mt5", "risk"])
        try:
            result = _orig_run_once(cycle_num)
            _write_heartbeat(alive=True, components=["bot", "mt5", "risk", "cycle_ok"])
            return result
        except Exception as exc:
            _write_heartbeat(alive=True, components=["bot", "error"])
            raise

    _executor.run_once = _instrumented_run_once

    # Inicia ciclo
    try:
        _exec_main_loop()
    except KeyboardInterrupt:
        pass
    except Exception:
        logger.exception("Executor crash")
    finally:
        _write_heartbeat(alive=False, components=[])
        try:
            notifier.warn("🔴 Wealth Engine Bot PARADO")
        except Exception:
            pass
        logger.info("Wealth Engine v4 Launcher — finalizado")


if __name__ == "__main__":
    main()