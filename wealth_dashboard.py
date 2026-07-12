"""
wealth_dashboard.py — Painel Mestre Unificado
==============================================
Unifica: bot_dashboard.py + intelligence_dashboard.py + dashboard.py

TUDO num lugar só:
  ✅ Status do bot (rodando/parado, último ciclo)
  ✅ Regime de mercado + VIX/DXY + Sessão atual
  ✅ Cooldown dos símbolos (quanto tempo falta)
  ✅ Veredito de mercado (conclusão + drivers)
  ✅ Drivers: o que está movendo o mercado agora
  ✅ Direção por ativo (bullish/bearish/neutral)
  ✅ Pipeline de decisão (o que BLOQUEIA as ordens)
  ✅ Timeline de decisões (últimas 50)
  ✅ Trades recentes e eventos
  ✅ Notícias + Calendário econômico + COT + Preços MT5
  ✅ Configuração ativa

Uso:
  streamlit run wealth_dashboard.py --server.address=0.0.0.0 --server.port=8501

Acesso:
  http://localhost:8501         (neste PC)
  http://192.168.X.X:8501       (rede local — celular, tablet, outro PC)
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter, defaultdict

import streamlit as st
import pandas as pd

# ── Paths ──
PROJECT_ROOT = Path(__file__).resolve().parent
BOT_DIR = PROJECT_ROOT / "bot"
STATE_PATH = BOT_DIR / "bot_state.json"
DECISION_LOG_PATH = BOT_DIR / "decision_log.jsonl"
TRADE_LOG_PATH = BOT_DIR / "trade_log.jsonl"
INTEL_PATH = PROJECT_ROOT / "market_intelligence.json"
NEWS_PATH = PROJECT_ROOT / "filtered_news.json"
SNAPSHOT_PATH = PROJECT_ROOT / "market_snapshot.json"

st.set_page_config(
    page_title="Wealth Engine — Painel Mestre",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Auto-refresh ──
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=30_000, limit=None, key="megarefresh")
except ImportError:
    st.caption("💡 `pip install streamlit-autorefresh` para auto-refresh. Por ora, aperte R.")


# ═══════════════════════════ HELPERS ═══════════════════════════

def load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def load_jsonl(path: Path, n_last: int = 500) -> list[dict]:
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
        lines = [l for l in text.splitlines() if l.strip()]
        lines = lines[-n_last:]
        return [json.loads(l) for l in lines]
    except Exception:
        return []


def ago(ts_str: str) -> str:
    if not ts_str:
        return "—"
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - dt
        secs = delta.total_seconds()
        if secs < 60:
            return f"há {int(secs)}s"
        elif secs < 3600:
            return f"há {int(secs//60)}min"
        elif secs < 86400:
            return f"há {int(secs//3600)}h"
        else:
            return f"há {int(secs//86400)}d"
    except Exception:
        return ts_str[:19]


def regime_color(regime: str) -> str:
    return {"risk_on": "#4CAF50", "normal": "#2196F3",
            "risk_off": "#FF9800", "crisis": "#F44336"}.get(regime, "#9E9E9E")


def regime_emoji(regime: str) -> str:
    return {"risk_on": "✅", "normal": "⚖️", "risk_off": "⚠️", "crisis": "🚨"}.get(regime, "❓")


def regime_bg(regime: str) -> str:
    return {"risk_on": "#1a2e1a", "normal": "#1a1a2e",
            "risk_off": "#2e2a1a", "crisis": "#2e1a1a"}.get(regime, "#1a1a1a")


def session_emoji(session: str) -> str:
    return {"Sydney": "🇦🇺", "Tokyo": "🇯🇵", "London": "🇬🇧", "NewYork": "🇺🇸"}.get(session, "🌍")


def direction_emoji(dir_: str) -> str:
    return {"BUY": "🟢", "SELL": "🔴", "NONE": "⚪",
            "bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}.get(dir_, "⚪")


def direction_color(dir_: str) -> str:
    return {"bullish": "#4CAF50", "bearish": "#F44336",
            "long": "#4CAF50", "short": "#F44336",
            "BUY": "#4CAF50", "SELL": "#F44336",
            "neutral": "#FFC107", "NONE": "#9E9E9E"}.get(dir_, "#9E9E9E")


def result_emoji(result: str) -> str:
    return {"opened": "✅", "dry_run": "🔍", "blocked_filter": "🚫",
            "no_signal": "📉", "error": "❌"}.get(result, "❓")


FILTER_LABELS = {
    "mt5_connect": "🔌 Conexão MT5",
    "account_info": "👤 Info da Conta",
    "dd_check": "📉 Drawdown Diário/Semanal",
    "crisis": "🚨 Regime Crisis",
    "macro_blockers": "📅 Evento Econômico",
    "exposure_check": "📊 Exposição Total",
    "already_open": "🔄 Já Aberto (anti-empilhamento)",
    "cooldown": "⏳ Cooldown do Símbolo",
    "max_positions": "📦 Máx Posições Abertas",
    "risk_cap": "💰 Risco por Trade > Cap",
    "rr_": "📐 RR < Mínimo",
    "session_": "🌍 Filtro de Sessão",
    "max_positions_reached": "📦 Máx Posições Atingido",
}


def filter_label(key: str) -> str:
    if not key:
        return "—"
    for prefix, label in FILTER_LABELS.items():
        if key.startswith(prefix):
            return label
    return key


def impact_emoji(impact: str) -> str:
    return {"alto": "🔴", "medio": "🟡", "baixo": "⚪"}.get(impact, "⚪")


def arrow_for(dir_: str) -> str:
    return {"bullish": "▲", "bearish": "▼", "long": "▲", "short": "▼", "BUY": "▲", "SELL": "▼"}.get(dir_, "▬")


def get_current_session() -> str:
    h = datetime.now(timezone.utc).hour
    if 21 <= h < 24:
        return "Sydney"     # Sydney abre ~22:00 UTC (AEST, sem DST)
    elif 0 <= h < 7:
        return "Tokyo"      # Tokyo 00:00-06:00 UTC + overlap Sydney
    elif 7 <= h < 13:
        return "London"     # Europa (BST=UTC+1: 07:00-16:00)
    else:  # 13 <= h < 21
        return "NewYork"    # EUA (EDT=UTC-4: 12:00-21:00)


# ═══════════════════════════ CARREGAR DADOS ═══════════════════════════

state = load_json(STATE_PATH)
intel = load_json(INTEL_PATH)
snap = load_json(SNAPSHOT_PATH)
news = load_json(NEWS_PATH)
decisions = load_jsonl(DECISION_LOG_PATH, n_last=300)
events = load_jsonl(TRADE_LOG_PATH, n_last=200)

# ═══════════════════════════ SIDEBAR ═══════════════════════════

st.sidebar.title("🤖 Wealth Engine")
st.sidebar.caption("Painel Mestre Unificado")

# ── Bot Status ──
last_run = state.get("last_run_utc", "")
st.sidebar.subheader("📡 Bot Status")
if last_run:
    try:
        dt = datetime.fromisoformat(last_run.replace("Z", "+00:00"))
        secs = (datetime.now(timezone.utc) - dt).total_seconds()
        if secs < 600:
            st.sidebar.success(f"✅ Rodando ({ago(last_run)})")
        else:
            st.sidebar.warning(f"⏸️ Parado ({ago(last_run)})")
    except Exception:
        st.sidebar.info(f"🕐 {last_run[:19]}")
else:
    st.sidebar.error("❌ Nunca rodou")

# ── Account ──
mt5_data = intel.get("mt5", {})
account = mt5_data.get("account", {})
if account:
    bal = account.get("balance", 0)
    eq = account.get("equity", 0)
    st.sidebar.metric("💰 Saldo", f"${bal:,.2f}")
    st.sidebar.metric("📊 Equity", f"${eq:,.2f}")
    if bal > 0:
        pnl_pct = (eq - bal) / bal * 100
        st.sidebar.metric("📈 P&L Flutuante", f"{pnl_pct:+.2f}%",
                          delta_color="normal" if pnl_pct >= 0 else "inverse")

# ── Prices sidebar ──
prices = mt5_data.get("prices", {})
if prices:
    st.sidebar.subheader("💱 Preços")
    for sym, info in prices.items():
        if isinstance(info, dict):
            bid = info.get("bid", 0)
            ask = info.get("ask", 0)
            st.sidebar.write(f"**{sym}**: {bid:.5f} / {ask:.5f}")

# ── Quick decision stats ──
st.sidebar.subheader("📊 Decisões (últ. 300)")
_opened_count = sum(1 for d in decisions if d.get("payload", {}).get("result") == "opened")
_blocked_count = sum(1 for d in decisions if d.get("payload", {}).get("result") == "blocked_filter")
_nosignal_count = sum(1 for d in decisions if d.get("payload", {}).get("result") == "no_signal")
st.sidebar.markdown(f"✅ Abertos: **{_opened_count}**")
st.sidebar.markdown(f"🚫 Bloqueios: **{_blocked_count}**")
st.sidebar.markdown(f"📉 Sem sinal: **{_nosignal_count}**")

# ── Navigation hint ──
st.sidebar.divider()
st.sidebar.caption("💡 Auto-refresh a cada 30s")
st.sidebar.caption("🌐 Acessível via IP da rede")
st.sidebar.caption(f"📡 Porta: 8501")


# ═══════════════════════════ MAIN TITLE ═══════════════════════════

st.title("🤖 Wealth Engine — Painel Mestre")
st.caption(
    f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC "
    f"| Último bot: {ago(last_run)} "
    f"| Snapshot: {ago(snap.get('timestamp', '')) if snap else 'N/A'}"
)


# ═══════════════════════════ 1. VEREDICTO DO SISTEMA ═══════════════════════════

# Regime da última decisão
regime_str = "unknown"
last_decision_ts = ""
for d in reversed(decisions):
    ctx = d.get("payload", {}).get("market_context", {})
    r = ctx.get("regime")
    if r:
        regime_str = r
        last_decision_ts = d.get("ts_utc", "")
        break

# Market verdict do snapshot
snap_conclusion = snap.get("conclusion", "")
snap_confidence = snap.get("confidence", 0)
snap_risk_score = snap.get("risk_score", 50)
snap_regime = snap.get("regime", "")

# Usa regime do snapshot se disponível, senão do decision_log
if snap_regime:
    regime_str = snap_regime

# Build verdict
if _opened_count > 0:
    _verdict_icon = "✅"
    _verdict_title = "SISTEMA OPERACIONAL"
    _verdict_color = "#4CAF50"
    _verdict_bg = "#1a2e1a"
    _verdict_text = f"{_opened_count} ordens abertas nas últimas {len(decisions)} decisões."
else:
    _verdict_icon = "🚫"
    _verdict_title = "NÃO ESTÁ ABRINDO ORDENS"
    _verdict_color = "#F44336"
    _verdict_bg = "#2e1a1a"
    if _blocked_count > _nosignal_count:
        _verdict_text = f"{_blocked_count} bloqueios por filtro vs {_nosignal_count} sem sinal."
        # Find last block reason
        for d in reversed(decisions):
            if d.get("payload", {}).get("result") == "blocked_filter":
                motivo = d.get("payload", {}).get("reasoning", {}).get("reason", "")
                if motivo:
                    _verdict_text += f" Último bloqueio: {motivo[:120]}"
                break
    else:
        _verdict_text = f"{_nosignal_count} decisões 'sem sinal' (momentum fraco/dados insuficientes)."

if last_decision_ts:
    _verdict_text += f" Último ciclo: {ago(last_decision_ts)}."

# Add market conclusion if available
if snap_conclusion:
    _verdict_text = snap_conclusion + " | " + _verdict_text

st.markdown(
    f"""
    <div style="background-color:{_verdict_bg}; padding:20px; border-radius:12px;
                 border-left:6px solid {_verdict_color}; margin-bottom:20px;">
        <div style="font-size:12px; color:#aaa;">VEREDICTO DO SISTEMA</div>
        <div style="font-size:22px; font-weight:bold; margin:8px 0; color:{_verdict_color};">
            {_verdict_icon} {_verdict_title}
        </div>
        <div style="font-size:14px; color:#ccc;">
            {_verdict_text}
        </div>
        <div style="font-size:12px; color:#666; margin-top:4px;">
            Regime: {regime_str.upper()} | Confiança: {snap_confidence}/100 |
            Risk Score: {snap_risk_score}/100 |
            {_blocked_count} bloqueios | {_nosignal_count} sem sinal | {_opened_count} abertos
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.divider()

