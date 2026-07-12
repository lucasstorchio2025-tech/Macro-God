"""
post_trade_analysis.py — Análise pós-trade automatizada.

Lê o trade_log.jsonl (eventos) e decision_log.jsonl (decisões) e gera:

  1. Relatório de performance por símbolo, regime, sessão
  2. Match de trades fechados com as decisões que os abriram
  3. Análise de erros: qual filtro bloqueou mais, qual filtro salvou mais
  4. Acurácia do sinal: % de acerto por condição de mercado
  5. Recomendações de melhoria

Gera: reports/POST_TRADE.md

Uso:
  python bot/post_trade_analysis.py
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ═════════════════════════════ CONSTANTES ═════════════════════════════
# Data em que o bot v2 (atual) entrou em producao com apenas XAUUSDm.
# Qualquer trade ANTES disso e do cron antigo e deve ser ignorado nas analises.
V2_START_UTC = datetime(2026, 7, 3, tzinfo=timezone.utc)

# ═════════════════════════════ PATHS ═════════════════════════════
BOT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"
LOG_PATH = BOT_DIR / "trade_log.jsonl"
DECISION_LOG_PATH = BOT_DIR / "decision_log.jsonl"
REPORT_PATH = REPORTS_DIR / "POST_TRADE.md"


# ═════════════════════════════ SINC COM MT5 ═════════════════════════════
def sync_trades_from_mt5() -> int:
    """Conecta no MT5 e puxa deals recentes (72h) que ainda nao estao no trade_log.

    Isso resolve o bug onde o improvement cycle roda ANTES do executor detectar
    trades fechados. Agora o proprio post_trade_analysis puxa os dados frescos.

    Retorna quantidade de novos DEAL_FOUND escritos no trade_log.
    """
    try:
        import MetaTrader5 as mt5

        from dotenv import load_dotenv
        load_dotenv(r"C:\Users\lucas\.hermes\.env", override=False)
        load_dotenv(str(PROJECT_ROOT / ".env"), override=False)

        login = os.environ.get("EXNESS_LOGIN")
        password = os.environ.get("EXNESS_PASSWORD")
        server = os.environ.get("EXNESS_SERVER")
        if not login or not password or not server:
            print("[post_trade] MT5 credenciais nao encontradas, pulando sync")
            return 0

        if not mt5.initialize(login=int(login), password=password, server=server, timeout=15000):
            print(f"[post_trade] MT5 nao conectou: {mt5.last_error()}")
            return 0

        ti = mt5.terminal_info()
        if not ti or not ti.connected:
            print("[post_trade] MT5 terminal nao conectado")
            mt5.shutdown()
            return 0

        # Puxa deals das ultimas 72h
        now = datetime.now(timezone.utc)
        deals = mt5.history_deals_get(now - timedelta(hours=72), now)
        if not deals:
            print("[post_trade] MT5: nenhum deal nas ultimas 72h")
            mt5.shutdown()
            return 0

        # Le deals ja logados
        logged = set()
        if LOG_PATH.exists():
            for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
                try:
                    ev = json.loads(line)
                    deal_id = ev.get("payload", {}).get("deal")
                    if deal_id:
                        logged.add(deal_id)
                except Exception:
                    pass

        MAGIC = int(os.environ.get("EXNESS_MAGIC", "999888777"))
        novos = 0
        for d in deals:
            if d.magic != MAGIC:
                continue
            if d.ticket in logged:
                continue
            if d.type not in (0, 1):
                continue

            event = {
                "ts_utc": datetime.now(timezone.utc).isoformat(),
                "type": "DEAL_FOUND",
                "payload": {
                    "deal": d.ticket,
                    "order": d.order,
                    "symbol": d.symbol,
                    "type": d.type,
                    "volume": d.volume,
                    "price": d.price,
                    "profit": d.profit,
                    "comment": d.comment,
                },
            }
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
            novos += 1

        mt5.shutdown()
        if novos:
            print(f"[post_trade] Sincronizados {novos} novos deals do MT5")
        else:
            print("[post_trade] MT5: nenhum deal novo encontrado")
        return novos

    except ImportError:
        print("[post_trade] MetaTrader5 nao instalado, pulando sync")
        return 0
    except Exception as e:
        print(f"[post_trade] Erro ao sincronizar MT5: {type(e).__name__}: {e}")
        return 0


# ═════════════════════════════ LEITURA DOS LOGS ═════════════════════════════
def read_trade_log() -> list[dict]:
    """Lê trade_log.jsonl. Retorna lista de eventos."""
    if not LOG_PATH.exists():
        return []
    try:
        lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
        return [json.loads(l) for l in lines if l.strip()]
    except Exception as e:
        print(f"[post_trade] erro lendo trade_log: {e}")
        return []


def read_decision_log(n_last: int = 5000) -> list[dict]:
    """Lê decision_log.jsonl."""
    if not DECISION_LOG_PATH.exists():
        return []
    try:
        lines = DECISION_LOG_PATH.read_text(encoding="utf-8").splitlines()
        lines = lines[-n_last:]
        return [json.loads(l) for l in lines if l.strip()]
    except Exception as e:
        print(f"[post_trade] erro lendo decision_log: {e}")
        return []


# ═════════════════════════════ MATCH TRADES ↔ DECISIONS ═════════════════════════════
def match_trades_with_decisions(trades: list[dict], decisions: list[dict]) -> list[dict]:
    """Tenta casar cada trade fechado com a decisão que o abriu.

    Retorna lista de dicts com {trade, decision, profit, symbol, direction, ...}
    """
    # Indexa decisões por símbolo + timestamp aproximado
    decision_index: dict[str, list[dict]] = defaultdict(list)
    for d in decisions:
        if d.get("type") != "DECISION":
            continue
        payload = d.get("payload", {})
        if payload.get("result") in ("opened", "dry_run"):
            sym = payload.get("symbol")
            decision_index[sym].append(d)

    matched = []
    for ev in trades:
        ev_type = ev.get("type", "")
        payload = ev.get("payload", {})

        # Eventos de fechamento (DEAL_FOUND com profit != 0, CLOSE_SENT)
        if ev_type == "DEAL_FOUND":
            profit = payload.get("profit", 0)
            if profit == 0:
                continue
            # Filtro V2: ignora trades do cron antigo (antes de 03/07/2026)
            try:
                ev_ts = datetime.fromisoformat(ev.get("ts_utc", "").replace("Z", "+00:00"))
                if ev_ts < V2_START_UTC:
                    continue
            except (ValueError, TypeError):
                continue
            matched.append({
                "type": "closed_trade",
                "symbol": payload.get("symbol"),
                "profit": profit,
                "volume": payload.get("volume"),
                "price": payload.get("price"),
                "ts_utc": ev.get("ts_utc", ""),
                "comment": payload.get("comment", ""),
                "decision": _find_matching_decision(payload.get("symbol", ""),
                                                     payload.get("price", 0),
                                                     profit, decision_index),
            })

        elif ev_type == "DRY_RUN_WOULD_OPEN":
            matched.append({
                "type": "dry_run_signal",
                "symbol": payload.get("symbol"),
                "direction": payload.get("direction"),
                "lot": payload.get("lot"),
                "entry": payload.get("entry"),
                "sl": payload.get("sl"),
                "tp": payload.get("tp"),
                "rr": payload.get("rr"),
                "risk_pct": payload.get("risk_real_pct"),
                "ts_utc": ev.get("ts_utc", ""),
            })

        elif ev_type == "ORDER_SENT":
            matched.append({
                "type": "order_sent",
                "symbol": payload.get("req", {}).get("symbol"),
                "direction": "BUY" if payload.get("req", {}).get("type") == 0 else "SELL",
                "volume": payload.get("req", {}).get("volume"),
                "price": payload.get("price"),
                "retcode": payload.get("result_retcode"),
                "order": payload.get("order"),
                "deal": payload.get("deal"),
                "ts_utc": ev.get("ts_utc", ""),
            })

    return matched


def _find_matching_decision(symbol: str, price: float, profit: float,
                             decision_index: dict) -> Optional[dict]:
    """Encontra a decisão mais recente que abriu trade neste símbolo."""
    decisions = decision_index.get(symbol, [])
    if not decisions:
        return None
    # Pega a mais recente
    return decisions[-1]


# ═════════════════════════════ ANÁLISE POR CATEGORIA ═════════════════════════════
def analyze_decisions(decisions: list[dict]) -> dict:
    """Analisa decisões: resultados, filtros, contexto."""
    total = 0
    by_result = Counter()
    by_filter = Counter()
    by_regime = Counter()
    by_session = Counter()
    by_symbol = Counter()
    by_momentum_strength = Counter()
    momentum_vs_result: dict[str, list[float]] = defaultdict(list)

    for d in decisions:
        if d.get("type") != "DECISION":
            continue
        payload = d.get("payload", {})
        total += 1
        result = payload.get("result", "unknown")
        by_result[result] += 1

        fb = payload.get("filter_blocked")
        if fb:
            by_filter[fb] += 1

        ctx = payload.get("market_context", {})
        regime = ctx.get("regime", "unknown")
        by_regime[regime] += 1

        session = ctx.get("session", "unknown")
        by_session[session] += 1

        sym = payload.get("symbol", "unknown")
        by_symbol[sym] += 1

        reasoning = payload.get("reasoning", {})
        mom_strength = reasoning.get("momentum_strength", "unknown")
        by_momentum_strength[mom_strength] += 1

        mom_pct = reasoning.get("momentum_signal_pct")
        if mom_pct is not None and result in ("opened", "dry_run"):
            momentum_vs_result[mom_strength].append(mom_pct)

    return {
        "total": total,
        "by_result": dict(by_result),
        "by_filter": dict(by_filter),
        "by_regime": dict(by_regime),
        "by_session": dict(by_session),
        "by_symbol": dict(by_symbol),
        "by_momentum_strength": dict(by_momentum_strength),
        "momentum_vs_result": {k: {"count": len(v), "avg_pct": round(sum(v)/len(v), 3) if v else 0}
                                for k, v in momentum_vs_result.items()},
    }


def analyze_closed_trades(matched: list[dict]) -> dict:
    """Analisa trades fechados: P&L por símbolo, direção, win rate."""
    by_symbol_pnl = defaultdict(list)
    by_direction = defaultdict(list)
    total_pnl = 0.0
    wins = 0
    losses = 0
    best_trade: Optional[dict] = None
    worst_trade: Optional[dict] = None

    for m in matched:
        if m.get("type") != "closed_trade":
            continue
        profit = m.get("profit", 0)
        symbol = m.get("symbol", "?")
        total_pnl += profit

        by_symbol_pnl[symbol].append(profit)

        if profit > 0:
            wins += 1
            if best_trade is None or profit > best_trade["profit"]:
                best_trade = m
        elif profit < 0:
            losses += 1
            if worst_trade is None or profit < worst_trade["profit"]:
                worst_trade = m

    stats = {}
    for sym, pnls in by_symbol_pnl.items():
        wins_s = sum(1 for p in pnls if p > 0)
        stats[sym] = {
            "trades": len(pnls),
            "pnl_total": round(sum(pnls), 2),
            "win_rate": round(wins_s / len(pnls) * 100, 1) if pnls else 0,
            "avg_pnl": round(sum(pnls) / len(pnls), 2) if pnls else 0,
            "best": round(max(pnls), 2),
            "worst": round(min(pnls), 2),
        }

    total = wins + losses
    return {
        "total_trades": total,
        "total_pnl": round(total_pnl, 2),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / total * 100, 1) if total else 0,
        "by_symbol": stats,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
    }


def analyze_decision_accuracy(decisions: list[dict], closed_pnls: list[dict]) -> dict:
    """Analisa acurácia das decisões: percentual de acerto por regime, sessão, momento."""
    # Agrupa decisões de abertura por regime
    opened_by_regime = defaultdict(list)
    for d in decisions:
        if d.get("type") != "DECISION":
            continue
        payload = d.get("payload", {})
        if payload.get("result") != "opened":
            continue
        ctx = payload.get("market_context", {})
        regime = ctx.get("regime", "unknown")
        opened_by_regime[regime].append(d)

    # Estatísticas por regime
    regime_stats = {}
    for regime, decs in opened_by_regime.items():
        regime_stats[regime] = {
            "trades_opened": len(decs),
            "symbols": Counter(d.get("payload", {}).get("symbol", "?") for d in decs),
        }

    return {
        "opened_by_regime": regime_stats,
        "total_opened": sum(len(v) for v in opened_by_regime.values()),
    }


# ═════════════════════════════ GERAR RELATÓRIO ═════════════════════════════
def generate_report() -> Path:
    """Gera o relatório POST_TRADE.md."""
    # Passo 0: Sincroniza trades fechados diretamente do MT5
    novos = sync_trades_from_mt5()

    trades = read_trade_log()
    decisions = read_decision_log()

    print(f"[post_trade] {len(trades)} eventos no trade_log ({novos} novos sincronizados do MT5)")
    print(f"[post_trade] {len(decisions)} decisões no decision_log")

    # Análises
    matched = match_trades_with_decisions(trades, decisions)
    closed_analysis = analyze_closed_trades(matched)
    decision_analysis = analyze_decisions(decisions)
    accuracy = analyze_decision_accuracy(decisions, matched)

    # ── Monta relatório ──
    lines = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"# 📊 POST-TRADE ANALYSIS")
    lines.append(f"**Gerado em:** {now}")
    lines.append(f"**Eventos processados:** {len(trades)} | **Decisões analisadas:** {len(decisions)}")
    lines.append("")

    # ── Seção 1: Trades Fechados ──
    lines.append("## 1. Trades Fechados")
    lines.append("")
    ca = closed_analysis
    lines.append(f"- **Total:** {ca['total_trades']} trades | **P&L:** ${ca['total_pnl']:+.2f}")
    lines.append(f"- **Win Rate:** {ca['win_rate']}% ({ca['wins']}W / {ca['losses']}L)")
    if ca['best_trade']:
        bt = ca['best_trade']
        lines.append(f"- **Melhor trade:** {bt.get('symbol','?')} ${bt.get('profit',0):+.2f}")
    if ca['worst_trade']:
        wt = ca['worst_trade']
        lines.append(f"- **Pior trade:** {wt.get('symbol','?')} ${wt.get('profit',0):+.2f}")
    lines.append("")

    # Por símbolo
    if ca['by_symbol']:
        lines.append("### Por Símbolo")
        lines.append("")
        lines.append("| Símbolo | Trades | P&L Total | Win Rate | Média | Melhor | Pior |")
        lines.append("|---------|--------|-----------|----------|-------|--------|------|")
        for sym, stats in sorted(ca['by_symbol'].items()):
            lines.append(f"| {sym} | {stats['trades']} | ${stats['pnl_total']:+.2f} | "
                         f"{stats['win_rate']}% | ${stats['avg_pnl']:+.2f} | "
                         f"${stats['best']:+.2f} | ${stats['worst']:+.2f} |")
        lines.append("")

    # ── Seção 2: Decisões por Resultado ──
    lines.append("## 2. Decisões por Resultado")
    lines.append("")
    da = decision_analysis
    lines.append(f"**Total de decisões:** {da['total']}")
    lines.append("")
    lines.append("| Resultado | Qtd | % |")
    lines.append("|-----------|-----|---|")
    for result, count in sorted(da['by_result'].items(), key=lambda x: -x[1]):
        pct = count / da['total'] * 100 if da['total'] else 0
        lines.append(f"| {result} | {count} | {pct:.1f}% |")
    lines.append("")

    # ── Seção 3: Filtros que Bloquearam ──
    lines.append("## 3. Filtros Que Mais Bloquearam")
    lines.append("")
    if da['by_filter']:
        lines.append("| Filtro | Qtd Bloqueios |")
        lines.append("|--------|--------------|")
        for filtro, count in sorted(da['by_filter'].items(), key=lambda x: -x[1]):
            lines.append(f"| {filtro} | {count} |")
        lines.append("")
    else:
        lines.append("Nenhum bloqueio de filtro registrado.")
        lines.append("")

    # ── Seção 4: Contexto de Mercado ──
    lines.append("## 4. Contexto de Mercado nas Decisões")
    lines.append("")

    # Por regime
    lines.append("### Por Regime")
    lines.append("")
    lines.append("| Regime | Decisões | % |")
    lines.append("|--------|----------|---|")
    for regime, count in sorted(da['by_regime'].items(), key=lambda x: -x[1]):
        pct = count / da['total'] * 100 if da['total'] else 0
        lines.append(f"| {regime} | {count} | {pct:.1f}% |")
    lines.append("")

    # Por sessão
    lines.append("### Por Sessão")
    lines.append("")
    lines.append("| Sessão | Decisões | % |")
    lines.append("|--------|----------|---|")
    for session, count in sorted(da['by_session'].items(), key=lambda x: -x[1]):
        pct = count / da['total'] * 100 if da['total'] else 0
        lines.append(f"| {session} | {count} | {pct:.1f}% |")
    lines.append("")

    # Por símbolo
    lines.append("### Por Símbolo")
    lines.append("")
    lines.append("| Símbolo | Decisões | % |")
    lines.append("|---------|----------|---|")
    for sym, count in sorted(da['by_symbol'].items(), key=lambda x: -x[1]):
        pct = count / da['total'] * 100 if da['total'] else 0
        lines.append(f"| {sym} | {count} | {pct:.1f}% |")
    lines.append("")

    # ── Seção 5: Força do Momentum ──
    lines.append("## 5. Força do Momentum nas Decisões")
    lines.append("")
    lines.append("| Força | Decisões |")
    lines.append("|-------|----------|")
    for strength, count in sorted(da['by_momentum_strength'].items(), key=lambda x: -x[1]):
        lines.append(f"| {strength} | {count} |")
    lines.append("")

    if da['momentum_vs_result']:
        lines.append("### Média do Sinal de Momentum por Decisão (abertas)")
        lines.append("")
        lines.append("| Força | Trades | Média do Sinal % |")
        lines.append("|-------|--------|-----------------|")
        for strength, info in sorted(da['momentum_vs_result'].items()):
            lines.append(f"| {strength} | {info['count']} | {info['avg_pct']:+.3f}% |")
        lines.append("")

    # ── Seção 6: Trades Abertos por Regime ──
    lines.append("## 6. Precisão: Trades Abertos por Condição")
    lines.append("")
    acc = accuracy
    lines.append(f"**Total de trades abertos no período:** {acc['total_opened']}")
    lines.append("")
    lines.append("| Regime | Trades Abertos | Símbolos |")
    lines.append("|--------|----------------|----------|")
    for regime, stats in sorted(acc['opened_by_regime'].items()):
        syms = ", ".join(f"{s}({c})" for s, c in stats['symbols'].most_common())
        lines.append(f"| {regime} | {stats['trades_opened']} | {syms} |")
    lines.append("")

    # ── Seção 7: Recomendações ──
    lines.append("## 7. Recomendações")
    lines.append("")

    reco_lines = []
    # Baseado em win rate
    if ca['total_trades'] >= 5:
        wr = ca['win_rate']
        if wr < 30:
            reco_lines.append("- 🔴 **Win rate abaixo de 30%.** Considere revisar o threshold de entrada do momentum (MOMENTUM_MIN_ABS_R) ou aumentar o RR mínimo.")
        elif wr < 40:
            reco_lines.append("- 🟡 **Win rate médio-baixo.** A estratégia TS-momentum tem win rate histórico de ~42%. Monitorar se a amostra é representativa.")
        else:
            reco_lines.append("- 🟢 **Win rate dentro do esperado** para uma estratégia de momentum com RR 2:1.")

    # Baseado em filtros
    if da['by_filter']:
        top_filters = sorted(da['by_filter'].items(), key=lambda x: -x[1])[:3]
        reco_lines.append(f"- 🔍 **Filtros mais ativos:** {', '.join(f'{f}({c})' for f, c in top_filters)}. "
                          f"Verificar se algum está bloqueando trades lucrativos demais.")

    # Baseado em regime
    if 'crisis' in da['by_regime']:
        reco_lines.append("- ⚠️ **Operando em crise.** O bot reduziu exposição, mas crise exige cautela extra.")

    if not reco_lines:
        reco_lines.append("- ✅ Dados insuficientes para recomendações. Deixe o bot rodar por mais tempo.")

    lines.extend(reco_lines)
    lines.append("")

    lines.append("---")
    lines.append(f"_Relatório gerado automaticamente por post_trade_analysis.py em {now}_")

    # Salva
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"[post_trade] Relatório salvo: {REPORT_PATH}")
    return REPORT_PATH


# ═════════════════════════════ MAIN ═════════════════════════════
def main():
    print("=" * 60)
    print("  WEALTH_ENGINE — POST-TRADE ANALYSIS")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")
    print("=" * 60)
    print()

    report_path = generate_report()

    print()
    print("=" * 60)
    print(f"  RELATÓRIO PRONTO: {report_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
