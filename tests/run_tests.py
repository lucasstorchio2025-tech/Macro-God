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
    ("tests.test_meta_learner", [
        "test_parse_valid_json", "test_parse_clamp_risk_multiplier_high",
        "test_parse_clamp_risk_multiplier_low", "test_parse_clamp_confidence",
        "test_parse_reasoning_truncated", "test_parse_invalid_json",
        "test_parse_empty", "test_parse_none", "test_parse_missing_keys",
        "test_parse_junk_middleware", "test_parse_non_dict_response",
    ]),
    ("tests.test_executor_mocked", [
        "test_hard_cap_respected", "test_risk_cap_rejects_excess",
        "test_risk_cap_allows_safe", "test_vol_target_called_via_strategy",
        "test_risk_config_consistency",
    ]),
    ("tests.test_autonomous_oracle", [
        "test_liquidity_expansionary", "test_liquidity_tight",
        "test_liquidity_missing_data",
        "test_correlation_risk_on_genuine", "test_correlation_panic",
        "test_correlation_normal", "test_correlation_no_data",
        "test_regime_memory_record", "test_regime_memory_same_regime",
        "test_regime_memory_performance", "test_regime_memory_best_regime",
        "test_regime_memory_serialization",
        "test_thesis_generator_has_prompt",
        "test_oracle_analyze_with_fallback", "test_oracle_analyze_with_basic_data",
        "test_oracle_analyze_crisis",
        "test_fallback_allocation_crisis", "test_fallback_allocation_risk_off",
        "test_fallback_allocation_risk_on", "test_fallback_allocation_normal", "test_fallback_thesis_generation",
        "test_oracle_analyze_updates_regime_memory",
    ]),
    ("tests.test_self_evolution", [
        "test_parameter_mutate_respects_bounds",
        "test_parameter_mutate_high_confidence",
        "test_parameter_inactive", "test_default_parameter_pool",
        "test_performance_analyzer_empty", "test_performance_analyzer_basic",
        "test_max_drawdown", "test_max_drawdown_empty",
        "test_compute_trend_positive", "test_compute_trend_negative",
        "test_compute_trend_insufficient_data",
        "test_max_consecutive_losses",
        "test_tuner_initialization", "test_tuner_get_config_update",
        "test_strategy_registry", "test_strategy_select_risk_on",
        "test_strategy_select_crisis", "test_strategy_select_normal",
        "test_strategy_record_result", "test_strategy_record_unknown_strategy",
        "test_evolution_llm_has_prompt",
        "test_evolution_engine_init", "test_evolution_engine_evolve_no_trades",
        "test_evolution_engine_evolve_force",
        "test_apply_llm_recommendations_bounds",
    ]),
    ("tests.test_commander", [
        "test_commander_order_defaults", "test_commander_order_to_dict",
        "test_context_defaults",
        "test_safety_crisis_waits", "test_safety_crisis_close_all",
        "test_safety_risk_off_reduces",
        "test_safety_max_positions", "test_safety_no_signal",
        "test_fallback_with_signal", "test_fallback_without_signal",
        "test_fallback_ignore_open_symbol",
        "test_commander_init", "test_commander_get_status_fresh",
        "test_commander_learn_no_crash", "test_commander_cycle_round_trip",
    ]),
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
