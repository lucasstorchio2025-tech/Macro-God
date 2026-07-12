"""regime.py — detector de regime de mercado, plugável.

A exigência central do projeto: o sistema precisa se adaptar quando o jogo muda
(paz / guerra / crise / superávit). A adaptação mecânica acontece em 2 níveis:

  1. GATE DE EXPOSIÇÃO (aqui): classifica o estado atual em 4 regimes e escala
     o tamanho das novas entradas. Em "crise" (VIX alto OU correlação ≈1 entre
     pares), o sistema vai quase flat — sobrevive, não ataca.
  2. SIZING POR VOL (sizing.py): ativo nervoso → tamanho menor, automaticamente.

Decisão de arquitetura (eu decidi, conforme você pediu): REGRAS como motor,
não ML/HMM. Razão: regimes de crise são RAROS por definição (um 2008, um COVID
em décadas). Treinar ML em poucas crises = overfit garantido. Regras de
vol/VIX/correlação têm base acadêmica (Target Volatility funds, AQR) e funcionam
EXATAMENTE quando ML falha — em pânico.

Deixo a interface `RegimeProvider` abstrata: `RuleBasedRegime` é a implementação;
`HMMRegime` é o slot futuro (costura), encaixa sem reescrever nada quando houver
orçamento pra mais dados.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np
import pandas as pd

from . import config as C
from .indicators import rolling_correlation_matrix, max_pair_correlation


REGIMES = ("risk_on", "normal", "risk_off", "crisis")


class RegimeProvider(ABC):
    """Interface: dado um instante + contexto, devolve o regime vigente."""

    @abstractmethod
    def at(self, ts: pd.Timestamp, ctx: dict) -> str:
        """Retorna um de REGIMES."""
        ...


# ═════════════════════════════ REGIME POR REGRAS ═════════════════════════════
class RuleBasedRegime(RegimeProvider):
    """Detector por regras, sem lookahead.

    Três camadas, aplicadas EM ORDEM:
      1. VIX BASE (volatilidade): VIX + percentil → regime base
      2. GOLD-EQUITY CORRELATION (verdadeiro risk_on):
         Correlação rolante entre retornos diários de XAUUSD e SPY.
         - Correlação NEGATIVA (ouro cai quando ações sobem) = RISK_ON verdadeiro
         - Correlação POSITIVA (ouro e ações andam juntos) = NÃO é risk_on
           (driver comum: USD fraco, inflação)
      3. LIQUIDITY STRESS (flight-to-dollar): DXY + VIX disparam juntos

    Estados finais:
      crisis    : pânico confirmado → exposição 0
      risk_off  : estresse/medo → exposição reduzida
      normal    : sem viés forte → exposição padrão
      risk_on   : apetite a risco GENUÍNO → exposição cheia
    """

    def __init__(self, vix: Optional[pd.Series] = None,
                 prices_for_corr: Optional[dict] = None,
                 gold_equity_corr: Optional[pd.Series] = None):
        """
        Args:
            vix: Série diária do VIX
            prices_for_corr: Dict de preços H4 para calcular correlação entre pares
            gold_equity_corr: Série diária de correlação rolante XAUUSD vs SPY
                (pré-computada por data.gold_equity_corr())
        """
        self._vix = vix
        self._prices_corr = prices_for_corr
        self._gold_equity_corr = gold_equity_corr
        self._vix_pct = None
        self._corr_pairs = None
        if vix is not None and len(vix):
            self._vix_pct = _rolling_percentile(vix, C.VIX_PERCENTILE_LOOKBACK_DAYS)
        if prices_for_corr is not None:
            self._corr_pairs, _ = rolling_correlation_matrix(
                prices_for_corr, C.CORREL_LOOKBACK_BARS)

    def at(self, ts: pd.Timestamp, ctx: dict) -> str:
        vix_val = _last_known(self._vix, ts)
        vix_pct = _last_known(self._vix_pct, ts) if self._vix_pct is not None else None

        # ═══════════════════════════════════════════════════════════════
        # CAMADA 1: CRISIS (sobrepõe tudo)
        # ═══════════════════════════════════════════════════════════════
        if vix_val is not None and vix_val >= C.VIX_CRISIS_ABS:
            return "crisis"
        if vix_pct is not None and vix_pct >= C.VIX_CRISIS_PERCENTILE:
            return "crisis"
        if self._corr_pairs is not None:
            corr_max = _max_corr_at(self._corr_pairs, ts)
            if corr_max is not None and corr_max >= C.CORREL_CRISIS_THRESHOLD:
                return "crisis"

        # ═══════════════════════════════════════════════════════════════
        # CAMADA 2: REGIME BASE (VIX)
        # ═══════════════════════════════════════════════════════════════
        # VIX no percentil 80-95 = risk_off (estresse)
        if vix_pct is not None and vix_pct >= C.VIX_RISKOFF_PERCENTILE:
            base_regime = "risk_off"
        # VIX ≤ 33º percentil = baixa volatilidade (calmaria, NÃO necessariamente risk_on)
        elif vix_pct is not None and vix_pct <= 33:
            base_regime = "vix_calm"  # NÃO é risk_on ainda — precisa confirmar
        else:
            base_regime = "normal"

        # ═══════════════════════════════════════════════════════════════
        # CAMADA 3: GOLD-EQUITY CORRELATION (verdadeiro risk_on)
        # ═══════════════════════════════════════════════════════════════
        # A correlação XAUUSD vs SPY revela a natureza do movimento:
        #   - NEGATIVA: ouro cai quando ações sobem → RISK_ON GENUÍNO
        #     (capital saindo de safe haven para risco)
        #   - POSITIVA: ouro e ações andam juntos → OUTRO DRIVER
        #     (USD fraco, inflação, política monetária — NÃO é risk_on)
        gold_corr = _last_known(self._gold_equity_corr, ts) if self._gold_equity_corr is not None else None

        if gold_corr is not None and pd.notna(gold_corr):
            if gold_corr <= C.GE_CORR_RISKON_THRESHOLD:
                # Correlação negativa = risk_on GENUÍNO
                if base_regime == "vix_calm":
                    base_regime = "risk_on"  # confirmado: capital saindo de ouro para ações
                elif base_regime == "normal":
                    base_regime = "risk_on"  # upgrade: há apetite a risco mesmo com VIX moderado
            elif gold_corr >= C.GE_CORR_FAKE_RISKON_THRESHOLD:
                # Correlação positiva = NÃO é risk_on (ouro e ações sobem juntos)
                if base_regime == "vix_calm":
                    base_regime = "normal"  # downgrade: VIX baixo mas não é risk_on
                elif base_regime == "normal" and gold_corr >= C.GE_CORR_PANIC_THRESHOLD:
                    # Correlação positiva forte: tudo andando junto = algo sistêmico
                    # Verifica se AMBOS estão caindo (pânico)
                    spy_ret = _last_known(ctx.get("spy_return"), ts) if ctx else None
                    if spy_ret is not None and spy_ret < -0.02:
                        base_regime = "risk_off"  # pânico: tudo cai junto
            else:
                # Correlação próxima de zero (entre -0.15 e +0.25): sem sinal claro
                # Regime base (VIX) dita, sem confirmação de risk_on
                if base_regime == "vix_calm":
                    base_regime = "normal"
        else:
            # Sem dados de correlação: VIX baixo vira "normal", não risk_on
            if base_regime == "vix_calm":
                base_regime = "normal"

        # ═══════════════════════════════════════════════════════════════
        # CAMADA 4: LIQUIDITY STRESS / DOLLAR SAFE-HAVEN
        # ═══════════════════════════════════════════════════════════════
        # Walk-forward validation (WALK_FORWARD.md) mostrou que este sinal NÃO
        # agregou valor OOS (0/8 janelas). Mantido no código com flag de
        # liga/desliga (DXY_LIQUIDITY_STRESS_ENABLED) para re-testes futuros.
        if C.DXY_LIQUIDITY_STRESS_ENABLED:
            dxy_chg = ctx.get("dxy_pct_change") if ctx else None
            vix_chg = ctx.get("vix_pct_change") if ctx else None

            if dxy_chg is not None and vix_chg is not None:
                dxy_up = dxy_chg >= C.DXY_LIQUIDITY_STRESS_UP_PCT
                vix_up = vix_chg >= C.VIX_LIQUIDITY_STRESS_UP_PCT
                dxy_very_strong = dxy_chg >= C.DXY_LIQUIDITY_STRESS_UP_PCT * 2

                if dxy_up and vix_up:
                    # Flight-to-dollar confirmado: escala o regime pra cima
                    if base_regime == "normal":
                        return "risk_off"
                    elif base_regime == "risk_off":
                        return "crisis"
                    elif base_regime == "risk_on":
                        return "risk_off"  # stress de liquidez > risk_on
                elif dxy_very_strong and base_regime != "crisis":
                    if base_regime == "risk_on":
                        return "normal"

        return base_regime


# ═════════════════════════════ NO-OP (sem gate) ═════════════════════════════
class AlwaysNormalRegime(RegimeProvider):
    """Para comparar com vs sem regime no backtest. Devolve 'normal' sempre."""
    def at(self, ts, ctx): return "normal"


# ═════════════════════════════ HMM (stub — costura futura) ═════════════════════════════
class HMMRegime(RegimeProvider):
    """SLOT FUTURO. Não implementado agora — quando houver orçamento pra
    alternative data / série longa de features, treina estados hidden e pluga
    aqui. Mesma interface, motor não muda nada.

    Por ora, levanta NotImplementedError se usado — pra ninguém ativar por engano.
    """
    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "HMMRegime é slot futuro. Use RuleBasedRegime por ora. "
            "Implementar quando houver orçamento pra features extras."
        )

    def at(self, ts, ctx):  # pragma: no cover
        raise NotImplementedError


# ═════════════════════════════ HELPERS ═════════════════════════════
def _rolling_percentile(s: pd.Series, window: int) -> pd.Series:
    """Percentil do último valor dentro da janela rolante (causal)."""
    def _pct(block):
        if len(block) < 2:
            return np.nan
        return (block.iloc[:-1] <= block.iloc[-1]).mean() * 100.0
    return s.rolling(window, min_periods=max(5, window // 10)).apply(_pct, raw=False)


def _last_known(s: Optional[pd.Series], ts: pd.Timestamp) -> Optional[float]:
    """Último valor VÁLIDO (não-NaN) até ts inclusive. Sem lookahead."""
    if s is None or s.empty:
        return None
    sub = s.loc[:ts]
    sub = sub.dropna()
    if sub.empty:
        return None
    return float(sub.iloc[-1])


def _max_corr_at(corr_pairs, ts: pd.Timestamp) -> Optional[float]:
    """Maior correlação par-a-par conhecida até ts."""
    vals = []
    for _a, _b, roll in corr_pairs:
        sub = roll.loc[:ts].dropna()
        if not sub.empty:
            vals.append(float(sub.iloc[-1]))
    return max(vals) if vals else None


__all__ = ["RegimeProvider", "RuleBasedRegime", "AlwaysNormalRegime",
           "HMMRegime", "REGIMES"]
