# WFO TEST: VIX_MAX_LEVEL Filter Comparison

**Gerado em:** 2026-07-12 16:52 UTC

**Janelas:** 8 | **Periodo:** 2021-10-27 -> 2026-07-10

## Resultados

| Cenario | VIX_MAX | OOS Medio | >0.6 | >0.8 | Janela Sharpes |
|---|---|---|---|---|---|
| Baseline (sem filtro) | 0 | 0.41 | 3/8 | 3/8 | 0.16, 1.53, -0.18, -1.57, 0.06, 1.70, 1.90, -0.27 |
| VIX_MAX_LEVEL=25 | 25 | 0.43 | 3/8 | 3/8 | 0.05, 1.53, -0.18, -1.57, 0.06, 1.91, 1.90, -0.26 |
| VIX_MAX_LEVEL=20 | 20 | 0.79 | 5/8 | 5/8 | -1.32, 2.30, 1.40, -1.57, -0.04, 1.76, 1.90, 1.88 |

## Conclusao

- **VIX_MAX_LEVEL=25**: ⚖️  Empate tecnico (OOS 0.43 vs 0.41, delta +0.01)
- **VIX_MAX_LEVEL=20**: ✅ Melhorou (OOS 0.79 vs 0.41, delta +0.37)

**Melhor cenario:** VIX_MAX_LEVEL=20 (OOS medio 0.79)
✅ Filtro VIX pode ser uma melhoria real.