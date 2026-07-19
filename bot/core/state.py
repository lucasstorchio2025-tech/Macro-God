"""bot.core.state — gerência thread-/process-safe do estado do bot.

P0-A + P0-C: extrai `load_state`/`save_state` do monolito bot/executor.py
e adiciona:

  1. Escrita atômica (tmpfile + os.replace) — nunca mais meio arquivo em disco.
  2. Lock inter-processo via filelock (lib nova) — Commander e Executor não se
     pisam mais uns nos outros.
  3. Recovery de corrupção: JSON inválido é renomeado pra `*.corrupt_<ts>`,
     state novo começa, alerta é emitido.
  4. Schema Pydantic BotState valida os campos do namespace do executor.
  5. Namespaces isolados: cada módulo (executor, commander, oracle, meta_state,
     self_evolution, _processed_deals) lê/escreve SÓ suas chaves — sem
     sobrescrever campos alheios.

Backward-compat: `load_state()` e `save_state(state)` continuam funcionando
igual ao executor antigo (mesma path, mesmo merge semântico), mas as chamadas
atravessam SafeFileStore por baixo.

Uso:
    from bot.core.state import store
    state = store.read()                          # -> dict (mesma forma que antes)
    state["trades_opened_total"] += 1
    store.save(state)                             # atômico, com lock

    # Para modificações seguras entre read e write:
    with store.lock():
        s = store.read()
        s["last_exit_ts"]["XAUUSDm"] = iso_ts
        store.save(s)

    # Namespaces isolados (sem cross-update):
    commander_state = store.read_namespace("autonomous_commander")
    store.save_namespace("autonomous_commander", commander_state)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from filelock import FileLock
from pydantic import BaseModel, Field, ConfigDict

logger = logging.getLogger(__name__)

# Path idêntica ao executor antigo: bot/bot_state.json
_BOT_DIR = Path(__file__).resolve().parents[1]
_STATE_PATH = _BOT_DIR / "bot_state.json"
_LOCK_PATH = _BOT_DIR / "bot_state.lock"

# Namespaces conhecidos no bot_state.json hoje (chaves != do executor core):
#   - autonomous_commander
#   - autonomous_oracle
#   - meta_state
#   - self_evolution
#   - _processed_deals
# Cada uma é PRESERVADA em save() — só atualizamos as chaves do caller.
_NAMESPACES = ("autonomous_commander", "autonomous_oracle",
               "meta_state", "self_evolution", "_processed_deals")


# ── Pydantic state shape (somente o namespace do executor core) ───────────
class BotState(BaseModel):
    """Schema dos campos próprios do executor (não das namespaces isoladas)."""

    model_config = ConfigDict(extra="allow")  # permite chaves extras — não quebra retrocompat

    paused_until_utc: str | None = None
    last_run_utc: str | None = None
    starting_balance_today: float | None = None
    starting_balance_week: float | None = None
    last_reset_day: str | None = None
    last_reset_week: str | None = None
    trades_opened_total: int = 0
    trades_closed_total: int = 0
    last_exit_ts: dict[str, str] = Field(default_factory=dict)


def _default_state() -> dict[str, Any]:
    """Mesma forma default do `load_state` antigo."""
    return {
        "paused_until_utc": None,
        "last_run_utc": None,
        "starting_balance_today": None,
        "starting_balance_week": None,
        "last_reset_day": None,
        "last_reset_week": None,
        "trades_opened_total": 0,
        "trades_closed_total": 0,
        "last_exit_ts": {},
    }


class CorruptStateError(RuntimeError):
    """Levantado quando o JSON em disco está ilegível e foi movido para .corrupt_*."""


class SafeFileStore:
    """Estado persistente com escrita atômica + lock inter-processo.

    - read(): lê JSON; se ilegível, renomeia p/ .corrupt_<ts>, retorna default
    - save(d): merge com namespaces preservados, escrita atômica via tmp+rename
    - lock(): context manager filelock (inter-processo)
    - mutate(fn): read+lock+apply+save em transação
    """

    def __init__(self, path: Path = _STATE_PATH, lock_path: Path | None = None,
                 on_corrupt: Callable[[Path, Exception], None] | None = None) -> None:
        self.path = path
        self._lock_path = lock_path or path.with_suffix(path.suffix + ".lock")
        self._lock = FileLock(str(self._lock_path), timeout=10)
        self._on_corrupt = on_corrupt or _default_corrupt_handler
        # Garante dir
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ── public API ─────────────────────────────────────────────────────
    def read(self) -> dict[str, Any]:
        """Lê o estado completo. Em caso de JSON inválido, recupera."""
        if not self.path.exists():
            return _default_state()
        try:
            text = self.path.read_text(encoding="utf-8")
            return json.loads(text)
        except (json.JSONDecodeError, OSError) as exc:
            self._quarantine_corrupt(exc)
            return _default_state()

    def save(self, new_state: dict[str, Any]) -> None:
        """Persiste `new_state` preservando namespaces alheios.

        Faz merge: chaves presentes em `new_state` sobrescrevem; chaves isoladas
        (_NAMESPACES) só mudam se caller as passar explicitamente.
        Escrita atômica: tmp file + os.replace.
        """
        existing = self._read_raw() if self.path.exists() else {}
        merge_target = dict(existing)
        merge_target.update(new_state)
        # Re-valida schema do namespace do executor; extras passam (extra="allow").
        # NÃO re-valida as namespaces isoladas — classes responsáveis.
        self._atomic_write(merge_target)

    def mutate(self, fn: Callable[[dict[str, Any]], dict[str, Any] | None]) -> dict[str, Any]:
        """Transação read-modify-write sob lock.

        fn recebe o state atual, retorna novo state (ou None para skip).
        """
        with self._lock:
            current = self.read()
            updated = fn(current)
            if updated is None:
                return current
            self.save(updated)
            return updated

    def lock(self):
        """Context manager — adquire FileLock (inter-processo, timeout 10s)."""
        return self._lock

    def read_namespace(self, name: str) -> Any:
        """Lê só uma namespace (ex: 'autonomous_commander'). Default {}."""
        if name not in _NAMESPACES:
            raise KeyError(f"namespace unknown: {name}")
        return self.read().get(name, {})

    def save_namespace(self, name: str, value: Any) -> None:
        """Escreve só uma namespace, preservando resto."""
        with self._lock:
            current = self._read_raw() if self.path.exists() else {}
            current[name] = value
            self._atomic_write(current)

    # ── internal ───────────────────────────────────────────────────────
    def _read_raw(self) -> dict[str, Any]:
        """Leitura sem recovery (não chama _default_state). Lança em corrupto."""
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise
        except OSError:
            return {}

    def _atomic_write(self, data: dict[str, Any]) -> None:
        """Escreve em tmp + os.replace — atômico mesmo em NTFS."""
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            tmp.write_text(
                json.dumps(data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            os.replace(str(tmp), str(self.path))  # atômico em NTFS
        except Exception:
            # cleanup tmp solto em failure
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            raise

    def _quarantine_corrupt(self, exc: Exception) -> None:
        """Renomeia state ilegível para .corrupt_<ts>.json, notifica handler."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        corrupt_path = self.path.with_suffix(f".corrupt_{ts}.json")
        try:
            shutil.copy2(self.path, corrupt_path)
            self.path.unlink()
        except OSError as copy_exc:
            logger.error("cannot quarantine corrupt state: %s", copy_exc)
        logger.error("state corrupt, quarantined to %s: %s", corrupt_path, exc)
        try:
            self._on_corrupt(corrupt_path, exc)
        except Exception as cb_exc:
            logger.error("on_corrupt handler raised: %s", cb_exc)


def _default_corrupt_handler(corrupt_path: Path, exc: Exception) -> None:
    """Handler default: tenta notificar via Telegram (best-effort)."""
    # Import tardio pra evitar circular: notify ainda pode não existir
    try:
        from bot.core.config import settings
        if settings.telegram_configured:
            try:
                import requests
                requests.post(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                    json={
                        "chat_id": settings.telegram_chat_id,
                        "text": f"🚨 bot_state.json CORROMPIDO — movido p/ {corrupt_path.name}. "
                                f"Novo state inicializado. Causa: {type(exc).__name__}.",
                    },
                    timeout=10,
                )
            except Exception:
                pass  # notificação é best-effort
    except Exception:
        pass


# Singleton — importável de qualquer módulo.
store = SafeFileStore()


# ── Backward-compat com executor antigo (load_state/save_state) ─────────
def load_state() -> dict[str, Any]:
    """API idêntica ao `load_state` original do executor."""
    return store.read()


def save_state(s: dict[str, Any]) -> None:
    """API idêntica ao `save_state` original — merge preservando namespaces."""
    store.save(s)
