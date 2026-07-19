"""bot.core — núcleo modular do Wealth_Engine v4.

Módulos extraídos do monolito bot/executor.py (P0-A).
Cada módulo tem contrato público explícito e é testável isoladamente.
"""
from __future__ import annotations

__all__ = ["state", "mt5_bridge", "risk", "decision", "execution", "notify", "config"]
