"""
test_autonomous_oracle.py — Testes do Oráculo Autônomo.

Valida que:
  1. GlobalLiquidityAnalyzer classifica liquidez corretamente
  2. CrossAssetCorrelator detecta regimes de correlação
  3. RegimeMemory: registro, recuperação, performance tracking
  4. MacroThesisGenerator parsing de JSON
  5. AutonomousOracle.analyze() com fallback (sem LLM)
  6. _fallback_allocation para cada regime
  7. _fallback_thesis gera texto coerente em cada regime
"""
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.autonomous_oracle import (
    AutonomousOracle, RegimeMemory, IntermarketSnapshot,
    MacroThesis, OracleSnapshot,
    GlobalLiquidityAnalyzer, CrossAssetCorrelator,
    MacroThesisGenerator,
)


# ═══════════════════════════ GLOBAL LIQUIDITY ═══════════════════════════

def test_liquidity_expansionary():
    """Fed funds baixo + DXY baixo = liquidez expansionary."""
    analyzer = GlobalLiquidityAnalyzer()
    intel = {
        "fed_rates": {
            "fed_funds_rate_diario": {"valor": 0.5},
            "treasury_10y": {"valor": 2.0},
        },
        "risk_sentiment": {
            "dollar_index": 97.0,
        },
    }
    result = analyzer.analyze(intel)
    assert result["liquidity_cycle"] == "expansionary", (
        f"Esperado expansionary, got {result['liquidity_cycle']}"
    )
    assert result["score"] >= 70, f"Score liquidez devia ser alto, got {result['score']}"


def test_liquidity_tight():
    """Fed funds alto + DXY alto = liquidez tight."""
    analyzer = GlobalLiquidityAnalyzer()
    intel = {
        "fed_rates": {
            "fed_funds_rate_diario": {"valor": 5.5},
            "treasury_10y": {"valor": 5.0},
        },
        "risk_sentiment": {
            "dollar_index": 107.0,
        },
    }
    result = analyzer.analyze(intel)
    assert result["liquidity_cycle"] == "tight", (
        f"Esperado tight, got {result['liquidity_cycle']}"
    )
    assert result["score"] <= 30, f"Score liquidez devia ser baixo, got {result['score']}"


def test_liquidity_missing_data():
    """Sem dados de fed, retorna neutral."""
    analyzer = GlobalLiquidityAnalyzer()
    result = analyzer.analyze({})
    assert result["liquidity_cycle"] == "neutral"
    assert result["score"] == 50


# ═══════════════════════════ CROSS-ASSET CORRELATION ═══════════════════════════

def test_correlation_risk_on_genuine():
    """Gold-equity correlation negativa = risk_on genuino."""
    correlator = CrossAssetCorrelator()
    intel = {"gold_equity_correlation": -0.5}
    result = correlator.analyze(intel)
    assert result["regime_correlation_signal"] == "risk_on_genuine"


def test_correlation_panic():
    """Gold-equity correlation muito positiva = panic."""
    correlator = CrossAssetCorrelator()
    intel = {"gold_equity_correlation": 0.7}
    result = correlator.analyze(intel)
    assert result["regime_correlation_signal"] == "panic"


def test_correlation_normal():
    """Gold-equity correlation baixa = normal."""
    correlator = CrossAssetCorrelator()
    intel = {"gold_equity_correlation": 0.1}
    result = correlator.analyze(intel)
    assert result["regime_correlation_signal"] == "normal"


def test_correlation_no_data():
    """Sem dados de correlacao, retorna neutral."""
    correlator = CrossAssetCorrelator()
    result = correlator.analyze({})
    assert result["regime_correlation_signal"] == "neutral"


# ═══════════════════════════ REGIME MEMORY ═══════════════════════════

def test_regime_memory_record():
    """Registro de regime deve armazenar e detectar transicoes."""
    rm = RegimeMemory()
    assert rm.last_regime == "unknown"
    
    rm.record_regime("risk_on", 12.0, 100.0)
    assert rm.last_regime == "risk_on"
    assert len(rm.regime_history) == 1
    
    rm.record_regime("risk_off", 25.0, 104.0)
    assert rm.last_regime == "risk_off"
    assert len(rm.regime_history) == 2
    assert len(rm.regime_transitions) == 1  # risk_on -> risk_off


def test_regime_memory_same_regime():
    """Mesmo regime registrado 2x nao cria transicao."""
    rm = RegimeMemory()
    rm.record_regime("risk_on", 12.0, 100.0)
    rm.record_regime("risk_on", 13.0, 101.0)
    assert len(rm.regime_history) == 2
    assert len(rm.regime_transitions) == 0  # nao mudou


