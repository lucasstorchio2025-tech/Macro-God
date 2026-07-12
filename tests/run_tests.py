"""Roda todos os testes sem precisar de pytest.

Uso: python tests/run_tests.py
"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

tests = [
    ("tests.test_no_lookahead", ["test_momentum_signal_causal", "test_momentum_only_uses_past"]),
    ("tests.test_sizing", ["test_vol_target_reduces_volatile_asset", "test_vol_target_capped",
                            "test_usd_exposure_aggregates", "test_usd_cap_blocks_excess"]),
    ("tests.test_regime", ["test_crisis_on_extreme_vix", "test_risk_on_low_vix_without_spy",
                            "test_always_normal", "test_no_regime_returns_normal"]),
    ("tests.test_liquidity_signal", ["test_stress_scenario", "test_normal_scenario",
                                      "test_dxy_very_strong", "test_panic_without_flight_to_dollar",
                                      "test_missing_data", "test_missing_dxy_change"]),
]

passed = failed = 0
for mod_name, fns in tests:
    mod = __import__(mod_name, fromlist=fns)
    for fn_name in fns:
        fn = getattr(mod, fn_name)
        try:
            fn()
            print(f"  [OK] {mod_name}.{fn_name}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {mod_name}.{fn_name}: {e}")
            traceback.print_exc()
            failed += 1

print(f"\n{'='*50}")
print(f"Result: {passed} passed, {failed} failed")
print(f"{'='*50}")
sys.exit(0 if failed == 0 else 1)
