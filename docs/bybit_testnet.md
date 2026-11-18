# Bybit Testnet — FASE 5

> 🧭 **Nota (FASE 9 — Fatia 1):** este documento cobre **TESTNET** (`api-testnet.bybit.com`). **Bybit Demo Trading** é ambiente **separado** (`api-demo.bybit.com`) com key/secret/ledger próprios. Ver [bybit_demo_trading.md](bybit_demo_trading.md). Não usar key Demo no fluxo testnet — e vice-versa.

> ⚠️ **STATUS NO PROVIDER REGISTRY (FASE 8): `RESTRICTED`** para o operador atual.
> O acesso ao produto **derivativo linear (BTCUSDT perp USDT)** está **bloqueado por restrição regional/regulatória** desde FASE 7 Estágio 3.
> **Código FASE 5/6 preservado e intacto.** `safe-check` read-only (`get_balance`) continua válido se necessário.
> Reclassificar para `OPT_IN` somente após resolução da restrição externa.

> ⚠️ **Testnet usa credentials reais (mesmo que sem dinheiro real).** Trate-as como você trataria credenciais de produção.
> ⚠️ **Mainnet/live permanece BLOQUEADO** por design — independente de ter credentials válidas.
> ⚠️ **Testnet NÃO garante performance futura.** Custos, latência, slippage e liquidez podem variar drasticamente entre testnet e mainnet, e ainda mais entre mainnet e o futuro.

---

## Visão geral

A FASE 5 adiciona uma camada **manual e controlada** para enviar ordens à Bybit testnet. Características chave:

- `httpx + HMAC próprio` (sem `pybit`, sem dependências novas).
- `BybitTestnetExecutor` em `execution/`, **separado** de `PaperTrader`.
- `PaperTrader` continua sendo o **default** do `BotEngine` e do `PaperTradingOrchestrator`.
- Integração `BotEngine` ↔ `BybitTestnetExecutor` **NÃO** foi feita nesta fase — uso é via scripts manuais.
- Mainnet/live continua **BLOQUEADO** com triple-lock existente (`assert_live_allowed`).
- Testnet exige **triple-lock próprio** (`assert_testnet_execution_allowed`): NÃO afrouxa nada de live.

---

## Triple-lock para testnet (assimétrico ao live, sem se misturar)

Para que qualquer ordem testnet seja enviada, **TODAS** as 3 condições devem ser satisfeitas:

| Condição | Onde |
|---|---|
| `TRADING_MODE=testnet` | `.env` |
| `ENABLE_TESTNET_EXECUTION=true` | `.env` |
| `confirm_testnet_execution=True` | Argumento da chamada Python OU `--confirm-testnet-execution` no script CLI |

**Para o script `run_testnet_diagnostic.py`**, há **4 flags CLI necessárias** para o modo "envia ordem":
- `--execute-testnet-order`
- `--confirm-testnet-execution`
- `--i-understand-this-is-testnet`
- Sizing explícito: `--position-size`, `--entry-price`, `--stop-loss`, `--capital` (todos > 0).

---

## Configuração `.env`

```bash
# Trading mode — paper é o padrão seguro
TRADING_MODE=paper                    # paper | testnet | live
ENABLE_LIVE_TRADING=false             # mainnet — false em uso normal
ENABLE_TESTNET_EXECUTION=false        # FASE 5 — segunda trava para testnet

# Bybit testnet credentials (gere em https://testnet.bybit.com/app/user/api-management)
# ⚠️  Nunca commite o .env real. Apenas .env.example com placeholders.
BYBIT_API_KEY=your_testnet_api_key_here
BYBIT_API_SECRET=your_testnet_api_secret_here
BYBIT_USE_TESTNET=true                # default seguro
BYBIT_RECV_WINDOW=5000                # janela Bybit V5 em ms
```

---

## Componentes

### `bybit_auth.py` — HMAC puro

Função `sign_request(api_key, api_secret, timestamp_ms, recv_window_ms, method, query_or_body) → headers`.

- Pure function (sem I/O).
- HMAC-SHA256 conforme spec Bybit V5.
- Helpers `build_query_string(params)` (ordem alfabética) e `build_body_string(payload)` (JSON compacto).
- **api_secret nunca aparece em headers/output** — apenas a assinatura derivada.

### `log_redaction.py` — sanitização de mensagens

`redact_sensitive(text)` e `redact_dict(data)`.

