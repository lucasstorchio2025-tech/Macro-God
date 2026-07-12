"""Testes automatizados do engine.

Rodar: python -m pytest tests/  (ou: python tests/run_tests.py)

Cada teste valida uma garantia fundamental do sistema:
  - test_no_lookahead: nenhuma decisão usa dado do futuro (o erro nº1 de backtest)
  - test_sizing: vol-targeting + correlação funcionam matematicicamente
  - test_regime: detector classifica corretamente os 4 estados
"""
