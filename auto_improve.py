"""
auto_improve.py — LOOP MESTRE DE MELHORIA CONTÍNUA
==================================================

Uso:
    python auto_improve.py                  # roda 1 ciclo completo
    python auto_improve.py --loop           # roda em loop infinito (sleep entre ciclos)
    python auto_improve.py --quick          # só análise pós-trade + recomendações (pula backtest longo)
    python auto_improve.py --tune           # roda análise + tuning de parâmetros

O que faz em 1 ciclo:
  1. Sincroniza trades pendentes (sync_orphan_closes)
  2. Roda post_trade_analysis.py (análise dos trades reais)
  3. Roda full_analysis.py (backtest completo com params atuais)
  4. Compara performance real vs backtest esperado
  5. Gera recomendações de melhoria
  6. Se --tune: roda sweep de parâmetros e atualiza config.py se encontrar melhoria
  7. Salva relatório consolidado em reports/IMPROVEMENT.md
  8. Se --loop: dorme CYCLE_HOURS horas e repete

Arquivos de saída:
  - reports/IMPROVEMENT.md       — relatório do ciclo atual
  - reports/IMPROVEMENT_LOG.jsonl — histórico de todos os ciclos
"""
import os
import sys
import json
import time
import subprocess
import traceback
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──
PROJECT_ROOT = Path(__file__).resolve().parent
BOT_DIR = PROJECT_ROOT / "bot"
ENGINE_DIR = PROJECT_ROOT / "engine"
REPORTS_DIR = PROJECT_ROOT / "reports"
CONFIG_PATH = ENGINE_DIR / "config.py"
STATE_PATH = BOT_DIR / "bot_state.json"
LOG_PATH = BOT_DIR / "trade_log.jsonl"
DECISION_LOG_PATH = BOT_DIR / "decision_log.jsonl"
IMPROVEMENT_LOG = REPORTS_DIR / "IMPROVEMENT_LOG.jsonl"
REPORT_PATH = REPORTS_DIR / "IMPROVEMENT.md"

# ── Config do loop ──
CYCLE_HOURS = 6          # tempo entre ciclos no modo --loop
MAX_LOG_ENTRIES = 500    # max linhas no improvement log

sys.path.insert(0, str(PROJECT_ROOT))

# ═════════════════════════════ UTILITÁRIOS ═════════════════════════════

def run_script(script_path: str, args: list = None, timeout: int = 600) -> tuple[bool, str]:
    """Roda um script Python e captura output. Retorna (sucesso, output)."""
    cmd = [sys.executable or "python", script_path] + (args or [])
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(PROJECT_ROOT)
        )
        output = result.stdout + "\n" + result.stderr
        return (result.returncode == 0), output.strip()
    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT ({timeout}s): {' '.join(cmd)}"
    except Exception as e:
        return False, f"ERRO: {type(e).__name__}: {e}"


