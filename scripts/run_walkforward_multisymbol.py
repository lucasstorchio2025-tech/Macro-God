"""
run_walkforward_multisymbol.py — Walk-Forward TS-Momentum para múltiplos símbolos.

Reaproveita walk_forward_validate.py (genérico) para validar/refutar a alegação
"TS-Momentum não funciona em forex (comprovado)" com walk-forward real.

SÍMBOLOS TESTADOS:
  - XAUUSDm (ouro) — referência
  - XAGUSDm (prata) — testa se momentum funciona em outros metais
  - EURUSDm, GBPUSDm, USDJPYm — revalidação da claim do config.py

USO:
  cd Wealth_Engine
  venv\Scripts\python.exe -u scripts\run_walkforward_multisymbol.py
"""

from __future__ import annotations

import json
import sys
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine import config as C
from engine.data import dxy_pct_change_h4, load_all_prices, load_dxy, load_vix
from engine.macro_events import get_events_for_backtest
from engine.regime import RuleBasedRegime
from engine.signals import TSMomentumStrategy
from engine.backtest import run_backtest
from engine.analytics import basic_summary
from engine.walk_forward_validate import _build_windows

# ── Parâmetros ────────────────────────────────────────────
WF_TRAIN_BARS = 1440
WF_TEST_BARS = 720
WF_STEP_BARS = 720

SYMBOLS = [
    "XAUUSDm",  # ouro (referência)
    "XAGUSDm",  # prata
    "EURUSDm",
    "GBPUSDm",
    "USDJPYm",
]

SESSION_OVERRIDE = ["Tokyo"]  # só Tokyo (comprovado que funciona no ouro)

OUTPUT_FILE = PROJECT_ROOT / "reports" / "WALK_FORWARD_MULTISYMBOL_2026-07-19.json"


def banner(msg: str = "") -> None:
    if msg:
        print(f"\n{'=' * 70}")
        print(f"  {msg}")
        print(f"{'=' * 70}")
    else:
        print(f"{'─ ' * 35}")


