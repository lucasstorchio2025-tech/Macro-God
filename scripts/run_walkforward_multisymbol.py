"""
run_walkforward_multisymbol.py — Walk-Forward TS-Momentum para múltiplos símbolos.

Carrega cada símbolo independentemente (align=False), calcula janelas
proporcionais aos dados disponíveis. Usa _run_backtest do walk_forward_validate.

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
from engine.data import load_prices, load_vix  # per-symbol, sem align
from engine.regime import RuleBasedRegime
from engine.walk_forward_validate import _build_windows, _run_backtest

WF_TRAIN_BARS = 1440
WF_TEST_BARS = 720
WF_STEP_BARS = 720
SESSION_OVERRIDE = ["Tokyo"]
OUTPUT_FILE = PROJECT_ROOT / "reports" / "WALK_FORWARD_MULTISYMBOL_2026-07-20.json"


def _banner(msg: str = "") -> None:
    if msg:
        print(f"\n{'=' * 70}\n  {msg}\n{'=' * 70}")


def _mk(val) -> float:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return 0.0
    return float(val)


def main() -> None:
    _banner("WALK-FORWARD TS-MOMENTUM — MULTISYMBOL (per-symbol)")
    print(f"  {datetime.now(timezone.utc).isoformat()} UTC")

    orig_session = deepcopy(C.SESSION_FILTER_ALLOW)
    C.SESSION_FILTER_ALLOW = SESSION_OVERRIDE

    target = ["XAUUSDm", "XAGUSDm", "EURUSDm", "GBPUSDm", "USDJPYm"]
    results: dict[str, dict] = {}

    vix = load_vix(period="max")
    regime = RuleBasedRegime(vix=vix, prices_for_corr=None)  # generic regime

    for sym in target:
        print(f"\n{'─' * 60}\n  {sym}\n{'─' * 60}")

        # Carrega dados do símbolo
        try:
            df = load_prices(sym, C.TIMEFRAME, C.BARS_LOOKBACK)
        except Exception as e:
            print(f"  ❌ Erro ao carregar {sym}: {e}")
            results[sym] = {"error": str(e)}
            continue

        if len(df) < WF_TRAIN_BARS + WF_TEST_BARS:
            print(f"  ⚠ {sym}: apenas {len(df)} barras (precisa de ≥{WF_TRAIN_BARS + WF_TEST_BARS})")
            print(f"    → abra gráfico H4 no MT5 e role até o início (Home)")
            results[sym] = {"error": f"insuficiente: {len(df)} barras"}
            continue

        h4 = df["close"].index
        windows = _build_windows(h4, WF_TRAIN_BARS, WF_TEST_BARS, WF_STEP_BARS)
        print(f"  {len(df)} barras → {len(windows)} janelas walk-forward")

        prices = {sym: df}
        oos_sharpes: list[float] = []
        t0 = time.time()

        for i, w in enumerate(windows, 1):
            try:
                # IS
                _run_backtest(prices, regime, None, None,
                              w["train_start"], w["train_end"],
                              f"{sym}_IS_w{i}")
                # OOS
                oos = _run_backtest(prices, regime, None, None,
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
        elapsed = time.time() - t0

        results[sym] = {
            "OOS_avg_sharpe": round(avg, 4),
            "OOS_win_ratio": wr_str,
            "barras": len(df),
            "janelas_total": len(windows),
            "janelas_validas": tot,
            "sharpe_vals": [round(x, 4) for x in valid],
            "tempo_s": round(elapsed, 1),
        }

        st = "✅ VÁLIDO" if wins_n > 0 else "❌ REFUTADO"
        print(f"  {st}  SR OOS={avg:.3f}  wins={wr_str}  ({elapsed:.0f}s)")

    # ── Salva ─────────────────────────────────────────────
    print(f"\n[Salvando] → {OUTPUT_FILE}")
    out = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "target": target,
        "session": SESSION_OVERRIDE,
        "train_bars": WF_TRAIN_BARS,
        "test_bars": WF_TEST_BARS,
        "step_bars": WF_STEP_BARS,
        "results": results,
    }
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    # ── Resumo ────────────────────────────────────────────
    _banner("RESUMO")
    print(f"  {'Símbolo':10s} {'Barras':>7s} {'SR OOS':>8s} {'Wins':>8s}  Status")
    print(f"  {'-' * 48}")
    for sym, r in results.items():
        if "error" in r:
            print(f"  {sym:10s} {'—':>7s} {'—':>8s} {'—':>8s}  ⚠ {r['error'][:40]}")
        else:
            sr = _mk(r.get("OOS_avg_sharpe"))
            wr = r.get("OOS_win_ratio", "?")
            nb = r.get("barras", 0)
            st = "✅" if sr > 0 else "❌ REFUTADO"
            print(f"  {sym:10s} {nb:>7d} {sr:>8.3f} {wr:>8s}  {st}")

    xau = _mk(results.get("XAUUSDm", {}).get("OOS_avg_sharpe"))
    eur = _mk(results.get("EURUSDm", {}).get("OOS_avg_sharpe"))
    gbp = _mk(results.get("GBPUSDm", {}).get("OOS_avg_sharpe"))
    jpy = _mk(results.get("USDJPYm", {}).get("OOS_avg_sharpe"))
    xag = _mk(results.get("XAGUSDm", {}).get("OOS_avg_sharpe"))

    print(f"\n  CONCLUSÃO (walk-forward Tokyo, TS-Momentum):")
    print(f"    XAUUSDm: {'✅ SR=' + str(xau) if xau > 0 else '❌ refutado'}")
    print(f"    XAGUSDm: {'✅ SR=' + str(xag) if xag > 0 else '❌ refutado ou dados insuficientes'}")
    print(f"    EURUSDm: {'✅ momentum funciona em forex!' if eur > 0 else '❌ refutado (confirma claim)'}")
    print(f"    GBPUSDm: {'✅' if gbp > 0 else '❌ refutado'}")
    print(f"    USDJPYm: {'✅' if jpy > 0 else '❌ refutado'}")

    if any(r.get("error", "").startswith("insuficiente") for r in results.values()):
        print(f"\n  ⚠ Símbolos com dados insuficientes: abra gráfico H4 no MT5 e role")
        print(f"    até o início (tecla Home) para baixar o histórico completo.")
    _banner()

    C.SESSION_FILTER_ALLOW = orig_session


if __name__ == "__main__":
    main()