def read_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def append_log(entry: dict):
    """Append no improvement log JSONL."""
    IMPROVEMENT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(IMPROVEMENT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    # Trunca se muito grande
    if IMPROVEMENT_LOG.exists():
        lines = IMPROVEMENT_LOG.read_text(encoding="utf-8").splitlines()
        if len(lines) > MAX_LOG_ENTRIES:
            IMPROVEMENT_LOG.write_text(
                "\n".join(lines[-MAX_LOG_ENTRIES:]), encoding="utf-8"
            )


def read_improvement_log() -> list[dict]:
    if not IMPROVEMENT_LOG.exists():
        return []
    try:
        lines = IMPROVEMENT_LOG.read_text(encoding="utf-8").splitlines()
        return [json.loads(l) for l in lines if l.strip()]
    except Exception:
        return []


def get_last_run_info() -> dict:
    """Extrai info da última execução do bot do state e logs."""
    state = read_json(STATE_PATH)
    info = {
        "last_run_utc": state.get("last_run_utc", "N/A"),
        "balance_today_start": state.get("starting_balance_today"),
        "balance_week_start": state.get("starting_balance_week"),
        "trades_opened": state.get("trades_opened_total", 0),
        "trades_closed": state.get("trades_closed_total", 0),
        "paused_until": state.get("paused_until_utc"),
    }
    return info


def parse_post_trade_report() -> dict:
    """Parse o relatório POST_TRADE.md para extrair métricas."""
    report_path = REPORTS_DIR / "POST_TRADE.md"
    if not report_path.exists():
        return {}
    text = report_path.read_text(encoding="utf-8")
    metrics = {}

    # Trades fechados
    import re
    m = re.search(r'\*\*Total:\*\* (\d+) trades.*?\*\*P&L:\*\* \$([-\d.]+)', text)
    if m:
        metrics["closed_trades"] = int(m.group(1))
        metrics["total_pnl"] = float(m.group(2))

    m = re.search(r'\*\*Win Rate:\*\* ([\d.]+)%', text)
    if m:
        metrics["win_rate"] = float(m.group(1))

    # P&L por símbolo
    symbol_section = False
    for line in text.splitlines():
        if line.startswith("| Símbolo |") and "P&L Total" in line:
            symbol_section = True
            continue
        if symbol_section and line.startswith("|---"):
            continue
        if symbol_section and line.startswith("|"):
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) >= 4:
                sym = parts[0]
                try:
                    pnl = float(parts[2].replace("$", "").replace("+", ""))
                    metrics[f"pnl_{sym}"] = pnl
                except (ValueError, IndexError):
                    pass
        elif symbol_section and not line.startswith("|"):
            break

    # Filtros bloqueadores
    filter_section = False
    for line in text.splitlines():
        if line.startswith("| Filtro |"):
            filter_section = True
            continue
        if filter_section and line.startswith("|---"):
            continue
        if filter_section and line.startswith("|"):
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) >= 2:
                try:
                    metrics[f"blocked_{parts[0]}"] = int(parts[1])
                except (ValueError, IndexError):
                    pass
        elif filter_section and not line.startswith("|"):
            break

    return metrics


def parse_analysis_report() -> dict:
    """Parse o relatório ANALYSIS.md para extrair métricas do backtest."""
    report_path = REPORTS_DIR / "ANALYSIS.md"
    if not report_path.exists():
        return {}
    text = report_path.read_text(encoding="utf-8")
    metrics = {}

    import re
    m = re.search(r'\*\*Retorno:\*\* \+?([-\d.]+)%', text)
    if m:
        metrics["bt_return_pct"] = float(m.group(1))

    m = re.search(r'\*\*Sharpe:\*\* ([\-\d.]+)', text)
    if m:
        metrics["bt_sharpe"] = float(m.group(1))

    m = re.search(r'\*\*Max DD:\*\* ([-\d.]+)%', text)
    if m:
        metrics["bt_max_dd"] = float(m.group(1))

    m = re.search(r'\*\*Win Rate:\*\* ([\d.]+)%', text)
    if m:
        metrics["bt_win_rate"] = float(m.group(1))

    m = re.search(r'\*\*Expectancy:\*\* \$([-\d.]+)/trade', text)
    if m:
        metrics["bt_expectancy"] = float(m.group(1))

    m = re.search(r'(\d+) trades \|', text)
    if m:
        metrics["bt_trades"] = int(m.group(1))

    m = re.search(r'\*\*Final:\*\* \$([\d.]+)', text)
    if m:
        metrics["bt_final_equity"] = float(m.group(1))

    return metrics


# ═════════════════════════════ GERADOR DE RECOMENDAÇÕES ═════════════════════════════