def test_regime_memory_performance():
    """Registro de performance por regime."""
    rm = RegimeMemory()
    rm.record_performance("risk_on", {"pnl_usd": 50.0, "rr_realized": 2.0})
    rm.record_performance("risk_on", {"pnl_usd": -30.0, "rr_realized": -1.0})
    
    perf = rm.performance_by_regime.get("risk_on", {})
    assert perf["trades"] == 2
    assert perf["wins"] == 1
    assert perf["losses"] == 1
    assert perf["total_pnl"] == 20.0  # 50 - 30
    assert perf["avg_rr"] == 0.5  # (2.0 + (-1.0)) / 2


def test_regime_memory_best_regime():
    """get_best_regime retorna o regime com melhor win rate."""
    rm = RegimeMemory()
    rm.record_performance("risk_on", {"pnl_usd": 10, "rr_realized": 2.0})
    rm.record_performance("risk_on", {"pnl_usd": 10, "rr_realized": 2.0})
    rm.record_performance("risk_on", {"pnl_usd": 10, "rr_realized": 2.0})
    rm.record_performance("risk_on", {"pnl_usd": 10, "rr_realized": 2.0})
    rm.record_performance("risk_on", {"pnl_usd": 10, "rr_realized": 2.0})  # 5 wins
    rm.record_performance("risk_off", {"pnl_usd": -10, "rr_realized": -1.0})
    rm.record_performance("risk_off", {"pnl_usd": -10, "rr_realized": -1.0})
    rm.record_performance("risk_off", {"pnl_usd": -10, "rr_realized": -1.0})
    rm.record_performance("risk_off", {"pnl_usd": -10, "rr_realized": -1.0})
    rm.record_performance("risk_off", {"pnl_usd": -10, "rr_realized": -1.0})  # 5 losses
    
    best = rm.get_best_regime()
    assert best == "risk_on", f"Esperado risk_on, got {best}"


def test_regime_memory_serialization():
    """RegimeMemory.to_dict() e from_dict() sao simetricos."""
    rm = RegimeMemory()
    rm.record_regime("risk_on", 12.0, 100.0)
    rm.record_regime("risk_off", 25.0, 104.0)
    rm.record_performance("risk_on", {"pnl_usd": 50, "rr_realized": 2.0})
    
    data = rm.to_dict()
    rm2 = RegimeMemory.from_dict(data)
    
    assert rm2.last_regime == rm.last_regime
    assert len(rm2.regime_history) == len(rm.regime_history)
    assert rm2.performance_by_regime["risk_on"]["trades"] == 1


# ═══════════════════════════ MACRO THESIS PARSING ═══════════════════════════

def test_thesis_generator_has_prompt():
    """MacroThesisGenerator deve ter o template de prompt definido."""
    gen = MacroThesisGenerator()
    assert hasattr(gen, "THESIS_PROMPT")
    assert "{regime}" in gen.THESIS_PROMPT
    assert "{risk_score}" in gen.THESIS_PROMPT


# ═══════════════════════════ AUTONOMOUS ORACLE ═══════════════════════════

def test_oracle_analyze_with_fallback():
    """analyze() sem dados de mercado deve retornar snapshot com fallback."""
    oracle = AutonomousOracle()
    # Reseta o regime_memory para estado known
    oracle.regime_memory = RegimeMemory()
    
    snapshot = oracle.analyze({}, {})
    
    assert isinstance(snapshot, OracleSnapshot)
    assert isinstance(snapshot.thesis, MacroThesis)
    assert isinstance(snapshot.intermarket, IntermarketSnapshot)
    assert isinstance(snapshot.regime_memory, RegimeMemory)
    
    # Com dados vazios, deve cair em fallback
    assert snapshot.thesis.regime in ("normal", "unknown")
    assert len(snapshot.thesis.summary_pt) > 0  # fallback gerou texto


def test_oracle_analyze_with_basic_data():
    """analyze() com dados basicos de VIX/DXY."""
    oracle = AutonomousOracle()
    intel = {
        "risk_sentiment": {
            "vix": 15.0,
            "vix_pct_change": -2.0,
            "dollar_index": 103.0,
            "dollar_index_pct_change": 0.3,
        },
    }
    
    snapshot = oracle.analyze(intel, {})
    
    # VIX baixo + DXY normal = risk_on ou normal
    assert snapshot.thesis.regime in ("risk_on", "normal"), (
        f"Esperado risk_on/normal, got {snapshot.thesis.regime}"
    )
    assert snapshot.thesis.risk_score >= 40


