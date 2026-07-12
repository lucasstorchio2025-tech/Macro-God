"""
meta_learner.py — RAG + LLM (Gemma 4-opt via Ollama) para metacognicao.

O LLM e consultado PERIODICAMENTE (a cada N trades ou em gatilhos) para
analisar o desempenho recente do bot e gerar recomendacoes de ajuste.

RAG (Retrieval-Augmented Generation):
  - Os "documentos" sao os proprios logs do bot (trade_log.jsonl, decision_log.jsonl)
  - O pre-processamento em Python extrai metricas reais destes logs
  - O prompt so contem DADOS REAIS — o LLM nunca "inventa" numeros
  - O LLM so interpreta os dados que recebeu

Fluxo:
  1. Le trade_log.jsonl (ultimos N trades)
  2. Le decision_log.jsonl (ultimas decisoes)
  3. Le market_snapshot.json (contexto de mercado atual)
  4. Estrutura tudo em um prompt
  5. Envia para Gemma 4-opt via Ollama API
  6. Valida o JSON de resposta
  7. Atualiza MetaState com a recomendacao
"""
from __future__ import annotations

import json
import os
import subprocess
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from engine.meta_config import MetaState, DEFAULT_RISK_MULT

# ── Configuracao Ollama ──
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("META_LLM_MODEL", "gemma4-opt:latest")
OLLAMA_TIMEOUT = 30  # segundos

# ── Paths ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOT_DIR = PROJECT_ROOT / "bot"
TRADE_LOG_PATH = BOT_DIR / "trade_log.jsonl"
DECISION_LOG_PATH = BOT_DIR / "decision_log.jsonl"
INTEL_PATH = PROJECT_ROOT / "market_intelligence.json"
STATE_PATH = BOT_DIR / "bot_state.json"

# ── Prompt Template ──
META_ANALYSIS_PROMPT = """You are a professional trading system analyst.

Your role: analyze the BOT's recent performance data and recommend a risk multiplier.

CRITICAL RULES (violating these will cause losses):
1. NEVER recommend changing trade direction (BUY/SELL) — that is the strategy's job.
2. NEVER recommend new fixed parameters — only relative multipliers.
3. ONLY recommend changes if there is a clear, statistically relevant pattern (>10 trades in a bucket).
4. Base your analysis SOLELY on the data provided below. Do not invent numbers.
5. Default risk_multiplier is 1.0 (no change). Only deviate if data clearly shows a problem.

CONTEXT:
- Regime: {regime}
- VIX: {vix} (change: {vix_chg}%)
- DXY: {dxy} (change: {dxy_chg}%)
- Gold-equity correlation: {ge_corr}

ROLLING METRICS (last {rolling_n} trades):
- Win Rate: {win_rate}%
- Payoff (avg RR): {payoff}
- SL Rate: {sl_rate}%
- Consecutive Losses: {consecutive_losses}
- Avg PnL per Trade: ${avg_pnl}

PERFORMANCE BY CONTEXT (buckets with >=10 trades):
{buckets_text}

RECENT DECISIONS SUMMARY:
- Total decisions in log: {total_decisions}
- Result distribution: {result_dist}
- Top blocking filters: {top_filters}

TASK:
Based ONLY on the data above, recommend a risk multiplier for the next trading cycle.

A risk_multiplier of:
- 1.0 = keep current risk (normal)
- 0.7 = reduce risk by 30% (use when specific bucket is underperforming)
- 0.5 = reduce risk by 50% (use when multiple buckets or overall trend is bad)
- 1.3 = increase risk by 30% (use only if ALL buckets show strong, consistent performance)

Respond with ONLY valid JSON in this exact format (no markdown, no explanation):
{{"risk_multiplier": 1.0, "confidence": 0.9, "reasoning": "string under 200 chars"}}

Constraints:
- risk_multiplier must be between 0.1 and 2.0
- confidence must be between 0.0 and 1.0
- reasoning must be under 200 characters
"""


# ═════════════════════════════ LEITURA DOS LOGS ═════════════════════════════

def read_trade_log(n_last: int = 50) -> list[dict]:
    """Le os ultimos N trades do trade_log.jsonl."""
    if not TRADE_LOG_PATH.exists():
        return []
    try:
        lines = TRADE_LOG_PATH.read_text(encoding="utf-8").splitlines()
        lines = lines[-n_last:]
        return [json.loads(l) for l in lines if l.strip()]
    except Exception:
        return []


