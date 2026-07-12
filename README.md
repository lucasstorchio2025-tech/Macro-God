# Wealth Engine v2 🤖

> **Sistema automatizado de trading baseado em TS-Momentum (Moskowitz 2012), com detecção de regime, vol-targeting institucional e meta-aprendizado contínuo.**

---

## 📋 Índice

- [Visão Geral](#-visão-geral)
- [Arquitetura](#-arquitetura)
- [Engine (Núcleo de Análise)](#engine-núcleo-de-análise)
- [Bot (Executor ao Vivo)](#bot-executor-ao-vivo)
- [Painel Mestre (Dashboard)](#-painel-mestre-dashboard)
- [Inteligência de Mercado](#-inteligência-de-mercado)
- [Sistema de Melhoria Contínua](#-sistema-de-melhoria-contínua)
- [Relatórios](#-relatórios)
- [Testes](#-testes)
- [Configuração](#-configuração)
- [Como Usar](#-como-usar)
- [Arquivos do Projeto](#-arquivos-do-projeto)

---

## 📖 Visão Geral

**Wealth Engine** é um robô de trading automatizado para **MetaTrader 5** (conta demo Exness) que opera exclusivamente **XAUUSD (ouro)** usando a estratégia **Time-Series Momentum** (Moskowitz, Ooi & Pedersen 2012).

### Filosofia

1. **ZERO lookahead** — toda decisão usa apenas dados até o momento da decisão. Testado automaticamente.
2. **Custos reais** — spread + slippage em toda entrada. Sem isso, backtest mente.
3. **Regime adaptativo** — o sistema detecta se o mercado está em risk_on, normal, risk_off ou crisis e ajusta exposição automaticamente.
4. **Vol-targeting** — ativo nervoso → tamanho menor. Princípio institucional (Target Volatility funds).
5. **Meta-aprendizado** — o bot aprende com seus próprios erros via análise LLM (Gemma/Ollama), ajustando risco por contexto.

### Resultados do Backtest (OOS)

| Métrica | Valor |
|---|---|
| Sharpe (OOS) | 1.30 |
| Win Rate | ~42% |
| Payoff | ~2.02 |
| Trades/ano | ~96 |
| Sessão | Apenas Tokyo |

---

## 🏗️ Arquitetura

```
Wealth_Engine/
│
├── engine/              ← Núcleo de análise (INDEPENDENTE do bot)
│   ├── config.py        ← Todos os parâmetros centralizados
│   ├── data.py          ← Carregamento de histórico (MT5, yfinance, COT)
│   ├── indicators.py    ← ATR, vol realizada, momentum, correlação
│   ├── regime.py        ← Detector de regime (4 estados)
│   ├── signals.py       ← Estratégias (TS-Momentum, COT Contrarian)
│   ├── backtest.py      ← Motor de backtest barra-a-barra
│   ├── sizing.py        ← Vol-targeting + correlação + exposição USD
│   ├── analytics.py     ← Sharpe, Sortino, drawdown, veredito
│   ├── macro_analysis.py ← Análise macro (drivers, conclusão)
│   ├── macro_signals.py ← Sinais macro (USD, RISK, YIELDS, COT, etc.)
│   └── meta_config.py   ← MetaState (aprendizado contínuo)
│
├── bot/                 ← Bot ao vivo (conecta MT5, executa ordens)
│   ├── executor.py      ← Ciclo principal de decisão + execução
│   ├── strategy_bridge.py ← Ponte engine → executor ao vivo
│   ├── decision_log.py  ← Log estruturado de decisões
│   ├── telegram_setup.py ← Notificações Telegram
│   └── post_trade_analysis.py ← Análise pós-trade
│
├── scripts/             ← Scripts auxiliares
│   ├── run_intelligence.py ← Pipeline de inteligência
│   ├── files/market_intelligence.py ← Coleta de dados macro
│   ├── files/news_aggregator.py ← Agregador de notícias (Ollama)
│   └── risk_manager.py ← Gerenciador de risco externo
│
├── wealth_dashboard.py  ← Painel Mestre Unificado (Streamlit)
├── auto_improve.py      ← Loop de melhoria contínua
├── auto_tune.py         ← Ajuste de parâmetros
└── tests/               ← Testes unitários
```

### Fluxo de Decisão

```
MT5 (preços) ──→ strategy_bridge ──→ engine/signals.py (TS-Momentum)
                                             │
                    engine/regime.py ←── VIX + DXY + SPY + COT
                                             │
                    engine/sizing.py ←── vol-target + correlação
                                             │
                    executor.py (filtros):    │
                      ├─ drawdown check      │
                      ├─ max positions       │
                      ├─ exposure cap        │
                      ├─ macro blockers      │
                      ├─ cooldown            │
                      ├─ session filter      │
                      └─ regime gate ────────┘
                                             │
                    ABRE ORDEM (ou dry-run)
```

---

## ⚙️ Engine (Núcleo de Análise)

O **engine** é um pacote Python independente que **nunca abre ordens**. Tudo é cálculo sobre histórico, testável e reproduzível.

### `engine/config.py` — Fonte Única da Verdade

Todos os parâmetros do sistema estão aqui, com nomes claros e comentários. Principais categorias:

| Categoria | Parâmetros-chave |
|---|---|
| **Universo** | `SYMBOLS = ["XAUUSDm"]`, `USD_BETA` |
| **Risco** | `RISK_PER_TRADE_PCT = 5%`, `MAX_OPEN_POSITIONS = 3`, `MIN_REWARD_RISK = 2.0` |
| **Regime** | `VIX_RISKOFF_PERCENTILE = 80`, `VIX_CRISIS_PERCENTILE = 95`, `EXPOSURE_SCALE` |
| **Momentum** | `MOMENTUM_LOOKBACK_BARS = 264` (~1 ano), `MOMENTUM_SKIP_BARS = 24` |
| **Vol-Target** | `TARGET_VOL_PCT_ANNUAL = 12%`, `VOL_TARGET_CAP = 0.6` |
| **Sessão** | `SESSION_FILTER_ALLOW = ["Tokyo"]` → apenas Tokyo (Sharpe OOS 1.30) |
| **ATR por Regime** | risk_on: 2.0×ATR, normal: 1.5×ATR, risk_off: 1.0×ATR |
| **Eventos Macro** | Reduz exposição 4h antes de FOMC/NFP/CPI |

### `engine/data.py` — Dados

Carrega histórico de 4 fontes:

| Fonte | O que | Cache |
|---|---|---|
| **MT5** | Preços H4 de XAUUSDm | `engine/cache/*.parquet` |
| **yfinance** | VIX (^VIX), DXY (DX-Y.NYB), SPY | `engine/cache/vix.csv`, `dxy.csv`, `spy.csv` |
| **CFTC Socrata** | COT histórico (especuladores) | `engine/cache/cot_history.csv` |

### `engine/indicators.py` — Indicadores Técnicos

- **ATR** — Average True Range (vetorizado)
- **Realized Vol** — Volatilidade realizada anualizada (para vol-targeting)
- **TS-Momentum** — Retorno passado (lookback - skip) (Moskowitz 2012)
- **Correlação Rolante** — Matriz de correlação entre pares (usada no sizing)
- **Z-Score** — Para COT Contrarian

### `engine/regime.py` — Detector de Regime

Classifica o mercado em 4 estados:

| Estado | Descrição | Exposição |
|---|---|---|
| ✅ **risk_on** | Apetite a risco genuíno (VIX baixo + gold-equity corr negativa) | 100% |
| ⚖️ **normal** | Mercado sem viés forte | 75% |
| ⚠️ **risk_off** | Estresse/medo (VIX alto, correlações subindo) | 30% |
| 🚨 **crisis** | Pânico (VIX>35 ou percentil 95+) | 0% (flat) |

Três camadas, aplicadas em ordem:
1. **VIX** — volatilidade absoluta + percentil
2. **Gold-Equity Correlation** — correlação XAUUSD vs SPY (verdadeiro risk_on)
3. **Liquidity Stress** — DXY + VIX subindo juntos (flight-to-dollar)

### `engine/signals.py` — Estratégias

| Estratégia | Descrição |
|---|---|
| **TSMomentumStrategy** | Time-series momentum cross-asset. Compra quem subiu, vende quem caiu. 👍 |
| **COTContrarianStrategy** | Age só em extremos (z-score≥2). Contrarian. |
| **LegacyCOTStrategy** | Reproduz lógica ANTIGA (que perdeu $90). Baseline a superar. |

### `engine/backtest.py` — Motor de Backtest

Princípios:
1. **Zero lookahead** — decisão em t só vê dados até t-1 (testado!)
2. **Custos reais** — spread + slippage em toda entrada
3. **Saída intra-barra conservadora** — se SL e TP tocados, assume SL primeiro
4. **Walk-forward** — otimização só in-sample, resultado em out-of-sample

Recursos:
- Partial TP (realiza 30% em 1×RR, deixa 70% correr)
- Holding time max (fecha posição após ~14 dias)
- Loss streak cooldown (pausa anti-tilt após 6 perdas consecutivas)
- Macro events (reduz exposição antes de FOMC/NFP/CPI)
- Filtro de tendência D1 (só opera na direção da diária)

### `engine/sizing.py` — Dimensionamento Institucional

Três correções ao erro do bot antigo:
1. **Vol-targeting**: tamanho ∝ vol_alvo / vol_realizada
2. **Cap por correlação**: EURUSD + GBPUSD ≈ mesma aposta → divide tamanho
3. **Exposição USD agregada**: soma beta-USD de todas as posições

### `engine/macro_analysis.py` + `macro_signals.py` — Análise Macro

8 drivers de mercado analisados:
- **USD** — DXY (dólar forte/fraco)
- **RISK** — VIX (apetite de risco)
- **LIQUIDITY** — Stress de liquidez (flight-to-dollar)
- **YIELDS** — Treasury 10y, Fed Funds
- **COT** — Posicionamento de especuladores
- **MOMENTUM** — TS-Momentum técnico
- **REGIME** — Estado atual do detector
- **NEWS** — Viés narrativo (Ollama)

### `engine/meta_config.py` — Meta-Aprendizado

**MetaState** armazena:
- Rolling metrics (win rate, payoff, SL rate) dos últimos 50 trades
- Performance por bucket de contexto (regime, direção, stop)
- Multiplicadores adaptativos gerados pelo LLM (Gemma via Ollama)
- Histórico de recomendações do LLM para auditoria

Filosofia:
- NUNCA muda a direção do trade
- NUNCA salva features de preço (overfit)
- Só aprende por categorias interpretáveis

---

## 🤖 Bot (Executor ao Vivo)

### `bot/executor.py` — Coração do Robô

**Fluxo de cada ciclo (a cada 5 minutos):**

1. **Conecta MT5** — credenciais do `.env`
2. **Drawdown check** — diário (-8%) e semanal (-15%)
3. **Sync** — detecta deals automáticos (SL/TP batidos)
4. **Alimenta MetaState** — trades fechados viram aprendizado
5. **Max positions** — verifica slots disponíveis
6. **Regime gate** — crisis → fecha tudo, fica flat
7. **Macro blockers** — evento de alto impacto em <2h? Não opera
8. **Exposure check** — risco aberto vs cap
9. **Sinais** — strategy_bridge → TS-Momentum
10. **Anti-empilhamento** — mesmo símbolo já aberto? Pula
11. **Cooldown** — espera 48h após saída de símbolo
12. **Session filter** — só Tokyo
13. **Calcula SL/TP/lote** — ATR + sizing + meta_risk
14. **Abre ordem** — ou dry-run (não executa)

**Dry-Run**: `run_once.dry_run = True` — calcula tudo, não abre ordem. Perfeito para testar.

### `bot/strategy_bridge.py` — Ponte Engine ↔ Bot

Adapta o sinal do engine (dados históricos) pro formato do executor ao vivo (MT5 real). Busca dados frescos, chama o regime e as estratégias, retorna sinais com contexto detalhado.

### `bot/decision_log.py` — Log Estruturado

Cada decisão vira um registro JSON com:
- Contexto completo (regime, VIX, DXY, COT, notícias)
- Símbolo, direção, resultado (opened/dry_run/blocked/no_signal)
- Filtro que bloqueou (se aplicável)
- Informação de risco (lote, RR, SL, TP)

### `bot/post_trade_analysis.py` — Análise Pós-Trade

Analisa trades fechados e gera relatório com:
- Win rate, payoff, expectancy por regime
- Performance por sessão, direção, ATR stop
- Distribuição de RR
- Recomendações de melhoria

### `bot/telegram_setup.py` — Notificações

Configura bot do Telegram para receber alertas do robô.

---

## 📊 Painel Mestre (Dashboard)

### `wealth_dashboard.py` — O ÚNICO Dashboard

**Acesso:** `http://localhost:8501` (ou IP da rede)

**Seções:**

| Seção | O que mostra |
|---|---|
| 🏆 **Veredicto** | Status do bot + conclusão de mercado + confiança + risk score |
| 📊 **Regime** | risk_on/normal/risk_off/crisis com cor |
| 🌡️ **VIX + DXY** | Sentimento de risco em tempo real |
| 🌍 **Sessão Atual** | Sydney/Tokyo/London/NewYork + horário UTC |
| ⏳ **Cooldown** | Quanto tempo falta para cada símbolo |
| 🔍 **Drivers** | O que está movendo o mercado (USD, RISK, YIELDS, COT, etc.) |
| 🧭 **Direção** | Para onde cada ativo aponta (bullish/bearish) |
| 🚫 **Pipeline** | Quais filtros estão bloqueando e quantas vezes |
| 📜 **Timeline** | Últimas 50 decisões com cores |
| 📊 **Trades** | Ordens enviadas, deals encontrados, dry-runs |
| 📰 **Contexto** | Notícias, calendário econômico, COT, juros, preços MT5 |
| ⚙️ **Config** | Símbolos, risco, RR, cooldown, sessão |

**Auto-refresh:** a cada 30 segundos.

---

## 🧠 Inteligência de Mercado

### `scripts/run_intelligence.py` — Pipeline

```
1. market_intelligence.py → coleta DXY, VIX, Fed, COT, MT5
2. news_aggregator.py → notícias via Ollama (opcional)
3. analyze_market() → cruza tudo, gera snapshot
4. Salva market_snapshot.json → dashboard lê
5. Envia conclusão no Telegram (se configurado)
```

### `scripts/files/market_intelligence.py`

Coleta:
- DXY (US Dollar Index) via yfinance
- VIX (CBOE Volatility Index) via yfinance
- Treasury 10y + Fed Funds via FRED API (gratuita)
- COT (Commitment of Traders) via CFTC Socrata
- Preços MT5 ao vivo
- Calendário econômico (ForexFactory)
- Swing trade plan com RR e lote recomendado

### `scripts/files/news_aggregator.py`

Agregador de notícias que usa **Ollama** (modelo local) para:
- Baixar RSS de veículos financeiros (Bloomberg, Reuters, CNBC, Investing.com)
- Classificar cada notícia como hawkish/dovish/neutra
- Filtrar apenas notícias relevantes para XAUUSD
- Salvar em `filtered_news.json`

---

## 🔄 Sistema de Melhoria Contínua

### `auto_improve.py`

Loop mestre de melhoria que:
1. Chama `post_trade_analysis.py` (análise dos trades reais)
2. Roda backtest completo (`full_analysis.py`)
3. Calcula métricas de performance
4. Gera recomendações
5. Salva em `reports/IMPROVEMENT.md`

**Modos:**
```bash
python auto_improve.py           # 1 ciclo completo
python auto_improve.py --quick   # só análise (pula backtest)
python auto_improve.py --tune    # análise + tuning
python auto_improve.py --loop    # loop infinito (a cada 6h)
```

### `auto_tune.py`

Analisa parâmetros atuais e sugere ajustes no `engine/config.py`:
- Vol-targeting
- Cooldown
- Sessão
- Limites de risco
- ATR multipliers

### `run_improvement.bat`

Menu interativo no terminal para rodar ciclos de melhoria.

---

## 📈 Relatórios

Gerados automaticamente em `reports/`:

| Relatório | Fonte | Descrição |
|---|---|---|
| `VERDICT.md` | `analytics.py` | Veredito do backtest: qual estratégia venceu, Sharpe, recomendação |
| `POST_TRADE.md` | `post_trade_analysis.py` | Análise dos trades reais fechados |
| `ANALYSIS.md` | `full_analysis.py` | Backtest completo com todas as métricas |
| `IMPROVEMENT.md` | `auto_improve.py` | Recomendações do ciclo de melhoria |
| `WALK_FORWARD.md` | `walk_forward_validate.py` | Validação walk-forward OOS |
| `WALK_FORWARD_TOKYO.md` | `walk_forward_tokyo.py` | WFO específico para sessão Tokyo |
| `ANALISE_NEGATIVOS.md` | `analyze_negative_months.py` | Análise de meses negativos |
| `COMPARATIVO.md` | `sweep_comparativo.py` | Comparação de melhorias |
| `LIQUIDITY_SWEEP.md` | `regime_sweep_liquidity.py` | Sweep de thresholds de liquidez |
| `TUNE_LOG.jsonl` | `auto_tune.py` | Histórico de tuning |
| `TUNE_RESULT.json` | `auto_tune.py` | Resultado do último tuning |
| `IMPROVEMENT_LOG.jsonl` | `auto_improve.py` | Histórico de melhorias |

---

## 🧪 Testes

### Testes Unitários (`tests/`)

```bash
python tests/run_tests.py
```

16 testes que validam garantias fundamentais:

| Teste | O que valida |
|---|---|
| `test_no_lookahead` | Nenhuma decisão usa dado do futuro (erro nº1 de backtest) |
| `test_sizing` | Vol-targeting + correlação funcionam matematicamente |
| `test_regime` | Detector classifica corretamente os 4 estados |
| `test_liquidity_signal` | Stress de liquidez é detectado corretamente |

### Resultados Atuais

```
16 passed, 0 failed ✅
```

---

## 🔧 Configuração

### Credenciais (`.env`)

Criar em `C:\Users\lucas\.hermes\.env` ou `Wealth_Engine\.env`:

```env
EXNESS_LOGIN=seu_login
EXNESS_PASSWORD=sua_senha
EXNESS_SERVER=Exness-MT5Trial11
TELEGRAM_BOT_TOKEN=seu_token
TELEGRAM_CHAT_ID=seu_chat_id
FRED_API_KEY=sua_fred_key
```

### Dependências

```bash
pip install -r requirements.txt
```

Principais: `MetaTrader5`, `pandas`, `numpy`, `yfinance`, `streamlit`, `requests`, `python-dotenv`

### Inicialização Automática

O dashboard inicia automaticamente ao ligar o PC (atalho na pasta Startup). O watchdog (`watchdog_supervisor.bat`) monitora e relança o executor se cair.

---

## 🚀 Como Usar

### 1. Abrir o Dashboard

```bash
streamlit run wealth_dashboard.py --server.address=0.0.0.0 --server.port=8501
```
Acessar: `http://localhost:8501` ou `http://SEU_IP:8501`

### 2. Rodar o Bot (Loop Infinito)

```bash
python bot/executor.py
```

### 3. Rodar Inteligência de Mercado

```bash
python scripts/run_intelligence.py
```

### 4. Rodar Dry-Run (Teste Sem Abrir Ordens)

```bash
python -c "
import sys; sys.path.insert(0, 'bot')
from executor import run_once, load_state
state = load_state()
run_once.dry_run = True
result = run_once(state)
print(result)
"
```

### 5. Rodar Testes

```bash
python tests/run_tests.py
```

### 6. Rodar Ciclo de Melhoria

```bash
run_improvement.bat        # menu interativo
python auto_improve.py     # 1 ciclo completo
```

### 7. Atalhos Rápidos (`.bat`)

| Arquivo | O que faz |
|---|---|
| `bot/abrir_dashboard.bat` | Abre o Dashboard Mestre |
| `bot/run_executor.bat` | Inicia o executor do bot |
| `bot/run_news.bat` | Atualiza inteligência de mercado |
| `bot/watchdog_supervisor.bat` | Monitora e relança o bot |
| `bot/instalar_dashboard_startup.vbs` | Instala dashboard na inicialização do Windows |

---

## 📁 Arquivos do Projeto

### Raiz

| Arquivo | Descrição |
|---|---|
| `wealth_dashboard.py` | **Painel Mestre Unificado** (Streamlit) — substituto dos 3 dashboards antigos |
| `auto_improve.py` | Loop de melhoria contínua (análise + backtest + recomendações) |
| `auto_tune.py` | Ajuste de parâmetros (varredura + aplicação) |
| `run_intel_now.py` | Execução rápida do pipeline de inteligência |
| `requirements.txt` | Dependências Python |
| `run_improvement.bat` | Menu para rodar ciclos de melhoria |

### `engine/` (Núcleo)

| Arquivo | Descrição |
|---|---|
| `config.py` | Todos os parâmetros centralizados |
| `data.py` | Carregamento de histórico com cache |
| `indicators.py` | ATR, vol realizada, momentum, correlação, z-score |
| `regime.py` | Detector de regime (4 estados: risk_on → crisis) |
| `signals.py` | Estratégias (TS-Momentum, COT Contrarian) |
| `backtest.py` | Motor de backtest barra-a-barra |
| `sizing.py` | Vol-targeting + correlação + exposição USD |
| `analytics.py` | Métricas de performance e veredito |
| `macro_analysis.py` | Análise macro (drivers, conclusão, direção por ativo) |
| `macro_signals.py` | Sinais individuais (USD, RISK, YIELDS, COT, etc.) |
| `meta_config.py` | MetaState — aprendizado contínuo |
| `meta_learner.py` | Consulta LLM (Gemma/Ollama) |
| `full_analysis.py` | Backtest completo + relatório |
| `run_verdict.py` | Geração do veredito |
| `utils.py` | Utilitários (sessão forex, ATR labels) |
| `macro_events.py` | Calendário de eventos macro |
| `analyze_negative_months.py` | Análise de meses negativos |
| `regime_sweep.py` | Sweep de gates de regime |
| `regime_sweep2.py` | Investigação profunda do paradoxo do regime |
| `regime_sweep_liquidity.py` | Sweep de thresholds de liquidez |
| `sweep_comparativo.py` | Comparação de melhorias |
| `walk_forward_validate.py` | Validação walk-forward |
| `walk_forward_tokyo.py` | WFO específico Tokyo |

### `bot/` (Executor)

| Arquivo | Descrição |
|---|---|
| `executor.py` | Ciclo principal de decisão e execução |
| `strategy_bridge.py` | Ponte engine → executor ao vivo |
| `decision_log.py` | Log estruturado de decisões |
| `post_trade_analysis.py` | Análise pós-trade |
| `telegram_setup.py` | Notificações Telegram |
| `abrir_dashboard.bat` | Abre o Dashboard Mestre |
| `run_executor.bat` | Inicia o executor |
| `run_news.bat` | Atualiza inteligência |
| `watchdog_supervisor.bat` | Monitora e relança o bot |
| `auto_intel.bat` | Pipeline automático de inteligência |
| `status.bat` | Status rápido no terminal |
| `instalar_dashboard_startup.vbs` | Instala dashboard na inicialização |
| `instalar_dashboard_startup.ps1` | Versão PowerShell do auto-start |

### `scripts/` (Auxiliares)

| Arquivo | Descrição |
|---|---|
| `run_intelligence.py` | Orquestra pipeline de inteligência |
| `risk_manager.py` | Gerenciador de risco externo |
| `files/market_intelligence.py` | Coleta de dados macro (DXY, VIX, Fed, COT, MT5) |
| `files/news_aggregator.py` | Agregador de notícias via Ollama |

### `tests/` (Testes)

| Arquivo | Descrição |
|---|---|
| `run_tests.py` | Roda todos os testes |
| `test_no_lookahead.py` | Garante zero lookahead no backtest |
| `test_sizing.py` | Valida vol-targeting e correlação |
| `test_regime.py` | Valida detector de 4 estados |
| `test_liquidity_signal.py` | Valida detector de stress de liquidez |

### `engine/cache/` (Dados)

Dados cacheados para evitar downloads repetidos:
- `vix.csv`, `dxy.csv`, `spy.csv` — índices financeiros
- `cot_history.csv` — histórico COT
- `*_H4.parquet` — preços MT5 por par

### `reports/` (Relatórios)

Relatórios gerados automaticamente pelo sistema.

### Dados Gerados

| Arquivo | Descrição |
|---|---|
| `market_intelligence.json` | Snapshot da inteligência de mercado |
| `market_snapshot.json` | Snapshot com análise completa |
| `filtered_news.json` | Notícias filtradas pelo agregador |
| `raw_macro_rss.json` | RSS bruto de notícias |
| `wealth_ledger.json` | Livro-razão de operações |
| `bot/bot_state.json` | Estado persistente do bot |
| `bot/decision_log.jsonl` | Log de decisões (event-sourced) |
| `bot/trade_log.jsonl` | Log de eventos de trading |

---

## 🧹 Limpeza Realizada

O projeto foi limpo de arquivos temporários e não utilizados:

| Grupo | Removidos |
|---|---|
| Dashboards antigos | `bot/bot_dashboard.py`, `scripts/files/dashboard.py`, `scripts/files/intelligence_dashboard.py` |
| Scripts de probe/calibração | `calibrate_lot.py`, `probe_*.py`, `place_test_order.py`, `check_position.py`, `close_position.py`, `emergency_close_all.py`, `close_on_open.py` |
| Testes temporários | `test_mt5.py`, `test_eurusd_5pct.py`, `bot/test_*.py` |
| Debug | `bot/dump_contributions.py` |
| Artefatos | `bot/confidence_result.json`, `bot/test_multiposition_result.json` |
| Watchdog antigo | `bot/setup_watchdog.vbs`, `bot/setup_watchdog.bat`, `bot/uninstall_watchdog.bat`, `bot/register_task.bat` |
| Documentação desatualizada | `PROJECT_AUDIT.md`, `nul` |

---

## 📜 Licença

Uso pessoal — trading em conta demo Exness.

---

## 🤝 Contribuindo com Fable 5

O projeto está limpo, documentado e pronto para análise por **Fable 5**. A arquitetura separa claramente:
- **Engine** (cálculo puro, testável, independente)
- **Bot** (execução ao vivo, conecta MT5)
- **Scripts** (pipeline de dados)
- **Dashboard** (visualização)

Cada componente pode ser melhorado independentemente.
