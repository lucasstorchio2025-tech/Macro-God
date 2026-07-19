# Wealth_Engine v4 — Briefing de Execução (Híbrido Hermes + Serviço Windows)

> **Role:** engenheiro sênior com acesso读写 ao repositório. Você NÃO está aqui para
> "planejar" nem "descrever" — está aqui para editar arquivos, rodar testes e
> commitar trabalho verificável. Se um passo não termina num `git diff`, ele não
> conta como feito.
>
> **Stack target (decidida, não negociar):**
> - **Bot de trading** roda como **Windows Service via NSSM** — processo próprio, 24/7, sem lockstep ao Hermes.
> - **Auto-aperfeiçoamento** roda como **cron job do Hermes Agent** (model glm-5.2). Lê logs + state, propõe ajustes, entrega no Telegram.
> - **Interface humana** = **Telegram** (bot nativo já no `.env`). Dashboard web é P2, opcional, read-only.
>
> Credenciais já em `C:\Users\lucas\Wealth_Engine\.env`: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `EXNESS_LOGIN/PASSWORD/SERVER`, `FINNHUB_API_KEY`, `FRED_API_KEY`.
> Python 3.11.15. Sem Docker. Windows nativo (não WSL).

---

## 0) Diagnóstico baseado no estado ATUAL do repo (não em suposições)

Lido em 18/jul/2026:

| Fato | Evidência |
|---|---|
| O `executor.py` é monolito de **1078 linhas** misturando 8 responsabilidades | `wc -l bot/executor.py` |
| `25` blocos `try/except` no executor — vários `except Exception: pass` silenciosos | `grep -c "except.*:" bot/executor.py` |
| Globais duck-tape: `_AUTONOMOUS_AVAILABLE`, `_COMMANDER`, `TELEGRAM_BOT_TOKEN` | `bot/executor.py:80-85,111` |
| `auto_tune.py` (15KB) e `auto_improve.py` (23KB) **não são importados em nenhum lugar** | `grep -rn "auto_tune\|auto_improve" bot/ engine/` vazio |
| `autonomous_bridge.py` (139 ln) é uma casca; `commander.py` (604 ln), `autonomous_oracle.py` (658 ln), `self_evolution.py` (619 ln) existem mas **o executor chama commander via global reloading `_COMMANDER = get_commander()` dentro de `run_once`** — estado em disco em vez de instância viva | `bot/executor.py:665-688` |
| **`save_state` é a função mais perigosa do projeto**: lê-modifica-escreve sem lock; múltiplos callers (`run_once`, meta learner, commander) sobrescrevem campos uns dos outros | `bot/executor.py:168` |
| `pytest` **não está instalado** no venv do Hermes (o único Python ativo). "32 testes" é aspiração — não rodam | `python -m pytest` → No module named pytest |
| 7 scripts de startup (`abrir_dashboard.bat`, `start_all.bat`, `start_everything.ps1/.vbs`, etc.) **todos com path hardcoded** `C:\Users\lucas\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe` | `bot/*.bat` linha 1 |
| `bot/run/` (PID file, logs, lock) **não existe** — então não há guard contra dupla execução | `ls bot/run/` → missing |
| Dashboard (`wealth_dashboard.py`, 1020 ln Streamlit) faz `--server.address=0.0.0.0` **sem senha**. Qualquer um na LAN lê saldo/equity/trades | docstring do arquivo |
| Telegram hoje envia via `urllib` inline dentro de `notify()` (bot/executor.py:116) — sem retry, sem rate-limit, sem queue | linha 128 |
| `.env` carrega via `load_dotenv(Path.home() / ".hermes" / ".env")` **segundo** `load_dotenv(<project>/.env)`. Combinação de perfis Hermes + projeto é fonte constante de bug 401 MT5 | `bot/executor.py:62-63` |

---

## 1) ESCOPO POR FASE (P0 → P2) — cada item é um commit verificável

### P0-A — Extrair núcleo do monolito (sem refator total, sem reciclar behavior)

