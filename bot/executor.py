"""Wealth_Engine v4 — Executor (Entry Point)
==========================================
Loop principal delega para bot.core.* (state, mt5_bridge, risk, decision, execution, notify).
~250 linhas — sem lógica de negócio inline.
"""
from __future__ import annotations

import os
import sys
import time
import signal
import traceback
from datetime import datetime, timezone
from pathlib import Path

# UTF-8 stdout/stderr
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

# Project root no path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Single .env loading (project only)
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env", override=False)

# Core modules (P0-A)
from bot.core import state, config, mt5_bridge, risk, decision, execution, notify, logging_utils, ratelimiter
from bot.core.state import store

# Engine configs & meta-cognition
from engine import config as C
from engine.meta_config import MetaState, load_meta_state, save_meta_state
from engine.meta_learner import consult_llm, quick_analysis, health_check_kill_switch
from bot.decision_log import build_decision_context, log_decision

# Autonomous Commander (P1-A)
from engine.commander import AutonomousCommander, CommanderDecisionContext
from bot.strategy_bridge import compute_signals_with_detail

# ── Paths & Constants ───────────────────────────────────────────────────
BOT_DIR = Path(__file__).resolve().parent
LOG_PATH = BOT_DIR / "trade_log.jsonl"
INTEL_PATH = PROJECT_ROOT / "market_intelligence.json"

SYMBOLS = C.SYMBOLS
MAX_OPEN_POSITIONS = C.MAX_OPEN_POSITIONS
TOTAL_RISK_CAP_PCT = C.TOTAL_RISK_CAP_PCT
RISK_PER_TRADE_PCT = C.RISK_PER_TRADE_PCT
RISK_OVERRIDE_PCT = C.RISK_OVERRIDE_PCT
MIN_RR = C.MIN_REWARD_RISK
MAGIC = C.EXNESS_MAGIC
COMMENT_TAG = C.COMMENT_TAG
POLL_SECONDS = int(os.environ.get("WEALTH_POLL_SECONDS", "300"))
COOLDOWN_SECONDS = C.COOLDOWN_BARS * 4 * 3600
DRY_RUN_MODE = C.DRY_RUN_MODE

# Bridge instances (injected, testable)
_bridge = mt5_bridge.bridge
_risk = risk.risk
_decision = decision.decision_engine
_executor = execution.executor
_notifier = notify.notifier

# Meta-cognition
_meta_state: MetaState | None = None

# Commander (injected at startup)
_commander: AutonomousCommander | None = None

# Graceful shutdown
_shutdown = False


def _signal_handler(signum, frame):
    global _shutdown
    _notifier.notify(f"Sinal {signum} recebido — encerrando graciosamente", "warn")
    _shutdown = True


