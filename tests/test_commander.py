"""
test_commander.py — Testes do Comandante Autônomo.

Valida que:
  1. CommanderDecisionEngine.decide() regras de segurança
     - crisis → close_all/wait
     - risk_off + score baixo → wait/reduce
     - max positions → wait
     - sem sinal → wait
  2. CommanderDecisionEngine._fallback_decision()
  3. CommanderOrder.to_dict() funciona
  4. CommanderDecisionContext defaults
  5. AutonomousCommander.get_status() sem ciclos
  6. AutonomousCommander.learn() não crasha
"""
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.commander import (
    AutonomousCommander, CommanderOrder, CommanderDecisionContext,
    CommanderDecisionEngine,
)
from engine.autonomous_oracle import AutonomousOracle, OracleSnapshot, MacroThesis
from engine.meta_config import MetaState
from dataclasses import replace


# ═══════════════════════════ COMMANDER ORDER ═══════════════════════════

def test_commander_order_defaults():
    """CommanderOrder com valores padrao deve ser funcional."""
    order = CommanderOrder(action="wait")
    assert order.action == "wait"
    assert order.symbol == ""
    assert order.direction == ""
    assert order.risk_pct == 0.0
    assert order.confidence == 0.0


def test_commander_order_to_dict():
    """to_dict() deve incluir todos os campos esperados."""
    order = CommanderOrder(
        action="trade", symbol="XAUUSDm", direction="BUY",
        risk_pct=5.0, size_frac=0.8, stop_atr_mult=1.5,
        rr_target=2.0, confidence=0.75,
        reasoning="Test trade", primary_driver="momentum",
        selected_strategy="ts_momentum", regime="risk_on",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    d = order.to_dict()
    assert d["action"] == "trade"
    assert d["symbol"] == "XAUUSDm"
    assert d["direction"] == "BUY"
    assert d["risk_pct"] == 5.0
    assert d["confidence"] == 0.75
    assert "reasoning" in d
    assert d["primary_driver"] == "momentum"


# ═══════════════════════════ COMMANDER DECISION CONTEXT ═══════════════════════════

def test_context_defaults():
    """CommanderDecisionContext com valores padrao."""
    ctx = CommanderDecisionContext()
    assert ctx.oracle is None
    assert ctx.meta is None
    assert ctx.evolution is None
    assert ctx.signals == {}
    assert ctx.balance == 0.0
    assert ctx.open_positions == 0
    assert ctx.open_symbols == set()


# ═══════════════════════════ SAFETY RULES ═══════════════════════════

def _make_crisis_oracle() -> OracleSnapshot:
    """Cria um OracleSnapshot simulando crise."""
    oracle = AutonomousOracle()
    intel = {
        "risk_sentiment": {"vix": 35.0, "vix_pct_change": 15.0,
                           "dollar_index": 108.0, "dollar_index_pct_change": 1.0},
        "fed_rates": {"fed_funds_rate_diario": {"valor": 5.5},
                      "treasury_10y": {"valor": 5.0}},
    }
    return oracle.analyze(intel, {})


def _make_normal_oracle() -> OracleSnapshot:
    """Cria um OracleSnapshot simulando mercado normal."""
    oracle = AutonomousOracle()
    intel = {
        "risk_sentiment": {"vix": 15.0, "vix_pct_change": -1.0,
                           "dollar_index": 100.0, "dollar_index_pct_change": 0.1},
    }
    return oracle.analyze(intel, {})


def test_safety_crisis_waits():
    """Crisis + sem posicoes → action = wait."""
    engine = CommanderDecisionEngine()
    oracle = _make_crisis_oracle()
    
    ctx = CommanderDecisionContext(
        oracle=oracle, meta=MetaState(),
        signals={"XAUUSDm": ("BUY", 0.05)},
        balance=500.0, open_positions=0, open_symbols=set(),
    )
    order = engine.decide(ctx)
    assert order.action == "wait", f"Esperado wait em crisis, got {order.action}"
    assert order.confidence >= 0.8


def test_safety_crisis_close_all():
    """Crisis + posicoes abertas → action = close_all."""
    engine = CommanderDecisionEngine()
    oracle = _make_crisis_oracle()
    
    ctx = CommanderDecisionContext(
        oracle=oracle, meta=MetaState(),
        signals={"XAUUSDm": ("BUY", 0.05)},
        balance=500.0, open_positions=1, open_symbols={"XAUUSDm"},
    )
    order = engine.decide(ctx)
    assert order.action == "close_all", f"Esperado close_all, got {order.action}"
    assert order.risk_multiplier == 0.0  # risco zero em crisis


def test_safety_risk_off_reduces():
    """Risk_off com score baixo → action = wait (reduce)."""
    engine = CommanderDecisionEngine()
    # Cria oracle com risk_off forçado
    oracle = AutonomousOracle()
    intel = {
        "risk_sentiment": {"vix": 28.0, "vix_pct_change": 5.0,
                           "dollar_index": 102.0, "dollar_index_pct_change": 0.5},
        "fed_rates": {"fed_funds_rate_diario": {"valor": 5.0},
                      "treasury_10y": {"valor": 4.5}},
    }
    oracle_snap = oracle.analyze(intel, {})
    
    # Se oracle nao detectou risk_off (dados podem variar), forca o regime manualmente
    # Modifica o snapshot para testar a regra
    oracle_snap.thesis = replace(oracle_snap.thesis, regime="risk_off", risk_score=30)
    
    ctx = CommanderDecisionContext(
        oracle=oracle_snap, meta=MetaState(),
        signals={"XAUUSDm": ("BUY", 0.05)},
        balance=500.0, open_positions=0, open_symbols=set(),
    )
    order = engine.decide(ctx)
    assert order.action in ("wait", "reduce_risk"), (
        f"Esperado wait/reduce, got {order.action}"
    )


def test_safety_max_positions():
    """Max positions atingido → action = wait."""
    engine = CommanderDecisionEngine()
    oracle = _make_normal_oracle()
    
    ctx = CommanderDecisionContext(
        oracle=oracle, meta=MetaState(),
        signals={"XAUUSDm": ("BUY", 0.05)},
        balance=500.0, open_positions=1, open_symbols={"XAUUSDm"},
    )
    order = engine.decide(ctx)
    assert order.action == "wait", f"Esperado wait (max pos), got {order.action}"
    assert "max" in order.reasoning.lower() or "Max" in order.reasoning


def test_safety_no_signal():
    """Sem sinal disponivel → action = wait."""
    engine = CommanderDecisionEngine()
    oracle = _make_normal_oracle()
    
    ctx = CommanderDecisionContext(
        oracle=oracle, meta=MetaState(),
        signals={},  # sem sinal
        balance=500.0, open_positions=0, open_symbols=set(),
    )
    order = engine.decide(ctx)
    assert order.action == "wait", f"Esperado wait (sem sinal), got {order.action}"
    assert "No clear signal" in order.reasoning


# ═══════════════════════════ FALLBACK DECISION ═══════════════════════════

def test_fallback_with_signal():
    """Fallback deve usar o primeiro sinal disponivel."""
    engine = CommanderDecisionEngine()
    oracle = _make_normal_oracle()
    now = datetime.now(timezone.utc)
    
    ctx = CommanderDecisionContext(
        oracle=oracle, meta=MetaState(),
        signals={"XAUUSDm": ("BUY", 0.05)},
        balance=500.0, open_positions=0, open_symbols=set(),
    )
    order = engine._fallback_decision(ctx, now)
    assert order.action == "trade", f"Esperado trade, got {order.action}"
    assert order.direction == "BUY"
    assert order.symbol == "XAUUSDm"


def test_fallback_without_signal():
    """Fallback sem sinal deve retornar wait."""
    engine = CommanderDecisionEngine()
    oracle = _make_normal_oracle()
    now = datetime.now(timezone.utc)
    
    ctx = CommanderDecisionContext(
        oracle=oracle, meta=MetaState(),
        signals={},
        balance=500.0, open_positions=0, open_symbols=set(),
    )
    order = engine._fallback_decision(ctx, now)
    assert order.action == "wait"


def test_fallback_ignore_open_symbol():
    """Fallback nao deve sugerir trade em simbolo ja aberto."""
    engine = CommanderDecisionEngine()
    oracle = _make_normal_oracle()
    now = datetime.now(timezone.utc)
    
    ctx = CommanderDecisionContext(
        oracle=oracle, meta=MetaState(),
        signals={"XAUUSDm": ("BUY", 0.05)},
        balance=500.0, open_positions=1, open_symbols={"XAUUSDm"},
    )
    order = engine._fallback_decision(ctx, now)
    assert order.action == "wait", (
        f"Nao deve sugerir trade em simbolo aberto, got {order.action}"
    )


# ═══════════════════════════ AUTONOMOUS COMMANDER ═══════════════════════════

def test_commander_init():
    """Commander inicializa sem erros."""
    commander = AutonomousCommander()
    assert commander.cycle_count == 0
    assert len(commander.decision_history) == 0


def test_commander_get_status_fresh():
    """get_status() sem ciclos deve refletir estado inicial."""
    commander = AutonomousCommander()
    status = commander.get_status()
    assert status["cycle_count"] == 0
    assert status["last_oracle_update"] == ""
    assert status["decisions_made"] == 0
    assert status["last_decision"] is None
    assert len(status["evolution"]["parameters"]) == 10


def test_commander_learn_no_crash():
    """learn() com dados minimos nao crasha."""
    commander = AutonomousCommander()
    trade_result = {
        "symbol": "XAUUSDm", "direction": "BUY",
        "pnl_usd": 50.0, "rr_realized": 2.0,
        "regime_at_entry": "risk_on",
        "exit_reason": "TP", "strategy": "ts_momentum",
    }
    try:
        commander.learn(trade_result)
    except Exception as e:
        assert False, f"learn() crashou: {type(e).__name__}: {e}"
    
    # Apos learn, o regime deve ter sido registrado
    assert "risk_on" in commander.oracle.regime_memory.performance_by_regime


def test_commander_cycle_round_trip():
    """cycle() com dados basicos deve retornar CommanderOrder."""
    commander = AutonomousCommander()
    intel = {
        "risk_sentiment": {"vix": 15.0, "vix_pct_change": -1.0,
                           "dollar_index": 100.0, "dollar_index_pct_change": 0.1},
        "fed_rates": {"fed_funds_rate_diario": {"valor": 4.5},
                      "treasury_10y": {"valor": 4.0}},
    }
    meta = MetaState()
    
    order = commander.cycle(
        intel=intel, meta=meta,
        signals={}, balance=500.0,
        open_positions=0, open_symbols=set(),
    )
    assert isinstance(order, CommanderOrder)
    assert order.action in ("trade", "wait", "close_all", "reduce_risk")
    
    # Apos cycle, status deve refletir
    status = commander.get_status()
    assert status["cycle_count"] >= 1
    assert status["last_oracle_update"] != ""


if __name__ == "__main__":
    tests = [
        ("test_commander_order_defaults", test_commander_order_defaults),
        ("test_commander_order_to_dict", test_commander_order_to_dict),
        ("test_context_defaults", test_context_defaults),
        ("test_safety_crisis_waits", test_safety_crisis_waits),
        ("test_safety_crisis_close_all", test_safety_crisis_close_all),
        ("test_safety_risk_off_reduces", test_safety_risk_off_reduces),
        ("test_safety_max_positions", test_safety_max_positions),
        ("test_safety_no_signal", test_safety_no_signal),
        ("test_fallback_with_signal", test_fallback_with_signal),
        ("test_fallback_without_signal", test_fallback_without_signal),
        ("test_fallback_ignore_open_symbol", test_fallback_ignore_open_symbol),
        ("test_commander_init", test_commander_init),
        ("test_commander_get_status_fresh", test_commander_get_status_fresh),
        ("test_commander_learn_no_crash", test_commander_learn_no_crash),
        ("test_commander_cycle_round_trip", test_commander_cycle_round_trip),
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