# ═══════════════════════════ 2. TOP ROW: Métricas ═══════════════════════════

col1, col2, col3, col4 = st.columns(4)

# Regime
rc = regime_color(regime_str)
with col1:
    st.markdown(
        f"""
        <div style="background-color:#1a1a1a; padding:15px; border-radius:10px;
                     border-left:5px solid {rc}; text-align:center;">
            <div style="font-size:12px; color:#aaa;">REGIME</div>
            <div style="font-size:28px; font-weight:bold; color:{rc};">
                {regime_emoji(regime_str)} {regime_str.upper()}
            </div>
            <div style="font-size:12px; color:#666;">Confiança: {snap_confidence}/100</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# VIX / DXY
rs = intel.get("risk_sentiment", {}) if intel else {}
vix = rs.get("vix")
vix_chg = rs.get("vix_pct_change")
dxy = rs.get("dollar_index")
dxy_chg = rs.get("dollar_index_pct_change")
with col2:
    vix_color = "#4CAF50" if (vix or 0) < 18 else "#FF9800" if (vix or 0) < 25 else "#F44336"
    vix_str = f"{vix:.1f}" if vix is not None else "—"
    vix_chg_str = f"({vix_chg:+.1f}%)" if isinstance(vix_chg, (int, float)) else ""
    dxy_str = f"{dxy:.2f}" if dxy is not None else "—"
    dxy_chg_str = f"({dxy_chg:+.2f}%)" if isinstance(dxy_chg, (int, float)) else ""
    st.markdown(
        f"""
        <div style="background-color:#1a1a1a; padding:15px; border-radius:10px;
                     border-left:5px solid {vix_color}; text-align:center;">
            <div style="font-size:12px; color:#aaa;">SENTIMENTO</div>
            <div style="font-size:20px;">
                VIX: <b>{vix_str}</b>
                <span style="font-size:14px; color={'#F44336' if (vix_chg or 0) > 0 else '#4CAF50'};">{vix_chg_str}</span>
            </div>
            <div style="font-size:16px;">
                DXY: <b>{dxy_str}</b>
                <span style="font-size:12px; color:#666;">{dxy_chg_str}</span>
            </div>
            <div style="font-size:11px; color:#555; margin-top:2px;">
                Risk Score: {snap_risk_score}/100
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# Session
sess = get_current_session()
with col3:
    st.markdown(
        f"""
        <div style="background-color:#1a1a1a; padding:15px; border-radius:10px;
                     border-left:5px solid #2196F3; text-align:center;">
            <div style="font-size:12px; color:#aaa;">SESSÃO</div>
            <div style="font-size:28px;">
                {session_emoji(sess)} {sess}
            </div>
            <div style="font-size:12px; color:#666;">{datetime.now(timezone.utc).strftime('%H:%M')} UTC</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# Cooldown
with col4:
    exits = state.get("last_exit_ts", {})
    cooldown_h = 48
    cooldown_items = []
    for sym, ts_exit in exits.items():
        try:
            dt_exit = datetime.fromisoformat(ts_exit.replace("Z", "+00:00"))
            remaining = (dt_exit + timedelta(hours=cooldown_h) - datetime.now(timezone.utc)).total_seconds()
            if remaining > 0:
                cooldown_items.append(f"{sym}: {int(remaining//3600)}h{int((remaining%3600)//60)}m")
        except Exception:
            pass

    cd_html = "<br>".join(cooldown_items) if cooldown_items else "✅ Nenhum"
    cd_color = "#FF9800" if cooldown_items else "#4CAF50"
    st.markdown(
        f"""
        <div style="background-color:#1a1a1a; padding:15px; border-radius:10px;
                     border-left:5px solid {cd_color}; text-align:center;">
            <div style="font-size:12px; color:#aaa;">COOLDOWN ({cooldown_h}h)</div>
            <div style="font-size:16px;">
                {cd_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.divider()

# ═══════════════════════════ 3. DRIVERS DE MERCADO + DIREÇÃO ═══════════════════════════

if snap and "drivers" in snap:
    st.subheader("🔍 Drivers de Mercado — O que está movendo")

    drivers = snap.get("drivers", [])
    if drivers:
        driver_cols = st.columns(min(len(drivers), 3))
        for i, d in enumerate(sorted(drivers, key=lambda x: x.get("strength", 0), reverse=True)[:6]):
            with driver_cols[i % 3]:
                strength = d.get("strength", 0)
                direction = d.get("direction", "neutral")
                driver = d.get("driver", "")
                rationale = d.get("rationale", "")
                detail = d.get("detail", {})

                icon_map = {"USD": "💵", "RISK": "🌊", "YIELDS": "🏦",
                            "COT": "🏢", "MOMENTUM": "📈", "REGIME": "⚙️", "NEWS": "📰"}
                icon = icon_map.get(driver, "📊")

                dc = direction_color(direction)
                bar = "█" * int(strength * 12) + "░" * (12 - int(strength * 12))

                st.markdown(
                    f"""
                    <div style="background-color:#1a1a1a; padding:12px; border-radius:8px;
                                 border-left:4px solid {dc}; margin-bottom:8px;">
                        <div style="font-size:15px; font-weight:bold;">
                            {icon} {driver}
                            <span style="color:{dc}; float:right;">{arrow_for(direction)} {direction.upper()}</span>
                        </div>
                        <div style="font-size:11px; color:#666; font-family:monospace;">{bar} {strength:.0%}</div>
                        <div style="font-size:12px; color:#aaa; margin-top:4px;">{rationale[:100]}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                # Expandable details
                if driver == "USD" and detail.get("dxy") is not None:
                    dxy_val = detail["dxy"] or 0
                    dxy_pct = detail.get("dxy_pct") or 0
                    st.caption(f"DXY: {dxy_val:.2f} ({dxy_pct:+.2f}%)")
                elif driver == "RISK" and detail.get("vix") is not None:
                    vix_val = detail["vix"] or 0
                    vix_pct = detail.get("vix_pct") or 0
                    st.caption(f"VIX: {vix_val:.1f} ({vix_pct:+.1f}%)")
                elif driver == "YIELDS" and detail.get("treasury_10y") is not None:
                    ty_val = detail["treasury_10y"] or 0
                    st.caption(f"Treasury 10y: {ty_val:.2f}%")
                elif driver == "NEWS" and detail.get("top"):
                    for n in detail["top"][:3]:
                        st.caption(f"{impact_emoji(n.get('impact',''))} {n.get('headline','?')[:60]}")
                elif driver == "COT" and detail:
                    cot_items = {k: v for k, v in detail.items() if k != "top" and v is not None}
                    for cur, net in list(cot_items.items())[:3]:
                        c = "#4CAF50" if net and net > 0 else "#F44336"
                        st.markdown(f"<span style='font-size:11px;color:{c}'>{cur}: {int(net or 0):+,}</span>",
                                    unsafe_allow_html=True)
    else:
        st.info("Nenhum driver encontrado no snapshot.")

    # ── Asset direction ──
    assets = snap.get("assets", [])
    if assets:
        st.subheader("🧭 Direção por Ativo")
        asset_cols = st.columns(min(len(assets), 4))
        for i, a in enumerate(assets):
            with asset_cols[i % 4]:
                sym = a.get("symbol", "")
                direction = a.get("direction", "neutral")
                strength = a.get("strength", 0)
                thesis = a.get("thesis", "")
                ac = direction_color(direction)
                arr = arrow_for(direction)

                st.markdown(
                    f"""
                    <div style="padding:12px 14px; border-radius:8px; border-left:4px solid {ac};
                                background-color:#1a1a1a; margin-bottom:8px;">
                        <div style="font-size:20px; font-weight:bold; color:{ac};">
                            {arr} {sym}
                        </div>
                        <div style="font-size:11px; color:#ccc; margin-top:2px;">
                            {thesis[:80]}
                            <span style="color:#666;">força {strength:.0%}</span>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # Alerts from snapshot
    alerts = snap.get("alerts", [])
    if alerts:
        st.subheader("🚨 Alertas")
        for al in alerts:
            st.warning(al)

    st.divider()

# ═══════════════════════════ 4. PIPELINE DE DECISÃO ═══════════════════════════

st.subheader("🔍 Pipeline de Decisão — O que está bloqueando as ordens?")

# Count blockers
blocked_counter: Counter = Counter()
blocked_details: dict[str, list[str]] = defaultdict(list)
signal_counter: Counter = Counter()
last_blocked_per_filter: dict[str, str] = {}

for d in decisions:
    payload = d.get("payload", {})
    result = payload.get("result", "")
    filt = payload.get("filter_blocked", "")
    rsn = payload.get("reasoning", {}).get("reason", "")
    ts = d.get("ts_utc", "")

    if result == "blocked_filter" and filt:
        label = filter_label(filt)
        blocked_counter[label] += 1
        if rsn:
            blocked_details[label].append(rsn)
        last_blocked_per_filter[label] = ts
    elif result == "no_signal":
        signal_counter["no_signal"] += 1
    elif result == "opened":
        signal_counter["opened"] += 1
    elif result == "dry_run":
        signal_counter["dry_run"] += 1
    elif result == "error":
        signal_counter["error"] += 1

total_decisions = len(decisions) or 1
total_blocked = sum(blocked_counter.values())

# Metrics summary
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric("🔄 Ciclos Analisados", f"{total_decisions} decisões")
with c2:
    pct_blocked = total_blocked / total_decisions * 100
    st.metric("🚫 Bloqueios por Filtro", f"{total_blocked} ({pct_blocked:.0f}%)")
with c3:
    st.metric("✅ Ordens Abertas", f"{signal_counter.get('opened', 0)}")
with c4:
    st.metric("📉 Sem Sinal", f"{signal_counter.get('no_signal', 0)}")

st.markdown("---")

# Most recent filter
most_recent_filter = None
most_recent_ts = ""
for label, ts in last_blocked_per_filter.items():
    if ts > most_recent_ts:
        most_recent_ts = ts
        most_recent_filter = label

if blocked_counter:
    st.markdown("### 🚫 Bloqueios por Filtro (últimas 300 decisões)")
    filter_cols = st.columns(4)
    for i, (label, count) in enumerate(blocked_counter.most_common()):
        with filter_cols[i % 4]:
            pct = count / total_decisions * 100
            is_blocking = label == most_recent_filter
            border_color = "#F44336" if is_blocking else "#333"
            glow = "box-shadow: 0 0 10px rgba(244,67,54,0.3);" if is_blocking else ""
            st.markdown(
                f"""
                <div style="background-color:#1a1a1a; padding:12px; border-radius:8px;
                             border-left:4px solid {border_color}; {glow} margin-bottom:8px;">
                    <div style="font-size:13px; color:#ccc;">{label}</div>
                    <div style="font-size:26px; font-weight:bold; color={'#F44336' if count > 5 else '#FF9800'};">
                        {count}x
                    </div>
                    <div style="font-size:11px; color:#666;">{pct:.1f}% das decisões</div>
                    <div style="font-size:11px; color:#888;">
                        Último: {ago(last_blocked_per_filter.get(label, ''))}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # Top blocker details
    top_filter = blocked_counter.most_common(1)[0][0]
    st.markdown(f"### 🔍 Por que **{top_filter}** está bloqueando?")
    reasons = blocked_details.get(top_filter, [])
    for r in reasons[:5]:
        st.write(f"- {r}")
    if len(reasons) > 5:
        st.caption(f"... e mais {len(reasons)-5} ocorrências")
else:
    st.info("Nenhum bloqueio registrado nas últimas decisões.")

st.divider()

# ═══════════════════════════ 5. TIMELINE ═══════════════════════════

st.subheader("📜 Timeline de Decisões (últimas 50)")

recent_decisions = decisions[-50:]
if recent_decisions:
    timeline_rows = []
    for d in reversed(recent_decisions):
        payload = d.get("payload", {})
        ctx = payload.get("market_context", {})
        rsn = payload.get("reasoning", {})
        risk = payload.get("risk", {})

        ts = d.get("ts_utc", "")
        symbol = payload.get("symbol", "?")
        direction = payload.get("direction", "?")
        result = payload.get("result", "?")
        filt = payload.get("filter_blocked", "")

        regime = ctx.get("regime", "?")
        session = ctx.get("session", "?")
        reason = rsn.get("reason", "")
        mom = rsn.get("momentum_signal_pct")
        rr_val = risk.get("rr") if risk else None
        lot = risk.get("lot") if risk else None

        mom_str = f"{mom:+.3f}%" if mom is not None else ""
        rr_str = f"RR {rr_val:.2f}" if rr_val else ""
        lot_str = f"{lot} lot" if lot else ""

        timeline_rows.append({
            "🕐": ago(ts),
            "Símbolo": symbol,
            "→": direction_emoji(direction),
            "Direção": direction,
            "Resultado": f"{result_emoji(result)} {result}",
            "Filtro": filter_label(filt) if filt else "—",
            "Motivo": reason[:80] if reason else "—",
            "Detalhes": f"{mom_str} {rr_str} {lot_str}".strip(),
            "Regime": regime,
            "Sessão": session,
        })

    df = pd.DataFrame(timeline_rows)

    def color_result(val):
        if "opened" in str(val):
            return "background-color: #1a3a1a; color: #4CAF50"
        elif "blocked" in str(val):
            return "background-color: #3a1a1a; color: #F44336"
        elif "dry_run" in str(val):
            return "background-color: #1a1a3a; color: #FFC107"
        elif "no_signal" in str(val):
            return "color: #888"
        return ""

    display_cols = ["🕐", "Símbolo", "→", "Direção", "Resultado", "Filtro", "Motivo", "Detalhes", "Regime", "Sessão"]
    df_display = df[display_cols]

    st.dataframe(
        df_display.style.map(color_result, subset=["Resultado"]),
        width='stretch',
        hide_index=True,
        height=min(50 * 25, 600),
    )
else:
    st.info("Nenhuma decisão registrada ainda.")

st.divider()

# ═══════════════════════════ 6. TRADES RECENTES ═══════════════════════════

st.subheader("📊 Últimos Eventos (trade_log.jsonl)")

trade_events = [e for e in events if e.get("type") in (
    "ORDER_SENT", "DEAL_FOUND", "DRY_RUN_WOULD_OPEN",
    "CYCLE_END", "CYCLE_BLOCKED_EXPOSURE", "CYCLE_BLOCKED_DD",
    "CYCLE_BLOCKED_MACRO", "CYCLE_BLOCKED_CRISIS",
)]

if trade_events:
    trade_rows = []
    for e in reversed(trade_events[-50:]):
        ts = e.get("ts_utc", "")
        etype = e.get("type", "")
        payload = e.get("payload", {})

        if etype == "ORDER_SENT":
            req = payload.get("req", {})
            result = payload.get("result_retcode")
            sym = req.get("symbol", "?")
            dir_ = "BUY" if req.get("type") == 0 else "SELL"
            lot = req.get("volume", 0)
            price = req.get("price", 0)
            trade_rows.append({
                "🕐": ago(ts), "Evento": "📤 ORDER SENT",
                "Símbolo": sym, "Direção": dir_, "Lote": lot,
                "Preço": f"{price:.5f}",
                "Resultado": "✅ OK" if result in (10009, 10008) else f"❌ {result}",
                "Deal": payload.get("deal", ""),
            })
        elif etype == "DEAL_FOUND":
            sym = payload.get("symbol", "?")
            profit = payload.get("profit", 0)
            deal_type = "Buy" if payload.get("type") == 0 else "Sell"
            trade_rows.append({
                "🕐": ago(ts), "Evento": "💰 DEAL",
                "Símbolo": sym, "Direção": deal_type,
                "Lote": payload.get("volume", 0),
                "Preço": f"{payload.get('price', 0):.5f}",
                "Resultado": f"{'✅' if profit > 0 else '❌'} ${profit:+.2f}",
                "Deal": payload.get("deal", ""),
            })
        elif etype == "DRY_RUN_WOULD_OPEN":
            sym = payload.get("symbol", "?")
            dir_ = payload.get("direction", "?")
            lot = payload.get("lot", 0)
            rr_val = payload.get("rr", 0)
            trade_rows.append({
                "🕐": ago(ts), "Evento": "🔍 DRY-RUN",
                "Símbolo": sym, "Direção": dir_, "Lote": lot,
                "Preço": f"{payload.get('entry', 0):.5f}",
                "Resultado": f"RR {rr_val:.2f}", "Deal": "",
            })
        elif etype.startswith("CYCLE_BLOCKED"):
            motivo = ""
            actions = payload.get("actions", [])
            for a in actions:
                if not a.get("ok", True):
                    motivo = a.get("motivo", a.get("step", ""))
            label = etype.replace("CYCLE_BLOCKED_", "").replace("_", " ").title()
            trade_rows.append({
                "🕐": ago(ts), "Evento": f"🚫 {label}",
                "Símbolo": "—", "Direção": "—", "Lote": "—",
                "Preço": "—", "Resultado": motivo[:60] if motivo else "—", "Deal": "",
            })
        elif etype == "CYCLE_END":
            actions = payload.get("actions", [])
            action_strs = []
            for a in actions:
                if a.get("step") == "open_trade":
                    action_strs.append(f"✅ {a.get('symbol','?')} {a.get('direction','?')}")
                elif a.get("step") == "no_signal":
                    action_strs.append("📉 Sem sinal")
                elif a.get("step") == "dry_run_would_open":
                    action_strs.append(f"🔍 Dry: {a.get('symbol','?')}")
                else:
                    action_strs.append(a.get("step", "?"))
            trade_rows.append({
                "🕐": ago(ts), "Evento": "🔄 CICLO",
                "Símbolo": "—", "Direção": "—",
                "Lote": f"${payload.get('balance', 0):.1f}",
                "Preço": f"{payload.get('exposure_pct', 0):.1f}%",
                "Resultado": ", ".join(action_strs[:3]), "Deal": "",
            })

    if trade_rows:
        df_trades = pd.DataFrame(trade_rows)
        # Fix ArrowTypeError: ensure mixed-type column 'Lote' is string
        if "Lote" in df_trades.columns:
            df_trades["Lote"] = df_trades["Lote"].astype(str)
        st.dataframe(df_trades, width='stretch', hide_index=True,
                     height=min(50 * 25, 500))
    else:
        st.info("Nenhum evento de trade encontrado.")
else:
    st.info("Nenhum evento encontrado no trade_log.")

st.divider()

# ═══════════════════════════ 7. CONTEXTO DE MERCADO ═══════════════════════════

st.subheader("📰 Contexto de Mercado")

ctx_left, ctx_right = st.columns(2)

with ctx_left:
    # Economic calendar
    st.markdown("**📅 Calendário Econômico (próximas 48h)**")
    cal = intel.get("economic_calendar_next_48h", []) if intel else []
    if cal and isinstance(cal, list):
        for ev in cal[:8]:
            st.write(f"- **{ev.get('event','?')}** ({ev.get('country','?')}) — {str(ev.get('time',''))[:16]}")
    else:
        st.caption("Nenhum evento de alto impacto nas próximas 48h.")

    # Active alerts
    st.markdown("**🚨 Alertas Ativos**")
    alerts_bot = intel.get("active_alerts", []) if intel else []
    if alerts_bot:
        for a in alerts_bot:
            st.warning(a)
    else:
        st.caption("Nenhum alerta ativo.")

    # COT
    st.markdown("**🏛️ COT Positioning (CFTC)**")
    cot = intel.get("cot_positioning", {}) if intel else {}
    if cot and "error" not in cot:
        for code, info in cot.items():
            if isinstance(info, dict) and "net" in info:
                c = "#4CAF50" if info["net"] > 0 else "#F44336"
                st.markdown(
                    f"<span style='color:{c}'><b>{code}</b>: {info['vies']} "
                    f"(net {info['net']:+,})</span>",
                    unsafe_allow_html=True,
                )
    else:
        st.caption("COT indisponível.")

with ctx_right:
    # Macro headlines
    st.markdown("**📺 Manchetes Macroeconômicas**")
    headlines = intel.get("macro_headlines", []) if intel else []
    if headlines:
        for h in headlines[:6]:
            fonte = h.get("fonte", "?")
            head = h.get("headline", "?")
            ts_h = h.get("timestamp")
            if ts_h:
                dt_h = datetime.fromtimestamp(ts_h)
                st.write(f"- [{dt_h.strftime('%d/%m %H:%M')}] *{head[:100]}* — `{fonte}`")
            else:
                st.write(f"- *{head[:100]}* — `{fonte}`")
    else:
        st.caption("Sem manchetes (Finnhub não configurado).")

    # Filtered news
    st.markdown("**📰 Notícias Filtradas (news_aggregator)**")
    news_items = news.get("noticias", []) if news else []
    if news_items:
        st.caption(f"{news.get('total_relevante', 0)} relevantes de {news.get('total_coletado', 0)} coletadas")
        for n in news_items[:8]:
            imp = impact_emoji(n.get("impacto", ""))
            ativos = ", ".join(n.get("ativos_afetados", [])) or "—"
            st.write(f"{imp} **{n.get('headline','?')[:80]}** — _{ativos}_ — viés: {n.get('vies','?')}")
    else:
        st.caption("Rode `python scripts/run_intelligence.py` para notícias.")

    # Interest rates
    st.markdown("**🏦 Taxas de Juros**")
    fed = intel.get("fed_rates", {}) if intel else {}
    if fed and "error" not in fed:
        for k, v in fed.items():
            if isinstance(v, dict) and "valor" in v:
                st.metric(k, f"{v['valor']}%", help=f"Data: {v.get('data','?')}")
    else:
        st.caption("FRED não configurado.")

st.divider()

# ═══════════════════════════ 8. CONFIGURAÇÃO ═══════════════════════════

st.subheader("⚙️ Configuração Ativa")
cfg_cols = st.columns(4)
with cfg_cols[0]:
    st.metric("Símbolos", "XAUUSDm, EURUSDm, GBPUSDm, USDJPYm")
with cfg_cols[1]:
    st.metric("Máx Posições", "3")
with cfg_cols[2]:
    st.metric("Risco por Trade", "5-8% (por regime)")
with cfg_cols[3]:
    st.metric("Drawdown Diário", "8%")

cfg_cols2 = st.columns(4)
with cfg_cols2[0]:
    st.metric("RR Mínimo", "2:1")
with cfg_cols2[1]:
    st.metric("Sessão Permitida", "Tokyo")
with cfg_cols2[2]:
    st.metric("Cooldown", "48h")
with cfg_cols2[3]:
    st.metric("Stop Multiplier", "1.5-2.0×ATR")

st.divider()

# ═══════════════════════════ FOOTER ═══════════════════════════

st.caption(
    "🤖 **Wealth Engine — Painel Mestre Unificado** | "
    "Auto-refresh 30s | "
    f"Última atualização: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC | "
    "Acessível via http://localhost:8501 ou http://IP_DA_REDE:8501"
)
