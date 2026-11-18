# Bybit Demo Trading — FASE 9 Fatias 1 + 2 + 3 + 4A + 4B + 4B-Preflight + 4B-Hardening

> ⚠️ **STATUS NO PROVIDER REGISTRY: `OPT_IN`** (promovido na Fatia 4B).
> `assert_usable("bybit_demo_linear")` continua bloqueando sem `confirm_provider=True`. Promoção para `ACTIVE` continua exigindo execução real bem-sucedida + auditoria de redaction in-memory + revisão arquitetural separada.
> ⚠️ **Bybit Demo Trading NÃO é Bybit Testnet.** Endpoint, ledger, key e UI são diferentes. Não misturar.
> ⚠️ **Demo Trading NÃO garante performance futura.** Slippage, latência, fills e regimes diferem do mercado real.
> ⚠️ **Mainnet/live permanece BLOQUEADO.** `assert_live_allowed` intocado em todas as fatias.

## Mapa das fatias

| Fatia | Entrega | Onde |
|---|---|---|
| **Fatia 1** | `ExchangeConfig` (`environment`/`use_demo`/`resolved_environment`) + `BybitClient(environment="demo")` + `BASE_URL_DEMO` + `_require_private_access` aceita demo | `config/exchange_config.py`, `exchange/bybit_client.py` |
| **Fatia 2** | `TradingMode.DEMO`, `enable_demo_execution`, `ModeGuard.assert_demo_execution_allowed` (triple-lock próprio), `ProviderStatus.CANDIDATE_REVALIDATION`, provider `bybit_demo_linear` registrado, script esqueleto | `config/settings.py`, `core/mode_guard.py`, `execution/provider_capability.py`, `execution/provider_registry.py`, `scripts/run_bybit_demo_diagnostic.py` |
| **Fatia 3** | Safe-check **REAL**: `--safe-check --confirm-demo-execution` chama `get_balance()` em `api-demo.bybit.com` após passar TODAS as travas; relatório sanitizado; `--execute-demo-order` segue bloqueado | `scripts/run_bybit_demo_diagnostic.py` + testes |
| **Fatia 4A** | `BybitDemoExecutor` dedicado (separado de `BybitTestnetExecutor`); safe-check passa pelo executor; interface de ordem demo registrada com sizing exigido; `execute(dry_run=False)` levanta `NotImplementedError` | `execution/bybit_demo_executor.py` + script refatorado + testes |
| **Fatia 4B** | `execute(dry_run=False)` IMPLEMENTADO via `place_market_order` + reconciliação (`get_order_status` + `get_positions`) + `record_trade_opened` apenas em `FILLED`. Script habilita `--execute-demo-order` com triple-flag-lock + sizing > 0 + ModeGuard + provider gate (`confirm_provider=True`) + `RiskEngine.validate_signal`. Registry: `bybit_demo_linear` migra `CANDIDATE_REVALIDATION` → `OPT_IN`. `cancel_pending(dry_run=False)` segue bloqueado (fechamento via UI). | `bybit_demo_executor.py` + `provider_registry.py` + script + testes |
| **Fatia 4B-Preflight** | Preflight automático **100% read-only**: `BybitDemoPreflight` coleta `instruments-info` + `orderbook` + `ticker` + `balance` + `positions` + `open_orders` via novos métodos `BybitClient.get_instruments_info` e `BybitClient.get_open_orders`. Calcula `qty mínima válida`, `position_size_usd`, `stop_loss` alinhado a tick, `risk_usd`, `capital` derivado do wallet. Novo modo `--prepare-demo-order` no script imprime relatório sanitizado + comando final pronto para copy-paste. **NUNCA envia ordem.** | `bybit_client.py` + `bybit_demo_preflight.py` + script + testes |
| **Fatia 4B-Hardening** | Hardening pós-primeira-ordem-real: `BybitDemoExecutor` ganha retry de `get_order_status` (default 3×, 0.2s) + fallback `get_order_history` (novo método em `BybitClient`). Distingue 5 estados: `SUBMITTED`/`FILLED`/`CANCELED`/`FAILED`/`RECONCILIATION_FAILED` (novo). `record_trade_opened` SOMENTE em FILLED confirmado. Reason cita o método de reconciliação usado. | `bybit_demo_executor.py` + `bybit_client.py` + testes |
| **FASE 14 Demo v2** | Ordem demo real com SL+TP server-side enviados via payload V5 (`stopLoss` + `takeProfit`). Hardenings durante a fase: surfacing de `BybitAPIError.ret_code/ret_msg` no `DemoExecutionResult`; `Decimal` qty normalization (corrige `0.0009999999999999998` → `0.001`). Validado manualmente na UI Bybit Demo. Fechamento manual via Close Position. **Nenhum SELL via script.** **Nenhum `close_position` via script.** | `bybit_demo_executor.py` + `bybit_client.py` (sem alterações) + script + testes |
| **FASE 15** | Reconciliation hardening pós Demo v2: novo `BybitClient.get_executions` (`/v5/execution/list`, read-only); triangulação por executions + positions com defesas estritas (symbol+side+qty match, rejeita múltiplas posições); novo status `FILLED_BY_TRIANGULATION` conservador (NÃO chama `record_trade_opened`, marca `manual_review_required`+`safety_halt_recommended`); `ReconciliationAttempt` estruturado com retCode/retMsg sanitizados; sub-modo `--post-session-check` read-only no diagnostic. | `bybit_demo_executor.py` + `bybit_client.py` (apenas + `get_executions`) + script + testes |

