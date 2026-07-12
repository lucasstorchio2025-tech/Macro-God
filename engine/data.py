"""data.py — carregamento de histórico, com cache local.

Duas fontes, ambas $0:
  1. Preço H4: MetaTrader5.copy_rates_from_pos (a mesma chamada que o bot
     original já usa com sucesso). Cache em parquet no disco pra não refazer.
  2. COT histórico multi-ano: CFTC Socrata (publicreporting.cftc.gov), grátis,
     sem chave. Reuso a URL que já está em market_intelligence.py:170, mas aqui
     puxo SÉRIE TEMPORAL (limite alto, ordenado por data) em vez de só a última.

  3. VIX histórico: yfinance ^VIX (grátis). Necessário pro detector de regime.

Nada aqui abre ordem. É leitura pura.
"""
from __future__ import annotations

import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from . import config as C

try:
    from dotenv import load_dotenv
    for _p in [str(Path.home() / ".hermes" / ".env")]:
        if os.path.exists(_p):
            load_dotenv(_p, override=False)
except ImportError:
    pass


# ═════════════════════════════ MT5 HELPERS ═════════════════════════════
_TF_MAP = {
    "M15": None, "H1": None, "H4": None, "D1": None,  # preenchido sob demanda
}


def _tf_const(timeframe: str):
    """Resolve o inteiro de timeframe do MT5 só quando necessário (lazy import)."""
    import MetaTrader5 as mt5
    mapping = {
        "M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1,
    }
    return mapping[timeframe]


def _connect_mt5() -> bool:
    import MetaTrader5 as mt5
    login = os.environ.get("EXNESS_LOGIN")
    if not login:
        return False
    return mt5.initialize(
        login=int(login),
        password=os.environ["EXNESS_PASSWORD"],
        server=os.environ["EXNESS_SERVER"],
        timeout=15000,
    )


def _mt5_to_df(rates) -> pd.DataFrame:
    """Converte array de rates do MT5 em DataFrame limpo, indexado por tempo UTC."""
    if rates is None or len(rates) == 0:
        return pd.DataFrame()
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("time")
    # mt5 devolve: open high low close tick_volume spread real_volume
    keep = ["open", "high", "low", "close", "tick_volume"]
    return df[[c for c in keep if c in df.columns]].astype(float)


# ═════════════════════════════ PREÇO H4 ═════════════════════════════
def load_prices(symbol: str, timeframe: str = C.TIMEFRAME,
                bars: int = C.BARS_LOOKBACK, use_cache: bool = True) -> pd.DataFrame:
    """Série OHLCV de um símbolo. Usa cache parquet se disponível.

    Retorna DataFrame com índice tz-aware UTC e colunas [open,high,low,close,tick_volume].
    """
    cache_file = C.CACHE_DIR / f"{symbol}_{timeframe}.parquet"

    # Tentativa de cache (só reusa se for "fresco" — mais de 1 dia = baixa de novo).
    if use_cache and cache_file.exists():
        try:
            cached = pd.read_parquet(cache_file)
            # checa se tem dado recente
            if len(cached) and (datetime.now(timezone.utc) - cached.index[-1]).days < 1:
                return cached
            # senão, baixa tudo de novo pra estender (mais barato que merge incremental)
        except Exception:
            pass

    # Download do MT5
    import MetaTrader5 as mt5
    connected = _connect_mt5()
    if not connected:
        # se tem cache mesmo velho, usa; senão erro
        if cache_file.exists():
            return pd.read_parquet(cache_file)
        raise RuntimeError(f"MT5 não conectou e não há cache para {symbol}")

    try:
        mt5.symbol_select(symbol, True)
        rates = mt5.copy_rates_from_pos(symbol, _tf_const(timeframe), 0, bars)
    finally:
        mt5.shutdown()

    df = _mt5_to_df(rates)
    if df.empty:
        raise RuntimeError(f"MT5 devolveu vazio para {symbol}")

    if use_cache:
        try:
            df.to_parquet(cache_file)
        except Exception:
            # fallback CSV se parquet falhar (sem pyarrow, etc.)
            df.to_csv(cache_file.with_suffix(".csv"))
    return df


