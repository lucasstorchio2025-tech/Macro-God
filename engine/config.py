"""config.py — fonte única da verdade para TODOS os parâmetros do engine.

Filosofia: nenhum número mágico espalhado pelo código. Se um parâmetro existe,
ele vive aqui, com nome claro e comentário. Mudar comportamento = mudar aqui.

Isto substitui os constantes espalhados pelo executor.py antigo (RISK_PER_TRADE_PCT,
MIN_RR, etc.) e centraliza os novos (vol alvo, janelas de regime, limites de
correlação) que a v2 introduz.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


# ───────────────────────── PATHS ─────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR   = PROJECT_ROOT / "engine"
CACHE_DIR    = PROJECT_ROOT / "engine" / "cache"   # histórico em parquet/CSV
REPORTS_DIR  = PROJECT_ROOT / "reports"
TESTS_DIR    = PROJECT_ROOT / "tests"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


# ───────────────────────── UNIVERSO ─────────────────────────
# Os 4 pares da conta Exness Trial11 (sufixo "m" = micro).
# USD_BETA: quanto esse par se move (aprox.) quando USD aprecia 1%.
#   EURUSD/GBPUSD sobem quando USD cai  → beta USD negativo.
#   USDJPY/XAUUSD sobem quando USD sobe  → beta USD positivo.
#   (Usado pelo sizing.py pra somar exposição USD agregada — o erro do bot antigo
#    era tratar EURUSD + GBPUSD como 2 apostas independentes; são a mesma aposta USD.)
SYMBOLS: list[str] = ["XAUUSDm"]   # Apenas XAUUSD — TS-Momentum não funciona em forex (comprovado)

USD_BETA: dict[str, float] = {
    "XAUUSDm": -1.0,   # USD sobe → ouro desce (em USD)
}


# ───────────────────────── DADOS ─────────────────────────
TIMEFRAME        = "H4"          # mesma TF do plano de swing original
BARS_LOOKBACK    = 20000         # puxa até esse nº de barras do MT5 (cobre >12y em H4)
START_COMMON     = "2021-10-27"  # 1ª data em que TODOS os 4 pares têm dado H4
END_DEFAULT      = "2026-06-30"  # fim do backtest (snapshot do projeto)


# ───────────────────────── RISCO ─────────────────────────
ACCOUNT_START_USD   = 500.0      # saldo inicial do backtest (mesmo da demo)
RISK_PER_TRADE_PCT  = 5.0        # teto padrão de risco por trade (% do saldo)
MAX_OPEN_POSITIONS  = 1          # XAUUSD — máximo 1 posição (apenas 1 símbolo ativo no momento).
# NOTA: Antes era 3 quando o universo tinha 4 pares (EURUSDm, GBPUSDm, USDJPYm, XAUUSDm).
# Com SYMBOLS=["XAUUSDm"] e anti-empilhamento ativo, 3 posições simultâneas é impossível.
# Mantido com valor 1 para clareza — se expandir para múltiplos símbolos no futuro, aumentar.
# XAUUSDm: lote mínimo 0.01 = ~10.6% risco com $566 de saldo (varia com ATR).
RISK_OVERRIDE_PCT: dict[str, float] = {"XAUUSDm": 12.0}
MIN_REWARD_RISK     = 2.0        # RR mínimo
DAILY_DD_PCT        = 12.0       # pausa o dia (aumentado de 8% para liberar XAUUSDm)
WEEKLY_DD_PCT       = 15.0       # pausa a semana
TOTAL_RISK_CAP_PCT  = 12.0       # exposição aberta somada <= 12%. (aumentado junto com DAILY_DD_PCT)
# NOTA: O usuário optou por aumentar os limites de risco para que XAUUSDm
# possa operar com o saldo atual (~$566). O lote mínimo 0.01 de XAUUSDm
# consome ~10.6% do saldo — acima do antigo cap de 7.5% / 8%.
#
# NOVA CONTA:
#   RISK_OVERRIDE_PCT["XAUUSDm"] = 12%  → override individual
#   DAILY_DD_PCT                 = 12%  → hard_cap efetivo = min(12%, 12%) = 12%
#   risco_real 0.01 lot XAUUSDm  ≈ 10.6%  → 10.6% < 12% ✅ trade passa
#   WEEKLY_DD_PCT                = 15%  → proteção semanal ainda ativa
#
# Se o trade perder (~$60), saldo cai pra ~$506:
#   risco 0.01 lot em $506 ≈ 11.9% — ainda dentro do cap de 12% (por pouco)
# Se o trade ganhar (+$156), saldo sobe pra ~$722:
#   risco 0.01 lot em $722 ≈ 8.3% — folga confortável
#
# Isto foi uma DECISÃO ATIVA do usuário (não é o padrão recomendado).
# Assim que o saldo atingir ~$800+, pode-se reduzir de volta pra 8%.

# Custos de transação honestos. Sem isto, qualquer backtest mente.
# Spread em PONTOS (mesma unidade de symbol_info.spread). Slippage conservador.
SPREAD_POINTS: dict[str, int] = {
    "XAUUSDm": 240,   # ouro: spread ~24 pts em micro conta
}
SLIPPAGE_POINTS: dict[str, int] = {
    "XAUUSDm": 50,    # ouro é mais grosso
}


# ───────────────────────── ESTOP / ATR ─────────────────────────
ATR_PERIOD        = 14           # mesmo do market_intelligence.py original
ATR_STOP_MULT     = 1.5          # fallback se o regime não estiver no dict ATR_STOP_MULT_BY_REGIME
RR_TARGET_MULT    = 2.0          # alvo = stop × 2  (RR 2:1)


# ───────────────────────── GESTÃO INTRA-TRADE (PROTEÇÃO DE LUCRO) ─────────────────────────
# Mecanismos institucionais que cortam perda e protegem lucro, calibrados para
# PRESERVAR o edge do TS-Momentum original (Sharpe 1.12, Payoff 2.02) enquanto
# reduzem drawdown e variancia:
#
#  1. PARTIAL TAKE-PROFIT (1.0×RR, 30%): Realiza 30% do lucro em 1×RR.
#     70% da posição continua correndo até o TP cheio (2×RR). Isto preserva
#     o grosso do upside original enquanto ainda melhora a consistência.
#  2. HOLDING TIME MAX (84 barras = ~14 dias): Fecha posição que não atingiu
#     nem SL nem TP. Evita posições penduradas eternamente em lateral.
#  3. MAX LOSS STREAK: Pausa automática após perdas consecutivas (anti-tilt).
#
# Breakeven e trailing estão DESLIGADOS porque:
#   - Breakeven cria stops muito apertados (entry) que matam o edge em pullbacks
#   - Trailing destrói o payoff (2.02 → 1.0) ao fechar trades prematuramente
#   - O partial TP leve já dá consistência sem sacrificar os grandes winners
HOLDING_TIME_MAX_BARS = 84         # ~14 dias (84 barras H4). 0 = desativado.
TRAILING_STOP_ACTIVATE_RR = 0.0    # 0 = desativado (destrói payoff em trend-following).
TRAILING_STOP_LOCK_RR      = 0.5   # (só usado se TRAILING_STOP_ACTIVATE_RR > 0)
BREAKEVEN_ACTIVATE_RR      = 0.0   # 0 = desativado (cria stops apertados que quebram edge).
PARTIAL_TP_RR              = 1.0   # Realiza 30% da posição em 1×RR.
PARTIAL_TP_FRACTION        = 0.3   # Fração a realizar no partial TP (0.3 = 30%).
REGIME_EXIT_ON_RISKOFF     = False  # NÃO fecha posições no risk_off (causa whipsaw).
                                     # Só fecha em CRISIS (95th+ percentil ou VIX>35).

# ───────────────────────── PERDAS CONSECUTIVAS (ANTI-TILT) ─────────────────────────
# Pausa automática após sequência de perdas para evitar revenge trading.
# Com win rate ~41%, streak de 6 perdas acontece ~1% das vezes.
MAX_LOSS_STREAK         = 6     # Pausa após 6 perdas consecutivas.
LOSS_STREAK_COOLDOWN_BARS = 42  # Castigo de ~7 dias (42 barras H4).


# ───────────────────────── VOL-TARGETING ─────────────────────────
# Princípio institucional (Target Volatility funds): dimensiona posição pra que
# cada ativo contribua com vol-alvo ~constante. Ativo nervoso → tamanho menor.
# Vol-alvo em termos de "fração da unidade-base" por unidade de vol realizada.
TARGET_VOL_PCT_ANNUAL = 12.0     # vol-alvo anualizado do portfólio (~12%)
VOL_LOOKBACK_BARS     = 63       # vol realizada: ~3 meses em H4 (63 × 4h ≈ 10.5 dias úteis)
VOL_TARGET_CAP        = 0.6      # cap conservador do vol-scalar. Sweep mostrou que 0.6 dá o
                                  # melhor Sharpe (0.62) com DD aceitável (-38%). 1.2 causava DD de -54%.


# ───────────────────────── COOLDOWN ─────────────────────────
# Após fechar uma posição num símbolo, espera N barras antes de reentrar.
# Sem isso, o ts-momentum reabre toda barra após SL/TP → 5000+ trades → overtrading.
COOLDOWN_BARS = 12              # ~2 dias em H4 (12 × 4h = 48h). Evita reentrada emocional.


# ───────────────────────── FILTRO POR SESSÃO ─────────────────────────
# Filtra trades por sessão de mercado. Validação walk-forward confirmou
# que operar APENAS em Tokyo maximiza Sharpe e reduz drawdown:
#   - Tokyo:   65.4% WR | +$4.06/trade (MELHOR — Sharpe OOS 1.30)
#   - New York: 58.5% WR | +$1.67/trade (inferior)
#   - London:  55.9% WR | +$0.65/trade (inferior)
#   - Sydney:  removida (pior performance)
#
# Opções disponíveis: "London", "NewYork", "Tokyo", "Sydney"
# Lista vazia = todas as sessões permitidas
SESSION_FILTER_ALLOW: list[str] = ["Tokyo"]  # Apenas Tokyo — WFO confirmou Sharpe OOS 1.30


# ───────────────────────── EVENTOS MACRO ─────────────────────────
# Redução de exposição antes de eventos econômicos de alto impacto.
# Evita levar stop em volatilidade de FOMC/NFP/CPI.
#
# Lógica:
#   - ANTES do evento (EVENT_REDUCTION_HOURS_BEFORE): reduz o tamanho da posição
#     em EVENT_REDUCTION_SCALE. Ex: 0.5 = reduz 50%
#   - DEPOIS do evento (EVENT_VOLATILITY_HOURS_AFTER): alarga o stop em
#     EVENT_VOLATILITY_SL_MULT para evitar ser caçado por spikes de volatilidade
#
# Eventos monitorados (importância >= min_importance):
#   FOMC (5), NFP (4), CPI (4), FOMC_MINUTES (3), PPI (2), GDP (2)
EVENT_REDUCTION_ENABLED = True         # Liga/desliga a redução pré-evento
EVENT_REDUCTION_HOURS_BEFORE = 4        # Reduz posição 4h ANTES do evento
EVENT_REDUCTION_SCALE = 0.5             # Escala de redução (0.5 = metade do tamanho)
EVENT_VOLATILITY_HOURS_AFTER = 4        # Alarga stop 4h DEPOIS do evento
EVENT_VOLATILITY_SL_MULT = 2.0          # Multiplicador do stop após evento (2x = dobro)
EVENT_MIN_IMPORTANCE = 3               # Importância mínima: 3 = FOMC_MINUTES+


# ───────────────────────── REGIME ─────────────────────────
# Estados: risk_on / normal / risk_off / crisis.
# Thresholds vêm de PERCENTIS ROLANTES do próprio VIX (não fixos) → adapta-se à época.
VIX_PERCENTILE_LOOKBACK_DAYS = 252   # 1 ano de pregão
VIX_RISKOFF_PERCENTILE      = 80     # VIX no percentil 80+ do último ano = risk_off
VIX_CRISIS_PERCENTILE       = 95     # VIX no percentil 95+ = crisis
VIX_CRISIS_ABS              = 35.0   # fallback absoluto: VIX > 35 = crisis (ex: COVID)
CORREL_CRISIS_THRESHOLD     = 0.85   # se pares correlacionam > 0.85, diversificaçãosome → crisis

# Escala de exposição por regime (fração do tamanho que o sizing permitiria).
# crisis = 0.0: NÃO opera em pânico. Dados mostram que o sistema PERDE em crisis
# mesmo com escala reduzida (-$0.32/trade). Melhor ficar flat.
EXPOSURE_SCALE: dict[str, float] = {
    "risk_on":  1.0,
    "normal":   0.75,
    "risk_off": 0.30,   # reduzido de 0.40 — risk_off mal empata ($0.17/trade)
    "crisis":   0.0,    # ZERO — crisis PERDE (-$0.32/trade). Fica flat.
}


# ───────────────────────── RISCO POR REGIME ─────────────────────────
# Percentual de risco por trade, variável conforme o regime de mercado.
# Lógica:
#   - risk_on: risco MAIOR (8%) — mercado favorável, sistema ganha $2.54/trade com 64% WR
#   - normal:  risco padrão (5%) — já validado
#   - risk_off: risco MENOR (3%) — mercado neutro/negativo, sistema só empata
#   - crisis:  risco ZERO (0%) — sistema PERDE em pânico
RISK_PCT_BY_REGIME: dict[str, float] = {
    "risk_on":  8.0,    # +60% vs padrão — aproveita regime favorável
    "normal":   5.0,    # padrão atual
    "risk_off": 3.0,    # -40% vs padrão — reduz exposição em regime fraco
    "crisis":   0.0,    # não opera em pânico
}


# ───────────────────────── FILTRO DE TENDÊNCIA D1 ─────────────────────────
# Filtra entradas H4 para só operar na direção da tendência diária.
# Exemplo: se D1 momentum > 0 (tendência de alta), só permite LONG.
# Isto evita comprar quedas e vender topos — pega a tendência principal.
D1_MOMENTUM_LOOKBACK_BARS = 20    # Dias lookback para momentum diário
D1_FILTER_ENABLED = True           # Liga/desliga o filtro de tendência D1


# ───────────────────────── ATR MULTIPLICADOR POR REGIME ─────────────────────────
# Adapta a distância do stop de acordo com o regime de mercado.
# Lógica:
#   - risk_on: stop MAIS LARGO (2.0×ATR) para deixar os grandes winners correrem
#   - normal:  stop normal (1.5×ATR) — padrão
#   - risk_off: stop MAIS APERTADO (1.0×ATR) para sair rápido de posições ruins
#   - crisis:  não aplicável (exposição = 0)
#
# Isto é baseado em dados reais do backtest: 99% do lucro vem de risk_on + normal.
# Em risk_off o sistema mal empata (+$0.17/trade) — stop apertado reduz perdas.
# Em crisis o sistema PERDE (-$0.32/trade) — melhor ficar de fora.
ATR_STOP_MULT_BY_REGIME: dict[str, float] = {
    "risk_on":  2.0,   # +33% mais largo que o normal — deixa winners correrem
    "normal":   1.5,   # padrão atual
    "risk_off": 1.0,   # -33% mais apertado — sai rápido de posição ruim
    "crisis":   1.5,   # não usado (exposição = 0), mas definido pra segurança
}


# ───────────────────────── CORRELAÇÃO OURO × AÇÕES (RISK_ON GENUÍNO) ─────────────────────────
# A correlação rolante entre retornos diários de XAUUSD (ouro) e SPY (S&P500) é o
# VERDADEIRO medidor de risk_on/risk_off no sentido macroeconômico:
#
#   CORRELAÇÃO NEGATIVA (ex: -0.3): ouro cai quando ações sobem
#     → RISK_ON GENUÍNO (capital saindo de safe haven para risco)
#     Faz sentido o bot comprar gold? NÃO — gold está caindo, bot deve vender.
#
#   CORRELAÇÃO POSITIVA (ex: +0.4): ouro e ações sobem JUNTOS
#     → NÃO é risk_on. Driver comum (USD fraco, inflação) está movendo ambos.
#     O bot pode comprar gold aqui sem contradição.
#
#   CORRELAÇÃO POSITIVA FORTE (ex: +0.7) + ambos caindo:
#     → PÂNICO GENERALIZADO (tudo cai junto)
#
# Parâmetros:
GE_CORR_WINDOW_DAYS         = 60     # Janela para correlação rolante (dias úteis ≈ 3 meses)
GE_CORR_RISKON_THRESHOLD    = -0.15  # Correlação <= -0.15 = risk_on genuíno
GE_CORR_FAKE_RISKON_THRESHOLD = 0.25 # Correlação >= +0.25 = NÃO é risk_on (falso positivo)
GE_CORR_PANIC_THRESHOLD     = 0.6    # Correlação >= +0.6 = tudo andando junto (potencial pânico)


# ───────────────────────── LIQUIDEZ / DOLLAR SAFE-HAVEN ─────────────────────────
# Novo fator de regime: detecta quando o DÓLAR está vencendo o ouro como safe haven.
# Clássico cenário de "flight-to-liquidity": DXY sobe + VIX sobe = pânico com dólar
# como refúgio primário. O ouro PERDE proteção nesse cenário.
#
# Lógica: DXY subindo forte (> threshold) + VIX subindo (> threshold) = liquidez estressada.
# O regime é escalado: normal → risk_off, risk_off → crisis.
#
# AVISO EM WALK-FORWARD.md: LiquidityStressSignal NÃO agregou valor OOS (0/8 janelas).
# A flag abaixo permite desligar sem remover o código, caso nova validação confirme.
DXY_LIQUIDITY_STRESS_ENABLED       = False  # FALSE = desligado (não agregou valor OOS, ver WALK_FORWARD.md)
DXY_LIQUIDITY_STRESS_UP_PCT       = 0.5    # DXY sobe >= 0.5% = candidato a stress de liquidez (otimizado via sweep)
VIX_LIQUIDITY_STRESS_UP_PCT        = 10.0   # VIX sobe >= 10% = medo crescendo (confirma stress, otimizado via sweep)
DXY_LIQUIDITY_STRESS_LOOKBACK_BARS = 4      # janela H4 pra calcular % change


# ───────────────────────── MOMENTUM (TS-mom) ─────────────────────────
# Moskowitz/Ooi/Pedersen 2012: olha retorno passado N períodos, vai LONG se > 0,
# SHORT se < 0. Janela "264 barras H4" ≈ 1 ano em base 4h (~6 barras/dia × 44 sem).
MOMENTUM_LOOKBACK_BARS = 264
MOMENTUM_SKIP_BARS     = 24       # pula último dia pra não captar rebote de curto
MOMENTUM_MIN_ABS_R     = 0.01     # ignora sinais pífios (|retorno| < 1%)


# ───────────────────────── COT CONTRARIAN ─────────────────────────
# Uso institucional real: posicionamento saturado é sinal CONTRARIAN.
# Só age em EXTREMOS (z-score histórico elevado). Corrige o uso do bot antigo
# (que tratava COT como momentum — comprar o topo, vender o fundo).
COT_ZSCORE_LOOKBACK_WEEKS = 156    # 3 anos de histórico de COT pra normalizar
COT_ZSCORE_ENTRY          = 2.0    # só opera se |z| >= 2 (extremo estatístico)


# ───────────────────────── SIZING / CORRELAÇÃO ─────────────────────────
CORREL_LOOKBACK_BARS = 63         # janela pra matriz de correlação rolante
CORREL_DUP_LIMIT     = 0.60       # se 2 pares > 0.60, são "a mesma aposta"
USD_EXPOSURE_CAP     = 1.5        # exposição USD agregada (em "unidades de risco") <= 1.5


# ───────────────────────── WALK-FORWARD ─────────────────────────
WF_TRAIN_BARS  = 1440             # in-sample (~6 meses em H4: 6×6×40)
WF_TEST_BARS   = 720              # out-of-sample (~3 meses em H4)
WF_STEP_BARS   = 720              # rolamento


# ───────────────────────── CONTA DEMO ─────────────────────────
EXNESS_MAGIC    = 999888777
COMMENT_TAG     = "Wealth_Engine_bot"


@dataclass
class RunConfig:
    """Snapshot imutável de uma configuração de backtest. Facilita comparar runs."""
    symbols: list[str] = field(default_factory=lambda: list(SYMBOLS))
    start: str = START_COMMON
    end: str = END_DEFAULT
    timeframe: str = TIMEFRAME
    account_start: float = ACCOUNT_START_USD
    strategy: str = "ts_momentum"     # "ts_momentum" | "cot_contrarian" | "legacy_cot"
    risk_per_trade_pct: float = RISK_PER_TRADE_PCT
    use_costs: bool = True
    use_regime: bool = True
    use_voltarget: bool = True
    label: str = ""


__all__ = [
    "PROJECT_ROOT", "ENGINE_DIR", "CACHE_DIR", "REPORTS_DIR", "TESTS_DIR",
    "SYMBOLS", "USD_BETA", "TIMEFRAME", "BARS_LOOKBACK", "START_COMMON", "END_DEFAULT",
    "ACCOUNT_START_USD", "RISK_PER_TRADE_PCT", "MAX_OPEN_POSITIONS",
    "RISK_OVERRIDE_PCT", "MIN_REWARD_RISK", "DAILY_DD_PCT", "WEEKLY_DD_PCT",
    "TOTAL_RISK_CAP_PCT", "SPREAD_POINTS", "SLIPPAGE_POINTS",
    "RISK_PCT_BY_REGIME",
    "D1_MOMENTUM_LOOKBACK_BARS", "D1_FILTER_ENABLED",
    "ATR_PERIOD", "ATR_STOP_MULT", "RR_TARGET_MULT",
    "ATR_STOP_MULT_BY_REGIME",
    "HOLDING_TIME_MAX_BARS", "TRAILING_STOP_ACTIVATE_RR", "TRAILING_STOP_LOCK_RR",
    "BREAKEVEN_ACTIVATE_RR", "PARTIAL_TP_RR", "PARTIAL_TP_FRACTION",
    "REGIME_EXIT_ON_RISKOFF", "MAX_LOSS_STREAK", "LOSS_STREAK_COOLDOWN_BARS",
    "TARGET_VOL_PCT_ANNUAL", "VOL_LOOKBACK_BARS",
    "VIX_PERCENTILE_LOOKBACK_DAYS", "VIX_RISKOFF_PERCENTILE",
    "VIX_CRISIS_PERCENTILE", "VIX_CRISIS_ABS", "CORREL_CRISIS_THRESHOLD",
    "EXPOSURE_SCALE",
    "GE_CORR_WINDOW_DAYS", "GE_CORR_RISKON_THRESHOLD",
    "GE_CORR_FAKE_RISKON_THRESHOLD", "GE_CORR_PANIC_THRESHOLD",
    "DXY_LIQUIDITY_STRESS_ENABLED", "DXY_LIQUIDITY_STRESS_UP_PCT",
    "VIX_LIQUIDITY_STRESS_UP_PCT", "DXY_LIQUIDITY_STRESS_LOOKBACK_BARS",
    "MOMENTUM_LOOKBACK_BARS", "MOMENTUM_SKIP_BARS",
    "MOMENTUM_MIN_ABS_R", "COT_ZSCORE_LOOKBACK_WEEKS", "COT_ZSCORE_ENTRY",
    "CORREL_LOOKBACK_BARS", "CORREL_DUP_LIMIT", "USD_EXPOSURE_CAP",
    "ATR_STOP_MULT_BY_REGIME",
    "SESSION_FILTER_ALLOW",
    "EVENT_REDUCTION_ENABLED", "EVENT_REDUCTION_HOURS_BEFORE", "EVENT_REDUCTION_SCALE",
    "EVENT_VOLATILITY_HOURS_AFTER", "EVENT_VOLATILITY_SL_MULT", "EVENT_MIN_IMPORTANCE",
    "WF_TRAIN_BARS", "WF_TEST_BARS", "WF_STEP_BARS",
    "EXNESS_MAGIC", "COMMENT_TAG", "RunConfig",
]