## Demo v2 — sucesso operacional (registrado FASE 14)

| Campo | Valor |
|---|---|
| Ordem | `BTCUSDT Market Buy 0.001 BTC` |
| Leverage | `1.0x` |
| Stop Loss server-side | `70 483.70` |
| Take Profit server-side | `73 704.10` |
| Entry executado | `71 583.60` |
| Endpoint | `https://api-demo.bybit.com` |
| `order_id` | `22817097-79cb-40c5-b1d4-ae0acdfeb552` |
| Fechamento | Manual via UI → Close Position |
| Provider status | `bybit_demo_linear` continua `OPT_IN` |

Reconciliação automática falhou (`/v5/order/realtime` + `/v5/order/history`
ambos `BybitAPIError` na conta Demo). Validação visual da UI cobriu a
lacuna. FASE 15 endureceu o caminho com triangulação read-only para
mitigar o cenário em futuras sessões.

---

## O que é Bybit Demo Trading

Ambiente próprio da Bybit acessado via UI principal (não a UI testnet) sob a seção **"Demo Trading"** / **"Trading Teste"**. Características:

- **Endpoint REST**: `https://api-demo.bybit.com` (separado de mainnet e testnet).
- **WebSocket privado**: `wss://stream-demo.bybit.com/v5/private`.
- **WebSocket público**: usa o stream da **mainnet** (`wss://stream.bybit.com/v5/public`) — dados de mercado são reais.
- **Key/secret**: geradas na seção Demo Trading, **não funcionam em testnet nem em mainnet** e vice-versa.
- **Ledger**: separado; não há custódia de fundos reais, mas as regras de produto (mínimos, ticks, símbolos) seguem a **mainnet**.
- **Caso de uso comum**: validação operacional para integração com prop firms (ex.: HyroTrader Demo Challenge) que aceitam contas Demo Trading como ambiente.

---

## Por que Fatia 1 entrega só config + cliente

Análise prévia mostrou que o código pré-FASE 9 modelava o mundo como **binário**: testnet ou mainnet. Tentar autenticar com **key demo** no endpoint testnet falha; trocar `BYBIT_USE_TESTNET=false` por engano cairia em mainnet. Fatia 1 fecha essa ambiguidade.

### O que MUDOU nesta fatia

| Arquivo | Mudança |
|---|---|
| `config/exchange_config.py` | Novos campos `environment` e `use_demo` + `resolved_environment` + URLs por ambiente |
| `exchange/bybit_client.py` | Novo `BASE_URL_DEMO` + parâmetro `environment` + propriedade `environment`/`is_demo`/`is_mainnet`; `_require_private_access` aceita demo **e** testnet (rejeita mainnet) |
| `.env.example` | Documenta `BYBIT_ENVIRONMENT` e `BYBIT_USE_DEMO` (comentados como opt-in) |
| `tests/` | Cobertura nova de precedência + URLs + private gate por ambiente |

### O que NÃO mudou

- `BybitTestnetExecutor` (continua testnet-only por design — rejeita client `use_testnet=False`, o que inclui demo).
- `ModeGuard` (nenhum método novo nesta fatia).
- `ProviderRegistry` (nenhum provider novo).
- `Settings` (nenhum campo novo).
- `RiskEngine`, `assert_live_allowed`, `PaperTrader`: intocados.

---

## Precedência de resolução de ambiente

Implementada em `ExchangeConfig.resolved_environment`:

```
1. BYBIT_USE_DEMO=true              → "demo"   (precedência máxima)
2. BYBIT_ENVIRONMENT = testnet|demo → o valor informado
3. BYBIT_USE_TESTNET=true (legado)  → "testnet"
4. caso contrário                   → "mainnet" (read-only público; private bloqueado)
```

