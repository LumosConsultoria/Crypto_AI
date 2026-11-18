# Provider Layer — FASE 8

> ⚠️ **PaperTrader continua o caminho default absoluto do BotEngine.** Nenhum provider externo vira default por esta fase.
> ⚠️ **Mainnet/live permanece BLOQUEADO.** `assert_live_allowed` intocado; `provider_id` mainnet/live é rejeitado no validator.
> ⚠️ **Testnet/demo NÃO garante performance futura.** Custos, fills, latência, liquidez e regras diferem da mainnet.

---

## Visão geral

A FASE 8 introduz uma **camada de capabilities + registry** para tornar o bot **provider-agnostic** de verdade. O bot agora "conhece" 4 providers explicitamente — sem implementar execução real para os que ainda não foram aprovados.

```
Strategy → FeatureEngine → RiskEngine (soberano)
                              │
                              ▼
                ExecutorProtocol.execute(risk_result)
                              │
                              ▼
         PaperTrader (default)   ou   ProviderAdapter (opt-in)
                                              │
                                              ▼
                              ProviderCapability + ProviderRegistry
                                              │
                                              ▼
                              ModeGuard.assert_provider_allowed
```

---

## Providers registrados (FASE 8)

| provider_id | Status | Capability `confirmed` | Notas |
|---|---|---|---|
| `paper` | **ACTIVE** | `True` | Default seguro. PaperTrader local. |
| `bybit_testnet_linear` | **RESTRICTED** | `True` (capabilities) | Código FASE 5/6 intacto. Operador atual sem acesso ao produto derivativo. |
| `bybit_demo_linear` | **OPT_IN** | `False` | FASE 9 Fatias 1+2+3+4A+4B — config + client + ModeGuard + `BybitDemoExecutor` com `execute(dry_run=False)` implementado via `place_market_order` + reconciliação. Safe-check real validado. Registry exige `confirm_provider=True`. Envio real fica nas mãos do operador via script gated. Endpoint `api-demo.bybit.com`. Ver [bybit_demo_trading.md](bybit_demo_trading.md). |
| `binance_futures_testnet` | **DRY_RUN_ONLY** | `False` | Adapter esqueleto. Sem httpx. Integração real em fase futura. |
| `hyrotrader_cleo_demo` | **UNCONFIRMED** | `False` | Mecanismo de integração não confirmado. Capabilities todas `False`. |
| `tealstreet_cli_gateway` | **DRY_RUN_ONLY** | `False` | FASE 9B — adapter monta comando CLI + payload de webhook sem executar. Sem subprocess, sem httpx. Uso real depende de ToS HyroTrader. Ver [tealstreet_gateway.md](tealstreet_gateway.md). |

`ProviderStatus`:
- `ACTIVE` — passa em `assert_usable` sem confirmação.
- `OPT_IN` — passa só com `confirm_provider=True`.
- `DRY_RUN_ONLY` — bloqueia execução real.
- `FROZEN` — bloqueado por decisão arquitetural.
- `RESTRICTED` — bloqueado por restrição externa (regulatória/conta).
- `UNCONFIRMED` — bloqueado até capabilities serem confirmadas.
- `CANDIDATE_REVALIDATION` (FASE 9 Fatia 2) — bloqueado; semântica "evidência operacional preliminar coletada, requer adaptação técnica antes de OPT_IN".

---

## `ProviderCapability` — modelo de suporte

Frozen dataclass que **DESCREVE** o que um provider sabe fazer:

- Tipos de ordem: `supports_market_order`, `supports_limit_order`.
- SL/TP: `supports_stop_loss`, `supports_take_profit`.
- Posição: `supports_reduce_only`, `supports_leverage_api`.
- Consultas: `supports_positions_query`, `supports_balance_query`, `supports_cancel_order`.
- Transporte (FASE 9B): `supports_webhook`, `supports_cli`.
- Ambiente: `is_demo_environment`, `is_live_environment` (sempre `False` para os 5 atuais).
- Confirmação: `confirmed`, `confirmation_source`, `notes`.
- Documentação: `documented_assets: tuple[str, ...]`.

**Não armazena**: capital, sizing, leverage, risco, URLs, credenciais, factories.

**Default seguro**: tudo `False`, `confirmed=False`. Adicionar suporte exige declaração explícita.

---

## `ProviderRegistry` — trava de execução

Registry em memória com os 4 providers FASE 8 registrados na importação. Não instancia clientes externos.

