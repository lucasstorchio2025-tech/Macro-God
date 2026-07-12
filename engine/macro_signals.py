"""macro_signals.py — blocos de leitura do mercado.

Cada classe aqui lê um pedaço dos dados (DXY, VIX, yields, COT, momentum,
regime, notícias) e devolve um Signal padronizado: direção + força + texto.

Princípio: cada sinal é HONESTO. Se os dados estão fracos ou ambíguos,
devolve strength baixo. Não força leitura onde não há leitura.

Signal é o átomo da análise. O macro_analysis.py combina todos eles pra
chegar numa conclusão sobre o que move o mercado.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from . import config as C

# ═════════════════════════════ TIPO PADRÃO ═════════════════════════════
@dataclass
class Signal:
    """Resultado de ler um driver de mercado.

    direction: "long" | "short" | "neutral"  (em relação ao que o driver mede)
    strength:  0.0 a 1.0 (quão forte é a leitura)
    rationale: texto em PT explicando o porquê
    driver:    nome do driver ("USD", "RISK", "YIELDS", "COT", "MOMENTUM", ...)
    detail:    dict com valores crus pra o dashboard mostrar
    """
    driver: str
    direction: str = "neutral"   # "long" | "short" | "neutral"
    strength: float = 0.0
    rationale: str = ""
    detail: dict = field(default_factory=dict)


def _strength_from_pct_change(pct: float, scale: float = 1.0) -> float:
    """Converte % change em força [0,1]. scale = % que = força cheia."""
    return float(np.clip(abs(pct) / scale, 0, 1))


# ═════════════════════════════ DXY / DÓLAR ═════════════════════════════
class DollarSignal:
    """Lê o Dollar Index (DXY) pra determinar força do USD.

    direction "long" = USD forte (DXY subindo), "short" = USD fraco.
    Usa a % change diária se disponível; senão cai no nível vs. referência.
    """

    def read(self, intel: dict, prices: dict[str, pd.DataFrame]) -> Signal:
        rs = intel.get("risk_sentiment", {}) if intel else {}
        dxy = rs.get("dollar_index")
        dxy_chg = rs.get("dollar_index_pct_change")
        if dxy is None:
            return Signal("USD", rationale="DXY indisponível")
        dxy = float(dxy)

        # se tem % change, usa; senão infere força pelo nível vs. 100
        if dxy_chg is not None:
            strength = _strength_from_pct_change(dxy_chg, scale=0.5)
            direction = "long" if dxy_chg > 0.05 else ("short" if dxy_chg < -0.05 else "neutral")
            seta = "subindo" if dxy_chg > 0 else ("caindo" if dxy_chg < 0 else "lateral")
        else:
            # sem variação: classifica pelo nível. >104 = forte, <100 = fraco
            if dxy >= 104:
                strength, direction = min(1.0, (dxy - 103) / 3), "long"
                seta = "nível elevado"
            elif dxy <= 99:
                strength, direction = min(1.0, (100 - dxy) / 3), "short"
                seta = "nível baixo"
            else:
                strength, direction = 0.2, "neutral"
                seta = "nível neutro"

        if direction == "neutral":
            rationale = f"DXY lateral ({seta}). Sem direção clara do dólar."
        else:
            adj = "forte" if direction == "long" else "fraco"
            chg_str = f" ({dxy_chg:+.2f}%)" if dxy_chg is not None else ""
            rationale = f"Dólar {adj} — DXY {seta}{chg_str} (DXY={dxy:.2f})."
        return Signal("USD", direction, strength, rationale,
                      {"dxy": dxy, "dxy_pct": dxy_chg})


# ═════════════════════════════ VIX / RISCO ═════════════════════════════
class RiskAppetiteSignal:
    """Lê o VIX pra determinar apetite de risco.

    direction "long" = risk_on (VIX baixo), "short" = risk_off (VIX alto).
    """

    def read(self, intel: dict, vix: Optional[pd.Series]) -> Signal:
        rs = intel.get("risk_sentiment", {}) if intel else {}
        vix_now = rs.get("vix")
        vix_chg = rs.get("vix_pct_change")
        if vix_now is None:
            return Signal("RISK", rationale="VIX indisponível")
        vix_now = float(vix_now)

        # classificação por nível absoluto
        if vix_now >= C.VIX_CRISIS_ABS:
            direction, regime = "short", "crisis"
            strength = 1.0
            rationale = f"VIX {vix_now:.1f} — PÂNICO. Risk-off máximo."
        elif vix_now >= 25:
            direction, regime = "short", "risk_off"
            strength = min(1.0, (vix_now - 20) / 15)
            rationale = f"VIX {vix_now:.1f} — medo elevado, risk_off."
        elif vix_now <= 14:
            direction, regime = "long", "risk_on"
            strength = min(1.0, (16 - vix_now) / 4)
            rationale = f"VIX {vix_now:.1f} — complacência, risk_on forte."
        elif vix_now <= 18:
            direction, regime = "long", "risk_on"
            strength = (19 - vix_now) / 4
            rationale = f"VIX {vix_now:.1f} — apetite de risco saudável."
        else:
            direction, regime = "neutral", "normal"
            strength = 0.2
            rationale = f"VIX {vix_now:.1f} — neutro, sem viés de risco claro."

        # reforça se VIX está subindo rápido
        if vix_chg and abs(vix_chg) > 5:
            if vix_chg > 0 and direction != "long":
                strength = min(1.0, strength + 0.2)
                rationale += f" VIX disparando (+{vix_chg:.1f}%)."
            elif vix_chg < 0 and direction == "long":
                rationale += f" VIX caindo ({vix_chg:+.1f}%), medo diminuindo."

        return Signal("RISK", direction, strength, rationale,
                      {"vix": vix_now, "vix_pct": vix_chg, "regime_implied": regime})


# ═════════════════════════════ YIELDS / JUROS ═════════════════════════════
class YieldsSignal:
    """Lê Treasury 10y e Fed Funds pra direção dos juros.

    direction "long" = juros subindo (hawkish, fortalece USD), "short" = caindo.
    """

    def read(self, intel: dict, prices: dict) -> Signal:
        fed = intel.get("fed_rates", {}) if intel else {}
        t10 = fed.get("treasury_10y", {})
        t10_val = t10.get("valor") if isinstance(t10, dict) else None
        ff = fed.get("fed_funds_rate_diario", {})
        ff_val = ff.get("valor") if isinstance(ff, dict) else None
        if t10_val is None:
            return Signal("YIELDS", rationale="Treasury 10y indisponível")

        t10_val = float(t10_val)
        # spread 10y - fed funds = term premium (proxy de curva)
        spread = (t10_val - float(ff_val)) if ff_val is not None else None
        # sem histórico de variação no snapshot, usa nível
        if t10_val >= 4.5:
            direction, strength = "long", min(1.0, (t10_val - 4.0) / 1.5)
            rationale = f"Juros 10y em {t10_val:.2f}% — altos, viés hawkish."
        elif t10_val <= 3.5:
            direction, strength = "short", min(1.0, (4.0 - t10_val) / 1.0)
            rationale = f"Juros 10y em {t10_val:.2f}% — baixos, viés dovish."
        else:
            direction, strength = "neutral", 0.2
            rationale = f"Juros 10y em {t10_val:.2f}% — faixa neutra."
        if spread is not None:
            if spread < 0:
                rationale += f" Curva invertida ({spread:+.2f}pp) — sinal de alerta recessão."
            elif spread > 1.5:
                rationale += f" Curva íngreme ({spread:+.2f}pp) — crescimento esperado."
        return Signal("YIELDS", direction, strength, rationale,
                      {"treasury_10y": t10_val, "fed_funds": ff_val, "spread": spread})


# ═════════════════════════════ COT / FLUXO INSTITUCIONAL ═════════════════════════════
class CotFlowSignal:
    """Lê net positioning de especuladores do COT.

    direction "long" = especuladores net-long (momentum institucional).
    Para contrarian, isso seria sinal de reversão potencial.
    """

    def read(self, intel: dict, prices: dict) -> Signal:
        cot = intel.get("cot_positioning", {}) if intel else {}
        if not cot:
            return Signal("COT", rationale="COT indisponível")
        # pega o USD como proxy agregado, e detalha por moeda no detail
        usd = cot.get("USD", {})
        net = usd.get("net") if isinstance(usd, dict) else None
        if net is None:
            return Signal("COT", rationale="COT USD indisponível")
        direction = "long" if net > 0 else "short"
        strength = min(1.0, abs(net) / 50000)  # escala aproximada
        adj = "long" if net > 0 else "short"
        rationale = f"Especuladores {adj} em USD (net={net:+,.0f} contratos)."
        detail = {}
        for cur, info in cot.items():
            if isinstance(info, dict):
                detail[cur] = info.get("net")
        return Signal("COT", direction, strength, rationale, detail)


# ═════════════════════════════ MOMENTUM TÉCNICO ═════════════════════════════
class MomentumSignal:
    """Lê TS-momentum (retorno passado) por símbolo.

    Devolve um signal AGREGADO + detalhe por símbolo no detail.
    direction "long" = momentum bullish (tendência de alta).
    """

    def read(self, intel: dict, prices: dict[str, pd.DataFrame]) -> Signal:
        if not prices:
            return Signal("MOMENTUM", rationale="Preços indisponíveis")
        from .indicators import ts_momentum_signal
        detail = {}
        votes_long = votes_short = 0
        total_strength = 0.0
        for sym, df in prices.items():
            if len(df) < C.MOMENTUM_LOOKBACK_BARS:
                continue
            sig = ts_momentum_signal(df).iloc[-1]
            if not np.isfinite(sig):
                continue
            detail[sym] = float(sig)
            total_strength += abs(sig)
            if sig > C.MOMENTUM_MIN_ABS_R:
                votes_long += 1
            elif sig < -C.MOMENTUM_MIN_ABS_R:
                votes_short += 1
        n = len(detail)
        if n == 0:
            return Signal("MOMENTUM", rationale="Dados insuficientes pra momentum")
        net = votes_long - votes_short
        avg_strength = min(1.0, (total_strength / n) / 0.05) if n else 0
        if net > 0:
            direction, rationale = "long", f"Momentum de alta em {votes_long}/{n} pares."
        elif net < 0:
            direction, rationale = "short", f"Momentum de baixa em {votes_short}/{n} pares."
        else:
            direction, rationale = "neutral", f"Momentum misto ({votes_long} alta vs {votes_short} baixa)."
        return Signal("MOMENTUM", direction, avg_strength, rationale, detail)


# ═════════════════════════════ REGIME ═════════════════════════════
class RegimeSignal:
    """Lê o regime atual (RuleBasedRegime). Wrapper pra manter consistência."""

    def read(self, regime_str: Optional[str]) -> Signal:
        if not regime_str:
            return Signal("REGIME", rationale="Regime indisponível")
        scale = C.EXPOSURE_SCALE.get(regime_str, 0.5)
        if regime_str == "crisis":
            direction, strength = "short", 1.0
            rationale = "REGIME: crisis. Mercado em pânico — flat defensivo."
        elif regime_str == "risk_off":
            direction, strength = "short", 0.7
            rationale = f"REGIME: risk_off. Exposição reduzida (escala {scale})."
        elif regime_str == "risk_on":
            direction, strength = "long", 0.8
            rationale = f"REGIME: risk_on. Condições favoráveis (escala {scale})."
        else:
            direction, strength = "neutral", 0.3
            rationale = f"REGIME: normal. Mercado sem viés forte (escala {scale})."
        return Signal("REGIME", direction, strength, rationale, {"regime": regime_str, "scale": scale})


# ═════════════════════════════ NOTÍCIAS / BIAS NARRATIVO ═════════════════════════════
class NewsBiasSignal:
    """Agrega o vies das notícias classificadas pelo news_aggregator.

    direction "long" = viés bullish (risk_on/hawkish pra USD), "short" = bearish.
    """

    def read(self, news_path) -> Signal:
        import json
        from pathlib import Path
        p = Path(news_path)
        if not p.exists():
            return Signal("NEWS", rationale="Notícias não coletadas (rode o news_aggregator)")
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return Signal("NEWS", rationale="Notícias ilegíveis")
        items = data.get("noticias") if isinstance(data, dict) else None
        if not items:
            return Signal("NEWS", rationale="Nenhuma notícia relevante")
        votes = {"long": 0, "short": 0, "neutral": 0}
        top_items = []
        for it in items[:8]:
            vies = it.get("vies", "neutro")
            impacto = it.get("impacto", "baixo")
            peso = {"alto": 3, "medio": 2, "baixo": 1}.get(impacto, 1)
            # hawkish/risk_on = long (aproximação: hawkish fortalece USD)
            if vies in ("hawkish", "risk_on"):
                votes["long"] += peso
            elif vies in ("dovish", "risk_off"):
                votes["short"] += peso
            else:
                votes["neutral"] += peso
            top_items.append({"headline": it.get("headline", "")[:80], "vies": vies, "impacto": impacto})
        net = votes["long"] - votes["short"]
        total = max(1, votes["long"] + votes["short"] + votes["neutral"])
        strength = min(1.0, abs(net) / (total * 0.6)) if total else 0
        if net > 1:
            direction, rationale = "long", f"Narrativa hawkish/risk-on ({votes['long']} vs {votes['short']} votos)."
        elif net < -1:
            direction, rationale = "short", f"Narrativa dovish/risk-off ({votes['short']} vs {votes['long']} votos)."
        else:
            direction, rationale = "neutral", f"Narrativa mista ({votes['long']}L/{votes['short']}S/{votes['neutral']}N)."
        return Signal("NEWS", direction, strength, rationale, {"top": top_items})


# ═════════════════════════════ LIQUIDEZ / DOLLAR SAFE-HAVEN ═════════════════════════════
class LiquidityStressSignal:
    """Detecta quando o DÓLAR está vencendo o ouro como safe haven.

    O clássico "flight-to-liquidity": em crises onde o sistema precisa de USD
    como funding, o dólar sobe e o ouro PERDE proteção (cai junto com equities).
    Exemplos: COVID Mar/2020, crise bancária regional 2023.

    Lógica:
      - DXY SOBE forte (> DXY_LIQUIDITY_STRESS_UP_PCT)
      - VIX SOBE (> VIX_LIQUIDITY_STRESS_UP_PCT)
      - OU: DXY sobe muito forte (>2x threshold) mesmo sem VIX alto
        (dólar unilateral = stress encoberto)

    direction "short" = LIQUIDITY_STRESS ativo (reduzir exposição),
    "long" = sem stress, "neutral" = indefinido.
    """

    def read(self, intel: dict) -> Signal:
        """Lê dados de DXY e VIX do intel pra detectar stress de liquidez.

        Diferente das outras signals, NÃO precisa de série temporal — só precisa
        do snapshot mais recente de DXY %% change e VIX %% change.
        """
        rs = intel.get("risk_sentiment", {}) if intel else {}
        dxy = rs.get("dollar_index")
        dxy_chg = rs.get("dollar_index_pct_change")
        vix_chg = rs.get("vix_pct_change")

        if dxy is None or dxy_chg is None:
            return Signal("LIQUIDITY", rationale="DXY indisponível pra detectar stress")

        dxy_chg = float(dxy_chg)
        vix_chg = float(vix_chg) if vix_chg is not None else 0.0

        # ── Sinal 1: DXY subindo + VIX subindo = flight-to-liquidity clássico ──
        dxy_up = dxy_chg >= C.DXY_LIQUIDITY_STRESS_UP_PCT
        vix_up = vix_chg >= C.VIX_LIQUIDITY_STRESS_UP_PCT

        # ── Sinal 2: DXY subindo MUITO forte (unilateral) = stress mesmo sem VIX ──
        dxy_very_strong = dxy_chg >= C.DXY_LIQUIDITY_STRESS_UP_PCT * 2

        if dxy_up and vix_up:
            # Stress confirmado: dólar + medo subindo juntos
            strength = min(1.0, abs(dxy_chg) / (C.DXY_LIQUIDITY_STRESS_UP_PCT * 2))
            rationale = (
                f"🚨 STRESS DE LIQUIDEZ: DXY subindo {dxy_chg:+.2f}% + "
                f"VIX subindo {vix_chg:+.1f}%. Flight-to-dollar ativo. "
                f"Ouro PERDE proteção neste cenário."
            )
            direction = "short"
        elif dxy_very_strong:
            # Stress parcial: dólar subindo forte demais mesmo sem medo explícito
            strength = min(0.6, abs(dxy_chg) / (C.DXY_LIQUIDITY_STRESS_UP_PCT * 3))
            rationale = (
                f"⚠️ DXY subindo forte ({dxy_chg:+.2f}%) sem confirmação do VIX. "
                f"Possível stress de liquidez encoberto."
            )
            direction = "short"
        elif dxy_chg <= -C.DXY_LIQUIDITY_STRESS_UP_PCT and vix_chg > C.VIX_LIQUIDITY_STRESS_UP_PCT:
            # DXY caindo + VIX subindo = pânico NÃO direcionado ao dólar
            # Isso é ouro-safe-haven clássico: VIX sobe mas dólar não é o refúgio
            strength = min(0.5, abs(vix_chg) / (C.VIX_LIQUIDITY_STRESS_UP_PCT * 2))
            rationale = (
                f"VIX subindo ({vix_chg:+.1f}%) mas DXY caindo ({dxy_chg:+.2f}%). "
                f"Pânico SEM flight-to-dollar — ouro mantém proteção."
            )
            direction = "long"  # sem stress de liquidez, ouro safe haven intacto
        else:
            return Signal("LIQUIDITY", direction="neutral", strength=0.0,
                          rationale="Sem stress de liquidez detectado.",
                          detail={"dxy_pct": dxy_chg, "vix_pct": vix_chg})

        return Signal("LIQUIDITY", direction, strength, rationale, {
            "dxy_pct": dxy_chg,
            "vix_pct": vix_chg,
            "dxy_up": dxy_up,
            "vix_up": vix_up,
            "dxy_very_strong": dxy_very_strong,
            "stress_active": direction == "short",
        })


__all__ = [
    "Signal", "DollarSignal", "RiskAppetiteSignal", "YieldsSignal",
    "CotFlowSignal", "MomentumSignal", "RegimeSignal", "NewsBiasSignal",
    "LiquidityStressSignal",
]