Valores **proibidos** em `BYBIT_ENVIRONMENT`: `mainnet`, `main`, `live`, `production`, `prod`, `real`. Rejeitados no validator com `ValidationError`.

### URLs resolvidas

| Ambiente | REST | WS público | WS privado |
|---|---|---|---|
| `testnet` | `api-testnet.bybit.com` | `stream-testnet.bybit.com` | `stream-testnet.bybit.com/private` |
| `demo` | `api-demo.bybit.com` | `stream.bybit.com` (mainnet) | `stream-demo.bybit.com/private` |
| `mainnet` | `api.bybit.com` | `stream.bybit.com` | `stream.bybit.com/private` |

---

## Trava de `_require_private_access` (cliente)

Resumo da regra atualizada:

```
ambiente == mainnet   → bloqueia (BybitExecutionBlockedError)
ambiente in {testnet, demo} + credentials presentes → passa
ambiente in {testnet, demo} sem credentials → bloqueia
```

Isso é **defesa em profundidade** no nível do client. **Não substitui** o ModeGuard externo. Como ainda **não existe** executor demo nesta fatia, demo só pode ser exercitado por código novo (próxima fatia) que terá seu próprio gate.

---

## Como usar (após Fatia 1, antes de Fatia 2)

### Leitura local da config (sem rede, sem secrets)

```python
from crypto_trading_bot.config.exchange_config import ExchangeConfig

cfg = ExchangeConfig()           # carrega .env via prefixo BYBIT_
print(cfg.resolved_environment)  # "demo" | "testnet" | "mainnet"
print(cfg.rest_url)              # URL correspondente
# cfg.has_credentials é booleano; valores nunca aparecem em repr()
```

### Cliente construído com ambiente explícito

```python
from crypto_trading_bot.exchange.bybit_client import BybitClient

client = BybitClient(environment="demo", api_key=..., api_secret=...)
# client.environment == "demo"
# client.is_demo == True
# client._base_url == "https://api-demo.bybit.com"
```

### O que NÃO fazer ainda

- ❌ Não rodar `safe-check`/`get_balance()` contra Demo: precisa de script novo + gate (Fatia 2).
- ❌ Não tentar passar um client `environment="demo"` para `BybitTestnetExecutor`: ele recusa por design (`use_testnet=False`). Será criado executor demo na Fatia 2.
- ❌ Não promover nenhum provider do registry para `OPT_IN`/`ACTIVE`.

---

## FASE 9 — Fatia 2 entregue

### O que foi implementado nesta fatia

| Componente | Mudança |
|---|---|
| `TradingMode` | Novo valor `DEMO = "demo"` |
| `Settings.enable_demo_execution` | Bool, default `False` |
| `Settings.is_demo_mode` / `is_demo_execution_enabled` | Properties novas |
| `Settings.provider_id` Literal | Aceita `bybit_demo_linear` |
| `ModeGuard.is_demo` / `is_demo_execution_allowed` | Properties novas |
| `ModeGuard.assert_demo_execution_allowed` | Triple-lock próprio (demo paralela ao testnet) |
| `ProviderStatus.CANDIDATE_REVALIDATION` | Novo valor aditivo |
| `ProviderRegistry` | Provider `bybit_demo_linear` com status `CANDIDATE_REVALIDATION` |
| `scripts/run_bybit_demo_diagnostic.py` | Esqueleto seguro: dry-run + safe-check estrutural (sem rede) |

### O que NÃO foi implementado nesta fatia (continua pendente)

- ❌ **Executor demo dedicado** (`BybitDemoExecutor`). `BybitTestnetExecutor` continua testnet-only.
- ❌ **Chamada real** de `get_balance()` contra `api-demo.bybit.com`.
- ❌ **Envio de ordem demo**. A flag `--execute-demo-order` está registrada no script mas levanta `NotImplementedError`.
- ❌ **Promoção** de `bybit_demo_linear` para `OPT_IN`/`ACTIVE`.

### Triple-lock para execução demo (preparado, ainda sem executor)

```
1. TRADING_MODE=demo              (.env)
2. ENABLE_DEMO_EXECUTION=true     (.env)
3. confirm_demo_execution=True    (argumento explícito da chamada)
```

`ModeGuard.assert_demo_execution_allowed` aplica esse triple-lock e é **independente** de `assert_testnet_execution_allowed` e de `assert_live_allowed` (intocados).

### `ProviderStatus.CANDIDATE_REVALIDATION` — semântica