def load_all_prices(timeframe: str = C.TIMEFRAME,
                    bars: int = C.BARS_LOOKBACK,
                    align: bool = True) -> dict[str, pd.DataFrame]:
    """Carrega todos os símbolos. Se align=True, restringe ao período comum."""
    out = {}
    for sym in C.SYMBOLS:
        df = load_prices(sym, timeframe, bars)
        out[sym] = df

    if align:
        start = max(df.index[0] for df in out.values())
        end   = min(df.index[-1] for df in out.values())
        out = {s: df.loc[start:end].copy() for s, df in out.items()}
    return out


# ═════════════AnimationFrame══════════════════════════════════════════
def load_vix(period: str = "max", use_cache: bool = True) -> pd.Series:
    """Série diária do VIX (^VIX) via yfinance. Retorna Series nomeada 'vix'."""
    cache_file = C.CACHE_DIR / "vix.csv"
    if use_cache and cache_file.exists():
        try:
            cached = pd.read_csv(cache_file, index_col=0, parse_dates=True)
            cached.index = pd.to_datetime(cached.index, utc=True)
            if len(cached) and (datetime.now(timezone.utc) - cached.index[-1]).days < 1:
                return cached["vix"]
        except Exception:
            pass

    import yfinance as yf
    hist = yf.Ticker("^VIX").history(period=period, auto_adjust=False)
    if hist.empty:
        if cache_file.exists():
            return pd.read_csv(cache_file, index_col=0, parse_dates=True)["vix"]
        raise RuntimeError("yfinance devolveu vazio para ^VIX")
    s = hist["Close"].rename("vix")
    s.index = s.index.tz_convert("UTC") if s.index.tz else s.index.tz_localize("UTC")
    s = s[~s.index.duplicated(keep="last")]
    if use_cache:
        s.to_frame().to_csv(cache_file)
    return s


def vix_resampled_to(tf_index: pd.DatetimeIndex, vix: Optional[pd.Series] = None) -> pd.Series:
    """Reamostra VIX diário pra alinhar com barras H4 (forward-fill: usa último VIX conhecido)."""
    if vix is None:
        vix = load_vix()
    # alinha: pra cada timestamp H4, pega o ÚLTIMO VIX diário conhecido (sem lookahead)
    return vix.reindex(tf_index, method="ffill").fillna(method="ffill")


# ═════════════════════════════ COT HISTÓRICO ═════════════════════════════
# Reuso a URL do market_intelligence.py:170, mas aqui como SÉRIE (limite alto).
_COT_BASE = "https://publicreporting.cftc.gov/resource/jun7-fc8e.json"
_COT_CURRENCIES = {
    "EUR": "EURO FX", "GBP": "BRITISH POUND", "JPY": "JAPANESE YEN",
    "AUD": "AUSTRALIAN DOLLAR", "CAD": "CANADIAN DOLLAR", "CHF": "SWISS FRANC",
    "XAU": "GOLD - COMMODITY EXCHANGE",
    "USD": "USD INDEX - ICE FUTURES",
}


