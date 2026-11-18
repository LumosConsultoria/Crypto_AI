# API-Driven Demo Blueprint — FASE 22

> Ponte entre `BybitDemoPreflight` (FASE 9 Fatia 4B+) e o gate
> `execute_demo_session_gated` (FASE 20). Substitui valores manuais por
> blueprint dinâmico, fresco e auditável gerado pela API. **Não envia
> ordem.** Caminho real do `run_bybit_demo_session_gated.py` agora
> exige um `DemoApiBlueprint` JSON gerado por preflight imediatamente
> anterior.

## FASE 22 close-out — Stage-aware post_session_check

A versão inicial do `post_session_check` (FASE 22 Final) marcava
qualquer posição com `size != 0` como `residual_position_detected=True`,
o que conflitava com o uso imediato pós-Comando B: a posição
recém-aberta e protegida com SL/TP server-side é **esperada**, não
residual.

A correção introduz **stage** explícito:

- **`stage="after_entry"`** (default usado pelo script após Comando B):
  - Espera **uma** posição aberta no `symbol` com `size > 0`.
  - Exige SL e TP server-side quando `require_sl=True`/`require_tp=True`
    (defaults).
  - Aceita `expected_qty` opcional (do `blueprint.proposal.qty`); qty
    divergente → `manual_review`.
  - Múltiplas posições ou ausência de posição → `manual_review`.
  - Open orders pendentes inesperados → `manual_review` (com
    `tpslMode="Full"`, SL/TP server-side **não** aparecem em
    `open_orders` separados).
  - API error → `safety_halt`.
- **`stage="flat_check"`** (usado pelo operador **depois** de
  fechar/gerenciar manualmente pela UI):
  - Espera **zero posições** e **zero ordens**.
  - Qualquer residual → `manual_review`/`safety_halt`.

O script `run_bybit_demo_session_gated.py` wira `stage="after_entry"`
+ `expected_qty=blueprint.proposal.qty` automaticamente no caminho
real do Comando B. O `flat_check` é chamado manualmente pelo operador
depois de fechar a posição pela UI (validação final fora do escopo
single-shot).

## FASE 22 Final — Signed Read-only Reconciliation + Redaction + Clean Session

A primeira tentativa demo real (Comando B) revelou três problemas operacionais
que precisaram ser endurecidos antes de fechar a FASE 22:

1. **`retCode=10004` ("error sign")** persistente em endpoints signed
   read-only de reconciliação (`/v5/order/realtime`, `/v5/order/history`,
   `/v5/execution/list`). Causa raiz: `BybitClient._signed_request`
   construía a string HMAC com `build_query_string` (params ordenados
   alfabeticamente) mas chamava `httpx.get(params=query_params)` na
   **ordem de inserção** do dict Python. Quando essas ordens divergiam,
   a Bybit V5 recalculava HMAC e falhava. **Fix:** ordenar `params`
   alfabeticamente **antes** de passar para `httpx.get`, garantindo
   que payload assinado == payload enviado.
2. **`origin_string[...]` leakado em logs.** Bybit V5 retorna o payload
   exato usado para assinar (incluindo `ts+api_key+window+query`) dentro
   de `retMsg`. **Fix:** novo `redact_ret_msg()` em `bybit_client.py`,
   aplicado **automaticamente** em `BybitAPIError.__init__`. Patterns
   redactados: `origin_string[...]`, `X-BAPI-SIGN=...`, `Bearer ...`,
   `Authorization=...`, `sign=<hex>`, `signature=<hex>`, `api_key=...`,
   `api_secret=...`. `retCode` é preservado para diagnóstico.
3. **Post-session check fraco.** `safe_check_only` validava apenas
   `get_balance`, não detectava posições/ordens residuais. **Fix:** novo
   `BybitDemoExecutor.post_session_check(symbol, dry_run)`: leitura
   `get_balance` + `get_positions` + `get_open_orders`, retorna
   `DemoExecutionResult` com `manual_review_required=True` /
   `safety_halt_recommended=True` se qualquer residual for detectado OU
   qualquer endpoint privado falhar. 100% read-only. Não fecha, não
   cancela, não envia ordem.

### Criterio explicito de CANONICAL CLEAN SESSION (READY_FOR_NEXT_DEMO_SESSION)

Documentado em `RecommendedNextAction.READY_FOR_NEXT_DEMO_SESSION`. Os
7 requisitos:

1. `executor_result.success == True`
2. `dry_run == False`
3. `reconciliation_confidence == "canonical"`
4. `requires_manual_review == False`
5. `safety_halt_recommended == False`
6. SL/TP server-side anexados quando signal exigiu (defesa em
   profundidade da FASE 22.4)
