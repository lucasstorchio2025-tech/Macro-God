"""indicators.py — cálculos vetorizados sobre séries OHLCV.

Reuso a fórmula de ATR do market_intelligence.py:218 (que já funciona na prática).
Resto é novo: vol realizada, momentum, correlação rolante — tudo em pandas, sem
loops Python por barra (velocidade pra rodar 15 anos de H4 em segundos).

Todos os indicadores aqui são CAUSAL: só olham pra trás. Nada de centered/lookahead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


# ─────────────── ATR (reaproveitado de market_intelligence.py:218) ───────────────
def atr(df: pd.DataFrame, period: int = C.ATR_PERIOD) -> pd.Series:
    """Average True Range. Mesma lógica do bot original, mas vetorizada.

    True Range = max(high-low, |high-prev_close|, |low-prev_close|).
    ATR = média móvel simples do TR nos últimos `period` barras.
    """
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


# ─────────────── Vol realizada ───────────────
def realized_vol(df: pd.DataFrame, window: int = C.VOL_LOOKBACK_BARS,
                 annualize: bool = True) -> pd.Series:
    """Volatilidade realizada dos retornos log, em janela rolante.

    Em H4: 6 barras/dia × 252 = ~1512 barras/ano. Annualiza raiz(1512).
    Essencial pro vol-targeting: ativo nervoso → vol alta → tamanho cai.
    """
    rets = np.log(df["close"] / df["close"].shift(1))
    vol = rets.rolling(window, min_periods=window // 2).std()
    if annualize:
        bars_per_year = 6 * 252  # H4 ≈ 6 barras/dia úteis
        vol = vol * np.sqrt(bars_per_year)
    return vol


# ─────────────── Momentum (time-series) ───────────────
def ts_momentum_signal(df: pd.DataFrame,
                       lookback: int = C.MOMENTUM_LOOKBACK_BARS,
                       skip: int = C.MOMENTUM_SKIP_BARS) -> pd.Series:
    """Retorno passado (lookback - skip) barras atrás até `skip` atrás.

    Moskowitz/Ooi/Pedersen 2012: vai LONG se > 0, SHORT se < 0.
    Skip do final evita captar rebote de curtíssimo prazo.
    """
    close = df["close"]
    return (close.shift(skip) / close.shift(lookback)) - 1.0


# ─────────────── Correlação rolante entre pares ───────────────
def rolling_correlation_matrix(prices: dict[str, pd.DataFrame],
                               window: int = C.CORREL_LOOKBACK_BARS) -> pd.DataFrame:
    """Matriz de correlação rolante entre os retornos dos símbolos.

    Retorna painel: MultiIndex (timestamp, (sym_a, sym_b)) -> correlação.
    O sizing.py usa isso pra detectar "mesma aposta" (ex: EURUSD ≈ GBPUSD).
    """
    # alinha retornos num DataFrame wide
    rets = pd.DataFrame({s: np.log(d["close"] / d["close"].shift(1)) for s, d in prices.items()})
    rets = rets.dropna(how="all")

    # correlação rolante par a par (mais robusto que corr() em painel)
    syms = list(rets.columns)
    pairs = []
    idx = rets.index
    for i, a in enumerate(syms):
        for b in syms[i + 1:]:
            roll = rets[a].rolling(window, min_periods=window // 2).corr(rets[b])
            pairs.append((a, b, roll))
    return pairs, syms


def max_pair_correlation(prices: dict[str, pd.DataFrame],
                         window: int = C.CORREL_LOOKBACK_BARS,
                         at_idx: pd.Timestamp | None = None) -> float:
    """Maior correlação par-a-par no instante at_idx. Usado pro regime de crise."""
    pairs, _ = rolling_correlation_matrix(prices, window)
    vals = []
    for a, b, roll in pairs:
        if at_idx in roll.index:
            v = roll.loc[at_idx]
            if pd.notna(v):
                vals.append(v)
    return max(vals) if vals else float("nan")


# ─────────────── Z-score (pra COT contrarian) ───────────────
def zscore(series: pd.Series, lookback: int = C.COT_ZSCORE_LOOKBACK_WEEKS) -> pd.Series:
    """Z-score rolante: (x - média_lookback) / std_lookback. Causal."""
    mean = series.rolling(lookback, min_periods=lookback // 3).mean()
    std  = series.rolling(lookback, min_periods=lookback // 3).std()
    return (series - mean) / std


__all__ = [
    "atr", "realized_vol", "ts_momentum_signal",
    "rolling_correlation_matrix", "max_pair_correlation", "zscore",
]
