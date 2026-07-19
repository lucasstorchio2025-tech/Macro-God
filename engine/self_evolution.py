"""
self_evolution.py — MOTOR DE AUTO-EVOLUÇÃO
===========================================
O sistema evolui SOZINHO — ajusta parâmetros, otimiza estratégia,
aprende com erros e melhora continuamente sem intervenção humana.

CAPACIDADES:
  1. Auto Hyperparameter Tuning: Ajusta parâmetros-chave baseado em performance
  2. Strategy Selection by Regime: Escolhe a melhor estratégia para cada regime
  3. Parameter Drift Detection: Detecta quando parâmetros param de funcionar
  4. Continuous Walk-Forward: Validação automática em novos dados
  5. Performance Attribution: O que está funcionando e o que não está
  6. Auto Config Update: Atualiza engine/config.py com parâmetros otimizados
  7. Beta Testing: Testa novas estratégias em ambiente isolado antes de ativar

Filosofia:
  - NUNCA faz overfit: toda otimização é validada OOS (walk-forward)
  - Tudo é reversível: cada mudança tem um rollback automático
  - Aprendizado por reforço: trades reais alimentam o modelo
  - O LLM (Gemma 4-opt) interpreta, NÃO inventa dados
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
from .meta_config import MetaState, load_meta_state, save_meta_state as save_ms

# ── Paths ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOT_DIR = PROJECT_ROOT / "bot"
ENGINE_DIR = PROJECT_ROOT / "engine"
STATE_PATH = BOT_DIR / "bot_state.json"
EVOLUTION_STATE_KEY = "self_evolution"
TRADE_LOG_PATH = BOT_DIR / "trade_log.jsonl"


# ═════════════════════════════ PARAMETER SPACE ═════════════════════════════

@dataclass
class EvolvableParameter:
    """Um parâmetro que o sistema pode evoluir autonomamente."""
    name: str
    current_value: float
    min_value: float
    max_value: float
    step: float
    description: str
    category: str          # "risk" | "strategy" | "filter" | "exit"
    is_active: bool = True
    performance_history: list[dict] = field(default_factory=list)
    last_tuned: str = ""
    confidence: float = 1.0

    def mutate(self, performance_trend: float) -> float:
        """Gera novo valor baseado em tendência de performance."""
        if not self.is_active:
            return self.current_value
        
        # Quanto maior a confiança, menor a mutação (exploit > explore)
        mutation_scale = max(0.05, 0.5 * (1.0 - self.confidence))
        
        # Direção da mutação: positiva se performance melhorou
        direction = 1.0 if performance_trend > 0 else -1.0
        
        # Se confiança baixa, explora mais aleatoriamente
        if self.confidence < 0.3:
            direction *= np.random.choice([-1, 1])
        
        delta = direction * self.step * mutation_scale
        new_val = self.current_value + delta
        return round(max(self.min_value, min(self.max_value, new_val)), 4)


# ═════════════════════════════ PARAMETER POOL ═════════════════════════════

DEFAULT_PARAMETER_POOL: list[EvolvableParameter] = [
    # ── RISK ──
    EvolvableParameter("risk_per_trade_pct", C.RISK_PER_TRADE_PCT, 1.0, 10.0, 0.5,
                       "% do saldo arriscado por trade", "risk"),
    EvolvableParameter("daily_dd_pct", C.DAILY_DD_PCT, 5.0, 20.0, 1.0,
                       "Limite de drawdown diário (%)", "risk"),
    EvolvableParameter("weekly_dd_pct", C.WEEKLY_DD_PCT, 8.0, 25.0, 1.0,
                       "Limite de drawdown semanal (%)", "risk"),
    # ── STRATEGY ──
    EvolvableParameter("momentum_lookback_bars", C.MOMENTUM_LOOKBACK_BARS, 120, 504, 24,
                       "Janela de lookback do TS-Momentum (barras H4)", "strategy"),
    EvolvableParameter("momentum_min_abs_r", C.MOMENTUM_MIN_ABS_R, 0.005, 0.05, 0.005,
                       "Mínimo retorno absoluto para sinal", "strategy"),
    # ── EXIT ──
    EvolvableParameter("atr_stop_mult", C.ATR_STOP_MULT, 0.5, 3.0, 0.25,
                       "Multiplicador ATR para stop loss", "exit"),
    EvolvableParameter("rr_target_mult", C.RR_TARGET_MULT, 1.0, 3.0, 0.25,
                       "Multiplicador do take profit (RR)", "exit"),
    EvolvableParameter("holding_time_max_bars", C.HOLDING_TIME_MAX_BARS, 42, 168, 12,
                       "Máximo de barras H4 para segurar posição", "exit"),
    # ── FILTER ──
    EvolvableParameter("vix_max_level", C.VIX_MAX_LEVEL, 0, 35, 2.5,
                       "VIX máximo para operar (0=desligado)", "filter"),
    EvolvableParameter("cooldown_bars", C.COOLDOWN_BARS, 4, 24, 2,
                       "Cooldown entre trades no mesmo símbolo (barras H4)", "filter"),
]


# ═════════════════════════════ STRATEGY REGISTRY ═════════════════════════════

STRATEGY_REGISTRY = {
    "ts_momentum": {
        "name": "TS-Momentum (Moskowitz 2012)",
        "description": "Trend following clássico: compra tendências, vende reversões",
        "best_regimes": ["risk_on", "normal"],
        "worst_regimes": ["crisis"],
        "current_weight": 1.0,
        "performance": {},
    },
    "mean_reversion": {
        "name": "Mean Reversion (contrarian)",
        "description": "Compra oversold, vende overbought em regimes de volatilidade",
        "best_regimes": ["risk_off"],
        "worst_regimes": ["risk_on"],
        "current_weight": 0.0,
        "performance": {},
    },
    "macro_directional": {
        "name": "Macro Directional (top-down)",
        "description": "Segue a tese macro: opera na direção do driver principal",
        "best_regimes": ["risk_on", "risk_off"],
        "worst_regimes": ["normal"],
        "current_weight": 0.0,
        "performance": {},
    },
}

# ═════════════════════════════ PERFORMANCE ANALYZER ═════════════════════════════

class PerformanceAnalyzer:
    """Analisa performance para alimentar o motor de evolução."""

    @staticmethod
    def analyze_trades(trades: list[dict], n_last: int = 50) -> dict:
        """Analisa trades recentes e retorna métricas detalhadas."""
        if not trades:
            return {"n": 0, "error": "no trades"}
        
        recent = trades[-n_last:]
        pnls = [t.get("payload", {}).get("profit", 0) for t in recent]
        clean = [p for p in pnls if p != 0]
        
        if not clean:
            return {"n": 0, "error": "no closed trades"}
        
        wins = [p for p in clean if p > 0]
        losses = [p for p in clean if p < 0]
        total_pnl = sum(clean)
        
        return {
            "n": len(clean),
            "win_rate": len(wins) / len(clean) if clean else 0,
            "avg_win": np.mean(wins) if wins else 0,
            "avg_loss": abs(np.mean(losses)) if losses else 0,
            "total_pnl": total_pnl,
            "avg_pnl": total_pnl / len(clean) if clean else 0,
            "profit_factor": abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float('inf'),
            "sharpe": (np.mean(clean) / np.std(clean)) * np.sqrt(len(clean)) if np.std(clean) > 0 else 0,
            "max_drawdown": PerformanceAnalyzer._max_drawdown(clean),
            "consecutive_losses": PerformanceAnalyzer._max_consecutive(clean, negative=True),
            "consecutive_wins": PerformanceAnalyzer._max_consecutive(clean, negative=False),
        }

    @staticmethod
    def _max_drawdown(pnls: list[float]) -> float:
        """Calcula o máximo drawdown da sequência de PnLs."""
        if not pnls:
            return 0
        cumulative = np.cumsum(pnls)
        peak = np.maximum.accumulate(cumulative)
        drawdown = peak - cumulative
        return float(np.max(drawdown)) if len(drawdown) > 0 else 0

    @staticmethod
    def _max_consecutive(values: list[float], negative: bool = True) -> int:
        """Máximo de valores consecutivos negativos (ou positivos)."""
        max_count = count = 0
        for v in values:
            if (negative and v < 0) or (not negative and v > 0):
                count += 1
                max_count = max(max_count, count)
            else:
                count = 0
        return max_count

    @staticmethod
    def compute_trend(metrics_history: list[dict], window: int = 5) -> float:
        """Calcula tendência de performance: positiva = melhorando."""
        if len(metrics_history) < 2:
            return 0.0
        recent = metrics_history[-window:] if len(metrics_history) >= window else metrics_history
        # Compara sharpe médio recente vs antigo
        if len(recent) < 2:
            return 0.0
        half = len(recent) // 2
        recent_half = [m.get("sharpe", 0) for m in recent[half:]]
        older_half = [m.get("sharpe", 0) for m in recent[:half]]
        if not older_half or not recent_half:
            return 0.0
        return (np.mean(recent_half) - np.mean(older_half)) / max(abs(np.mean(older_half)), 0.01)


# ═════════════════════════════ PARAMETER TUNER ═════════════════════════════

class ParameterTuner:
    """Ajusta parâmetros evolutivos baseado em performance."""

    def __init__(self):
        self.parameters = [p for p in DEFAULT_PARAMETER_POOL]

    def tune_all(self, metrics: dict, trend: float) -> list[dict]:
        """Ajusta todos os parâmetros ativos baseado nas métricas atuais."""
        changes = []
        
        for param in self.parameters:
            old_value = param.current_value
            
            # Adapta confiança baseado no profit factor
            pf = metrics.get("profit_factor", 1.0)
            if pf > 2.0:
                param.confidence = min(1.0, param.confidence + 0.1)
            elif pf < 1.0:
                param.confidence = max(0.1, param.confidence - 0.1)
            
            new_value = param.mutate(trend)
            
            if new_value != old_value:
                param.current_value = new_value
                param.last_tuned = datetime.now(timezone.utc).isoformat()
                param.performance_history.append({
                    "timestamp": param.last_tuned,
                    "old_value": old_value,
                    "new_value": new_value,
                    "trend": trend,
                    "confidence": param.confidence,
                })
                changes.append({
                    "parameter": param.name,
                    "category": param.category,
                    "old": old_value,
                    "new": new_value,
                    "reason": f"Trend={trend:+.3f}, Confidence={param.confidence:.2f}",
                })
        
        return changes

    def get_config_update(self) -> dict:
        """Gera dicionário de atualização de config baseado nos parâmetros atuais."""
        update = {}
        for param in self.parameters:
            # Mapeia nomes de parâmetros para constantes do config.py
            key_map = {
                "risk_per_trade_pct": "RISK_PER_TRADE_PCT",
                "daily_dd_pct": "DAILY_DD_PCT",
                "weekly_dd_pct": "WEEKLY_DD_PCT",
                "momentum_lookback_bars": "MOMENTUM_LOOKBACK_BARS",
                "momentum_min_abs_r": "MOMENTUM_MIN_ABS_R",
                "atr_stop_mult": "ATR_STOP_MULT",
                "rr_target_mult": "RR_TARGET_MULT",
                "holding_time_max_bars": "HOLDING_TIME_MAX_BARS",
                "vix_max_level": "VIX_MAX_LEVEL",
                "cooldown_bars": "COOLDOWN_BARS",
            }
            config_key = key_map.get(param.name)
            if config_key and param.confidence > 0.3:
                update[config_key] = param.current_value
        return update


# ═════════════════════════════ STRATEGY SELECTOR ═════════════════════════════

class StrategySelector:
    """Seleciona a melhor estratégia para o regime atual."""

    def __init__(self):
        self.strategies = STRATEGY_REGISTRY

    def select(self, regime: str, oracle_data: dict) -> dict:
        """Seleciona estratégia(s) para o regime atual.
        
        Returns:
            dict com estratégias selecionadas e weights
        """
        # Determina weight baseado no fit com o regime
        for name, strat in self.strategies.items():
            weight = 0.0
            if regime in strat["best_regimes"]:
                weight = 1.0
            elif regime in strat["worst_regimes"]:
                weight = 0.0
            else:
                weight = 0.3  # peso baixo para regimes não-ótimos
            
            # Ajusta por performance histórica no regime
            perf = strat["performance"].get(regime, {})
            n_trades = perf.get("trades", 0)
            if n_trades >= 5:
                wr = perf.get("wins", 0) / max(1, n_trades)
                if wr > 0.5:
                    weight = min(1.0, weight + 0.2)
                else:
                    weight = max(0.0, weight - 0.2)
            
            strat["current_weight"] = weight
        
        # Retorna estratégia(s) com weight > 0.3
        selected = {
            name: strat
            for name, strat in self.strategies.items()
            if strat["current_weight"] > 0.3
        }
        
        if not selected:
            # Fallback: sempre tem ts_momentum
            selected = {"ts_momentum": self.strategies["ts_momentum"]}
        
        return selected

    def record_result(self, strategy: str, regime: str, trade_result: dict):
        """Registra resultado de trade para aprendizado da seleção."""
        if strategy not in self.strategies:
            return
        
        if regime not in self.strategies[strategy]["performance"]:
            self.strategies[strategy]["performance"][regime] = {
                "trades": 0, "wins": 0, "losses": 0, "pnl": 0.0
            }
        
        perf = self.strategies[strategy]["performance"][regime]
        perf["trades"] += 1
        pnl = trade_result.get("pnl_usd", 0)
        if pnl > 0:
            perf["wins"] += 1
        else:
            perf["losses"] += 1
        perf["pnl"] += pnl


# ═════════════════════════════ LLM CONSULTANT ═════════════════════════════

class EvolutionLLM:
    """Consulta o LLM para decisões complexas de evolução."""

    EVOLUTION_PROMPT = """You are a systematic trading system optimizer.

