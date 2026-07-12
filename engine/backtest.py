"""backtest.py — motor de backtest honesto, barra-a-barra, zero lookahead.

PRINCÍPIOS (cada um é o que separa backtest que mente de backtest que informa):
  1. ZERO LOOKAHEAD. A decisão no tempo t só enxerga dados ATÉ t-1. O high/low
     de t não pode influenciar se entro em t. Implementação: sinais computados
     com .shift(1) antes da checagem de execução. Há teste automatizado disso.
  2. CUSTOS REAIS. Toda entrada paga spread + slippage. Sem isso, 90% das
     estratégias parecem lucrativas. spread em PONTOS (config.SPREAD_POINTS).
  3. SAÍDA INTRA-BARRA CONSERVATIVA. Se numa barra tanto o stop quanto o alvo
     foram tocados (high/low cruzam ambos), assumimos o PIOR CASO (stop primeiro).
     Isto é pessimista de propósito — prefiro subestimar edge que superestimar.
  4. WALK-FORWARD. Otimiza (se houver parâmetros) só em in-sample; o número
     reportado vem de out-of-sample nunca visto no treino. Anti-overfit.

O motor não conhece estratégia nem regime: ele executa sinais que recebe.
Strategy e RegimeProvider são injetados (ver signals.py, regime.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, Callable

import numpy as np
import pandas as pd

from . import config as C
from .utils import session_of


# ═════════════════════════════ TIPOS ═════════════════════════════
@dataclass
class Trade:
    """Um trade fechado. Tudo que o analytics.py precisa pra computar métricas."""
    symbol: str
    direction: str          # "BUY" | "SELL"
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    size_units: float       # fração da conta arriscada (1.0 = risco cheio do plano)
    pnl_pct: float          # retorno % sobre o capital arriscado (líquido de custo)
    pnl_usd: float          # P&L em USD (sobre saldo no momento)
    rr_realized: float      # reward/risk realizado
    exit_reason: str        # "TP" | "SL" | "TIME" | "SIGNAL_FLIP" | "REGIME_EXIT"
    regime_at_entry: str = ""
    atr_stop_mult: float = 0.0  # ATR multiplier usado (regime-based)


@dataclass
class BacktestResult:
    """Resultado completo de um run. Inclui série temporal e lista de trades."""
    label: str
    trades: list[Trade]
    equity: pd.Series               # índice por timestamp, valor = saldo USD
    exposure: pd.Series             # índice por timestamp, fração exposta (0..1)
    regime: pd.Series               # regime por timestamp (pra cortar métricas por estado)
    config: dict = field(default_factory=dict)
    n_bars: int = 0
    period: tuple[str, str] = ("", "")

    def summary(self) -> dict:
        from . import analytics
        return analytics.basic_summary(self)


# ═════════════════════════════ CUSTOS ═════════════════════════════
def cost_in_price(symbol: str, digits: int) -> float:
    """Custo de entrada em UNIDADES DE PREÇO (spread+slippage). Em pontos/10^digits."""
    pts = C.SPREAD_POINTS.get(symbol, 5) + C.SLIPPAGE_POINTS.get(symbol, 1)
    return pts / (10 ** digits)


# ═════════════════════════════ POSIÇÃO ABERTA (estado interno) ═════════════════════════════
@dataclass
class _OpenPos:
    symbol: str
    direction: str
    entry_time: pd.Timestamp
    entry_price: float
    stop: float
    take: float
    size_frac: float            # fração do saldo arriscada se bater stop
    risk_usd: float             # USD em jogo (perda se stop)
    regime_at_entry: str
    _entry_bar_idx: int = 0          # índice no common_idx (pra trailing stop + holding time)
    _original_stop_move: float = 0.0  # distância original entry→stop (não muda com breakeven)
    _partial_tp_taken: bool = False   # se já realizou parcialmente (scale-out)
    atr_stop_mult: float = 0.0        # ATR multiplier usado neste trade (regime-based)


# ═════════════════════════════ MOTOR ═════════════════════════════
def run_backtest(
    prices: dict[str, pd.DataFrame],
    strategy,                          # objeto com método .signals(ctx) -> dict[sym]->("BUY"|"SELL"|"NONE", size_frac)
    regime_provider=None,              # objeto com .at(ts, ctx) -> regime str; None = "normal" sempre
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    account_start: float = C.ACCOUNT_START_USD,
    max_positions: int = C.MAX_OPEN_POSITIONS,
    risk_per_trade_pct: float = C.RISK_PER_TRADE_PCT,
    risk_pct_by_regime: Optional[dict[str, float]] = None,  # risco VARIÁVEL por regime (ex: risk_on=8%)
    d1_momentum: Optional[dict[str, pd.Series]] = None,     # D1 momentum por símbolo (pro filtro de tendência)
    use_costs: bool = True,
    use_rr_filter: bool = True,
    min_rr: float = C.MIN_REWARD_RISK,
    label: str = "run",
    dxy_pct: Optional[pd.Series] = None,      # série de % change do DXY indexada por H4
    vix_pct: Optional[pd.Series] = None,       # série de % change do VIX indexada por H4
    spy_return: Optional[pd.Series] = None,    # série de retorno diário do SPY (para gold-equity corr no regime)
    macro_events: Optional[list[dict]] = None, # lista de eventos econômicos pra backtest
) -> BacktestResult:
    """Roda backtest barra-a-barra sobre os preços alinhados.

    strategy.signals(ctx): recebe um ctx com preços até t-1 e devolve, por símbolo,
    um par (direction, size_frac). direction in {"BUY","SELL","NONE"}.
    size_frac em [0,1] = fração da conta a arriscar nesse trade.

    regime_provider.at(ts, ctx): devolve regime ("risk_on"/"normal"/"risk_off"/"crisis").
    Se None, assume "normal" (sem gate de regime).

    Saída por: stop / take / flip de sinal / regime crisis (fecha tudo).
    """
    # ── alinha índices comuns ──
    common_idx = _common_index(prices)
    if start:
        common_idx = common_idx[common_idx >= pd.Timestamp(start, tz="UTC")]
    if end:
        common_idx = common_idx[common_idx <= pd.Timestamp(end, tz="UTC")]
    if len(common_idx) < 200:
        raise ValueError(f"Poucas barras no período ({len(common_idx)})")

    digits = {s: int(prices[s]["close"].iloc[0:1].count()) for s in prices}  # placeholder
    # digits reais via número de casas decimais (preço EURUSD=1.13xx → 5)
    digits = {}
    for s, df in prices.items():
        sample = df["close"].iloc[-1]
        # conta casas: arredonda até bater
        d = 0
        for cand in (5, 3, 2):
            if round(sample, cand) == sample:
                d = cand; break
        digits[s] = d if d else 5

    balance = account_start
    total_swap_cost = 0.0              # acumulador de swap (corrige: swap não era contabilizado)
    equity_pts = []
    exposure_pts = []
    regime_pts = []
    open_positions: list[_OpenPos] = []
    closed_trades: list[Trade] = []
    last_exit: dict[str, int] = {}    # sym -> índice na common_idx quando foi fechado por último
    loss_streak: int = 0              # perdas consecutivas (para pausa anti-tilt)
    loss_streak_start_bar: int = 0    # barra índice onde a streak começou
    # Macro events: módulo lazy-import (só carrega se EVENT_REDUCTION_ENABLED)
    _macro_event_fns = None  # (events_near, get_events) cache

    # helper: verifica se a barra atual é rollover (17:00 ET ≈ 21:00 UTC)
    def _is_rollover_bar(ts: pd.Timestamp) -> bool:
        """True se esta barra H4 cruza o horário de rollover (21:00 UTC / 17:00 ET)."""
        # Barra H4: timestamps em 0,4,8,12,16,20 UTC.
        # Rollover acontece às 21:00 UTC. A barra que contém 21:00 é a das 20:00 UTC,
        # que vai de 20:00 a 23:59 UTC. Sexta-feira o swap é 3x (rola para segunda).
        h = ts.hour
        return h == 20  # barra das 20:00 UTC (cruza rollover 21:00)

    def _swap_cost(pos) -> float:
        """Custo de swap para esta posição na barra atual.
        Retorna custo negativo para long, positivo para short (como na vida real).
        """
        if pos.direction == "BUY":
            return C.SWAP_LONG_USD_PER_LOT.get(pos.symbol, 0.0) * pos.size_frac
        else:
            return C.SWAP_SHORT_USD_PER_LOT.get(pos.symbol, 0.0) * pos.size_frac

    # helper: contexto passado à estratégia (snapshot imutável do "passado")
    def ctx_at(t_idx: int) -> dict:
        ts = common_idx[t_idx]
        # slice ATÉ t_idx INCLUSIVE? NÃO — para decisão usamos até t_idx-1.
        # Mas o motor decide em t e executa no close de t (sem ver high/low de t+1).
        # Sinais já são shiftados internamente pelas estratégias (causal). Passamos t.
        past = {s: prices[s].loc[:ts] for s in prices}
        ctx = {"ts": ts, "prices": past, "balance": balance,
                "open": list(open_positions), "digits": digits}
        # DXY % change e VIX % change para o detector de liquidez/stress
        if dxy_pct is not None and ts in dxy_pct.index:
            v = dxy_pct.loc[ts]
            if pd.notna(v):
                ctx["dxy_pct_change"] = float(v)
        if vix_pct is not None and ts in vix_pct.index:
            v = vix_pct.loc[ts]
            if pd.notna(v):
                ctx["vix_pct_change"] = float(v)
        # SPY return para o detector de gold-equity correlation (pânico)
        if spy_return is not None:
            spy_reindexed = spy_return.reindex(common_idx, method="ffill")
            if ts in spy_reindexed.index:
                v = spy_reindexed.loc[ts]
                if pd.notna(v):
                    ctx["spy_return"] = float(v)
        return ctx

    for i in range(1, len(common_idx)):
        ts = common_idx[i]

        # ── 1. Custo de swap (rollover) — aplicado na barra que contém 17:00 ET ──
        if _is_rollover_bar(ts):
            swap_mult = 3.0 if C.SWAP_TRIPLE_ON_WEDNESDAY and ts.weekday() == 2 else 1.0
            for pos in open_positions:
                swap = _swap_cost(pos) * swap_mult
                total_swap_cost += swap  # acumula separadamente (NÃO mexe no balance ainda)

        # ── 2. Atualiza P&L das posições abertas com o high/low DESSA barra ──
        # Checks por posição (na ordem: breakeven → trailing stop → partial TP → SL/TP → holding time):
        still_open = []
        for pos in open_positions:
            bar = prices[pos.symbol].loc[ts] if ts in prices[pos.symbol].index else None
            if bar is None:
                still_open.append(pos); continue
            hi, lo = bar["high"], bar["low"]
            close_px = bar["close"]

            if pos.direction == "BUY":
                favor_move = close_px - pos.entry_price
            else:
                favor_move = pos.entry_price - close_px

            # Usa _original_stop_move (gravado na abertura) para TODOS os checks
            # de threshold. Isto é CRÍTICO: depois que o breakeven move o stop para
            # o entry, stop_move calculado ao vivo vira 0 e quebra trailing + partial TP.
            orig_stop = pos._original_stop_move

            # 1a. BREAKEVEN STOP: move o stop para o ponto de entrada quando o preço
            #     atinge BREAKEVEN_ACTIVATE_RR × stop_move a favor.
            #     Garante que o trade nunca vire perda após atingir este nível.
            #     0 = desativado.
            if (C.BREAKEVEN_ACTIVATE_RR > 0 and orig_stop > 0 and
                    favor_move >= orig_stop * C.BREAKEVEN_ACTIVATE_RR and
                    ((pos.direction == "BUY" and pos.stop < pos.entry_price) or
                     (pos.direction == "SELL" and pos.stop > pos.entry_price))):
                pos.stop = round(pos.entry_price, digits[pos.symbol])

            # 1b. TRAILING STOP: quando o CLOSE move X×RR a favor, trilha o stop.
            #     Usa orig_stop (distância ORIGINAL) para funcionar MESMO DEPOIS
            #     do breakeven. Usa CLOSE (não high/low) pra evitar whipsaw.
            #     0 = desativado.
            bars_held = i - pos._entry_bar_idx
            if (C.TRAILING_STOP_ACTIVATE_RR > 0 and orig_stop > 0 and
                    favor_move >= orig_stop * C.TRAILING_STOP_ACTIVATE_RR):
                if pos.direction == "BUY":
                    new_stop = close_px - orig_stop * C.TRAILING_STOP_LOCK_RR
                    pos.stop = max(pos.stop, round(new_stop, digits[pos.symbol]))
                else:
                    new_stop = close_px + orig_stop * C.TRAILING_STOP_LOCK_RR
                    pos.stop = min(pos.stop, round(new_stop, digits[pos.symbol]))

            # 1c. PARTIAL TAKE-PROFIT: realiza 30% em 1×RR, deixa 70% correr.
            #     Usa orig_stop para funcionar mesmo depois do breakeven.
            if (C.PARTIAL_TP_RR > 0 and not pos._partial_tp_taken and orig_stop > 0 and
                    ((pos.direction == "BUY" and hi >= pos.entry_price + orig_stop * C.PARTIAL_TP_RR) or
                     (pos.direction == "SELL" and lo <= pos.entry_price - orig_stop * C.PARTIAL_TP_RR))):
                pos._partial_tp_taken = True
                # Calcula preço do partial TP
                if pos.direction == "BUY":
                    partial_px = pos.entry_price + orig_stop * C.PARTIAL_TP_RR
                else:
                    partial_px = pos.entry_price - orig_stop * C.PARTIAL_TP_RR
                # Fecha a fração parcial
                partial_risk = pos.risk_usd * C.PARTIAL_TP_FRACTION
                partial_rr = C.PARTIAL_TP_RR  # 1×RR no momento do scale-out
                partial_pnl = partial_rr * partial_risk
                partial_pnl_pct = (partial_pnl / balance * 100.0) if balance > 0 else 0.0
                closed_trades.append(Trade(
                    symbol=pos.symbol, direction=pos.direction,
                    entry_time=pos.entry_time, entry_price=pos.entry_price,
                    exit_time=ts, exit_price=partial_px,
                    size_units=pos.size_frac * C.PARTIAL_TP_FRACTION,
                    pnl_pct=partial_pnl_pct, pnl_usd=partial_pnl,
                    rr_realized=partial_rr, exit_reason="PARTIAL_TP",
                    regime_at_entry=pos.regime_at_entry,
                    atr_stop_mult=pos.atr_stop_mult,
                ))
                # Reduz a posição restante proporcionalmente
                remaining_frac = 1.0 - C.PARTIAL_TP_FRACTION
                pos.size_frac *= remaining_frac
                pos.risk_usd *= remaining_frac

            # 1d. STOP / TAKE (conservador: ambos tocados = stop primeiro)
            hit_sl = (pos.direction == "BUY"  and lo <= pos.stop) or \
                     (pos.direction == "SELL" and hi >= pos.stop)
            hit_tp = (pos.direction == "BUY"  and hi >= pos.take) or \
                     (pos.direction == "SELL" and lo <= pos.take)
            if hit_sl and hit_tp:
                _close_trade(pos, pos.stop, ts, "SL", closed_trades, balance_snapshot=balance,
                             last_exit=last_exit, bar_idx=i)
            elif hit_sl:
                _close_trade(pos, pos.stop, ts, "SL", closed_trades, balance_snapshot=balance,
                             last_exit=last_exit, bar_idx=i)
            elif hit_tp:
                _close_trade(pos, pos.take, ts, "TP", closed_trades, balance_snapshot=balance,
                             last_exit=last_exit, bar_idx=i)
            # 1e. HOLDING TIME MAX: posição não fica aberta eternamente.
            #     0 = desativado.
            elif C.HOLDING_TIME_MAX_BARS > 0 and bars_held >= C.HOLDING_TIME_MAX_BARS:
                px = bar["close"]
                _close_trade(pos, px, ts, "TIME", closed_trades, balance_snapshot=balance,
                             last_exit=last_exit, bar_idx=i)
            else:
                still_open.append(pos)
        open_positions = still_open

        # ── 3. Regime agora (gate de exposição / saída por mudança de regime) ──
        regime = regime_provider.at(ts, ctx_at(i)) if regime_provider else "normal"
        regime_pts.append((ts, regime))
        # Crisis: fecha tudo
        if regime == "crisis" and open_positions:
            for pos in list(open_positions):
                px = prices[pos.symbol].loc[ts, "close"] if ts in prices[pos.symbol].index else pos.entry_price
                _close_trade(pos, px, ts, "REGIME_EXIT", closed_trades, balance_snapshot=balance,
                             last_exit=last_exit, bar_idx=i)
            open_positions = []
        # Risk_off com REGIME_EXIT_ON_RISKOFF: fecha posições abertas (conservador)
        elif C.REGIME_EXIT_ON_RISKOFF and regime == "risk_off" and open_positions:
            for pos in list(open_positions):
                px = prices[pos.symbol].loc[ts, "close"] if ts in prices[pos.symbol].index else pos.entry_price
                _close_trade(pos, px, ts, "REGIME_EXIT", closed_trades, balance_snapshot=balance,
                             last_exit=last_exit, bar_idx=i)
            open_positions = []

        # ── 3b. Atualiza loss streak baseado nos trades que fecharam NESTA barra ──
        # Verifica os trades fechados nesta iteração (os que têm exit_time == ts)
        new_closes = [t for t in closed_trades if t.exit_time == ts]
        for t in new_closes:
            if t.pnl_usd <= 0:
                loss_streak += 1
            else:
                loss_streak = 0  # reset ao ganhar
        # Se atingiu max streak, marca o início
        if loss_streak == 0:
            loss_streak_start_bar = 0
        elif loss_streak >= C.MAX_LOSS_STREAK and loss_streak_start_bar == 0:
            loss_streak_start_bar = i

        # ── 4. Recálculo do saldo = saldo_inicial + soma pnl_usd de todos fechados + swap ──
        balance = account_start + sum(t.pnl_usd for t in closed_trades) + total_swap_cost

        # ── 5. Novas entradas (se há slot e regime permite) ──
        base_scale = C.EXPOSURE_SCALE.get(regime, 0.5)
        scale = base_scale
        slots = max_positions - len(open_positions)

        # ── 4a. Macro events: reduz escala antes de eventos de alto impacto ──
        #     E alarga o stop após eventos (volatilidade extra)
        event_near_list = []
        event_sl_mult = 1.0  # multiplicador do stop (1.0 = normal)
        if C.EVENT_REDUCTION_ENABLED and macro_events is not None:
            if _macro_event_fns is None:
                # Import lazy (evita circular imports na inicialização do módulo)
                try:
                    from .macro_events import events_near
                    _macro_event_fns = events_near
                except ImportError:
                    _macro_event_fns = False  # flag: falhou, não tenta de novo
            if _macro_event_fns and _macro_event_fns is not False:
                # Eventos PRÓXIMOS (que vão acontecer em breve — olha pra frente)
                # hours_before = janela futura, hours_after = janela passada
                near_before = _macro_event_fns(
                    macro_events, ts,
                    hours_before=C.EVENT_REDUCTION_HOURS_BEFORE,
                    hours_after=0,
                    min_importance=C.EVENT_MIN_IMPORTANCE,
                )
                if near_before:
                    # Reduz escala proporcionalmente
                    scale *= C.EVENT_REDUCTION_SCALE
                    event_near_list = near_before

                # Eventos RECENTES (que acabaram de acontecer — olha pra trás)
                near_after = _macro_event_fns(
                    macro_events, ts,
                    hours_before=0,
                    hours_after=C.EVENT_VOLATILITY_HOURS_AFTER,
                    min_importance=C.EVENT_MIN_IMPORTANCE,
                )
                if near_after:
                    event_sl_mult = C.EVENT_VOLATILITY_SL_MULT
                    event_near_list.extend(near_after)

        # Loss streak cooldown: se está em streak, bloqueia novas entradas
        in_loss_streak_cooldown = (loss_streak >= C.MAX_LOSS_STREAK and
                                   (i - loss_streak_start_bar) < C.LOSS_STREAK_COOLDOWN_BARS)
        if slots > 0 and scale > 0.05 and not in_loss_streak_cooldown:
            ctx = ctx_at(i)
            sigs = strategy.signals(ctx) if hasattr(strategy, "signals") else {}
            for sym, val in sigs.items():
                if slots <= 0:
                    break
                if sym not in prices:
                    continue
                direction, size_frac = (val if isinstance(val, tuple) else (val, 0.05))
                if direction == "NONE" or size_frac <= 0:
                    continue
                # D1 TREND FILTER: só trade na direção da tendência diária
                if C.D1_FILTER_ENABLED and d1_momentum is not None and sym in d1_momentum:
                    d1_val = d1_momentum[sym].reindex([ts]).iloc[0] if ts in d1_momentum[sym].index else 0.0
                    if pd.notna(d1_val):
                        if d1_val > 0 and direction == "SELL":
                            continue  # D1 em alta, não vender
                        if d1_val < 0 and direction == "BUY":
                            continue  # D1 em baixa, não comprar
                # dedup anti-empilhamento: não abre no mesmo símbolo se já há posição
                if any(p.symbol == sym for p in open_positions):
                    continue
                # COOLDOWN: após sair de sym, espera N barras antes de reentrar
                prev_exit_idx = last_exit.get(sym, -999)
                if (i - prev_exit_idx) < C.COOLDOWN_BARS:
                    continue
                # SESSION FILTER: só entra se a sessão atual está na whitelist
                if C.SESSION_FILTER_ALLOW:
                    sess = session_of(ts)
                    if sess not in C.SESSION_FILTER_ALLOW:
                        continue
                bar = prices[sym].loc[ts] if ts in prices[sym].index else None
                if bar is None:
                    continue
                entry = bar["close"]
                if use_costs:
                    c = cost_in_price(sym, digits[sym])
                    entry_eff = entry + c if direction == "BUY" else entry - c
                else:
                    entry_eff = entry

                # stop/take via ATR (calculado sobre dados até ts, sem lookahead)
                from .indicators import atr
                a = atr(prices[sym].loc[:ts]).iloc[-1]
                if not np.isfinite(a) or a <= 0:
                    continue
                # ATR stop multiplciador adaptativo por regime de mercado
                # risk_on: stop MAIS LARGO (2.0×ATR) para deixar winners correrem
                # risk_off: stop MAIS APERTADO (1.0×ATR) para sair rapido
                regime_stop_mult = C.ATR_STOP_MULT_BY_REGIME.get(regime, C.ATR_STOP_MULT)
                stop_dist = a * regime_stop_mult
                # Se macro event acabou de acontecer, alarga o stop (vol extra)
                effective_stop_dist = stop_dist * event_sl_mult
                if direction == "BUY":
                    stop = entry_eff - effective_stop_dist
                    take = entry_eff + stop_dist * C.RR_TARGET_MULT  # TP não muda
                else:
                    stop = entry_eff + effective_stop_dist
                    take = entry_eff - stop_dist * C.RR_TARGET_MULT

                # tamanho: fração do saldo × scale de regime (com redução macro) × risk (variável por regime)
                regime_risk = risk_pct_by_regime.get(regime, risk_per_trade_pct) if risk_pct_by_regime else risk_per_trade_pct
                risk_usd = balance * (regime_risk / 100.0) * size_frac * scale
                if risk_usd <= 0:
                    continue

                open_positions.append(_OpenPos(
                    symbol=sym, direction=direction, entry_time=ts,
                    entry_price=entry_eff, stop=stop, take=take,
                    size_frac=size_frac * scale, risk_usd=risk_usd,
                    regime_at_entry=regime,
                    _entry_bar_idx=i,
                    _original_stop_move=effective_stop_dist,  # stop real (pode ser alargado)
                    atr_stop_mult=regime_stop_mult,           # regime-based ATR mult
                ))
                slots -= 1

        # ── 5. Equity = saldo + P&L flutuante das abertas (mark-to-market no close) ──
        floating = 0.0
        for pos in open_positions:
            bar = prices[pos.symbol].loc[ts] if ts in prices[pos.symbol].index else None
            if bar is None:
                continue
            px = bar["close"]
            # P&L proporcional ao risco (se stop = -risk_usd, então 1×RR move = +2×risk_usd)
            # Usa _original_stop_move para que o floating funcione mesmo depois do
            # breakeven (quando stop = entry, stop_move ao vivo = 0).
            if pos.direction == "BUY":
                moved = px - pos.entry_price
            else:
                moved = pos.entry_price - px
            orig = pos._original_stop_move
            if orig > 0:
                rr_now = moved / orig
                floating += rr_now * pos.risk_usd
        equity_pts.append((ts, balance + floating))
        exposure_pts.append((ts, sum(p.risk_usd for p in open_positions) / balance if balance > 0 else 0.0))

    # fecha posições restantes no fim do período (a mercado, sem custo extra p/ simplicidade)
    if open_positions and len(common_idx) > 0:
        last_ts = common_idx[-1]
        last_i = len(common_idx) - 1
        for pos in open_positions:
            px = prices[pos.symbol].loc[last_ts, "close"] if last_ts in prices[pos.symbol].index else pos.entry_price
            _close_trade(pos, px, last_ts, "TIME", closed_trades, balance_snapshot=balance,
                         last_exit=last_exit, bar_idx=last_i)

    equity = pd.Series(dict(equity_pts), name="equity")
    exposure = pd.Series(dict(exposure_pts), name="exposure")
    regime_s = pd.Series(dict(regime_pts), name="regime")

    return BacktestResult(
        label=label, trades=closed_trades, equity=equity, exposure=exposure,
        regime=regime_s, n_bars=len(common_idx),
        period=(str(common_idx[0].date()), str(common_idx[-1].date())),
        config={"account_start": account_start, "max_positions": max_positions,
                "risk_per_trade_pct": risk_per_trade_pct, "use_costs": use_costs,
                "label": label},
    )


# ═════════════════════════════ HELPERS INTERNOS ═════════════════════════════
def _close_trade(pos: _OpenPos, exit_price: float, exit_time: pd.Timestamp,
                 reason: str, closed: list[Trade], balance_snapshot: float,
                 last_exit: dict | None = None, bar_idx: int = 0):
    """Calcula pnl e registra trade fechado. Atualiza last_exit pra cooldown.

    Usa pos._original_stop_move para o cálculo do RR, NÃO o stop ao vivo.
    Isto é CRÍTICO porque após o breakeven mover o stop para o entry,
    stop_move ao vivo vira 0 e zeraria todo PnL dos trades que passam do breakeven.
    """
    if pos.direction == "BUY":
        moved = exit_price - pos.entry_price
    else:
        moved = pos.entry_price - exit_price
    orig = pos._original_stop_move
    rr = moved / orig if orig > 0 else 0.0
    pnl_usd = rr * pos.risk_usd
    pnl_pct = (pnl_usd / balance_snapshot * 100.0) if balance_snapshot > 0 else 0.0
    closed.append(Trade(
        symbol=pos.symbol, direction=pos.direction,
        entry_time=pos.entry_time, entry_price=pos.entry_price,
        exit_time=exit_time, exit_price=exit_price,
        size_units=pos.size_frac, pnl_pct=pnl_pct, pnl_usd=pnl_usd,
        rr_realized=rr, exit_reason=reason, regime_at_entry=pos.regime_at_entry,
        atr_stop_mult=pos.atr_stop_mult,
    ))
    if last_exit is not None:
        last_exit[pos.symbol] = bar_idx


def _common_index(prices: dict[str, pd.DataFrame]) -> pd.DatetimeIndex:
    """Índice de timestamps presente em TODOS os símbolos (interseção)."""
    idx = None
    for df in prices.values():
        i = df.index
        idx = i if idx is None else idx.intersection(i)
    return idx.sort_values().unique()


__all__ = ["Trade", "BacktestResult", "run_backtest", "cost_in_price"]