```python
from crypto_trading_bot.execution import get_registry, ProviderBlockedError

registry = get_registry()
registry.assert_usable("paper")                # OK (ACTIVE)
registry.assert_usable("bybit_testnet_linear") # ProviderBlockedError (RESTRICTED)
registry.assert_usable("binance_futures_testnet")  # ProviderBlockedError (DRY_RUN_ONLY)
registry.assert_usable("hyrotrader_cleo_demo")     # ProviderBlockedError (UNCONFIRMED)

# Para OPT_IN futuros:
registry.assert_usable("some_optin", confirm_provider=True)  # passa
```

`audit_snapshot()` devolve um dict sanitizado (sem credenciais, sem factories) — usado para auditoria e populado em `BotCycleResult.provider_snapshot` (campo opcional, paralelo a `executor_result`/`trade` legados).

---

## `ModeGuard.assert_provider_allowed` — delegação

Método novo, **complementar e não destrutivo**:

```python
guard.assert_provider_allowed("paper")               # passa
guard.assert_provider_allowed("bybit_testnet_linear") # TradingModeError
```

**NÃO substitui** nem afrouxa:
- `assert_safe_mode` / `assert_not_live` (modo live continua bloqueado).
- `assert_live_allowed` (triple-lock de live intocado).
- `assert_testnet_execution_allowed` (triple-lock de testnet intocado).

---

## Settings

`Settings.provider_id: Literal["paper", "bybit_testnet_linear", "binance_futures_testnet", "hyrotrader_cleo_demo"]` (default `"paper"`).

Validator rejeita: `"live"`, `"mainnet"`, `"real"`, `"production"`, `"prod"`, `"bybit_mainnet"`, `"binance_mainnet"`, `"hyrotrader_real"`, `"bybit_live"`, `"binance_live"`.

`provider_id` é **ortogonal** a `executor_type` (FASE 6, wiring no BotEngine). `provider_id` é apenas metadata do registry. Mudá-lo NÃO autoriza execução real — o registry + ModeGuard continuam soberanos.

---

## Ciclo de vida de um provider

```
UNCONFIRMED  →  DRY_RUN_ONLY  →  OPT_IN  →  ACTIVE
   │                │              │            │
   │ capabilities   │ adapter       │ adapter    │ adapter
   │ todas False    │ dry-run       │ real (com  │ real (sem
   │                │ esqueleto     │ confirm)   │ confirm)
```

Cada transição exige:
1. Evidência operacional documentada (`confirmation_source` preenchido).
2. Capabilities reais marcadas `True`.
3. Aprovação humana explícita.
4. Testes offline cobrindo os caminhos.
5. Atualização do registry (`status` e `reason`).

**Nenhum provider externo deve ser promovido a `ACTIVE` sem essa esteira completa.**

---

## Garantias arquiteturais

| Garantia | Como |
|---|---|
| PaperTrader continua default | `Settings.provider_id` default = "paper"; PaperTrader não foi alterado |
| Bybit preservada | `BybitClient`, `BybitTestnetExecutor`, `TestnetExecutorBotAdapter` intactos; apenas reclassificada como `RESTRICTED` |
| CLEO sem assumir mecanismo | Capability all `False`; status `UNCONFIRMED`; execute sempre `success=False` |
| Binance sem internet | Adapter esqueleto sem httpx; `dry_run=False` levanta NotImplementedError |
| Mainnet/live bloqueado | Validator rejeita `provider_id` mainnet/live; `is_live_environment=False` em todos os providers FASE 8 |
| RiskEngine soberano | Adapters chamados APÓS `validate_signal`; rejeitam `risk_result.approved=False` |
| Sem dependência nova | Apenas stdlib + pydantic já presente |
| Sem hardcode operacional | Capabilities descrevem suporte (bool), nunca capital/sizing/leverage/risco |
| Auditoria sem secrets | `audit_snapshot` retorna apenas dict sanitizado |

---

## Próximos passos por provider (não implementar sem aprovação)

- **CLEO**: aguardar respostas das perguntas em [hyrotrader_cleo.md](hyrotrader_cleo.md). Especialmente o gate de **ToS sobre automação**.
- **Binance**: implementar cliente HTTP + HMAC em fase própria, mantendo testes offline. Promover de `DRY_RUN_ONLY` → `OPT_IN` após cobertura mockada.
- **Bybit**: aguardar resolução da restrição regional/regulatória externa. Reclassificar para `OPT_IN` quando aplicável.
- **Paper**: nada a fazer — já é o default seguro e auditado.
