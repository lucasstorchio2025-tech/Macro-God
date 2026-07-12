"""Investiga a janela 8 do WFO (2025-11-14 a 2026-04-30) onde ATR=51.6, VolAnual=13.2%.

Possiveis causas:
1. Dado corrompido (spike/gap no MT5)
2. Mudanca real de volatilidade do ouro
3. Erro de calculo do ATR
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from engine import config as C
from engine.data import load_all_prices, load_vix
from engine.indicators import atr as atr_fn

print("=" * 70)
print("  ANALISE JANELA 8 WFO: 2025-11-14 a 2026-04-30")
print("=" * 70)

# Carregar dados
prices = load_all_prices(timeframe=C.TIMEFRAME, bars=C.BARS_LOOKBACK, align=True)
xau = prices.get("XAUUSDm")
if xau is None:
    print("ERRO: XAUUSDm nao encontrado")
    sys.exit(1)

print(f"\nXAUUSD: {len(xau)} barras H4 de {xau.index[0].date()} a {xau.index[-1].date()}")

# Periodos
w8_start = pd.Timestamp("2025-11-14", tz="UTC")
w8_end = pd.Timestamp("2026-04-30", tz="UTC")

# Periodo anterior (comparacao)
prev_start = pd.Timestamp("2025-08-01", tz="UTC")

w8 = xau.loc[w8_start:w8_end]
prev = xau.loc[prev_start:w8_start - pd.Timedelta(hours=4)]  # ate antes da w8

print(f"\nJanela 8:   {w8_start.date()} a {w8_end.date()}  -> {len(w8)} barras")
print(f"Anterior:   {prev_start.date()} a {(w8_start - pd.Timedelta(hours=4)).date()}  -> {len(prev)} barras")

# 1. ATR janela 8
atr_w8 = atr_fn(w8)
print(f"\n--- ATR na Janela 8 ---")
print(f"  ATR medio: {atr_w8.mean():.1f}")
print(f"  ATR max:   {atr_w8.max():.1f}")
print(f"  ATR min:   {atr_w8.min():.1f}")
print(f"  ATR std:   {atr_w8.std():.1f}")
print(f"  ATR ultimo: {atr_w8.iloc[-1]:.1f}")

# 2. ATR periodo anterior
atr_prev = atr_fn(prev)
print(f"\n--- ATR no Periodo Anterior ---")
print(f"  ATR medio: {atr_prev.mean():.1f}")
print(f"  ATR max:   {atr_prev.max():.1f}")
print(f"  ATR min:   {atr_prev.min():.1f}")

# 3. ATR global (todo o dataset)
atr_all = atr_fn(xau)
print(f"\n--- ATR Global ({len(xau)} barras) ---")
print(f"  ATR medio: {atr_all.mean():.1f}")
print(f"  ATR max:   {atr_all.max():.1f}")
print(f"  ATR min:   {atr_all.min():.1f}")
print(f"  ATR 95th pct: {atr_all.quantile(0.95):.1f}")
print(f"  ATR 99th pct: {atr_all.quantile(0.99):.1f}")

# 4. Precos: checar gaps, spikes, NaN
print(f"\n--- Qualidade dos dados na Janela 8 ---")
print(f"  NaN em close: {w8['close'].isna().sum()}")
print(f"  NaN em high:  {w8['high'].isna().sum()}")
print(f"  NaN em low:   {w8['low'].isna().sum()}")

# Retornos
ret_w8 = w8["close"].pct_change().dropna()
print(f"\n  Retorno medio: {ret_w8.mean()*100:.3f}%")
print(f"  Retorno std:   {ret_w8.std()*100:.3f}%")
print(f"  Retorno max:   {ret_w8.max()*100:.2f}%")
print(f"  Retorno min:   {ret_w8.min()*100:.2f}%")

# Spikes (retornos > 3%)
spikes = ret_w8[abs(ret_w8) > 0.03]
print(f"  Spikes (>3%):  {len(spikes)} ocorrencias")
for idx in spikes.index:
    print(f"    {idx}: {spikes.loc[idx]*100:.2f}%")

# 5. Volatilidade anualizada
vol_w8 = ret_w8.std() * np.sqrt(6*252)  # H4 bars
vol_prev = prev["close"].pct_change().dropna().std() * np.sqrt(6*252)
vol_all = xau["close"].pct_change().dropna().std() * np.sqrt(6*252)
print(f"\n--- Volatilidade Anualizada ---")
print(f"  Janela 8:   {vol_w8*100:.1f}%")
print(f"  Anterior:   {vol_prev*100:.1f}%")
print(f"  Global:     {vol_all*100:.1f}%")

# 6. Verificacao: preco max/min na janela
print(f"\n--- Precos ---")
print(f"  Preco inicio: ${w8['close'].iloc[0]:.2f}")
print(f"  Preco fim:    ${w8['close'].iloc[-1]:.2f}")
print(f"  Preco max:    ${w8['close'].max():.2f} em {w8['close'].idxmax()}")
print(f"  Preco min:    ${w8['close'].min():.2f} em {w8['close'].idxmin()}")

# 7. VIX na janela
vix = load_vix(period="max")
print(f"\n--- VIX na Janela 8 ---")
vix_w8 = vix.loc[w8_start:w8_end] if vix is not None else None
if vix_w8 is not None and not vix_w8.empty:
    print(f"  VIX medio: {vix_w8.mean():.1f}")
    print(f"  VIX max:   {vix_w8.max():.1f}")
    print(f"  VIX min:   {vix_w8.min():.1f}")

# 8. Conclusao
print(f"\n{'='*70}")
print("  CONCLUSAO:")
print(f"{'='*70}")
if atr_w8.mean() > atr_all.quantile(0.95):
    print("  🔴 ATR medio da janela 8 esta no 95th percentil global — ANOMALIA real.")
elif atr_w8.mean() > atr_all.quantile(0.80):
    print("  🟡 ATR medio da janela 8 esta acima do 80th percentil — elevado mas plausivel.")
else:
    print("  🟢 ATR medio da janela 8 esta dentro do normal.")

if len(spikes) > 10:
    print(f"  🔴 {len(spikes)} spikes de >3% — dado possivelmente corrompido ou periodo extremo.")
else:
    print(f"  🟢 {len(spikes)} spikes — dentro do esperado para XAUUSD H4.")

# Ver se ATR alto e explicado por tendencia de alta forte
trend = (w8["close"].iloc[-1] / w8["close"].iloc[0] - 1) * 100
print(f"  Tendencia na janela: {trend:+.1f}%")
if abs(trend) > 20:
    print(f"  🔴 Tendencia forte de {abs(trend):.0f}% — trending market explica ATR alto.")
else:
    print(f"  🟢 Tendencia moderada — ATR alto nao e explicado por trend direcional.")