Mascara:
- `api_key`, `api_secret`, `secret` (em qualquer forma: `key=val`, `"key": "val"`, etc.)
- `X-BAPI-API-KEY`, `X-BAPI-SIGN`, `X-BAPI-SIGN-TYPE`
- `Authorization: ...` (Bearer, Basic, etc.) — tudo após o `:` até newline

Substitui valor por `***REDACTED***`.

### `BybitClient` (extensão mínima)

Construtor ganha args **opcionais** retrocompatíveis:
- `api_key: Optional[str] = None`
- `api_secret: Optional[str] = None`
- `recv_window: int = 5000`

Métodos privados (`place_market_order`, `cancel_order`, `get_positions`, `get_balance`, `get_order_status`):
- **SEM credentials** → continuam lançando `BybitExecutionBlockedError`.
- **Mainnet** (`use_testnet=False`) → continuam bloqueados **mesmo com credentials** (defesa em profundidade).
- **Testnet + credentials** → operacionais.

Logs NUNCA contêm `api_key` (apenas `auth=present|none`) nem `api_secret` nem signature.

### `ModeGuard.assert_testnet_execution_allowed`

Método NOVO, separado de `assert_live_allowed`. Verifica:
1. `TRADING_MODE=testnet`
2. `ENABLE_TESTNET_EXECUTION=true`
3. `confirm_testnet_execution=True` (passado explicitamente)

Lança `TradingModeError` se qualquer condição falhar.

**`assert_live_allowed` permanece intocado** — triple-lock de mainnet/live preservado.

### `BybitTestnetExecutor`

Camada análoga ao `PaperTrader`. INVARIANTES:

| Invariante | Como verificada |
|---|---|
| `risk_result.approved=True` obrigatório | `execute()` levanta `ValueError` se False |
| ModeGuard verificado | Chama `assert_testnet_execution_allowed` antes de qualquer privado |
| `use_testnet=True` obrigatório | `__init__` rejeita mainnet client |
| `dry_run=True` não chama API | Testado por mock que falha se chamado |
| `safe_check_only` chama APENAS `get_balance` | Testado |
| `record_trade_opened` apenas após sucesso confirmado | Status == FILLED |
| Logs sem secrets | `redact_sensitive` + `SecretStr` |
| Sem hardcode de capital/sizing/leverage | Tudo vem do signal ou argumento |

---

## Scripts

### `scripts/check_testnet_config.py`

```bash
python scripts/check_testnet_config.py
python scripts/check_testnet_config.py --json
```

**Nunca chama endpoint privado.** Apenas valida `.env`, `Settings`, `ModeGuard`. Diz se a config está pronta para `run_testnet_diagnostic.py`.

### `scripts/run_testnet_diagnostic.py`

Três modos, em ordem progressiva de risco:

```bash
# 1) Dry-run (default): apenas mostra config, ZERO rede
python scripts/run_testnet_diagnostic.py

# 2) Safe-check: chama apenas get_balance() (autenticação check)
python scripts/run_testnet_diagnostic.py --safe-check

# 3) Envio real de ordem testnet (todas as 4 flags + sizing obrigatórios)
python scripts/run_testnet_diagnostic.py \
    --execute-testnet-order \
    --confirm-testnet-execution \
    --i-understand-this-is-testnet \
    --symbol BTCUSDT --side buy \
    --position-size 5 --entry-price 65000 \
    --stop-loss 64000 --take-profit 67000 \
    --capital 1000
```

**Default é dry-run.** Para enviar ordem real, as 4 flags + sizing são exigidos.

---

## Garantias arquiteturais

| Garantia | Como |
|---|---|
| Mainnet/live continua bloqueado | `assert_live_allowed` intocado; `BybitClient` rejeita mainnet em métodos privados (defesa em profundidade) |
| Testnet exige confirmação explícita | Triple-lock no ModeGuard + 3 flags CLI |
| PaperTrader continua default | `BotEngine` e `PaperTradingOrchestrator` NÃO foram alterados |
| RiskEngine soberano | INVARIANTE: `execute()` rejeita `risk_result.approved=False` |
| Sem dependência nova | Apenas stdlib + `httpx` já existente |
| Sem hardcode operacional | capital/sizing/leverage sempre vêm de `.env`, signal ou CLI |
| Testes 100% offline | BybitClient sempre mockado; nenhum teste usa API key real |
| Secrets nunca em logs | `SecretStr` + `log_redaction` |

---

## Limitações reconhecidas

