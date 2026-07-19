"""
autonomous_oracle.py — ORÁCULO AUTÔNOMO DE MACROECONOMIA
=========================================================
Entende o sistema macroeconômico GLOBAL em tempo real.

CAPACIDADES:
  1. Análise Intermarket: DXY, VIX, Treasuries, Commodities, Equities, Credit
  2. Ciclos de Liquidez Global: Detecção de expansão/contração monetária
  3. Regime Detection com Memória: Aprende com regimes passados
  4. Correlação Cross-Asset: Rastreia mudanças nas correlações entre ativos
  5. Geração de Tese via LLM: Resumo macro em português com recomendação
  6. Pontuação de Risco Multi-fator: Combina TODOS os drivers num score único
  7. Detecção de Regime Change: Identifica MUDANÇAS de regime em tempo real

Fluxo:
  oracle = AutonomousOracle()
  snapshot = oracle.analyze(intel, prices, news)
  # snapshot.conclusion = "Mercado em risk_off com USD forte... XAUUSD sob pressão..."
  # snapshot.regime = "risk_off"
  # snapshot.risk_score = 35
  # snapshot.thesis = {...tese completa em PT...}
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from . import config as C
from .macro_analysis import analyze_market, MarketSnapshot, AssetView
from .macro_signals import Signal

# ── Paths ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOT_DIR = PROJECT_ROOT / "bot"
STATE_PATH = BOT_DIR / "bot_state.json"
ORACLE_STATE_KEY = "autonomous_oracle"


# ═════════════════════════════ DATA CLASSES ═════════════════════════════

@dataclass
class MacroThesis:
    """Tese macro completa gerada pelo oráculo."""
    summary_pt: str                          # Resumo em português (1 parágrafo)
    regime: str                              # risk_on | normal | risk_off | crisis
    risk_score: int                          # 0-100 (0=risco máximo, 100=segurança)
    primary_driver: str                      # O que está movendo o mercado agora
    secondary_drivers: list[str]             # Drivers secundários
    asset_allocation: dict[str, str]         # {symbol: "long"|"short"|"neutral"|"avoid"}
    alerts: list[str]                        # Alertas críticos
    confidence: int                          # 0-100
    timestamp: str = ""


@dataclass
class RegimeMemory:
    """Memória de regimes passados para o oráculo aprender."""
    regime_history: list[dict] = field(default_factory=list)
    performance_by_regime: dict[str, dict] = field(default_factory=dict)
    regime_transitions: list[dict] = field(default_factory=list)
    last_regime: str = "unknown"
    regime_duration_hours: dict[str, int] = field(default_factory=dict)

    def record_regime(self, regime: str, vix: float, dxy: float):
        """Registra o regime atual no histórico."""
        now = datetime.now(timezone.utc)
        entry = {
            "timestamp": now.isoformat(),
            "regime": regime,
            "vix": vix,
            "dxy": dxy,
        }
        self.regime_history.append(entry)
        if len(self.regime_history) > 1000:
            self.regime_history = self.regime_history[-500:]

        # Duração do regime
        if regime == self.last_regime:
            self.regime_duration_hours[regime] = self.regime_duration_hours.get(regime, 0) + 1
        else:
            if self.last_regime != "unknown" and self.last_regime != regime:
                self.regime_transitions.append({
                    "from": self.last_regime,
                    "to": regime,
                    "timestamp": now.isoformat(),
                })
            self.regime_duration_hours[regime] = 1
        self.last_regime = regime

    def is_regime_change(self, threshold_hours: int = 24) -> bool:
        """Detecta se houve mudança de regime nas últimas N horas."""
        if not self.regime_transitions:
            return False
        last = self.regime_transitions[-1]
        try:
            dt = datetime.fromisoformat(last["timestamp"])
            delta = datetime.now(timezone.utc) - dt
            return delta.total_seconds() < threshold_hours * 3600
        except Exception:
            return False

    def record_performance(self, regime: str, trade_result: dict):
        """Registra performance de um trade no regime em que foi aberto."""
        if regime not in self.performance_by_regime:
            self.performance_by_regime[regime] = {
                "trades": 0, "wins": 0, "losses": 0,
                "total_pnl": 0.0, "avg_rr": 0.0, "rr_sum": 0.0,
            }
        perf = self.performance_by_regime[regime]
        perf["trades"] += 1
        pnl = trade_result.get("pnl_usd", 0)
        rr = trade_result.get("rr_realized", 0)
        if pnl > 0:
            perf["wins"] += 1
        else:
            perf["losses"] += 1
        perf["total_pnl"] += pnl
        perf["rr_sum"] += rr
        perf["avg_rr"] = perf["rr_sum"] / perf["trades"] if perf["trades"] > 0 else 0.0

    def get_best_regime(self) -> Optional[str]:
        """Retorna o regime com melhor performance histórica."""
        best = None
        best_win_rate = 0.0
        for regime, perf in self.performance_by_regime.items():
            if perf["trades"] >= 5:
                wr = perf["wins"] / perf["trades"] if perf["trades"] > 0 else 0
                if wr > best_win_rate:
                    best_win_rate = wr
                    best = regime
        return best

    def to_dict(self) -> dict:
        return {
            "regime_history": self.regime_history[-100:],
            "performance_by_regime": self.performance_by_regime,
            "regime_transitions": self.regime_transitions[-20:],
            "last_regime": self.last_regime,
            "regime_duration_hours": self.regime_duration_hours,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RegimeMemory:
        rm = cls()
        rm.regime_history = data.get("regime_history", [])
        rm.performance_by_regime = data.get("performance_by_regime", {})
        rm.regime_transitions = data.get("regime_transitions", [])
        rm.last_regime = data.get("last_regime", "unknown")
        rm.regime_duration_hours = data.get("regime_duration_hours", {})
        return rm


@dataclass
class IntermarketSnapshot:
    """Snapshot completo das relações intermarket atuais."""
    dollar: dict = field(default_factory=dict)        # DXY analysis
    risk: dict = field(default_factory=dict)           # VIX analysis
    yields: dict = field(default_factory=dict)          # Treasury yields
    commodities: dict = field(default_factory=dict)     # Gold, Oil
    equities: dict = field(default_factory=dict)        # SPY, global indices
    credit: dict = field(default_factory=dict)          # Credit spreads (proxy)
    correlations: dict = field(default_factory=dict)    # Cross-asset correlations
    global_liquidity: dict = field(default_factory=dict) # Global liquidity cycle
    timestamp: str = ""


@dataclass
class OracleSnapshot:
    """Resultado completo da análise do oráculo."""
    thesis: MacroThesis
    intermarket: IntermarketSnapshot
    regime_memory: RegimeMemory
    market_snapshot: Optional[MarketSnapshot] = None
    alerts: list[str] = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)


# ═════════════════════════════ GLOBAL LIQUIDITY ANALYSIS ═════════════════════════════

class GlobalLiquidityAnalyzer:
    """Analisa o ciclo de liquidez global.
    
    Monitora:
    - Fed Funds Rate trajectory
    - DXY (proxy de liquidez USD global)
    - Gold (proxy de liquidez real / hedge)
    - Real yields
    """

    def analyze(self, intel: dict) -> dict:
        """Retorna análise do ciclo de liquidez global."""
        result = {"liquidity_cycle": "neutral", "details": {}, "score": 50}

        if not intel:
            return result

        fed = intel.get("fed_rates", {})
        dxy_data = intel.get("risk_sentiment", {})

        # Fed policy stance (proxy via rate level)
        ff_rate = None
        if isinstance(fed.get("fed_funds_rate_diario"), dict):
            ff_rate = fed["fed_funds_rate_diario"].get("valor")
        
        if ff_rate is not None:
            ff_rate = float(ff_rate)
            if ff_rate <= 1.0:
                result["liquidity_cycle"] = "expansionary"
                result["score"] = 80
                result["details"]["fed_stance"] = "Dovish / Expansionary"
            elif ff_rate <= 3.0:
                result["liquidity_cycle"] = "neutral_accommodative"
                result["score"] = 60
                result["details"]["fed_stance"] = "Mildly accommodative"
            elif ff_rate <= 5.0:
                result["liquidity_cycle"] = "neutral_tight"
                result["score"] = 40
                result["details"]["fed_stance"] = "Mildly restrictive"
            else:
                result["liquidity_cycle"] = "tight"
                result["score"] = 20
                result["details"]["fed_stance"] = "Restrictive / Tight"

        # Treasury 10y real yield proxy
        t10 = fed.get("treasury_10y", {})
        if isinstance(t10, dict):
            t10_val = t10.get("valor")
            if t10_val is not None:
                t10_val = float(t10_val)
                real_yield = t10_val - (ff_rate or 0)
                result["details"]["real_yield_proxy"] = round(real_yield, 2)
                if real_yield > 2.0:
                    result["liquidity_cycle"] = "tight"
                    result["score"] = min(result["score"], 20)
                    result["details"]["liquidity_note"] = "Real yields altos = liquidez contraindo"
                elif real_yield < -1.0:
                    result["liquidity_cycle"] = "expansionary"
                    result["score"] = max(result["score"], 70)

        # DXY trend
        dxy = dxy_data.get("dollar_index")
        if dxy is not None:
            result["details"]["dxy"] = float(dxy)
            if float(dxy) > 105:
                result["details"]["dollar_liquidity"] = "USD scarcity (DXY alto = liquidez USD contraindo)"
                result["score"] = max(10, result["score"] - 15)
            elif float(dxy) < 98:
                result["details"]["dollar_liquidity"] = "USD abundante (DXY baixo = liquidez USD expansionando)"
                result["score"] = min(90, result["score"] + 15)

        return result


# ═════════════════════════════ CROSS-ASSET CORRELATION ═════════════════════════════

class CrossAssetCorrelator:
    """Rastreia correlações entre ativos para detectar mudanças de regime.
    
    Lógica:
    - Correlação ouro/ações: negativa = risk_on genuíno; positiva = regime misto
    - Correlação USD/ouro: negativa = normal; positiva = stress
    - Correlação VIX/SPY: negativa forte = medo
    """

    def analyze(self, intel: dict) -> dict:
        """Analisa correlações intermarket atuais."""
        result = {
            "gold_equity_correlation": None,
            "dollar_gold_correlation": None,
            "regime_correlation_signal": "neutral",
            "details": {},
        }

        if not intel:
            return result

        # Gold-equity correlation (vem do intelligence ou calculamos)
        ge_corr = intel.get("gold_equity_correlation")
        if ge_corr is not None:
            ge_corr = float(ge_corr)
            result["gold_equity_correlation"] = ge_corr
            if ge_corr < -0.3:
                result["regime_correlation_signal"] = "risk_on_genuine"
                result["details"]["ge_note"] = "Gold c/ ações = RISK_ON genuíno. Capital saindo de safe haven."
            elif ge_corr > 0.3:
                result["regime_correlation_signal"] = "correlated_market"
                result["details"]["ge_note"] = "Ouro e ações andam juntos — driver comum (USD/inflação)."
            elif ge_corr > 0.6:
                result["regime_correlation_signal"] = "panic"
                result["details"]["ge_note"] = "⚠️ TUDO CORRELACIONADO — potencial pânico generalizado."
            else:
                result["regime_correlation_signal"] = "normal"

        # VIX level and trend
        rs = intel.get("risk_sentiment", {})
        vix = rs.get("vix")
        if vix is not None:
            vix = float(vix)
            result["details"]["vix"] = vix
            vix_chg = rs.get("vix_pct_change")
            if vix_chg is not None and abs(float(vix_chg)) > 3:
                result["details"]["vix_momentum"] = f"VIX movendo {float(vix_chg):+.1f}%"

        return result


# ═════════════════════════════ MACRO THESIS GENERATOR ═════════════════════════════

class MacroThesisGenerator:
    """Gera tese macro em português usando o LLM local."""

    THESIS_PROMPT = """You are a senior macro strategist at a global hedge fund.

