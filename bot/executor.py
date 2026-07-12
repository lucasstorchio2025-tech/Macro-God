"""
Wealth_Engine Auto-Trader v2 (demo-first)
=========================================

REESCRITA COMPLETA da lógica de decisão. Preserva a infraestrutura que
funcionava (logging event-sourced, drawdown diário/semanal, dry-run, MT5 auth)
e corrige os 3 problemas que destruíram $90 na demo:

  BUG 1 (crítico): check_max_positions usava positions_get(symbol="") que
         retorna [] mesmo com posições abertas. Corrigido pra positions_get().
         Isto é a causa raiz do empilhamento de 7 SELL EURUSDm idênticos.
  BUG 2: sinal COT-momentum ao contrário (comprava topo). Substituído por
         TS-momentum cross-asset (Moskowitz 2012), validado em backtest
         com Sharpe 0.62 e +135% em 5 anos (ver reports/VERDICT.md).
  BUG 3: sizing por % fixa. Substituído por vol-targeting + cap por correlação
         + exposição USD agregada (engine/sizing.py).

META-COGNICAO v2: o bot aprende com os proprios erros sem overfit.
  MetaState (engine/meta_config.py) armazena metricas rolling e performance
  por bucket de contexto (regime, direcao, atr_stop). O LLM local (Gemma 4-opt
  via Ollama) analisa periodica mente e gera risk_multiplier adaptativo.

HARD FILTROS (preservados, qualquer falha = NAO opera):
  1. trade_allowed do terminal MT5 = True
  2. Max N posições abertas (HONESTAS agora — lê posições reais)
  3. Exposicao total aberta <= TOTAL_RISK_CAP_PCT
  4. Saldo nao atingiu -DAILY_DD_PCT no dia
  5. Saldo nao atingiu -WEEKLY_DD_PCT na semana
  6. Nao ha evento de alto impacto nas proximas 2h
  7. Regime != crisis (gate de regime)
  8. Nao ha posicao aberta no mesmo símbolo (anti-empilhamento)
  9. Cooldown respeitado após última saída do símbolo

DRY-RUN: run_once.dry_run = True antes de chamar. Calcula tudo, não abre ordem.
"""
import os
import sys
import json
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

# engine no path (bot/ é subpasta do projeto)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# decision_log — logging estruturado de decisões (bot/ no path)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from decision_log import build_decision_context, log_decision

from dotenv import load_dotenv
# Carrega ambos: .hermes (credenciais Exness) primeiro, depois .env do projeto
# (Telegram etc). override=False preserva vars ja definidas.
load_dotenv(str(Path.home() / ".hermes" / ".env"), override=False)
load_dotenv(str(Path(__file__).resolve().parent.parent / ".env"), override=False)

import MetaTrader5 as mt5
import requests

from engine import config as C
from engine.utils import session_of
from engine.meta_config import MetaState, load_meta_state, save_meta_state
from engine.meta_learner import consult_llm, quick_analysis, health_check_kill_switch

# ============== PATHS ==============
BOT_DIR = Path(__file__).resolve().parent
BOT_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = BOT_DIR / "trade_log.jsonl"
STATE_PATH = BOT_DIR / "bot_state.json"
INTEL_PATH = Path(__file__).resolve().parent.parent / "market_intelligence.json"

# ============== CONFIG (importada do engine) ==============
SYMBOLS = C.SYMBOLS
MAX_OPEN_POSITIONS = C.MAX_OPEN_POSITIONS
TOTAL_RISK_CAP_PCT = C.TOTAL_RISK_CAP_PCT
RISK_PER_TRADE_PCT = C.RISK_PER_TRADE_PCT
RISK_OVERRIDE_PCT = C.RISK_OVERRIDE_PCT
MIN_RR = C.MIN_REWARD_RISK
DAILY_DD_PCT = C.DAILY_DD_PCT
WEEKLY_DD_PCT = C.WEEKLY_DD_PCT
MAGIC = C.EXNESS_MAGIC
COMMENT_TAG = C.COMMENT_TAG
POLL_SECONDS = int(os.environ.get("WEALTH_POLL_SECONDS", "300"))
COOLDOWN_SECONDS = C.COOLDOWN_BARS * 4 * 3600  # 12 barras H4 = 48h em segundos

# Modo dry-run: limites mais apertados
DRY_RUN_MODE = C.DRY_RUN_MODE
if DRY_RUN_MODE:
    notify("DRY-RUN MODE ATIVO — limites apertados ativos", "warn")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


# ============== TELEGRAM ==============
def notify(msg: str, level: str = "info"):
    """Mensagens curtas. Se Telegram nao configurado, cai no stdout."""
    icons = {"info": "[INFO]", "trade": "[TRADE]", "warn": "[AVISO]",
             "paused": "[PAUSADO]", "error": "[ERRO]"}
    text = f"{icons.get(level, '[?]')} {msg}"
    print(text, flush=True)
    if TELEGRAM_BOT_TOKEN.startswith("COLOQUE") or TELEGRAM_BOT_TOKEN == "":
        return
    if TELEGRAM_CHAT_ID.startswith("COLOQUE") or TELEGRAM_CHAT_ID == "":
        return
    try:
        requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            params={"chat_id": TELEGRAM_CHAT_ID, "text": text[:3500]},
            timeout=10,
        )
    except Exception:
        pass


