# Paper Trading Orquestrado — FASE 4

> ⚠️ **Paper trading NÃO garante performance futura.**
> ⚠️ Toda execução é simulada via `MockExchange` + `PaperTrader`. **ZERO** ordens reais, **ZERO** API key, **ZERO** endpoint privado.
> ⚠️ Nenhum caminho do orquestrador instancia `BybitClient`.

---

## Visão geral

A FASE 4 entrega o `PaperTradingOrchestrator` — uma camada que **reaproveita** o `BotEngine` (intocado) e adiciona:

- Configuração rica via `PaperSessionConfig` (imutável).
- Integração com `StrategySpec` da FASE 3F (Strategy Research Framework).
- Source de candles configurável: `MOCK_EXCHANGE`, `CACHE` (FASE 3G), `INMEMORY`.
- Loop controlado por `max_cycles` + intervalo + `stop()` manual.
- `dry_run` que força HOLD em todos os ciclos (audita pipeline sem executar).
- `PaperSessionResult` agregando métricas + cycle results auditáveis.

---

## Garantias arquiteturais

| Garantia | Como |
|---|---|
| `BotEngine` intocado | Apenas instanciado por sessão. |
| `PaperTrader` / `MockExchange` / `RiskEngine` / `ModeGuard` intocados | Reaproveitados via DI. |
| `BybitClient` NUNCA instanciado pelo orquestrador | Confirmado por teste com `patch` que falharia se BybitClient fosse criado. |
| `RiskEngine` soberano | INVARIANTE preservada via `BotEngine`: `PaperTrader.execute` só aceita `risk_approved=True`. |
| Capital configurável | `PaperSessionConfig.capital` é **OBRIGATÓRIO**. Sem default 5000. Funciona com 1k, 5k, 10k, 25k. |
| Provider-agnostic | Config nunca menciona `provider_name`. |
| Cada sessão = instâncias FRESCAS | Sem state leak entre sessões consecutivas. |
| Sem dependência nova | Apenas stdlib + módulos existentes. |

---

## Componentes

### `CandlesSource` (enum)

| Valor | Significado |
|---|---|
| `MOCK_EXCHANGE` | `MockExchange` random walk (não-determinístico). Default. |
| `CACHE` | Carrega de `DataCache` (FASE 3G). Requer `cached_symbol`+`cached_timeframe`. |
| `INMEMORY` | Usa `inmemory_candles: Tuple[Candle, ...]` fornecidos. |

> ⚠️ **`CACHE` e `INMEMORY` extraem apenas os closes** para popular `MockExchange._price_history`. OHLCV completo NÃO é preservado por aqui. Para precisão OHLCV total, use `BacktestEngine`.

### `PaperSessionConfig` (frozen dataclass)

```python
from crypto_trading_bot.execution import PaperSessionConfig, CandlesSource

config = PaperSessionConfig(
    spec=my_strategy_spec,           # StrategySpec da FASE 3F
    spec_config_override={"x": 1},   # mescla sobre default_config

    symbol="BTCUSDT",
    timeframe="15",
    capital=10000.0,                 # ⚠️ OBRIGATÓRIO — sem default fixo

    candles_source=CandlesSource.MOCK_EXCHANGE,
    # Para CACHE: cached_symbol=..., cached_timeframe=...
    # Para INMEMORY: inmemory_candles=tuple(...)

    max_cycles=20,
    cycle_interval_seconds=0.0,      # 0 = replay rápido
    dry_run=False,                   # True → força HOLD em todos os ciclos

    simulated_fee_pct=0.001,         # fee do MockExchange (default 0.1%)
)
```

**Validações em `__post_init__`:**
- `capital` é **OBRIGATÓRIO** (não há default 5000). Sem capital → `ValueError` claro.
- `capital > 0`, `max_cycles > 0`, `cycle_interval_seconds >= 0`, `simulated_fee_pct >= 0`.
- `CACHE` exige `cached_symbol` + `cached_timeframe`.
- `INMEMORY` exige `inmemory_candles` não-vazio.
- `spec_config_override` é convertido para `MappingProxyType` (read-only).

### `PaperSessionResult` (frozen dataclass)

```python
@dataclass(frozen=True)
class PaperSessionResult:
    config: PaperSessionConfig
    n_cycles_completed: int
    cycle_results: Tuple[BotCycleResult, ...]
    paper_summary: Mapping[str, Any]        # PaperTrader.get_summary()
    risk_summary: Mapping[str, Any]         # RiskEngine.get_status_summary()
    started_at: datetime
    ended_at: datetime
    stopped_reason: str                     # "max_cycles" | "manual_stop" | "error"
    dry_run_active: bool
```

