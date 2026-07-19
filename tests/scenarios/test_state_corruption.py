"""tests/scenarios/test_state_corruption.py — bot_state.json corrompido.

Cenário: JSON inválido no state file.
Espera: SafeFileStore detecta, renomeia para .corrupt_<ts>, inicia state novo, alerta Telegram.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.core.state import store, SafeFileStore
from bot.core import notify


def test_state_corruption_recovery(mock_telegram, tmp_path):
    """Escreve JSON inválido, verifica recovery + alerta Telegram."""
    # Corrompe o arquivo
    state_path = Path("bot/bot_state.json")
    state_path.write_text("{ invalid json }", encoding="utf-8")
    
    # Tenta ler — deve recuperar
    recovered = store.read()
    
    # Deve retornar state default válido
    assert isinstance(recovered, dict)
    assert "trades_opened_total" in recovered
    assert recovered["trades_opened_total"] == 0
    
    # Arquivo original deve ter sido movido para .corrupt_*
    corrupt_files = list(Path("bot").glob("bot_state.corrupt_*.json"))
    assert len(corrupt_files) == 1
    
    # Telegram avisou
    assert any("CORROMPIDO" in m["text"] or "corrupt" in m["text"].lower() 
               for m in mock_telegram.sent_messages)


def test_state_corruption_on_save():
    """Save atômico: se falhar no meio, arquivo original intacto."""
    from bot.core.state import SafeFileStore
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SafeFileStore(Path(tmpdir) / "test_state.json")
        
        # Estado válido inicial
        store.save({"key": "value", "count": 1})
        
        # Força erro no write (mock json.dump para falhar)
        import json as json_mod
        original_dump = json_mod.dump
        def fail_dump(*args, **kwargs):
            raise IOError("Disk full")
        json_mod.dump = fail_dump
        
        try:
            store.save({"key": "new", "count": 2})
        except IOError:
            pass
        finally:
            json_mod.dump = original_dump
        
        # Arquivo original deve estar intacto
        recovered = store.read()
        assert recovered == {"key": "value", "count": 1}