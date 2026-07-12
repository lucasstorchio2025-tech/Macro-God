"""test_meta_learner.py — Garantias do meta-learner (parse + clamp + fallback).

Valida que:
  1. parse_llm_response aceita JSON válido e rejeita inválido
  2. risk_multiplier é clamped em [0.1, 2.0]
  3. confidence é clamped em [0.0, 1.0]
  4. reasoning é truncado em 200 chars
  5. Fallback pra None quando resposta é vazia/malformada
  6. Fallback pra 1.0 quando valor está fora dos limites
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.meta_learner import parse_llm_response


def test_parse_valid_json():
    """Resposta JSON válida deve ser parseada corretamente."""
    raw = '{"risk_multiplier": 0.7, "confidence": 0.8, "reasoning": "teste valido"}'
    result = parse_llm_response(raw)
    assert result is not None, "Deveria retornar dict"
    assert result["risk_multiplier"] == 0.7
    assert result["confidence"] == 0.8
    assert result["reasoning"] == "teste valido"


def test_parse_clamp_risk_multiplier_high():
    """risk_multiplier > 2.0 deve ser clamped em 2.0."""
    raw = '{"risk_multiplier": 5.0, "confidence": 0.9, "reasoning": "muito alto"}'
    result = parse_llm_response(raw)
    assert result is not None
    assert result["risk_multiplier"] == 2.0, f"Esperado 2.0, got {result['risk_multiplier']}"


def test_parse_clamp_risk_multiplier_low():
    """risk_multiplier < 0.1 deve ser clamped em 0.1."""
    raw = '{"risk_multiplier": 0.01, "confidence": 0.5, "reasoning": "muito baixo"}'
    result = parse_llm_response(raw)
    assert result is not None
    assert result["risk_multiplier"] == 0.1, f"Esperado 0.1, got {result['risk_multiplier']}"


def test_parse_clamp_confidence():
    """confidence deve ser clamped em [0.0, 1.0]."""
    raw = '{"risk_multiplier": 1.2, "confidence": 1.5, "reasoning": "confianca alta demais"}'
    result = parse_llm_response(raw)
    assert result is not None
    assert result["confidence"] == 1.0, f"Esperado 1.0, got {result['confidence']}"


def test_parse_reasoning_truncated():
    """reasoning > 200 chars deve ser truncado."""
    long_reason = "x" * 300
    raw = f'{{"risk_multiplier": 0.5, "confidence": 0.3, "reasoning": "{long_reason}"}}'
    result = parse_llm_response(raw)
    assert result is not None
    assert len(result["reasoning"]) <= 200, f"Esperado <=200, got {len(result['reasoning'])}"


def test_parse_invalid_json():
    """JSON inválido deve retornar None."""
    result = parse_llm_response("isto nao e json")
    assert result is None, "Deveria retornar None para JSON invalido"


def test_parse_empty():
    """String vazia deve retornar None."""
    result = parse_llm_response("")
    assert result is None, "Deveria retornar None para string vazia"


def test_parse_none():
    """None deve retornar None."""
    result = parse_llm_response(None)
    assert result is None, "Deveria retornar None para input None"


def test_parse_missing_keys():
    """JSON sem risk_multiplier deve usar fallback 1.0."""
    raw = '{"confidence": 0.5, "reasoning": "sem risk_mult"}'
    result = parse_llm_response(raw)
    assert result is not None
    assert result["risk_multiplier"] == 1.0, f"Esperado 1.0 (fallback), got {result['risk_multiplier']}"


def test_parse_junk_middleware():
    """JSON com lixo ao redor (markdown) deve ser extraído."""
    raw = '```json\n{"risk_multiplier": 1.3, "confidence": 0.7, "reasoning": "com markdown"}\n```'
    # O call_ollama já limpa markdown, mas parse_llm_response tenta regex como fallback
    result = parse_llm_response(raw)
    # Se o strip não funcionar, o regex pode pegar
    assert result is not None, "Deveria extrair JSON mesmo com markdown"


def test_parse_non_dict_response():
    """Array JSON (não dict) deve retornar None."""
    raw = '["risk_multiplier", 1.0]'
    result = parse_llm_response(raw)
    assert result is None, "Array JSON nao e um dict valido"


if __name__ == "__main__":
    # Roda manualmente
    tests = [
        ("test_parse_valid_json", test_parse_valid_json),
        ("test_parse_clamp_risk_multiplier_high", test_parse_clamp_risk_multiplier_high),
        ("test_parse_clamp_risk_multiplier_low", test_parse_clamp_risk_multiplier_low),
        ("test_parse_clamp_confidence", test_parse_clamp_confidence),
        ("test_parse_reasoning_truncated", test_parse_reasoning_truncated),
        ("test_parse_invalid_json", test_parse_invalid_json),
        ("test_parse_empty", test_parse_empty),
        ("test_parse_none", test_parse_none),
        ("test_parse_missing_keys", test_parse_missing_keys),
        ("test_parse_junk_middleware", test_parse_junk_middleware),
        ("test_parse_non_dict_response", test_parse_non_dict_response),
    ]
    passed = 0
    failed = 0
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
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