Estado novo no registry, entre `UNCONFIRMED` (nada provado) e `OPT_IN` (pronto para uso com confirmação). Significa: **evidência operacional preliminar coletada** (UI validada, key existe), **mas requer adaptação técnica + executor dedicado** antes de virar `OPT_IN`. `assert_usable` bloqueia (mesmo padrão que UNCONFIRMED/DRY_RUN_ONLY).

### Script `run_bybit_demo_diagnostic.py`

```powershell
# 1) Default (dry-run): valida config local SEM rede
python scripts/run_bybit_demo_diagnostic.py

# 2) Safe-check estrutural: valida triple-lock + monta client demo (SEM rede)
python scripts/run_bybit_demo_diagnostic.py --safe-check --confirm-demo-execution

# 3) Execução REAL: levanta NotImplementedError seguro (sem rede, sem secrets)
python scripts/run_bybit_demo_diagnostic.py \
    --execute-demo-order --confirm-demo-execution --i-understand-this-is-demo
```

O modo `--safe-check` desta fatia NÃO chama `get_balance()` — apenas:
1. Aplica `ModeGuard.assert_demo_execution_allowed`.
2. Confirma que `ProviderRegistry.assert_usable("bybit_demo_linear")` bloqueia.
3. Monta `BybitClient(environment="demo", ...)` (validando URLs/precedência).
4. Reporta que safe-check real depende de executor demo futuro.

---

## FASE 9 — Fatia 3 entregue

### O que esta fatia libera

`scripts/run_bybit_demo_diagnostic.py --safe-check --confirm-demo-execution` agora chama `get_balance()` **real** contra `https://api-demo.bybit.com` — porém **apenas** depois que TODAS as 4 travas independentes passarem (defesa em camadas):

| # | Trava | O que valida |
|---|---|---|
| 1 | `ModeGuard.assert_demo_execution_allowed` | `TRADING_MODE=demo` + `ENABLE_DEMO_EXECUTION=true` + `confirm_demo_execution=True` |
| 2 | Endpoint `==` `https://api-demo.bybit.com` | `BYBIT_USE_DEMO=true` ou `BYBIT_ENVIRONMENT=demo` resolveu corretamente; nunca cair em testnet/mainnet com key demo |
| 3 | `ExchangeConfig.has_credentials` | api_key + api_secret presentes (não placeholders) |
| 4 | `ProviderRegistry.assert_usable("bybit_demo_linear")` **bloqueia** | Confirma que provider segue `CANDIDATE_REVALIDATION` — defesa para evitar promoção acidental |

Qualquer trava falhando aborta **antes** de qualquer chamada de rede.

### Escopo da chamada

- **Único endpoint chamado**: `GET /v5/account/wallet-balance` (read-only) via `BybitClient.get_balance()`.
- **Não tocados nesta fatia**: `place_market_order`, `cancel_order`, `get_order_status`, `get_positions`, qualquer endpoint de escrita.
- `--execute-demo-order` permanece levantando `NotImplementedError` (verificado por teste).

### Relatório sanitizado

A saída de `--safe-check` é estruturada e **NUNCA** contém valores sensíveis:

```
SAFE-CHECK RESULT — autenticação Bybit Demo validada.
    success                   = True
    endpoint_type             = demo
    endpoint                  = https://api-demo.bybit.com
    credentials_present       = True
    wallet_check              = ok
```

Não inclui: saldos, números de conta, API key, API secret, assinatura, headers `X-BAPI-*`. Erros são passados por `redact_sensitive` antes de imprimir — qualquer string contendo `api_key=...`, `X-BAPI-SIGN: ...`, `Authorization: ...`, etc. vira `***REDACTED***`.

### Comando manual sugerido (aguarda seu OK)

```powershell
# Pré-requisitos no .env (uma vez):
#   TRADING_MODE=demo
#   ENABLE_DEMO_EXECUTION=true
#   BYBIT_USE_DEMO=true       (ou BYBIT_ENVIRONMENT=demo)
#   BYBIT_API_KEY=<demo_key>
#   BYBIT_API_SECRET=<demo_secret>

python scripts/run_bybit_demo_diagnostic.py --safe-check --confirm-demo-execution
```

Resultado esperado: exit 0 com `success=True / wallet_check=ok`. Em caso de falha, exit 1 com `failure_reason` sanitizado.

### O que ainda NÃO foi implementado

- ❌ Executor demo dedicado (`BybitDemoExecutor`). `BybitTestnetExecutor` continua testnet-only por design.
- ❌ Envio de ordem demo (`--execute-demo-order` sempre levanta `NotImplementedError`).
- ❌ Promoção de `bybit_demo_linear` para `OPT_IN`/`ACTIVE` — exige executor + safe-check verde + revisão completa.

