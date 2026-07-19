"""
autonomous_bridge.py — PONTE ENTRE EXECUTOR E SISTEMA AUTÔNOMO
==============================================================
Conecta o executor.py existente ao AutonomousCommander.

Sem modificar o executor, esta bridge:
  1. Cria o Commander (com Oracle + Evolution + Decision Engine)
  2. No início de cada ciclo, chama commander.cycle()
  3. O Commander retorna uma CommanderOrder
  4. O executor usa a ordem para decidir se opera ou não
  5. Após cada trade fechado, chama commander.learn()

Uso no executor:
    from engine.autonomous_bridge import get_commander
    
    # No início do bot
    commander = get_commander()
    
    # Em cada ciclo, ANTES dos filtros manuais:
    order = commander.cycle(
        intel=intel_data,
        prices=price_data,
        meta=meta_state,
        signals=signals_dict,
        signal_details=details_dict,
        balance=balance,
        open_positions=open_count,
        open_symbols=open_set,
        news_path=news_json_path,
        last_trades=recent_trades,
    )
    
    # Se order.action == "wait":
    #   pule o ciclo
    # Se order.action == "close_all":
    #   feche todas as posições
    # Se order.action == "trade":
    #   use order.direction, order.risk_pct, order.stop_atr_mult
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Importação segura (não quebra se módulos falharem)
try:
    from engine.commander import AutonomousCommander, CommanderOrder
    from engine.autonomous_oracle import AutonomousOracle
    from engine.self_evolution import SelfEvolutionEngine
    
    _HAS_AUTONOMOUS = True
except ImportError as e:
    print(f"[Bridge] Autonomous modules not available: {e}")
    _HAS_AUTONOMOUS = False


# ── Singleton do Commander ──
_commander_instance = None


def get_commander() -> Optional[object]:
    """Retorna instância única do AutonomousCommander."""
    global _commander_instance
    
    if not _HAS_AUTONOMOUS:
        return None
    
    if _commander_instance is None:
        try:
            _commander_instance = AutonomousCommander()
            print(f"[Bridge] Autonomous Commander initialized!", flush=True)
            print(f"[Bridge] Oracle: macro analysis active", flush=True)
            print(f"[Bridge] Evolution: self-tuning active", flush=True)
            print(f"[Bridge] Decision Engine: AI-powered decisions active", flush=True)
        except Exception as e:
            print(f"[Bridge] Failed to initialize Commander: {e}", flush=True)
            _commander_instance = None
    
    return _commander_instance


def commander_cycle(commander, intel: dict, prices: dict = None,
                    meta: object = None,
                    signals: dict = None,
                    signal_details: dict = None,
                    balance: float = 0.0,
                    open_positions: int = 0,
                    open_symbols: set = None,
                    news_path: Optional[Path] = None,
                    last_trades: list = None) -> CommanderOrder:
    """Wrapper seguro para commander.cycle()."""
    if commander is None or not _HAS_AUTONOMOUS:
        # Fallback: retorna ordem vazia (deixa o executor decidir)
        return CommanderOrder(action="wait", reasoning="Autonomous system unavailable")
    
    try:
        return commander.cycle(
            intel=intel,
            prices=prices or {},
            meta=meta,
            signals=signals or {},
            signal_details=signal_details or {},
            balance=balance,
            open_positions=open_positions,
            open_symbols=open_symbols or set(),
            news_path=news_path,
            last_trades=last_trades or [],
        )
    except Exception as e:
        print(f"[Bridge] Commander cycle error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return CommanderOrder(action="wait", reasoning=f"Commander error: {e}")


def commander_learn(commander, trade_result: dict):
    """Registra aprendizado com trade fechado."""
    if commander is None or not _HAS_AUTONOMOUS:
        return
    try:
        commander.learn(trade_result)
    except Exception as e:
        print(f"[Bridge] Commander learn error: {e}", flush=True)


def is_autonomous_available() -> bool:
    """Verifica se o sistema autônomo está disponível."""
    return _HAS_AUTONOMOUS and get_commander() is not None


__all__ = [
    "get_commander", "commander_cycle", "commander_learn",
    "is_autonomous_available",
    "CommanderOrder",
]
