"""bot.manager — Gerenciador central do Wealth Engine v4.

P0-B: Entry point único que substitui 7 scripts .bat/.ps1/.vbs legados.
Suporta: Windows Service (NSSM), PID lock, heartbeat, graceful shutdown,
healthcheck HTTP, logs rotacionados (JSONL).

Uso:
    python bot/manager.py start          # inicia executor + dashboard (background)
    python bot/manager.py stop           # para graciosamente (SIGTERM)
    python bot/manager.py restart
    python bot/manager.py status         # JSON: pid, uptime, last_cycle, heartbeat
    python bot/manager.py health         # HTTP 200/503 + JSON (para monitoração)
    python bot/manager.py install        # registra Windows Service via NSSM
    python bot/manager.py uninstall      # remove Windows Service
"""
from __future__ import annotations

import argparse
import atexit
import json
import logging
import os
import signal
import sys
import time
import threading
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Paths ──────────────────────────────────────────────────────────────
BOT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BOT_DIR.parent
RUN_DIR = BOT_DIR / "run"
RUN_DIR.mkdir(parents=True, exist_ok=True)

PID_FILE = RUN_DIR / "wealth.pid"
HEARTBEAT_FILE = RUN_DIR / "heartbeat.json"
STATE_FILE = BOT_DIR / "bot_state.json"
LOG_FILE = RUN_DIR / "wealth-manager.log"
EXECUTOR_LOG = RUN_DIR / "executor.log"

# Importar módulos core (deve funcionar sem MT5)
sys.path.insert(0, str(PROJECT_ROOT))

# ── Logging estruturado ────────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            base["exc"] = self.formatException(record.exc_info)
        for k, v in record.__dict__.items():
            if k not in {"name", "msg", "args", "created", "filename", "funcName",
                         "levelname", "levelno", "lineno", "module", "msecs",
                         "message", "msecs", "name", "pathname", "process",
                         "processName", "relativeCreated", "thread", "threadName",
                         "exc_info", "exc_text", "stack_info"}:
                base[k] = v
        return json.dumps(base, ensure_ascii=False)


