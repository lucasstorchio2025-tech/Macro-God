"""
meta_config.py — Estado meta do bot: aprendizado contínuo sem overfit.

MetaState armazena:
  1. Rolling metrics (win rate, payoff, SL rate) dos últimos N trades
  2. Performance por bucket de contexto (regime, direcao, atr_stop)
  3. Multiplicadores adaptativos gerados pelo LLM (Gemma 4-opt)
  4. Histórico de recomendações do LLM para auditoria

Filosofia:
  - NUNCA muda a direcao do trade (quem decide é o TS-Momentum)
  - NUNCA salva features de preco (isso seria overfit)
  - So aprende por categorias interpretaveis (regime, direcao, stop)
  - Tudo tem janela rolante (esquece dados antigos)
"""
from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Constantes ──
ROLLING_WINDOW = 50            # janela para metricas rolling
BUCKET_MIN_TRADES = 10         # minimo de trades por bucket para acao
DEFAULT_RISK_MULT = 1.0        # multiplicador padrao (sem alteracao)
META_STATE_KEY = "meta_state"  # chave no bot_state.json


# ═════════════════════════════ Bucket de Performance ═════════════════════════════
@dataclass
class BucketPerformance:
    """Performance de trades agrupados por contexto interpretavel.

    Exemplo de bucket key: ("risk_on", "BUY", 2.0) = comprar em risk_on com stop 2.0xATR
    """
    trades: list[dict] = field(default_factory=list)
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    total_rr: float = 0.0
    last_updated: str = ""

    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        return self.wins / self.n if self.n > 0 else 0.0

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.n if self.n > 0 else 0.0

    @property
    def avg_rr(self) -> float:
        return self.total_rr / self.n if self.n > 0 else 0.0

    def add_trade(self, trade: dict):
        """Adiciona um trade fechado ao bucket."""
        self.trades.append(trade)
        pnl = trade.get("pnl_usd", 0)
        rr = trade.get("rr_realized", 0)
        if pnl > 0:
            self.wins += 1
        else:
            self.losses += 1
        self.total_pnl += pnl
        self.total_rr += rr
        # Mantém janela rolante
        if len(self.trades) > ROLLING_WINDOW:
            old = self.trades.pop(0)
            old_pnl = old.get("pnl_usd", 0)
            old_rr = old.get("rr_realized", 0)
            if old_pnl > 0:
                self.wins -= 1
            else:
                self.losses -= 1
            self.total_pnl -= old_pnl
            self.total_rr -= old_rr
        self.last_updated = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "wins": self.wins, "losses": self.losses,
            "n_calc": self.n,
            "win_rate": round(self.win_rate, 3),
            "avg_pnl": round(self.avg_pnl, 2),
            "avg_rr": round(self.avg_rr, 3),
            "total_pnl": round(self.total_pnl, 2),
            "total_rr": round(self.total_rr, 3),
            "last_updated": self.last_updated,
            "_trades": [t.copy() for t in self.trades[-20:]],
        }