**Meta:** `bot/executor.py` ≤ 250 linhas (aixo entry point). Resto em `bot/core/`.

| Módulo novo | Migra de `executor.py` | Contrato público mínimo |
|---|---|---|
| `bot/core/state.py` — `StateManager` com `SafeFileStore` | `load_state`/`save_state` | `read() -> BotState`, `mutate(fn)`, `atomic_write()` |
| `bot/core/mt5_bridge.py` — `MT5Bridge` | `mt5_connect`, `check_max_positions`, `get_open_symbols` | `connect()`, `is_connected()`, `positions()`, `send(order)`, `close(ticket)` |
| `bot/core/risk.py` — `RiskManager` | `check_daily_weekly_dd`, `check_total_exposure`, `check_cooldown`, `check_regime_gate`, `check_macro_blockers` | `can_trade(ctx) -> RiskVerdict` |
| `bot/core/decision.py` — `DecisionEngine` | bloco TS-momentum + filtros em `run_once` (ln ~600-900) | `analyze(ctx) -> Signal \| None`, `decide(ctx) -> Order \| None` |
| `bot/core/execution.py` — `TradeExecutor` | `open_trade`, `close_trade`, `close_all_on_crisis`, `sync_orphan_closes` | `execute(signal) -> OrderResult`, `flatten_all() -> int` |

**Regras não-negociáveis (preservar behavior testado):**
- MANTER coeficiente/constantes de risk idênticos (5% risco, RR 2:1, daily_dd 8%, weekly_dd 15%) — não reescrever lógica, mover.
- MANTER uso do `BotConfig` existente em `engine/config.py`. Não inventar Pydantic paralelo.
- MANTER ordem dos filtros hard (1→9 no docstring) — usuário já perdeu $90 por bug de empilhamento.
- `StateManager` deve usar **escrita atômica** (`path.with_suffix(".tmp")` + `os.replace`) e **lock** via `fcntl`-equivalente Windows: `msvcrt.locking` ou mais simples, `filelock` library (adicionar `filelock>=3.13` ao requirements.txt).

**Critério de "feito":**
1. `python -c "from bot.core import state, risk, decision, execution, mt5_bridge"` roda sem erro
2. `bot/executor.py` importa e usa essas classes; seu `main_loop()` é o único conteúdo substantivo
3. `git diff bot/executor.py` mostra **remoção** de ~800 linhas
4. Smoke test: `python bot/executor.py --dry-run --once` ainda completa um ciclo sem crash

---

### P0-B — Launcher único + Windows Service (NSSM)

**Deleta:** `bot/abrir_dashboard.bat`, `bot/start_all.bat`, `bot/start_everything.ps1`, `bot/start_everything.vbs`, `bot/instalar_dashboard_startup.{ps1,vbs}`, `bot/instalar_startup_completo.ps1`, `bot/remover_startup.ps1`, `bot/watchdog_supervisor.bat`, `bot/run_executor.bat`, `bot/run_news.bat`, `bot/status.bat`, `bot/diagnostico.bat`, `scripts/run_bot.vbs`.

**Cria:**

**`bot/manager.py`** — entry-point único, sem hardcoded paths, sem UI:
```
python bot/manager.py start      → inicia executor + dashboard em background
python bot/manager.py stop       → graciosamente pára (SIGTERM via PID file)
python bot/manager.py restart
python bot/manager.py status    → JSON: pid, uptime, last_heartbeat, last_cycle
python bot/manager.py health    → HTTP 200/503 + JSON (pra healthcheck)
python bot/manager.py install   → registra Windows Service via NSSM (checa nssm.exe)
python bot/manager.py uninstall
```