def setup_logging() -> logging.Logger:
    """Configura logging para arquivo rotacionado + stdout."""
    logger = logging.getLogger("wealth.manager")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    # File handler com rotação (10MB, 5 backups)
    from logging.handlers import RotatingFileHandler
    fh = RotatingFileHandler(LOG_FILE, maxBytes=10_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(JsonFormatter())
    logger.addHandler(fh)

    # Stdout (para systemd/journal se rodar como service)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(JsonFormatter())
    logger.addHandler(sh)

    return logger


logger = setup_logging()


# ── Helpers ────────────────────────────────────────────────────────────
def read_pid() -> Optional[int]:
    if PID_FILE.exists():
        try:
            return int(PID_FILE.read_text().strip())
        except Exception:
            pass
    return None


def write_pid(pid: int) -> None:
    PID_FILE.write_text(str(pid))


def remove_pid() -> None:
    if PID_FILE.exists():
        PID_FILE.unlink(missing_ok=True)


def is_process_alive(pid: int) -> bool:
    """Verifica se processo PID está vivo (Windows: tasklist)."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=5
        )
        return str(pid) in result.stdout
    except Exception:
        return False


def write_heartbeat(cycle: int = 0, extra: dict | None = None,
                    executor_pid: int | None = None,
                    dashboard_pid: int | None = None) -> None:
    """Atualiza heartbeat.json (lido pelo cron do Hermes)."""
    data = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "cycle": cycle,
        "alive": True,
    }
    if executor_pid:
        data["executor_pid"] = executor_pid
    if dashboard_pid:
        data["dashboard_pid"] = dashboard_pid
    if extra:
        data.update(extra)
    tmp = HEARTBEAT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(HEARTBEAT_FILE)


def read_heartbeat() -> dict:
    if HEARTBEAT_FILE.exists():
        try:
            return json.loads(HEARTBEAT_FILE.read_text())
        except Exception:
            pass
    return {}


# ── Process management ─────────────────────────────────────────────────
class ProcessManager:
    """Gerencia subprocessos do executor e dashboard."""

    def __init__(self) -> None:
        self._procs: dict[str, subprocess.Popen] = {}
        self._stop_event = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._cycle = 0

    def start(self, components: list[str] = None) -> bool:
        """Inicia componentes solicitados."""
        if components is None:
            components = ["executor"]

        # Verifica lock
        pid = read_pid()
        if pid and is_process_alive(pid):
            logger.error("Já existe instância rodando (PID %d)", pid)
            return False

        write_pid(os.getpid())
        atexit.register(remove_pid)

        # Inicia heartbeat thread
        self._stop_event.clear()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

        # Executor
        if "executor" in components:
            self._spawn_executor()

        # Dashboard (opcional)
        if "dashboard" in components:
            self._spawn_dashboard()

        logger.info("Manager started: components=%s", components)
        return True

    def _spawn_executor(self) -> None:
            """Roda executor.py em subprocesso."""
            python = sys.executable
            cmd = [python, "-u", "bot/executor.py"]
            env = os.environ.copy()
            env["PYTHONPATH"] = str(PROJECT_ROOT) + ";" + env.get("PYTHONPATH", "")

            # Modo binário + errors=replace para evitar UnicodeDecodeError em ANSI/binary output
            proc = subprocess.Popen(
                cmd,
                cwd=str(PROJECT_ROOT),
                stdout=open(EXECUTOR_LOG, "ab", buffering=0),  # unbuffered binary append
                stderr=subprocess.STDOUT,
                env=env,
            )
            self._procs["executor"] = proc
            logger.info("Executor spawned: PID=%d", proc.pid)

    def _spawn_dashboard(self) -> None:
        """Roda wealth_dashboard.py via streamlit."""
        python = sys.executable
        cmd = [
            python, "-m", "streamlit", "run", "wealth_dashboard.py",
            "--server.address=127.0.0.1", "--server.port=8501",
            "--server.headless=true", "--browser.gatherUsageStats=false",
        ]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT) + ";" + env.get("PYTHONPATH", "")
        # Passa senha do dashboard via env (Streamlit lê STREAMLIT_SERVER_PASSWORD)
        dashboard_pwd = os.environ.get("DASHBOARD_PASSWORD")
        if dashboard_pwd:
            env["STREAMLIT_SERVER_PASSWORD"] = dashboard_pwd

        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",  # handle encoding issues
        )
        self._procs["dashboard"] = proc
        logger.info("Dashboard spawned: PID=%d", proc.pid)

    def _heartbeat_loop(self) -> None:
        """Atualiza heartbeat.json a cada 60s."""
        while not self._stop_event.is_set():
            self._cycle += 1
            write_heartbeat(
                cycle=self._cycle,
                executor_pid=self._procs.get("executor").pid if self._procs.get("executor") else None,
                dashboard_pid=self._procs.get("dashboard").pid if self._procs.get("dashboard") else None,
                extra={"components": list(self._procs.keys())}
            )
            # Loga status dos filhos
            for name, proc in self._procs.items():
                if proc.poll() is not None:
                    logger.warning("Component %s exited with code %d", name, proc.returncode)
            time.sleep(60)

    def stop(self, timeout: int = 30) -> None:
        """Para todos os filhos graciosamente (SIGTERM)."""
        logger.info("Stopping components...")
        self._stop_event.set()

        # Pega PIDs do heartbeat (funciona cross-process)
        hb = read_heartbeat()
        executor_pid = hb.get("executor_pid")
        dashboard_pid = hb.get("dashboard_pid")

        for name, pid in [("executor", executor_pid), ("dashboard", dashboard_pid)]:
            if pid and is_process_alive(pid):
                logger.info("Sending SIGTERM to %s (PID=%d)", name, pid)
                try:
                    subprocess.run(["taskkill", "/PID", str(pid), "/T"], check=False, capture_output=True)
                except Exception as exc:
                    logger.warning("terminate %s failed: %s", name, exc)

        # Aguarda com timeout
        deadline = time.time() + timeout
        for name, pid in [("executor", executor_pid), ("dashboard", dashboard_pid)]:
            while pid and is_process_alive(pid) and time.time() < deadline:
                time.sleep(0.5)
            if pid and is_process_alive(pid):
                logger.warning("Force killing %s (PID=%d)", name, pid)
                try:
                    subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], check=False, capture_output=True)
                except Exception:
                    pass

        self._procs.clear()
        remove_pid()
        write_heartbeat(cycle=0, executor_pid=None, dashboard_pid=None, extra={"alive": False})
        logger.info("Manager stopped")

    def status(self) -> dict:
        """Retorna status JSON."""
        hb = read_heartbeat()
        pid = read_pid()
        alive = pid and is_process_alive(pid)
        executor_pid = hb.get("executor_pid")
        dashboard_pid = hb.get("dashboard_pid")
        return {
            "manager": {
                "pid": pid,
                "alive": alive,
                "uptime_seconds": time.time() - (PID_FILE.stat().st_ctime if PID_FILE.exists() else time.time()),
            },
            "heartbeat": hb,
            "children": {
                "executor": {
                    "pid": executor_pid,
                    "running": executor_pid and is_process_alive(executor_pid),
                },
                "dashboard": {
                    "pid": dashboard_pid,
                    "running": dashboard_pid and is_process_alive(dashboard_pid),
                },
            },
        }

    def health(self) -> tuple[int, dict]:
        """Retorna (HTTP_status, JSON) para healthcheck."""
        st = self.status()
        # Healthy se manager vivo E executor rodando
        healthy = st["manager"]["alive"] and st["children"].get("executor", {}).get("running", False)
        return (200 if healthy else 503, st)


# ── Windows Service (NSSM) ─────────────────────────────────────────────
NSSM_URL = "https://nssm.cc/release/nssm-2.24.zip"
NSSM_EXE = BOT_DIR / "nssm.exe"
SERVICE_NAME = "WealthEngine"


def ensure_nssm() -> bool:
    """Baixa nssm.exe se não existir."""
    if NSSM_EXE.exists():
        return True
    try:
        import urllib.request
        import zipfile
        import io
        logger.info("Baixando NSSM...")
        with urllib.request.urlopen(NSSM_URL, timeout=30) as resp:
            data = resp.read()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            # nssm-2.24/win64/nssm.exe
            for name in zf.namelist():
                if name.endswith("nssm.exe"):
                    zf.extract(name, RUN_DIR)
                    extracted = RUN_DIR / name
                    extracted.rename(NSSM_EXE)
                    break
        logger.info("NSSM instalado em %s", NSSM_EXE)
        return True
    except Exception as exc:
        logger.error("Falha ao baixar NSSM: %s", exc)
        return False


def service_install() -> bool:
    """Registra serviço Windows via NSSM."""
    if not ensure_nssm():
        return False

    python = sys.executable
    app_dir = str(PROJECT_ROOT)
    cmd = [str(NSSM_EXE), "install", SERVICE_NAME, python, "bot/manager.py", "start"]
    try:
        subprocess.run(cmd, cwd=app_dir, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        logger.error("nssm install falhou: %s", exc.stderr)
        return False

    # Configurações recomendadas
    configs = [
        ["set", SERVICE_NAME, "AppDirectory", app_dir],
        ["set", SERVICE_NAME, "AppStdout", str(RUN_DIR / "service.log")],
        ["set", SERVICE_NAME, "AppStderr", str(RUN_DIR / "service.log")],
        ["set", SERVICE_NAME, "AppRotateFiles", "1"],
        ["set", SERVICE_NAME, "AppRotateOnline", "1"],
        ["set", SERVICE_NAME, "AppRotateSeconds", "86400"],
        ["set", SERVICE_NAME, "AppRotateBytes", "10485760"],
        ["set", SERVICE_NAME, "Start", "SERVICE_AUTO_START"],
        ["set", SERVICE_NAME, "Description", "Wealth Engine v4 Trading Bot"],
    ]
    for cfg in configs:
        subprocess.run([str(NSSM_EXE)] + cfg, check=False, capture_output=True)

    logger.info("Serviço %s instalado", SERVICE_NAME)
    return True


def service_uninstall() -> bool:
    if not NSSM_EXE.exists():
        logger.warning("NSSM não encontrado — serviço pode não existir")
        return True
    try:
        subprocess.run([str(NSSM_EXE), "stop", SERVICE_NAME], check=False, capture_output=True)
        subprocess.run([str(NSSM_EXE), "remove", SERVICE_NAME, "confirm"], check=True, capture_output=True)
        logger.info("Serviço %s removido", SERVICE_NAME)
        return True
    except Exception as exc:
        logger.error("Falha ao remover serviço: %s", exc)
        return False


def service_start() -> bool:
    try:
        subprocess.run([str(NSSM_EXE), "start", SERVICE_NAME], check=True, capture_output=True)
        return True
    except Exception as exc:
        logger.error("Falha ao iniciar serviço: %s", exc)
        return False


# ── HTTP Healthcheck server ────────────────────────────────────────────
def run_health_server(port: int = 9090, stop_event: threading.Event = None) -> None:
    """Servidor HTTP mínimo para /health (stdlib only)."""
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                code, body = manager.health()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format, *args):
            logger.debug("Health HTTP: %s", format % args)

    server = HTTPServer(("127.0.0.1", port), HealthHandler)
    logger.info("Healthcheck server listening on 127.0.0.1:%d", port)
    while not (stop_event and stop_event.is_set()):
        server.handle_request()


# ── CLI ────────────────────────────────────────────────────────────────
manager = ProcessManager()


def main() -> int:
    parser = argparse.ArgumentParser(description="Wealth Engine Manager")
    parser.add_argument("command", choices=[
        "start", "stop", "restart", "status", "health",
        "install", "uninstall", "service-start", "service-stop", "service-restart",
    ])
    parser.add_argument("--components", default="executor",
                        help="Lista separada por vírgula: executor,dashboard")
    args = parser.parse_args()

    components = [c.strip() for c in args.components.split(",") if c.strip()]

    if args.command == "start":
        # Inicia health server em thread separada
        health_stop = threading.Event()
        health_thread = threading.Thread(target=run_health_server, args=(9090, health_stop), daemon=True)
        health_thread.start()

        ok = manager.start(components)
        if not ok:
            health_stop.set()
            return 1

        # Loop principal: espera SIGTERM/Ctrl+C
        def handle_sigterm(*_):
            logger.info("SIGTERM recebido")
            health_stop.set()
            manager.stop()
            sys.exit(0)

        signal.signal(signal.SIGTERM, handle_sigterm)
        signal.signal(signal.SIGINT, handle_sigterm)

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            handle_sigterm()
        return 0

    elif args.command == "stop":
        pid = read_pid()
        if pid and is_process_alive(pid):
            # Envia Ctrl+C via GenerateConsoleCtrlEvent não funciona bem cross-process
            # Usa taskkill /PID (SIGTERM equivalente)
            subprocess.run(["taskkill", "/PID", str(pid), "/T"], check=False)
            time.sleep(2)
            if is_process_alive(pid):
                subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], check=False)
            logger.info("Stop signal sent to PID %d", pid)
        else:
            logger.warning("Nenhum manager rodando (PID file: %s)", PID_FILE)
        return 0

    elif args.command == "restart":
        # Para + inicia
        main_stop_args = argparse.Namespace(command="stop", components="")
        main(main_stop_args)  # não retorna se falhar
        time.sleep(2)
        return main()

    elif args.command == "status":
        st = manager.status()
        print(json.dumps(st, indent=2, default=str))
        return 0

    elif args.command == "health":
        code, body = manager.health()
        print(json.dumps(body, indent=2, default=str))
        return 0 if code == 200 else 1

    elif args.command == "install":
        if service_install():
            print(f"Serviço {SERVICE_NAME} instalado. Use 'service-start' para iniciar.")
            return 0
        return 1

    elif args.command == "uninstall":
        if service_uninstall():
            print(f"Serviço {SERVICE_NAME} removido.")
            return 0
        return 1

    elif args.command == "service-start":
        if service_start():
            print("Serviço iniciado.")
            return 0
        return 1

    elif args.command == "service-stop":
        subprocess.run([str(NSSM_EXE), "stop", SERVICE_NAME], check=False)
        return 0

    elif args.command == "service-restart":
        subprocess.run([str(NSSM_EXE), "restart", SERVICE_NAME], check=False)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())