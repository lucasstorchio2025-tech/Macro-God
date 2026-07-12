"""strategy_bridge.py — adapta o sinal do engine pro formato do executor ao vivo.

O engine (engine/signals.py) trabalha com DataFrames de histórico. O executor
ao vivo trabalha com a API MetaTrader5. Esta ponte converte:

  1. Pega histórico H4 do MT5 (copy_rates_from_pos) → DataFrame que o engine entende.
  2. Instancia a estratégia escolhida (default: TSMomentumStrategy, que venceu o backtest).
  3. Computa regime atual (RuleBasedRegime) com VIX de agora.
  4. Devolve sinais {symbol: (direction, size_frac)} no formato que o executor usa.
  5. Agora TAMBÉM devolve contexto detalhado para logging de decisão.

Por que existe: isola o executor de detalhes do engine. Se amanhã trocarmos
ts_momentum por outra estratégia, só muda aqui.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from engine import config as C
from engine.signals import TSMomentumStrategy
from engine.regime import RuleBasedRegime
from engine.data import load_vix, load_spy, load_prices, _mt5_to_df, gold_equity_corr
from engine.indicators import ts_momentum_signal


# Singleton: estratégia é stateless entre chamadas (só precisa do histórico atual).
_STRATEGY = None
_REGIME = None
_VIX = None


def _get_strategy():
    global _STRATEGY
    if _STRATEGY is None:
        _STRATEGY = TSMomentumStrategy()
    return _STRATEGY


def _compute_gold_equity_corr():
    """Tenta calcular correlação ouro×ações para o detector de risk_on genuíno.

    Tenta duas fontes para XAUUSD:
      1. Cache local (parquet do load_prices)
      2. Conexão rápida ao MT5
    SPY vem do yfinance (cache diário).

    Se falhar, retorna None (regime conservador: VIX baixo = 'normal').
    """
    try:
        # 1. SPY (yfinance, cache diário)
        spy = load_spy(period="2y")
        if spy is None or len(spy) < 60:
            return None

        # 2. XAUUSD preços
        xau = None
        try:
            # Tenta cache local primeiro (mais rápido, não precisa de MT5)
            xau = load_prices("XAUUSDm", timeframe="H4", bars=500, use_cache=True)
        except Exception:
            xau = None

        if xau is None or len(xau) < 60:
            return None

        # 3. Reamostra XAUUSD H4 → diário
        xau_daily = xau["close"].resample("D").last().dropna()
        if len(xau_daily) < 60:
            return None

        # 4. Calcula correlação (C já importado no módulo)
        corr = gold_equity_corr(spy, xau_daily, window=C.GE_CORR_WINDOW_DAYS)
        if corr is not None and len(corr.dropna()) > 20:
            print(f"[bridge] Correlação gold×ações calculada: {corr.iloc[-1]:+.3f} (último valor)")
            return corr
        return None
    except Exception as e:
        print(f"[bridge] gold_equity_corr indisponível ({e}) — regime conservador")
        return None


def _get_regime():
    global _REGIME, _VIX
    if _VIX is None:
        try:
            _VIX = load_vix(period="max")
        except Exception:
            _VIX = None
    if _REGIME is None:
        # Tenta calcular correlação gold×ações para risk_on genuíno
        ge_corr = _compute_gold_equity_corr()
        _REGIME = RuleBasedRegime(vix=_VIX, prices_for_corr=None, gold_equity_corr=ge_corr)
    return _REGIME


def fetch_recent_prices(mt5, bars: int = C.MOMENTUM_LOOKBACK_BARS + 50) -> dict[str, pd.DataFrame]:
    """Puxa histórico H4 recente de TODOS os símbolos para alimentar a estratégia.

    Reusa _mt5_to_df do data.py pra manter formato consistente com o backtest.
    """
    out = {}
    for sym in C.SYMBOLS:
        if not mt5.symbol_select(sym, True):
            continue
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_H4, 0, bars)
        if rates is None or len(rates) == 0:
            continue
        out[sym] = _mt5_to_df(rates)
    return out


# ═════════════════════════════ NOVO: CONTEXTO RICO ═════════════════════════════
def compute_signal_detail(mt5, symbol: str, prices: dict[str, pd.DataFrame],
                          regime_now: str) -> dict:
    """Retorna o raciocínio DETALHADO por trás do sinal de um símbolo.

    Isto é o que vai pro decision_log.jsonl — explica POR QUE o bot decidiu
    comprar, vender, ou ignorar este símbolo neste ciclo.

    Retorna dict com:
      - direction: "BUY" | "SELL" | "NONE"
      - momentum_signal: float (retorno passado %)
      - regime: regime atual
      - session: sessão baseada na hora UTC
      - atr: ATR atual
      - spread: spread atual em pontos
      - reason: string legível explicando a decisão
    """
    from engine.indicators import atr as calc_atr

    detail = {
        "symbol": symbol,
        "regime": regime_now,
        "session": _session_name(),
    }

    # ATR
    df = prices.get(symbol)
    if df is not None and len(df) > 20:
        a = calc_atr(df).iloc[-1]
        detail["atr"] = round(float(a), 8) if pd.notna(a) else None
    else:
        detail["atr"] = None

    # Spread
    try:
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            detail["spread_points"] = round((tick.ask - tick.bid) / mt5.symbol_info(symbol).point if mt5.symbol_info(symbol) else 0)
        else:
            detail["spread_points"] = None
    except Exception:
        detail["spread_points"] = None

    # Momentum signal
    df = prices.get(symbol)
    if df is not None and len(df) >= C.MOMENTUM_LOOKBACK_BARS:
        mom = ts_momentum_signal(df).iloc[-1]
        if np.isfinite(mom):
            detail["momentum_signal_pct"] = round(float(mom) * 100, 3)
            if mom > C.MOMENTUM_MIN_ABS_R:
                detail["direction"] = "BUY"
                detail["momentum_strength"] = "bullish"
                detail["momentum_size"] = round(float(mom), 4)
                detail["reason"] = f"Momentum de alta ({mom*100:+.3f}% retorno passado)"
            elif mom < -C.MOMENTUM_MIN_ABS_R:
                detail["direction"] = "SELL"
                detail["momentum_strength"] = "bearish"
                detail["momentum_size"] = round(float(mom), 4)
                detail["reason"] = f"Momentum de baixa ({mom*100:+.3f}% retorno passado)"
            else:
                detail["direction"] = "NONE"
                detail["momentum_strength"] = "weak"
                detail["momentum_size"] = round(float(mom), 4)
                detail["reason"] = f"Momentum fraco ({mom*100:+.3f}%) — abaixo do threshold {C.MOMENTUM_MIN_ABS_R*100:.2f}%"
        else:
            detail["direction"] = "NONE"
            detail["reason"] = "Sinal de momentum inválido (NaN)"
    else:
        detail["direction"] = "NONE"
        detail["reason"] = f"Dados insuficientes ({len(df) if df is not None else 0} barras, mínimo {C.MOMENTUM_LOOKBACK_BARS})"
        detail["momentum_signal_pct"] = None

    return detail


def _session_name() -> str:
    """Classifica hora UTC em sessão forex."""
    h = pd.Timestamp.utcnow().hour
    if 0 <= h < 4:
        return "Sydney"
    elif 4 <= h < 8:
        return "Tokyo"
    elif 7 <= h < 16:
        return "London"
    elif 13 <= h < 22:
        return "NewYork"
    return "Off"


# ═════════════════════════════ COMPUTE LIVE SIGNALS (modificado) ═════════════════════════════
def compute_live_signals(mt5) -> dict[str, tuple[str, float]]:
    """Ponto de entrada único pro executor. Devolve {symbol: (direction, size_frac)}.

    direction in {"BUY","SELL","NONE"}. size_frac em [0,1] = fração da conta a arriscar.
    """
    prices = fetch_recent_prices(mt5)
    if not prices:
        return {}

    now_ts = pd.Timestamp.utcnow()
    regime = _get_regime()
    regime_now = regime.at(now_ts, {"prices": prices})

    strategy = _get_strategy()
    ctx = {
        "ts": now_ts,
        "prices": prices,
        "balance": 0.0,
        "open": [],
        "digits": {},
    }
    try:
        sigs = strategy.signals(ctx)
    except Exception as e:
        print(f"[bridge] estratégia falhou: {type(e).__name__}: {e}")
        return {}

    # aplica escala de regime (igual ao backtest)
    scale = C.EXPOSURE_SCALE.get(regime_now, 0.5)
    scaled = {}
    for sym, (direction, frac) in sigs.items():
        scaled[sym] = (direction, frac * scale)
    return scaled


# ═════════════════════════════ NOVO: sinais COM contexto completo ═════════════════════════════
def compute_signals_with_detail(mt5) -> tuple[dict[str, tuple[str, float]], dict[str, dict], str]:
    """Igual compute_live_signals, mas retorna também o detalhamento por símbolo + regime.

    Retorna:
      (sinais, detalhes_por_simbolo, regime_atual)

    O executor usa isso pra:
      - Abrir trades (com os sinais)
      - Logar decisão completa (com os detalhes)
    """
    prices = fetch_recent_prices(mt5)
    if not prices:
        return {}, {}, "unknown"

    now_ts = pd.Timestamp.utcnow()
    regime = _get_regime()
    regime_now = regime.at(now_ts, {"prices": prices})

    strategy = _get_strategy()
    ctx = {
        "ts": now_ts,
        "prices": prices,
        "balance": 0.0,
        "open": [],
        "digits": {},
    }
    try:
        sigs = strategy.signals(ctx)
    except Exception as e:
        print(f"[bridge] estratégia falhou: {type(e).__name__}: {e}")
        return {}, {}, regime_now

    scale = C.EXPOSURE_SCALE.get(regime_now, 0.5)

    # Monta detalhamento para CADA símbolo (inclusive os que não tiveram sinal)
    details = {}
    for sym in C.SYMBOLS:
        detail = compute_signal_detail(mt5, sym, prices, regime_now)
        details[sym] = detail

    # Preenche direção e tamanho dos que tiveram sinal
    scaled = {}
    for sym, (direction, frac) in sigs.items():
        scaled[sym] = (direction, frac * scale)
        if sym in details:
            details[sym]["direction"] = direction
            details[sym]["size_frac"] = round(frac * scale, 4)
            details[sym]["reason"] = f"Momentum confirmado. Escala de regime aplicada: {scale}"

    return scaled, details, regime_now


def get_current_regime() -> str:
    """Atalho pro executor perguntar o regime atual sem computar sinais."""
    return _get_regime().at(pd.Timestamp.utcnow(), {})


__all__ = [
    "compute_live_signals", "compute_signals_with_detail",
    "compute_signal_detail", "get_current_regime",
    "fetch_recent_prices",
]