def load_cot_history(weeks: int = C.COT_ZSCORE_LOOKBACK_WEEKS,
                     use_cache: bool = True) -> pd.DataFrame:
    """Série temporal de net positioning (noncomm long - short) por moeda.

    Retorna DataFrame indexado por data do relatório (semanal), uma coluna por moeda,
    valor = net contracts (especuladores long - short). Mesma fonte que o bot atual;
    aqui com histórico pra permitir z-score (extremos).
    """
    import requests
    cache_file = C.CACHE_DIR / "cot_history.csv"

    # Cache válido por 7 dias (COT sai 1x/semana)
    if use_cache and cache_file.exists():
        age_days = (datetime.now(timezone.utc) - datetime.fromtimestamp(
            cache_file.stat().st_mtime, tz=timezone.utc)).days
        if age_days < 7:
            try:
                df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
                # normaliza tz ao ler do CSV (que perde tz ao salvar)
                if df.index.tz is None:
                    df.index = df.index.tz_localize("UTC")
                return df.tail(weeks)
            except Exception:
                pass

    series: dict[str, pd.Series] = {}
    for code, name_frag in _COT_CURRENCIES.items():
        try:
            # SoQL order por data DESC, limite alto pra pegar histórico
            r = requests.get(_COT_BASE, params={
                "$q": name_frag,
                "$order": "report_date_as_yyyy_mm_dd DESC",
                "$limit": weeks + 20,
            }, timeout=20)
            rows = r.json()
            # Filtra "MICRO X" (queremos o contrato principal)
            data = {}
            for cand in rows:
                nm = (cand.get("market_and_exchange_names") or "").upper()
                if nm.startswith("MICRO "):
                    continue
                if code == "XAU" and "MICRO" in nm:
                    continue
                d = cand.get("report_date_as_yyyy_mm_dd", "")[:10]
                if not d:
                    continue
                longs   = int(cand.get("noncomm_positions_long_all", 0) or 0)
                shorts  = int(cand.get("noncomm_positions_short_all", 0) or 0)
                # pega só o primeiro (mais recente) por data
                if d not in data:
                    data[d] = longs - shorts
                break_in_name = False  # placeholder p/ legibilidade
            s = pd.Series(data, name=code, dtype=float)
            s.index = pd.to_datetime(s.index)
            s = s[~s.index.duplicated(keep="last")].sort_index()
            series[code] = s
        except Exception as e:
            print(f"[data] COT {code}: falhou ({type(e).__name__})")
            continue

    if not series:
        if cache_file.exists():
            df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            return df.tail(weeks)
        raise RuntimeError("COT histórico indisponível (sem rede e sem cache)")

    df = pd.DataFrame(series).sort_index()
    df.index.name = "report_date"
    # NORMALIZA timezone: COT é tz-naive vindo do CSV; o resto do engine é tz-aware UTC.
    # Forçar UTC pra toda comparação de índice funcionar (sem isso: TypeError tz-naive vs aware).
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    if use_cache:
        df.to_csv(cache_file)
    return df.tail(weeks)


def cot_at_date(cot_history: pd.DataFrame, target_date: pd.Timestamp) -> dict[str, float]:
    """Net positioning por moeda VÁLIDO em target_date (último relatório <= data).

    Crítico pra não usar lookahead: em t, só podemos conhecer o COT publicado até t.
    COT sai sexta à noite; uso a publicação mais recente <= target_date.
    """
    if cot_history.empty:
        return {}
    # última linha cujo índice <= target_date
    valid = cot_history.loc[cot_history.index <= target_date]
    if valid.empty:
        return {}
    row = valid.iloc[-1]
    return {k: float(v) for k, v in row.items() if pd.notna(v)}


# ═════════════════════════════ DXY (US Dollar Index) ═════════════════════════════
def load_dxy(period: str = "max", use_cache: bool = True) -> pd.Series:
    """Série do US Dollar Index (DX-Y.NYB) via yfinance, fechamento diário.

    Necessário pro detector de liquidez/stress: quando DXY sobe forte + VIX sobe,
    é flight-to-dollar — ouro PERDE proteção.
    Retorna Series nomeada 'dxy' com índice UTC.
    """
    cache_file = C.CACHE_DIR / "dxy.csv"
    if use_cache and cache_file.exists():
        try:
            cached = pd.read_csv(cache_file, index_col=0, parse_dates=True)
            cached.index = pd.to_datetime(cached.index, utc=True)
            if len(cached) and (datetime.now(timezone.utc) - cached.index[-1]).days < 1:
                return cached["dxy"]
        except Exception:
            pass

    import yfinance as yf
    # Tentativa com tickers alternativos (Yahoo pode variar)
    for ticker in ("DX-Y.NYB", "=DX"):
        try:
            hist = yf.Ticker(ticker).history(period=period, auto_adjust=False)
            if not hist.empty:
                break
        except Exception:
            continue
    else:
        if cache_file.exists():
            return pd.read_csv(cache_file, index_col=0, parse_dates=True)["dxy"]
        raise RuntimeError("yfinance devolveu vazio para DXY (tentados: DX-Y.NYB, =DX)")

    s = hist["Close"].rename("dxy")
    s.index = s.index.tz_convert("UTC") if s.index.tz else s.index.tz_localize("UTC")
    s = s[~s.index.duplicated(keep="last")]
    if use_cache:
        s.to_frame().to_csv(cache_file)
    return s


