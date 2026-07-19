#!/usr/bin/env python3
"""scripts/finalize_services.py — Configuração FINAL serviços + Task Scheduler.

Rode como ADMINISTRADOR (PowerShell Admin).
"""
from __future__ import annotations

import subprocess
import sys
import time


def run(cmd: list[str], check: bool = False) -> int:
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and result.returncode != 0:
        print(f"FALHA: {cmd} → {result.stderr[:200]}")
    return result.returncode


def main():
    PROJECT = "C:\\Users\\lucas\\Wealth_Engine"
    VENV_PYTHON = f"{PROJECT}\\venv\\Scripts\\python.exe"
    NSSM = "C:\\Program Files\\nssm\\nssm.exe"

    print("=" * 60)
    print("WEALTH ENGINE v4 — CONFIGURAÇÃO FINAL")
    print("=" * 60)

    # ──────────────────────────────────────────────────────────────
    # 1. Remover Bot do NSSM (não funciona como SYSTEM - MT5 IPC fail)
    # ──────────────────────────────────────────────────────────────
    print("\n[1/6] Removendo Bot do NSSM (MT5 precisa de usuário Lucas)...")
    run(["sc", "stop", "WealthEngine_Bot"])
    time.sleep(2)
    run(["sc", "delete", "WealthEngine_Bot"])
    print("  ✅ Bot removido do NSSM")

    # ──────────────────────────────────────────────────────────────
    # 2. Remover MT5 Task antiga e criar NOVA como usuário Lucas
    # ──────────────────────────────────────────────────────────────
    print("\n[2/6] Criando Task Scheduler para Bot (usuário Lucas)...")
    run(["schtasks", "/Delete", "/TN", "WealthEngine_Bot_Startup", "/F"])

    BAT = f"{PROJECT}\\scripts\\start_bot.bat"
    run([
        "schtasks", "/Create",
        "/TN", "WealthEngine_Bot_Startup",
        "/TR", f'"{BAT}"',
        "/SC", "ONLOGON",
        "/RL", "HIGHEST",
        "/F",
    ])
    print("  ✅ Task Bot criada (executa como Lucas no logon)")

    # ──────────────────────────────────────────────────────────────
    # 3. Task MT5 (abre terminal Exness antes do Bot)
    # ──────────────────────────────────────────────────────────────
    print("\n[3/6] Criando Task Scheduler para MT5 Exness...")
    run(["schtasks", "/Delete", "/TN", "WealthEngine_MT5_Startup", "/F"])

    MT5_EXE = "C:\\Program Files\\MetaTrader 5 EXNESS\\terminal64.exe"
    run([
        "schtasks", "/Create",
        "/TN", "WealthEngine_MT5_Startup",
        "/TR", f'"{MT5_EXE}"',
        "/SC", "ONLOGON",
        "/RL", "HIGHEST",
        "/F",
    ])
    print("  ✅ Task MT5 criada")

    # ──────────────────────────────────────────────────────────────
    # 4. Recriar Dashboard + API no NSSM (funcionam como SYSTEM)
    # ──────────────────────────────────────────────────────────────
    print("\n[4/6] Configurando Dashboard NSSM...")
    run(["sc", "stop", "WealthEngine_Dashboard"])
    time.sleep(1)
    run(["sc", "delete", "WealthEngine_Dashboard"])

    run([
        NSSM, "install", "WealthEngine_Dashboard",
        VENV_PYTHON,
        "-m streamlit run wealth_dashboard.py --server.address=127.0.0.1 --server.port=8501 --server.headless=true",
    ], check=True)
    run([NSSM, "set", "WealthEngine_Dashboard", "AppDirectory", PROJECT])
    run([NSSM, "set", "WealthEngine_Dashboard", "AppStdout", f"{PROJECT}\\bot\\run\\dashboard.log"])
    run([NSSM, "set", "WealthEngine_Dashboard", "AppStderr", f"{PROJECT}\\bot\\run\\dashboard.log"])
    run([NSSM, "set", "WealthEngine_Dashboard", "AppRotateFiles", "1"])
    run([NSSM, "set", "WealthEngine_Dashboard", "AppRotateOnline", "1"])
    run([NSSM, "set", "WealthEngine_Dashboard", "AppRotateSeconds", "86400"])
    run([NSSM, "set", "WealthEngine_Dashboard", "Start", "SERVICE_AUTO_START"])
    run(["sc", "failure", "WealthEngine_Dashboard", "reset=86400", "actions=restart/5000/restart/10000/restart/30000"])
    print("  ✅ Dashboard NSSM OK")

    print("\n[5/6] Configurando API NSSM...")
    run(["sc", "stop", "WealthEngine_API"])
    time.sleep(1)
    run(["sc", "delete", "WealthEngine_API"])

    run([
        NSSM, "install", "WealthEngine_API",
        VENV_PYTHON,
        "-m uvicorn bot.api.server:app --host 127.0.0.1 --port 8000",
    ], check=True)
    run([NSSM, "set", "WealthEngine_API", "AppDirectory", PROJECT])
    run([NSSM, "set", "WealthEngine_API", "AppStdout", f"{PROJECT}\\bot\\run\\api.log"])
    run([NSSM, "set", "WealthEngine_API", "AppStderr", f"{PROJECT}\\bot\\run\\api.log"])
    run([NSSM, "set", "WealthEngine_API", "AppRotateFiles", "1"])
    run([NSSM, "set", "WealthEngine_API", "AppRotateOnline", "1"])
    run([NSSM, "set", "WealthEngine_API", "AppRotateSeconds", "86400"])
    run([NSSM, "set", "WealthEngine_API", "Start", "SERVICE_AUTO_START"])
    run(["sc", "failure", "WealthEngine_API", "reset=86400", "actions=restart/5000/restart/10000/restart/30000"])
    print("  ✅ API NSSM OK")

    # ──────────────────────────────────────────────────────────────
    # 6. Reiniciar serviços
    # ──────────────────────────────────────────────────────────────
    print("\n[6/6] Reiniciando serviços...")

    run(["sc", "start", "WealthEngine_Ollama"])
    time.sleep(10)
    run(["sc", "start", "WealthEngine_Dashboard"])
    run(["sc", "start", "WealthEngine_API"])

    print("\n" + "=" * 60)
    print("CONFIGURAÇÃO FINAL CONCLUÍDA")
    print("=" * 60)
    print("")
    print("Serviços configurados:")
    print("  1. WealthEngine_Ollama       — NSSM SERVICE_AUTO_START")
    print("  2. WealthEngine_Dashboard    — NSSM SERVICE_AUTO_START")
    print("  3. WealthEngine_API          — NSSM SERVICE_AUTO_START")
    print("  4. WealthEngine_MT5_Startup  — Task Scheduler (logon)")
    print("  5. WealthEngine_Bot_Startup  — Task Scheduler (logon)")
    print("  6. Hermes Cron               — 0 3 * * *")
    print("")
    print("Ordem de boot:")
    print("  Ollama (service) → Dashboard (service) → API (service)")
    print("  Logon → MT5 abre → 15s → Bot start_bot.bat")
    print("")
    print("Para testar Bot AGORA:")
    print(f"  {PROJECT}\\scripts\\start_bot.bat")
    print("")
    print("Para reboot completo: reinicie o PC")
    print("=" * 60)


if __name__ == "__main__":
    main()