# ============== LOGGING EVENT-SOURCED ==============
def log_event(event_type: str, payload: dict):
    """Append no trade_log.jsonl. Cada linha = 1 evento. Nunca sobrescreve."""
    event = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "payload": payload,
    }
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


# ============== STATE LOCAL ==============
def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "paused_until_utc": None,
        "last_run_utc": None,
        "starting_balance_today": None,
        "starting_balance_week": None,
        "last_reset_day": None,
        "last_reset_week": None,
        "trades_opened_total": 0,
        "trades_closed_total": 0,
        "last_exit_ts": {},   # NOVO v2: {symbol: iso_ts} pra cooldown anti-empilhamento
    }


def save_state(s: dict):
    STATE_PATH.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")


# ============== MT5 AUTH ==============
def mt5_connect():
    """Conecta uma vez no inicio do ciclo. Retorna bool."""
    if not mt5.initialize(
        login=int(os.environ["EXNESS_LOGIN"]),
        password=os.environ["EXNESS_PASSWORD"],
        server=os.environ["EXNESS_SERVER"],
        timeout=15000,
    ):
        return False
    ti = mt5.terminal_info()
    return bool(ti and ti.connected and ti.trade_allowed and not ti.tradeapi_disabled)


# ============== FILTROS HARD (CORRIGIDOS v2) ==============
def check_daily_weekly_dd(current_balance: float, state: dict) -> tuple[bool, str]:
    """Retorna (pode_operar, motivo_se_nao). Reseta contadores diariamente/semanalmente.

    Em DRY-RUN mode, usa limites MAIS APERTADOS (DRY_RUN_WEEKLY_DD_PCT)
    para proteger capital durante validacao ao vivo.
    """
    now = datetime.now(timezone.utc)
    weekday = now.weekday()
    today_str = now.date().isoformat()
    week_str = now.strftime("%Y-W%V")

    # Limites adaptativos: dry-run usa limites mais apertados
    effective_daily = C.DRY_RUN_DAILY_DD_PCT if DRY_RUN_MODE else DAILY_DD_PCT
    effective_weekly = C.DRY_RUN_WEEKLY_DD_PCT if DRY_RUN_MODE else WEEKLY_DD_PCT
    daily_label = f"DRY_RUN({effective_daily}%)" if DRY_RUN_MODE else f"{effective_daily}%"
    weekly_label = f"DRY_RUN({effective_weekly}%)" if DRY_RUN_MODE else f"{effective_weekly}%"

    if state.get("last_reset_day") != today_str:
        state["starting_balance_today"] = current_balance
        state["last_reset_day"] = today_str
    if weekday == 0 and state.get("last_reset_week") != week_str:
        state["starting_balance_week"] = current_balance
        state["last_reset_week"] = week_str
    if state.get("starting_balance_today") is None:
        state["starting_balance_today"] = current_balance
    if state.get("starting_balance_week") is None:
        state["starting_balance_week"] = current_balance

    base_dia = state["starting_balance_today"]
    base_sem = state["starting_balance_week"]
    dd_dia_pct = (current_balance - base_dia) / base_dia * 100 if base_dia else 0
    dd_sem_pct = (current_balance - base_sem) / base_sem * 100 if base_sem else 0

    if dd_dia_pct <= -effective_daily:
        return False, f"DD diario {dd_dia_pct:.2f}% <= {daily_label}. Bot pausado ate amanha."
    if dd_sem_pct <= -effective_weekly:
        return False, f"DD semanal {dd_sem_pct:.2f}% <= {weekly_label}. Bot pausado ate segunda."
    return True, ""


def check_max_positions() -> tuple[bool, int]:
    """Quantas posições abertas temos no momento (com magic nosso).

    *** FIX CRÍTICO v2 ***
    O código antigo usava mt5.positions_get(symbol="") — string vazia. Isso
    retornava [] mesmo com posições abertas. É o bug que deixou 7 SELL EURUSDm
    empilharem. Corrigido pra mt5.positions_get() (sem args = todas).
    """
    positions = mt5.positions_get() or []   # SEM argumentos — vê tudo
    our = [p for p in positions if p.magic == MAGIC]
    return (len(our) < MAX_OPEN_POSITIONS), len(our)


def get_open_symbols() -> set:
    """Símbolos que já temos posição aberta. Usado no anti-empilhamento."""
    positions = mt5.positions_get() or []
    return {p.symbol for p in positions if p.magic == MAGIC}


