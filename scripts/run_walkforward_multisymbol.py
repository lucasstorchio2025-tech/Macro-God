"""
run_walkforward_multisymbol.py — Walk-Forward TS-Momentum para múltiplos símbolos.

Usa _run_backtest do walk_forward_validate.py (mesmos kwargs que Tokyo/London).
IS e OOS separados → métrica correta.

USO: venv\Scripts\python.exe -u scripts\run_walkforward_multisymbol.py
"""
from __future__ import annotations

import json
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine import config as C
from engine.data import dxy_pct_change_h4, load_all_prices, load_dxy, load_vix
from engine.regime import RuleBasedRegime
from engine.walk_forward_validate import _build_windows, _run_backtest

WF_TRAIN_BARS = 1440
WF_TEST_BARS = 720
WF_STEP_BARS = 720
SESSION_OVERRIDE = ["Tokyo"]
OUTPUT_FILE = PROJECT_ROOT / "reports" / "WALK_FORWARD_MULTISYMBOL_2026-07-19.json"


def _banner(msg: str = "") -> None:
    if msg:
        print(f"\n{'=' * 70}\n  {msg}\n{'=' * 70}")


def _mk(val) -> float:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return 0.0
    return float(val)


def main() -> None:
    _banner("WALK-FORWARD TS-MOMENTUM — MULTISYMBOL")
    print(f"  {datetime.now(timezone.utc).isoformat()} UTC")

    orig_session = deepcopy(C.SESSION_FILTER_ALLOW)
    C.SESSION_FILTER_ALLOW = SESSION_OVERRIDE

    # ── Dados ──────────────────────────────────────────────
    print("\n[1/4] Dados...")
    t0 = time.time()
    all_prices = load_all_prices(timeframe=C.TIMEFRAME, bars=C.BARS_LOOKBACK, align=True)
    common_h4 = next(iter(all_prices.values()))["close"].index
    vix = load_vix(period="max")
    dxy_pct = None
    try:
        dxy_raw = load_dxy(period="10y")
        dxy_pct = dxy_pct_change_h4(dxy_raw, common_h4,
                                    lookback=C.DXY_LIQUIDITY_STRESS_LOOKBACK_BARS)
    except Exception:
        pass
    print(f"   Disponível: {list(all_prices.keys())} — "
          f"{len(common_h4)} barras H4 ({time.time() - t0:.1f}s)")

    # ── Regime + Janelas ───────────────────────────────────
    print("\n[2/4] Regime + Janelas...")
    regime = RuleBasedRegime(vix=vix, prices_for_corr=all_prices)
    windows = _build_windows(common_h4, train_bars=WF_TRAIN_BARS,
                             test_bars=WF_TEST_BARS, step_bars=WF_STEP_BARS)
    print(f"   {len(windows)} janelas")

    # ── Walk-forward ───────────────────────────────────────
    print("\n[3/4] Walk-forward por símbolo:")
    target = ["XAUUSDm", "XAGUSDm", "EURUSDm", "GBPUSDm", "USDJPYm"]
    results: dict[str, dict] = {}

    for sym in target:
        if sym not in all_prices:
            print(f"   ⚠ {sym}: indisponível")
            results[sym] = {"error": "indisponível"}
            continue

        print(f"   {sym} ({len(windows)} janelas) ...", end=" ", flush=True)
        t_sym = time.time()

        prices_single = {sym: all_prices[sym]}
        oos_sharpes: list[float] = []

        for i, w in enumerate(windows, 1):
            try:
                # IS (train)
                _run_backtest(prices_single, regime, dxy_pct, None,
                              w["train_start"], w["train_end"],
                              f"{sym}_IS_w{i}")
                # OOS (test)
                oos = _run_backtest(prices_single, regime, dxy_pct, None,
                                    w["test_start"], w["test_end"],
                                    f"{sym}_OOS_w{i}")
                oos_sharpes.append(_mk(oos.get("sharpe")))
            except Exception:
                oos_sharpes.append(float("nan"))

        valid = [x for x in oos_sharpes if not np.isnan(x)]
        avg = np.mean(valid) if valid else 0.0
        wins_n = sum(1 for x in valid if x > 0)
        tot = len(valid)
        wr_str = (f"{wins_n}/{len(windows)} ({int(wins_n / tot * 100)}%)"
                  if tot > 0 else "0/0")
        elapsed = time.time() - t_sym

        results[sym] = {
            "OOS_avg_sharpe": round(avg, 4),
            "OOS_win_ratio": wr_str,
            "janelas_total": len(windows),
            "janelas_validas": tot,
            "sharpe_vals": [round(x, 4) for x in valid],
            "tempo_s": round(elapsed, 1),
        }

        st = "✅ VÁLIDO" if wins_n > 0 else "❌ REFUTADO"
        print(f"{st}  SR={avg:.3f}  wins={wr_str}  ({elapsed:.0f}s)")

    # ── Salva + Resumo ─────────────────────────────────────
    print("\n[4/4] Salvando...")
    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "available": list(all_prices.keys()),
        "target": target,
        "session": SESSION_OVERRIDE,
        "train_bars": WF_TRAIN_BARS,
        "test_bars": WF_TEST_BARS,
        "step_bars": WF_STEP_BARS,
        "total_janelas": len(windows),
        "results": results,
    }
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"   => {OUTPUT_FILE}")

    _banner("RESUMO")
    print(f"  {'Símbolo':10s} {'SR OOS':>8s} {'Wins':>8s}  Status")
    print(f"  {'-' * 42}")
    xau = _mk(results.get("XAUUSDm", {}).get("OOS_avg_sharpe"))
    for lab, r in results.items():
        if "error" in r:
            print(f"  {lab:10s} {'—':>8s} {'—':>8s}  ⚠")
        else:
            sr = _mk(r.get("OOS_avg_sharpe"))
            wr = r.get("OOS_win_ratio", "?")
            st = "✅" if sr > 0 else "❌ REFUTADO"
            print(f"  {lab:10s} {sr:>8.3f} {wr:>8s}  {st}")

    concl = "✅ momentum funciona no OOS (Tokyo)" if xau > 0 else "❌ walk-forward refuta momentum"
    print(f"\n  CONCLUSÃO (XAUUSDm): {concl}")
    print(f"  Prata/Forex: indisponíveis — abra símbolos no Market Watch do MT5")
    _banner()

    C.SESSION_FILTER_ALLOW = orig_session


if __name__ == "__main__":
    main()