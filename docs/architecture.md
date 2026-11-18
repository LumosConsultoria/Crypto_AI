# 🏗️ Arquitetura do Crypto Trading Bot

## Visão Geral

Sistema de trading quantitativo em Python, projetado com segurança e auditabilidade como prioridades absolutas. O bot começa em modo **paper trading** (simulação) e só evolui para operação real após validação completa em cada fase.

---

## Diagrama de Fluxo Principal

```
┌─────────────────────────────────────────────────────────────────┐
│                        Market Data                               │
│  (MockExchange em paper / BybitClient em testnet/live)          │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌───────────────────────────────────────────────────────────────────┐
│                        Indicators                                  │
│  (SMA, RSI, MACD, ATR, Bollinger, etc. — calculados localmente)  │
└───────────────────────────┬───────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Strategy                                   │
│  (Gera TradingSignal com stop loss obrigatório)                  │
│  ⚠️  NUNCA decide com IA/LLM diretamente                         │
└───────────────────────────┬─────────────────────────────────────┘
                            │  TradingSignal
                            ▼
┌═════════════════════════════════════════════════════════════════╗
║                    RISK ENGINE  ⚠️  SOBERANO                    ║
║  ✅ Stop loss obrigatório        ✅ Limite de perda diária       ║
║  ✅ Limite de perda total        ✅ Max trades/dia               ║
║  ✅ Exposição por ativo          ✅ Alavancagem máxima           ║
║  ✅ Capital suficiente           ✅ Modo seguro                  ║
╚═══════════════════════════┬════════════════════════════════════╝
                          APROVADO  ╲  BLOQUEADO
                            │        ╲───► [Log de Auditoria]
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                  ModeGuard Check                                 │
│  paper → PaperTrader     testnet → BybitClient(testnet)         │
│  live  → BybitClient(live) [requer triple-lock]                  │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Executor                                       │
│  PaperTrader: simula sem API      BybitExecutor: ordem real      │
│  Todos os trades → Log de Auditoria                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## Estrutura de Pacotes

```
src/crypto_trading_bot/
│
├── config/             # Configuração central (carregada do .env)
│   ├── settings.py     # Modo de operação, símbolo, logs
│   ├── risk_config.py  # Regras de risco (HyroTrader rules)
│   └── exchange_config.py  # Credenciais e endpoints Bybit
│
├── core/               # Núcleo do sistema
│   ├── mode_guard.py   # 🔒 PROTEÇÃO TRIPLA contra execução real acidental
│   ├── bot_engine.py   # Loop principal de decisão
│   └── event_bus.py    # Comunicação interna pub/sub
│
├── logging_system/     # Logs estruturados
│   └── logger.py       # Logs gerais + auditoria separada
│
├── risk/               # Motor de risco (PRIORIDADE MÁXIMA)
│   └── risk_engine.py  # Valida TODA operação antes de executar
│
├── strategies/         # Estratégias determinísticas (não-IA)
│   ├── base_strategy.py             # Interface abstrata
│   ├── example_strategy.py          # Exemplo: SMA20 (só para testes)
│   ├── ema_rsi_strategy.py          # Placeholder de integração (não-trading)
│   ├── trend_pullback_strategy.py   # FASE 10 — Tendência + pullback (BUY-only)
│   └── volatility_breakout_strategy.py  # FASE 10 — Rompimento + volatilidade + filtro direcional
│
├── exit_policy/        # FASE 11 — Decisão determinística de saída (não executa)
│   ├── exit_decision.py   # ExitDecision/Reason/Source/PositionSide/OpenPositionState
│   ├── exit_policy.py     # ExitPolicy (provider-agnostic; capability ≠ autorização)
│   └── paper_session.py   # FASE 13 — PaperExitOrchestrator (opt-in, fecha posições paper)
│
│   # FASE 12 — Integração ExitPolicy ↔ BacktestEngine opt-in:
│   # - backtesting/exit_policy_adapter.py (helper puro)
│   # - BacktestEngine.use_exit_policy=False por padrão
│   # FASE 13 — Paper Activation + Demo SL/TP Readiness:
│   # - PaperExitOrchestrator (acima) fecha posições paper sem abrir.
│   # - BybitDemoPreflight valida take_profit (opt-in).
│   # - scripts/run_bybit_demo_diagnostic.py --prepare-demo-v2-order (OFFLINE).
│   # FASE 15 — Post-Demo v2 Reconciliation Hardening:
│   # - BybitClient.get_executions (read-only fallback).
│   # - BybitDemoExecutor: triangulação via executions + positions,
│   #   FILLED_BY_TRIANGULATION conservador (não dispara record_trade_opened).
│   # - scripts/run_bybit_demo_diagnostic.py --post-session-check (read-only).
│
├── operational_safety/   # FASE 16 — Máquina consultiva de safety state
│   ├── safety_state.py        # SafetyState/SafetyEvent/InvalidSafetyTransition
│   └── safety_state_machine.py  # SafetyStateMachine (provider-agnostic)
│
├── operational_profile/  # FASE 16 — Perfis operacionais provider-agnostic
│   ├── profile.py             # OperationalProfile frozen dataclass
│   ├── factories.py           # build_personal/prop_challenge/hyrotrader_template/custom
│   ├── validation.py          # validate_profile_self + cross-config (puro, offline)
│   └── risk_adapter.py        # FASE 18 — Gate explícito Profile → novo RiskConfig (não muta base)
│
├── session_runner/       # FASE 17 — Supervisor paper-only com gates safety+profile
│   ├── config.py              # SessionRunnerConfig (clock/sleep injetáveis)
│   ├── result.py              # SessionRunResult/SessionBlockEvent/SessionStopReason
│   └── runner.py              # SessionRunner — pipeline construído UMA vez; preserva estado entre ciclos
│
├── demo_session_readiness/  # FASE 19 — Camada read-only de preparação gated
│   ├── flags_adapter.py       # SafetyFlags (frozen) + helpers duck-typed (sem rede)
│   └── readiness_check.py     # DemoSessionReadinessCheck — 6 gates / DOES NOT EXECUTE
│   # is_ready_for_gated_demo é SINAL — não autoriza ordem. Provider-agnostic.
│   # bybit_demo_linear continua OPT_IN; ProviderRegistry consultado read-only.
│
├── challenge_readiness/  # FASE 23 — Challenge Readiness + Endurance Progressivo
│   ├── stages.py              # ChallengeEnduranceStage + STAGE_DEFINITIONS
│   ├── readiness.py           # ChallengeReadinessConfig + Report + Status + build_*
│   ├── result.py              # ChallengeEnduranceResult (frozen, JSON, to_ui_snapshot)
│   └── endurance_runner.py    # ChallengeEnduranceRunner (paper-only, reusa SessionRunner)
│   # Paper-only nesta fase. DEMO_* permanece planned-only.
│   # Provider-agnostic: nao importa BybitClient/BybitDemoExecutor/httpx/requests.
│   # Challenge target eh KPI; NUNCA bloqueia por lucro insuficiente.
│   # CLI: scripts/run_challenge_endurance.py (ASCII-only, paper-only).
│   # Docs: challenge_readiness.md, endurance_progression.md, _ui_snapshot.md
│
├── demo_session_execution/  # FASE 20 — Gate single-shot + plan + outcome
│   ├── plan.py                # SignalBlueprint + DemoSessionPlan + build_demo_session_plan
│   ├── outcome.py             # DemoSessionOutcome + RecommendedNextAction
│   ├── gate.py                # execute_demo_session_gated — SINGLE-SHOT, 10 gates antes do executor
│   └── api_blueprint.py       # FASE 22 — DemoApiBlueprint + bridge OrderProposal->SignalBlueprint
│   # dry_run=True default. Executor injetado via DemoExecutorProtocol (duck-typed).
│   # NÃO importa BybitClient/BybitDemoExecutor/httpx/requests/SessionRunner/BotEngine.
│   # bybit_demo_linear continua OPT_IN; SessionRunner permanece paper-only.
│   # FASE 21 entrega o operator wiring em scripts/run_bybit_demo_session_gated.py
│   # (4 CLI flags + interactive Y prompt + .env demo válido + ALL gates internos).
│   # FASE 22 adiciona --prepare-demo-blueprint / --from-blueprint para fluxo
│   # API-driven (reaproveita BybitDemoPreflight; sem hardcode entry/sl/tp/size).
│   # Runbook: docs/demo_session_first_real_order_runbook.md
│   # Blueprint doc: docs/api_driven_demo_blueprint.md
│   # Auditoria: docs/hardcoded_values_audit_phase22.md
│
├── exchange/           # Abstrações de exchange
│   ├── base_exchange.py    # Interface comum
│   ├── mock_exchange.py    # Simulação sem API (paper trading)
│   └── bybit_client.py     # ⛔ BLOQUEADO até FASE 3
│
├── execution/          # Executores de ordens
│   ├── paper_trader.py            # Executor simulado (mock) — DEFAULT
│   ├── paper_orchestrator.py      # FASE 4 — sessões de paper trading
│   ├── bybit_testnet_executor.py  # FASE 5 — ordens testnet (manual, triple-lock)
│   ├── executor_protocol.py       # FASE 6 — contrato ExecutorProtocol
│   ├── testnet_executor_adapter.py# FASE 6 — adapta testnet ao BotEngine (dry_run obrigatório)
│   ├── provider_capability.py     # FASE 8 — modelo de capabilities + ProviderStatus
│   ├── provider_registry.py       # FASE 8 — registry singleton + assert_usable
│   └── providers/                 # FASE 8 — adapters esqueleto opt-in
│       ├── binance_futures_testnet_adapter.py  # DRY_RUN_ONLY
│       └── hyrotrader_cleo_adapter.py          # UNCONFIRMED
│
├── data/           # Coleta de dados (TODO FASE 3)
├── indicators/     # Indicadores técnicos (TODO FASE 3)
├── backtesting/    # Backtesting (TODO FASE 3)
└── ai_assistant/   # IA auxiliar — NÃO decide trades (TODO FASE 4)
```

---

## Camadas de Segurança

### Triple-Lock para Live Trading

Para habilitar execução real, TRÊS condições devem ser satisfeitas:

```
1. .env: TRADING_MODE=live
2. .env: ENABLE_LIVE_TRADING=true
3. Código: guard.assert_live_allowed(confirm_live_trading=True)
```

Qualquer condição ausente → `TradingModeError` lançada.

### RiskEngine Soberano

Toda operação passa por 11 verificações em sequência:
1. Modo seguro (ModeGuard)
2. Validade do sinal
3. Stop loss presente
4. Stop loss mínimo
5. Stop loss máximo
6. Limite de perda total
7. Limite de perda diária
8. Máximo de trades hoje
9. Exposição por ativo
10. Alavancagem máxima
11. Capital suficiente

A primeira falha bloqueia e registra em auditoria.

---

## Regras de IA

- A IA **NUNCA** decide compra, venda, stop loss ou posição
- A IA pode ser usada para: análise de notícias, resumo de logs, classificação de eventos
- Módulo `ai_assistant/` é somente auxiliar e não tem acesso ao executor
- Implementação de IA planejada para FASE 4+

---

## Fluxo de Dados de Mercado (FASE 3A)

```
Bybit V5 API (internet, somente leitura)
    │ GET /v5/market/kline
    │ GET /v5/market/tickers
    │ GET /v5/market/orderbook
    ↓