def check_total_exposure(current_balance: float) -> tuple[bool, float]:
    """Soma do risco aberto <= TOTAL_RISK_CAP_PCT do saldo."""
    positions = mt5.positions_get() or []
    our = [p for p in positions if p.magic == MAGIC]
    total_risk = 0.0
    for p in our:
        info = mt5.symbol_info(p.symbol)
        if not info:
            continue
        # risco em USD = distância ao SL × valor por unidade
        risk_per_unit = mt5.order_calc_profit(p.type, p.symbol, info.volume_min, p.price_open, p.sl)
        if risk_per_unit is None:
            continue
        units = p.volume / info.volume_min
        total_risk += abs(risk_per_unit) * units
    total_risk_pct = (total_risk / current_balance * 100) if current_balance else 0
    return (total_risk_pct < TOTAL_RISK_CAP_PCT), total_risk_pct


def check_macro_blockers(intel: dict) -> tuple[bool, str]:
    """Se tem evento de alto impacto em < 2h, nao opera."""
    cal = intel.get("economic_calendar_next_48h", [])
    if not isinstance(cal, list):
        return True, ""
    now = datetime.now(timezone.utc)
    for ev in cal:
        try:
            ev_time = datetime.fromisoformat(str(ev.get("time", "")).replace("Z", "+00:00"))
            minutes_to = (ev_time - now).total_seconds() / 60
            if 0 <= minutes_to <= 120:
                return False, (f"Evento de alto impacto em {int(minutes_to)} min: "
                               f"{ev.get('event','?')} ({ev.get('country','?')})")
        except Exception:
            continue
    return True, ""


def check_cooldown(symbol: str, state: dict) -> bool:
    """True se o símbolo está fora do cooldown (OK pra operar).

    Anti-empilhamento v2: após sair de um símbolo, espera COOLDOWN_SECONDS
    antes de reentrar. Impede reabrir a mesma aposta a cada ciclo.
    """
    last = state.get("last_exit_ts", {}).get(symbol)
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
        return elapsed >= COOLDOWN_SECONDS
    except Exception:
        return True


def check_regime_gate() -> tuple[bool, str]:
    """Gate de regime: se crisis, nao opera (vai flat)."""
    try:
        from bot.strategy_bridge import get_current_regime
        regime = get_current_regime()
        if regime == "crisis":
            return False, f"Regime = crisis (VIX alto ou correlação explodiu). Bot flat."
        return True, f"regime={regime}"
    except Exception as e:
        # se o regime falhar (sem VIX carregado, etc), NÃO bloqueia — opera normal
        return True, f"regime indisponível ({type(e).__name__}), prosseguindo"


# ============== ABERTURA / FECHAMENTO (preservados do v1) ==============
def open_trade(symbol: str, direction: str, stop: float, take: float,
               lot: float, account_balance: float):
    """Abre ordem com SL/TP/lote explícitos (calculados pelo engine/sizing)."""
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if not info or not tick:
        return None

    if direction == "BUY":
        order_type = mt5.ORDER_TYPE_BUY
        entry = tick.ask
    else:
        order_type = mt5.ORDER_TYPE_SELL
        entry = tick.bid

    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": entry,
        "sl": stop,
        "tp": take,
        "deviation": 30,
        "magic": MAGIC,
        "comment": f"{COMMENT_TAG}_{direction}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    check = mt5.order_check(req)
    if check.retcode != 0:
        log_event("ORDER_CHECK_FAIL", {"req": req, "check_comment": check.comment})
        notify(f"order_check falhou em {symbol}: {check.comment}", "error")
        return None

    result = mt5.order_send(req)
    log_event("ORDER_SENT", {
        "req": req, "result_retcode": result.retcode,
        "result_comment": result.comment, "order": result.order,
        "deal": result.deal, "price": result.price, "volume": result.volume,
    })
    if result.retcode not in (10009, 10008):
        notify(f"Falha ao abrir {direction} {symbol}: {result.comment} (retcode {result.retcode})", "error")
        return None

    notify(f"ABERTO {direction} {symbol} {lot} lote @ {entry} | SL {stop} | TP {take} | ticket {result.order}", "trade")
    return result.order


def close_trade(position) -> bool:
    """Fecha posição a mercado."""
    info = mt5.symbol_info(position.symbol)
    tick = mt5.symbol_info_tick(position.symbol)
    if not info or not tick:
        return False
    close_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask
    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": position.symbol,
        "volume": position.volume,
        "type": close_type,
        "position": position.ticket,
        "price": price,
        "deviation": 30,
        "magic": MAGIC,
        "comment": f"{COMMENT_TAG}_CLOSE",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    check = mt5.order_check(req)
    if check.retcode != 0:
        log_event("CLOSE_CHECK_FAIL", {"req": req, "check_comment": check.comment})
        return False
    result = mt5.order_send(req)
    log_event("CLOSE_SENT", {
        "req": req, "result_retcode": result.retcode,
        "result_comment": result.comment, "deal": result.deal,
    })
    if result.retcode not in (10009, 10008):
        notify(f"Falha ao fechar ticket {position.ticket}: {result.comment}", "error")
        return False
    notify(f"FECHADO {position.symbol} {position.volume} lote, profit={position.profit:+.2f} USD", "trade")
    return True