# ═════════════════════════════ MetaState ═════════════════════════════
@dataclass
class MetaState:
    """Estado meta completo do bot. Persistido no bot_state.json."""

    # Rolling metrics (ultimos ROLLING_WINDOW trades)
    recent_trades: list[dict] = field(default_factory=list)
    rolling_wins: int = 0
    rolling_losses: int = 0
    rolling_pnl: float = 0.0
    rolling_rr_sum: float = 0.0
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0

    # Performance por bucket de contexto
    buckets: dict[str, dict] = field(default_factory=dict)
    # Ex: {"risk_on|BUY|2.0": BucketPerformance}

    # Multiplicadores ativos (gerados pelo LLM)
    risk_multiplier: float = DEFAULT_RISK_MULT
    risk_multiplier_confidence: float = 0.0
    risk_multiplier_reasoning: str = ""
    risk_multiplier_updated: str = ""

    # Stop multiplier (futuro)
    stop_multiplier: float = 1.0

    # Historico de recomendacoes do LLM (para auditoria)
    llm_recommendations: list[dict] = field(default_factory=list)
    max_llm_history: int = 20

    # Gatilhos
    last_llm_consult_utc: str = ""
    trades_since_last_consult: int = 0
    total_trades_analyzed: int = 0

    # Kill-switch: desliga meta-learner se PnL estiver degradando
    _kill_switch_active: bool = False

    # ── Metodos ──

    @property
    def rolling_n(self) -> int:
        return len(self.recent_trades)

    @property
    def rolling_win_rate(self) -> float:
        return self.rolling_wins / self.rolling_n if self.rolling_n > 0 else 0.0

    @property
    def rolling_payoff(self) -> float:
        """Payoff medio = media dos RR realizados (so trades fechados)."""
        return self.rolling_rr_sum / self.rolling_n if self.rolling_n > 0 else 0.0

    @property
    def rolling_sl_rate(self) -> float:
        """Taxa de STOP loss = proporcao de trades que bateram SL."""
        if self.rolling_n == 0:
            return 0.0
        sl_count = sum(1 for t in self.recent_trades
                       if t.get("exit_reason") == "SL")
        return sl_count / self.rolling_n

    @property
    def needs_llm_consult(self) -> bool:
        """True se devemos consultar o LLM agora."""
        # Kill-switch ativo: nunca consulta LLM
        if self._kill_switch_active:
            return False
        # Gatilho 1: a cada 10 trades
        if self.trades_since_last_consult >= 10:
            return True
        # Gatilho 2: streak de 3+ perdas
        if self.consecutive_losses >= 3:
            return True
        # Gatilho 3: primeira consulta
        if not self.last_llm_consult_utc and self.rolling_n >= 5:
            return True
        return False

    @needs_llm_consult.setter
    def needs_llm_consult(self, value: bool):
        """Setter para o kill-switch desligar consultas ao LLM.

        Quando setado para False pelo kill-switch, ativa
        _kill_switch_active para sobrescrever os gatilhos normais.
        """
        if not value:
            self._kill_switch_active = True
            self.trades_since_last_consult = 0

    def on_trade_close(self, trade: dict):
        """Atualiza estado com um trade fechado."""
        # Adiciona a rolling window
        self.recent_trades.append(trade)
        pnl = trade.get("pnl_usd", 0)
        rr = trade.get("rr_realized", 0)
        reason = trade.get("exit_reason", "")

        if pnl > 0:
            self.rolling_wins += 1
            self.consecutive_losses = 0
        else:
            self.rolling_losses += 1
            self.consecutive_losses += 1
            self.max_consecutive_losses = max(
                self.max_consecutive_losses, self.consecutive_losses
            )

        self.rolling_pnl += pnl
        self.rolling_rr_sum += rr

        # Mantem janela rolante
        if len(self.recent_trades) > ROLLING_WINDOW:
            old = self.recent_trades.pop(0)
            old_pnl = old.get("pnl_usd", 0)
            old_rr = old.get("rr_realized", 0)
            if old_pnl > 0:
                self.rolling_wins -= 1
            else:
                self.rolling_losses -= 1
            self.rolling_pnl -= old_pnl
            self.rolling_rr_sum -= old_rr

        # Atualiza bucket de contexto
        bucket_key = self._bucket_key(trade)
        if bucket_key not in self.buckets:
            self.buckets[bucket_key] = BucketPerformance().to_dict()
        # Reconstroi BucketPerformance do dict, usando total_rr salvo direto
        stored = self.buckets[bucket_key]
        bp = BucketPerformance(
            trades=stored.get("_trades", []),
            wins=stored.get("wins", 0),
            losses=stored.get("losses", 0),
            total_pnl=stored.get("total_pnl", 0.0),
            total_rr=stored.get("total_rr", 0.0),
            last_updated=stored.get("last_updated", ""),
        )
        bp.add_trade(trade)
        self.buckets[bucket_key] = bp.to_dict()

        self.total_trades_analyzed += 1
        self.trades_since_last_consult += 1

    def _bucket_key(self, trade: dict) -> str:
        """Gera chave do bucket: regime|direcao|atr_stop_mult."""
        regime = trade.get("regime_at_entry", "unknown")
        direction = trade.get("direction", "unknown")
        atr_mult = trade.get("atr_stop_mult", 0)
        return f"{regime}|{direction}|{atr_mult}"

    def get_risk_multiplier(self) -> float:
        """Retorna o multiplicador de risco atual."""
        return self.risk_multiplier

    def reset_kill_switch(self):
        """Reativa o meta-learner apos kill-switch.

        Uso:
            meta.reset_kill_switch()
            save_meta_state(STATE_PATH, meta)
        """
        self._kill_switch_active = False
        self.risk_multiplier = DEFAULT_RISK_MULT
        self.risk_multiplier_reasoning = "Kill-switch resetado manualmente"
        self.risk_multiplier_confidence = 0.0
        self.trades_since_last_consult = 10  # gatilho rapido na proxima consulta

    def apply_llm_recommendation(self, rec: dict):
        """Aplica recomendacao do LLM validada."""
        rm = rec.get("risk_multiplier", DEFAULT_RISK_MULT)
        # Limites de seguranca
        self.risk_multiplier = max(0.1, min(2.0, rm))
        self.risk_multiplier_confidence = rec.get("confidence", 0.0)
        self.risk_multiplier_reasoning = rec.get("reasoning", "")
        self.risk_multiplier_updated = datetime.now(timezone.utc).isoformat()

        # Salva no historico
        self.llm_recommendations.append({
            "timestamp": self.risk_multiplier_updated,
            "risk_multiplier": self.risk_multiplier,
            "confidence": self.risk_multiplier_confidence,
            "reasoning": self.risk_multiplier_reasoning,
        })
        if len(self.llm_recommendations) > self.max_llm_history:
            self.llm_recommendations.pop(0)

        # Reseta contador
        self.last_llm_consult_utc = self.risk_multiplier_updated
        self.trades_since_last_consult = 0

    def get_buckets_summary(self, min_trades: int = BUCKET_MIN_TRADES) -> list[dict]:
        """Retorna buckets com N >= min_trades para analise."""
        result = []
        for key, data in self.buckets.items():
            n = data.get("n_calc") or data.get("n", 0)  # compat: n_calc (novo) ou n (legado)
            if n >= min_trades:
                result.append({"bucket": key, "n": n, **data})
        return sorted(result, key=lambda x: -x["n"])

    def get_llm_context(self) -> dict:
        """Monta o contexto completo para enviar ao LLM.

        So inclui dados reais — nada que o LLM possa inventar.
        """
        buckets_summary = self.get_buckets_summary()
        return {
            "rolling": {
                "n": self.rolling_n,
                "win_rate": round(self.rolling_win_rate, 3),
                "payoff": round(self.rolling_payoff, 3),
                "sl_rate": round(self.rolling_sl_rate, 3),
                "consecutive_losses": self.consecutive_losses,
                "avg_pnl": round(self.rolling_pnl / self.rolling_n, 2)
                if self.rolling_n > 0 else 0,
            },
            "buckets": [
                {"key": b["bucket"],
                 "n": b["n"],
                 "win_rate": b["win_rate"],
                 "avg_rr": b["avg_rr"],
                 "avg_pnl": b["avg_pnl"]}
                for b in buckets_summary
            ],
            "total_analyzed": self.total_trades_analyzed,
        }

    def to_dict(self) -> dict:
        return {
            "rolling_n": self.rolling_n,
            "rolling_win_rate": self.rolling_win_rate,
            "rolling_payoff": self.rolling_payoff,
            "rolling_sl_rate": self.rolling_sl_rate,
            "consecutive_losses": self.consecutive_losses,
            "max_consecutive_losses": self.max_consecutive_losses,
            "risk_multiplier": self.risk_multiplier,
            "risk_multiplier_confidence": self.risk_multiplier_confidence,
            "risk_multiplier_reasoning": self.risk_multiplier_reasoning,
            "risk_multiplier_updated": self.risk_multiplier_updated,
            "buckets": self.buckets,
            "llm_recommendations": self.llm_recommendations[-5:],
            "last_llm_consult_utc": self.last_llm_consult_utc,
            "trades_since_last_consult": self.trades_since_last_consult,
            "total_trades_analyzed": self.total_trades_analyzed,
            "recent_trades_count": len(self.recent_trades),
            "kill_switch_active": self._kill_switch_active,
        }


