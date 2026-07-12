"""
market_intelligence.py
-----------------------
Substitui o "Intelligence Hub" vazio por dados REAIS, vindos de APIs oficiais.
Nenhum dado aqui é gerado por LLM -- tudo vem de fonte verificável.

Roda 1x e grava um JSON limpo. Agende no Windows Task Scheduler (taskschd.msc)
a cada 15-30 min -- NÃO dependa do cron/gateway do Hermes pra essa parte,
ele é instável e não é necessário pra buscar dado.

Requisitos:
    pip install requests
    pip install MetaTrader5      (opcional, mas recomendado -- preço real)
    pip install yfinance         (opcional -- VIX/DXY como proxy de risco)

Chaves grátis (2 min cada):
    FRED:    https://fredaccount.stlouisfed.org/apikey
    Finnhub: https://finnhub.io/register
"""

import json
import os
from datetime import datetime, timedelta, timezone
import requests

# Carrega variaveis do .env (sem precisar editar o script toda vez que voce colocar uma chave)
try:
    from dotenv import load_dotenv
    for env_path in [r"C:\Users\lucas\.hermes\.env"]:
        if os.path.exists(env_path):
            load_dotenv(env_path, override=False)
except ImportError:
    pass  # python-dotenv e opcional; sem ele, FRED/Finnhub vao retornar {"error": "..."}

# ============== CONFIG -- AJUSTE AQUI ==============
# Estas chaves podem estar no seu .env (recomendado) OU hardcoded aqui.
FRED_API_KEY = os.environ.get("FRED_API_KEY", "COLOQUE_SUA_CHAVE_FRED")
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "COLOQUE_SUA_CHAVE_FINNHUB")
OUTPUT_PATH = os.environ.get("WEALTH_OUTPUT_PATH", r"C:\Users\lucas\Wealth_Engine\market_intelligence.json")
SYMBOLS_MT5 = ["EURUSDm", "XAUUSDm", "GBPUSDm", "USDJPYm"]  # Exness Trial11 padrao com sufixo "m" (micro)

# Alertas (opcional) -- crie um bot em 2 min falando com @BotFather no Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "COLOQUE_SEU_TOKEN_TELEGRAM")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "COLOQUE_SEU_CHAT_ID")
VIX_ALERT_THRESHOLD_PCT = 5.0
CALENDAR_ALERT_MINUTES_AHEAD = 60
# =====================================================


def get_mt5_prices():
    """Preço real, direto do terminal MT5 já logado na sua conta Exness."""
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return {"error": "Pacote MetaTrader5 não instalado. Rode: pip install MetaTrader5"}

    if not mt5.initialize():
        return {"error": f"Não consegui conectar ao terminal MT5: {mt5.last_error()}. "
                          f"O MetaTrader 5 precisa estar ABERTO e logado."}

    prices = {}
    for symbol in SYMBOLS_MT5:
        if not mt5.symbol_select(symbol, True):
            continue
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            prices[symbol] = {
                "bid": tick.bid,
                "ask": tick.ask,
                "spread": round(tick.ask - tick.bid, 5),
                "time_utc": datetime.fromtimestamp(tick.time, tz=timezone.utc).isoformat(),
            }

    acc = mt5.account_info()
    account_info = (
        {"balance": acc.balance, "equity": acc.equity, "currency": acc.currency}
        if acc else {"error": "account_info() retornou nada"}
    )
    mt5.shutdown()
    return {"prices": prices, "account": account_info}


def get_fed_data():
    """Taxa de juros real do Fed, direto da fonte oficial (FRED)."""
    if FRED_API_KEY == "COLOQUE_SUA_CHAVE_FRED":
        return {"error": "Configure FRED_API_KEY"}

    series = {"FEDFUNDS": "fed_funds_rate_mensal", "DFF": "fed_funds_rate_diario", "DGS10": "treasury_10y",
               "ECBDFR": "ecb_deposit_rate"}
    out = {}
    for sid, label in series.items():
        try:
            r = requests.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={"series_id": sid, "api_key": FRED_API_KEY, "file_type": "json",
                        "sort_order": "desc", "limit": 1},
                timeout=10,
            )
            obs = r.json().get("observations", [])
            if obs:
                out[label] = {"valor": obs[0]["value"], "data": obs[0]["date"]}
        except Exception as e:
            out[label] = {"error": str(e)}
    return out