def main() -> None:
    banner("WALK-FORWARD TS-MOMENTUM — MULTISYMBOL")
    print(f"  {datetime.utcnow().isoformat()} UTC")
    print(f"  Símbolos: {len(SYMBOLS)} — {', '.join(SYMBOLS)}")
    print(f"  Sessões: {SESSION_OVERRIDE}")
    print()

    original_session = deepcopy(C.SESSION_FILTER_ALLOW)
    C.SESSION_FILTER_ALLOW = SESSION_OVERRIDE

    # 1. Load data
    print("[1/5] Carregando dados...\n")
    t0 = time.time()
    prices = load_all_prices(timeframe=C.TIMEFRAME, bars=C.BARS_LOOKBACK, align=True)
    common_h4 = next(iter(prices.values()))["close"].index

    vix = load_vix(period="max")
    dxy_pct = None
    vix_h4 = None
    try:
        dxy_raw = load_dxy(period="10y")
        dxy_pct = dxy_pct_change_h4(dxy_raw, common_h4, lookback=C.DXY_LIQUIDITY_STRESS_LOOKBACK_BARS)
        vix_h4 = vix.pct_change(5).reindex(common_h4).ffill() * 100.0
    except Exception as e:
        print(f"   ⚠ DXY/VIX: {e}")

    macro_events = None
    try:
        macro_events = get_events_for_backtest(C.START_COMMON, C.END_DEFAULT)
    except Exception:
        pass

    print(f"   {len(prices)} símbolos, {len(common_h4)} barras H4 ({time.time() - t0:.1f}s)")

    # 2. Regime
    print("\n[2/5] Regime...\n")
    regime = RuleBasedRegime(vix=vix, prices_for_corr=prices)

    # 3. D1 momentum
    print("[3/5] D1 momentum...\n")
    d1_momentum: dict[str, np.ndarray] = {}
    if C.D1_FILTER_ENABLED:
        for sym, df in prices.items():
            daily_close = df["close"].resample("D").last().dropna()
            mom = (daily_close.shift(1) / daily_close.shift(C.D1_MOMENTUM_LOOKBACK_BARS + 1)) - 1.0
            d1_momentum[sym] = mom.reindex(common_h4, method="ffill").values
    print(f"   {len(d1_momentum)} símbolos com D1 momentum")

    # 4. Janelas
    print("\n[4/5] Janelas walk-forward...\n")
    windows = _build_windows(common_h4, train_bars=WF_TRAIN_BARS, test_bars=WF_TEST_BARS, step_bars=WF_STEP_BARS)
    print(f"   {len(windows)} janelas (train={WF_TRAIN_BARS} test={WF_TEST_BARS} step={WF_STEP_BARS})")

    # 5. Run per symbol
    print("\n[5/5] Walk-forward por símbolo:\n")
    results: dict[str, dict] = {}

    for sym in SYMBOLS:
        if sym not in prices:
            print(f"   ❌ {sym}: símbolo não encontrado\n")
            results[sym] = {"error": "symbol not found"}
            continue

        print(f"   {sym} ... ", end="", flush=True)
        t_sym = time.time()

        single_prices = {sym: prices[sym]}
        oos_sharpe_vals: list[float] = []

        for i, (start, end) in enumerate(windows, 1):
            try:
                res = run_backtest(
                    prices=single_prices,
                    strategy=TSMomentumStrategy(),
                    regime=regime,
                    d1_momentum={sym: d1_momentum.get(sym)} if d1_momentum else None,
                    dxy_pct=dxy_pct,
                    vix_h4=vix_h4,
                    macro_events=macro_events,
                    start=start,
                    end=end,
                    train_start=windows[0][0],
                    train_end=(
                        windows[-2][1] if len(windows) > 1 else windows[0][1]
                    ),
                )
                summary = basic_summary(res.details)
                oos_sharpe = summary.get("oos_sharpe", float("nan"))
                oos_sharpe_vals.append(oos_sharpe)
            except Exception:
                oos_sharpe_vals.append(float("nan"))

        valid_sharpes = [s for s in oos_sharpe_vals if not np.isnan(s)]
        avg_oos = np.mean(valid_sharpes) if valid_sharpes else float("nan")
        wins = sum(1 for s in valid_sharpes if s > 0)
        total = len(valid_sharpes)
        win_pct = f"{wins}/{total} ({int(wins / total * 100)}%)" if total > 0 else "0/0"
        elapsed = time.time() - t_sym

        results[sym] = {
            "OOS_avg_sharpe": round(avg_oos, 4) if not np.isnan(avg_oos) else None,
            "OOS_win_ratio": win_pct,
            "janelas_total": len(windows),
            "janelas_validas": total,
            "sharpe_vals": [round(s, 4) for s in oos_sharpe_vals if not np.isnan(s)],
            "tempo_s": round(elapsed, 1),
        }

        if wins > 0:
            print(f"✅ OOS SR={avg_oos:.3f}  wins={win_pct}  ({elapsed:.0f}s)")
        else:
            print(f"❌ REFUTADO  OOS SR={avg_oos:.3f}  wins=0/{total}  ({elapsed:.0f}s)")

    # 6. Salva resultados
    print("\n\nSalvando...\n")
    output = {
        "ts": datetime.utcnow().isoformat(),
        "symbols": SYMBOLS,
        "session": SESSION_OVERRIDE,
        "train_bars": WF_TRAIN_BARS,
        "test_bars": WF_TEST_BARS,
        "step_bars": WF_STEP_BARS,
        "total_janelas": len(windows),
        "results": results,
    }
    OUTOUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"   {OUTPUT_FILE}\n")

    # Resumo
    banner()
    print("RESUMO WALK-FORWARD MULTISYMBOL\n")
    for sym, r in results.items():
        if "error" in r:
            print(f"  {sym}: ⚠ {r['error']}")
            continue
        oos = r.get("OOS_avg_sharpe", 0)
        wr = r.get("OOS_win_ratio", "?")
        status = "✅ VÁLIDO" if oos > 0 else "❌ REFUTADO"
        print(f"  {sym:10s}  OOS={oos:>7.3f}  wins={wr}  {status}")

    banner()

    # Restaura sessão original
    C.SESSION_FILTER_ALLOW = original_session


if __name__ == "__main__":
    main()