7. `post_session_check` (quando fornecido) retornou `success=True` sem
   positions/orders residuais nem api_errors

Qualquer falha em (1)-(7) → `MANUAL_REVIEW_REQUIRED` ou
`SAFETY_HALT_ACK_NEEDED`.

### Sessão demo real anterior (registro histórico)

A tentativa anterior:
- ordem market BUY BTCUSDT qty 0.001 foi enviada;
- posição abriu **sem SL/TP server-side**;
- reconciliação canônica falhou com `retCode=10004`;
- safety halt foi corretamente ativado;
- posição foi **fechada manualmente** pela UI;
- estado final: Positions=0, Open Orders=0, Conditional Orders=0;
- Realized P&L=-0.0619 USDT;
- nenhum secret vazou para os logs.

Esta sessão NÃO foi canonical clean e nunca deveria ter sido
considerada como tal. Os 3 endurecimentos acima previnem repetição.

## Hotfix FASE 22.4 — SL/TP server-side payload + post-fill check

Observado operacionalmente: Comando B em Bybit Demo enviou ordem
market BUY BTCUSDT com sucesso (qty 0.001 BTC, leverage 1x, fill OK na
UI), porém **SL/TP não foram anexados server-side** à posição. O
blueprint tinha SL=65843.4 e TP=68851.6, o `BybitClient` enviou no
payload, mas a Bybit V5 (UTA Demo) **descartou silenciosamente**.

Causa raiz: payload `/v5/order/create` omitia `tpslMode`, triggers e
order types. Bybit V5 docs exigem para SL/TP server-side em market
order linear/UTA:
- `tpslMode`: `"Full"` (aplica a posição inteira) ou `"Partial"`.
- `slTriggerBy` / `tpTriggerBy`: `"LastPrice"` / `"MarkPrice"` / `"IndexPrice"`.
- `slOrderType` / `tpOrderType`: `"Market"` ou `"Limit"`.

Sem esses parâmetros, o endpoint aceita a ordem mas descarta SL/TP.

A FASE 22.4 entrega:

1. **`BybitClient.place_market_order` — payload completo** (alteração
   mínima, aditiva, dentro do `if stop_loss/take_profit is not None`):
   - `tpslMode="Full"` quando SL ou TP presente.
   - `slTriggerBy="LastPrice"` + `slOrderType="Market"` quando SL presente.
   - `tpTriggerBy="LastPrice"` + `tpOrderType="Market"` quando TP presente.
   - **Comportamento legacy preservado**: chamadas sem SL/TP não recebem
     parâmetros tpsl.
   - Log estruturado adicional: `sl_present`, `tp_present`,
     `tpsl_payload_present` para diagnóstico.
2. **`BybitDemoExecutor.execute` — defesa em profundidade**:
   - Helper `_sl_or_tp_missing_in_position(snapshot, field, expected)`.
   - Após fill canônico, se `position_snapshot` retornado por
     `get_positions` mostrar `stopLoss=""` ou `"0"` quando o signal
     pedia SL > 0 (idem TP), **marca `manual_review_required=True`**
     mesmo com fill canônico.
   - Garante que a invariante "sessão clean ⇒ posição com SL+TP
     server-side anexados" não falha silenciosamente.

## Hotfix FASE 22.2 — get_open_orders param fix + diagnostic capture

Após o hotfix FASE 22.1, a re-execução do Step 1 operacional contra
Bybit Demo retornou `BybitAPIError` em `get_open_orders` de forma
persistente, bloqueando o blueprint corretamente mas sem expor a causa
real (apenas o tipo da exceção).

A FASE 22.2 entrega:

1. **`BybitClient.get_open_orders` — fix de parâmetro**:
   - **Antes:** enviava `openOnly=1` (que, na docs Bybit V5, significa
     "ordens **concluídas** recentes", não ordens abertas).
   - **Depois:** omite `openOnly` → default `0` (ordens abertas
     active/untriggered). Comportamento agora correto para o uso de
     preflight. Documentado no docstring.
   - Em Demo Trading, `openOnly=1` retornava `BybitAPIError` dependendo
     de `account_type`/permissões — comportamento agora removido na
     raiz.
2. **`BybitDemoPreflight._collect_account_state` — diagnostic capture**:
   - Captura `BybitAPIError` separadamente do `Exception` genérico.
   - Inclui `retCode` + `retMsg` (truncado em 120 chars) na
     `manual_confirmations_needed` para diagnóstico. **Sem secrets**:
     `retCode`/`retMsg` são valores públicos da API, não credenciais.
   - Mantém o branch `Exception` para qualquer outra falha
     (Network/etc.), com apenas o tipo da exceção.
