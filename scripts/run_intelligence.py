"""run_intelligence.py — orquestra: atualiza dados + roda análise + salva snapshot.

Uso:
  python scripts/run_intelligence.py          # atualiza tudo + análise
  python scripts/run_intelligence.py --skip   # pula coleta, só re-analisa

Fluxo:
  1. Roda market_intelligence.py (FRED, CFTC, MT5, VIX, DXY → market_intelligence.json)
  2. Tenta rodar news_aggregator.py (Ollama) → filtered_news.json (opcional)
  3. Roda analyze_market() cruzando tudo
  4. Salva market_snapshot.json (pro dashboard ler)
  5. Envia conclusão no Telegram (se configurado)
"""
import sys
import json
import os
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# carrega .env
from dotenv import load_dotenv
load_dotenv(str(PROJECT_ROOT / ".env"), override=False)
load_dotenv(str(Path.home() / ".hermes" / ".env"), override=False)

from engine.data import load_all_prices, load_vix, load_spy, gold_equity_corr
from engine.regime import RuleBasedRegime
from engine.macro_analysis import analyze_market

INTEL_PATH = PROJECT_ROOT / "market_intelligence.json"
NEWS_PATH = PROJECT_ROOT / "filtered_news.json"
SNAPSHOT_PATH = PROJECT_ROOT / "market_snapshot.json"
MI_SCRIPT = PROJECT_ROOT / "scripts" / "files" / "market_intelligence.py"
NEWS_SCRIPT = PROJECT_ROOT / "scripts" / "files" / "news_aggregator.py"


def collect_intel():
    """Roda market_intelligence.py pra atualizar DXY, VIX, Fed, COT, MT5."""
    print("[1/3] Coletando dados de mercado...")
    if not MI_SCRIPT.exists():
        print("  [FALHA] market_intelligence.py nao encontrado")
        return False
    import importlib.util
    spec = importlib.util.spec_from_file_location("mi", MI_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        if hasattr(mod, "build_intelligence_hub"):
            data = mod.build_intelligence_hub()
            out_path = os.environ.get("WEALTH_OUTPUT_PATH",
                                     str(PROJECT_ROOT / "market_intelligence.json"))
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                                     encoding="utf-8")
            print(f"  [OK] Intel atualizada ({len(data)} secoes)")
            return True
        else:
            print("  [FALHA] build_intelligence_hub nao encontrada")
            return False
    except Exception as e:
        print(f"  [FALHA] Coleta: {e}")
        return False


def collect_news():
    """Tenta rodar news_aggregator.py (precisa de Ollama rodando)."""
    print("[2/3] Coletando notícias (Ollama)...")
    if not NEWS_SCRIPT.exists():
        print("  [FALHA] news_aggregator.py nao encontrado")
        return
    import importlib.util
    spec = importlib.util.spec_from_file_location("na", NEWS_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        if hasattr(mod, "build_filtered_news"):
            data = mod.build_filtered_news()
            NEWS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                                 encoding="utf-8")
            n = data.get("total_relevante", 0)
            print(f"  [OK] {n} noticias relevantes")
        else:
            print("  [FALHA] build_filtered_news nao encontrada")
    except Exception as e:
        print(f"  [AVISO] Ollama indisponivel: {e}")
        print("    (noticias nao sao essenciais -- painel funciona sem)")


def run_analysis() -> dict:
    """Roda analyze_market() com dados disponíveis."""
    print("[3/3] Analisando mercado...")
    intel = {}
    if INTEL_PATH.exists():
        intel = json.loads(INTEL_PATH.read_text(encoding="utf-8"))
    prices = load_all_prices(align=True)
    vix = load_vix(period="max")
    # Carrega SPY e calcula correlação ouro×ações para regime genuíno
    ge_corr = None
    try:
        spy = load_spy(period="5y")
        xau = prices.get("XAUUSDm")
        if xau is not None and spy is not None:
            xau_daily = xau["close"].resample("D").last().dropna()
            ge_corr = gold_equity_corr(spy, xau_daily, window=60)
            print(f"  [OK] Correlação ouro×ações carregada ({len(ge_corr.dropna())} dias)")
    except Exception as e:
        print(f"  [AVISO] SPY indisponível ({e}) — correlação gold×ações desativada")
    regime = RuleBasedRegime(vix=vix, prices_for_corr=prices, gold_equity_corr=ge_corr)
    regime_str = regime.at(__import__("pandas").Timestamp.utcnow(), {})

    snap = analyze_market(intel, prices, vix, regime_str, news_path=NEWS_PATH)

    # salva snapshot
    SNAPSHOT_PATH.write_text(
        json.dumps(snap.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n{'=' * 60}")
    print(f"  CONCLUSÃO: {snap.conclusion}")
    print(f"  Confiança: {snap.confidence}/100 | Risk Score: {snap.risk_score}")
    print(f"  Regime: {snap.regime}")
    if snap.alerts:
        for a in snap.alerts:
            print(f"  {a}")
    print(f"{'=' * 60}")
    print(f"  Snapshot salvo: {SNAPSHOT_PATH}")

    # telegram
    _send_telegram(snap)

    return snap.to_dict()


def _send_telegram(snap):
    """Envia conclusão no Telegram (se configurado)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat or token.startswith("COLOQUE"):
        return
    try:
        import requests
        arrow = "🟢" if snap.risk_score >= 60 else ("🟡" if snap.risk_score >= 40 else "🔴")
        regime_icon = {"risk_on": "✅", "normal": "⚖️", "risk_off": "⚠️", "crisis": "🚨"}.get(snap.regime, "❓")
        lines = [
            f"📊 *Wealth_Engine Intel*",
            f"",
            f"{regime_icon} Regime: {snap.regime.upper()}",
            f"{arrow} Risk: {snap.risk_score}/100",
            f"",
            f"*{snap.conclusion}*",
            f"",
            f"Confiança: {snap.confidence}/100",
        ]
        for a in snap.assets:
            sym = a.symbol if hasattr(a, 'symbol') else a.get('symbol', '?')
            direction = a.direction if hasattr(a, 'direction') else a.get('direction', '?')
            thesis = a.thesis if hasattr(a, 'thesis') else a.get('thesis', '')
            icon = "🟢" if direction == "bullish" else ("🔴" if direction == "bearish" else "⚪")
            lines.append(f"{icon} {sym} — {direction} ({thesis})")
        if snap.alerts:
            lines.append("")
            for al in snap.alerts:
                lines.append(f"⚠ {al}")
        text = "\n".join(lines)
        requests.get(
            f"https://api.telegram.org/bot{token}/sendMessage",
            params={"chat_id": chat, "text": text[:4000], "parse_mode": "Markdown"},
            timeout=10,
        )
        print("  [OK] Enviado no Telegram")
    except Exception as e:
        print(f"  [AVISO] Telegram falhou: {e}")


def main():
    print("=" * 60)
    print("  WEALTH_ENGINE — Intelligence Pipeline")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")
    print("=" * 60)

    skip_collect = "--skip" in sys.argv

    if not skip_collect:
        collect_intel()
        collect_news()
    else:
        print("  (--skip: usando dados existentes)")

    run_analysis()
    print("\nPronto. Abra o painel: streamlit run wealth_dashboard.py --server.address=0.0.0.0 --server.port=8501")


if __name__ == "__main__":
    main()