def get_economic_calendar():
    """Próximos eventos econômicos de alto impacto (NFP, CPI, decisões de juros, etc.)."""
    if FINNHUB_API_KEY == "COLOQUE_SUA_CHAVE_FINNHUB":
        return {"error": "Configure FINNHUB_API_KEY"}
    try:
        today = datetime.utcnow().date()
        r = requests.get(
            "https://finnhub.io/api/v1/calendar/economic",
            params={"from": today.isoformat(), "to": (today + timedelta(days=2)).isoformat(),
                    "token": FINNHUB_API_KEY},
            timeout=10,
        )
        events = r.json().get("economicCalendar", [])
        high_impact = [e for e in events if e.get("impact") == "high"]
        return high_impact[:10]
    except Exception as e:
        return {"error": str(e)}


def get_macro_news():
    """Manchetes macro recentes (Fed, geopolítica, etc.) -- só headline+fonte, sem inventar nada."""
    if FINNHUB_API_KEY == "COLOQUE_SUA_CHAVE_FINNHUB":
        return {"error": "Configure FINNHUB_API_KEY"}
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/news",
            params={"category": "general", "token": FINNHUB_API_KEY},
            timeout=10,
        )
        news = r.json()[:8]
        return [{"headline": n["headline"], "fonte": n["source"], "timestamp": n["datetime"]} for n in news]
    except Exception as e:
        return {"error": str(e)}


def get_risk_sentiment():
    """Proxy de risk-on/risk-off via VIX e DXY (sem chave, via Yahoo Finance)."""
    try:
        import yfinance as yf
    except ImportError:
        return {"error": "Pacote yfinance não instalado (opcional). Rode: pip install yfinance"}
    try:
        out = {}
        for ticker, label in [("^VIX", "vix"), ("DX-Y.NYB", "dollar_index")]:
            hist = yf.Ticker(ticker).history(period="2d")
            if len(hist) >= 2:
                prev_close = float(hist["Close"].iloc[-2])
                last_close = float(hist["Close"].iloc[-1])
                pct_change = round((last_close - prev_close) / prev_close * 100, 2)
                out[label] = last_close
                out[f"{label}_pct_change"] = pct_change
            elif not hist.empty:
                out[label] = round(float(hist["Close"].iloc[-1]), 2)
        return out
    except Exception as e:
        return {"error": str(e)}


def get_cot_positioning():
    """Posicionamento dos GRANDES especuladores (CFTC, dado oficial, grátis, sem chave).
    Atualiza 1x por semana (sexta) -- é normal o valor não mudar entre execuções no meio da semana.
    Serve como viés direcional institucional: quando especulador está muito líquido comprado
    ou vendido numa moeda, isso é informação de peso pra confirmar (ou desconfiar) de uma direção."""
    base_url = "https://publicreporting.cftc.gov/resource/jun7-fc8e.json"
    # SoQL: $q faz full-text search; $where like '%25X%25' falha em algumas bases (retornava 0 linhas
    # mesmo com o texto presente). $where com ILIKE funciona pra nomes hifenizados tipo "EURO FX".
    currencies = {
        "EUR": "EURO FX", "GBP": "BRITISH POUND", "JPY": "JAPANESE YEN",
        "AUD": "AUSTRALIAN DOLLAR", "CAD": "CANADIAN DOLLAR", "CHF": "SWISS FRANC",
        # GOLD tem "MICRO GOLD" tambem; filtramos pra pegar o GOLD puro (mercado principal)
        "XAU": "GOLD - COMMODITY EXCHANGE",
        # USD via DX (ICE U.S. Dollar Index futures). CFTC nao publica "USD" isolado,
        # mas publica o contrato de indice do dolar na ICE Futures U.S.
        # Isso da o sinal de USD pros pares EURUSDm/GBPUSDm/USDJPYm que antes ficavam com USD missing.
        "USD": "USD INDEX - ICE FUTURES",
    }
    out = {}
    for code, name_fragment in currencies.items():
        try:
            # Tenta full-text search primeiro (rapido, robusto)
            r = requests.get(base_url, params={
                "$q": name_fragment,
                "$order": "report_date_as_yyyy_mm_dd DESC",
                "$limit": 5,
            }, timeout=15)
            rows = r.json()
            # Pega a linha mais recente cujo nome BATE EXATO com o pedido (sem ser "MICRO X")
            row = None
            for cand in rows:
                name = (cand.get("market_and_exchange_names") or "").upper()
                if code == "XAU" and name.startswith("MICRO "): continue
                # aceita "EURO FX - ..." mas recusa "MICRO EURO FX - ..."
                if name.startswith("MICRO "): continue
                row = cand
                break
            if row:
                long = int(row.get("noncomm_positions_long_all", 0) or 0)
                short = int(row.get("noncomm_positions_short_all", 0) or 0)
                out[code] = {
                    "data_relatorio": (row.get("report_date_as_yyyy_mm_dd") or "")[:10],
                    "especuladores_long": long,
                    "especuladores_short": short,
                    "net": long - short,
                    "vies": "comprado" if long > short else "vendido",
                    "mercado": row.get("market_and_exchange_names"),
                }
        except Exception as e:
            out[code] = {"error": str(e)}
    return out


