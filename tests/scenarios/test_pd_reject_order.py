"""tests/scenarios/test_pd_reject_order.py — PD rejeita ordem.

Cenário: mt5.order_send retorna retcode != 10009 — executor loga, NÃO empilha, continua loop.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

from bot.core.mt5_bridge import MT5Bridge, OrderResult
from bot.executor import run_once


def test_order_reject_not_stacked():
    """Retcode 10015 (invalid price) — loga erro, não incrementa trades_opened_total, continua."""
    mock_bridge = MagicMock(spec=MT5Bridge)
    mock_bridge.ensure_connected.return_value = True
    mock_bridge.account.return_value = MagicMock(balance=10000.0)
    mock_bridge.positions.return_value = []
    mock_bridge.open_symbols.return_value = set()
    mock_bridge.send.return_value = OrderResult(
        success=False, retcode=10015, comment="Invalid price"
    )
    
    with patch("bot.executor._bridge", mock_bridge):
        with patch("bot.executor._risk") as mock_risk:
            mock_risk.can_trade.return_value = MagicMock(ok=True, blocked=False)
            with patch("bot.executor._decision") as mock_decision:
                mock_decision.analyze.return_value = MagicMock(
                    symbol="XAUUSDm", direction="BUY", lot=0.01,
                    entry=2000.0, sl=1995.0, tp=2010.0
                )
                state = {"trades_opened_total": 0}
                summary = run_once(1)
    
    # Verifica: action open_trade com ok=False
    open_actions = [a for a in summary["actions"] if a.get("step") == "open_trade"]
    assert len(open_actions) == 1
    assert open_actions[0]["ok"] is False
    assert "Invalid price" in open_actions[0]["error"]
    
    # trades_opened_total NÃO incrementou
    assert state["trades_opened_total"] == 0
    
    # Ciclo continuou (não travou)
    assert "cycle_end" in summary


def test_order_reject_10014():
    """Retcode 10014 (invalid stops) — mesmo comportamento."""
    mock_bridge = MagicMock(spec=MT5Bridge)
    mock_bridge.ensure_connected.return_value = True
    mock_bridge.account.return_value = MagicMock(balance=10000.0)
    mock_bridge.positions.return_value = []
    mock_bridge.open_symbols.return_value = set()
    mock_bridge.send.return_value = OrderResult(
        success=False, retcode=10014, comment="Invalid stops"
    )
    
    with patch("bot.executor._bridge", mock_bridge):
        with patch("bot.executor._risk") as mock_risk:
            mock_risk.can_trade.return_value = MagicMock(ok=True, blocked=False)
            with patch("bot.executor._decision") as mock_decision:
                mock_decision.analyze.return_value = MagicMock(
                    symbol="XAUUSDm", direction="SELL", lot=0.01,
                    entry=2000.0, sl=2005.0, tp=1990.0  # SL > entry para SELL = inválido
                )
                state = {"trades_opened_total": 0}
                summary = run_once(1)
    
    open_actions = [a for a in summary["actions"] if a.get("step") == "open_trade"]
    assert open_actions[0]["ok"] is False
    assert state["trades_opened_total"] == 0


def test_multiple_rejections_dont_accumulate():
    """5 rejeições seguidas — não empilha, não vaza memória."""
    mock_bridge = MagicMock(spec=MT5Bridge)
    mock_bridge.ensure_connected.return_value = True
    mock_bridge.account.return_value = MagicMock(balance=10000.0)
    mock_bridge.positions.return_value = []
    mock_bridge.open_symbols.return_value = set()
    mock_bridge.send.return_value = OrderResult(
        success=False, retcode=10013, comment="Invalid request"
    )
    
    with patch("bot.executor._bridge", mock_bridge):
        with patch("bot.executor._risk") as mock_risk:
            mock_risk.can_trade.return_value = MagicMock(ok=True, blocked=False)
            with patch("bot.executor._decision") as mock_decision:
                mock_decision.analyze.return_value = MagicMock(
                    symbol="XAUUSDm", direction="BUY", lot=0.01,
                    entry=2000.0, sl=1995.0, tp=2010.0
                )
                state = {"trades_opened_total": 0}
                for i in range(5):
                    summary = run_once(i + 1)
    
    # Todas falharam
    assert state["trades_opened_total"] == 0
    # Loop não travou
    assert all("cycle_end" in run_once(j) for j in range(6, 8))