BybitClient (exchange/bybit_client.py)
    • Sem autenticação
    • category="linear" para BTCUSDT perp
    • Decimal para parse de valores financeiros
    • Timeout, retry, tratamento de erros HTTP
    ↓
MarketDataService (data/market_data.py)
    • Abstrai o cliente de exchange
    • Funciona com MockExchange OU BybitClient
    • Métodos: get_candles(), get_ticker(), get_latest_price(), get_order_book()
    • build_market_data_dict() → formato usado pelas estratégias
    ↓
Strategy.generate_signal(market_data)
    • Nunca acessa BybitClient diretamente
    • Recebe dict padronizado do MarketDataService
```

---

## Roadmap de Fases

| Fase | Status | Escopo |
|------|--------|--------|
| 1 | ✅ | Análise e arquitetura |
| 2 | ✅ | Estrutura base, ModeGuard, RiskEngine, PaperTrader — 98 testes |
| 3A | ✅ | Market data Bybit read-only, MarketDataService — 167 testes |
| 3B | ⏳ | Bybit testnet, autenticação, execução testnet |
| 3C | ⏳ | Backtesting, indicadores técnicos (`ta` lib) |
| 4 | ⏳ | Estratégias validadas, análise avançada |
| 5 | ⏳ | ML/AI auxiliar, Polymarket, notícias |
| 6 | ⏳ | Live trading (após validação completa) |

---

## Dependências Externas

| Dependência | Uso | Status |
|------------|-----|--------|
| pydantic-settings | Configuração validada | ✅ Ativo |
| loguru | Logs estruturados | ✅ Ativo |
| python-dotenv | Variáveis de ambiente | ✅ Ativo |
| pandas | Dados de mercado | ✅ Ativo |
| numpy | Cálculos numéricos | ✅ Ativo |
| pybit | Bybit API | ⏳ FASE 3 |
| pandas-ta | Indicadores técnicos | ⏳ FASE 3 |
| vectorbt | Backtesting | ⏳ FASE 3 |
| openai | IA auxiliar | ⏳ FASE 4 |