3. **Invariante preservada (FASE 22.1)**:
   - `build_demo_api_blueprint` continua bloqueando quando
     `manual_confirmations_needed` contém substring crítica de
     `open orders`. **Sem bypass.**
   - Se a leitura falhar mesmo após o fix de parâmetro (ex.: key sem
     permissão de leitura), operador agora vê retCode/retMsg no audit
     e pode investigar antes de re-rodar.

## Hotfix FASE 22.1 — TP via Risk-Reward + open-orders bloqueador

A versão inicial da FASE 22 gerava `take_profit=null` no proposal
quando o operador não passava `target_take_profit_factor` para o
preflight (default omitido por design da FASE 13). Isso fazia o gate
da FASE 20 abortar via `BLUEPRINT BRIDGE REJECTED` no Step 2 — gate
funcionava, mas Step 2 ficava inviável.

A FASE 22.1 entrega:

1. **`BybitDemoPreflight.target_take_profit_rr`** (alteração mínima):
   calcula TP a partir da distância real entre `reference_price` e
   `stop_loss` ponderada por RR, alinhado a `tick_size`. Mutuamente
   exclusivo com `target_take_profit_factor` (rejeitado no construtor).
   - **BUY:** `TP = entry + (entry - SL) * RR`, floor para tick.
   - **SELL:** `TP = entry - (SL - entry) * RR`, ceil para tick.
   - Sanity: BUY exige `TP > entry`; SELL exige `0 < TP < entry`.
2. **CLI `--take-profit-rr`** com default `DEFAULT_TAKE_PROFIT_RR=2.0`
   (constante nomeada/documentada/editável; não é regra de estratégia).
   Operador pode override. `<= 0` desliga TP.
3. **`DemoApiBlueprint.take_profit_rr`** (novo campo): audita o RR
   usado. Persistido no JSON e propagado por `load_from_json`.
4. **`build_demo_api_blueprint` agora bloqueia `manual_confirmations`
   críticos** relacionados a `open orders` (substring case-insensitive
   em `_CRITICAL_MANUAL_CONFIRMATION_SUBSTRINGS`). Sem bypass fácil
   nesta fase: `open_orders_count=0` retornado por defesa quando a
   API falhou não é tratado como confirmação confiável.
5. **`schema_version`** sobe para `2`. Blueprints `v1` são rejeitados
   por `load_from_json` (compatibilidade forward — operador re-roda
   Step 1).

## Princípios

- **Reaproveita** `BybitDemoPreflight` integralmente. Nenhuma duplicação
  de coleta de `instruments-info`, `orderbook`, `ticker`, `balance`,
  `positions`, `open_orders`, nem recálculo de `minOrderQty`,
  `qtyStep`, `minNotional`, `tickSize`, `reference_price`, `SL`, `TP`
  ou `risk_usd`.
- **Frozen + JSON-serializável + sem secrets.** Garantido por teste
  estrutural (`api_key`/`api_secret`/`Bearer`/`X-BAPI-SIGN`/`sign=` →
  nunca presentes no JSON).
- **TTL curto** (default 60s). Stale → rejeitado em `load_from_json`.
- **Bridge** `to_signal_blueprint(api_blueprint) → SignalBlueprint`.
  Exige `take_profit > 0` (FASE 20).
- **Caminho real não aceita valores manuais.** Qualquer combinação de
  flags reais (`--execute-demo`/`--confirm-demo-session`/
  `--operator-token`/`--i-understand-this-is-demo`) + `--entry`/`--sl`/
  `--tp`/`--size` agora é **bloqueada** com mensagem clara.

## Tipos

```python
@dataclass(frozen=True)
class DemoApiBlueprint:
    blueprint_id: str                # uuid4
    generated_at: datetime           # tz-aware UTC
    schema_version: int              # 1
    market_info: MarketInfo          # da FASE 9 (read-only)
    account_state: AccountState      # idem
    proposal: OrderProposal          # idem
    spread_pct: float                # derivado bid/ask/mid
    notional_usd: float              # derivado qty * reference_price
    risk_pct: float                  # risk_usd / capital * 100
    readiness_summary: Mapping       # counts auditáveis
    manual_confirmations_needed: tuple[str, ...]
    command_preview: str             # sanitizado, sem secrets
```

## Aborts (em `build_demo_api_blueprint`)