def run_once(cycle_num: int) -> dict:
    """Executa 1 ciclo de decisão. Retorna summary para logging."""
    cycle_start = datetime.now(timezone.utc)
    summary = {"cycle": cycle_num, "cycle_start": cycle_start.isoformat(), "actions": []}

    # 1. MT5 connection
    if not _bridge.ensure_connected():
        summary["actions"].append({"step": "mt5_connect", "ok": False})
        # Notifica só 1 vez por sequência de falhas (não a cada ciclo)
        if not getattr(_bridge, "_notified_failure", False):
            _notifier.notify("MT5 não conectou — mercado fechado ou sessão expirada. "
                            "Bot aguarda reconexão automática.", "error")
            _bridge._notified_failure = True
        return summary

    acc = _bridge.account()
    if not acc:
        summary["actions"].append({"step": "account_info", "ok": False})
        _bridge.shutdown()
        return summary

    balance = acc.balance
    summary["balance"] = balance

    # 2. Load bot state (atomic + locked)
    bot_state = store.read()

    # 3. Load meta-state (rolling performance)
    global _meta_state
    if _meta_state is None:
        _meta_state = load_meta_state(store.path)
    meta_rm = _meta_state.get_risk_multiplier()
    summary["risk_multiplier"] = meta_rm

    # 4. Load intelligence (market data)
    intel = {}
    if INTEL_PATH.exists():
        try:
            import json
            intel = json.loads(INTEL_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            _notifier.notify(f"Intel load error: {exc}", "warn")

    # 5. Sync closed deals (SL/TP hits) → cooldown + meta-state
    new_deals = _executor.sync_closed_deals(bot_state)
    if new_deals:
        try:
            from bot.core.logging_utils import _feed_closed_trades_to_meta
            _feed_closed_trades_to_meta(_meta_state, intel, bot_state)
        except Exception as exc:
            _notifier.notify(f"MetaState feed error: {exc}", "warn")

    # 6. Risk filters (hard gates)
    risk_verdict = _risk.can_trade(balance, bot_state, intel)
    if risk_verdict.blocked:
        summary["actions"].append({"step": "risk_filters", "ok": False, "filter": risk_verdict.filter_name, "reason": risk_verdict.reason})
        _notifier.notify(risk_verdict.reason, "warn")
        _bridge.shutdown()
        return summary

    # 7. Open positions / symbols
    positions = _bridge.positions(MAGIC)
    open_count = len(positions)
    open_symbols = {p.symbol for p in positions}
    summary["open_positions"] = open_count
    summary["open_symbols"] = list(open_symbols)

    # 8. Commander cycle (autonomous decision)
    commander_order = None
    if _commander:
        try:
            # Compute signals for commander context
            sigs, details, regime_now = compute_signals_with_detail(_bridge)

            # Recent trades for commander context
            last_trades = []
            if LOG_PATH.exists():
                try:
                    import json
                    lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
                    last_trades = [json.loads(l) for l in lines if l.strip()][-30:]
                except Exception as exc:
                    _notifier.notify(f"Last trades load error: {exc}", "warn")

            ctx = CommanderDecisionContext(
                oracle=None,
                meta=_meta_state,
                evolution=None,
                signals=sigs,
                signal_details=details,
                balance=balance,
                open_positions=open_count,
                open_symbols=open_symbols,
                last_trades=last_trades,
                timestamp=cycle_start.isoformat(),
            )
            # Commander runs its own oracle + evolution + decision
            commander_order = _commander.cycle(
                intel=intel,
                prices=None,
                meta=_meta_state,
                signals=sigs,
                signal_details=details,
                balance=balance,
                open_positions=open_count,
                open_symbols=open_symbols,
                news_path=PROJECT_ROOT / "filtered_news.json",
                last_trades=last_trades,
            )
            summary["commander"] = commander_order.to_dict()

            # Execute commander order
            if commander_order.action == "close_all":
                closed = _executor.flatten_all(dry_run=DRY_RUN_MODE)
                summary["actions"].append({"step": "commander_close_all", "closed": closed})
                _notifier.crisis(f"[COMMANDER] Fechou {closed} posições: {commander_order.reasoning[:100]}")
                _bridge.shutdown()
                return summary
            elif commander_order.action == "wait":
                summary["actions"].append({"step": "commander_wait", "reason": commander_order.reasoning[:200]})
                _bridge.shutdown()
                return summary
            # "trade" → falls through to normal signal processing
        except Exception as exc:
            _notifier.notify(f"Commander error: {exc}", "warn")

    # 9. Normal signal processing (if commander didn't override)
    if open_count < MAX_OPEN_POSITIONS:
        sigs, details, regime_now = compute_signals_with_detail(_bridge)

        for sym in SYMBOLS:
            detail = details.get(sym, {})
            sig = sigs.get(sym, "NONE")

            decision_ctx = build_decision_context(intel, None, bot_state, balance)

            if sig == "NONE":
                log_decision(decision_ctx, sym, "NONE", "no_signal", detail.get("reason", "Sem sinal"))
                continue

            direction = "BUY" if sig == "BUY" else "SELL"
            size_frac = detail.get("size_frac", 0.05) if isinstance(sig, tuple) else 0.05

            # Anti-stacking
            if sym in open_symbols:
                log_decision(decision_ctx, sym, direction, "blocked_filter",
                           {"reason": "Anti-empilhamento"}, filter_blocked="already_open")
                continue

            # Cooldown
            last_exit = bot_state.get("last_exit_ts", {}).get(sym)
            if last_exit:
                try:
                    elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last_exit.replace("Z", "+00:00"))).total_seconds()
                    if elapsed < COOLDOWN_SECONDS:
                        log_decision(decision_ctx, sym, direction, "blocked_filter",
                                   {"reason": f"Cooldown {elapsed:.0f}s < {COOLDOWN_SECONDS}s"}, filter_blocked="cooldown")
                        continue
                except Exception as exc:
                    _notifier.notify(f"Cooldown parse error for {sym}: {exc}", "warn")

            # Session filter
            from engine.utils import session_of
            if C.SESSION_FILTER_ALLOW:
                sess = session_of(datetime.now(timezone.utc))
                if sess not in C.SESSION_FILTER_ALLOW:
                    log_decision(decision_ctx, sym, direction, "blocked_filter",
                               {"reason": f"Sessão {sess} bloqueada"}, filter_blocked=f"session_{sess}")
                    continue

            # Sizing + SL/TP (ATR)
            try:
                from engine.sizing import compute_sizing
                sizing = compute_sizing(
                    symbol=sym,
                    direction=direction,
                    balance=balance,
                    risk_pct=RISK_PER_TRADE_PCT,
                    atr_mult=C.ATR_STOP_MULT,
                    regime=regime_now,
                )
            except Exception as exc:
                log_decision(decision_ctx, sym, direction, "error", {"reason": f"Sizing error: {exc}"})
                continue

            if sizing is None:
                continue

            # RR check
            if sizing.rr < MIN_RR:
                log_decision(decision_ctx, sym, direction, "blocked_filter",
                           {"reason": f"RR {sizing.rr:.2f} < {MIN_RR}"}, filter_blocked="rr")
                continue

            # Risk cap per trade
            hard_cap = min(RISK_OVERRIDE_PCT.get(sym, RISK_PER_TRADE_PCT), C.DAILY_DD_PCT)
            if sizing.risk_pct > hard_cap:
                log_decision(decision_ctx, sym, direction, "blocked_filter",
                           {"reason": f"Risco {sizing.risk_pct:.1f}% > cap {hard_cap}%"}, filter_blocked="risk_cap")
                continue

            # Execute
            if DRY_RUN_MODE:
                log_decision(decision_ctx, sym, direction, "dry_run",
                           {"lot": sizing.lot, "entry": sizing.entry, "sl": sizing.sl, "tp": sizing.tp})
                summary["actions"].append({"step": "dry_run", "symbol": sym, "direction": direction, "lot": sizing.lot})
            else:
                sig_obj = execution.Signal(
                    symbol=sym, direction=direction, lot=sizing.lot,
                    entry=sizing.entry, sl=sizing.sl, tp=sizing.tp
                )
                result = _executor.execute(sig_obj, dry_run=False)
                if result.success:
                    bot_state["trades_opened_total"] = bot_state.get("trades_opened_total", 0) + 1
                    open_symbols.add(sym)
                    summary["actions"].append({"step": "open_trade", "symbol": sym, "ticket": result.order})
                else:
                    log_decision(decision_ctx, sym, direction, "error",
                               {"reason": result.comment})

    # 10. Meta-cognition (LLM consult if needed)
    try:
        if _meta_state.needs_llm_consult:
            rec = consult_llm(_meta_state)
            if rec:
                summary["meta_llm_consulted"] = True
    except Exception as exc:
        _notifier.notify(f"Meta LLM error: {exc}", "warn")

    # 11. Kill switch
    try:
        if health_check_kill_switch(_meta_state):
            _meta_state.risk_multiplier = 1.0
            summary["meta_kill_switch"] = True
    except Exception as exc:
        _notifier.notify(f"Kill switch error: {exc}", "warn")

    # 12. Persist state (atomic)
    bot_state["last_run_utc"] = datetime.now(timezone.utc).isoformat()
    store.save(bot_state)
    try:
        save_meta_state(store.path, _meta_state)
    except Exception as exc:
        _notifier.notify(f"MetaState save error: {exc}", "warn")

    _bridge.shutdown()
    summary["cycle_end"] = datetime.now(timezone.utc).isoformat()
    return summary