def generate_recommendations(backtest: dict, live: dict, history: list[dict]) -> list[str]:
    """Gera recomendações baseadas na comparação backtest × real e tendências históricas."""
    recs = []

    # 1. Comparacao backtest vs real
    bt_win_rate = backtest.get("bt_win_rate", 0)
    live_win_rate = live.get("win_rate", 0)
    if live_win_rate > 0 and live_win_rate < bt_win_rate * 0.5:
        recs.append(f"[CRITICO] Win rate real ({live_win_rate:.1f}%) muito abaixo do backtest ({bt_win_rate:.1f}%). "
                     "Revise se os filtros estao muito restritivos ou se o mercado mudou de regime.")

    # 2. Sharpe baixo
    bt_sharpe = backtest.get("bt_sharpe", 0)
    if backtest and bt_sharpe < 0.5:
        recs.append(f"[ATENCAO] Sharpe baixo ({bt_sharpe:.2f}). Considere aumentar o RR minimo ou reduzir "
                     "o risco por trade.")

    # 3. Drawdown alto
    bt_max_dd = backtest.get("bt_max_dd", 0)
    if backtest and bt_max_dd < -30:
        recs.append(f"[AVISO] Max Drawdown alto ({bt_max_dd:.1f}%). Verifique EXPOSURE_SCALE para risk_off "
                     "e considere reduzir RISK_PER_TRADE_PCT.")

    # 4. Exposure check bloqueando tudo
    blocked_exposure = live.get("blocked_exposure_check", 0)
    if blocked_exposure > 50:
        recs.append(f"[CRITICO] exposure_check bloqueou {blocked_exposure}x. Isso indica que o "
                     "TOTAL_RISK_CAP_PCT esta muito baixo para o lote minimo do simbolo. "
                     "Verificar RISK_OVERRIDE_PCT e TOTAL_RISK_CAP_PCT no config.py.")

    # 5. Analise de tendencia de melhoria/piora
    if len(history) >= 3:
        recent = history[-3:]
        bt_returns = [h.get("backtest", {}).get("bt_return_pct", 0) for h in recent]
        if all(r < 100 for r in bt_returns) and bt_returns[-1] < bt_returns[0]:
            recs.append(f"[TENDENCIA] Retorno do backtest em queda nos ultimos 3 ciclos: "
                         f"{bt_returns[0]:.1f}% -> {bt_returns[-1]:.1f}%. "
                         "Mercado pode estar mudando de regime. Considere re-otimizar parametros.")

    # 6. Verifica se ha posicao aberta ha muito tempo
    last_run = live.get("last_run_utc", "")
    if last_run and "T" in last_run:
        try:
            last_dt = datetime.fromisoformat(last_run)
            hours_since = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
            if hours_since > 24:
                recs.append(f"[PAUSADO] Bot nao roda ha {hours_since:.0f}h (ultimo run: {last_run}). "
                            "Verificar se o executor esta rodando (run_executor.bat) e se o watchdog esta ativo.")
        except Exception:
            pass

    # 7. Verifica se esta so bloqueando (sem abrir trades)
    total_decisions = live.get("total_decisions", 0)
    opened = live.get("opened", 0)
    if total_decisions > 50 and opened == 0:
        recs.append("[ATENCAO] Nenhum trade aberto nas ultimas decisoes. Verificar se o sinal "
                     "direcional esta funcionando ou se todos os filtros estao bloqueando.")

    if not recs:
        recs.append("[OK] Tudo dentro do esperado. Sistema operando conforme o backtest.")

    return recs


# ═════════════════════════════ GERAR RELATÓRIO ═════════════════════════════