**Properties úteis:**
- `total_executions`, `total_holds`, `total_risk_blocked`, `total_safety_blocked`.
- `total_pnl_usd`.

**Métodos:**
- `summary_text()` — saída textual com **aviso obrigatório** de não-garantia.
- `to_dict()` — JSON-friendly.

### `PaperTradingOrchestrator`

```python
from crypto_trading_bot.execution import PaperTradingOrchestrator

orchestrator = PaperTradingOrchestrator()

result = orchestrator.run_session(config)
print(result.summary_text())

# Stop manual (cross-thread ou pré-set):
orchestrator.stop()                          # sinaliza
result = orchestrator.run_session(config)    # encerra antes do 1º ciclo
# stopped_reason = "manual_stop"
```

**Pipeline construído por sessão:**

```
MockExchange (fresco, fee customizada, capital injetado)
    └─ MarketDataService (symbol/timeframe)
        └─ FeatureEngine (fresco)
            └─ Strategy (criada UMA vez por sessão via spec.factory)
                └─ RiskEngine (fresco, capital injetado)
                    └─ PaperTrader (fresco)
                        └─ BotEngine (fresco)
                            └─ loop run_once() × max_cycles
```

Cada sessão é **completamente isolada**. Sem state leak.

---

## Modo `dry_run`

Quando `dry_run=True`:

1. O orquestrador embrulha a estratégia em um wrapper que **força HOLD** em todos os ciclos.
2. `PaperTrader.execute()` nunca é chamado.
3. `cycle_result.action == "hold"` para todos os ciclos.
4. `result.dry_run_active == True`.
5. `summary_text()` torna explícito: "🔍 DRY-RUN ATIVO".

Útil para auditar o pipeline (MarketData, Features, RiskEngine) **sem** abrir trades simulados.

---

## Capital obrigatório (sem hardcode)

O orquestrador é **agnóstico de tamanho de conta**. Funciona com:

- Conta pessoal: `capital=500.0` ou `capital=1000.0`.
- Prop challenge 5k: `capital=5000.0`.
- Prop challenge 10k: `capital=10000.0`.
- Prop funded 25k: `capital=25000.0`.
- Qualquer valor customizado.

**Não há default fixo de 5000.** Omitir `capital` no `PaperSessionConfig` levanta `ValueError`:

```python
PaperSessionConfig(spec=spec)        # raises ValueError: "capital é OBRIGATÓRIO"
PaperSessionConfig(spec=spec, capital=None)    # raises
PaperSessionConfig(spec=spec, capital=0.0)     # raises
PaperSessionConfig(spec=spec, capital=-100.0)  # raises
```

---

## FASE 13 — Paper Activation (opt-in)

`PaperExitOrchestrator` é o ponto de ativação opt-in da `ExitPolicy`
no fluxo paper. **Default permanece off**: sem instanciá-lo, o
`PaperTrader` e o `PaperTradingOrchestrator` continuam exatamente como
estavam.

### Uso

```python
from crypto_trading_bot.execution.provider_capability import ProviderCapability
from crypto_trading_bot.exit_policy import ExitPolicy, PaperExitOrchestrator

policy = ExitPolicy(
    provider_capability=ProviderCapability(
        provider_id="paper", supports_reduce_only=True,
    ),
    max_time_in_position_seconds=None,           # opcional
    allow_close_on_opposite_signal=False,        # opcional
    emergency_close_enabled=False,               # opcional
)

orchestrator = PaperExitOrchestrator(paper_trader, policy)

# A cada candle, o caller chama:
decisions = orchestrator.on_candle(
    candle=candle,
    now=datetime.now(timezone.utc),
    latest_signal=latest_strategy_signal,   # opcional, para opposite
    manual_close={trade_id: True},          # opcional, para fechamento manual
    emergency_active=False,                 # opcional, kill switch
)
```

### Regras preservadas

- **Nunca abre posição.** Só fecha posições já abertas.
- **Anti-flip**: opposite signal gera fechamento; nova entrada nunca acontece
  no mesmo ciclo (PaperTrader não abre nada).
- **RiskEngine soberano**: `close_trade` chama `record_trade_closed`.
- **Capability ≠ autorização**: o `auto_execute_blocked` reportado no
  snapshot é apenas a camada técnica. Paper não envia ordem real.