Regras:
- `PID file` em `bot/run/wealth.pid` — se já existir E processo vivo, **não inicia segunda instância** (erro explícito).
- `bot/run/wealth.log` com `RotatingFileHandler(10MB, 5 backups)`. Logs em JSON estruturado (não texto livre).
- Heartbeat: a cada 60s, escreve `{"ts": ISO, "last_cycle": N, "alive": true}` em `bot/run/heartbeat.json`. O cron do Hermes (P2) lê isto pra detectar fallback.
- Graceful shutdown via `signal.SIGTERM` handler + `KeyboardInterrupt` que chama `executor.graceful_stop()` (fecha posições abertas? **NÃO** — em demo, deixa abertas; só para o loop e persiste state).
- Healthcheck em `localhost:9090/health` (módulo stdlib `http.server`, sem framework novo).

**`scripts/install_service.bat`** — invoca NSSM (checa se existe em `PATH`; se não, baixa URL fixa). NÃO atalho Startup (frágil). Usa `sys.executable` do Python que rodou o install, nunca path hardcoded.

**Critério de "feito":**
- `python bot/manager.py status` roda e mostra JSON mesmo com bot parado.
- Após `start`: `curl http://localhost:9090/health` retorna `{"status":"ok"}`.
- Após `stop`: `bot/run/wealth.pid` é removido.

---

### P0-C — Segurança & Persistência (não inventar features)

**Implementa:**

1. **`bot/core/state.py` — `SafeFileStore`** (escrita atômica + lock)
   - `tmp = path.with_suffix(".tmp")` → `json.dump` → `os.replace(tmp, path)` (atômico em NTFS).
   - `filelock` (lib nova) pra lock inter-processo (`with store.lock():`).
   - Detecta state corrupto: se `json.load` falhar, **não apaga** — renomeia pra `*.corrupt_<ts>` e começa state novo. Logging via Telegram alerta.
   - Schema validation via `pydantic` — `BotState` model com campos atuais do `bot_state.json` (não inventar campos).

2. **`.env` loading único** — em `bot/core/config.py`:
   - REMOVE a linha `load_dotenv(Path.home() / ".hermes" / ".env")` em `executor.py:62`.
   - Carrega SÓ `.env` do projeto. Variável `EXNESS_*` pertence ao projeto, não ao Hermes.
   - Cria `.env.example` com placeholders (não comitar `.env` real — já está no `.gitignore`? Verificar).

3. **`RateLimiter`** — bloqueia empilhamento de ciclos. Se `run_once` anterior ainda rodando, próximo tick pula. Implementação simples: `asyncio.Semaphore` ou `threading.Lock` + timestamp.

4. **Mata 5 `except Exception: pass` prioritários** — lista em `bot/executor.py:540,688,731,973,1040` (áreas de commander/order_send). Substitui por `logger.exception(...)` + retorna `CycleResult(error=...)`. NÃO generalizar pra "todos os 25" — escopo cirúrgico.

5. **Dashboard auth** (se Streamlit mantiver em P2): `--server.address=127.0.0.1` (default), senha via `.env` `DASHBOARD_PASSWORD`. Se ainda não tinha, NÃO expor `0.0.0.0` por padrão.

**Critério de "feito":**
- `Manager.status()` lê `bot_state.json` mesmo após "crash" simulado (introduzir JSON inválido, confirmar recovery).
- `bot_state.json` continua válido após 100 ciclos de `run_once` simulados.
- `grep -n "except.*pass" bot/executor.py` mostra drop dos 5 alvos.

---

### P0-D — Telegram bridge moderno (mantém backward compat)

**Cria `bot/core/notify.py`** — envolto em classe `TelegramNotifier`:
- Lê `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` do `.env` do projeto (via `bot.core.config`, não direto).
- `requests.post(.../sendMessage)` com **retry exponential backoff (3 tentativas, 2/4/8s)** e **timeout 10s**.
- Queue simples (lista in-memory) — se Telegram cai, acumula até 50 msgs, descarta acima (avisa no log).
- Níveis: `info | warn | alert | crisis` com emoji prefixado.
- **Não usar chattybot** — só o usuário (Lucas) recebe. Sem broadcast.
- Métodos:
  - `notify.trade_open(order)` — "🟢 BUY 0.05 XAUUSDm @ 2412.34 SL 2405 TP 2426"
  - `notify.trade_closed(result, pnl)` — "🔴 Closed +$23.45 (TP hit)"
  - `notify.crisis(reason)` — "🚨 CRISIS regime — flatten all"
  - `notify.heartbeat_dead(seconds)` — "⚠ Bot sem heartbeat há 600s"
  - `notify.dd_warning(pct, limit)` — "🟡 DD diário 45% do limite (3.6% / 8%)"