---

## FASE 9 — Fatia 4A entregue

### O que esta fatia entrega

| Componente | Mudança |
|---|---|
| `BybitDemoExecutor` (NOVO) | Executor dedicado, paralelo a `BybitTestnetExecutor`. **NUNCA** substitui nem reusa. |
| `DemoTrade` / `DemoTradeStatus` / `DemoExecutionResult` / `DemoExecutionError` (NOVO) | Tipos auxiliares frozen, sanitizados, sem credenciais. |
| Constructor do executor | Rejeita client com `environment != "demo"` (testnet/mainnet bloqueados na origem). |
| `safe_check_only(dry_run=False)` | Chama `client.get_balance()` após `ModeGuard.assert_demo_execution_allowed`. Read-only. |
| `execute(risk_result, dry_run=True)` | Simula sem chamar `place_market_order`. Retorna `DemoExecutionResult` sanitizado. |
| `execute(risk_result, dry_run=False)` | **Levanta `NotImplementedError` na Fatia 4A.** |
| `cancel_pending(dry_run=False)` | Idem — `NotImplementedError`. |
| `execution/__init__.py` | Re-exporta os 5 símbolos demo. |
| `scripts/run_bybit_demo_diagnostic.py` | Refatorado: safe-check passa por `BybitDemoExecutor.safe_check_only`; flags de sizing (`--symbol/--side/--capital/--position-size/--entry-price/--stop-loss/--take-profit/--leverage`) registradas para ordem futura. |
| `BybitTestnetExecutor` | **NÃO alterado.** Continua testnet-only por design. |

### Invariantes do executor

1. Constructor rejeita client não-demo (`BybitExecutionBlockedError`).
2. `execute(risk_result)` rejeita `risk_result.approved=False` (`ValueError`) — **antes** de qualquer outro gate.
3. ModeGuard verificado antes de qualquer I/O privado em `safe_check_only(dry_run=False)`.
4. `dry_run=True` nunca chama `BybitClient` privado de escrita.
5. `dry_run=False` em `execute()` / `cancel_pending()` levanta `NotImplementedError`.
6. Reason em `DemoExecutionResult` em caso de falha de API contém apenas `type(e).__name__` — `str(e)` (que poderia incluir `X-BAPI-SIGN`, `Authorization`, etc.) **nunca** vai para o resultado.
7. `repr` / `to_dict` / `get_summary` não vazam credenciais (verificado por marker em testes).
8. Módulo não importa `subprocess`/`selenium`/`playwright`/`pyautogui` (verificado por teste).
9. Sem hardcode operacional — capital, sizing, leverage vêm do `TradingSignal`.

### Interface de ordem demo futura (registrada, BLOQUEADA)

`scripts/run_bybit_demo_diagnostic.py` agora aceita os parâmetros que serão exigidos quando a ordem real for desbloqueada em fatia futura:

```powershell
python scripts/run_bybit_demo_diagnostic.py `
    --execute-demo-order --confirm-demo-execution --i-understand-this-is-demo `
    --symbol BTCUSDT --side buy `
    --capital 1000 --position-size 5 --entry-price 65000 `
    --stop-loss 64000 --leverage 1.0
```

Nesta Fatia 4A, o comando acima:
- Imprime os parâmetros recebidos (auditoria).
- Levanta `NotImplementedError` antes de qualquer chamada de rede.
- Nenhum default operacional perigoso (todos os campos de sizing são `None` por default e exigidos na fatia futura).

### Provider `bybit_demo_linear` — status NÃO alterado

Continua **`CANDIDATE_REVALIDATION`**. Esta fatia adiciona o executor, mas a promoção do provider para `OPT_IN`/`ACTIVE` exige:

1. Plano explícito de desbloqueio de `execute(dry_run=False)`.
2. Auditoria de redaction com captura de stream durante ordem real.
3. Aprovação humana explícita (fora de banda).
4. Confirmação operacional via UI demo (BTCUSDT linear, Close Position, etc.).
5. Plano de fechamento da posição via UI demo (não há cancel real liberado aqui).

---

## FASE 9 — Fatia 4B entregue

### Sete travas independentes no caminho `--execute-demo-order`