- **Provider-agnostic**: o orquestrador consome `ProviderCapability`,
  sem importar `BybitClient` / executores / `httpx`.

### Preço de fechamento determinístico

| Motivo | close_price |
|---|---|
| STOP_LOSS       | `signal.stop_loss_price` |
| TAKE_PROFIT     | `signal.take_profit_price` |
| TIME_LIMIT      | `candle.close` |
| OPPOSITE_SIGNAL | `candle.close` |
| MANUAL/EMERGENCY| `candle.close` se houver candle; senão `signal.entry_price` |

PnL é calculado pelo `PaperTrader.close_trade` (lógica existente).

### Novos status em `PaperTradeStatus`

- `CLOSED_TIME_LIMIT`
- `CLOSED_OPPOSITE_SIGNAL`
- `CLOSED_EMERGENCY`

Os valores anteriores (`OPEN`, `CLOSED_STOP_LOSS`, `CLOSED_TAKE_PROFIT`,
`CLOSED_MANUAL`, `FAILED`) permanecem inalterados — compat. de serialização.

### Snapshot opcional

`PaperTrade.exit_decision_snapshot: Optional[dict]` é populado **apenas**
quando o trade é fechado via `PaperExitOrchestrator`. Quando preenchido,
contém `reason`, `source`, `requires_reduce_only`, `auto_execute_blocked`,
`capability_allows_auto_close`, `provider_id`, `trigger_price`,
`elapsed_candles`, `elapsed_seconds`. **Não contém** `execution_allowed`.

> ⚠️ Demo v2 (FASE 14): a ativação real para Bybit Demo permanece bloqueada.
> Veja [bybit_demo_v2_readiness.md](bybit_demo_v2_readiness.md).

---

## CLI: `scripts/run_paper_orchestrated.py`

```bash
# Capital sempre obrigatório
python scripts/run_paper_orchestrated.py --cycles 5 --source mock --capital 1000

# Dry-run
python scripts/run_paper_orchestrated.py --cycles 5 --source mock --capital 1000 --dry-run

# Capital diferente
python scripts/run_paper_orchestrated.py --cycles 5 --source mock --capital 25000

# Com CACHE da FASE 3G (cache deve estar populado previamente)
python scripts/run_paper_orchestrated.py --cycles 5 --source cache \
    --capital 10000 --symbol BTCUSDT --timeframe 15
```

Argumentos relevantes:
- `--capital` (OBRIGATÓRIO)
- `--cycles` (default 10)
- `--source` (`mock` | `cache` | `inmemory`)
- `--symbol`, `--timeframe` (default BTCUSDT/15)
- `--position-size` (default 200)
- `--cycle-interval` (default 0 = replay rápido)
- `--fee-pct` (default 0.001)
- `--dry-run` (flag)

---

## Limitações reconhecidas

1. **`ExecutionCostConfig` da FASE 3E.1 NÃO aplicada em paper.** Apenas `MockExchange.simulated_fee_pct` (fee simples). Para custos avançados (slippage, spread, latência), use `BacktestEngine`.
2. **`CACHE`/`INMEMORY` extraem apenas closes.** OHLCV completo NÃO é preservado pelo replay no MockExchange.
3. **`stop()` é single-thread.** Verificado entre ciclos. Para cross-thread, use sinal externo (signal, threading.Event).
4. **`MockExchange.random_walk` não é determinístico** entre runs (sem seed). Para determinismo, use `CACHE` ou `INMEMORY`.
5. **Paper trading não substitui testnet real.** Não há ordens reais, latência real de rede, ou comportamento real do exchange.

---

## Próximo passo natural

Quando esta fase estabilizar (validação em diferentes capitais, estratégias e cenários), o próximo passo lógico é:

> **FASE 5 — Bybit Testnet Privada Controlada** (a planejar com aprovação explícita)

- Habilitar credenciais de testnet (não live).
- Manter `ModeGuard` rigoroso em testnet.
- Substituir `MockExchange` por `BybitClient` em modo testnet (com `assert_live_allowed` exigindo confirmação explícita).
- Manter `PaperTrader` como fallback para ambientes sem credenciais.

**A FASE 5 só deve ser iniciada após validação extensiva da FASE 4** em paper trading offline.

---

## Reforço final

> ⚠️ Paper trading com dados simulados ou históricos NÃO garante performance em condições reais. Custos, latência, slippage e regimes de mercado podem variar drasticamente. Use stress tests da FASE 3E.3 + walk-forward da FASE 3E.4A + paper extensivo antes de qualquer execução real.
