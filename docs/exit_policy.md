# Exit Policy — FASE 11

Camada determinística e auditável de **decisão de saída** de posições.
A `ExitPolicy` decide *quando* uma posição deve ser fechada e *por quê* — mas
**não** executa nada, **não** chama rede, **não** envia ordem, **não** chama
exchange ou executor real.

## Princípios

- 100% offline. ZERO API real. ZERO API key. ZERO ordem.
- Provider-agnostic: consome apenas `ProviderCapability` (frozen dataclass).
- Determinística: mesma entrada → mesma decisão.
- Auditável: cada decisão de fechamento emite uma única linha estruturada.
- Não chama `RiskEngine`. O `RiskEngine` permanece como segunda camada de
  proteção (anti-flip, invariantes) sem alteração nenhuma.
- Não chama executor (`BybitDemoExecutor`, `BybitTestnetExecutor`,
  `PaperTrader`). Apenas decide; a integração futura é fora de escopo.

## Capability ≠ autorização de execução

`ExitDecision.auto_execute_blocked` reflete **apenas** a camada técnica do
provider (`supports_reduce_only` em `ProviderCapability`).

> **Mesmo com `auto_execute_blocked=False`, execução real continua dependendo de:**
> 1. `ProviderStatus` permitido no `ProviderRegistry`;
> 2. `ModeGuard` adequado (paper / testnet / demo / live);
> 3. Ambiente correto e credenciais válidas;
> 4. Confirmação humana / gate de execução;
> 5. `RiskEngine` em estado consistente;
> 6. Fase futura de integração com o executor.

O `metadata` da `ExitDecision` expõe `capability_allows_auto_close`, mas
**não** expõe `execution_allowed`, `executor_authorized` nem `ready_to_execute`.
Capability é capacidade técnica; autorização é responsabilidade dos gates
existentes (`ModeGuard`, `assert_live_allowed`, `ProviderRegistry`).

## Bypass de `reduceOnly` proibido

O parâmetro `require_reduce_only_for_auto_close=False` apenas reporta
`requires_reduce_only=False` na decisão — **não** desbloqueia
`auto_execute_blocked` em providers sem `supports_reduce_only`. O override
existe somente para uso em paper/backtest/manual e emite warning no logger.

## Ordem de precedência (hard-coded)

1. **EMERGENCY** — se `emergency_close_enabled=True` e `emergency_active=True`.
2. **MANUAL** — `manual_close_requested=True`.
3. **STOP_LOSS** — candle bate o stop. Vence TP no mesmo candle (regra
   conservadora, idêntica à do `BacktestEngine`).
4. **TAKE_PROFIT** — candle bate o TP, e o SL não bateu.
5. **OPPOSITE_SIGNAL** — sinal contrário da estratégia, se
   `allow_close_on_opposite_signal=True`.
6. **TIME_LIMIT** — por candles (`max_time_in_position_candles`, modo
   backtest) **ou** por segundos (`max_time_in_position_seconds`, modo live).
7. **Default** — `should_close=False`, `reason=NONE`, `source=NONE`.

## Anti-flip

Sinal contrário com posição aberta gera `ExitDecision(OPPOSITE_SIGNAL)` —
nunca uma nova entrada na direção oposta no mesmo ciclo. A entrada nova só
pode ocorrer **depois** que a saída foi confirmada/reconciliada — trabalho
de fase futura. O `RiskEngine` permanece como segunda camada de proteção
(invariante "uma posição por símbolo"), inalterado.

## Matriz de providers (snapshot atual)

| Provider | `supports_reduce_only` | `auto_execute_blocked` | Observação |
|---|---|---|---|
| `bybit_demo_linear` | False | True | Fechamento **continua manual via UI** até fase futura específica. |
| `bybit_testnet_linear` | False | True | Auto-close por API bloqueado. |
| `binance_futures_testnet` | True | False | Capability OK; execução real ainda depende de status + ModeGuard + integração. |
| `tealstreet_cli_gateway` | False | True | — |
| `hyrotrader_cleo_demo` | False | True | — |

A Binance é o único caso em que o gate de capability libera auto-close. Isso
**não promove** o provider, **não** o coloca em `ACTIVE` no
`ProviderRegistry`, e **não** habilita execução real nesta fase.

## TP teórico (backtest) vs. TP real (provider)

O `BacktestEngine` detecta `take_profit_hit` quando `candle.high >= tp_price`.
Em execução real (live/demo/testnet), o preenchimento de uma ordem TP
depende de wick, gap, slippage, profundidade do livro e do tipo de ordem
suportado pelo provider. A `ExitPolicy` **decide** a saída usando a mesma
regra que o backtest; quem traduz a decisão em ordem real (fase futura)
precisa lidar com a diferença.

> **Backtest com TP não garante execução perfeita no provider real.**

## TP opcional — risco documentado

`OpenPositionState.take_profit_price` é `Optional[float]`. Estratégias que
não emitem TP são aceitas por retrocompatibilidade, mas operacionalmente
isso é uma lacuna: a posição depende apenas de SL, manual, time-limit ou
opposite signal para sair. Estratégias candidatas a produção devem sempre
emitir TP.

## Linha de auditoria

Cada `ExitDecision` com `should_close=True` emite **exatamente uma** linha:

```
EXIT_DECISION | reason=<reason> | source=<source> | symbol=BTCUSDT |
side=<buy|sell> | reduce_only_required=<bool> | auto_blocked=<bool> |
entry=<price> | trigger=<price|n/a> | elapsed=candles=<n>,seconds=<s> |
provider_cap=<provider_id>
```

A linha **não contém** API keys, secrets, headers, signatures, e-mail ou
qualquer PII. Auditada por 9 testes em `tests/test_exit_policy_audit_logging.py`.

## Arquivos

| Arquivo | Conteúdo |
|---|---|
| `src/crypto_trading_bot/exit_policy/exit_decision.py` | `ExitDecision`, `ExitReason`, `ExitSource`, `PositionSide`, `OpenPositionState`, `make_hold_decision` |
| `src/crypto_trading_bot/exit_policy/exit_policy.py` | `ExitPolicy` |
| `src/crypto_trading_bot/exit_policy/__init__.py` | exports públicos |
| `tests/test_exit_decision.py` | 18 testes de contrato e invariantes |
| `tests/test_exit_policy_rules.py` | 21 testes de precedência |
| `tests/test_exit_policy_anti_flip.py` | 6 testes de anti-flip + isolamento |
| `tests/test_exit_policy_reduce_only_gate.py` | 8 testes do gate de capability |
| `tests/test_exit_policy_provider_matrix.py` | 8 testes (matriz dos 5 providers) |
| `tests/test_exit_policy_audit_logging.py` | 9 testes de audit determinístico |

## O que esta fase NÃO faz

- Não altera `BacktestEngine`, `PaperTrader`, `BotEngine`, `RiskEngine`,
  `ModeGuard`, `assert_live_allowed`, `ProviderRegistry`, `ProviderCapability`,
  `BybitClient`, `BybitDemoExecutor`, `BybitTestnetExecutor`, `walk_forward`,
  `ExecutionCostConfig`, providers, estratégias ou qualquer módulo existente.
- Não envia ordem real, demo ou testnet.
- Não promove provider para `ACTIVE`.
- Não instala dependência nova.
- Não implementa `close_position` ou `cancel_order` reais.
- Não substitui a lógica inline de SL/TP do `BacktestEngine` — essa
  migração é trabalho de fase futura (FASE 12+).

## Fases futuras sugeridas

- ✅ **FASE 12 (concluída):** ExitPolicy integrada no `BacktestEngine`
  atrás de flag `use_exit_policy=False` por default.
- ✅ **FASE 13 (concluída):** Paper Activation + Bybit Demo SL/TP Readiness.
  `PaperExitOrchestrator` entrega ativação opt-in da ExitPolicy no paper
  (ver [paper_trading.md](paper_trading.md)). `BybitDemoPreflight` agora
  valida `take_profit` quando `target_take_profit_factor` é fornecido.
  `BybitClient.place_market_order` já enviava `takeProfit` ao payload V5
  da Bybit, e `BybitDemoExecutor` já repassava `signal.take_profit_price`
  ao `BybitClient` (auditado por inspeção de fonte). Sub-modo
  `--prepare-demo-v2-order` foi adicionado ao
  `scripts/run_bybit_demo_diagnostic.py` — **offline**, sem rede.
- **FASE 14 (futura, atrás de gate):** Demo v2 — uma única ordem real com
  SL+TP atrelados. Sem `close_position` automático.
- **FASE 15+ (futura):** se `bybit_demo_linear` passar a expor
  `supports_reduce_only=True`, considerar `close_position()` automático
  com gate dedicado.

## FASE 12 — Como ativar a integração no backtest

```python
from crypto_trading_bot.backtesting.backtest_engine import BacktestEngine
from crypto_trading_bot.execution.provider_capability import ProviderCapability
from crypto_trading_bot.exit_policy import ExitPolicy

policy = ExitPolicy(
    provider_capability=ProviderCapability(
        provider_id="paper", supports_reduce_only=True,
    ),
    # opcionais; default desligado:
    max_time_in_position_candles=None,
    allow_close_on_opposite_signal=False,
)

engine = BacktestEngine(
    strategy=..., risk_engine=..., feature_engine=...,
    use_exit_policy=True,         # ← opt-in (default False)
    exit_policy=policy,
)
report = engine.run(candles)
```

> **Default:** `use_exit_policy=False`. Sem essa flag, o BacktestEngine
> roda o caminho legado byte-a-byte. Esta integração é apenas para
> pesquisa/simulação — **não envia ordem real, demo ou testnet**.

### O que muda na saída do trade quando `use_exit_policy=True`

- `BacktestTrade.exit_decision_snapshot` é populado com um dict puro
  contendo `reason`, `source`, `requires_reduce_only`,
  `auto_execute_blocked`, `capability_allows_auto_close`,
  `triggered_at_idx`, `trigger_price`, `elapsed_candles` e
  `elapsed_seconds`.
- `BacktestTrade.to_dict()` inclui a chave `exit_decision_snapshot`
  apenas quando o snapshot não for `None` — schema legado preservado.
- Novos valores de `CloseReason`: `TIME_LIMIT`, `OPPOSITE_SIGNAL`
  (disponíveis somente quando ExitPolicy ativa).

> ⚠️ Reforço final: `ExitPolicy` decide; ela não autoriza. Autorização é
> responsabilidade de `ModeGuard` + `ProviderRegistry` + gates de execução
> existentes. Capability é capacidade técnica, não permissão.