| Causa | Mensagem (substring) |
|---|---|
| `preflight_report.ok=False` | `"ok=False"` |
| `market_info`/`account_state`/`proposal` ausentes | nome do campo |
| `open_positions_count > 0` | `"open_position"` |
| `open_orders_count > 0` | `"open_order"` |
| Bid/ask não-positivos | `"bid/ask"` |
| `ask < bid` | `"ask < bid"` |
| `mid_price <= 0` | `"mid_price"` |
| `spread_pct > max_spread_pct` (default 0.10%) | `"spread"` |
| `leverage_confirmable=False` sem `accept_leverage_manual_confirmation=True` | `"leverage"` |

## Aborts (em `load_from_json`)

| Causa | Mensagem (substring) |
|---|---|
| Path com `..` | `".."` |
| Arquivo inexistente | `"inexistente"` |
| JSON malformado | `"json_invalid"` |
| JSON não é objeto | `"objeto"` |
| `schema_version` divergente | `"schema_version"` |
| Schema com campos faltando/inválidos | `"schema_invalid"` |
| `generated_at` no futuro | `"futuro"` |
| Idade > TTL | `"stale"` |

## Aborts (em `to_signal_blueprint`)

| Causa | Mensagem (substring) |
|---|---|
| `proposal.take_profit=None` | `"take_profit"` |
| `proposal.side` ≠ `"buy"`/`"sell"` | `"side"` |

## Fluxo operacional (CLI)

### Step 1 — Prepare (read-only, sem ordem)

```powershell
$env:PYTHONIOENCODING="utf-8"
python scripts/run_bybit_demo_session_gated.py `
    --prepare-demo-blueprint `
    --output blueprint.json `
    --profile personal --capital <CAPITAL> `
    --symbol BTCUSDT --side buy
```

Roda `BybitDemoPreflight` real (exige `.env` demo válido), aborta com
`PreflightAbortReason` em qualquer falha. Em sucesso, grava blueprint
JSON sanitizado e imprime `blueprint_id`, `generated_at`,
`spread_pct`, `notional_usd`, `risk_pct`, `manual_confirmations_needed`
e o `command_preview`.

### Step 2 — Execute from fresh blueprint (real, single-shot)

```powershell
$env:PYTHONIOENCODING="utf-8"
python scripts/run_bybit_demo_session_gated.py `
    --from-blueprint blueprint.json `
    --execute-demo --confirm-demo-session `
    --operator-token "operator@example.com" `
    --i-understand-this-is-demo
```

Carrega blueprint, valida TTL (default 60s; customizável via
`--blueprint-ttl-seconds`), reconstrói `SignalBlueprint` via bridge,
e chama `execute_demo_session_gated` (FASE 20) com o triple-lock
existente (4 flags CLI + prompt Y + gates internos). **Single-shot.**

## O que **não** funciona mais

- `--execute-demo` + `--entry`/`--sl`/`--tp`/`--size` manuais → **exit 1**
  com mensagem:
  > `Real demo execution requires a fresh API-driven blueprint. Manual
  > entry/sl/tp/size are allowed only for dry-run examples.`
- Dry-run preview com valores manuais (sem flags reais) **continua
  funcionando** como antes. Útil para validar pipeline sem rede.

## Arquivos

- [src/crypto_trading_bot/demo_session_execution/api_blueprint.py](../src/crypto_trading_bot/demo_session_execution/api_blueprint.py)
- [scripts/run_bybit_demo_session_gated.py](../scripts/run_bybit_demo_session_gated.py)
- [docs/hardcoded_values_audit_phase22.md](hardcoded_values_audit_phase22.md)
- [docs/demo_session_first_real_order_runbook.md](demo_session_first_real_order_runbook.md) — runbook atualizado para FASE 22.

## O que esta fase **não** faz

- Não envia ordem. Não chama `place_market_order`/`cancel_order`/
  `close_position`. Não implementa `reduceOnly`.
- Não promove provider. `bybit_demo_linear` permanece `OPT_IN`.
- Não altera `BybitDemoExecutor`, `BybitClient`, `BybitDemoPreflight`,
  `RiskEngine`, `ModeGuard`, `assert_live_allowed`, `ProviderRegistry`,
  `SessionRunner`, `demo_session_execution/{plan,outcome,gate}.py`.
- Não parametriza constantes do preflight (`SL_BUY_FACTOR`,
  `SL_SELL_FACTOR`, `CAPITAL_MARGIN_FACTOR`) — microfase futura se
  necessário.

## Próxima etapa operacional

Após `pytest` verde e nova sessão limpa de **dry-run preview**, operador
pode rodar o fluxo Step 1 + Step 2 com `.env` demo configurado e
ambiente Bybit Demo aberto. Runbook detalhado em
[demo_session_first_real_order_runbook.md](demo_session_first_real_order_runbook.md).
