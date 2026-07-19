"""tests/scenarios/test_double_start.py — Segunda instância recusa.

Cenário: 2× python bot/manager.py start — segundo recusa com "já rodando (PID X)".
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from bot.manager import ProcessManager, write_pid, read_pid, is_process_alive


def test_double_start_refused():
    """Segunda instância detecta PID vivo e recusa."""
    manager = ProcessManager()
    
    # Simula PID file existente
    with tempfile.TemporaryDirectory() as tmpdir:
        pid_file = Path(tmpdir) / "wealth.pid"
        pid_file.write_text("999999")
        
        with patch("bot.manager.PID_FILE", pid_file):
            with patch("bot.manager.is_process_alive", return_value=True):
                ok = manager.start()
        
        assert ok is False
        assert "Já existe instância rodando" in str(manager)


def test_double_start_allowed_if_dead():
    """PID file existe mas processo morto — permite iniciar."""
    manager = ProcessManager()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        pid_file = Path(tmpdir) / "wealth.pid"
        pid_file.write_text("999999")
        
        with patch("bot.manager.PID_FILE", pid_file):
            with patch("bot.manager.is_process_alive", return_value=False):
                ok = manager.start()
        
        # Deve permitir (sobrescreve PID)
        assert ok is True


def test_status_shows_correct_pid():
    """status() retorna PID correto do heartbeat."""
    from bot.manager import read_heartbeat
    
    with tempfile.TemporaryDirectory() as tmpdir:
        hb_file = Path(tmpdir) / "heartbeat.json"
        hb_file.write_text('{"pid": 12345, "alive": true}')
        
        with patch("bot.manager.HEARTBEAT_FILE", hb_file):
            hb = read_heartbeat()
        
        assert hb["pid"] == 12345
        assert hb["alive"] is True