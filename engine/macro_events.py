"""macro_events.py — Calendário de eventos econômicos de alto impacto.

Gera datas de eventos com base em calendários conhecidos:
  - FOMC: 8 reuniões/ano (Fed segue calendário previsível)
  - NFP (Payroll): Primeira sexta de cada mês
  - CPI: Meados do mês (~10-15)
  - FOMC Minutes: 3 semanas após cada reunião
  - Geopolitical: não previsível, não incluído

Para LIVE, o Finnhub API (já integrado em market_intelligence.py) fornece
o calendário real das próximas 48h. Este módulo serve para BACKTEST,
onde não temos API de calendário histórico.

Uso no backtest:
  events = get_events_for_backtest(start, end)
  near = events_near(events, ts, hours_before=4)
  if near:
      scale *= EVENT_REDUCTION_SCALE  # reduz posição antes de evento

Uso no live:
  O executor.py já usa check_macro_blockers() com dados do Finnhub.
  Este módulo também serve como fallback se o Finnhub falhar.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from . import config as C


# ═════════════════════════════ TIPOS ═════════════════════════════
EVENT_TYPES = {
    "FOMC": "Federal Open Market Committee decision",
    "FOMC_MINUTES": "FOMC Minutes release",
    "NFP": "Non-Farm Payrolls employment report",
    "CPI": "Consumer Price Index inflation report",
    "PPI": "Producer Price Index inflation report",
    "GDP": "Gross Domestic Product advance estimate",
}

EVENT_IMPORTANCE: dict[str, int] = {
    "FOMC": 5,   # Máxima: decisão de juros + guidance + SEP
    "NFP": 4,    # Muito alta: payroll + desemprego + salários
    "CPI": 4,    # Muito alta: inflação ao consumidor
    "FOMC_MINUTES": 3,  # Alta: detalhes da discussão do Fed
    "PPI": 2,    # Média: inflação ao produtor (antecede CPI)
    "GDP": 2,    # Média: PIB trimestral
}


# ═════════════════════════════ GERADOR DE DATAS ═════════════════════════════
def _fomc_dates(year: int) -> list[datetime]:
    """Gera datas aproximadas das 8 reuniões FOMC de um ano.

    Baseado no padrão histórico (sempre terça/quarta, 8x/ano):
      Jan, Mar, May, Jun, Jul, Sep, Nov, Dec
    Terceira semana do mês, tipicamente terça-quarta.

    NOTA: Estas são APROXIMAÇÕES. Para precisão real, use o calendário
    oficial do Fed (federalreserve.gov/monetarypolicy/fomccalendars.htm).
    """
    # Mapeamento aproximado: (mês, semana_do_mês, dia_da_semana)
    # terca=1, quarta=2 (das 8 reuniões, maioria é terça+quarta)
    schedule = [
        (1, 3, 1),   # Jan: 3a terça
        (3, 3, 1),   # Mar: 3a terça
        (5, 3, 1),   # May: 3a terça
        (6, 2, 1),   # Jun: 2a terça (mais cedo, antes do fim do semestre)
        (7, 3, 1),   # Jul: 3a terça
        (9, 3, 1),   # Sep: 3a terça
        (11, 2, 1),  # Nov: 2a terça (antes do Thanksgiving)
        (12, 3, 1),  # Dec: 3a terça
    ]
    dates = []
    for month, week, weekday in schedule:
        d = _nth_weekday(year, month, weekday, week)
        if d is not None:
            # Reunião FOMC começa na terça e termina quarta com decisão às 14h ET
            # A decisão (o evento de mercado) é na quarta às 14h ET = 18h UTC
            decision_day = d + timedelta(days=1)  # quarta
            decision_dt = decision_day.replace(hour=18, minute=0, second=0)
            decision_dt = decision_dt.replace(tzinfo=timezone.utc)
            dates.append(decision_dt)
    return dates


def _fomc_minutes_dates(fomc_dates_list: list[datetime]) -> list[datetime]:
    """FOMC Minutes são publicados 3 semanas após cada reunião, às 14h ET (18h UTC)."""
    return [d + timedelta(days=21) for d in fomc_dates_list]


def _nfp_dates(year: int) -> list[datetime]:
    """NFP: primeira sexta de cada mês, às 8:30 ET (12:30 UTC).

    Se a primeira sexta for feriado (ex: 1 de jan), é no dia seguinte útil.
    Simplificação: primeira sexta do mês.
    """
    dates = []
    for month in range(1, 13):
        d = _first_weekday(year, month, 4)  # 4 = sexta
        if d is not None:
            dt = d.replace(hour=12, minute=30, second=0, tzinfo=timezone.utc)
            dates.append(dt)
    return dates


def _cpi_dates(year: int) -> list[datetime]:
    """CPI: normalmente entre dia 10-15 de cada mês, às 8:30 ET (12:30 UTC).

    Simplificação: dia 13 de cada mês (média do intervalo).
    Para precisão, consultar calendário BLS.
    """
    dates = []
    for month in range(1, 13):
        try:
            d = datetime(year, month, 13, 12, 30, 0, tzinfo=timezone.utc)
            dates.append(d)
        except ValueError:
            # Mês sem dia 13 (improvável)
            d = datetime(year, month, 12, 12, 30, 0, tzinfo=timezone.utc)
            dates.append(d)
    return dates


def _ppidates(year: int) -> list[datetime]:
    """PPI: normalmente 1-2 dias antes do CPI, às 8:30 ET.

    Simplificação: dia 11 de cada mês.
    """
    dates = []
    for month in range(1, 13):
        try:
            d = datetime(year, month, 11, 12, 30, 0, tzinfo=timezone.utc)
            dates.append(d)
        except ValueError:
            d = datetime(year, month, 10, 12, 30, 0, tzinfo=timezone.utc)
            dates.append(d)
    return dates


# ═════════════════════════════ HELPERS ═════════════════════════════
def _nth_weekday(year: int, month: int, weekday: int, n: int) -> Optional[datetime]:
    """Enésima ocorrência de um dia da semana no mês.
    weekday: 0=segunda, 1=terça, 2=quarta, 3=quinta, 4=sexta, 5=sábado, 6=domingo
    """
    first_day = datetime(year, month, 1)
    # Quantos dias até o primeiro weekday desejado?
    days_ahead = weekday - first_day.weekday()
    if days_ahead < 0:
        days_ahead += 7
    first_occurrence = first_day + timedelta(days=days_ahead)
    result = first_occurrence + timedelta(weeks=n - 1)
    if result.month != month:
        return None
    return result


def _first_weekday(year: int, month: int, weekday: int) -> Optional[datetime]:
    """Primeira ocorrência de um dia da semana no mês."""
    return _nth_weekday(year, month, weekday, 1)


# ═════════════════════════════ API PÚBLICA ═════════════════════════════
def get_events_for_backtest(
    start: str | pd.Timestamp | datetime,
    end: str | pd.Timestamp | datetime,
) -> list[dict]:
    """Gera lista de eventos econômicos para o período do backtest.

    Retorna lista de dicts:
      {
        "time": datetime (UTC),
        "event": str (ex: "FOMC", "NFP", "CPI"),
        "country": str (ex: "US"),
        "importance": int (1-5),
        "description": str
      }

    Estes são APROXIMADOS — para precisão real, usar API de calendário
    econômico (Finnhub, Bloomberg, etc).
    """
    if isinstance(start, str):
        start = pd.Timestamp(start, tz="UTC")
    if isinstance(end, str):
        end = pd.Timestamp(end, tz="UTC")
    if isinstance(start, pd.Timestamp):
        start = start.to_pydatetime()
    if isinstance(end, pd.Timestamp):
        end = end.to_pydatetime()
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    events: list[dict] = []
    years = range(start.year, end.year + 1)

    for year in years:
        # FOMC
        for dt in _fomc_dates(year):
            if start <= dt <= end:
                events.append({
                    "time": dt,
                    "event": "FOMC",
                    "country": "US",
                    "importance": EVENT_IMPORTANCE["FOMC"],
                    "description": "FOMC interest rate decision + SEP + press conference",
                })
        # FOMC Minutes
        fomc_dts = _fomc_dates(year)
        for dt in _fomc_minutes_dates(fomc_dts):
            if start <= dt <= end:
                events.append({
                    "time": dt,
                    "event": "FOMC_MINUTES",
                    "country": "US",
                    "importance": EVENT_IMPORTANCE["FOMC_MINUTES"],
                    "description": "FOMC Minutes release (3 weeks after meeting)",
                })
        # NFP
        for dt in _nfp_dates(year):
            if start <= dt <= end:
                events.append({
                    "time": dt,
                    "event": "NFP",
                    "country": "US",
                    "importance": EVENT_IMPORTANCE["NFP"],
                    "description": "Non-Farm Payrolls employment report",
                })
        # CPI
        for dt in _cpi_dates(year):
            if start <= dt <= end:
                events.append({
                    "time": dt,
                    "event": "CPI",
                    "country": "US",
                    "importance": EVENT_IMPORTANCE["CPI"],
                    "description": "Consumer Price Index inflation report",
                })
        # PPI
        for dt in _ppidates(year):
            if start <= dt <= end:
                events.append({
                    "time": dt,
                    "event": "PPI",
                    "country": "US",
                    "importance": EVENT_IMPORTANCE["PPI"],
                    "description": "Producer Price Index inflation report",
                })

    events.sort(key=lambda e: e["time"])
    return events


def events_near(
    events: list[dict],
    ts: pd.Timestamp | datetime,
    hours_before: int = 4,
    hours_after: int = 4,
    min_importance: int = 3,
) -> list[dict]:
    """Retorna eventos próximos de um timestamp.

    Args:
        events: lista de eventos (get_events_for_backtest)
        ts: timestamp de referência
        hours_before: quantas horas ANTES do evento considerar
        hours_after: quantas horas DEPOIS do evento considerar
        min_importance: importância mínima (1-5)

    Returns:
        Lista de eventos dentro da janela [ts - hours_before, ts + hours_after]
    """
    if isinstance(ts, pd.Timestamp):
        ts = ts.to_pydatetime()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    window_start = ts - timedelta(hours=hours_after)
    window_end = ts + timedelta(hours=hours_before)

    near = []
    for ev in events:
        if ev["importance"] < min_importance:
            continue
        ev_time = ev["time"]
        if ev_time.tzinfo is None:
            ev_time = ev_time.replace(tzinfo=timezone.utc)
        if window_start <= ev_time <= window_end:
            near.append(ev)
    return near


# ═════════════════════════════ TESTE RÁPIDO ═════════════════════════════
if __name__ == "__main__":
    events = get_events_for_backtest("2024-01-01", "2024-12-31")
    print(f"Total events in 2024: {len(events)}")
    for ev in events[:10]:
        print(f"  {ev['time'].strftime('%Y-%m-%d %H:%M UTC')} | {ev['event']:12s} | "
              f"imp={ev['importance']} | {ev['description'][:50]}")

    # Teste: events near a specific timestamp
    test_ts = pd.Timestamp("2024-03-20 16:00", tz="UTC")  # 4h antes do FOMC Mar 2024
    near = events_near(events, test_ts, hours_before=4, hours_after=0)
    print(f"\nEvents near {test_ts}:")
    for ev in near:
        print(f"  {ev['time'].strftime('%Y-%m-%d %H:%M UTC')} | {ev['event']:12s}")


__all__ = [
    "get_events_for_backtest", "events_near",
    "EVENT_TYPES", "EVENT_IMPORTANCE",
]
