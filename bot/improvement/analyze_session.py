"""bot.improvement.analyze_session — Análise diária autônoma (P2-A).

Roda via Hermes cron job às 03:00 UTC.
Lê logs do bot (últimas 24h) e propõe 1 ajuste paramétrico.
Não aplica — só entrega proposta no Telegram para aprovação humana.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import Counter, defaultdict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

BOT_DIR = PROJECT_ROOT / "bot"
RUN_DIR = BOT_DIR / "run"

HEARTBEAT_FILE = RUN_DIR / "heartbeat.json"
DECISION_LOG = BOT_DIR / "decision_log.jsonl"
TRADE_LOG = BOT_DIR / "trade_log.jsonl"
BOT_STATE = BOT_DIR / "bot_state.json"
COMMANDER_STATE = RUN_DIR / "commander_state.json"


def _read_jsonl(path: Path, since: datetime) -> list[dict]:
    """Lê linhas JSONL filtradas por timestamp >= since."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
            ts_str = ev.get("ts_utc") or ev.get("payload", {}).get("ts_utc")
            if ts_str:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts >= since:
                    out.append(ev)
        except Exception:
            continue
    return out


def _read_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def analyze() -> dict:
    """Retorna dict com análise completa para o relatório Telegram."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=24)

    # ── 1. Heartbeat health ─────────────────────────────────────────────
    hb = _read_json(HEARTBEAT_FILE)
    hb_age = None
    if hb.get("ts"):
        try:
            hb_ts = datetime.fromisoformat(hb["ts"].replace("Z", "+00:00"))
            hb_age = int((now - hb_ts).total_seconds())
        except Exception:
            pass

    # ── 2. Decisions (últimas 24h) ─────────────────────────────────────
    decisions = _read_jsonl(DECISION_LOG, since)
    cycles = [d for d in decisions if d.get("type") == "CYCLE_END"]
    cycle_blocks = [d for d in decisions if d.get("type") == "DECISION"]

    # Filtros que mais bloquearam
    block_counts = Counter()
    for d in cycle_blocks:
        payload = d.get("payload", {})
        if payload.get("result") == "blocked_filter":
            block_counts[payload.get("filter_blocked", "unknown")] += 1

    # Símbolos/direções mais operados
    trade_counts = Counter()
    for d in cycle_blocks:
        payload = d.get("payload", {})
        if payload.get("result") in ("opened", "dry_run"):
            sym = payload.get("symbol")
            direction = payload.get("direction")
            if sym and direction:
                trade_counts[f"{sym} {direction}"] += 1

    # ── 3. Trades fechados (PnL real) ───────────────────────────────────
    trades = _read_jsonl(TRADE_LOG, since)
    closed = []
    for t in trades:
        if t.get("type") == "DEAL_FOUND":
            p = t.get("payload", {})
            if p.get("profit", 0) != 0:
                closed.append({
                    "symbol": p.get("symbol"),
                    "direction": "BUY" if p.get("type") == 0 else "SELL",
                    "pnl": p.get("profit", 0),
                    "entry": p.get("price"),
                    "exit_reason": "TP" if p.get("profit", 0) > 0 else "SL",
                })

    # 3 piores trades (maior perda)
    worst = sorted(closed, key=lambda x: x["pnl"])[:3]

    # ── 4. Estado atual ─────────────────────────────────────────────────
    state = _read_json(BOT_STATE)
    commander = _read_json(COMMANDER_STATE)

    # ── 5. Proposta de ajuste ───────────────────────────────────────────
    proposal = None
    if block_counts:
        top_block = block_counts.most_common(1)[0]
        filter_name, count = top_block
        # Heurística simples: se session filter bloqueia >50% dos ciclos, sugerir expandir
        if filter_name.startswith("session_") and count > len(cycles) * 0.5:
            proposal = {
                "parameter": "SESSION_FILTER_ALLOW",
                "current": "configurado no engine/config.py",
                "suggested": "adicionar sessão bloqueada",
                "reason": f"Filtro de sessão bloqueou {count}/{len(cycles)} ciclos ({count/len(cycles):.0%}). Considere remover a restrição se a estratégia funciona nessa sessão.",
            }
        elif filter_name == "cooldown" and count > len(cycles) * 0.3:
            proposal = {
                "parameter": "COOLDOWN_BARS",
                "current": "12 (48h)",
                "suggested": "8 (32h) ou 6 (24h)",
                "reason": f"Cooldown bloqueou {count}/{len(cycles)} ciclos. Reduzir pode capturar reentradas válidas sem overtrade.",
            }
        elif filter_name == "rr" and count > len(cycles) * 0.2:
            proposal = {
                "parameter": "MIN_REWARD_RISK",
                "current": "2.0",
                "suggested": "1.8",
                "reason": f"RR mínimo bloqueou {count}/{len(cycles)} ciclos. Reduzir levemente aumenta oportunidades mantendo edge.",
            }

    # Fallback: se não há proposta clara, sugerir baseado em PnL
    if not proposal and closed:
        total_pnl = sum(t["pnl"] for t in closed)
        if total_pnl < 0:
            proposal = {
                "parameter": "RISK_PER_TRADE_PCT",
                "current": "5.0",
                "suggested": "4.0",
                "reason": f"PnL 24h negativo (${total_pnl:.2f}). Reduzir risco por trade preserva capital enquanto valida edge.",
            }
        else:
            proposal = {
                "parameter": "RISK_PER_TRADE_PCT",
                "current": "5.0",
                "suggested": "5.0 (manter)",
                "reason": f"PnL 24h positivo (${total_pnl:.2f}). Manter risk sizing atual.",
            }

    return {
        "timestamp": now.isoformat(),
        "period_hours": 24,
        "health": {
            "heartbeat_age_seconds": hb_age,
            "heartbeat_alive": hb.get("alive", False),
            "executor_pid": hb.get("executor_pid"),
        },
        "summary": {
            "cycles_completed": len(cycles),
            "total_decisions": len(cycle_blocks),
            "trades_closed": len(closed),
            "net_pnl_usd": round(sum(t["pnl"] for t in closed), 2),
            "win_rate": round(sum(1 for t in closed if t["pnl"] > 0) / max(1, len(closed)) * 100, 1),
        },
        "top_blockers": [{"filter": k, "count": v, "pct": round(v / max(1, len(cycles)) * 100, 1)} for k, v in block_counts.most_common(5)],
        "most_traded": [{"symbol_dir": k, "count": v} for k, v in trade_counts.most_common(5)],
        "worst_trades": [
            {"symbol": t["symbol"], "direction": t["direction"], "pnl": round(t["pnl"], 2), "exit": t["exit_reason"]}
            for t in worst
        ],
        "proposal": proposal or {"parameter": "NONE", "reason": "Nenhum ajuste sugerido — performance dentro do esperado."},
        "commander_state": {
            "cycle_count": commander.get("cycle_count", 0),
            "last_decision": commander.get("last_decision"),
            "last_oracle_update": commander.get("last_oracle_update"),
        },
    }


def format_telegram(report: dict) -> str:
    """Formata relatório para Telegram (HTML, <4096 chars)."""
    s = report["summary"]
    h = report["health"]

    lines = [
        f"<b>📊 Wealth Engine — Daily Report</b>",
        f"Período: 24h até {report['timestamp'][:19].replace('T', ' ')} UTC",
        f"",
        f"<b>Saúde do Bot</b>",
        f"  Heartbeat: {'🟢 vivo' if h['heartbeat_alive'] else '🔴 morto'} "
        f"({'%ds atrás' % h['heartbeat_age_seconds'] if h['heartbeat_age_seconds'] else 'N/A'})",
        f"  Executor PID: {h['executor_pid'] or 'N/A'}",
        f"",
        f"<b>Resumo 24h</b>",
        f"  Ciclos: {s['cycles_completed']}",
        f"  Trades fechados: {s['trades_closed']}",
        f"  PnL líquido: ${s['net_pnl_usd']:+.2f}",
        f"  Win rate: {s['win_rate']:.1f}%",
        f"",
        f"<b>Top 5 Blockers</b>",
    ]
    for b in report["top_blockers"]:
        lines.append(f"  {b['filter']}: {b['count']} ({b['pct']:.1f}%)")

    if report["worst_trades"]:
        lines.append(f"")
        lines.append(f"<b>3 Piores Trades</b>")
        for t in report["worst_trades"]:
            lines.append(f"  {t['symbol']} {t['direction']}: ${t['pnl']:+.2f} ({t['exit']})")

    lines.append(f"")
    lines.append(f"<b>Proposta de Ajuste</b>")
    p = report["proposal"]
    lines.append(f"  Parâmetro: <code>{p['parameter']}</code>")
    lines.append(f"  Atual: {p.get('current', 'N/A')}")
    lines.append(f"  Sugerido: {p.get('suggested', 'N/A')}")
    lines.append(f"  Justificativa: {p.get('reason', 'N/A')}")

    lines.append(f"")
    lines.append(f"<i>Não aplica automaticamente. Responda 'aplicar {p['parameter']}' para confirmar.</i>")

    return "\n".join(lines)


def main():
    try:
        report = analyze()
        print(json.dumps(report, indent=2, ensure_ascii=False))
        # Telegram notification via bot.core.notify (import tardio para evitar circular)
        try:
            from bot.core.notify import notifier
            notifier.notify(format_telegram(report), "alert")
        except Exception as exc:
            print(f"[WARN] Telegram notify failed: {exc}", file=sys.stderr)
    except Exception as exc:
        print(f"[ERROR] analyze_session failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()