| # | Trava | Onde |
|---|---|---|
| 1 | Triple-flag-lock CLI completo (`--execute-demo-order` + `--confirm-demo-execution` + `--i-understand-this-is-demo`) | script |
| 2 | Sizing > 0 em TODOS os 5 campos (`--capital`, `--position-size`, `--entry-price`, `--stop-loss`, `--leverage`) | script |
| 3 | `ModeGuard.assert_demo_execution_allowed` (`TRADING_MODE=demo` + `ENABLE_DEMO_EXECUTION=true` + `confirm_demo_execution=True`) | script + executor |
| 4 | Endpoint resolvido == `https://api-demo.bybit.com` (não testnet, não mainnet) | script |
| 5 | `ExchangeConfig.has_credentials` (api_key + api_secret presentes) | script |
| 6 | `ModeGuard.assert_provider_allowed("bybit_demo_linear", confirm_provider=True)` (registry exige confirm) | script |
| 7 | `RiskEngine.validate_signal(signal)` aprova | script |

Falha em qualquer trava aborta **antes** de qualquer chamada de rede. Cada trava tem teste dedicado offline.

### Comportamento de `execute(dry_run=False)`

```text
1. INVARIANTE: rejeita risk_result.approved=False (ValueError).
2. ModeGuard.assert_demo_execution_allowed (early abort).
3. Valida signal.entry_price > 0.
4. qty = signal.position_size_usd / signal.entry_price.
5. client.place_market_order(symbol, side, qty, stop_loss, take_profit).
   ⚠️  reduceOnly NÃO é passado.
   ⚠️  leverage NÃO é passado (configurada na UI da conta demo).
6. client.get_order_status (best-effort, falha não quebra resultado).
7. client.get_positions (best-effort).
8. Cria DemoTrade frozen. trade_id = "BT_DEMO_<symbol>_<order_id>".
9. Se status == FILLED → RiskEngine.record_trade_opened.
10. Retorna DemoExecutionResult(success=True, trade=trade).
```

Em qualquer falha (exceção HTTP, BybitClient bloqueia, etc.), retorna `DemoExecutionResult(success=False)` com `reason = f"... {type(e).__name__}"`. **`str(e)` nunca aparece** em `reason`/`to_dict`/log — defesa contra leak de headers/assinatura.

### `cancel_pending` continua bloqueado

`BybitDemoExecutor.cancel_pending(dry_run=False)` segue levantando `NotImplementedError`. Motivo: `BybitClient.place_market_order` não aceita `reduceOnly`, então um cancel via API pode flipar a posição. **Fechamento = UI Bybit Demo → "Close Position"** (UI usa reduceOnly server-side).

### Registry: `bybit_demo_linear` promovido a `OPT_IN`

```python
get_registry().assert_usable("bybit_demo_linear")                       # BLOQUEIA
get_registry().assert_usable("bybit_demo_linear", confirm_provider=True)  # PASSA
```

Script-level: `guard.assert_provider_allowed("bybit_demo_linear", confirm_provider=True)`. `confirm_provider=True` só é passado pelo script quando triple-flag-lock está completo.

### Comando manual sugerido (NÃO executar sem seu OK)

```powershell
# Pré-requisitos no .env (uma vez, depois reverter):
#   TRADING_MODE=demo
#   ENABLE_DEMO_EXECUTION=true
#   BYBIT_USE_DEMO=true       (ou BYBIT_ENVIRONMENT=demo)
#   BYBIT_API_KEY=<demo>      (já presente)
#   BYBIT_API_SECRET=<demo>

# Pré-checks operacionais:
#   1. UI Bybit Demo: leverage de BTCUSDT linear = 1x
#   2. UI Bybit Demo: nenhuma posição aberta em BTCUSDT
#   3. Ler entry_price atual no order book

python scripts/run_bybit_demo_diagnostic.py `
    --execute-demo-order `
    --confirm-demo-execution `
    --i-understand-this-is-demo `
    --symbol BTCUSDT `
    --side buy `
    --capital 1000 `
    --position-size 5 `
    --entry-price <MID_NO_MOMENTO> `
    --stop-loss <ENTRY_MENOS_1.5_PCT> `
    --leverage 1.0
```

**Fechamento da posição**: UI Bybit Demo → "Close Position". **NÃO** rodar o script com `--side sell` para fechar.

**Rollback após execução**:
```bash
# .env:
TRADING_MODE=paper
ENABLE_DEMO_EXECUTION=false
BYBIT_USE_DEMO=false
```

---

---

## FASE 9 — Fatia 4B-Preflight entregue

### Objetivo

Automatizar a coleta de TODOS os dados necessários para montar uma ordem mínima Bybit Demo, eliminando a necessidade do operador informar manualmente valores que a API pode fornecer (preço, minOrderQty, qtyStep, saldo, posições, etc.).

### Componentes novos

