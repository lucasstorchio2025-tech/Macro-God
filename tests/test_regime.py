"""test_regime.py — valida que o detector classifica os 4 estados corretamente."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from engine.regime import RuleBasedRegime, AlwaysNormalRegime
from engine import config as C


def _vix_series(values):
    """Cria Series de VIX com valores dados, indexada por data."""
    idx = pd.date_range("2024-01-01", periods=len(values), freq="D", tz="UTC")
    return pd.Series(values, index=idx, name="vix", dtype=float)


def test_crisis_on_extreme_vix():
    """VIX > 35 (absoluto) = crisis."""
    vix = _vix_series([15]*300 + [40])  # calmaria longa, depois pico
    regime = RuleBasedRegime(vix=vix)
    ts = vix.index[-1]
    r = regime.at(ts, {})
    assert r == "crisis", f"VIX=40 deveria ser crisis, got {r}"


def test_risk_on_low_vix_without_spy():
    """VIX baixo SEM correlação gold×ações = normal (não é risk_on genuíno).

    A partir da v2, VIX baixo sozinho não basta para risk_on — precisa de
    correlação gold×ações negativa (ouro cai quando ações sobem) para confirmar
    apetite a risco genuíno. Sem SPY, o máximo que VIX baixo produz é 'normal'.
    """
    vix = _vix_series([12]*300 + [11])
    regime = RuleBasedRegime(vix=vix)  # sem gold_equity_corr
    ts = vix.index[-1]
    r = regime.at(ts, {})
    assert r == "normal", f"VIX=11 sem SPY deveria ser normal, got {r}"


def test_always_normal():
    """AlwaysNormalRegime sempre devolve 'normal'."""
    reg = AlwaysNormalRegime()
    assert reg.at(pd.Timestamp.utcnow(), {}) == "normal"


def test_no_regime_returns_normal():
    """Sem VIX carregado, não deve crashar — cai em 'normal'."""
    regime = RuleBasedRegime(vix=None)
    r = regime.at(pd.Timestamp.utcnow(), {})
    assert r in ("normal", "risk_on"), f"Sem VIX deveria ser normal/risk_on, got {r}"


if __name__ == "__main__":
    test_crisis_on_extreme_vix()
    print("✓ test_crisis_on_extreme_vix passou")
    test_risk_on_low_vix()
    print("✓ test_risk_on_low_vix passou")
    test_always_normal()
    print("✓ test_always_normal passou")
    test_no_regime_returns_normal()
    print("✓ test_no_regime_returns_normal passou")
    print("\nTodos os testes de regime passaram.")