**Critério de "feito":**
- Substituir `notify()` inline em `executor.py:116` por `notifier.notify(msg, level=...)`.
- Teste smoke: rodar `python -c "from bot.core.notify import TelegramNotifier; TelegramNotifier.from_env().notify.crisis('TEST')"` manda mensagem real (usar chat_id de teste se possível, ou apenas `print` se `TELEGRAM_BOT_TOKEN` começar com `TEST`).

---

### P1-A — Commander real (assíncrono, com EventBus mínimo)

**Refatora `engine/commander.py`:**
- `Commander` como classe única instancia, **injetada** no executor (não mais `get_commander()` global).
- `decide(ctx) -> CommanderOrder` assinado (dataclass, não dict).
- Estado do Commander em **arquivo separado** — `bot/run/commander_state.json`, NÃO `bot_state.json`.
- `EventBus` mínimo: pub/sub in-memory, síncrono (não asyncio — bot hoje é síncrono e migrar pra async é P3). Eventos: `TradeOpened`, `TradeClosed`, `CommanderDecision`, `OracleUpdate`.
- `Oracle.analyze()` em `engine/autonomous_oracle.py` retorna `OracleThesis` tipado.
- `EvolutionEngine.evolve()` em `engine/self_evolution.py` com **validação OOS em janela fixa** (30 dias) — não muta sem baseline.
- **Bridge limpa:** `engine/autonomous_bridge.py` atual tem 139 ln de shim. Integração agora direta: `executor` detém instância de `Commander`, passa contexto, recebe ordem.

**Critério de "feito":**
- `pytest tests/test_commander.py` mocka oracle+evolution, chama `commander.decide(...)`, verifica ordem.
- `grep -n "_COMMANDER\|_AUTONOMOUS_AVAILABLE" bot/executor.py` → zero (variables globais extintas).
- Smoke: `python -c "from engine.commander import Commander; print(Commander.__init__.__annotations__)"` mostra DI tipada.

---

### P1-B — Testes de cenário (não "100% coverage" — coverage alvo onde dói)

Instalar pytest + pytest-cov no venv Hermes (`venv/Scripts/pip install pytest pytest-cov pytest-mock` — verificar se pip existe; se não, usar `python -m ensurepip`).

**Prioriza testes de CENARIO DE FALHA** (trading real perde dinheiro):

| Arquivo de teste | Cenário |
|---|---|
| `tests/scenarios/test_mt5_disconnect.py` | Mock `mt5.shutdown()` no meio de `run_once` — executor não trava, retry, loga, state persiste |
| `tests/scenarios/test_state_corruption.py` | `bot_state.json` com JSON inválido — recovery via `SafeFileStore`, rename pra `.corrupt`, alerta Telegram |
| `tests/scenarios/test_race_save_state.py` | 2 threads chamando `StateManager.mutate()` concurrent — lock garante consistência |
| `tests/scenarios/test_llm_timeout.py` | `autonomous_oracle` chama Ollama que dá timeout em 5s — fallback pra heurística hardcoded, sem crash |
| `tests/scenarios/test_double_start.py` | 2× `python bot/manager.py start` — segundo recusa com "já rodando (PID X)" |
| `tests/scenarios/test_pd_reject_order.py` | `mt5.order_send` retorna retcode != 10009 — executor loga, NÃO empilha, continua loop |

Mock fixtures em `tests/conftest.py` — `mock_mt5`, `mock_ollama`, `mock_telegram`, `sample_state`.