| Componente | Responsabilidade |
|---|---|
| `BybitClient.get_instruments_info(symbol, category)` | PÚBLICO. `GET /v5/market/instruments-info`. Retorna lotSizeFilter (minOrderQty, qtyStep, minNotionalValue, maxOrderQty) + priceFilter (tickSize). |
| `BybitClient.get_open_orders(symbol, category)` | SIGNED. `GET /v5/order/realtime?openOnly=1`. Lista ordens ATIVAS para o símbolo (lista vazia se não há). |
| `BybitDemoPreflight` ([bybit_demo_preflight.py](../src/crypto_trading_bot/execution/bybit_demo_preflight.py)) | Orquestrador read-only. `run()` sempre retorna `PreflightReport` (nunca levanta). |
| `MarketInfo`, `AccountState`, `OrderProposal`, `PreflightReport` | Tipos imutáveis sanitizados. `to_dict()` nunca contém credenciais. |
| `PreflightAbortReason` | Enum classificando 14 motivos de abort. |

### Dados coletados automaticamente pela API

| Origem | Campos | Endpoint |
|---|---|---|
| `instruments-info` (público) | `minOrderQty`, `maxOrderQty`, `qtyStep`, `minNotionalValue`, `tickSize` | `/v5/market/instruments-info` |
| `orderbook` (público) | `best_bid`, `best_ask`, `mid_price` (reference_price) | `/v5/market/orderbook` |
| `ticker` (público, opcional) | `last_price` (informativo) | `/v5/market/tickers` |
| `wallet-balance` (privado read-only) | `walletBalance USDT`, `availableToWithdraw USDT` | `/v5/account/wallet-balance` |
| `positions` (privado read-only) | `open_positions_count`, `leverage_value`, `leverage_confirmable` | `/v5/position/list` |
| `open-orders` (privado read-only) | `open_orders_count` | `/v5/order/realtime?openOnly=1` |

### Cálculos determinísticos a partir dos dados

```text
qty_inicial         = minOrderQty
se qty_inicial * reference_price < minNotionalValue:
    qty             = ceil(minNotionalValue / reference_price / qtyStep) * qtyStep
qty                 = qty alinhada a qtyStep
abort se qty > maxOrderQty
position_size_usd   = qty * reference_price
stop_loss (BUY)     = floor(reference_price * 0.985 / tickSize) * tickSize
risk_usd            = qty * (reference_price - stop_loss)
capital             = max(available_balance, wallet_balance, position_size_usd * 15)
```

Depois: `RiskEngine.validate_signal(signal)` com `initial_capital = proposal.capital`. Se rejeitar, preflight aborta com `RISK_ENGINE_REJECTED`.

### Dados que AINDA podem exigir confirmação manual

| Cenário | Por quê | Como o preflight reporta |
|---|---|---|
| Leverage não retornado pela API | Bybit V5 só retorna leverage quando há entry de posição (mesmo size=0); se a lista vier vazia, não há como confirmar | `account_state.leverage_confirmable=False` + entry em `manual_confirmations_needed` orientando UI Bybit Demo |
| Wallet endpoint falha de rede | Network glitch transitório | `manual_confirmations_needed` registra para o operador confirmar saldo na UI |
| Positions endpoint falha | Idem | Entry em `manual_confirmations_needed` |

Nesses casos, preflight ainda pode retornar `ok=True` se a falha não bloquear a proposta, mas o operador deve revisar o campo `manual_confirmations_needed` antes de executar.

### Sete travas de execução real seguem intactas

A microfase do preflight **não altera** o caminho `--execute-demo-order` — as 7 travas continuam ativas. O preflight apenas **prepara** os valores corretos para que essas travas passem na execução real, e mostra o comando completo pronto para copy-paste com seu OK.

### Comando do modo preflight

```powershell
# Pré-requisitos no .env:
#   TRADING_MODE=demo
#   ENABLE_DEMO_EXECUTION=true
#   BYBIT_USE_DEMO=true
#   BYBIT_API_KEY=<demo>
#   BYBIT_API_SECRET=<demo>

python scripts/run_bybit_demo_diagnostic.py --prepare-demo-order
```

