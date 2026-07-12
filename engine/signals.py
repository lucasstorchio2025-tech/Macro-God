"""signals.py — estratégias como plugins com interface comum.

Cada estratégia implementa .signals(ctx) -> dict[symbol -> (direction, size_frac)].

As 3 que comparo no VERDICT:
  - TSMomentumStrategy     : time-series momentum cross-asset (Moskowitz 2012).
                             Compra quem subiu, vende quem caiu, na janela.
  - COTContrarianStrategy  : age só em EXTREMOS de posicionamento (z-score>=2),
                             como CONTRARIAN. Corrige o uso do bot antigo.
  - LegacyCOTStrategy      : reproduz a lógica ATUAL do executor.py (COT como
                             momentum, sem z-score, sem extremo). Espera-se que
                             PERCA — é a prova de que o approach antigo era ruim.

O número decide qual vence. Eu não decido a priori.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np
import pandas as pd

from . import config as C
from .indicators import ts_momentum_signal, atr, zscore
from . import sizing as SZ


class Strategy(ABC):
    """Interface comum. ctx = {'ts', 'prices', 'balance', 'open', 'digits', 'cot', ...}"""

    name: str = "base"

    @abstractmethod
    def signals(self, ctx: dict) -> dict[str, tuple[str, float]]:
        """Devolve {symbol: (direction, size_frac)} só das entradas desejadas."""
        ...

    # helper comum: corr_pairs pré-computados (uma vez por run)
    def _corr_pairs(self, prices: dict):
        from .indicators import rolling_correlation_matrix
        return rolling_correlation_matrix(prices, C.CORREL_LOOKBACK_BARS)[0]


# ═════════════════════════════ TS-MOMENTUM CROSS-ASSET ═════════════════════════════
class TSMomentumStrategy(Strategy):
    """Time-series momentum (Moskowitz, Ooi, Pedersen 2012).

    Sinal por ativo: retorno passado (lookback - skip) barras.
      > +MIN_ABS_R  → BUY
      < -MIN_ABS_R  → SELL
      otherwise     → NONE
    Tamanho passa pelo vol-targeting + cap de correlação (sizing.py).
    """
    name = "ts_momentum"

    def __init__(self):
        self._corr = None

    def signals(self, ctx: dict) -> dict[str, tuple[str, float]]:
        ts = ctx["ts"]
        prices = ctx["prices"]
        out: dict[str, tuple[str, float]] = {}
        for sym, df in prices.items():
            past = df.loc[:ts]
            if len(past) < C.MOMENTUM_LOOKBACK_BARS:
                continue
            mom = ts_momentum_signal(past).iloc[-1]
            if not np.isfinite(mom):
                continue
            if mom > C.MOMENTUM_MIN_ABS_R:
                direction = "BUY"
            elif mom < -C.MOMENTUM_MIN_ABS_R:
                direction = "SELL"
            else:
                continue  # NONE — ignora pares sem momentum claro
            # tamanho via sizing (vol-target + correlação + regime já aplicado no motor)
            frac = SZ.compute_size_frac(
                sym, prices, ts, ctx.get("open", []),
                base_frac=1.0, regime_scale=1.0,
                corr_pairs=self._corr if self._corr is not None else None,
            )
            if frac <= 0:
                continue
            out[sym] = (direction, frac)
        return out


# ═════════════════════════════ COT CONTRARIAN (z-score) ═════════════════════════════
class COTContrarianStrategy(Strategy):
    """Uso INSTITUCIONAL real do COT: contrarian em extremos.

    Só age quando o posicionamento está em extremo estatístico (|z| >= 2):
      - Especulador MUITO comprado (z >= +2) → SELL (trade lotado = revert)
      - Esspeculador MUITO vendido  (z <= -2) → BUY
    Isto é o oposto do bot antigo, que comprava junto com o positioning.

    Requer ctx['cot'] = DataFrame histórico (data.py.load_cot_history).
    Requer mapeamento símbolo→moedas (EURUSDm → EUR base, USD quote).
    """
    name = "cot_contrarian"

    SYMBOL_CCY = {
        "EURUSDm": ("EUR", "USD"), "GBPUSDm": ("GBP", "USD"),
        "USDJPYm": ("USD", "JPY"),  "XAUUSDm": ("XAU", "USD"),
    }

    def __init__(self, cot_history: pd.DataFrame):
        self._cot = cot_history
        # z-score por moeda, pré-computado
        self._z = cot_history.apply(lambda s: zscore(s, C.COT_ZSCORE_LOOKBACK_WEEKS))
        self._corr = None

    def signals(self, ctx: dict) -> dict[str, tuple[str, float]]:
        ts = ctx["ts"]
        prices = ctx["prices"]
        out = {}
        if self._z is None or self._z.empty:
            return out
        # z válido em ts: última linha <= ts (sem lookahead)
        valid = self._z.loc[self._z.index <= ts]
        if valid.empty:
            return out
        row = valid.iloc[-1]

        for sym, (base, quote) in self.SYMBOL_CCY.items():
            if sym not in prices:
                continue
            zb = row.get(base)
            zq = row.get(quote)
            if not np.isfinite(zb) and not np.isfinite(zq):
                continue
            # combina: sinal contrarian por moeda. Base comprada(saturada) → bearish par.
            score = 0.0
            if np.isfinite(zb):
                score += -zb   # base muito comprada → vende o par
            if np.isfinite(zq):
                score += +zq   # quote muito comprada → compra o par (quote cara = par barato)
            if score >= C.COT_ZSCORE_ENTRY:
                direction = "SELL"
            elif score <= -C.COT_ZSCORE_ENTRY:
                direction = "BUY"
            else:
                continue
            frac = SZ.compute_size_frac(
                sym, prices, ts, ctx.get("open", []),
                base_frac=min(1.0, abs(score) / 4.0),  # convicção escala com extremo
                regime_scale=1.0,
                corr_pairs=self._corr if self._corr is not None else None,
            )
            if frac <= 0:
                continue
            out[sym] = (direction, frac)
        return out


# ═════════════════════════════ LEGACY (lógica atual do bot — baseline a superar) ═════════════════════════════
class LegacyCOTStrategy(Strategy):
    """Reproduz a lógica ATUAL do executor.py.decide_direction_for_symbol.

    COT como MOMENTUM: especulador comprado na base → BUY (junto com o fluxo),
    sem z-score, sem filtro de extremo, sem regime. Esta é a estratégia que
    perdeu $90 na demo. Rodar ela no backtest serve pra PROVAR em número que o
    approach era ruim — é o baseline que as outras duas precisam superar.
    """
    name = "legacy_cot"

    SYMBOL_CCY = COTContrarianStrategy.SYMBOL_CCY

    def __init__(self, cot_history: pd.DataFrame):
        self._cot = cot_history
        self._corr = None

    def signals(self, ctx: dict) -> dict[str, tuple[str, float]]:
        ts = ctx["ts"]
        prices = ctx["prices"]
        out = {}
        if self._cot is None or self._cot.empty:
            return out
        valid = self._cot.loc[self._cot.index <= ts]
        if valid.empty:
            return out
        row = valid.iloc[-1]

        for sym, (base, quote) in self.SYMBOL_CCY.items():
            if sym not in prices:
                continue
            nb = row.get(base)
            nq = row.get(quote)
            # lógica do executor.py: base comprada → bullish par (+1); quote comprada → bearish (-1)
            # (USD tem tratamento especial mas simplificamos pro genérico aqui)
            cot_signal = 0
            if np.isfinite(nb):
                cot_signal += 1 if nb > 0 else -1
            if np.isfinite(nq):
                cot_signal += -1 if nq > 0 else 1
            # threshold |cot_signal*2| >= 2  (do executor.py)
            bias = cot_signal * 2
            if bias >= 2:
                direction = "BUY"
            elif bias <= -2:
                direction = "SELL"
            else:
                continue
            frac = SZ.compute_size_frac(
                sym, prices, ts, ctx.get("open", []),
                base_frac=1.0, regime_scale=1.0,
                corr_pairs=self._corr if self._corr is not None else None,
            )
            if frac <= 0:
                continue
            out[sym] = (direction, frac)
        return out


__all__ = ["Strategy", "TSMomentumStrategy",
           "COTContrarianStrategy", "LegacyCOTStrategy"]