def _calc_atr(rates, period=14):
    """ATR (volatilidade média real) sem depender de pandas -- só os bars que o MT5 já devolveu."""
    trs = []
    for i in range(1, len(rates)):
        high, low = rates[i]["high"], rates[i]["low"]
        prev_close = rates[i - 1]["close"]
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def get_swing_trade_plan(symbol, timeframe="H4", account_risk_pct=5.0, atr_multiplier=1.5, min_reward_risk=2.0):
    """
    Plano pra trade DIRECIONAL (entra e segura, não scalping):
    - Stop = ATR x multiplicador -> aguenta o ruído normal do ativo, não é número arbitrário.
    - Alvo = stop x min_reward_risk (padrão 2:1).
    - Lote = calibrado contra mt5.order_calc_profit (verdade do servidor, não fórmula).

    ATENÇÃO: a fórmula de valor-por-ponto varia por tipo de instrumento (forex major vs
    XAUUSD vs índice). Em micro conta, valores-por-ponto nao batem com formulas genericas.
    Aqui usamos order_calc_profit como verdade: calculamos o lote que arrisca exatamente
    account_risk_pct% do saldo. Se o lote minimo do broker for maior que isso, devolvemos
    um aviso 'risco_minimo_excede_teto' pra voce decidir manualmente.
    """
    try:
        import MetaTrader5 as mt5
    except ImportError:
        return {"error": "MetaTrader5 não instalado"}

    if not mt5.initialize():
        return {"error": "MT5 não conectado"}

    tf_map = {"M15": mt5.TIMEFRAME_M15, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4, "D1": mt5.TIMEFRAME_D1}
    rates = mt5.copy_rates_from_pos(symbol, tf_map.get(timeframe, mt5.TIMEFRAME_H4), 0, 30)
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    acc = mt5.account_info()

    if rates is None or len(rates) < 15 or not info or not tick or not acc:
        mt5.shutdown()
        return {"error": "Dados insuficientes (MT5 fechado, símbolo errado ou histórico curto)"}

    atr = _calc_atr(rates, 14)
    if atr is None:
        mt5.shutdown()
        return {"error": "ATR não calculado (poucos candles)"}

    stop_distance = round(atr * atr_multiplier, info.digits)
    target_distance = round(stop_distance * min_reward_risk, info.digits)
    risk_money = round(acc.balance * (account_risk_pct / 100), 2)

    ask = tick.ask
    sl_price = round(ask - stop_distance, info.digits)
    tp_price = round(ask + target_distance, info.digits)

    # Verdade do servidor (BUY; pra SELL inverte sinais)
    base_loss = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, symbol, info.volume_min, ask, sl_price)
    base_gain = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, symbol, info.volume_min, ask, tp_price)
    mt5.shutdown()

    if base_loss is None or base_gain is None:
        return {"error": f"order_calc_profit falhou (mercado fechado?): {mt5.last_error()}"}

    # unit_loss: quanto custa 1 unidade de volume_step
    unit_loss = base_loss / info.volume_min
    unit_gain = base_gain / info.volume_min

    # lote_raw: quanto volume preciso pro risco desejado
    raw_lot = risk_money / abs(unit_loss) if unit_loss != 0 else None
    chosen_lot = None
    aviso_teto = None
    if raw_lot is not None and raw_lot > 0:
        n_steps = max(1, int(raw_lot / info.volume_step))
        chosen_lot = round(n_steps * info.volume_step, 2)
        if chosen_lot > info.volume_max:
            chosen_lot = info.volume_max
            aviso_teto = f"Lote necessario ({raw_lot:.4f}) excede volume_max ({info.volume_max})."
        if chosen_lot < info.volume_min:
            chosen_lot = info.volume_min
            aviso_teto = (f"Risco minimo do broker ({info.volume_min} lote em SL de {stop_distance}) "
                          f"excede account_risk_pct={account_risk_pct}%. Levante account_risk_pct ou "
                          f"diminua stop_distance. Risco real atual seria ~{abs(unit_loss)*info.volume_min:.2f} USD = "
                          f"{abs(unit_loss)*info.volume_min/acc.balance*100:.1f}% da conta.")
    else:
        chosen_lot = info.volume_min
        aviso_teto = "Nao foi possivel calcular lote (unit_loss==0)."

    # Recalcula risco REAL com o lote final
    real_loss = round(base_loss * (chosen_lot / info.volume_min), 2) if info.volume_min else None
    real_gain = round(base_gain * (chosen_lot / info.volume_min), 2) if info.volume_min else None
    real_risk_pct = round(abs(real_loss) / acc.balance * 100, 2) if real_loss else None
    rr_ratio = round(abs(real_gain / real_loss), 3) if real_loss and real_loss != 0 else None

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "atr_14": round(atr, info.digits),
        "stop_distance": stop_distance,
        "target_distance": target_distance,
        "preco_entrada_recomendado": ask,
        "stop_price": sl_price,
        "take_price": tp_price,
        "reward_risk_alvo": min_reward_risk,
        "reward_risk_real": rr_ratio,
        "risk_pct_alvo": account_risk_pct,
        "risk_money_alvo": risk_money,
        "risco_real_usd": real_loss,
        "ganho_real_usd": real_gain,
        "risco_real_pct_da_conta": real_risk_pct,
        "lote_recomendado": chosen_lot,
        "vol_min": info.volume_min,
        "vol_step": info.volume_step,
        "aviso_teto": aviso_teto,
    }

