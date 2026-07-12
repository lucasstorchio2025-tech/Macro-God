"""sizing.py — dimensionamento de posição institucional.

Três correções ao erro central do bot antigo:

  1. VOL-TARGETING. Tamanho escala inversamente com a vol realizada do ativo.
     Ativo nervoso (crise) → tamanho menor, automaticamente. Sem isso, você
     arrisca o mesmo $ em EURUSD calmo e em ouro em pânico — loucura.

  2. CAP POR CORRELAÇÃO. EURUSD + GBPUSD não são 2 apostas, são ~1 (correlação
     alta no mesmo fator USD). Se 2+ pares > CORREL_DUP_LIMIT, divido o tamanho
     pra não duplicar exposição no mesmo fator.

  3. EXPOSIÇÃO USD AGREGADA. Somo o beta-USD de cada posição. Se passar do
     limite, rejeito a entrada. Isto é o que fundos grandes fazem: contam
     exposição por FATOR, não por "número de tickets".

Este módulo só COMPUTA tamanhos — não abre ordem. O backtest e o executor usam.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from . import config as C
from .indicators import realized_vol, rolling_correlation_matrix


# ═════════════════════════════ VOL-TARGET SCALAR ═════════════════════════════
def vol_target_scalar(sym: str, prices: pd.DataFrame,
                      at_ts: pd.Timestamp,
                      target_vol_annual: float = C.TARGET_VOL_PCT_ANNUAL / 100.0) -> float:
    """Fração [0..~1] do tamanho-base a usar, baseada em vol realizada.

    Princípio Target Volatility: tamanho ∝ (vol_alvo / vol_realizada).
    Se ativo tem vol 24% e alvo é 12%, tamanho = 0.5 (metade).
    Capado em [0.05, VOL_TARGET_CAP] pra evitar extremos numéricos.
    Sem cap, forex calmo (vol 5%) gerava 2.4x — overtrading.

    Retorna 0.5 (neutro) se vol realizada indisponível ainda.
    """
    past = prices.loc[:at_ts]
    if len(past) < C.VOL_LOOKBACK_BARS:
        return 0.5
    vol = realized_vol(past).iloc[-1]
    if not np.isfinite(vol) or vol <= 0:
        return 0.5
    return float(np.clip(target_vol_annual / vol, 0.05, C.VOL_TARGET_CAP))


# ═════════════════════════════ CAP POR CORRELAÇÃO ═════════════════════════════
def correlation_penalty(sym: str, open_symbols: list[str],
                        prices: dict[str, pd.DataFrame],
                        at_ts: pd.Timestamp,
                        corr_pairs=None) -> float:
    """Reduz tamanho se o novo símbolo é "a mesma aposta" de um já aberto.

    Se corr(sym, open) > CORREL_DUP_LIMIT, divide tamanho por 2 (não exclui —
    só evita duplicar exposição no mesmo fator). Múltiplos correlacionados
    acumulam a penalidade.
    """
    if not open_symbols or corr_pairs is None:
        return 1.0
    penalty = 1.0
    for other in open_symbols:
        if other == sym:
            continue
        rho = _pair_corr(corr_pairs, sym, other, at_ts)
        if rho is not None and rho >= C.CORREL_DUP_LIMIT:
            # cada par altamente correlado corta 50% do tamanho restante
            penalty *= 0.5
    return penalty


def _pair_corr(corr_pairs, a: str, b: str, ts: pd.Timestamp) -> Optional[float]:
    for x, y, roll in corr_pairs:
        if {x, y} == {a, b}:
            sub = roll.loc[:ts].dropna()
            return float(sub.iloc[-1]) if not sub.empty else None
    return None


# ═════════════════════════════ EXPOSIÇÃO USD AGREGADA ═════════════════════════════
def usd_exposure(open_positions: list, balance: float) -> float:
    """Soma do |beta-USD| × fração de risco de cada posição aberta.

    open_positions: lista de objetos c/ atributos .symbol e .size_frac (ou
    dicionários {symbol, size_frac}). Aceita ambos.
    Retorna a exposição USD agregada em "unidades de risco relativo".
    Se > USD_EXPOSURE_CAP, a nova entrada é rejeitada.
    """
    total = 0.0
    for p in open_positions:
        sym = getattr(p, "symbol", p.get("symbol")) if isinstance(p, dict) else p.symbol
        frac = getattr(p, "size_frac", p.get("size_frac")) if isinstance(p, dict) else p.size_frac
        beta = C.USD_BETA.get(sym, 0.0)
        total += abs(beta) * frac
    return total


def can_open_given_usd(sym: str, open_positions: list, balance: float) -> bool:
    """True se adicionar `sym` mantém exposição USD abaixo do cap."""
    current = usd_exposure(open_positions, balance)
    added = abs(C.USD_BETA.get(sym, 0.0)) * 0.05  # fração mínima de referência
    return (current + added) <= C.USD_EXPOSURE_CAP


# ═════════════════════════════ COMBINADOR ═════════════════════════════
def compute_size_frac(sym: str, prices: dict[str, pd.DataFrame],
                      at_ts: pd.Timestamp, open_positions: list,
                      base_frac: float = 1.0,
                      regime_scale: float = 1.0,
                      corr_pairs=None) -> float:
    """Tamanho final de uma posição nova, combinando todas as camadas.

    Fração = base_frac
           × vol_target_scalar          (atenua ativo nervoso)
           × correlation_penalty        (evita duplicar fator)
           × regime_scale               (gate de crise)
    Capado em [0, 1]. Se exposição USD excederia o cap, devolve 0 (não abre).
    """
    if regime_scale <= 0.02:
        return 0.0
    if not can_open_given_usd(sym, open_positions, balance=1.0):
        return 0.0
    open_syms = [getattr(p, "symbol", p["symbol"]) if isinstance(p, dict) else p.symbol
                 for p in open_positions]
    vt = vol_target_scalar(sym, prices[sym], at_ts) if sym in prices else 0.5
    cp = correlation_penalty(sym, open_syms, prices, at_ts, corr_pairs)
    frac = base_frac * vt * cp * regime_scale
    return float(np.clip(frac, 0.0, 1.0))


__all__ = [
    "vol_target_scalar", "correlation_penalty", "usd_exposure",
    "can_open_given_usd", "compute_size_frac",
]