def read_decision_log(n_last: int = 200) -> list[dict]:
    """Le as ultimas N decisoes do decision_log.jsonl."""
    if not DECISION_LOG_PATH.exists():
        return []
    try:
        lines = DECISION_LOG_PATH.read_text(encoding="utf-8").splitlines()
        lines = lines[-n_last:]
        return [json.loads(l) for l in lines if l.strip()]
    except Exception:
        return []


def read_market_context() -> dict:
    """Le o snapshot de mercado atual do market_intelligence.json."""
    if not INTEL_PATH.exists():
        return {}
    try:
        data = json.loads(INTEL_PATH.read_text(encoding="utf-8"))
        rs = data.get("risk_sentiment", {})
        return {
            "regime": data.get("regime", "unknown"),
            "vix": rs.get("vix"),
            "vix_chg": rs.get("vix_pct_change"),
            "dxy": rs.get("dollar_index"),
            "dxy_chg": rs.get("dollar_index_pct_change"),
            "ge_corr": data.get("gold_equity_correlation"),
        }
    except Exception:
        return {}


def summarize_decisions(decisions: list[dict]) -> tuple[str, str]:
    """Extrai distribuicao de resultados e top filtros do decision_log."""
    results = Counter()
    filters = Counter()
    for d in decisions:
        payload = d.get("payload", {})
        r = payload.get("result", "unknown")
        results[r] += 1
        fb = payload.get("filter_blocked")
        if fb:
            filters[fb] += 1

    result_dist = ", ".join(f"{k}={v}" for k, v in results.most_common(6))
    top_filters = ", ".join(f"{k}({v})" for k, v in filters.most_common(3))
    return result_dist, top_filters


# ═════════════════════════════ CHAMADA OLLAMA ═════════════════════════════