Based on the data below, generate a concise MACRO THESIS in PORTUGUESE (Brazilian).
The thesis must be actionable for a systematic trend-following strategy trading XAUUSD.

DATA:
- Regime: {regime}
- Risk Score: {risk_score}/100
- VIX: {vix} (change: {vix_chg}%)
- DXY: {dxy} (change: {dxy_chg}%)
- Gold-Equity Correlation: {ge_corr}
- Treasury 10y: {t10}
- Fed Funds: {ff}
- Liquidity Cycle: {liquidity_cycle}
- {liquidity_detail}

TOP DRIVERS:
{drivers}

ALERTS:
{alerts}

INSTRUCTIONS:
1. Write 2-3 paragraphs in Portuguese explaining what is moving the market
2. State clearly: is this favorable or unfavorable for XAUUSD (gold)?
3. Include the PRIMARY DRIVER and how it affects gold
4. Mention RISKS to this thesis
5. Be direct and honest - if data is mixed, say it's mixed

Your output must be valid JSON:
{{"summary_pt": "2-3 paragraphs in PT-BR", "primary_driver": "main driver name", "secondary_drivers": ["driver2", "driver3"], "confidence": 0-100, "recommendation": "long_gold"|"short_gold"|"neutral_gold"|"avoid_gold", "risks": ["risk1", "risk2"]}}
"""

    def __init__(self):
        self.ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self.ollama_model = os.environ.get("META_LLM_MODEL", "gemma4-opt:latest")

    def generate(self, context: dict) -> Optional[dict]:
        """Gera tese macro via LLM."""
        try:
            import requests
            
            # Formata drivers
            drivers_text = "\n".join(
                f"  - {d.get('driver','?')}: {d.get('direction','neutral')} (strength={d.get('strength',0):.2f})"
                for d in context.get("drivers", [])[:5]
            ) if context.get("drivers") else "  (no data)"

            alerts_text = "\n".join(f"  - {a}" for a in context.get("alerts", [])[:5]) if context.get("alerts") else "  (none)"

            prompt = self.THESIS_PROMPT.format(
                regime=context.get("regime", "unknown"),
                risk_score=context.get("risk_score", 50),
                vix=context.get("vix", "N/A"),
                vix_chg=context.get("vix_chg", "N/A"),
                dxy=context.get("dxy", "N/A"),
                dxy_chg=context.get("dxy_chg", "N/A"),
                ge_corr=context.get("ge_corr", "N/A"),
                t10=context.get("t10", "N/A"),
                ff=context.get("ff", "N/A"),
                liquidity_cycle=context.get("liquidity_cycle", "neutral"),
                liquidity_detail=context.get("liquidity_detail", ""),
                drivers=drivers_text,
                alerts=alerts_text,
            )

            resp = requests.post(
                f"{self.ollama_host}/api/generate",
                json={"model": self.ollama_model, "prompt": prompt, "stream": False,
                      "options": {"temperature": 0.3, "num_predict": 1024}},
                timeout=None,
            )
            if resp.status_code == 200:
                raw = resp.json().get("response", "").strip()
                raw = raw.replace("```json", "").replace("```", "").strip()
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    # Fallback: extract JSON from text
                    import re
                    match = re.search(r'\{[^{}]*"summary_pt"[^{}]*\}', raw)
                    if match:
                        return json.loads(match.group())
            return None
        except Exception as e:
            print(f"[Oracle] Thesis generation error: {type(e).__name__}: {e}")
            return None


# ═════════════════════════════ CORE ORACLE ═════════════════════════════

class AutonomousOracle:
    """Oráculo autônomo que entende o sistema macroeconômico global."""

    def __init__(self):
        self.regime_memory = self._load_regime_memory()
        self.liquidity_analyzer = GlobalLiquidityAnalyzer()
        self.correlator = CrossAssetCorrelator()
        self.thesis_generator = MacroThesisGenerator()

    def _load_regime_memory(self) -> RegimeMemory:
        """Carrega memória de regimes do arquivo de estado."""
        if STATE_PATH.exists():
            try:
                data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                oracle_data = data.get(ORACLE_STATE_KEY, {})
                if oracle_data:
                    return RegimeMemory.from_dict(oracle_data.get("regime_memory", {}))
            except Exception:
                pass
        return RegimeMemory()

    def _save_regime_memory(self):
        """Persiste memória de regimes."""
        try:
            if STATE_PATH.exists():
                data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            else:
                data = {}
            if ORACLE_STATE_KEY not in data:
                data[ORACLE_STATE_KEY] = {}
            data[ORACLE_STATE_KEY]["regime_memory"] = self.regime_memory.to_dict()
            STATE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def analyze(self, intel: dict, prices: dict[str, pd.DataFrame] = None,
                news_path: Optional[Path] = None) -> OracleSnapshot:
        """Executa análise macro completa."""
        alerts = []
        now = datetime.now(timezone.utc)

        # ── 1. Análise Intermarket ──
        intermarket = IntermarketSnapshot()
        
        # DXY
        rs = intel.get("risk_sentiment", {}) if intel else {}
        dxy = rs.get("dollar_index")
        dxy_chg = rs.get("dollar_index_pct_change")
        intermarket.dollar = {
            "dxy": float(dxy) if dxy else None,
            "change_pct": float(dxy_chg) if dxy_chg else None,
            "trend": "up" if (dxy_chg and float(dxy_chg) > 0.1) else ("down" if (dxy_chg and float(dxy_chg) < -0.1) else "neutral"),
        }

        # VIX/Risk
        vix = rs.get("vix")
        vix_chg = rs.get("vix_pct_change")
        intermarket.risk = {
            "vix": float(vix) if vix else None,
            "change_pct": float(vix_chg) if vix_chg else None,
            "trend": "up" if (vix_chg and float(vix_chg) > 3) else ("down" if (vix_chg and float(vix_chg) < -3) else "neutral"),
        }

        # Yields
        fed = intel.get("fed_rates", {}) if intel else {}
        t10 = fed.get("treasury_10y", {})
        if isinstance(t10, dict):
            intermarket.yields = {
                "treasury_10y": t10.get("valor"),
                "fed_funds": fed.get("fed_funds_rate_diario", {}).get("valor") if isinstance(fed.get("fed_funds_rate_diario"), dict) else None,
            }

        # Global Liquidity
        intermarket.global_liquidity = self.liquidity_analyzer.analyze(intel)

        # Correlations
        intermarket.correlations = self.correlator.analyze(intel)

        # ── 2. Cross-asset snapshot via macro_analysis ──
        try:
            snapshot = analyze_market(intel, prices or {}, regime_str=None, news_path=news_path)
        except Exception as e:
            print(f"[Oracle] macro_analysis error: {e}")
            snapshot = None

        # ── 3. Determina Regime ──
        regime = snapshot.regime if snapshot else "normal"
        vix_val = float(vix) if vix else 25.0
        dxy_val = float(dxy) if dxy else 100.0
        
        # Override de regime baseado em análise mais profunda
        liq_cycle = intermarket.global_liquidity.get("liquidity_cycle", "neutral")
        if liq_cycle == "tight" and vix_val > 25:
            regime = "crisis"
        elif liq_cycle == "tight" and vix_val > 20:
            regime = "risk_off"
        
        # Correlação gold-equity como confirmador
        corr_signal = intermarket.correlations.get("regime_correlation_signal", "neutral")
        if corr_signal == "panic" and regime != "crisis":
            regime = "risk_off"
            alerts.append("🚨 Cross-asset panic signal: all assets correlated")

        self.regime_memory.record_regime(regime, vix_val, dxy_val)

        # ── 4. Calcula Risk Score Multi-fator ──
        risk_score = 50  # base neutral

        # Fator VIX
        if vix_val <= 14:
            risk_score += 20
        elif vix_val <= 18:
            risk_score += 10
        elif vix_val >= 30:
            risk_score -= 30
        elif vix_val >= 25:
            risk_score -= 15

        # Fator Liquidez
        liq_score = intermarket.global_liquidity.get("score", 50)
        risk_score = (risk_score + liq_score) // 2

        # Fator Correlação
        if corr_signal == "panic":
            risk_score -= 20
        elif corr_signal == "risk_on_genuine":
            risk_score += 10

        risk_score = max(0, min(100, risk_score))

        # ── 5. Gera Alertas ──
        if snapshot:
            alerts.extend(snapshot.alerts)
        
        # Alertas do oráculo
        if regime == "crisis":
            alerts.append("🔴 REGIME CRISIS DETECTED: Múltiplos fatores confirmam pânico")
        elif self.regime_memory.is_regime_change(threshold_hours=24):
            alerts.append("⚡ Regime change detected within last 24h")
        
        if intermarket.global_liquidity.get("liquidity_cycle") == "tight":
            alerts.append("💧 Liquidez global contraindo (juros altos + USD forte)")
        
        if intermarket.correlations.get("gold_equity_correlation") and abs(float(intermarket.correlations.get("gold_equity_correlation", 0))) > 0.5:
            alerts.append(f"📊 Gold-equity correlation = {float(intermarket.correlations['gold_equity_correlation']):.2f} (regime incomum)")

        # ── 6. Gera Tese via LLM ──
        thesis_context = {
            "regime": regime,
            "risk_score": risk_score,
            "vix": vix_val,
            "vix_chg": vix_chg or 0,
            "dxy": dxy_val,
            "dxy_chg": dxy_chg or 0,
            "ge_corr": intermarket.correlations.get("gold_equity_correlation", "N/A"),
            "t10": intermarket.yields.get("treasury_10y", "N/A"),
            "ff": intermarket.yields.get("fed_funds", "N/A"),
            "liquidity_cycle": intermarket.global_liquidity.get("liquidity_cycle", "neutral"),
            "liquidity_detail": intermarket.global_liquidity.get("details", {}).get("liquidity_note", ""),
            "drivers": [{"driver": d.driver, "direction": d.direction, "strength": d.strength}
                       for d in (snapshot.drivers if snapshot else [])],
            "alerts": alerts,
        }

        llm_thesis = self.thesis_generator.generate(thesis_context)

        # ── 7. Monta tese final (com fallback se LLM falhar) ──
        if llm_thesis:
            thesis = MacroThesis(
                summary_pt=llm_thesis.get("summary_pt", "Análise macro indisponível."),
                regime=regime,
                risk_score=risk_score,
                primary_driver=llm_thesis.get("primary_driver", "Desconhecido"),
                secondary_drivers=llm_thesis.get("secondary_drivers", []),
                asset_allocation=llm_thesis.get("asset_allocation", {}),
                alerts=alerts,
                confidence=llm_thesis.get("confidence", 50),
                timestamp=now.isoformat(),
            )
        else:
            # Fallback sem LLM
            thesis = MacroThesis(
                summary_pt=self._fallback_thesis(regime, risk_score, dxy_val, vix_val),
                regime=regime,
                risk_score=risk_score,
                primary_driver="Análise Quantitativa (LLM indisponível)",
                secondary_drivers=[],
                asset_allocation=self._fallback_allocation(regime),
                alerts=alerts,
                confidence=60,
                timestamp=now.isoformat(),
            )

        self._save_regime_memory()

        return OracleSnapshot(
            thesis=thesis,
            intermarket=intermarket,
            regime_memory=self.regime_memory,
            market_snapshot=snapshot,
            alerts=alerts,
            raw_data={
                "vix": vix_val, "dxy": dxy_val,
                "risk_score": risk_score, "regime": regime,
                "liquidity_cycle": intermarket.global_liquidity.get("liquidity_cycle"),
            }
        )

    def _fallback_thesis(self, regime: str, risk_score: int, dxy: float, vix: float) -> str:
        """Tese de fallback quando LLM está indisponível."""
        parts = []
        if regime == "crisis":
            parts.append("🚨 REGIME CRISE: Múltiplos indicadores apontam pânico de mercado. "
                         f"VIX={vix:.1f} (elevado). Recomendação: FLAT — não operar até normalização.")
        elif regime == "risk_off":
            parts.append(f"⚠️ RISK_OFF: Mercado cauteloso (VIX={vix:.1f}). "
                         "Reduzir exposição, stops mais apertados. "
                         f"USD pode estar funcionando como safe haven (DXY={dxy:.1f}).")
        elif regime == "risk_on":
            parts.append(f"✅ RISK_ON: Ambiente favorável (VIX={vix:.1f}). "
                         "Apetite de risco saudável. "
                         "Tendências podem se estender.")
        else:
            parts.append(f"⚖️ REGIME NEUTRO: Mercado sem viés claro. "
                         f"VIX={vix:.1f}, DXY={dxy:.1f}. "
                         "Operar normalmente, stops padrão.")

        parts.append(f"Score de Risco: {risk_score}/100 "
                     f"({'Alto risco' if risk_score < 30 else 'Risco moderado' if risk_score < 60 else 'Risco baixo'}).")
        return " ".join(parts)

    def _fallback_allocation(self, regime: str) -> dict[str, str]:
        """Alocação sugerida por regime."""
        base = {"XAUUSDm": "long"}
        if regime == "crisis":
            return {"XAUUSDm": "avoid"}
        elif regime == "risk_off":
            return {"XAUUSDm": "neutral"}
        elif regime == "risk_on":
            return {"XAUUSDm": "long"}
        return {"XAUUSDm": "long"}


__all__ = [
    "AutonomousOracle", "OracleSnapshot", "MacroThesis",
    "RegimeMemory", "IntermarketSnapshot",
    "MacroThesisGenerator",
]
