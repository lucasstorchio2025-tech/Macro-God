"""bot.api.server — FastAPI read-only para Wealth Engine (P2-B).

Endpoints JSON puros, sem estado, re-lê arquivos a cada request.
Auth: Bearer token via .env DASHBOARD_TOKEN.
Roda em 127.0.0.1:8000 (não exposto).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

BOT_DIR = PROJECT_ROOT / "bot"
RUN_DIR = BOT_DIR / "run"

# Token do .env
DASHBOARD_TOKEN = os.environ.get("DASHBOARD_TOKEN")
if not DASHBOARD_TOKEN:
    # Fallback pra development — em produção deve estar no .env
    DASHBOARD_TOKEN = "dev-token-change-me"


def verify_token(authorization: Optional[str] = Header(None)) -> str:
    """Valida Bearer token."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth scheme")
    token = authorization[7:]
    if token != DASHBOARD_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")
    return token


app = FastAPI(
    title="Wealth Engine API",
    description="Read-only endpoints for bot monitoring",
    version="v4",
    dependencies=[Depends(verify_token)],
)


# ── Response models ─────────────────────────────────────────────────────
class HealthResponse(BaseModel):
    status: str
    timestamp: str
    uptime_seconds: Optional[float] = None


class StatusResponse(BaseModel):
    manager: dict
    heartbeat: dict
    children: dict


class MetricsResponse(BaseModel):
    balance: float
    equity: float
    pnl_unrealized: float
    drawdown_pct: float
    open_positions: int
    trades_opened_total: int
    trades_closed_total: int
    risk_multiplier: float


class TradeItem(BaseModel):
    ts_utc: str
    symbol: str
    direction: str
    volume: float
    entry: float
    exit: Optional[float] = None
    pnl: Optional[float] = None
    result: str  # opened | closed | dry_run | blocked_filter | no_signal | error


class DecisionItem(BaseModel):
    ts_utc: str
    symbol: str
    direction: str
    result: str
    filter_blocked: Optional[str] = None
    reason: Optional[str] = None
    lot: Optional[float] = None
    entry: Optional[float] = None
    sl: Optional[float] = None
    tp: Optional[float] = None


class RegimeResponse(BaseModel):
    current: str
    risk_score: int
    vix: Optional[float] = None
    dxy: Optional[float] = None
    thesis_summary: str


# ── Helpers ──────────────────────────────────────────────────────────────
def _read_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _read_jsonl(path: Path, limit: int = 50) -> list[dict]:
    if not path.exists():
        return []
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        pass
    return out[-limit:]


def _parse_ts(ts_str: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        return None


# ── Endpoints ────────────────────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse)
async def health():
    """Healthcheck simples (sem auth via dependency override se necessário)."""
    hb = _read_json(RUN_DIR / "heartbeat.json")
    uptime = None
    if hb.get("ts"):
        try:
            hb_ts = _parse_ts(hb["ts"])
            if hb_ts:
                uptime = (datetime.now(timezone.utc) - hb_ts).total_seconds()
        except Exception:
            pass
    return HealthResponse(
        status="ok" if hb.get("alive") else "degraded",
        timestamp=datetime.now(timezone.utc).isoformat(),
        uptime_seconds=uptime,
    )


@app.get("/status", response_model=StatusResponse)
async def status():
    """Status completo do manager + heartbeat + filhos."""
    return StatusResponse(
        manager=_read_json(RUN_DIR / "wealth.pid") or {},
        heartbeat=_read_json(RUN_DIR / "heartbeat.json"),
        children={},  # manager.py já expõe no heartbeat
    )


@app.get("/metrics", response_model=MetricsResponse)
async def metrics():
    """Métricas atuais: balance, equity, DD, posições, risk multiplier."""
    state = _read_json(BOT_DIR / "bot_state.json")
    acc = _read_json(RUN_DIR / "account_info.json")  # opcional, se bot escrever
    return MetricsResponse(
        balance=state.get("starting_balance_today") or 0.0,
        equity=acc.get("equity", 0.0),
        pnl_unrealized=acc.get("profit", 0.0),
        drawdown_pct=0.0,  # calcular se tiver base
        open_positions=state.get("open_positions", 0),
        trades_opened_total=state.get("trades_opened_total", 0),
        trades_closed_total=state.get("trades_closed_total", 0),
        risk_multiplier=state.get("risk_multiplier", 1.0),
    )


@app.get("/trades", response_model=list[TradeItem])
async def trades(n: int = Query(50, ge=1, le=500)):
    """Últimos N trades (decision_log filtrado)."""
    decisions = _read_jsonl(BOT_DIR / "decision_log.jsonl", limit=n * 2)
    out = []
    for d in decisions:
        p = d.get("payload", {})
        if p.get("result") in ("opened", "closed", "dry_run", "blocked_filter", "no_signal", "error"):
            out.append(TradeItem(
                ts_utc=d.get("ts_utc", ""),
                symbol=p.get("symbol", ""),
                direction=p.get("direction", ""),
                volume=p.get("lot", 0.0),
                entry=p.get("entry"),
                exit=p.get("exit"),
                pnl=p.get("pnl"),
                result=p["result"],
            ))
    return out[-n:]


@app.get("/decisions", response_model=list[DecisionItem])
async def decisions(n: int = Query(50, ge=1, le=500)):
    """Últimas N decisões completas."""
    decisions = _read_jsonl(BOT_DIR / "decision_log.jsonl", limit=n)
    out = []
    for d in decisions:
        p = d.get("payload", {})
        out.append(DecisionItem(
            ts_utc=d.get("ts_utc", ""),
            symbol=p.get("symbol", ""),
            direction=p.get("direction", ""),
            result=p.get("result", ""),
            filter_blocked=p.get("filter_blocked"),
            reason=p.get("reasoning", {}).get("reason"),
            lot=p.get("lot"),
            entry=p.get("entry"),
            sl=p.get("sl"),
            tp=p.get("tp"),
        ))
    return out


@app.get("/regime", response_model=RegimeResponse)
async def regime():
    """Regime atual + macro thesis (lê market_intelligence.json)."""
    intel = _read_json(PROJECT_ROOT / "market_intelligence.json")
    thesis = intel.get("regime_thesis", {})
    return RegimeResponse(
        current=thesis.get("regime", "unknown"),
        risk_score=thesis.get("risk_score", 50),
        vix=intel.get("risk_sentiment", {}).get("vix"),
        dxy=intel.get("dxy", {}).get("value"),
        thesis_summary=thesis.get("summary_pt", "Sem thesis disponível"),
    )


# ── Main ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")