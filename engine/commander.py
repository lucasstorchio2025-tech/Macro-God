"""
commander.py — COMANDANTE AUTÔNOMO (IA CENTRAL)
=================================================
A IA que COMANDAR TUDO. O cérebro do sistema.

A Commander:
  1. Recebe dados de TODAS as fontes (oracle, evolution, meta, MT5)
  2. DECIDE: qual estratégia usar, quanto arriscar, quando operar
  3. ORQUESTRA: AutonomousOracle + SelfEvolutionEngine + meta_learner
  4. APRENDE: cada decisão é registrada e analisada
  5. ACELERA: identifica gargalos e otimiza performance
  6. PROTEGE: detecta falhas e ativa modos de segurança

Fluxo:
  commander = AutonomousCommander()
  order = commander.decide(intel, prices, meta, mt5_connection)
  # order = {"action": "open_trade"|"close_trade"|"wait",
  #          "symbol": "XAUUSDm", "direction": "BUY"|"SELL",
  #          "risk_pct": 5.0, "stop_atr_mult": 1.5,
  #          "reasoning": "AI reasoning text"}
  
  commander.learn(trade_result)
  # Sistema aprende com o resultado e evolui sozinho
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import numpy as np

from . import config as C
from .autonomous_oracle import AutonomousOracle, OracleSnapshot, MacroThesis
from .self_evolution import SelfEvolutionEngine, PerformanceAnalyzer, STRATEGY_REGISTRY
from .meta_config import MetaState, load_meta_state, save_meta_state
from .meta_learner import consult_llm, health_check_kill_switch

# ── Paths ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOT_DIR = PROJECT_ROOT / "bot"
STATE_PATH = BOT_DIR / "bot_state.json"
DECISION_LOG_PATH = BOT_DIR / "decision_log.jsonl"
COMMANDER_STATE_KEY = "autonomous_commander"


# ═════════════════════════════ COMMANDER ORDER ═════════════════════════════

@dataclass
class CommanderOrder:
    """Ordem emitida pela IA central."""
    action: str                           # "trade" | "wait" | "close_all" | "reduce_risk" | "pause"
    symbol: str = ""
    direction: str = ""                   # "BUY" | "SELL" | ""
    risk_pct: float = 0.0                # % do saldo para arriscar
    stop_atr_mult: float = 1.5           # Multiplicador ATR para stop
    size_frac: float = 0.0               # Fração do tamanho máximo
    rr_target: float = 2.0               # Alvo RR
    reasoning: str = ""                   # Raciocínio completo da IA
    confidence: float = 0.0              # 0-1
    primary_driver: str = ""
    selected_strategy: str = "ts_momentum"
    regime: str = "normal"
    risk_multiplier: float = 1.0
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "action": self.action, "symbol": self.symbol,
            "direction": self.direction, "risk_pct": self.risk_pct,
            "stop_atr_mult": self.stop_atr_mult, "size_frac": self.size_frac,
            "rr_target": self.rr_target, "reasoning": self.reasoning[:500],
            "confidence": self.confidence,
            "primary_driver": self.primary_driver,
            "selected_strategy": self.selected_strategy,
            "regime": self.regime, "risk_multiplier": self.risk_multiplier,
            "timestamp": self.timestamp,
        }


@dataclass
class CommanderDecisionContext:
    """Contexto completo para a decisão da IA."""
    oracle: Optional[OracleSnapshot] = None
    meta: Optional[MetaState] = None
    evolution: Optional[dict] = None
    signals: dict = field(default_factory=dict)
    signal_details: dict = field(default_factory=dict)
    balance: float = 0.0
    open_positions: int = 0
    open_symbols: set = field(default_factory=set)
    last_trades: list = field(default_factory=list)
    timestamp: str = ""


# ═════════════════════════════ COMMAND DECISION ENGINE ═════════════════════════════

class CommanderDecisionEngine:
    """Motor de decisão da IA central."""

    def __init__(self):
        self.ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self.ollama_model = os.environ.get("META_LLM_MODEL", "gemma4-opt:latest")

    DECISION_PROMPT = """You are an autonomous trading AI COMMANDER.

