"""tests/scenarios/test_mt5_disconnect.py — MT5 cai no meio do ciclo.

Cenário: mt5.shutdown() ou conexão perdida durante run_once.
Espera: executor não trava, retry, loga, state persiste.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from bot.core.mt5_bridge import MT5Bridge, OrderResult
from bot.executor import run_once


def test_mt5_disconnect_during_cycle():
    """MT5 desconecta após account_info — ciclo aborta graciosamente."""
    # Mock bridge que falha na segunda chamada
    mock_bridge = MagicMock(spec=MT5Bridge)
    call_count = [0]
    
    def ensure_connected_side_effect():
        call_count[0] += 1
        if call_count[0] == 1:
            return True  # Primeira vez OK
        return False  # Segunda vez falha
    
    mock_bridge.ensure_connected.side_effect = ensure_connected_side_effect
    mock_bridge.account.return_value = MagicMock(balance=10000.0)
    
    # Patch no módulo executor
    with patch("bot.executor._bridge", mock_bridge):
        state = {}
        summary = run_once(1)
    
    # Ciclo deve abortar em mt5_connect
    assert summary["actions"][0]["step"] == "mt5_connect"
    assert summary["actions"][0]["ok"] is False


def test_mt5_reconnect_next_cycle():
    """Próximo ciclo tenta reconectar automaticamente."""
    mock_bridge = MagicMock(spec=MT5Bridge)
    call_count = [0]
    
    def ensure_connected_side_effect():
        call_count[0] += 1
        return call_count[0] > 1  # Falha primeira, passa segunda
    
    mock_bridge.ensure_connected.side_effect = ensure_connected_side_effect
    mock_bridge.account.return_value = MagicMock(balance=10000.0)
    
    with patch("bot.executor._bridge", mock_bridge):
        # Ciclo 1: falha
        run_once(1)
        # Ciclo 2: deve reconectar
        summary = run_once(2)
    
    assert mock_bridge.ensure_connected.call_count >= 2


def test_mt5_order_send_failure():
    """order_send retorna retcode != 10009 — loga, não empilha, continua."""
    mock_bridge = MagicMock(spec=MT5Bridge)
    mock_bridge.ensure_connected.return_value = True
    mock_bridge.account.return_value = MagicMock(balance=10000.0)
    mock_bridge.positions.return_value = []
    mock_bridge.open_symbols.return_value = set()
    
    # Simula order_send falhando
    mock_bridge.send.return_value = OrderResult(
        success=False, retcode=10015, comment="Invalid price"
    )
    
    with patch("bot.executor._bridge", mock_bridge):
        # Need to mock risk, decision, etc. to reach execution
        with patch("bot.executor._risk") as mock_risk:
            mock_risk.can_trade.return_value = MagicMock(ok=True, blocked=False)
            with patch("bot.executor._decision") as mock_decision:
                mock_decision.analyze.return_value = MagicMock(
                    symbol="XAUUSDm", direction="BUY", lot=0.01,
                    entry=2000.0, sl=1995.0, tp=2010.0
                )
                state = {}
                summary = run_once(1)
    
    # Deve ter action de open_trade com ok=False
    open_actions = [a for a in summary["actions"] if a.get("step") == "open_trade"]
    assert any(not a["ok"] for a in open_actions)


def test_mt5_terminal_info_false():
    """terminal_info.trade_allowed=False — não conecta."""
    mock_bridge = MagicMock(spec=MT5Bridge)
    mock_bridge.ensure_connected.return_value = False
    
    with patch("bot.executor._bridge", mock_bridge):
        summary = run_once(1)
    
    assert summary["actions"][0]["step"] == "mt5_connect"
    assert summary["actions"][0]["ok"] is False