"""macro_analysis.py — cruza todos os sinais e devolve uma leitura de mercado.

Ponto de entrada: analyze_market().

Lê todos os drivers (USD, RISK, YIELDS, COT, MOMENTUM, REGIME, NEWS),
cruzados, e sintetiza:
  - drivers ordenados por força (o que está movendo)
  - direção por ativo (para onde)
  - conclusão em PT (frase pronta pra ler)
  - score de confiança (0-100)

Princípio: HONESTO. Se sinais divergem, diz "sinais mistos". Não inventa
narrativa onde não há. O score cai naturalmente quando há contradição.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from . import config as C
from .macro_signals import (
    Signal, DollarSignal, RiskAppetiteSignal, YieldsSignal,
    CotFlowSignal, MomentumSignal, RegimeSignal, NewsBiasSignal,
    LiquidityStressSignal,
)


# ═════════════════════════════ RESULTADO ═════════════════════════════
@dataclass
class AssetView:
    """Leitura de um ativo: direção + força + tese."""
    symbol: str
    direction: str        # "bullish" | "bearish" | "neutral"
    strength: float       # 0-1
    thesis: str           # texto curto


@dataclass
class MarketSnapshot:
    """Resultado completo de analyze_market()."""
    conclusion: str                       # a frase principal em PT
    confidence: int                       # 0-100
    regime: str                           # "risk_on" | "normal" | "risk_off" | "crisis"
    risk_score: int                       # 0=risk_off total, 100=risk_on total
    drivers: list[Signal]                 # ordenados por força
    assets: list[AssetView]               # direção por símbolo
    alerts: list[str]                     # eventos/divergências
    timestamp: str = ""
    signals_raw: dict = field(default_factory=dict)  # pra debug/dashboard

    def to_dict(self) -> dict:
        return {
            "conclusion": self.conclusion,
            "confidence": self.confidence,
            "regime": self.regime,
            "risk_score": self.risk_score,
            "drivers": [
                {"driver": d.driver, "direction": d.direction,
                 "strength": round(d.strength, 3), "rationale": d.rationale,
                 "detail": _safe_detail(d.detail)}
                for d in self.drivers
            ],
            "assets": [asdict(a) for a in self.assets],
            "alerts": self.alerts,
            "timestamp": self.timestamp,
        }


def _safe_detail(d: dict) -> dict:
    """Converte valores numpy/python pra JSON-serializable."""
    out = {}
    for k, v in d.items():
        if isinstance(v, (np.floating, np.integer)):
            out[k] = float(v)
        elif isinstance(v, dict):
            out[k] = {kk: (float(vv) if isinstance(vv, (np.floating, np.integer)) else vv)
                      for kk, vv in v.items()}
        else:
            out[k] = v
    return out


# ═════════════════════════════ BETA-USD DAS MOEDAS ═════════════════════════════
# Quandp USD fortalece, EUR/GBP/XAU caem (beta negativo), JPY sobe parcial.
USD_BETA = C.USD_BETA  # {"EURUSDm": -1.0, "GBPUSDm": -1.0, "USDJPYm": +0.6, "XAUUSDm": -1.0}


# ═════════════════════════════ ANALYZER PRINCIPAL ═════════════════════════════
def analyze_market(
    intel: dict,
    prices: dict[str, pd.DataFrame],
    vix: Optional[pd.Series] = None,
    regime_str: Optional[str] = None,
    news_path: Optional[Path | str] = None,
) -> MarketSnapshot:
    """Cruza todos os drivers e devolve uma MarketSnapshot.

    intel:       dict de market_intelligence.json (DXY, Fed rates, COT, etc.)
    prices:      {symbol: DataFrame} H4 OHLCV
    vix:         pd.Series do VIX (opcional, fallback pro intel)
    regime_str:  regime atual (se None, tenta inferir)
    news_path:   caminho pra filtered_news.json (opcional)
    """
    # ── 1. lê todos os drivers ──
    signals: list[Signal] = []
    usd_sig = DollarSignal().read(intel, prices)
    risk_sig = RiskAppetiteSignal().read(intel, vix)
    liq_sig = LiquidityStressSignal().read(intel)
    yield_sig = YieldsSignal().read(intel, prices)
    cot_sig = CotFlowSignal().read(intel, prices)
    mom_sig = MomentumSignal().read(intel, prices)
    reg_sig = RegimeSignal().read(regime_str)
    news_sig = NewsBiasSignal().read(str(news_path)) if news_path else Signal("NEWS", rationale="notícias não carregadas")

    signals = [usd_sig, risk_sig, liq_sig, yield_sig, cot_sig, mom_sig, reg_sig, news_sig]
    # ordena por força (maior primeiro)
    signals.sort(key=lambda s: s.strength, reverse=True)

    # ── 2. regime: usa o implícito do risk_sig se não veio ──
    regime = regime_str or risk_sig.detail.get("regime_implied", "normal")

    # ── 3. risk_score (0=risk_off total, 100=risk_on total) ──
    risk_vote = 50
    for s in [risk_sig, liq_sig, reg_sig, news_sig]:
        if s.direction == "long":
            risk_vote += s.strength * 20
        elif s.direction == "short":
            risk_vote -= s.strength * 20
    risk_score = int(np.clip(risk_vote, 0, 100))

    # ── 4. direção por ativo ──
    assets = _asset_views(signals, prices)

    # ── 5. alertas ──
    alerts = _build_alerts(signals, intel, assets)

    # ── 6. conclusão em PT ──
    conclusion = _build_conclusion(signals, regime, risk_score, assets)

    # ── 7. confiança: quão alinhados estão os sinais fortes? ──
    confidence = _confidence(signals)

    return MarketSnapshot(
        conclusion=conclusion,
        confidence=confidence,
        regime=regime,
        risk_score=risk_score,
        drivers=signals,
        assets=assets,
        alerts=alerts,
        timestamp=datetime.now(timezone.utc).isoformat(),
        signals_raw={s.driver: {"direction": s.direction, "strength": s.strength} for s in signals},
    )


# ═════════════════════════════ DIREÇÃO POR ATIVO ═════════════════════════════
def _asset_views(signals: list[Signal], prices: dict) -> list[AssetView]:
    """Para cada símbolo, vota: USD + momentum + risk + COT."""
    usd = next((s for s in signals if s.driver == "USD"), None)
    risk = next((s for s in signals if s.driver == "RISK"), None)
    mom = next((s for s in signals if s.driver == "MOMENTUM"), None)
    cot = next((s for s in signals if s.driver == "COT"), None)

    mom_detail = mom.detail if mom else {}
    cot_detail = cot.detail if cot else {}

    # mapa símbolo -> nome de moeda pro COT
    sym_to_cur = {"EURUSDm": "EUR", "GBPUSDm": "GBP", "USDJPYm": "JPY", "XAUUSDm": "XAU"}

    views = []
    for sym in C.SYMBOLS:
        beta = USD_BETA.get(sym, 0)
        score = 0.0  # positivo = bullish, negativo = bearish
        teses = []

        # voto USD: se USD forte (usd.direction long) e beta negativo, bearish pro par
        if usd and usd.strength > 0.1:
            usd_dir = 1 if usd.direction == "long" else (-1 if usd.direction == "short" else 0)
            # par sobe quando USD cai (beta negativo): USD forte → par cai
            vote = -usd_dir * beta * usd.strength
            score += vote * 0.4
            if abs(vote) > 0.1:
                teses.append("USD")

        # voto momentum
        m = mom_detail.get(sym, 0)
        if abs(m) > C.MOMENTUM_MIN_ABS_R:
            score += (1 if m > 0 else -1) * 0.3
            teses.append("momentum")

        # voto risk: risk_on favorece ouro/pro-cíclico, risk_off favorece JPY/USD
        if risk and risk.strength > 0.1:
            r_dir = 1 if risk.direction == "long" else (-1 if risk.direction == "short" else 0)
            # XAU é refúgio: sobe em risk_off (r_dir negativo → +) parcialmente
            if sym == "XAUUSDm":
                score += -r_dir * 0.15  # contracíclico parcial
                if abs(r_dir) > 0:
                    teses.append("risk(refúgio)")
            elif sym == "USDJPYm":
                score += r_dir * 0.15  # procíclico
                if abs(r_dir) > 0:
                    teses.append("risk")

        # voto COT (contrarian leve): se especuladores muito long, leve bearish
        cur = sym_to_cur.get(sym)
        cot_net = cot_detail.get(cur) if cot_detail else None
        if cot_net is not None and abs(cot_net) > 20000:
            score += (-1 if cot_net > 0 else 1) * 0.1
            teses.append("COT")

        # classifica
        if score > 0.25:
            direction, strength = "bullish", min(1.0, score)
            thesis = f"Bullish ({'+'.join(teses)})"
        elif score < -0.25:
            direction, strength = "bearish", min(1.0, abs(score))
            thesis = f"Bearish ({'+'.join(teses)})"
        else:
            direction, strength = "neutral", min(0.3, abs(score))
            thesis = "Neutro" if not teses else f"Misto ({'+'.join(teses)})"

        views.append(AssetView(symbol=sym, direction=direction, strength=strength, thesis=thesis))
    return views


# ═════════════════════════════ CONCLUSÃO EM PT ═════════════════════════════
def _build_conclusion(signals: list[Signal], regime: str, risk_score: int,
                      assets: list[AssetView]) -> str:
    """Frase principal. Começa pelo driver mais forte, puxa regime e ativos."""
    parts = []

    # top 2 drivers por força (já estão ordenados)
    strong = [s for s in signals if s.strength >= 0.3][:2]
    if not strong:
        parts.append("Sinais fracos — mercado sem driver claro.")
    else:
        driver_strs = []
        for s in strong:
            if s.driver == "USD":
                driver_strs.append("USD forte" if s.direction == "long" else "USD fraco" if s.direction == "short" else "USD lateral")
            elif s.driver == "RISK":
                driver_strs.append("risk_on" if s.direction == "long" else "risk_off" if s.direction == "short" else "risco neutro")
            elif s.driver == "YIELDS":
                driver_strs.append("juros subindo" if s.direction == "long" else "juros caindo" if s.direction == "short" else "juros neutros")
            elif s.driver == "COT":
                driver_strs.append("COT long USD" if s.direction == "long" else "COT short USD")
            elif s.driver == "LIQUIDITY":
                if s.direction == "short":
                    driver_strs.append("💧 stress de liquidez (flight-to-dollar)")
                elif s.direction == "long":
                    driver_strs.append("💧 sem stress de liquidez (ouro mantém proteção)")
            elif s.driver == "MOMENTUM":
                driver_strs.append("momentum de alta" if s.direction == "long" else "momentum de baixa" if s.direction == "short" else "momentum misto")
            elif s.driver == "REGIME":
                continue  # regime aparece depois
            elif s.driver == "NEWS":
                driver_strs.append("narrativa hawkish" if s.direction == "long" else "narrativa dovish" if s.direction == "short" else "narrativa neutra")
        if driver_strs:
            parts.append("Mercado precificando " + " + ".join(driver_strs) + ".")

    # ativos pressionados
    bears = [a.symbol for a in assets if a.direction == "bearish"]
    bulls = [a.symbol for a in assets if a.direction == "bullish"]
    if bears:
        parts.append(f"Pressão baixa em {', '.join(bears)}.")
    if bulls:
        parts.append(f"Favorável a {', '.join(bulls)}.")
    if not bears and not bulls:
        parts.append("Sem pressão direcional clara nos pares.")

    # regime
    reg_map = {"risk_on": "risk_on (favorável)", "normal": "neutro",
               "risk_off": "risk_off (cauteloso)", "crisis": "CRISIS (defensivo)"}
    parts.append(f"Regime: {reg_map.get(regime, regime)}.")

    return " ".join(parts)


# ═════════════════════════════ ALERTAS ═════════════════════════════
def _build_alerts(signals: list[Signal], intel: dict, assets: list[AssetView]) -> list[str]:
    alerts = []
    # evento de alto impacto em <2h
    cal = intel.get("economic_calendar_next_48h", []) if intel else []
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    for ev in cal:
        try:
            ev_time = datetime.fromisoformat(str(ev.get("time", "")).replace("Z", "+00:00"))
            mins = (ev_time - now).total_seconds() / 60
            if 0 <= mins <= 120:
                alerts.append(f"⚡ Evento em {int(mins)}min: {ev.get('event','?')} ({ev.get('country','?')})")
        except Exception:
            continue

    # divergência forte: USD diz uma coisa, momentum diz outra
    usd = next((s for s in signals if s.driver == "USD"), None)
    mom = next((s for s in signals if s.driver == "MOMENTUM"), None)
    if usd and mom and usd.strength > 0.4 and mom.strength > 0.4:
        if usd.direction != mom.direction and usd.direction != "neutral" and mom.direction != "neutral":
            alerts.append("⚠️ Divergência: USD e momentum apontam direções opostas.")

    # crisis
    risk = next((s for s in signals if s.driver == "RISK"), None)
    if risk and risk.detail.get("regime_implied") == "crisis":
        alerts.append("🔴 VIX em nível de pânico — risco de crise.")

    # liquidity stress
    liq = next((s for s in signals if s.driver == "LIQUIDITY"), None)
    if liq and liq.direction == "short" and liq.strength >= 0.5:
        alerts.append("🚨 STRESS DE LIQUIDEZ: DXY + VIX subindo juntos. Dólar vencendo ouro como safe haven.")
    elif liq and liq.direction == "short" and liq.strength >= 0.3:
        alerts.append("⚠️ Alerta de liquidez: DXY subindo forte — possível flight-to-dollar.")

    return alerts


# ═════════════════════════════ CONFIANÇA ═════════════════════════════
def _confidence(signals: list[Signal]) -> int:
    """0-100. Alta quando sinais fortes concordam, baixa quando divergem."""
    # pega sinais com força > 0.2
    active = [s for s in signals if s.strength > 0.2 and s.direction != "neutral"]
    if not active:
        return 25  # sem sinais fortes = baixa confiança
    longs = sum(1 for s in active if s.direction == "long")
    shorts = sum(1 for s in active if s.direction == "short")
    agreement = abs(longs - shorts) / max(1, len(active))
    avg_strength = np.mean([s.strength for s in active])
    # confiança = concordância × força média
    conf = int(np.clip(agreement * 100 * (0.4 + 0.6 * avg_strength), 0, 100))
    return conf


__all__ = ["analyze_market", "MarketSnapshot", "AssetView"]