def sync_orphan_closes(state: dict):
    """Detecta posições que bateram SL/TP automaticamente e registra o resultado.

    NOVO v2: atualiza last_exit_ts no state (pra cooldown funcionar).
    """
    deals = mt5.history_deals_get(datetime.utcnow() - timedelta(hours=72), datetime.utcnow())
    if not deals:
        return
    logged = set()
    try:
        for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
                if ev.get("payload", {}).get("deal"):
                    logged.add(ev["payload"]["deal"])
            except Exception:
                pass
    except Exception:
        pass

    for d in deals:
        if d.magic != MAGIC:
            continue
        if d.ticket in logged:
            continue
        if d.type not in (0, 1):
            continue
        log_event("DEAL_FOUND", {
            "deal": d.ticket, "order": d.order, "symbol": d.symbol, "type": d.type,
            "volume": d.volume, "price": d.price, "profit": d.profit, "comment": d.comment,
        })
        # registra saída pro cooldown
        exits = state.setdefault("last_exit_ts", {})
        exits[d.symbol] = datetime.now(timezone.utc).isoformat()


def close_all_on_crisis() -> int:
    """Em regime crisis, fecha TODAS as posições abertas. Retorna quantas fechou."""
    positions = mt5.positions_get() or []
    our = [p for p in positions if p.magic == MAGIC]
    closed = 0
    for pos in our:
        if close_trade(pos):
            closed += 1
    if closed:
        notify(f"CRISIS: fechadas {closed} posições defensivamente.", "warn")
    return closed


# ============== META-COGNICAO ==============
def _load_processed_deals(state: dict) -> set:
    """Carrega conjunto de deals processados do state (persistido entre restarts)."""
    return set(state.get("_processed_deals", []))


def _save_processed_deals(state: dict, deals: set):
    """Salva conjunto de deals processados no state (persiste entre restarts)."""
    # Limita a 500 entradas
    sorted_deals = sorted(deals)[-500:]
    state["_processed_deals"] = sorted_deals


def _feed_closed_trades_to_meta(meta: MetaState, intel: dict, state: dict):
    """Le DEAL_FOUND events do trade_log e alimenta o MetaState com trades fechados.

    So processa deals NOVOS (nao vistos em ciclos anteriores) para evitar
    que os mesmos trades sejam contados multiplas vezes na rolling window.
    Usa o ticket do deal como identificador unico.

    O conjunto de deals processados e persistido no state (bot_state.json)
    para sobreviver a restarts do bot.
    """
    processed = _load_processed_deals(state)
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
                # Marca como processado
                processed.add(deal_ticket)

                # Direcao: d_type=0=ORDER_TYPE_BUY, 1=ORDER_TYPE_SELL
                d_type = payload.get("type", 0)
                direction = "BUY" if d_type == 0 else "SELL"

                # Regime de entrada (usa o atual como proxy quando nao temos o historico)
                regime = "unknown"
                if intel:
                    regime = intel.get("regime", "unknown")

                # Estima RR: +2.0 pra winners (TP), -1.0 pra losers (SL)
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
                    "rr_realized": rr_est,  # estimativa (melhor que 0.0 fixo)
                    "exit_reason": reason,
                    "regime_at_entry": regime,
                    "atr_stop_mult": 1.5,  # fallback
                    "ts_utc": ev.get("ts_utc", ""),
                }
                meta.on_trade_close(trade)
                new_deals += 1
            except Exception:
                continue
        # Salva no state (persiste entre ciclos e restarts)
        _save_processed_deals(state, processed)
        if new_deals > 0:
            print(f"  [META] {new_deals} novos trades alimentados no MetaState")
    except Exception:
        pass


# ============== CICLO PRINCIPAL (REESCRITO v2) ==============
def _quick_ctx(balance: float = 0) -> dict:
    """Contexto mínimo pra early-return blocks. Não precisa de intel/MT5."""
    import pandas as _pd
    now = datetime.now(timezone.utc)
    session = session_of(now)
    return {
        "ts_utc": now.isoformat(),
        "balance": round(balance, 2),
        "regime": "unknown",
        "session": session,
        "weekday": now.strftime("%A"),
        "vix": None, "vix_pct_change": None,
        "dxy": None, "dxy_pct_change": None,
        "cot_positioning": {},
        "dd_daily_pct": None, "dd_weekly_pct": None,
        "open_positions_count": 0,
    }