def generate_report(cycle_info: dict, backtest: dict, live: dict,
                    recommendations: list[str], tuned: dict = None,
                    history: list = None):
    """Gera o relatório IMPROVEMENT.md."""
    if history is None:
        history = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = []
    lines.append(f"# CICLO DE MELHORIA CONTINUA")
    lines.append(f"**Gerado em:** {now}")
    lines.append(f"**Ciclo:** #{cycle_info.get('cycle_number', '?')}")
    lines.append(f"**Duração:** {cycle_info.get('duration_seconds', 0):.1f}s")
    lines.append("")

    # ── Seção 1: Estado Atual ──
    lines.append("## Estado Atual do Sistema")
    lines.append("")
    lines.append(f"| Métrica | Valor |")
    lines.append(f"|---------|-------|")
    last_run = live.get("last_run_utc", "N/A")
    lines.append(f"| Último run do bot | {last_run} |")
    lines.append(f"| Saldo início do dia | ${live.get('balance_today_start', 'N/A')} |")
    lines.append(f"| Trades abertos (total) | {live.get('trades_opened', 0)} |")
    lines.append(f"| Trades fechados | {live.get('closed_trades', 0)} |")
    lines.append(f"| P&L Real | ${live.get('total_pnl', 0):+.2f} |")
    lines.append(f"| Win Rate Real | {live.get('win_rate', 0):.1f}% |")
    lines.append("")

    # ── Seção 2: Backtest Atual ──
    lines.append("## Backtest (ts_momentum)")
    lines.append("")
    if backtest:
        lines.append(f"| Métrica | Valor |")
        lines.append(f"|---------|-------|")
        lines.append(f"| Trades | {backtest.get('bt_trades', '?')} |")
        lines.append(f"| Retorno | {backtest.get('bt_return_pct', 0):+.1f}% |")
        lines.append(f"| Sharpe | {backtest.get('bt_sharpe', 0):.2f} |")
        lines.append(f"| Max DD | {backtest.get('bt_max_dd', 0):.1f}% |")
        lines.append(f"| Win Rate | {backtest.get('bt_win_rate', 0):.1f}% |")
        lines.append(f"| Expectancy | ${backtest.get('bt_expectancy', 0):+.2f}/trade |")
        lines.append(f"| Equidade Final | ${backtest.get('bt_final_equity', 0):.2f} |")
    else:
        lines.append("Backtest não foi executado neste ciclo.")
    lines.append("")

    # ── Seção 3: Tuning de Parâmetros ──
    if tuned:
        lines.append("## Tuning de Parametros")
        lines.append("")
        lines.append(f"**Parâmetros originais VS otimizados**")
        lines.append("")
        lines.append(f"| Parâmetro | Antes | Depois | Delta |")
        lines.append(f"|-----------|-------|--------|-------|")
        for param, vals in tuned.items():
            if param == "timestamp":
                continue
            before = vals.get("before", "?")
            after = vals.get("after", "?")
            delta = vals.get("delta", "-")
            lines.append(f"| {param} | {before} | {after} | {delta} |")
        lines.append("")
        if tuned.get("config_updated"):
            lines.append("[OK] Configuracao atualizada automaticamente.")
        else:
            lines.append("[INFO] Nenhuma alteracao necessaria - parametros atuais sao otimos.")
        lines.append("")

    # ── Seção 4: Decisões Recentes ──
    lines.append("## Decisoes Recentes")
    lines.append("")
    total = live.get("total_decisions", 0)
    opened = live.get("opened", 0)
    dry_run = live.get("dry_run", 0)
    blocked = live.get("blocked_filter", 0)
    lines.append(f"**Total de decisões:** {total}")
    lines.append(f"- [OK] Trades abertos: {opened}")
    lines.append(f"- [DRY] Dry-run: {dry_run}")
    lines.append(f"- [BLOQ] Bloqueados por filtro: {blocked}")
    if live.get("blocked_exposure_check"):
        lines.append(f"  - exposure_check: {live.get('blocked_exposure_check')}")
    if live.get("blocked_max_positions"):
        lines.append(f"  - max_positions: {live.get('blocked_max_positions')}")
    if live.get("blocked_risk_cap"):
        lines.append(f"  - risk_cap: {live.get('blocked_risk_cap')}")
    if live.get("blocked_rr_2.00_below_2.0"):
        lines.append(f"  - RR abaixo do mínimo: {live.get('blocked_rr_2.00_below_2.0')}")
    lines.append("")

    # ── Seção 5: Recomendações ──
    lines.append("## Recomendacoes")
    lines.append("")
    for rec in recommendations:
        lines.append(rec)
    lines.append("")

    # ── Seção 6: Histórico de Ciclos ──
    if history:
        lines.append("## Historico de Ciclos")
        lines.append("")
        lines.append("| Ciclo | Data | Sharpe BT | Retorno BT | P&L Real | Ações |")
        lines.append("|-------|------|-----------|------------|----------|-------|")
        for i, h in enumerate(history[-10:], 1):
            bt = h.get("backtest", {})
            lv = h.get("live", {})
            ts = h.get("timestamp", "?")[:16]
            sharpe = bt.get("bt_sharpe", 0)
            ret = bt.get("bt_return_pct", 0)
            pnl = lv.get("total_pnl", 0)
            n_recs = len(h.get("recommendations", []))
            rec_label = "OK" if n_recs == 1 and "Tudo dentro" in str(h.get("recommendations", [])) else str(n_recs) + " rec"
            lines.append(f"| {i} | {ts} | {sharpe:.2f} | {ret:+.1f}% | ${pnl:+.2f} | {rec_label} |")
        lines.append("")

    lines.append("---")
    lines.append(f"_Relatório gerado por auto_improve.py em {now}_")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    return REPORT_PATH


