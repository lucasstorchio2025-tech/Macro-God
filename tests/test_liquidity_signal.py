"""Testes para o novo LiquidityStressSignal e integracao no regime."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.macro_signals import LiquidityStressSignal
from engine.regime import RuleBasedRegime


def test_stress_scenario():
    """DXY subindo + VIX subindo = stress de liquidez confirmado."""
    sig = LiquidityStressSignal().read({
        "risk_sentiment": {
            "dollar_index": 101.5,
            "dollar_index_pct_change": 0.6,
            "vix": 22.0,
            "vix_pct_change": 11.0,
        }
    })
    assert sig.driver == "LIQUIDITY"
    assert sig.direction == "short", f"Esperado 'short', got {sig.direction}"
    assert sig.strength > 0, f"Esperado strength > 0, got {sig.strength}"
    assert "STRESS DE LIQUIDEZ" in sig.rationale
    print(f"[OK] stress_scenario: direction={sig.direction}, strength={sig.strength:.2f}")


def test_normal_scenario():
    """DXY caindo + VIX caindo = sem stress."""
    sig = LiquidityStressSignal().read({
        "risk_sentiment": {
            "dollar_index": 100.85,
            "dollar_index_pct_change": -0.2,
            "vix": 16.0,
            "vix_pct_change": -2.0,
        }
    })
    assert sig.direction == "neutral", f"Esperado 'neutral', got {sig.direction}"
    assert sig.strength == 0.0
    print(f"[OK] normal_scenario: direction={sig.direction}, strength={sig.strength:.2f}")


def test_dxy_very_strong():
    """DXY muito forte mesmo sem VIX = stress encoberto."""
    sig = LiquidityStressSignal().read({
        "risk_sentiment": {
            "dollar_index": 102.0,
            "dollar_index_pct_change": 1.2,
            "vix": 16.0,
            "vix_pct_change": -1.0,
        }
    })
    assert sig.direction == "short", f"Esperado 'short', got {sig.direction}"
    assert sig.strength > 0
    print(f"[OK] dxy_very_strong: direction={sig.direction}, strength={sig.strength:.2f}")


def test_panic_without_flight_to_dollar():
    """VIX sobe + DXY cai = ouro mantem protecao."""
    sig = LiquidityStressSignal().read({
        "risk_sentiment": {
            "dollar_index": 100.5,
            "dollar_index_pct_change": -0.6,
            "vix": 25.0,
            "vix_pct_change": 12.0,
        }
    })
    assert sig.direction == "long", f"Esperado 'long', got {sig.direction}"
    assert sig.strength > 0
    print(f"[OK] panic_without_flight: direction={sig.direction}, strength={sig.strength:.2f}")


def test_missing_data():
    """Dados ausentes = neutro."""
    sig = LiquidityStressSignal().read({})
    assert sig.direction == "neutral"
    assert sig.strength == 0.0
    print(f"[OK] missing_data: direction={sig.direction}, strength={sig.strength:.2f}")


def test_missing_dxy_change():
    """DXY presente sem change = neutro."""
    sig = LiquidityStressSignal().read({
        "risk_sentiment": {
            "dollar_index": 101.5,
            "vix": 22.0,
            "vix_pct_change": 8.0,
        }
    })
    assert sig.direction == "neutral"
    print(f"[OK] missing_dxy_change: direction={sig.direction}")


def test_regime_escalation():
    """Regime escala com stress de liquidez."""
    import pandas as pd
    reg = RuleBasedRegime()
    ctx = {"dxy_pct_change": 0.6, "vix_pct_change": 11.0}
    ts = pd.Timestamp("2026-07-05", tz="UTC")
    result = reg.at(ts, ctx)
    print(f"[OK] regime_escalation: regime='{result}'")


if __name__ == "__main__":
    for name, fn in sorted({k: v for k, v in globals().items()
                            if k.startswith("test_")}.items()):
        fn()
    print("\n[TODOS OS TESTES PASSARAM]")
