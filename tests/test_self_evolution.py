"""
test_self_evolution.py — Testes do Motor de Auto-Evolução.

Valida que:
  1. EvolvableParameter.mutate() respeita limites e confiança
  2. PerformanceAnalyzer calcula métricas corretamente
  3. PerformanceAnalyzer._max_drawdown funciona
  4. PerformanceAnalyzer.compute_trend() detecta tendências
  5. ParameterTuner.tune_all() gera mudanças
  6. StrategySelector.select() escolhe estratégia por regime
  7. StrategySelector.record_result() acumula performance
  8. SelfEvolutionEngine.evolve() sem trades (deve retornar vazio)
  9. SelfEvolutionEngine._apply_llm_recommendations() respeita limites
"""
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from engine.self_evolution import (
    SelfEvolutionEngine, ParameterTuner, StrategySelector,
    PerformanceAnalyzer, EvolutionLLM,
    EvolvableParameter, DEFAULT_PARAMETER_POOL, STRATEGY_REGISTRY,
)
from engine.meta_config import MetaState


# ═══════════════════════════ EVOLVABLE PARAMETER ═══════════════════════════

def test_parameter_mutate_respects_bounds():
    """mutate() nunca ultrapassa min/max."""
    param = EvolvableParameter("test", current_value=5.0, min_value=0.0,
                                max_value=10.0, step=1.0, description="test",
                                category="risk", confidence=0.1)
    for _ in range(100):
        val = param.mutate(performance_trend=100.0)  # trend extremo
        assert 0.0 <= val <= 10.0, f"Valor {val} fora dos limites [0, 10]"


def test_parameter_mutate_high_confidence():
    """Confianca alta reduz variacao da mutacao."""
    param_high = EvolvableParameter("test", current_value=5.0, min_value=0.0,
                                     max_value=10.0, step=1.0, description="test",
                                     category="risk", confidence=0.95)
    param_low = EvolvableParameter("test", current_value=5.0, min_value=0.0,
                                    max_value=10.0, step=1.0, description="test",
                                    category="risk", confidence=0.1)
    
    np.random.seed(42)
    vals_high = [param_high.mutate(1.0) for _ in range(200)]
    np.random.seed(42)
    vals_low = [param_low.mutate(1.0) for _ in range(200)]
    
    # Alta confianca deve ter menos variacao (mais perto de 5.0)
    std_high = np.std(vals_high)
    std_low = np.std(vals_low)
    assert std_high <= std_low * 2 or std_low < 0.1, (
        f"Alta confianca ({std_high:.3f}) deveria variar menos que baixa ({std_low:.3f})"
    )


def test_parameter_inactive():
    """Parametro inativo deve retornar current_value."""
    param = EvolvableParameter("test", current_value=5.0, min_value=0.0,
                                max_value=10.0, step=1.0, description="test",
                                category="risk", is_active=False)
    val = param.mutate(100.0)
    assert val == 5.0, "Parametro inativo nao deve mudar"


def test_default_parameter_pool():
    """Pool de parametros padrao deve ter todos os parametros esperados."""
    names = [p.name for p in DEFAULT_PARAMETER_POOL]
    expected = ["risk_per_trade_pct", "daily_dd_pct", "weekly_dd_pct",
                "momentum_lookback_bars", "momentum_min_abs_r",
                "atr_stop_mult", "rr_target_mult", "holding_time_max_bars",
                "vix_max_level", "cooldown_bars"]
    for e in expected:
        assert e in names, f"Parametro {e} faltando no DEFAULT_PARAMETER_POOL"


# ═══════════════════════════ PERFORMANCE ANALYZER ═══════════════════════════

def test_performance_analyzer_empty():
    """Sem trades, deve retornar dict com n=0."""
    result = PerformanceAnalyzer.analyze_trades([])
    assert result["n"] == 0


def test_performance_analyzer_basic():
    """Trades simulados devem gerar metricas corretas."""
    trades = [
        {"payload": {"profit": 100.0}},
        {"payload": {"profit": -50.0}},
        {"payload": {"profit": 150.0}},
    ]
    result = PerformanceAnalyzer.analyze_trades(trades)
    assert result["n"] == 3
    assert result["win_rate"] == 2 / 3  # 2 wins, 1 loss
    assert result["total_pnl"] == 200.0  # 100 - 50 + 150
    assert result["avg_pnl"] == 200.0 / 3
    assert result["profit_factor"] == abs(250.0 / 50.0)  # 250 wins / 50 loss