def call_ollama(prompt: str, model: str = OLLAMA_MODEL,
                timeout: int = OLLAMA_TIMEOUT) -> Optional[str]:
    """Chama o modelo via Ollama API.

    Tenta API HTTP primeiro (requests), depois fallback para subprocess.
    """
    # Tentativa 1: API HTTP
    try:
        resp = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,   # temperatura baixa = deterministico
                    "num_predict": 512,    # max tokens na resposta
                },
            },
            timeout=timeout,
        )
        if resp.status_code == 200:
            data = resp.json()
            raw = data.get("response", "").strip()
            # Limpa possivel marcacao markdown
            raw = raw.replace("```json", "").replace("```", "").strip()
            return raw
        else:
            print(f"[meta_learner] Ollama API error: {resp.status_code} {resp.text[:200]}")
    except requests.exceptions.ConnectionError:
        print("[meta_learner] Ollama API nao respondeu em HTTP, tentando subprocess...")
    except Exception as e:
        print(f"[meta_learner] Ollama HTTP error: {type(e).__name__}: {e}")

    # Tentativa 2: subprocess (fallback)
    try:
        result = subprocess.run(
            ["ollama", "run", model],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            raw = result.stdout.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            return raw
        else:
            print(f"[meta_learner] Ollama CLI error: {result.stderr[:200]}")
    except FileNotFoundError:
        print("[meta_learner] Ollama CLI nao encontrado. Instale ollama ou verifique PATH.")
    except subprocess.TimeoutExpired:
        print(f"[meta_learner] Ollama timeout ({timeout}s)")
    except Exception as e:
        print(f"[meta_learner] Ollama subprocess error: {type(e).__name__}: {e}")

    return None


# ═════════════════════════════ PARSER / VALIDACAO ═════════════════════════════

def parse_llm_response(raw: str) -> Optional[dict]:
    """Tenta parsear JSON da resposta do LLM com validacao.

    Retorna dict com risk_multiplier, confidence, reasoning.
    Retorna None se resposta invalida.
    """
    if not raw:
        return None

    # Tenta parse direto
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Tenta encontrar JSON dentro do texto
        import re
        matches = re.findall(r'\{[^{}]*"risk_multiplier"[^{}]*\}', raw)
        if not matches:
            return None
        try:
            data = json.loads(matches[0])
        except json.JSONDecodeError:
            return None

    # Validacao de schema
    if not isinstance(data, dict):
        return None

    rm = data.get("risk_multiplier", DEFAULT_RISK_MULT)
    confidence = data.get("confidence", 0.0)
    reasoning = str(data.get("reasoning", ""))[:200]

    # Validacao de limites
    if not isinstance(rm, (int, float)):
        rm = DEFAULT_RISK_MULT
    rm = max(0.1, min(2.0, float(rm)))
    confidence = max(0.0, min(1.0, float(confidence)))

    return {
        "risk_multiplier": rm,
        "confidence": round(confidence, 2),
        "reasoning": reasoning,
    }


# ═════════════════════════════ CONSULTA COMPLETA ═════════════════════════════

def consult_llm(meta: MetaState, force: bool = False) -> Optional[dict]:
    """Executa uma consulta completa ao LLM: RAG + prompt + chamada + validacao.

    Args:
        meta: MetaState atual
        force: True = consulta mesmo sem gatilho

    Returns:
        Dict com recomendacao validada, ou None se nao necessario/falhou.
    """
    # Verifica se precisa consultar
    if not force and not meta.needs_llm_consult:
        return None

    print(f"\n[meta_learner] Consultando {OLLAMA_MODEL}...")
    print(f"  Gatilho: trades_since_last={meta.trades_since_last_consult}, "
          f"streak={meta.consecutive_losses}, total={meta.total_trades_analyzed}")

    # ── 1. RAG: Coleta dados reais ──
    market = read_market_context()
    decisions = read_decision_log()
    result_dist, top_filters = summarize_decisions(decisions)

    # ── 2. Prepara contexto do MetaState ──
    ctx = meta.get_llm_context()
    rolling = ctx["rolling"]
    buckets = ctx["buckets"]

    # Formata buckets para o prompt
    if buckets:
        buckets_text = "\n".join(
            f"  {b['key']}: {b['n']} trades, WR={b['win_rate']:.1%}, "
            f"avg RR={b['avg_rr']:.2f}, avg PnL=${b['avg_pnl']:.2f}"
            for b in buckets[:8]  # max 8 buckets pra nao estourar contexto
        )
    else:
        buckets_text = "  (nenhum bucket com dados suficientes ainda)"

    # ── 3. Monta prompt ──
    prompt = META_ANALYSIS_PROMPT.format(
        regime=market.get("regime", "unknown"),
        vix=market.get("vix", "N/A"),
        vix_chg=market.get("vix_chg", "N/A"),
        dxy=market.get("dxy", "N/A"),
        dxy_chg=market.get("dxy_chg", "N/A"),
        ge_corr=market.get("ge_corr", "N/A"),
        rolling_n=rolling["n"],
        win_rate=round(rolling["win_rate"] * 100, 1),
        payoff=rolling["payoff"],
        sl_rate=round(rolling["sl_rate"] * 100, 1),
        consecutive_losses=rolling["consecutive_losses"],
        avg_pnl=rolling["avg_pnl"],
        buckets_text=buckets_text,
        total_decisions=len(decisions),
        result_dist=result_dist,
        top_filters=top_filters,
    )

    # ── 4. Chama Ollama ──
    raw_response = call_ollama(prompt)

    if not raw_response:
        print(f"  [AVISO] Ollama nao retornou resposta. Usando fallback (1.0).")
        return None

    # ── 5. Valida resposta ──
    rec = parse_llm_response(raw_response)
    if rec is None:
        print(f"  [AVISO] Resposta invalida do LLM. Raw: {raw_response[:200]}")
        return None

    print(f"  [OK] Recomendacao: risk_mult={rec['risk_multiplier']:.2f}, "
          f"confianca={rec['confidence']:.2f}")
    print(f"  Raciocinio: {rec['reasoning']}")

    # ── 6. Aplica no MetaState ──
    meta.apply_llm_recommendation(rec)
    save_meta_state_to_file(meta)

    return rec


def save_meta_state_to_file(meta: MetaState):
    """Salva MetaState no bot_state.json."""
    from engine.meta_config import save_meta_state
    try:
        save_meta_state(STATE_PATH, meta)
    except Exception as e:
        print(f"[meta_learner] Erro ao salvar estado: {e}")


def quick_analysis(meta: MetaState) -> str:
    """Gera um resumo legivel do estado meta atual."""
    ctx = meta.get_llm_context()
    rolling = ctx["rolling"]
    lines = [
        f"[META] Rolling ({rolling['n']} trades): WR={rolling['win_rate']:.1%}, "
        f"Payoff={rolling['payoff']:.2f}, SL={rolling['sl_rate']:.1%}",
    ]
    if meta.risk_multiplier != 1.0:
        lines.append(
            f"[META] Risk Mult: {meta.risk_multiplier:.2f} "
            f"(conf={meta.risk_multiplier_confidence:.0%}) "
            f"- {meta.risk_multiplier_reasoning}"
        )
    return "\n".join(lines)


__all__ = [
    "consult_llm", "quick_analysis", "call_ollama", "parse_llm_response",
    "read_trade_log", "read_decision_log", "read_market_context",
]
