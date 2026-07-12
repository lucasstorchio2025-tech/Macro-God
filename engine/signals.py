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


# ═════════════════════════════ MEAN REVERSION (Bollinger-like) ═════════════════════════════
class MeanReversionStrategy(Strategy):
    """Mean reversion em XAUUSD H4.

    Compra quando o preço está significativamente ABAIXO da média móvel
    (z-score < -ENTRY_Z), vende quando está ACIMA (z-score > +ENTRY_Z).
    Ideal para ouro em períodos de consolidação/range.

    Parâmetros:
      LOOKBACK: 48 barras H4 (~8 dias) — janela da média móvel
      ENTRY_Z: 1.5 — desvios padrão para entrar (mais frouxo que COT)
      EXIT_Z: 0.0 — exit quando preço volta à média

    Lógica:
      - Calcula z-score do preço: (close - SMA) / rolling_std
      - z < -ENTRY_Z → BUY (oversold)
      - z > +ENTRY_Z → SELL (overbought)
      - z entre -EXIT_Z e +EXIT_Z → NONE (já reverteu)

    Baseado em: Bollinger (1992), Avellaneda & Stoikov (2008)
    """
    name = "mean_reversion"

    # Parametros (podem ser movidos pro config.py se validados)
    LOOKBACK = 48    # ~8 dias de H4
    ENTRY_Z = 1.5    # desvios padrao pra entrar
    EXIT_Z = 0.5     # desvios padrao pra sair (volta a media)
    MIN_ATR = 0.001  # ATR minimo pra evitar entrar em mercados mortos

    def __init__(self):
        self._corr = None

    def signals(self, ctx: dict) -> dict[str, tuple[str, float]]:
        ts = ctx["ts"]
        prices = ctx["prices"]
        out = {}
        for sym, df in prices.items():
            past = df.loc[:ts]
            if len(past) < self.LOOKBACK:
                continue
            close = past["close"]
            sma = close.rolling(self.LOOKBACK, min_periods=self.LOOKBACK).mean()
            std = close.rolling(self.LOOKBACK, min_periods=self.LOOKBACK).std()
            if std.iloc[-1] == 0 or not np.isfinite(std.iloc[-1]):
                continue
            z = (close.iloc[-1] - sma.iloc[-1]) / std.iloc[-1]

            # Verifica ATR minimo (mercado nao morto)
            a = atr(past).iloc[-1] if len(past) > 14 else 0
            if a < self.MIN_ATR or not np.isfinite(a):
                continue

            if z < -self.ENTRY_Z:
                direction = "BUY"
            elif z > self.ENTRY_Z:
                direction = "SELL"
            else:
                continue

            # Tamanho: convicção escala com |z| (quanto mais extremo, maior)
            z_abs = abs(z)
            base_frac = min(0.5, z_abs / 6.0)  # max 0.5 (metade do risco)
            frac = SZ.compute_size_frac(
                sym, prices, ts, ctx.get("open", []),
                base_frac=base_frac, regime_scale=1.0,
                corr_pairs=self._corr if self._corr is not None else None,
            )
            if frac <= 0:
                continue
            out[sym] = (direction, frac)
        return out


# ═════════════════════════════ BREAKOUT (Donchian) ═════════════════════════════
class BreakoutStrategy(Strategy):
    """Breakout de canal Donchian em XAUUSD H4.

    Compra quando o preço fecha ACIMA do canal de N períodos (breakout altista),
    vende quando fecha ABAIXO (breakout baixista).

    Parâmetros:
      CHANNEL_LOOKBACK: 96 barras H4 (~16 dias) — janela do canal
      CONFIRMATION_BARS: 1 — barras de confirmacao (1 = fecha acima/abaixo)
      MIN_ATR_MULT: 1.5 — ATR minimo como % do canal (evita falsos breakouts)

    Lógica:
      - High = max high dos ultimos N periodos
      - Low = min low dos ultimos N periodos
      - close > High * (1 - slippage) → BUY (rompeu resistencia)
      - close < Low * (1 + slippage) → SELL (rompeu suporte)

    Baseado em: Donchian (1960s), Turtle Traders (Richard Dennis)
    """
    name = "breakout"

    CHANNEL_LOOKBACK = 96     # ~16 dias de H4
    MIN_ATR_MULT = 1.5         # canal deve ser >= 1.5x ATR

    def __init__(self):
        self._corr = None

    def signals(self, ctx: dict) -> dict[str, tuple[str, float]]:
        ts = ctx["ts"]
        prices = ctx["prices"]
        out = {}
        for sym, df in prices.items():
            past = df.loc[:ts]
            if len(past) < self.CHANNEL_LOOKBACK:
                continue

            # Canal Donchian
            high = past["high"].rolling(self.CHANNEL_LOOKBACK).max()
            low = past["low"].rolling(self.CHANNEL_LOOKBACK).min()
            current_high = high.iloc[-1]
            current_low = low.iloc[-1]
            channel_width = current_high - current_low

            if channel_width <= 0 or not np.isfinite(channel_width):
                continue

            # ATR para filtro de qualidade
            a = atr(past).iloc[-1] if len(past) > 14 else 0
            if not np.isfinite(a) or a <= 0:
                continue

            # Canal deve ser largo o suficiente (>= MIN_ATR_MULT * ATR)
            if channel_width < self.MIN_ATR_MULT * a:
                continue

            close = past["close"].iloc[-1]

            # Breakout
            if close >= current_high * 0.999:  # tolerância de 0.1%
                direction = "BUY"
            elif close <= current_low * 1.001:  # tolerância de 0.1%
                direction = "SELL"
            else:
                continue

            # Tamanho: fracao base 0.3 (breakout é menos frequente mas mais explosivo)
            frac = SZ.compute_size_frac(
                sym, prices, ts, ctx.get("open", []),
                base_frac=0.3, regime_scale=1.0,
                corr_pairs=self._corr if self._corr is not None else None,
            )
            if frac <= 0:
                continue
            out[sym] = (direction, frac)
        return out


__all__ = ["Strategy", "TSMomentumStrategy",
           "COTContrarianStrategy", "LegacyCOTStrategy",
           "MeanReversionStrategy", "BreakoutStrategy"]
