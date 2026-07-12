"""
auto_tune.py — ANALISE E AJUSTE DE PARAMETROS
==============================================

Uso:
    python auto_tune.py                     # analisa parametros e sugere ajustes
    python auto_tune.py --apply             # aplica sugestoes no config.py
    python auto_tune.py --check-consistency # so verifica consistencia dos parametros

Filosofia:
    - Nao roda full_analysis.py para cada combinacao (muito lento)
    - Usa os relatorios existentes (ANALYSIS.md, LIQUIDITY_SWEEP.md, WALK_FORWARD.md)
      para basear recomendacoes
    - So atualiza config.py se encontrar inconsistencias ou melhorias claras
"""
import sys
import json
import re
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
ENGINE_DIR = PROJECT_ROOT / "engine"
REPORTS_DIR = PROJECT_ROOT / "reports"
CONFIG_PATH = ENGINE_DIR / "config.py"
TUNE_LOG = REPORTS_DIR / "TUNE_LOG.jsonl"
TUNE_RESULT_PATH = REPORTS_DIR / "TUNE_RESULT.json"

sys.path.insert(0, str(PROJECT_ROOT))


# ═════════════════════════════ LEITURA DE RELATORIOS ═════════════════════════════

def read_report(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def extract_analysis_metrics() -> dict:
    """Extrai metricas do ANALYSIS.md para basear recomendacoes."""
    text = read_report(REPORTS_DIR / "ANALYSIS.md")
    if not text:
        return {}

    metrics = {}
    m = re.search(r'Max DD:\s*([-\d.]+)%', text)
    if m:
        metrics["max_dd"] = float(m.group(1))

    m = re.search(r'Sharpe:\s*([\-\d.]+)', text)
    if m:
        metrics["sharpe"] = float(m.group(1))

    m = re.search(r'Win Rate:\s*([\d.]+)%', text)
    if m:
        metrics["win_rate"] = float(m.group(1))

    # P&L by regime
    if "risk_on" in text and "63.6%" in text:
        metrics["risk_on_profitable"] = True
    if "risk_off" in text and "53.8%" in text:
        metrics["risk_off_weak"] = True
    if "crisis" in text:
        m2 = re.search(r'crisis.*?pnl_total.*?\$([-\d.]+)', text)
        if m2:
            metrics["crisis_pnl"] = float(m2.group(1))

    # Por sessaoo - Tokyo performance
    m = re.search(r'Tokyo.*?\\$([\d.]+).*?Win.*?([\d.]+)%', text)
    if m:
        metrics["tokyo_pnl"] = float(m.group(1))
        metrics["tokyo_win_rate"] = float(m.group(2))

    return metrics


def check_config_consistency() -> list[dict]:
    """Verifica inconsistencias no config.py. Retorna lista de (param, problema, sugestao)."""
    issues = []
    try:
        import importlib
        import engine.config as C
        importlib.reload(C)

        # 1. TOTAL_RISK_CAP_PCT vs RISK_OVERRIDE_PCT
        for sym, override in C.RISK_OVERRIDE_PCT.items():
            if override > C.TOTAL_RISK_CAP_PCT:
                issues.append({
                    "param": f"RISK_OVERRIDE_PCT['{sym}']",
                    "current": override,
                    "suggested": C.TOTAL_RISK_CAP_PCT,
                    "reason": f"Override ({override}%) excede Total Cap ({C.TOTAL_RISK_CAP_PCT}%). Override deve ser <= Total Cap."
                })

        # 2. SESSION_FILTER_ALLOW vs SYMBOLS (Sydney filtrada?)
        if "Sydney" in C.SESSION_FILTER_ALLOW:
            issues.append({
                "param": "SESSION_FILTER_ALLOW",
                "current": C.SESSION_FILTER_ALLOW,
                "suggested": [s for s in C.SESSION_FILTER_ALLOW if s != "Sydney"],
                "reason": "Sydney tem pior performance. Remover Sydney do filtro de sessoes."
            })

        # 3. Regime risk_off exposure scale
        if C.EXPOSURE_SCALE.get("risk_off", 0.3) > 0.5:
            issues.append({
                "param": "EXPOSURE_SCALE['risk_off']",
                "current": C.EXPOSURE_SCALE.get("risk_off"),
                "suggested": 0.3,
                "reason": "Risk_off mal empata ($0.17/trade). Exposicao maxima de 30%."
            })

        # 4. risk_off stop mais largo que o normal?
        if C.ATR_STOP_MULT_BY_REGIME.get("risk_off", 1.0) > C.ATR_STOP_MULT_BY_REGIME.get("normal", 1.5):
            issues.append({
                "param": "ATR_STOP_MULT_BY_REGIME['risk_off']",
                "current": C.ATR_STOP_MULT_BY_REGIME.get("risk_off"),
                "suggested": C.ATR_STOP_MULT_BY_REGIME.get("normal", 1.5) * 0.67,
                "reason": "Risk_off precisa de stop MAIS APERTADO que o normal, nao mais largo."
            })

        # 5. MOMENTUM_MIN_ABS_R muito baixo?
        if C.MOMENTUM_MIN_ABS_R < 0.01:
            issues.append({
                "param": "MOMENTUM_MIN_ABS_R",
                "current": C.MOMENTUM_MIN_ABS_R,
                "suggested": 0.01,
                "reason": f"Threshold ({C.MOMENTUM_MIN_ABS_R}) muito baixo pode gerar sinais fracos. Minimo 0.01 (1%)."
            })

        # 6. COOLDOWN_BARS
        if C.COOLDOWN_BARS < 6:
            issues.append({
                "param": "COOLDOWN_BARS",
                "current": C.COOLDOWN_BARS,
                "suggested": 12,
                "reason": f"Cooldown de {C.COOLDOWN_BARS*4}h muito curto. Risco de re-entrada emocional apos SL."
            })

        # 7. MAX_LOSS_STREAK
        if C.MAX_LOSS_STREAK > 6:
            issues.append({
                "param": "MAX_LOSS_STREAK",
                "current": C.MAX_LOSS_STREAK,
                "suggested": 6,
                "reason": f"Max loss streak ({C.MAX_LOSS_STREAK}) muito alto. 6 perdas consecutivas = 1% probabilidade com WR 41%."
            })

        # 8. Regime risk_on risk_pct
        if C.RISK_PCT_BY_REGIME.get("risk_on", 8.0) > 10.0:
            issues.append({
                "param": "RISK_PCT_BY_REGIME['risk_on']",
                "current": C.RISK_PCT_BY_REGIME.get("risk_on"),
                "suggested": 8.0,
                "reason": "Risk_on > 10% excessivo para conta de $410. Manter em 8%."
            })

    except Exception as e:
        print(f"[AVISO] Erro lendo config.py: {e}")

    return issues


# ═════════════════════════════ ATUALIZACAO DO CONFIG.PY ═════════════════════════════

def update_config(filepath: Path, param_path: str, new_value) -> bool:
    """Atualiza config.py com regex. Suporta VARIAVEL e DICT['key']."""
    if not filepath.exists():
        return False

    content = filepath.read_text(encoding="utf-8")

    # Formata valor
    val_str = _format_value(new_value)

    # Determina se e dict key ou variavel direta
    m = re.match(r'(\w+)\[\'?(\w+)\'?\]', param_path)
    if m:
        # E um dict: precisa encontrar e substituir a linha
        dict_name = m.group(1)
        key = m.group(2)
        # Encontra a linha do dict
        in_dict = False
        new_lines = []
        for line in content.splitlines():
            if line.strip().startswith(dict_name) and '=' in line:
                in_dict = True
            if in_dict and line.strip().endswith('}'):
                # Substitui o valor da chave
                line = re.sub(
                    rf"['\"]?{re.escape(key)}['\"]?\s*:\s*[^,}}]+",
                    f"'{key}': {val_str}",
                    line
                )
                in_dict = False
            new_lines.append(line)
        new_content = "\n".join(new_lines)
    else:
        # Variavel direta
        pattern = rf'^{re.escape(param_path)}\s*=\s*.+$'
        replacement = f'{param_path} = {val_str}'
        new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

    if new_content == content:
        print(f"  [AVISO] Nao foi possivel atualizar {param_path}")
        return False

    filepath.write_text(new_content, encoding="utf-8")
    print(f"  [OK] {param_path} = {val_str}")
    return True


def _format_value(val) -> str:
    if isinstance(val, str):
        return f"'{val}'"
    elif isinstance(val, bool):
        return "True" if val else "False"
    elif isinstance(val, float):
        return f"{val}"
    elif isinstance(val, int):
        return str(val)
    elif isinstance(val, list):
        items = ", ".join(f"'{x}'" if isinstance(x, str) else str(x) for x in val)
        return "[" + items + "]"
    elif isinstance(val, dict):
        items = ", ".join(f"'{k}': {v}" if isinstance(k, str) else f"{k}: {v}"
                          for k, v in val.items())
        return "{" + items + "}"
    return str(val)


# ═════════════════════════════ MAIN ═════════════════════════════

def main():
    args = sys.argv[1:]
    apply_mode = "--apply" in args
    check_only = "--check-consistency" in args

    print("=" * 60)
    print("  WEALTH ENGINE - ANALISE DE PARAMETROS")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Modo: {'APLICAR' if apply_mode else 'APENAS ANALISAR'}")
    print("=" * 60)

    # Passo 1: Ler metricas dos relatorios
    print("\n[1/3] Lendo relatorios de performance...")
    analysis = extract_analysis_metrics()
    if analysis:
        print(f"   Analysis.md encontrado:")
        if "sharpe" in analysis:
            print(f"     Sharpe: {analysis['sharpe']:.2f}")
        if "max_dd" in analysis:
            print(f"     Max DD: {analysis['max_dd']:.1f}%")
        if "win_rate" in analysis:
            print(f"     Win Rate: {analysis['win_rate']:.1f}%")
        if "tokyo_pnl" in analysis:
            print(f"     Tokyo P&L: ${analysis['tokyo_pnl']:.2f}")
            print(f"     Tokyo Win Rate: {analysis['tokyo_win_rate']:.1f}%")
    else:
        print("   [AVISO] Nenhum relatorio de analise encontrado.")

    # Verifica relatorios de sweep
    liquidity_report = read_report(REPORTS_DIR / "LIQUIDITY_SWEEP.md")
    if "0.5%" in liquidity_report and "10.0%" in liquidity_report:
        print("   LIQUIDITY_SWEEP.md: Parametros DXY=0.5%, VIX=10.0% disponiveis")
    walk_forward = read_report(REPORTS_DIR / "WALK_FORWARD.md")
    if "PARCIALMENTE ROBUSTO" in walk_forward:
        print("   WALK_FORWARD.md: Walk-forward disponivel (parametros parcialmente robustos)")

    # Passo 2: Verificar consistencia do config.py
    print("\n[2/3] Verificando consistencia dos parametros...")
    issues = check_config_consistency()

    if not issues:
        print("   [OK] Nenhuma inconsistencia encontrada.")
    else:
        print(f"   [{len(issues)}] inconsistencias encontradas:")
        for i, issue in enumerate(issues, 1):
            print(f"     {i}. {issue['param']}: {issue['current']} -> {issue['suggested']}")
            print(f"        Motivo: {issue['reason']}")

    # Passo 3: Aplicar se solicitado
    print("\n[3/3] Gerando relatorio...")

    # Salva resultado
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "analysis_metrics": analysis,
        "issues_found": issues,
        "auto_applied": apply_mode,
    }

    changes_made = []
    if apply_mode and issues:
        for issue in issues:
            success = update_config(CONFIG_PATH, issue["param"], issue["suggested"])
            if success:
                changes_made.append(issue["param"])
                issue["applied"] = True
            else:
                issue["applied"] = False

        if changes_made:
            print(f"\n   ==> {len(changes_made)} alteracoes aplicadas: {', '.join(changes_made)}")
            result["config_updated"] = True
            result["changes_applied"] = changes_made
        else:
            print("\n   Nenhuma alteracao aplicada.")
            result["config_updated"] = False

    # Salva resultado
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    TUNE_RESULT_PATH.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    # Log
    with open(TUNE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")

    print(f"\n   Resultado salvo: {TUNE_RESULT_PATH}")

    if issues and not apply_mode:
        print("\n" + "=" * 60)
        print("  SUGESTOES DISPONIVEIS (use --apply para aplicar)")
        print("=" * 60)
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue['param']}: {issue['current']} -> {issue['suggested']}")
            print(f"     Motivo: {issue['reason']}")

    if not issues:
        print("\n[OK] Parametros atuais estao consistentes. Nenhum ajuste necessario.")

    print(f"\n{'=' * 60}")
    print("  ANALISE CONCLUIDA")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
