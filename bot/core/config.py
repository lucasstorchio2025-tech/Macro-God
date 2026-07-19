"""bot.core.config — carregamento único de .env do projeto.

P0-C: substitui `load_dotenv(Path.home() / ".hermes" / ".env")` que misturava
perfil Hermes com projeto. Agora lê SÓ `.env` do projeto, uma vez, no import.

Uso:
    from bot.core.config import settings
    settings.TELEGRAM_BOT_TOKEN
    settings.EXNESS_LOGIN
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# .env do projeto. NÃO carrega ~/.hermes/.env — separação de perfis.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # bot/core/config.py -> ../../..
_ENV_PATH = _PROJECT_ROOT / ".env"

# override=False: não caga em variáveis já definidas no shell (útil p/ testes).
load_dotenv(_ENV_PATH, override=False)


@dataclass(frozen=True)
class ProjectSettings:
    """Todas as credenciais/configs do .env do projeto.

    Frozen dataclass — imutável, testável. Se faltar uma chave essencial,
    accessa via property que valida.
    """

    project_root: Path
    telegram_bot_token: str
    telegram_chat_id: str
    exness_login: str
    exness_password: str
    exness_server: str
    finnhub_api_key: str
    fred_api_key: str
    ollama_host: str
    dashboard_password: str | None
    poll_seconds: int

    @property
    def telegram_configured(self) -> bool:
        """True se ambas as credenciais Telegram estão presentes e não-placeholder."""
        t = self.telegram_bot_token
        c = self.telegram_chat_id
        return bool(t) and not t.startswith("COLOQUE") and bool(c) and not c.startswith("COLOQUE")

    @property
    def exness_configured(self) -> bool:
        return bool(self.exness_login) and bool(self.exness_password) and bool(self.exness_server)


def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


settings = ProjectSettings(
    project_root=_PROJECT_ROOT,
    telegram_bot_token=_get("TELEGRAM_BOT_TOKEN"),
    telegram_chat_id=_get("TELEGRAM_CHAT_ID"),
    exness_login=_get("EXNESS_LOGIN"),
    exness_password=_get("EXNESS_PASSWORD"),
    exness_server=_get("EXNESS_SERVER"),
    finnhub_api_key=_get("FINNHUB_API_KEY"),
    fred_api_key=_get("FRED_API_KEY"),
    ollama_host=_get("OLLAMA_HOST", "http://localhost:11434"),
    dashboard_password=_get("DASHBOARD_PASSWORD") or None,
    poll_seconds=int(_get("WEALTH_POLL_SECONDS", "300")),
)