You have complete authority over trading decisions. Your goal is to maximize risk-adjusted returns.

CONTEXT:
- Regime: {regime}
- Risk Score: {risk_score}/100
- VIX: {vix} | DXY: {dxy}
- Balance: ${balance}
- Open Positions: {open_positions}/{max_positions}
- Open Symbols: {open_symbols}
- Risk Multiplier (meta): {risk_mult}
- Selected Strategy: {strategy}

MACRO THESIS:
{macro_thesis}

SIGNALS AVAILABLE:
{signals}

ALERTS:
{alerts}

RECENT PERFORMANCE:
{performance}

PERFORMANCE BY REGIME:
{regime_performance}

EVOLUTION STATUS:
{evolution_status}

DECISION RULES:
1. If regime is "crisis" OR risk_score < 20 → action MUST be "wait"
2. If no clear signal → action MUST be "wait"  
3. If already at max positions → action MUST be "wait"
4. If macro thesis says avoid gold → action MUST be "wait"
5. Risk pct should be adjusted by regime and confidence
6. size_frac: 1.0 = full size, 0.5 = half size, etc.

RESPOND WITH VALID JSON ONLY:
{{{{
  "action": "trade"|"wait"|"close_all"|"reduce_risk",
  "symbol": "XAUUSDm",
  "direction": "BUY"|"SELL"|"",
  "risk_pct": 5.0,
  "size_frac": 0.8,
  "stop_atr_mult": 1.5,
  "rr_target": 2.0,
  "selected_strategy": "ts_momentum",
  "confidence": 0.7,
  "primary_driver": "main driver name",
  "reasoning": "2-3 sentences explaining this decision"
}}}}
"""

    def decide(self, ctx: CommanderDecisionContext, skip_llm: bool = False) -> CommanderOrder:
        """IA toma decisão baseada em TODO o contexto disponível.
        
        Args:
            ctx: Contexto completo da decisão
            skip_llm: Se True, NAO consulta o LLM (evita dupla chamada)
        """
        now = datetime.now(timezone.utc)
        oracle = ctx.oracle
        meta = ctx.meta

        # ── 1. Extrai contexto ──
        regime = oracle.thesis.regime if oracle else "normal"
        risk_score = oracle.thesis.risk_score if oracle else 50
        vix = oracle.raw_data.get("vix", 25) if oracle else 25
        dxy = oracle.raw_data.get("dxy", 100) if oracle else 100
        alerts = oracle.alerts if oracle else []
        thesis_text = oracle.thesis.summary_pt if oracle else ""
        
        meta_rm = meta.get_risk_multiplier() if meta else 1.0

        # ── 2. Sinais disponíveis ──
        signals_text = "\n".join(
            f"  {sym}: {sig[0] if isinstance(sig, tuple) else sig} "
            f"(frac={sig[1] if isinstance(sig, tuple) else 'N/A'})"
            for sym, sig in ctx.signals.items()
        ) if ctx.signals else "  (none)"

        # ── 3. Performance por regime ──
        regime_perf = ""
        if oracle and oracle.regime_memory:
            perf = oracle.regime_memory.performance_by_regime
            regime_perf = "\n".join(
                f"  {r}: {p['trades']} trades, WR={p['wins']/max(1,p['trades']):.0%}, "
                f"PnL=${p['total_pnl']:.2f}"
                for r, p in perf.items() if p['trades'] >= 3
            )

        # ── 4. Últimos trades para performance ──
        perf_text = ""
        if ctx.last_trades:
            recent = ctx.last_trades[-10:]
            pf = "N/A"
            pnls = [t.get("payload", {}).get("profit", 0) for t in recent if t.get("payload", {}).get("profit", 0) != 0]
            if pnls:
                wins = sum(1 for p in pnls if p > 0)
                losses = sum(1 for p in pnls if p < 0)
                total = sum(pnls)
                perf_text = f"Last {len(pnls)} trades: {wins}W/{losses}L, Total=${total:.2f}"
        
        # ── 5. Evolution status ──
        evo_text = ""
        if ctx.evolution:
            changes = ctx.evolution.get("parameter_changes", [])
            strategy = ctx.evolution.get("strategy_selection", {})
            if changes:
                evo_text = f"Recent changes: {len(changes)} params, Strategy: {list(strategy.keys()) if strategy else 'ts_momentum'}"

        # ── 6. REGRAS DE SEGURANÇA (sempre executadas, mesmo sem LLM) ──
        
        # Regra 1: Crisis = WAIT
        if regime == "crisis" or risk_score < 20:
            return CommanderOrder(
                action="close_all" if ctx.open_positions > 0 else "wait",
                reasoning=f"🚨 CRISIS / RISK_SCORE={risk_score}. Fechando posições. {thesis_text[:200]}",
                confidence=0.95, regime=regime, risk_multiplier=0.0,
                timestamp=now.isoformat(),
            )

        # Regra 2: Risk_off com score muito baixo = REDUCE
        if regime == "risk_off" and risk_score < 35:
            if ctx.open_positions > 0:
                return CommanderOrder(
                    action="wait",
                    reasoning=f"⚠️ Risk_off severo (score={risk_score}). Mantendo flat. {thesis_text[:200]}",
                    confidence=0.8, regime=regime, risk_multiplier=meta_rm * 0.5,
                    timestamp=now.isoformat(),
                )
            return CommanderOrder(
                action="wait",
                reasoning=f"⚠️ Risk_off (score={risk_score}). Sem posições. Aguardando melhora.",
                confidence=0.7, regime=regime, risk_multiplier=meta_rm * 0.5,
                timestamp=now.isoformat(),
            )

        # Regra 3: Max positions = WAIT
        if ctx.open_positions >= C.MAX_OPEN_POSITIONS:
            return CommanderOrder(
                action="wait",
                reasoning=f"Max positions ({ctx.open_positions}/{C.MAX_OPEN_POSITIONS}) reached.",
                confidence=1.0, regime=regime, risk_multiplier=meta_rm,
                timestamp=now.isoformat(),
            )

        # Regra 4: Sem sinal = WAIT
        has_signal = any(
            (isinstance(v, tuple) and v[0] != "NONE" and v[1] > 0) or
            (not isinstance(v, tuple) and v != "NONE")
            for v in ctx.signals.values()
        )
        if not has_signal:
            return CommanderOrder(
                action="wait",
                reasoning="No clear signal from any strategy.",
                confidence=0.6, regime=regime, risk_multiplier=meta_rm,
                timestamp=now.isoformat(),
            )

        # ── 7. CONSULTA LLM PARA DECISÃO FINAL (pulado se skip_llm=True) ──
        if skip_llm:
            print("[Commander] LLM skip: meta_learner ja consultou neste ciclo", flush=True)
            return self._fallback_decision(ctx, now)

        # Garante modelo disponível
        if not self._ensure_model():
            print("[Commander] Modelo LLM não disponível e falhou ao baixar", flush=True)
            return self._fallback_decision(ctx, now)

        llm_order = self._consult_llm({
            "regime": regime, "risk_score": risk_score,
            "vix": vix, "dxy": dxy,
            "balance": ctx.balance, "open_positions": ctx.open_positions,
            "max_positions": C.MAX_OPEN_POSITIONS,
            "open_symbols": list(ctx.open_symbols),
            "risk_mult": meta_rm, "strategy": "ts_momentum",
            "macro_thesis": thesis_text[:800],
            "signals": signals_text,
            "alerts": "\n".join(alerts[:5]) if alerts else "(none)",
            "performance": perf_text,
            "regime_performance": regime_perf or "(not enough data)",
            "evolution_status": evo_text or "Inactive",
        }, now)

        # ── 8. Fallback seguro se LLM falhar ──
        if llm_order is None:
            return self._fallback_decision(ctx, now)

        return llm_order

    def _ensure_model(self) -> bool:
        """Garante que o modelo está disponível, puxa se não estiver."""
        try:
            import requests
            # Lista modelos disponíveis
            resp = requests.get(f"{self.ollama_host}/api/tags", timeout=5)
            if resp.status_code != 200:
                return False
            models = resp.json().get("models", [])
            if any(m.get("name", "").startswith(self.ollama_model.split(":")[0]) for m in models):
                return True
            
            # Puxa modelo automaticamente
            print(f"[Commander] Modelo {self.ollama_model} não encontrado. Baixando...")
            pull_resp = requests.post(
                f"{self.ollama_host}/api/pull",
                json={"name": self.ollama_model, "stream": False},
                timeout=300,
            )
            return pull_resp.status_code == 200
        except Exception as e:
            print(f"[Commander] Erro ao verificar/baixar modelo: {e}")
            return False

    def _consult_llm(self, ctx: dict, now: datetime) -> Optional[CommanderOrder]:
        """Consulta o LLM para a decisão final."""
        try:
            import requests
            
            # Filtra símbolos abertos para não sugerir trade duplicado
            open_syms = ctx.get("open_symbols", [])
            signals = ctx.pop("signals", "")  # remove do ctx pra não duplicar no format()
            if open_syms:
                signals += "\n  ⚠️ Already open: " + ", ".join(open_syms)

            prompt = self.DECISION_PROMPT.format(**ctx, signals=signals)

            resp = requests.post(
                f"{self.ollama_host}/api/generate",
                json={"model": self.ollama_model, "prompt": prompt, "stream": False,
                      "options": {"temperature": 0.15, "num_predict": 1024}},
                timeout=None,
            )
            if resp.status_code == 200:
                raw = resp.json().get("response", "").strip()
                raw = raw.replace("```json", "").replace("```", "").strip()
                import re
                match = re.search(r'\{[^{}]*"action"[^{}]*"reasoning"[^{}]*\}', raw)
                if match:
                    data = json.loads(match.group())
                    return CommanderOrder(
                        action=data.get("action", "wait"),
                        symbol=data.get("symbol", "XAUUSDm"),
                        direction=data.get("direction", ""),
                        risk_pct=float(data.get("risk_pct", 0)),
                        size_frac=float(data.get("size_frac", 0.5)),
                        stop_atr_mult=float(data.get("stop_atr_mult", 1.5)),
                        rr_target=float(data.get("rr_target", 2.0)),
                        selected_strategy=data.get("selected_strategy", "ts_momentum"),
                        confidence=float(data.get("confidence", 0.5)),
                        primary_driver=data.get("primary_driver", ""),
                        reasoning=data.get("reasoning", "LLM decision"),
                        regime=ctx.get("regime", "normal"),
                        risk_multiplier=ctx.get("risk_mult", 1.0),
                        timestamp=now.isoformat(),
                    )
            return None
        except Exception as e:
            print(f"[Commander] LLM decision error: {type(e).__name__}: {e}")
            return None

    def _fallback_decision(self, ctx: CommanderDecisionContext, now: datetime) -> CommanderOrder:
        """Decisão de fallback quando LLM está indisponível.
        
        NÃO abre trade sem LLM — espera confirmação humana/IA.
        """
        return CommanderOrder(
            action="wait",
            reasoning="LLM indisponível — aguardando confirmação para abrir trade.",
            confidence=0.0,
            timestamp=now.isoformat(),
        )


# ═════════════════════════════ AUTONOMOUS COMMANDER ═════════════════════════════

class AutonomousCommander:
    """Comandante autônomo — a IA central do sistema.

    Uso:
        commander = AutonomousCommander()
        
        # A cada ciclo:
        order = commander.cycle(
            intel=intel_data,
            prices=price_data,
            meta=meta_state,
            signals={"XAUUSDm": ("BUY", 0.05)},
            signal_details={},
            balance=500.0,
            open_positions=0,
            open_symbols=set(),
            news_path=Path("filtered_news.json"),
        )
        # order.action -> "trade" | "wait" | "close_all" | "reduce_risk"
        
        # Após cada trade fechado:
        commander.learn(trade_result)
    """

    def __init__(self):
        self.oracle = AutonomousOracle()
        self.evolution = SelfEvolutionEngine()
        self.decision_engine = CommanderDecisionEngine()
        self.decision_history: list[CommanderOrder] = []
        self.cycle_count: int = 0
        self.last_oracle_update: str = ""
        self.last_evolution_update: str = ""

    def cycle(self, intel: dict, prices: Optional[dict] = None,
              meta: Optional[MetaState] = None,
              signals: Optional[dict] = None,
              signal_details: Optional[dict] = None,
              balance: float = 0.0,
              open_positions: int = 0,
              open_symbols: Optional[set] = None,
              news_path: Optional[Path] = None,
              last_trades: Optional[list] = None) -> CommanderOrder:
        """Ciclo completo de decisão da IA.
        
        1. Oracle: analisa macro global
        2. Evolution: ajusta parâmetros
        3. Meta: consulta LLM para risk multiplier
        4. Decide: IA emite ordem final
        """
        self.cycle_count += 1
        now = datetime.now(timezone.utc)
        
        if open_symbols is None:
            open_symbols = set()
        if signals is None:
            signals = {}
        if signal_details is None:
            signal_details = {}
        if last_trades is None:
            last_trades = []

        print(f"\n{'='*50}", flush=True)
        print(f"[Commander] Cycle #{self.cycle_count} @ {now.strftime('%Y-%m-%d %H:%M')}", flush=True)
        print(f"{'='*50}", flush=True)

        # ── 1. ORACLE: Análise Macro (a cada ciclo) ──
        print("[Commander] Running Autonomous Oracle...", flush=True)
        oracle_snapshot = self.oracle.analyze(intel, prices or {}, news_path)
        self.last_oracle_update = now.isoformat()
        
        print(f"  Regime: {oracle_snapshot.thesis.regime} | "
              f"Risk Score: {oracle_snapshot.thesis.risk_score}/100 | "
              f"Confidence: {oracle_snapshot.thesis.confidence}%", flush=True)
        print(f"  Thesis: {oracle_snapshot.thesis.summary_pt[:150]}...", flush=True)

        # ── 2. SELF-EVOLUTION: Ajusta parâmetros (a cada 3 ciclos) ──
        evo_result = None
        if self.cycle_count % 3 == 0 or self.cycle_count == 1:
            print("[Commander] Running Self-Evolution Engine...", flush=True)
            evo_result = self.evolution.evolve(meta, {
                "thesis": oracle_snapshot.thesis,
                "regime_memory": oracle_snapshot.regime_memory,
            })
            self.last_evolution_update = now.isoformat()

        # ── 3. META-LEARNER: Consulta LLM para risk multiplier (se necessario) ──
        # NOTA: A consulta ao LLM e integrada na decisao do Commander.
        # O Commander tem seu proprio LLM consultation no decision engine.
        # So chama o meta_learner.consult_llm() se estritamente necessario
        # para evitar DUAS chamadas LLM por ciclo.
        llm_meta_rec = None
        if meta and hasattr(meta, 'needs_llm_consult') and meta.needs_llm_consult:
            print("[Commander] Meta-learner triggered: consulting LLM...", flush=True)
            try:
                llm_meta_rec = consult_llm(meta)
            except Exception as e:
                print(f"[Commander] Meta-learner error: {e}", flush=True)

        # ── 4. DECIDE: IA toma decisão ──
        # IMPORTANTE: O decision engine SO consulta o LLM se o meta_learner
        # NAO tiver acabado de consultar. Se llm_meta_rec nao for None,
        # significa que ja houve uma chamada LLM neste ciclo — o decision
        # engine usa regras de fallback em vez de chamar o LLM novamente.
        skip_llm_decision = llm_meta_rec is not None
        print("[Commander] Decision Engine running...", flush=True)
        
        ctx = CommanderDecisionContext(
            oracle=oracle_snapshot,
            meta=meta,
            evolution=evo_result,
            signals=signals,
            signal_details=signal_details or {},
            balance=balance,
            open_positions=open_positions,
            open_symbols=open_symbols,
            last_trades=last_trades,
            timestamp=now.isoformat(),
        )

        order = self.decision_engine.decide(ctx, skip_llm=skip_llm_decision)

        # ── 5. REGISTRA DECISÃO ──
        self.decision_history.append(order)
        if len(self.decision_history) > 100:
            self.decision_history = self.decision_history[-50:]

        # Log da decisão
        emoji_map = {"trade": "📈", "wait": "⏳", "close_all": "🔴", "reduce_risk": "⚠️"}
        print(f"\n[Commander] DECISÃO: {emoji_map.get(order.action, '❓')} {order.action.upper()}", flush=True)
        if order.action == "trade":
            print(f"  {order.direction} {order.symbol} | "
                  f"Risk: {order.risk_pct:.1f}% | Size: {order.size_frac:.2f} | "
                  f"RR: {order.rr_target:.1f}", flush=True)
        print(f"  Strategy: {order.selected_strategy} | "
              f"Driver: {order.primary_driver} | "
              f"Confidence: {order.confidence:.0%}", flush=True)
        print(f"  Reasoning: {order.reasoning[:200]}", flush=True)

        # Salva estado
        self._save_state()

        return order

    def learn(self, trade_result: dict):
        """Sistema aprende com o resultado de um trade fechado.
        
        Args:
            trade_result: dict com pnl_usd, rr_realized, symbol, direction,
                         regime_at_entry, strategy, exit_reason
        """
        regime = trade_result.get("regime_at_entry", "unknown")
        strategy = trade_result.get("strategy", "ts_momentum")
        pnl = trade_result.get("pnl_usd", 0)

        # 1. Oracle: registra performance no regime
        self.oracle.regime_memory.record_performance(regime, trade_result)

        # 2. Evolution: registra resultado na estratégia
        self.evolution.record_trade_result(strategy, regime, trade_result)

        # 3. Log
        emoji = "✅" if pnl > 0 else "❌"
        print(f"[Commander] Learn: {emoji} {strategy} @ {regime} | "
              f"PnL=${pnl:.2f} | RR={trade_result.get('rr_realized', 0):.2f}", flush=True)

    def get_status(self) -> dict:
        """Retorna status completo do commander para o dashboard."""
        return {
            "cycle_count": self.cycle_count,
            "last_oracle_update": self.last_oracle_update,
            "last_evolution_update": self.last_evolution_update,
            "decisions_made": len(self.decision_history),
            "last_decision": self.decision_history[-1].to_dict() if self.decision_history else None,
            "regime_memory": self.oracle.regime_memory.to_dict() if self.oracle else {},
            "oracle": {
                "regime": self.oracle.regime_memory.last_regime if self.oracle else "unknown",
                "performance_by_regime": self.oracle.regime_memory.performance_by_regime if self.oracle else {},
            },
            "evolution": {
                "count": self.evolution.evolution_count if self.evolution else 0,
                "parameters": [
                    {"name": p.name, "value": p.current_value, "confidence": p.confidence}
                    for p in (self.evolution.tuner.parameters if self.evolution else [])
                ],
            },
        }

    def _save_state(self):
        """Persiste estado completo do commander (lido pelo dashboard)."""
        try:
            if STATE_PATH.exists():
                data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            else:
                data = {}
            # Salva TUDO que o get_status() retorna — o dashboard le daqui
            data[COMMANDER_STATE_KEY] = self.get_status()
            STATE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def load_status_from_file(state_path: Path) -> Optional[dict]:
        """Carrega o status do Commander do arquivo de estado (para o dashboard).
        
        Usado pelo dashboard para mostrar o Commander sem precisar criar
        uma nova instância (que teria 0 ciclos).
        """
        try:
            if state_path.exists():
                data = json.loads(state_path.read_text(encoding="utf-8"))
                return data.get(COMMANDER_STATE_KEY)
        except Exception:
            pass
        return None


__all__ = [
    "AutonomousCommander", "CommanderOrder", "CommanderDecisionContext",
    "CommanderDecisionEngine",
]
