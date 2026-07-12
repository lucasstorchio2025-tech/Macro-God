"""test_sizing.py — valida que vol-targeting + correlação funcionam matematicaticamente."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from engine import config as C
from engine.sizing import vol_target_scalar, usd_exposure, can_open_given_usd


def _synthetic(low_vol=False):
    n = 200
    vol = 0.002 if low_vol else 0.02
    rets = np.random.RandomState(42).normal(0, vol, n)
    close = 100 * np.cumprod(1 + rets)
    idx = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({"close": close}, index=idx)


def test_vol_target_reduces_volatile_asset():
    """Ativo com vol ALTA deve ter size MENOR que ativo com vol BAIXA."""
    df_calm = _synthetic(low_vol=True)
    df_wild = _synthetic(low_vol=False)
    ts = df_calm.index[-1]

    # precisa de colunas high/low pro realized_vol? não — só close
    s_calm = vol_target_scalar("X", df_calm, ts)
    s_wild = vol_target_scalar("X", df_wild, ts)
    assert s_wild < s_calm, (
        f"Vol-target falhou: ativo selvagem ({s_wild:.3f}) deveria ser < calmo ({s_calm:.3f})")


def test_vol_target_capped():
    """Scalar nunca passa de VOL_TARGET_CAP."""
    df = _synthetic(low_vol=True)
    ts = df.index[-1]
    s = vol_target_scalar("X", df, ts)
    assert s <= C.VOL_TARGET_CAP + 0.001, f"Scalar {s:.3f} excede cap {C.VOL_TARGET_CAP}"


def test_usd_exposure_aggregates():
    """Soma de |beta| × frac das posições."""
    class P:
        def __init__(self, sym, frac):
            self.symbol = sym
            self.size_frac = frac
    positions = [P("XAUUSDm", 0.5), P("XAUUSDm", 0.5), P("XAUUSDm", 0.3)]
    expo = usd_exposure(positions, 500)
    # XAU |−1|×0.5=0.5 + XAU |−1|×0.5=0.5 + XAU |−1|×0.3=0.3 → total 1.3
    assert abs(expo - 1.3) < 0.01, f"USD exposure {expo:.3f} != 1.3"


def test_usd_cap_blocks_excess():
    """Quando exposição USD já está no cap, nova entrada é bloqueada."""
    class P:
        def __init__(self, sym, frac):
            self.symbol = sym; self.size_frac = frac
    # já com 1.5 de exposição (2 posições XAUUSDm de 0.75 cada → |−1|×0.75×2 = 1.5)
    positions = [P("XAUUSDm", 0.75), P("XAUUSDm", 0.75)]
    # tentar adicionar outro USD não deve passar
    assert not can_open_given_usd("XAUUSDm", positions, 500)


if __name__ == "__main__":
    test_vol_target_reduces_volatile_asset()
    print("✓ test_vol_target_reduces_volatile_asset passou")
    test_vol_target_capped()
    print("✓ test_vol_target_capped passou")
    test_usd_exposure_aggregates()
    print("✓ test_usd_exposure_aggregates passou")
    test_usd_cap_blocks_excess()
    print("✓ test_usd_cap_blocks_excess passou")
    print("\nTodos os testes de sizing passaram.")