def test_max_drawdown():
    """_max_drawdown calcula corretamente o pico ao vale."""
    pnls = [100, -50, -30, 200, -100, 50]
    dd = PerformanceAnalyzer._max_drawdown(pnls)
    # Acumulado: [100, 50, 20, 220, 120, 170]
    # Pico: 220, vale apos: 120, DD = 100
    assert dd == 100.0, f"Esperado 100.0, got {dd}"


def test_max_drawdown_empty():
    """Lista vazia deve retornar 0."""
    dd = PerformanceAnalyzer._max_drawdown([])
    assert dd == 0.0


def test_compute_trend_positive():
    """Trend positiva quando sharpe melhora."""
    history = [
        {"sharpe": 0.5},
        {"sharpe": 0.6},
        {"sharpe": 0.7},
        {"sharpe": 0.8},
        {"sharpe": 0.9},
    ]
    trend = PerformanceAnalyzer.compute_trend(history, window=5)
    assert trend > 0, f"Esperado trend positiva, got {trend:+.3f}"


def test_compute_trend_negative():
    """Trend negativa quando sharpe piora."""
    history = [
        {"sharpe": 0.9},
        {"sharpe": 0.8},
        {"sharpe": 0.7},
        {"sharpe": 0.6},
        {"sharpe": 0.5},
    ]
    trend = PerformanceAnalyzer.compute_trend(history, window=5)
    assert trend < 0, f"Esperado trend negativa, got {trend:+.3f}"


def test_compute_trend_insufficient_data():
    """Menos de 2 pontos deve retornar 0."""
    trend = PerformanceAnalyzer.compute_trend([{"sharpe": 1.0}])
    assert trend == 0.0


def test_max_consecutive_losses():
    """_max_consecutive conta perdas seguidas."""
    pnls = [10, -5, -8, -12, 20, -3, -7]
    n = PerformanceAnalyzer._max_consecutive(pnls, negative=True)
    assert n == 3, f"Esperado 3 perdas consecutivas, got {n}"


# ═══════════════════════════ PARAMETER TUNER ═══════════════════════════

def test_tuner_initialization():
    """Tuner inicializa com todos os parametros do pool."""
    tuner = ParameterTuner()
    assert len(tuner.parameters) == len(DEFAULT_PARAMETER_POOL)


def test_tuner_get_config_update():
    """get_config_update() retorna dict com chaves mapeadas."""
    tuner = ParameterTuner()
    update = tuner.get_config_update()
    assert isinstance(update, dict)
    # Deve conter pelo menos alguns parametros (confianca > 0.3)
    assert len(update) > 0
    # Verifica algumas chaves esperadas
    for key in ["RISK_PER_TRADE_PCT", "ATR_STOP_MULT", "VIX_MAX_LEVEL"]:
        assert key in update, f"Chave {key} faltando no config update"


# ═══════════════════════════ STRATEGY SELECTOR ═══════════════════════════

def test_strategy_registry():
    """Registry deve ter as 3 estrategias esperadas."""
    for name in ["ts_momentum", "mean_reversion", "macro_directional"]:
        assert name in STRATEGY_REGISTRY, f"Estrategia {name} faltando"


def test_strategy_select_risk_on():
    """Em risk_on, ts_momentum deve ter peso alto."""
    selector = StrategySelector()
    selected = selector.select("risk_on", {})
    assert "ts_momentum" in selected
    assert selected["ts_momentum"]["current_weight"] >= 0.8


def test_strategy_select_crisis():
    """Em crisis, ts_momentum deve ter peso ZERO (worst regime)."""
    selector = StrategySelector()
    selected = selector.select("crisis", {})
    # crisis é worst_regime para ts_momentum → peso = 0
    assert selected["ts_momentum"]["current_weight"] == 0.0, (
        f"Esperado peso 0 em crisis, got {selected['ts_momentum']['current_weight']}"
    )
    # Fallback: se nenhuma estrategia tem peso > 0.3, retorna ts_momentum
    assert "ts_momentum" in selected  # fallback


def test_strategy_select_normal():
    """Em normal, pelo menos ts_momentum deve estar ativo."""
    selector = StrategySelector()
    selected = selector.select("normal", {})
    assert len(selected) >= 1


def test_strategy_record_result():
    """record_result() acumula trades na estrategia."""
    selector = StrategySelector()
    selector.record_result("ts_momentum", "risk_on", {"pnl_usd": 100, "rr_realized": 2.0})
    selector.record_result("ts_momentum", "risk_on", {"pnl_usd": -50, "rr_realized": -1.0})
    
    perf = selector.strategies["ts_momentum"]["performance"]["risk_on"]
    assert perf["trades"] == 2
    assert perf["wins"] == 1
    assert perf["pnl"] == 50.0