def main_loop():
    global _commander, _meta_state, _shutdown

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    # Initialize Commander
    _commander = AutonomousCommander()
    _notifier.notify(f"Wealth_Engine v4 iniciado. Modo={'DRY-RUN' if DRY_RUN_MODE else 'DEMO'}. Poll={POLL_SECONDS}s", "info")

    # Load meta-state
    _meta_state = load_meta_state(store.path)

    cycle = 0
    while not _shutdown:
        cycle += 1
        # Rate limiter: pula se ciclo anterior ainda rodando
        if not ratelimiter.ratelimiter.acquire():
            _notifier.notify("Ciclo anterior ainda em execução — pulando tick", "warn")
            time.sleep(POLL_SECONDS)
            continue
        try:
            summary = run_once(cycle)
            logging_utils.log_cycle_end(cycle, summary)
        except Exception as exc:
            tb = traceback.format_exc()
            logging_utils.log_event("CYCLE_EXCEPTION", {"error": str(exc), "trace": tb})
            _notifier.notify(f"Exceção no ciclo: {exc}", "error")
        finally:
            ratelimiter.ratelimiter.release()
        time.sleep(POLL_SECONDS)

    _notifier.notify("Wealth_Engine encerrado", "info")
    _notifier.shutdown()


if __name__ == "__main__":
    main_loop()