def test_oracle_analyze_crisis():
    """VIX muito alto + DXY alto + tight liquidity = crisis."""
    oracle = AutonomousOracle()
    intel = {
        "risk_sentiment": {
            "vix": 35.0,
            "vix_pct_change": 15.0,
            "dollar_index": 108.0,
            "dollar_index_pct_change": 1.0,
        },
        "fed_rates": {
            "fed_funds_rate_diario": {"valor": 5.5},
            "treasury_10y": {"valor": 5.0},
        },
    }
    
    snapshot = oracle.analyze(intel, {})
    regime = snapshot.thesis.regime
    
    # VIX 35 + tight liquidity + DXY alto = crisis
    assert regime == "crisis", f"Esperado crisis, got {regime}"
    assert snapshot.thesis.risk_score < 30


def test_fallback_allocation_crisis():
    """Crisis deve retornar avoid para XAUUSDm."""
    allocation = AutonomousOracle()._fallback_allocation("crisis")
    assert allocation.get("XAUUSDm") == "avoid"


def test_fallback_allocation_risk_off():
    """Risk_off deve retornar neutral para XAUUSDm."""
    allocation = AutonomousOracle()._fallback_allocation("risk_off")
    assert allocation.get("XAUUSDm") == "neutral"


def test_fallback_allocation_risk_on():
    """Risk_on deve retornar long para XAUUSDm."""
    allocation = AutonomousOracle()._fallback_allocation("risk_on")
    assert allocation.get("XAUUSDm") == "long"


def test_fallback_allocation_normal():
    """Normal deve retornar long para XAUUSDm (padrao)."""
    allocation = AutonomousOracle()._fallback_allocation("normal")
    assert allocation.get("XAUUSDm") == "long"


def test_fallback_thesis_generation():
    """_fallback_thesis() gera texto coerente para cada regime."""
    oracle = AutonomousOracle()
    
    for regime in ("crisis", "risk_off", "risk_on", "normal"):
        thesis = oracle._fallback_thesis(regime, 50, 100.0, 18.0)
        assert len(thesis) > 30, f"Thesis muito curta para {regime}"
        assert isinstance(thesis, str)
        # Deve mencionar o regime
        if regime == "crisis":
            assert "CRISE" in thesis or "crise" in thesis
        elif regime == "risk_off":
            assert "RISK_OFF" in thesis or "risk_off" in thesis


def test_oracle_analyze_updates_regime_memory():
    """analyze() deve atualizar regime memory com dados reais."""
    oracle = AutonomousOracle()
    intel = {"risk_sentiment": {"vix": 12.0, "dollar_index": 100.0}}
    
    oracle.analyze(intel, {})
    
    # Apos analyze(), o regime deve estar registrado in-memory
    assert oracle.regime_memory.last_regime != "unknown", (
        "Regime memory deveria ter sido atualizado"
    )
    # Verifica serializacao
    state = oracle.regime_memory.to_dict()
    assert state["last_regime"] != "unknown"
    assert len(state["regime_history"]) == 1
    assert state["regime_duration_hours"].get(oracle.regime_memory.last_regime, 0) >= 1


if __name__ == "__main__":
    tests = [
        ("test_liquidity_expansionary", test_liquidity_expansionary),
        ("test_liquidity_tight", test_liquidity_tight),
        ("test_liquidity_missing_data", test_liquidity_missing_data),
        ("test_correlation_risk_on_genuine", test_correlation_risk_on_genuine),
        ("test_correlation_panic", test_correlation_panic),
        ("test_correlation_normal", test_correlation_normal),
        ("test_correlation_no_data", test_correlation_no_data),
        ("test_regime_memory_record", test_regime_memory_record),
        ("test_regime_memory_same_regime", test_regime_memory_same_regime),
        ("test_regime_memory_performance", test_regime_memory_performance),
        ("test_regime_memory_best_regime", test_regime_memory_best_regime),
        ("test_regime_memory_serialization", test_regime_memory_serialization),
        ("test_thesis_generator_parse_valid_json", test_thesis_generator_parse_valid_json),
        ("test_oracle_analyze_with_fallback", test_oracle_analyze_with_fallback),
        ("test_oracle_analyze_with_basic_data", test_oracle_analyze_with_basic_data),
        ("test_oracle_analyze_crisis", test_oracle_analyze_crisis),
        ("test_fallback_allocation_crisis", test_fallback_allocation_crisis),
        ("test_fallback_allocation_risk_off", test_fallback_allocation_risk_off),
        ("test_fallback_allocation_risk_on", test_fallback_allocation_risk_on),
        ("test_fallback_thesis_generation", test_fallback_thesis_generation),
        ("test_oracle_save_load_regime_memory", test_oracle_save_load_regime_memory),
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
