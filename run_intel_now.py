"""Smoke run do market_intelligence.py com credenciais do .env.
Le credenciais, conecta MT5, monta o hub, e imprime o JSON completo."""
import os, sys, json
from pathlib import Path

# Carrega .env sem dependencia
env_path = str(Path.home() / ".hermes" / ".env")
with open(env_path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k,_,v = line.partition("="); v=v.strip().strip('"').strip("'")
        if k.startswith("EXNESS_"): os.environ[k]=v

_PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "files"))
import market_intelligence as mi

# Sobrescreve config do modulo com credenciais reais do .env
mi.FRED_API_KEY = os.environ.get("FRED_API_KEY", mi.FRED_API_KEY) if "FRED_API_KEY" in os.environ else mi.FRED_API_KEY
mi.OUTPUT_PATH = str(_PROJECT_ROOT / "market_intelligence.json")

# Garante login automatico dentro do hub
real_init = mi.get_mt5_prices

def patched_get_mt5_prices():
    import MetaTrader5 as mt5
    from datetime import datetime, timezone
    try:
        if not mt5.initialize(login=int(os.environ["EXNESS_LOGIN"]),
                              password=os.environ["EXNESS_PASSWORD"],
                              server=os.environ["EXNESS_SERVER"],
                              timeout=15000):
            return {"error": f"mt5.initialize falhou: {mt5.last_error()}"}
    except Exception as e:
        return {"error": str(e)}
    out = real_init()
    mt5.shutdown()
    return out

mi.get_mt5_prices = patched_get_mt5_prices

# Mesma patch pro swing plan (tb chama initialize)
real_swing = mi.get_swing_trade_plan
def patched_swing(symbol, **kw):
    import MetaTrader5 as mt5
    if not mt5.initialize(login=int(os.environ["EXNESS_LOGIN"]),
                          password=os.environ["EXNESS_PASSWORD"],
                          server=os.environ["EXNESS_SERVER"],
                          timeout=15000):
        return {"error": "MT5 nao conectou"}
    r = real_swing(symbol, **kw)
    mt5.shutdown()
    return r
mi.get_swing_trade_plan = patched_swing

data = mi.build_intelligence_hub()
print("\n--- JSON COMPLETO ---")
print(json.dumps(data, indent=2, ensure_ascii=False)[:3000])