Coverage alvo: **80% em `bot/core/`** (state, risk, decision, execution, mt5_bridge). Não meta (~(60% global). `engine/` legacy pode ter cobertura baixa — prioridade é o core.

**Critério de "feito":**
- `python -m pytest tests/scenarios/ -v` roda 6 testes, todos passam.
- `python -m pytest tests/ --cov=bot/core --cov-report=term-missing` mostra >=80% em core.

---

### P2-A — Auto-aperfeiçoamento via cron do Hermes (novo, não-existent hoje)

**Decisão:** o bot de trading não melhora a si mesmo em runtime (perigoso, não-validável). Um **cron job do Hermes** roda todo dia às 03:00 UTC (sessão Asia calma), analisa `bot/run/decision_log.jsonl` + `bot_state.json` + `commander_state.json` das últimas 24h, e **propõe** ajustes — não aplica. Manda pro Telegram (Lucas aprova).

Cria `bot/improvement/analyze_session.py` — script standalone lido pelo cron, stdout injetado no agente.

Cria cron job via `cronjob` tool do Hermes:

```yaml
schedule: "0 3 * * *"     # diário 03:00 UTC
model: glm-5.2            # local, não clouds cloud cap
provider: nvidia
prompt: |
  Lê `bot/run/daily_summary.json` (gerado por analyze_session.py) e produces
  um relatório: (1) 3 trades mais dispendiosos do dia, com diagnóstico; (2)
  filtro que mais bloqueou ordens; (3) 1 proposta de ajuste paramétrico + justificativa.
  Não apliques — entrega no Telegram. Se estado CRISIS detectado, alerta vermelho.
deliver: origin             # já configurado no Hermes p/ Telegram do Lucas
skills: [wealth-engine]
workdir: C:\Users\lucas\Wealth_Engine
enabled_toolsets: [file, terminal]
```

**Critério de "feito":**
- `cronjob` tool chamada com esse spec, retorna job_id.
- Confirmar via `hermes cron list` que job existe.
- Schedule de testes: rodar `cronjob action=run job_id=...` uma vez e ver mensagem chegar no Telegram.

---

### P2-B — Dashboard FastAPI read-only (não SPA — leve)

**Decisão:** mantém `wealth_dashboard.py` (Streamlit) em paralelo por ora, mas adiciona FastAPI read-only expor JSON puros — usado pelo cron job e por um dashboard web futuro. Não reescreve Streamlit.

Cria `bot/api/server.py`:
- `FastAPI` + `uvicorn` (adicionar ao requirements.txt).
- Endpoints: `/health`, `/status`, `/metrics`, `/trades?n=50`, `/decisions?n=50`, `/regime`.
- Source dos dados = `bot_state.json`, `bot/run/decision_log.jsonl`, `bot/run/heartbeat.json`. **Re-read a cada request** (não cache) pra sempre fresco.
- Auth: `Authorization: Bearer <DASHBOARD_TOKEN>` em `.env`. Default deny.
- Roda em `127.0.0.1:8000` (não expor).

**Critério de "feito":**
- `curl -H "Authorization: Bearer X" http://localhost:8000/status` retorna JSON.
- Sem auth → 401.

---

## 2) REGRAS DE EXECUÇÃO (não negociável)

### Ordem
P0-A → P0-B → P0-C → P0-D → P1-A → P1-B → P2-A → P2-B. Não pular.

### Estilo de código
- **Python 3.11** — type hints com `X | None` moderno. `from __future__ import annotations` no topo de cada módulo novo.
- **Logging via** `logging.getLogger(__name__)`, nunca `print()`. RotatingFileHandler em produção, StreamHandler em dev.
- **Sem directories hardcoded.** Tudo relativo a `Path(__file__).resolve().parent`. Sem `C:\Users\lucas\...` em código.
- **Sem dependências inventadas sem** entry em `requirements.txt`.
- **Imports no topo do arquivo** (não lazy-loading sem justificativa em docstring).
- **Funções < 50 linhas.** Se maior, extrair.
- **Commits atômicos** — um commit por P0-A, P0-B, etc. `git commit -m "feat(P0-A): extrair bot/core/state.py do monolito"`.

### Preservar behavior testado
O TS-Momentum, sizing vol-target, regimes, COT momentum — TUDO funcionava no `reports/VERDICT.md` com Sharpe 0.62. **Não reescrever lógica de decisão**, só mover. Se tentar "melhorar" o sinal e quebra o backtest, é derrota.

### Não inventar
- ❌ Docker/Docker Compose — não cabe, Windows nativo, conta de $10.
- ❌ Prometheus/Grafana/logs ELK — overhead compacto pro projeto.
- ❌ React/TypeScript/Vite/Zustand — não existe frontend dev, é inexistente.
- ❌ JWT/session complexo — bearer token chega.
- ❌ Redis/RabbitMQ — filelock + JSON IO é suficiente.
- ❌ asyncio migration completa — bot hoje é síncrono, `mt5` lib é síncrono. Async é P4 (se um dia).

### Honesty
Se algo não funciona, **escreve no commit "WIP — não funciona ainda X motivo"** e move. NÃO commits "fix" em bug não-fixado. NÃO reportar "feito" em etapa que não rodou.

### Saúde em cada commit
1. `python -c "import bot.core.<modulo>"` sem erro.
2. `python -m pytest tests/<modulo_test> -v` passa (se teste existe pra aquele módulo).
3. `git diff --stat` mostra o esperado (linhas removidas > adicionadas em `executor.py`).

---

## 3) CHECKLIST RÁPIDO POR PRIORIDADE

- [ ] **P0-A** — `bot/core/{state,mt5_bridge,risk,decision,execution}.py` existe; `executor.py` encolheu de 1078 → ≤250
- [ ] **P0-B** — `bot/manager.py` com start/stop/status/health; 7 scripts `.bat`/`.ps1`/`.vbs` deletados; `bot/run/` existe
- [ ] **P0-C** — `SafeFileStore` atomic + lock; `.env` loading único; 5 `except: pass` mortos no executor
- [ ] **P0-D** — `bot/core/notify.py` com retry + queue; `notify()` inline no executor substituído
- [ ] **P1-A** — `Commander` injetado; `_COMMANDER` global extinto; EventBus mínimo
- [ ] **P1-B** — `tests/scenarios/` com 6 cenários; coverage >=80% em `bot/core/`
- [ ] **P2-A** — cron job Hermes criado (`cronjob action=create`); confirmado no `hermes cron list`
- [ ] **P2-B** — FastAPI read-only + bearer auth rodando em `127.0.0.1:8000`

---

## 4) CONTEXTO QUE VOCÊ JÁ TEM (não precisa redescobrir)

- **Branch:** `main`. Status atual: `8 modified, 10 untracked`. Os untracked são o que foi discutido em handoff anterior (autonomous_oracle, commander, etc.) — podem ser commitados como parte do P0-A.
- **Strategy válida:** TS-Momentum cross-asset (Moskowitz 2012), Sharpe 0.62, +135% em 5y backtest. Documento em `reports/VERDICT.md`.
- **3 bugs históricos** (já corrigidos no executor atual — preservar fix): (1) `positions_get()` não `positions_get(symbol="")`; (2) sinal COT não-top-buying; (3) sizing vol-target não %fixa.
- **Meta-config:** `engine/meta_config.py` tem o estado rolante de performance por bucket. Não descartar.
- **Decision log:** `bot/decision_log.jsonl` cresce infinitamente como event history — manter este padrão (não snapshot). 2.7MB hoje.

---

## 5) AVISO FINAL

O bot já perdeu $90 por bugs de "IA-fez-IA". Cada regressão é dólares. Antes de commitar, rodar `python -c "import bot.executor"` — se quebra, aborta commit. Prefira mover código que funciona a reescrever e introduzir novo bug. Você é responsável pela integridade do estado até o próximo handoff.

O usuário (Lucas) já discutiu meta de 20%/semana e foieducado que swing H4 real = 7-10%. Não reabordar este tema. O trabalho aqui é **engenharia**, não "otimizar retorno".