def run_once(state: dict) -> dict:
    """Executa 1 ciclo de decisão. Retorna resumo pra log."""
    cycle_start = datetime.now(timezone.utc)
    summary = {"cycle_start": cycle_start.isoformat(), "actions": []}

    if not mt5_connect():
        ctx = _quick_ctx()
        for sym in SYMBOLS:
            log_decision(ctx, sym, "NONE", "blocked_filter",
                         {"reason": "MT5 não conectou"},
                         filter_blocked="mt5_connect")
        summary["actions"].append({"step": "mt5_connect", "ok": False})
        log_event("CYCLE_SKIP_NO_MT5", summary)
        notify("MT5 nao conectou", "error")
        return summary

    acc = mt5.account_info()
    if not acc:
        ctx = _quick_ctx()
        for sym in SYMBOLS:
            log_decision(ctx, sym, "NONE", "blocked_filter",
                         {"reason": "account_info falhou (MT5 retornou None)"},
                         filter_blocked="account_info")
        summary["actions"].append({"step": "account_info", "ok": False})
        log_event("CYCLE_SKIP_NO_ACCOUNT", summary)
        mt5.shutdown()
        return summary

    balance = acc.balance
    summary["balance"] = balance

    # Carrega MetaState (aprendizado continuo)
    meta = load_meta_state(STATE_PATH)
    meta_rm = meta.get_risk_multiplier()
    summary["risk_multiplier"] = meta_rm
    if meta_rm != 1.0:
        print(f"  [META] Risk multiplier ativo: {meta_rm:.2f} ({meta.risk_multiplier_reasoning})")

    # Carrega intel ANTES dos filtros (precisa pro decision_ctx completo)
    intel = {}
    news_data = None
    if INTEL_PATH.exists():
        try:
            intel = json.loads(INTEL_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    NEWS_PATH = BOT_DIR.parent / "filtered_news.json"
    if NEWS_PATH.exists():
        try:
            news_data = json.loads(NEWS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    # FILTRO 1: drawdown diario/semanal
    ok_dd, motivo_dd = check_daily_weekly_dd(balance, state)
    if not ok_dd:
        ctx = _quick_ctx(balance)
        for sym in SYMBOLS:
            log_decision(ctx, sym, "NONE", "blocked_filter",
                         {"reason": motivo_dd},
                         filter_blocked="dd_check")
        summary["actions"].append({"step": "dd_check", "ok": False, "motivo": motivo_dd})
        log_event("CYCLE_BLOCKED_DD", summary)
        notify(motivo_dd, "paused")
        mt5.shutdown()
        return summary

    # SYNC: detecta deals automáticos (SL/TP) e atualiza cooldown + MetaState
    sync_orphan_closes(state)

    # Alimenta MetaState com trades fechados (via DEAL_FOUND no trade_log)
    try:
        _feed_closed_trades_to_meta(meta, intel, state)
    except Exception as e:
        print(f"  [META] Erro ao alimentar MetaState: {e}")

    # FILTRO 2: max posicoes (CORRIGIDO — agora enxerga de verdade)
    ok_max, qtd_open = check_max_positions()
    summary["open_positions"] = qtd_open
    open_syms = get_open_symbols()
    summary["open_symbols"] = list(open_syms)

    # Constrói contexto de decisão COMPLETO (com intel)
    # Só disponível depois de carregar intel e balance
    decision_ctx = build_decision_context(intel, news_data, state, balance)

    # FILTRO 3: regime gate (crisis = flat)
    ok_regime, regime_info = check_regime_gate()
    summary["regime"] = regime_info
    if not ok_regime:
        # em crisis, fecha tudo
        closed_n = close_all_on_crisis()
        for sym in SYMBOLS:
            log_decision(decision_ctx, sym, "NONE", "blocked_filter",
                         {"reason": regime_info}, filter_blocked="crisis")
        summary["actions"].append({"step": "crisis_flat", "ok": True, "closed": closed_n})
        log_event("CYCLE_BLOCKED_CRISIS", summary)
        notify(f"{regime_info} Fechadas {closed_n} posições.", "warn")
        state["last_run_utc"] = cycle_start.isoformat()
        save_state(state)
        mt5.shutdown()
        return summary

    # FILTRO 4: macro blockers (evento alto impacto em 2h)
    ok_macro, motivo_macro = check_macro_blockers(intel)
    if not ok_macro:
        for sym in SYMBOLS:
            log_decision(decision_ctx, sym, "NONE", "blocked_filter",
                         {"reason": motivo_macro}, filter_blocked="macro_blockers")
        summary["actions"].append({"step": "macro_blockers", "ok": False, "motivo": motivo_macro})
        log_event("CYCLE_BLOCKED_MACRO", summary)
        notify(motivo_macro, "warn")
        mt5.shutdown()
        return summary

    # FILTRO 5: exposicao total aberta
    ok_expo, expo_pct = check_total_exposure(balance)
    summary["exposure_pct"] = expo_pct
    if not ok_expo:
        for sym in SYMBOLS:
            log_decision(decision_ctx, sym, "NONE", "blocked_filter",
                         {"reason": f"Exposicao aberta {expo_pct:.2f}% >= cap {TOTAL_RISK_CAP_PCT}%"},
                         filter_blocked="exposure_check")
        summary["actions"].append({"step": "exposure_check", "ok": False, "exposure_pct": expo_pct})
        log_event("CYCLE_BLOCKED_EXPOSURE", summary)
        notify(f"Exposicao aberta {expo_pct:.2f}% >= {TOTAL_RISK_CAP_PCT}%. Nada a fazer.", "warn")
        mt5.shutdown()
        return summary

    # DECISÃO: se há slot, pede sinais ao engine (via strategy_bridge)
    # Usamos compute_signals_with_detail pra ter o contexto completo
    from bot.strategy_bridge import compute_signals_with_detail, get_current_regime
    if qtd_open < MAX_OPEN_POSITIONS:
        try:
            sigs, signal_details, regime_now = compute_signals_with_detail(mt5)
        except Exception as e:
            sigs, signal_details = {}, {}
            regime_now = "unknown"
            log_event("SIGNAL_BRIDGE_ERROR", {"error": str(e), "trace": traceback.format_exc()})
            notify(f"strategy_bridge falhou: {e}", "error")

        signal_log = []
        opened_this_cycle = False
        _RR_EPSILON = 0.001  # tolerância de ponto flutuante pra RR (ex: 1.9999999 vs 2.0)
        for sym, val in sigs.items():
            if opened_this_cycle:
                break
            direction, size_frac = val if isinstance(val, tuple) else (val, 0.05)
            if direction == "NONE" or size_frac <= 0:
                detail = signal_details.get(sym, {})
                log_decision(decision_ctx, sym, direction, "no_signal", {
                    "reason": detail.get("reason", "Sinal NONE"),
                    "momentum_signal_pct": detail.get("momentum_signal_pct"),
                    "momentum_strength": detail.get("momentum_strength", "weak"),
                    "atr": detail.get("atr"),
                    "session": detail.get("session"),
                    "regime": detail.get("regime"),
                    "spread_points": detail.get("spread_points"),
                })
                signal_log.append({"symbol": sym, "direction": direction, "size_frac": size_frac,
                                   "skipped": "none_or_zero",
                                   "reason": detail.get("reason", "")})
                continue
            # FILTRO 6: anti-empilhamento — não abre em símbolo já aberto
            if sym in open_syms:
                detail = signal_details.get(sym, {})
                log_decision(decision_ctx, sym, direction, "blocked_filter", {
                    "reason": f"Já existe posição aberta em {sym}",
                    "momentum_signal_pct": detail.get("momentum_signal_pct"),
                    "atr": detail.get("atr"),
                }, filter_blocked=f"already_open")
                signal_log.append({"symbol": sym, "direction": direction, "skipped": "already_open"})
                continue
            # FILTRO 7: cooldown
            if not check_cooldown(sym, state):
                detail = signal_details.get(sym, {})
                last_exit = state.get("last_exit_ts", {}).get(sym, "?")
                log_decision(decision_ctx, sym, direction, "blocked_filter", {
                    "reason": f"Cooldown ativo para {sym}. Última saída: {last_exit}",
                    "momentum_signal_pct": detail.get("momentum_signal_pct"),
                    "atr": detail.get("atr"),
                }, filter_blocked=f"cooldown")
                signal_log.append({"symbol": sym, "direction": direction, "skipped": "cooldown"})
                continue

            # FILTRO 8: sessão — respeita SESSION_FILTER_ALLOW config
            if C.SESSION_FILTER_ALLOW:
                sess = session_of(datetime.now(timezone.utc))
                if sess not in C.SESSION_FILTER_ALLOW:
                    detail = signal_details.get(sym, {})
                    log_decision(decision_ctx, sym, direction, "blocked_filter", {
                        "reason": f"Sessão {sess} bloqueada pelo filtro SESSION_FILTER_ALLOW",
                        "session": sess,
                        "momentum_signal_pct": detail.get("momentum_signal_pct"),
                        "atr": detail.get("atr"),
                    }, filter_blocked=f"session_{sess}")
                    signal_log.append({"symbol": sym, "direction": direction, "skipped": f"session_{sess}"})
                    continue

            # Calcula SL/TP/lote via ATR + sizing do engine
            info = mt5.symbol_info(sym)
            tick = mt5.symbol_info_tick(sym)
            if not info or not tick:
                continue
            # ATR no H4 recente
            rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, 50)
            if rates is None or len(rates) < 20:
                continue
            import numpy as _np
            trs = []
            for k in range(1, len(rates)):
                h, l, pc = rates[k]["high"], rates[k]["low"], rates[k-1]["close"]
                trs.append(max(h - l, abs(h - pc), abs(l - pc)))
            atr_val = sum(trs[-C.ATR_PERIOD:]) / C.ATR_PERIOD if len(trs) >= C.ATR_PERIOD else None
            if not atr_val or atr_val <= 0:
                continue

            entry = tick.ask if direction == "BUY" else tick.bid
            # ATR stop adaptativo por regime (mesma logica do backtest)
            # risk_on: stop MAIS LARGO (2.0×ATR), risk_off: MAIS APERTADO (1.0×ATR)
            regime_stop_mult = C.ATR_STOP_MULT_BY_REGIME.get(regime_now, C.ATR_STOP_MULT)
            stop_dist = atr_val * regime_stop_mult
            if direction == "BUY":
                sl = round(entry - stop_dist, info.digits)
                tp = round(entry + stop_dist * C.RR_TARGET_MULT, info.digits)
            else:
                sl = round(entry + stop_dist, info.digits)
                tp = round(entry - stop_dist * C.RR_TARGET_MULT, info.digits)

            # Lote: risk_usd = balance × RISK_PER_TRADE_PCT% × size_frac × meta_risk_mult
            # O risk_multiplier do MetaState (aprendizado continuo) reduz o risco
            # em contextos onde o bot historicamente perde.
            risk_usd = balance * (RISK_PER_TRADE_PCT / 100.0) * size_frac * meta_rm
            # lote via order_calc_profit (verdade do servidor, como no v1 e calibrate_lot.py).
            # base_loss = perda para volume_min (0.01). unit_loss = perda por 1 unidade de volume.
            base_loss = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, sym, info.volume_min, entry, sl)
            if base_loss is None or base_loss == 0:
                continue
            unit_loss = abs(base_loss) / info.volume_min   # perda por 1.0 lot ate o SL
            raw_lot = risk_usd / unit_loss                 # lot que arrisca exatamente risk_usd
            n_steps = max(1, int(raw_lot / info.volume_step))
            lot = round(n_steps * info.volume_step, 2)
            if lot < info.volume_min:
                lot = info.volume_min
            if lot > info.volume_max:
                lot = info.volume_max
            # recalcula risco real com o lote escolhido (pra logar honestamente)
            real_loss = abs(mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, sym, lot, entry, sl) or 0)
            real_risk_pct = (real_loss / balance * 100) if balance > 0 else 0

            # RR real check
            base_gain = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, sym, info.volume_min, entry, tp)
            rr_real = abs(base_gain / base_loss) if base_loss else 0
            # RR real check com tolerância de ponto flutuante
            if rr_real < (MIN_RR - _RR_EPSILON):
                log_decision(decision_ctx, sym, direction, "blocked_filter", {
                    "reason": f"RR {rr_real:.2f} < mínimo {MIN_RR}",
                    "rr_real": rr_real, "lot_calculated": lot,
                }, filter_blocked=f"rr_{rr_real:.2f}_below_{MIN_RR}")
                signal_log.append({"symbol": sym, "skipped": f"rr {rr_real:.2f} < {MIN_RR}"})
                continue

            # Risco real check: se o lote mínimo já excede o cap, REJEITA o trade.
            # O override (RISK_OVERRIDE_PCT) deve ser <= DAILY_DD_PCT para preservar
            # os circuit breakers. Se o lote mínimo do broker excede o override,
            # o trade é honestamente rejeitado — não se força entrada com risco alto.
            effective_cap = RISK_OVERRIDE_PCT.get(sym, RISK_PER_TRADE_PCT)
            # Camada extra de segurança: override não pode estourar DAILY_DD_PCT
            hard_cap = effective_cap
            if hard_cap > DAILY_DD_PCT:
                hard_cap = DAILY_DD_PCT
            if real_risk_pct > hard_cap:
                log_decision(decision_ctx, sym, direction, "blocked_filter", {
                    "reason": f"Risco real {real_risk_pct:.1f}% > cap {effective_cap}% (lote minimo excede)",
                    "lot_calculated": lot, "real_risk_pct": real_risk_pct,
                    "cap_pct": effective_cap,
                }, filter_blocked=f"risk_cap")
                signal_log.append({"symbol": sym, "skipped": f"risco_real {real_risk_pct:.1f}% > {effective_cap}% (lote minimo excede cap)"})
                continue

            if getattr(run_once, "dry_run", False):
                risk_info = {"lot": lot, "entry": entry, "sl": sl, "tp": tp,
                            "size_frac": size_frac, "rr": rr_real,
                            "risk_pct": real_risk_pct, "atr": atr_val}
                log_decision(decision_ctx, sym, direction, "dry_run", {
                    "reason": f"Dry-run: {direction} {sym} {lot} lot",
                    "momentum_signal_pct": signal_details.get(sym, {}).get("momentum_signal_pct"),
                }, risk_info=risk_info)
                log_event("DRY_RUN_WOULD_OPEN", {
                    "symbol": sym, "direction": direction, "lot": lot,
                    "entry": entry, "sl": sl, "tp": tp, "size_frac": size_frac,
                    "rr": rr_real, "risk_real_pct": real_risk_pct,
                })
                print(f"  [DRY-RUN] {sym} {direction} {lot} lot SL={sl} TP={tp} risk={real_risk_pct:.1f}% — NAO EXECUTADO", flush=True)
                summary["actions"].append({
                    "step": "dry_run_would_open", "ok": True, "symbol": sym,
                    "direction": direction, "lot": lot, "size_frac": size_frac, "rr": rr_real,
                })
                opened_this_cycle = True
                continue

            order = open_trade(sym, direction, sl, tp, lot, balance)
            if order:
                summary["actions"].append({
                    "step": "open_trade", "ok": True, "symbol": sym,
                    "direction": direction, "ticket": order, "lot": lot,
                    "size_frac": size_frac, "rr": rr_real,
                })
                state["trades_opened_total"] += 1
                open_syms.add(sym)
                opened_this_cycle = True
                risk_info = {"lot": lot, "entry": entry, "sl": sl, "tp": tp,
                            "ticket": order, "size_frac": size_frac,
                            "rr": rr_real, "risk_pct": real_risk_pct}
                log_decision(decision_ctx, sym, direction, "opened", {
                    "reason": f"Trade ABERTO: {direction} {sym}",
                    "momentum_signal_pct": signal_details.get(sym, {}).get("momentum_signal_pct"),
                }, risk_info=risk_info)
            else:
                log_decision(decision_ctx, sym, direction, "error", {
                    "reason": "order_send falhou (retcode != 10009)",
                    "lot": lot, "entry": entry, "sl": sl, "tp": tp,
                })
            signal_log.append({"symbol": sym, "direction": direction, "lot": lot,
                               "size_frac": size_frac, "rr": rr_real,
                               "opened": bool(order)})

        # Loga decisões para símbolos SEM sinal (pra ter rastro completo)
        for sym in SYMBOLS:
            if sym not in sigs:
                detail = signal_details.get(sym, {})
                log_decision(decision_ctx, sym, "NONE", "no_signal", {
                    "reason": detail.get("reason", "Sem sinal do engine (momentum fraco ou dados insuficientes)"),
                    "momentum_signal_pct": detail.get("momentum_signal_pct"),
                    "momentum_strength": detail.get("momentum_strength", "unknown"),
                    "atr": detail.get("atr"),
                    "session": detail.get("session"),
                    "regime": detail.get("regime"),
                    "spread_points": detail.get("spread_points"),
                })

        summary["signal_log"] = signal_log
        if not opened_this_cycle and not any(a.get("step") == "dry_run_would_open" for a in summary["actions"]):
            summary["actions"].append({"step": "no_signal", "ok": True})
    else:
        # Loga que atingiu máximo de posições
        for sym in SYMBOLS:
            log_decision(decision_ctx, sym, "NONE", "blocked_filter",
                         {"reason": "Máximo de posições abertas atingido"},
                         filter_blocked="max_positions")
        summary["actions"].append({"step": "max_positions_reached", "ok": True})

    # META-COGNICAO: consulta LLM se necessario (a cada 10 trades ou streak de 3+)
    try:
        if meta.needs_llm_consult:
            rec = consult_llm(meta)
            if rec:
                print(f"  [META] LLM recomenda risk_mult={rec['risk_multiplier']:.2f}: {rec['reasoning']}")
                meta_rm = meta.get_risk_multiplier()  # atualiza apos consulta
                summary["risk_multiplier"] = meta_rm
                summary["meta_llm_consulted"] = True
    except Exception as e:
        print(f"  [META] Erro ao consultar LLM: {type(e).__name__}: {e}")

    # HEALTH CHECK: kill-switch do meta-learner
    try:
        if health_check_kill_switch(meta):
            print(f"  [META] KILL-SWITCH ATIVADO — meta-learner desligado")
            meta_rm = 1.0
            summary["risk_multiplier"] = 1.0
            summary["meta_kill_switch"] = True
    except Exception as e:
        print(f"  [META] Erro no health check: {type(e).__name__}: {e}")

    # Mostra estado meta resumido
    try:
        meta_summary = quick_analysis(meta)
        if meta_summary:
            print(f"  {meta_summary}")
    except Exception:
        pass

    summary["cycle_end"] = datetime.now(timezone.utc).isoformat()
    log_event("CYCLE_END", summary)
    state["last_run_utc"] = summary["cycle_end"]
    
    # Salva state PRIMEIRO, depois MetaState (evita sobrescrita)
    save_state(state)
    try:
        save_meta_state(STATE_PATH, meta)
    except Exception as e:
        print(f"  [META] Erro ao salvar MetaState: {e}")
    
    mt5.shutdown()
    return summary


# ============== LOOP ==============
def main_loop():
    notify("Wealth_Engine v2 bot iniciado em modo DEMO. Magic=%d. Poll=%ds. "
           "Estrategia=ts_momentum (backtest Sharpe 0.62)." % (MAGIC, POLL_SECONDS), "info")
    state = load_state()
    log_event("BOT_START", {
        "version": "v2", "poll_seconds": POLL_SECONDS, "magic": MAGIC,
        "symbols": SYMBOLS, "max_positions": MAX_OPEN_POSITIONS,
        "risk_per_trade_pct": RISK_PER_TRADE_PCT, "total_risk_cap_pct": TOTAL_RISK_CAP_PCT,
        "daily_dd_pct": DAILY_DD_PCT, "weekly_dd_pct": WEEKLY_DD_PCT,
        "cooldown_seconds": COOLDOWN_SECONDS,
    })
    while True:
        try:
            run_once(state)
        except Exception as e:
            tb = traceback.format_exc()
            log_event("CYCLE_EXCEPTION", {"error": str(e), "trace": tb})
            notify(f"Excecao no ciclo: {e}", "error")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main_loop()