# ═════════════════════════════ MAIN CYCLE ═════════════════════════════

def run_cycle(cycle_number: int, quick: bool = False, do_tune: bool = False) -> dict:
    """Executa 1 ciclo completo de melhoria. Retorna resumo."""
    print("=" * 60)
    print(f"  CICLO DE MELHORIA #{cycle_number}")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)
    start_ts = time.time()

    cycle_info = {
        "cycle_number": cycle_number,
        "start_utc": datetime.now(timezone.utc).isoformat(),
    }

    # ── Passo 1: Estado atual ──
    print("\n[1/5] Estado atual do bot...")
    live_info = get_last_run_info()
    print(f"   Último run: {live_info.get('last_run_utc', 'N/A')}")
    print(f"   Trades abertos (hist): {live_info.get('trades_opened', 0)}")

    # ── Passo 2: Post-trade analysis (rápido) ──
    print("\n[2/5] Rodando análise pós-trade...")
    success, output = run_script(str(BOT_DIR / "post_trade_analysis.py"))
    if success:
        print("   [OK] Análise pós-trade concluída")
    else:
        print(f"   [AVISO] post_trade_analysis falhou:\n{output[:200]}")

    # Lê métricas do relatório
    live_metrics = parse_post_trade_report()
    # Adiciona info do bot state
    live_metrics.update(live_info)

    # Conta decisões do log
    try:
        if DECISION_LOG_PATH.exists():
            lines = DECISION_LOG_PATH.read_text(encoding="utf-8").splitlines()
            live_metrics["total_decisions"] = len([l for l in lines if l.strip()])
            # Conta resultados
            from collections import Counter
            results = Counter()
            filters = Counter()
            for line in lines:
                try:
                    d = json.loads(line)
                    payload = d.get("payload", {})
                    r = payload.get("result", "unknown")
                    results[r] += 1
                    fb = payload.get("filter_blocked")
                    if fb:
                        filters[fb] += 1
                except Exception:
                    pass
            live_metrics["opened"] = results.get("opened", 0)
            live_metrics["dry_run"] = results.get("dry_run", 0)
            live_metrics["blocked_filter"] = results.get("blocked_filter", 0)
            live_metrics["no_signal"] = results.get("no_signal", 0)
            for f, c in filters.most_common(10):
                live_metrics[f"blocked_{f}"] = c
    except Exception as e:
        print(f"   [AVISO] Erro lendo decision_log: {e}")

    # ── Passo 3: Backtest (pula se --quick) ──
    backtest_metrics = {}
    if not quick:
        print("\n[3/5] Rodando backtest completo...")
        success, output = run_script(str(ENGINE_DIR / "full_analysis.py"), timeout=600)
        if success:
            print("   [OK] Backtest concluído")
        else:
            print(f"   [AVISO] full_analysis falhou:\n{output[:300]}")
        backtest_metrics = parse_analysis_report()
    else:
        print("\n[3/5] Modo --quick: pulando backtest. Lendo último relatório...")
        backtest_metrics = parse_analysis_report()
        if backtest_metrics:
            print(f"   Último backtest: Sharpe {backtest_metrics.get('bt_sharpe', '?')}, "
                  f"Ret {backtest_metrics.get('bt_return_pct', 0):+.1f}%")
        else:
            print("   Nenhum relatório de backtest encontrado.")

    # ── Passo 4: Tuning (opcional) ──
    tuned_params = None
    if do_tune and backtest_metrics:
        print("\n[4/5] Rodando tuning de parâmetros...")
        success, output = run_script(str(PROJECT_ROOT / "auto_tune.py"), timeout=600)
        if success:
            print("   [OK] Tuning concluído")
            # Lê resultado do tuning
            tune_result_path = REPORTS_DIR / "TUNE_RESULT.json"
            if tune_result_path.exists():
                try:
                    tuned_params = json.loads(tune_result_path.read_text(encoding="utf-8"))
                    print(f"   Parâmetros atualizados: {len(tuned_params)} alterações")
                except Exception:
                    pass
        else:
            print(f"   [AVISO] auto_tune falhou:\n{output[:300]}")
    else:
        print("\n[4/5] Tuning não solicitado (use --tune).")

    # ── Passo 5: Recomendações ──
    print("\n[5/5] Gerando recomendações...")
    history = read_improvement_log()
    recommendations = generate_recommendations(backtest_metrics, live_metrics, history)

    for rec in recommendations:
        print(f"   • {rec}")

    # ── Salva ciclo ──
    duration = time.time() - start_ts
    cycle_info["duration_seconds"] = round(duration, 1)
    cycle_info["timestamp"] = datetime.now(timezone.utc).isoformat()

    entry = {
        "timestamp": cycle_info["timestamp"],
        "cycle_number": cycle_number,
        "duration_s": cycle_info["duration_seconds"],
        "live": live_metrics,
        "backtest": backtest_metrics,
        "tuned": tuned_params,
        "recommendations": recommendations,
    }
    append_log(entry)

    report_path = generate_report(cycle_info, backtest_metrics, live_metrics,
                                  recommendations, tuned_params, history)
    print(f"\n{'=' * 60}")
    print(f"  RELATÓRIO: {report_path}")
    print(f"  DURAÇÃO: {duration:.1f}s")
    print(f"{'=' * 60}")

    return entry


# ═════════════════════════════ CLI ═════════════════════════════

def main():
    args = sys.argv[1:]
    loop_mode = "--loop" in args
    quick_mode = "--quick" in args
    tune_mode = "--tune" in args

    # Lê histórico pra saber qual é o próximo ciclo
    history = read_improvement_log()
    next_cycle = len(history) + 1

    if loop_mode:
        print(f"Modo LOOP: executando a cada {CYCLE_HOURS}h")
        while True:
            run_cycle(next_cycle, quick=quick_mode, do_tune=tune_mode)
            next_cycle += 1
            print(f"\nPróximo ciclo em {CYCLE_HOURS}h. Ctrl+C para parar.\n")
            try:
                time.sleep(CYCLE_HOURS * 3600)
            except KeyboardInterrupt:
                print("\nLoop interrompido pelo usuário.")
                break
    else:
        run_cycle(next_cycle, quick=quick_mode, do_tune=tune_mode)


if __name__ == "__main__":
    main()