# ═════════════════════════════ Persistencia ═════════════════════════════

def load_meta_state(state_path: Path) -> MetaState:
    """Carrega MetaState do bot_state.json ou cria novo."""
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            meta_data = data.get(META_STATE_KEY, {})
            if meta_data:
                # Converte buckets de volta para dict
                buckets = meta_data.get("buckets", {})
                return MetaState(
                    recent_trades=meta_data.get("recent_trades", []),
                    rolling_wins=meta_data.get("rolling_wins", 0),
                    rolling_losses=meta_data.get("rolling_losses", 0),
                    rolling_pnl=meta_data.get("rolling_pnl", 0.0),
                    rolling_rr_sum=meta_data.get("rolling_rr_sum", 0.0),
                    consecutive_losses=meta_data.get("consecutive_losses", 0),
                    max_consecutive_losses=meta_data.get("max_consecutive_losses", 0),
                    buckets=buckets,
                    risk_multiplier=meta_data.get("risk_multiplier", DEFAULT_RISK_MULT),
                    risk_multiplier_confidence=meta_data.get("risk_multiplier_confidence", 0.0),
                    risk_multiplier_reasoning=meta_data.get("risk_multiplier_reasoning", ""),
                    risk_multiplier_updated=meta_data.get("risk_multiplier_updated", ""),
                    stop_multiplier=meta_data.get("stop_multiplier", 1.0),
                    llm_recommendations=meta_data.get("llm_recommendations", []),
                    last_llm_consult_utc=meta_data.get("last_llm_consult_utc", ""),
                    trades_since_last_consult=meta_data.get("trades_since_last_consult", 0),
                    total_trades_analyzed=meta_data.get("total_trades_analyzed", 0),
                    _kill_switch_active=meta_data.get("kill_switch_active", False),
                )
        except Exception:
            pass
    return MetaState()


def save_meta_state(state_path: Path, meta: MetaState):
    """Salva MetaState no bot_state.json (sem perder outros campos)."""
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}
    data[META_STATE_KEY] = meta.to_dict()
    state_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


__all__ = [
    "MetaState", "BucketPerformance", "load_meta_state", "save_meta_state",
    "ROLLING_WINDOW", "BUCKET_MIN_TRADES", "DEFAULT_RISK_MULT", "META_STATE_KEY",
]
