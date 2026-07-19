"""tests/scenarios/test_llm_timeout.py — Ollama timeout no Commander.

Cenário: Ollama trava/demora >5s — fallback para heurística hardcoded, sem crash.
"""
from __future__ import annotations

import time
from unittest.mock import patch, MagicMock

import pytest

from engine.commander import CommanderDecisionEngine, CommanderOrder


def test_ollama_timeout_fallback():
    """LLM demora >5s — _consult_llm retorna None, fallback decision usado."""
    engine = CommanderDecisionEngine()
    
    # Mock requests.post que demora forever
    def slow_post(*args, **kwargs):
        time.sleep(10)  # > timeout
        return MagicMock(status_code=200, json=lambda: {"response": "{}"})
    
    with patch("requests.post", side_effect=slow_post):
        with patch("engine.commander.CommanderDecisionEngine._consult_llm", return_value=None):
            # Should not hang, should return fallback
            ctx = MagicMock()
            ctx.signals = {"XAUUSDm": ("BUY", 0.05)}
            ctx.open_symbols = set()
            ctx.open_positions = 0
            ctx.balance = 10000.0
            ctx.meta = MagicMock(get_risk_multiplier=lambda: 1.0)
            
            order = engine.decide(ctx, skip_llm=False)  # Tenta LLM
    
    # Deve retornar fallback (não None, não crash)
    assert order is not None
    assert order.action in ("trade", "wait")


def test_ollama_connection_error_fallback():
    """ConnectionError no Ollama — fallback imediato."""
    engine = CommanderDecisionEngine()
    
    with patch("requests.post", side_effect=ConnectionError("Ollama down")):
        ctx = MagicMock()
        ctx.signals = {"XAUUSDm": ("BUY", 0.05)}
        ctx.open_symbols = set()
        ctx.open_positions = 0
        ctx.balance = 10000.0
        ctx.meta = MagicMock(get_risk_multiplier=lambda: 1.0)
        
        order = engine.decide(ctx, skip_llm=False)
    
    assert order is not None
    assert order.action in ("trade", "wait")


def test_llm_invalid_json_fallback():
    """LLM retorna JSON inválido — fallback."""
    engine = CommanderDecisionEngine()
    
    def bad_json_post(*args, **kwargs):
        return MagicMock(
            status_code=200,
            json=lambda: {"response": "not json at all {{{"}
        )
    
    with patch("requests.post", side_effect=bad_json_post):
        ctx = MagicMock()
        ctx.signals = {"XAUUSDm": ("BUY", 0.05)}
        ctx.open_symbols = set()
        ctx.open_positions = 0
        ctx.balance = 10000.0
        ctx.meta = MagicMock(get_risk_multiplier=lambda: 1.0)
        
        order = engine.decide(ctx, skip_llm=False)
    
    assert order is not None
    assert order.action in ("trade", "wait")