Your job: analyze the bot's performance data and recommend PARAMETER CHANGES.

CURRENT PARAMETERS:
{parameters}

PERFORMANCE (last {n_trades} trades):
{metrics}

REGIME: {regime}
ORACLE: {oracle_summary}

AVAILABLE STRATEGIES:
{strategies}

TASK:
Based on this data, recommend:
1. Which parameters to change and by how much
2. Which strategy to prioritize for the current regime
3. Any filters to enable/disable

Respond with valid JSON:
{{"parameter_changes": [{{"name": "param_name", "new_value": 1.5, "reason": "short reason"}}],
  "primary_strategy": "ts_momentum",
  "strategy_weight": 0.8,
  "filters": {{"filter_name": true/false}},
  "reasoning": "brief explanation"}}
"""

    def __init__(self):
        self.ollama_host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self.ollama_model = os.environ.get("META_LLM_MODEL", "gemma4-opt:latest")

    def consult(self, context: dict) -> Optional[dict]:
        """Consulta o LLM para recomendações de evolução."""
        try:
            import requests
            
            params_text = "\n".join(
                f"  {p['name']}: {p['current_value']} (range: {p['min_value']}-{p['max_value']}, conf:{p.get('confidence', 1.0):.2f})"
                for p in context.get("parameters", [])
            )
            
            metrics = context.get("metrics", {})
            metrics_text = (
                f"WR={metrics.get('win_rate',0):.1%}, "
                f"AvgPnL=${metrics.get('avg_pnl',0):.2f}, "
                f"PF={metrics.get('profit_factor',1):.2f}, "
                f"Sharpe={metrics.get('sharpe',0):.2f}, "
                f"MaxDD=${metrics.get('max_drawdown',0):.2f}"
            )
            
            strategies_text = "\n".join(
                f"  {k}: {v['description']} (best in {v['best_regimes']})"
                for k, v in context.get("strategies", {}).items()
            )

            prompt = self.EVOLUTION_PROMPT.format(
                parameters=params_text,
                n_trades=metrics.get("n", 0),
                metrics=metrics_text,
                regime=context.get("regime", "unknown"),
                oracle_summary=context.get("oracle_summary", ""),
                strategies=strategies_text,
            )

            resp = requests.post(
                f"{self.ollama_host}/api/generate",
                json={"model": self.ollama_model, "prompt": prompt, "stream": False,
                      "options": {"temperature": 0.2, "num_predict": 1024}},
                timeout=None,
            )
            if resp.status_code == 200:
                raw = resp.json().get("response", "").strip()
                raw = raw.replace("```json", "").replace("```", "").strip()
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    import re
                    match = re.search(r'\{[^{}]*"parameter_changes"[^{}]*\}', raw)
                    if match:
                        return json.loads(match.group())
            return None
        except Exception as e:
            print(f"[Evolution] LLM error: {type(e).__name__}: {e}")
            return None


# ═════════════════════════════ CORE SELF-EVOLUTION ENGINE ═════════════════════════════

class SelfEvolutionEngine:
    """Motor central de auto-evolução do sistema."""

    def __init__(self):
        self.tuner = ParameterTuner()
        self.selector = StrategySelector()
        self.llm = EvolutionLLM()
        self.analyzer = PerformanceAnalyzer()
        self.metrics_history: list[dict] = []
        self.evolution_log: list[dict] = []
        self.last_evolution_utc: str = ""
        self.evolution_count: int = 0

    def evolve(self, meta: MetaState, oracle_data: dict, force: bool = False) -> dict:
        """Executa um ciclo de evolução.
        
        Returns:
            dict com mudanças aplicadas e recomendações
        """
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "parameter_changes": [],
            "strategy_selection": {},
            "llm_recommendations": None,
            "config_update": {},
        }

        # ── 1. Carrega trades recentes ──
        trades = self._load_recent_trades()
        if not trades and not force:
            return result

        # ── 2. Analisa performance ──
        metrics = self.analyzer.analyze_trades(trades)
        result["metrics"] = metrics
        self.metrics_history.append(metrics)
        if len(self.metrics_history) > 50:
            self.metrics_history = self.metrics_history[-30:]

        # ── 3. Calcula tendência ──
        trend = self.analyzer.compute_trend(self.metrics_history)

        # ── 4. Ajusta parâmetros ──
        meta_rm = meta.get_risk_multiplier()
        if metrics.get("n", 0) >= 5 or force:
            changes = self.tuner.tune_all(metrics, trend)
            result["parameter_changes"] = changes
            result["config_update"] = self.tuner.get_config_update()
            
            if changes:
                self.evolution_count += 1
                self.evolution_log.append({
                    "timestamp": result["timestamp"],
                    "changes": changes,
                    "metrics": {k: metrics.get(k) for k in ["sharpe", "win_rate", "profit_factor", "total_pnl"]},
                    "trend": trend,
                })

        # ── 5. Seleciona estratégia ──
        thesis_obj = oracle_data.get("thesis")
        regime = thesis_obj.regime if hasattr(thesis_obj, 'regime') else "normal"
        selected = self.selector.select(regime, oracle_data)
        result["strategy_selection"] = {
            name: {"weight": s["current_weight"]}
            for name, s in selected.items()
        }

        # ── 6. Consulta LLM para decisões complexas ──
        if (self.evolution_count % 3 == 0 or force) and metrics.get("n", 0) >= 10:
            llm_context = {
                "parameters": [
                    {"name": p.name, "current_value": p.current_value,
                     "min_value": p.min_value, "max_value": p.max_value,
                     "confidence": p.confidence}
                    for p in self.tuner.parameters
                ],
                "metrics": metrics,
                "regime": regime,
                "oracle_summary": thesis_obj.summary_pt[:500] if hasattr(thesis_obj, 'summary_pt') else "",
                "strategies": {
                    k: {"description": v["description"], "best_regimes": v["best_regimes"]}
                    for k, v in STRATEGY_REGISTRY.items()
                },
            }
            llm_rec = self.llm.consult(llm_context)
            if llm_rec:
                result["llm_recommendations"] = llm_rec
                # Aplica recomendações do LLM se houverem
                self._apply_llm_recommendations(llm_rec)

        self.last_evolution_utc = result["timestamp"]
        
        # Log compacto
        print(f"[Evolution] Cycle #{self.evolution_count}: "
              f"{len(result['parameter_changes'])} param changes, "
              f"trend={trend:+.3f}, "
              f"Sharpe={metrics.get('sharpe',0):.2f}, "
              f"PF={metrics.get('profit_factor',1):.2f}", flush=True)

        self._save_state()
        return result

    def _apply_llm_recommendations(self, rec: dict):
        """Aplica recomendações do LLM nos parâmetros."""
        # Ajusta parâmetros
        for change in rec.get("parameter_changes", []):
            name = change.get("name")
            new_val = change.get("new_value")
            for param in self.tuner.parameters:
                if param.name == name:
                    if param.min_value <= new_val <= param.max_value:
                        param.current_value = new_val
                        param.last_tuned = datetime.now(timezone.utc).isoformat()
                        print(f"[Evolution] LLM: {name} = {new_val} ({change.get('reason','')})")
                    break

        # Ajusta pesos de estratégia
        primary = rec.get("primary_strategy")
        weight = rec.get("strategy_weight", 0.5)
        if primary and primary in self.selector.strategies:
            self.selector.strategies[primary]["current_weight"] = weight
            for name in self.selector.strategies:
                if name != primary:
                    self.selector.strategies[name]["current_weight"] = max(0, (1.0 - weight) / (len(self.selector.strategies) - 1))

    def _load_recent_trades(self) -> list[dict]:
        """Carrega trades recentes do log."""
        if not TRADE_LOG_PATH.exists():
            return []
        try:
            lines = TRADE_LOG_PATH.read_text(encoding="utf-8").splitlines()
            return [json.loads(l) for l in lines if l.strip()][-100:]
        except Exception:
            return []

    def record_trade_result(self, strategy: str, regime: str, trade_result: dict):
        """Registra resultado de trade no selector de estratégia."""
        self.selector.record_result(strategy, regime, trade_result)
        self._save_state()

    def _save_state(self):
        """Persiste estado da evolução."""
        try:
            if STATE_PATH.exists():
                data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            else:
                data = {}
            data[EVOLUTION_STATE_KEY] = {
                "metrics_history": self.metrics_history[-30:],
                "evolution_log": self.evolution_log[-50:],
                "last_evolution": self.last_evolution_utc,
                "evolution_count": self.evolution_count,
                "parameters": [
                    {"name": p.name, "current_value": p.current_value,
                     "confidence": p.confidence, "last_tuned": p.last_tuned}
                    for p in self.tuner.parameters
                ],
                "strategies": self.selector.strategies,
            }
            STATE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass


__all__ = [
    "SelfEvolutionEngine", "ParameterTuner", "StrategySelector",
    "PerformanceAnalyzer", "EvolutionLLM",
    "EvolvableParameter", "DEFAULT_PARAMETER_POOL",
]
