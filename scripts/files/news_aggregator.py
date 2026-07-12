"""
news_aggregator.py
-------------------
Junta notícia de VÁRIAS fontes globais (não só um site), remove duplicado,
e usa SEU modelo local (via Ollama) só pra CLASSIFICAR o que já foi coletado
de fonte real -- ele nunca inventa notícia, só rotula relevância/impacto.

Truque principal: em vez de manter uma lista fixa de sites (que quebra
quando o site muda o RSS), isso usa o Google News RSS de busca por tópico --
é assim que se cobre "tudo que acontece no mundo" sem manter dezenas de
integrações individuais. Cada tópico abaixo já agrega milhares de fontes.

Requisitos:
    pip install feedparser requests

Configurar:
    OLLAMA_MODEL -- nome do modelo que você já tem carregado (ollama list)
    Ollama precisa estar rodando (normalmente já fica em background)
"""

import json
import re
import hashlib
import urllib.parse
import os
from datetime import datetime, timezone

# Carrega chaves e modelos do .env (sem editar o script)
try:
    from dotenv import load_dotenv
    _hermes_env = str(Path.home() / ".hermes" / ".env")
    if os.path.exists(_hermes_env):
        load_dotenv(_hermes_env, override=False)
except ImportError:
    pass

import feedparser
import requests

# ============== CONFIG ==============
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4-opt:latest")
OUTPUT_PATH = os.environ.get("WEALTH_NEWS_PATH", str(_PROJECT_ROOT / "filtered_news.json"))
MAX_PER_BATCH = 12  # quantas manchetes manda pro modelo classificar por chamada

# Fontes fixas (oficiais, confirmadas, alta confiabilidade)
FIXED_FEEDS = {
    "fed_monetary_policy": "https://www.federalreserve.gov/feeds/press_monetary.xml",
    "fed_all_press": "https://www.federalreserve.gov/feeds/press_all.xml",
    "investing_com": "https://www.investing.com/rss/news.rss",
    "bbc_business": "https://feeds.bbci.co.uk/news/business/rss.xml",
}

# Tópicos buscados via Google News RSS -- é AQUI que você escala "todos os locais"
# Só adicionar uma string nova já cobre uma área inteira (geopolítica, banco central, etc.)
GOOGLE_NEWS_TOPICS = [
    "Federal Reserve interest rate decision",
    "ECB monetary policy euro",
    "Trump tariffs economy",
    "geopolitical risk markets",
    "war ceasefire negotiations",
    "China economy trade",
    "oil prices OPEC",
    "central bank inflation",
]
# =====================================


def _google_news_url(topic, hours=24):
    q = urllib.parse.quote(f"{topic} when:{max(hours // 24, 1)}d")
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def fetch_all_headlines():
    """Coleta texto REAL de cada fonte -- nenhuma IA envolvida nessa etapa."""
    sources = dict(FIXED_FEEDS)
    for topic in GOOGLE_NEWS_TOPICS:
        sources[f"google_news::{topic}"] = _google_news_url(topic)

    items = []
    for source, url in sources.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:
                items.append({
                    "source": source,
                    "headline": entry.get("title", "").strip(),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                })
        except Exception as e:
            print(f"[AVISO] Falha ao ler {source}: {e}")
    return _dedup(items)


def _dedup(items):
    """Várias fontes reportam a mesma notícia com título quase idêntico -- remove repetição."""
    seen = set()
    unique = []
    for item in items:
        norm = re.sub(r"[^a-z0-9 ]", "", item["headline"].lower())
        key = hashlib.md5(norm.encode()).hexdigest()[:12]
        if key not in seen and norm.strip():
            seen.add(key)
            unique.append(item)
    return unique