1. **Sem WebSocket nesta fase.** Apenas REST com HMAC.
2. **Integração com BotEngine NÃO foi feita.** `BybitTestnetExecutor` é usado manualmente via script. A integração `BotEngine ↔ TestnetExecutor` é uma fase futura.
3. **Reconciliação best-effort:** `get_order_status` e `get_positions` são chamados APÓS `place_market_order`, mas timing real pode variar (testnet pode ter delays).
4. **Sem retry exponencial.** Falha de rede → erro propagado.
5. **`log_redaction` aplicado manualmente.** Filtro global no logger (loguru) foi deliberadamente NÃO implementado nesta fase ("parar e reportar" se exigir mudança grande). Caller deve usar `redact_sensitive()` antes de logar strings sensíveis.

---

## FASE 6 — Integração BotEngine ↔ BybitTestnetExecutor

A FASE 6 conecta o `BotEngine` ao `BybitTestnetExecutor` **sem** alterar o
caminho default (PaperTrader continua o default absoluto). A integração é
**100% offline-testável** (mocks) e a execução real em testnet permanece atrás
do triple-lock da FASE 5.

### Componentes novos

| Componente | Papel |
|---|---|
| `execution/executor_protocol.py::ExecutorProtocol` | Contrato estrutural (`typing.Protocol`, `runtime_checkable`): qualquer objeto com `execute(risk_result) -> Any`. `PaperTrader` e o adapter satisfazem SEM herança. |
| `execution/testnet_executor_adapter.py::TestnetExecutorBotAdapter` | Adapta `BybitTestnetExecutor.execute(risk_result, dry_run=...)` ao contrato `execute(risk_result)`. **`dry_run` é OBRIGATÓRIO no construtor (sem default).** |

### Mudanças retrocompatíveis em `src/`

| Arquivo | Mudança |
|---|---|
| `core/bot_engine.py` | Novo parâmetro opcional `executor`; `paper_trader` agora opcional. Exige EXATAMENTE UM (ambos OU nenhum → `ValueError`). `self._active_executor` = executor ou paper_trader. |
| `core/cycle_result.py` | Novo campo paralelo `executor_result` (não substitui `trade`, que continua legado). |
| `config/settings.py` | Novo `executor_type: Literal["paper","testnet"]` (default `paper`). **`live` é REJEITADO** por validador. |

### Triple-lock continua soberano

`executor_type=testnet` **não** afrouxa nada. Para enviar ordem real testnet via
BotEngine, ainda valem TODAS as condições da FASE 5 (`TRADING_MODE=testnet` +
`ENABLE_TESTNET_EXECUTION=true` + `confirm_testnet_execution=True`), aplicadas
dentro do `BybitTestnetExecutor`. Além disso, o `TestnetExecutorBotAdapter` força
a decisão explícita de `dry_run` na construção.

### 🚦 GATE MANUAL OBRIGATÓRIO antes de `dry_run=False`

> **A implementação offline da FASE 6 (mocks, sem API key, sem internet) NÃO
> substitui a validação manual da FASE 5.** Antes de QUALQUER execução testnet
> externa com `dry_run=False`, é OBRIGATÓRIO validar a autenticação manualmente:
>
> ```bash
> python scripts/run_testnet_diagnostic.py --safe-check
> ```
>
> Esse safe-check (apenas `get_balance()`, sem ordem) é o gate que comprova que
> as credentials testnet reais funcionam. Só então use o BotEngine com o adapter
> em `dry_run=False`.

### Script `scripts/run_bot_testnet.py`

```bash
# Dry-run (default): prova a fiação BotEngine ↔ testnet executor (zero ordens)
python scripts/run_bot_testnet.py --capital 1000 --cycles 3

# Envio real em testnet (exige 3 flags + .env testnet + gate manual acima)
python scripts/run_bot_testnet.py \
    --execute-testnet-order \
    --confirm-testnet-execution \
    --i-understand-this-is-testnet \
    --capital 1000 --cycles 1 \
    --symbol BTCUSDT --position-size 5 --entry-price 65000
```

**Default é dry-run.** As 3 flags juntas são exigidas para `dry_run=False`.

> ⚠️ **Mainnet/live continua fora do escopo.** Nenhuma fase afrouxou
> `assert_live_allowed`, e `executor_type=live` é rejeitado por design.

---

## Reforço final

> ⚠️ **Bybit testnet é um ambiente de simulação operado pela Bybit.** Suas regras (slippage, fills, latência) podem diferir da mainnet. Sucessos em testnet **NÃO garantem** performance em conta real. Trate todo resultado de testnet como um sinal qualitativo de que a integração funciona — nunca como prova de lucratividade.
