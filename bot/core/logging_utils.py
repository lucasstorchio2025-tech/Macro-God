"""bot.core.logging_utils — logging estruturado JSONL.

P0-C: substitui log_event do executor.py com written atômico e sem
dependência circular (executor importa logging_utils, não o contrário).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parents[1]
LOG_PATH = BOT_DIR / "trade_log.jsonl"

logger = logging.getLogger(__name__)


def log_event(event_type: str, payload: dict) -> None:
    """Append linha JSON em trade_log.jsonl. Cada linha = 1 evento. Nunca sobrescreve."""
    event = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "payload": payload,
    }
    # Atomic append: write to temp + rename não faz sentido para append-only log
    # Mas garantimos que o arquivo existe e escrevemos com flush
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
            f.flush()
    except OSError as exc:
        logger.error("log_event write failed: %s", exc)


def log_cycle_start(cycle_num: int, balance: float) -> None:
    log_event("CYCLE_START", {"cycle": cycle_num, "balance": round(balance, 2)})


def log_cycle_end(cycle_num: int, summary: dict) -> None:
    log_event("CYCLE_END", {"cycle": cycle_num, **summary})


# ── Meta-state feed (extracted from old executor) ──────────────────────
def _feed_closed_trades_to_meta(meta: MetaState, intel: dict, state: dict):
    """Processa DEAL_FOUND events do trade_log e alimenta MetaState com trades fechados."""
    from engine.meta_config import MetaState
    processed = set(state.get("_processed_deals", []))
    if not LOG_PATH.exists():
        return
    try:
        lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
        new_deals = 0
        for line in lines:
            try:
                ev = json.loads(line)
                if ev.get("type") != "DEAL_FOUND":
                    continue
                payload = ev.get("payload", {})
                deal_ticket = payload.get("deal")
                if not deal_ticket or deal_ticket in processed:
                    continue
                profit = payload.get("profit", 0)
                if profit == 0:
                    continue
                processed.add(deal_ticket)

                d_type = payload.get("type", 0)
                direction = "BUY" if d_type == 0 else "SELL"
                regime = "unknown"
                if intel:
                    regime = intel.get("regime", "unknown")

                if profit > 0:
                    rr_est = 2.0
                    reason = "TP"
                else:
                    rr_est = -1.0
                    reason = "SL"

                trade = {
                    "symbol": payload.get("symbol", "?"),
                    "direction": direction,
                    "pnl_usd": profit,
                    "rr_realized": rr_est,
                    "exit_reason": reason,
                    "regime_at_entry": regime,
                    "atr_stop_mult": 1.5,
                    "ts_utc": ev.get("ts_utc", ""),
                }
                meta.on_trade_close(trade)
                new_deals += 1
            except Exception:
                continue
        if new_deals:
            # salva deals processados no state
            sorted_deals = sorted(processed)[-500:]
            state["_processed_deals"] = sorted_deals
            print(f"  [META] {new_deals} novos trades alimentados no MetaState")
    except Exception as e:
        print(f"  [META] Erro ao alimentar MetaState: {e}")