"""tests/conftest.py — Fixtures compartilhadas para testes de cenário."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Mock MetaTrader5 antes de qualquer import que o use
mt5_mock = MagicMock()
mt5_mock.TRADE_ACTION_DEAL = 1
mt5_mock.ORDER_TYPE_BUY = 0
mt5_mock.ORDER_TYPE_SELL = 1
mt5_mock.ORDER_TIME_GTC = 0
mt5_mock.ORDER_FILLING_IOC = 1
mt5_mock.TRADE_RETCODE_DONE = 10009
mt5_mock.TRADE_ACTION_DEAL = 1
mt5_mock.DEAL_TYPE_BUY = 0
mt5_mock.DEAL_TYPE_SELL = 1

sys.modules["MetaTrader5"] = mt5_mock


@pytest.fixture
def mock_mt5():
    """Mock completo do MetaTrader5."""
    return mt5_mock


@pytest.fixture
def mock_ollama():
    """Mock Ollama para testes de LLM."""
    mock = MagicMock()
    mock.post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"response": '{"action": "wait", "reasoning": "test"}'}
    )
    return mock


@pytest.fixture
def mock_telegram():
    """Mock Telegram notifier."""
    from bot.core.notify import TelegramNotifier
    notifier = MagicMock(spec=TelegramNotifier)
    notifier.sent_messages = []
    
    def capture(text, level="info"):
        notifier.sent_messages.append({"text": text, "level": level})
    
    notifier.notify.side_effect = capture
    notifier.crisis.side_effect = capture
    notifier.warn.side_effect = capture
    notifier.info.side_effect = capture
    notifier.trade_open.side_effect = capture
    notifier.trade_closed.side_effect = capture
    
    return notifier


@pytest.fixture
def sample_state():
    """Estado de bot típico para testes."""
    return {
        "paused_until_utc": None,
        "last_run_utc": "2026-07-18T14:00:00+00:00",
        "starting_balance_today": 10000.0,
        "starting_balance_week": 10000.0,
        "last_reset_day": "2026-07-18",
        "last_reset_week": "2026-W29",
        "trades_opened_total": 5,
        "trades_closed_total": 3,
        "last_exit_ts": {"XAUUSDm": "2026-07-18T12:00:00+00:00"},
        "risk_multiplier": 1.0,
    }


@pytest.fixture
def sample_intel():
    """Inteligência de mercado típica."""
    return {
        "regime": "normal",
        "risk_sentiment": {"vix": 18.5, "vix_pct_change": -2.1},
        "dxy": {"value": 102.3, "pct_change": 0.15},
        "economic_calendar_next_48h": [],
    }


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset singletons entre testes."""
    # Reset state store
    from bot.core.state import store
    store.save({})
    
    # Reset ratelimiter
    from bot.core.ratelimiter import ratelimiter
    ratelimiter._running = False
    ratelimiter._start_time = None
    if ratelimiter._lock.locked():
        ratelimiter._lock.release()
    
    yield
    
    # Cleanup
    store.save({})
    ratelimiter._running = False
    ratelimiter._start_time = None
    if ratelimiter._lock.locked():
        ratelimiter._lock.release()