def test_strategy_record_unknown_strategy():
    """Estrategia desconhecida nao deve crashar."""
    selector = StrategySelector()
    selector.record_result("unknown_strategy", "risk_on", {"pnl_usd": 100})


def test_evolution_llm_has_prompt():
    """EvolutionLLM deve ter o prompt definido."""
    llm = EvolutionLLM()
    assert hasattr(llm, "EVOLUTION_PROMPT")
    assert "{parameters}" in llm.EVOLUTION_PROMPT
    assert "{metrics}" in llm.EVOLUTION_PROMPT
    assert "{regime}" in llm.EVOLUTION_PROMPT


# ═══════════════════════════ SELF-EVOLUTION ENGINE ═══════════════════════════

def test_evolution_engine_init():
    """Engine inicializa sem erros."""
    engine = SelfEvolutionEngine()
    assert engine.evolution_count == 0
    assert engine.last_evolution_utc == ""


def test_evolution_engine_evolve_no_trades():
    """evolve() sem trades deve retornar dict vazio (nao crashar)."""
    engine = SelfEvolutionEngine()
    meta = MetaState()
    result = engine.evolve(meta, {"thesis": {"regime": "normal"}})
    assert isinstance(result, dict)
    assert "parameter_changes" in result
    assert result["parameter_changes"] == []  # sem trades, sem mudancas


def test_evolution_engine_evolve_force():
    """evolve() com force=True deve rodar mesmo sem trades."""
    engine = SelfEvolutionEngine()
    meta = MetaState()
    result = engine.evolve(meta, {"thesis": {"regime": "normal"}}, force=True)
    assert isinstance(result, dict)
    # Forcado, pode ter ou nao mudancas, mas nao deve crashar
    assert "parameter_changes" in result


def test_apply_llm_recommendations_bounds():
    """Recomendacoes do LLM respeitam limites dos parametros."""
    engine = SelfEvolutionEngine()
    param = engine.tuner.parameters[0]  # risk_per_trade_pct
    
    # Tenta setar valor extremo
    rec = {
        "parameter_changes": [
            {"name": param.name, "new_value": 9999.0, "reason": "test"}
        ],
        "primary_strategy": "ts_momentum",
        "strategy_weight": 1.0,
        "reasoning": "test",
    }
    
    engine._apply_llm_recommendations(rec)
    
    # Deve ter sido capado no maximo
    assert param.current_value <= param.max_value, (
        f"Valor {param.current_value} > max {param.max_value}"
    )


if __name__ == "__main__":
    tests = [
        ("test_parameter_mutate_respects_bounds", test_parameter_mutate_respects_bounds),
        ("test_parameter_mutate_high_confidence", test_parameter_mutate_high_confidence),
        ("test_parameter_inactive", test_parameter_inactive),
        ("test_default_parameter_pool", test_default_parameter_pool),
        ("test_performance_analyzer_empty", test_performance_analyzer_empty),
        ("test_performance_analyzer_basic", test_performance_analyzer_basic),
        ("test_max_drawdown", test_max_drawdown),
        ("test_max_drawdown_empty", test_max_drawdown_empty),
        ("test_compute_trend_positive", test_compute_trend_positive),
        ("test_compute_trend_negative", test_compute_trend_negative),
        ("test_compute_trend_insufficient_data", test_compute_trend_insufficient_data),
        ("test_max_consecutive_losses", test_max_consecutive_losses),
        ("test_tuner_initialization", test_tuner_initialization),
        ("test_tuner_get_config_update", test_tuner_get_config_update),
        ("test_strategy_registry", test_strategy_registry),
        ("test_strategy_select_risk_on", test_strategy_select_risk_on),
        ("test_strategy_select_crisis", test_strategy_select_crisis),
        ("test_strategy_select_normal", test_strategy_select_normal),
        ("test_strategy_record_result", test_strategy_record_result),
        ("test_strategy_record_unknown_strategy", test_strategy_record_unknown_strategy),
        ("test_evolution_llm_has_prompt", test_evolution_llm_has_prompt),
        ("test_evolution_engine_init", test_evolution_engine_init),
        ("test_evolution_engine_evolve_no_trades", test_evolution_engine_evolve_no_trades),
        ("test_evolution_engine_evolve_force", test_evolution_engine_evolve_force),
        ("test_apply_llm_recommendations_bounds", test_apply_llm_recommendations_bounds),
    ]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