def dxy_pct_change_h4(dxy: pd.Series, h4_index: pd.DatetimeIndex,
                       lookback: int = C.DXY_LIQUIDITY_STRESS_LOOKBACK_BARS) -> pd.Series:
    """Calcula % change do DXY alinhado às barras H4.

    Usa forward-fill (último DXY conhecido pra cada barra H4), depois
    calcula % change nos últimos `lookback` períodos H4 (~16h).
    Retorna Series indexada pelo h4_index.
    """
    # Reamostra: pra cada H4 bar, usa o último DXY conhecido (sem lookahead)
    dxy_h4 = dxy.reindex(h4_index, method="ffill")
    # % change no lookback
    pct = dxy_h4.pct_change(lookback) * 100.0
    return pct


# ═════════════════════════════ SPY (S&P500 ETF) ═════════════════════════════
def load_spy(period: str = "max", use_cache: bool = True) -> pd.Series:
    """Série diária do SPY (ETF S&P500) via yfinance, fechamento ajustado.

    Necessário para o detector de risk_on genuíno: correlação ouro vs ações.
    Quando SPY sobe E ouro desce = risk_on verdadeiro (capital saindo de safe haven
    para risco). Quando SPY e ouro sobem JUNTOS = não é risk_on, é outro driver
    (USD fraco, inflação) — o regime deve ser rebaixado.
    Retorna Series nomeada 'spy' com índice UTC.
    """
    cache_file = C.CACHE_DIR / "spy.csv"
    if use_cache and cache_file.exists():
        try:
            cached = pd.read_csv(cache_file, index_col=0, parse_dates=True)
            cached.index = pd.to_datetime(cached.index, utc=True)
            if len(cached) and (datetime.now(timezone.utc) - cached.index[-1]).days < 1:
                return cached["spy"]
        except Exception:
            pass

    import yfinance as yf
    hist = yf.Ticker("SPY").history(period=period, auto_adjust=True)
    if hist.empty:
        if cache_file.exists():
            return pd.read_csv(cache_file, index_col=0, parse_dates=True)["spy"]
        raise RuntimeError("yfinance devolveu vazio para SPY")
    s = hist["Close"].rename("spy")
    s.index = s.index.tz_convert("UTC") if s.index.tz else s.index.tz_localize("UTC")
    s = s[~s.index.duplicated(keep="last")]
    if use_cache:
        s.to_frame().to_csv(cache_file)
    return s


def gold_equity_corr(spy: pd.Series, xau_daily_returns: pd.Series,
                      window: int = 60) -> pd.Series:
    """Correlação rolante entre retornos diários do ouro e do SPY.

    Interpretação:
      - Correlação NEGATIVA (ex: -0.3): ouro cai quando ações sobem → RISK_ON verdadeiro
      - Correlação PRÓXIMA DE ZERO: sem relação clara → regime base (VIX) dita
      - Correlação POSITIVA (ex: +0.5): ouro e ações andam juntos → NÃO é risk_on
        Drivers comuns: USD fraco, inflação, política monetária frouxa
      - Correlação POSITIVA FORTE + ambos caindo → PÂNICO (tudo cai junto)

    Retorna Series com índice diário, valores de correlação rolante.
    """
    merged = pd.concat({"spy": spy, "xau": xau_daily_returns}, axis=1).dropna()
    # Retornos diários
    rets = merged.pct_change().dropna()
    # Correlação rolante
    corr = rets["spy"].rolling(window, min_periods=max(20, window // 2)).corr(rets["xau"])
    return corr


__all__ = [
    "load_prices", "load_all_prices", "load_vix", "vix_resampled_to",
    "load_cot_history", "cot_at_date",
    "load_dxy", "dxy_pct_change_h4",
    "load_spy", "gold_equity_corr",
]