def send_telegram_alert(message):
    """Manda um aviso pro seu Telegram. Se não configurado, só ignora silenciosamente."""
    if TELEGRAM_BOT_TOKEN.startswith("COLOQUE") or TELEGRAM_CHAT_ID.startswith("COLOQUE"):
        return
    try:
        requests.get(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            params={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=10,
        )
    except Exception:
        pass


def check_alerts(data):
    """Olha o dado JÁ coletado e decide se algo merece avisar você agora."""
    alerts = []

    # Evento de alto impacto chegando
    cal = data.get("economic_calendar_next_48h", [])
    if isinstance(cal, list):
        now = datetime.now(timezone.utc)
        for ev in cal:
            try:
                ev_time = datetime.fromisoformat(ev.get("time", "").replace("Z", "+00:00"))
                minutes_to_event = (ev_time - now).total_seconds() / 60
                if 0 <= minutes_to_event <= CALENDAR_ALERT_MINUTES_AHEAD:
                    alerts.append(f"[AVISO] Evento de alto impacto em {int(minutes_to_event)} min: "
                                  f"{ev.get('event')} ({ev.get('country')})")
            except Exception:
                continue

    # Movimento brusco de VIX (risco mudando de regime)
    risk = data.get("risk_sentiment", {})
    vix_change = risk.get("vix_pct_change")
    if isinstance(vix_change, (int, float)) and abs(vix_change) >= VIX_ALERT_THRESHOLD_PCT:
        direction = "subindo" if vix_change > 0 else "caindo"
        alerts.append(f"[VIX] VIX {direction} {abs(vix_change)}% hoje -- regime de risco pode estar mudando.")

    for msg in alerts:
        print(f"[ALERTA] {msg}")
        send_telegram_alert(msg)

    return alerts


def build_intelligence_hub():
    data = {
        "last_update_utc": datetime.now(timezone.utc).isoformat(),
        "mt5": get_mt5_prices(),
        "fed_rates": get_fed_data(),
        "economic_calendar_next_48h": get_economic_calendar(),
        "macro_headlines": get_macro_news(),
        "risk_sentiment": get_risk_sentiment(),
        "cot_positioning": get_cot_positioning(),
        "swing_trade_plans": {s: get_swing_trade_plan(s) for s in SYMBOLS_MT5},
    }
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    alerts = check_alerts(data)
    data["active_alerts"] = alerts

    print(f"[OK] Intelligence Hub atualizado com dados REAIS em: {OUTPUT_PATH}")
    if alerts:
        print(f"[OK] {len(alerts)} alerta(s) disparado(s).")
    return data


if __name__ == "__main__":
    build_intelligence_hub()