def _classify_batch(batch):
    """Manda manchetes JÁ COLETADAS pro modelo local só classificar -- zero invenção de dado."""
    numbered = "\n".join(f"{i+1}. {h['headline']}" for i, h in enumerate(batch))
    prompt = f"""Classifique as manchetes REAIS abaixo (já coletadas, não invente conteúdo novo).
Responda SOMENTE um JSON (lista de objetos), um por manchete, com os campos:
"n" (número inteiro), "relevante" (true/false -- importa pra forex/macro/geopolítica com impacto econômico?),
"impacto" ("alto"/"medio"/"baixo"/"nenhum"), "ativos_afetados" (lista, ex: ["USD","EUR","XAUUSD"]),
"vies" ("hawkish"/"dovish"/"risk_on"/"risk_off"/"neutro").

Manchetes:
{numbered}

Responda SÓ o JSON válido, sem markdown, sem texto antes ou depois. Se não conseguir, responda []."""

    try:
        r = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2, "num_predict": 1200},
        }, timeout=180)
        r.raise_for_status()
        content = r.json().get("message", {}).get("content", "").strip()
        # Defensivo: às vezes Ollama embrulha em ```json``` ou tem prefixo
        if content.startswith("```"):
            content = content.split("```", 2)[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()
        # Tenta parse direto; se vier string em vez de list, embrulha
        parsed = json.loads(content)
        if isinstance(parsed, dict) and "noticias" in parsed:
            parsed = parsed["noticias"]
        if not isinstance(parsed, list):
            return []
        return parsed
    except Exception as e:
        print(f"[AVISO] Classificação falhou nesse lote (segue sem): {type(e).__name__}: {e}")
        return []


def _ollama_smoke_test():
    """Confirma que o Ollama responde JSON simples antes de gastar tempo classificando manchetes.
    Se falhar, aborta cedo com mensagem útil em vez de devolver arrays vazios em silêncio."""
    try:
        r = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": "Responda SOMENTE um JSON: [{\"n\":1,\"relevante\":true}]"}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0, "num_predict": 80},
        }, timeout=60)
        r.raise_for_status()
        content = r.json().get("message", {}).get("content", "").strip()
        parsed = json.loads(content)
        if not isinstance(parsed, list) or not parsed:
            print(f"[SMOKE] Ollama respondeu JSON válido mas estrutura inesperada: {content[:200]}")
            return False
        print(f"[SMOKE] Ollama OK com modelo {OLLAMA_MODEL!r} ({len(content)} chars).")
        return True
    except Exception as e:
        print(f"[SMOKE] FALHOU: {type(e).__name__}: {e}")
        print(f"[SMOKE] Verifique: (1) Ollama rodando? (2) modelo {OLLAMA_MODEL!r} existe? Rode: ollama list")
        return False


def build_filtered_news():
    if not _ollama_smoke_test():
        print("[ABORTANDO] Sem classificador confiável. Coleta de notícias fica pausada.")
        return None
    raw = fetch_all_headlines()
    print(f"[INFO] {len(raw)} manchetes únicas coletadas de {len(FIXED_FEEDS) + len(GOOGLE_NEWS_TOPICS)} fontes/tópicos.")

    filtered = []
    for i in range(0, len(raw), MAX_PER_BATCH):
        batch = raw[i:i + MAX_PER_BATCH]
        for label in _classify_batch(batch):
            idx = label.get("n", 0) - 1
            if 0 <= idx < len(batch) and label.get("relevante") and label.get("impacto") != "nenhum":
                item = dict(batch[idx])
                item.update({
                    "impacto": label.get("impacto"),
                    "ativos_afetados": label.get("ativos_afetados", []),
                    "vies": label.get("vies"),
                })
                filtered.append(item)

    ordem_impacto = {"alto": 0, "medio": 1, "baixo": 2}
    filtered.sort(key=lambda x: ordem_impacto.get(x.get("impacto"), 3))

    output = {
        "last_update_utc": datetime.now(timezone.utc).isoformat(),
        "total_coletado": len(raw),
        "total_relevante": len(filtered),
        "noticias": filtered,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"[OK] {len(filtered)} de {len(raw)} notícias passaram o filtro. Salvo em {OUTPUT_PATH}")
    return output


if __name__ == "__main__":
    build_filtered_news()