Saída esperada quando OK:
```text
🛠️  MODE: PREFLIGHT — read-only; propõe ordem mínima sem enviar.
...
🛠️  Coletando dados read-only da Bybit Demo...
✅ PREFLIGHT OK — proposta de ordem mínima abaixo.

📊 MARKET INFO:
   symbol:             BTCUSDT
   best_bid:           80000.0
   best_ask:           80010.0
   mid_price:          80005.0
   reference_price:    80005.0
   min_order_qty:      0.001
   qty_step:           0.001
   tick_size:          0.10

👤 ACCOUNT STATE (read-only, sem secrets):
   wallet_balance_usdt:    10000.0
   open_positions_count:   0
   open_orders_count:      0
   leverage_confirmable:   True
   leverage_value:         1.0

🎯 ORDER PROPOSAL:
   symbol:           BTCUSDT
   side:             buy
   reference_price:  80005.0
   qty:              0.001
   position_size_usd:80.005000
   stop_loss:        78804.9
   leverage:         1.0
   risk_usd:         1.200100
   capital:          10000.00

📋 COMANDO FINAL SUGERIDO (NÃO EXECUTAR sem OK explícito):
python scripts/run_bybit_demo_diagnostic.py `
    --execute-demo-order `
    --confirm-demo-execution `
    --i-understand-this-is-demo `
    --symbol BTCUSDT `
    --side buy `
    --capital 10000.00 `
    --position-size 80.005000 `
    --entry-price 80005.0 `
    --stop-loss 78804.9 `
    --leverage 1.0
```

---

## Primeira ordem demo real — executada e fechada (registro)

**Data**: 2026-05-29.
**Endpoint**: `https://api-demo.bybit.com` (confirmado; nenhuma mainnet/testnet).
**Comando**: `--execute-demo-order --confirm-demo-execution --i-understand-this-is-demo --symbol BTCUSDT --side buy --capital 5000.00 --position-size 73.671450 --entry-price 73671.45 --stop-loss 72566.3 --leverage 1.0`.
**Resultado do executor**:
- `success=True`
- `order_id=87e6e17e-4ab2-4e51-9271-d5275f965769`
- `trade_id=BT_DEMO_BTCUSDT_87e6e17e-4ab2-4e51-9271-d5275f965769`
- `status=submitted` (reconciliação best-effort falhou — `BybitAPIError` em `get_order_status` na janela imediata pós-ack)
- `qty=0.001 BTC`, `side=buy`

**Confirmação manual na UI Bybit Demo**:
- Open Long BTCUSDT Market Filled 0.001/0.001 BTC.
- Close Long BTCUSDT Market Filled 0.001/0.001 BTC (fechamento manual via UI → "Close Position").

**Limitação observada**: a chamada `get_order_status` em `/v5/order/realtime` retornou `BybitAPIError` poucos ms após o `place_market_order` retornar `orderId`. Causa provável: ordens market preenchidas saem rapidamente de `/v5/order/realtime` e migram para `/v5/order/history`. O executor caía corretamente em `status=submitted`, mas isso **mascarava o `FILLED` real**.

**Mitigação implementada na Fatia 4B-Hardening**:
- Retry configurável (`reconciliation_attempts`, default 3) com pausa pequena (`reconciliation_delay_seconds`, default 0.2s) entre tentativas no endpoint `/v5/order/realtime`.
- Fallback para `BybitClient.get_order_history` (novo método; GET `/v5/order/history`) quando todos os retries em realtime falham/retornam vazio.
- Novo `DemoTradeStatus.RECONCILIATION_FAILED` separa "ordem ativa em pending" de "não conseguimos confirmar nada" — não há mais máscara silenciosa.
- Política conservadora: `record_trade_opened` (RiskEngine) só é chamado em `FILLED` confirmado.

---

## Próximas opções possíveis (a aprovar separadamente)

**Execução manual real**: usar o comando acima com seu OK explícito, depois rodar a auditoria de redaction in-memory (FASE 7 §2). Não é uma fatia nova — é uso do que já está pronto.

**Fatia 4C — Promoção para ACTIVE** (apenas após execução real bem-sucedida):
- Auditoria de redaction durante ordem real comprovada (sem leak).
- Revisão arquitetural separada.
- Plano de fechamento testado.
- Migrar `bybit_demo_linear` de `OPT_IN` → `ACTIVE`.

**Alternativa: FASE 10** (Estratégias Determinísticas + Robustez Offline):
- 100% offline. Não depende de provider externo.
- Trend Pullback + Volatility Breakout + comparação multi-métrica + walk-forward.
- Fortalece a base de estratégias antes de qualquer execução real intensiva.

---

## Garantias arquiteturais desta fatia

- ✅ Sem dependência nova; sem rede; sem secrets no código.
- ✅ Demo Trading separado de Testnet em config + client.
- ✅ Mainnet/live continuam bloqueados (private; validator do `environment`; `assert_live_allowed` intocado).
- ✅ Caminho testnet existente **100% preservado** (retrocompat byte-a-byte).
- ✅ `BybitTestnetExecutor` continua rejeitando clients não-testnet — isso impede demo por aquele caminho sem mudança consciente.
