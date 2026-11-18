# Strategy Research Framework — FASE 3F

> ⚠️ **RANKING NÃO GARANTE PERFORMANCE FUTURA.**
> ⚠️ Backtest é APROXIMAÇÃO; valide em paper/testnet real antes de qualquer execução em conta real.
> ⚠️ Este framework NÃO faz otimização automática de parâmetros.

---

## Visão geral

O `research/` é o framework de **avaliação e comparação** de estratégias quantitativas. Ele NÃO inventa estratégias — apenas oferece uma camada padronizada para:

- Registrar uma estratégia como `StrategySpec` (nome + factory + config padrão).
- Avaliar uma spec sobre um dataset com `evaluate_strategy()` (backtest single + opcionalmente walk-forward).
- Comparar várias specs no mesmo dataset com `compare_strategies()`.
- Rankear por uma métrica conservadora com `rank_strategies()` (3 rankings independentes).
- Imprimir tabela com avisos obrigatórios via `summarize_comparison()`.

Usa o `BacktestEngine`, `ExecutionCostConfig`, `run_walk_forward()` da FASE 3E **como caixa-preta** — sem alterar nada na pipeline existente.

---

## Garantias arquiteturais

| Garantia | Como |
|---|---|
| Não altera `BacktestEngine` / `BacktestTrade` / `BacktestReport` | Apenas consome via imports |
| Não altera `ExecutionCostConfig` / `walk_forward.py` | Reutiliza inalterados |
| `RiskEngine` permanece soberano | `evaluate_strategy()` chama `BacktestEngine` que chama `validate_signal()` |
| `ModeGuard` intocado | Sem qualquer referência |
| Provider-agnostic | Zero menção a `provider_name` no spec ou no runner |
| Sem `max_profit_usd` bloqueante | Nenhum campo introduzido |
| Challenge target permanece KPI | Propagado sem virar trava |
| Sem dependências novas | Apenas `dataclasses`, `types.MappingProxyType` (stdlib) |
| Determinístico | Mesmo dataset + mesmas specs → mesmo ranking |

---

## Componentes

### `StrategySpec`

Dataclass **frozen** (imutável) que representa uma estratégia registrada.

```python
from crypto_trading_bot.research import StrategySpec

def my_factory(config):
    s = MyStrategy(**config)
    s.set_running()
    return s

spec = StrategySpec(
    name="my_strat_default",
    factory=my_factory,
    description="Demo trend-following",
    default_config={"ema_period": 21, "rsi_period": 14},
    tags=("trend-following", "demo"),
)
```

**Proteções:**
- `default_config` é convertido para `MappingProxyType(dict(...))` (snapshot read-only).
- Mutar o dict ORIGINAL após criação NÃO altera o spec.
- `tags` é convertido para `tuple` imutável.
- `name` vazio ou factory não-callable → `ValueError`.

### `StrategyRegistry`

Registro **instanciável** (sem singleton global). Cada caso de uso cria o seu.

```python
from crypto_trading_bot.research import StrategyRegistry

reg = StrategyRegistry()
reg.register(spec)
spec_recovered = reg.get("my_strat_default")
reg.list_names()  # ordem alfabética
"my_strat_default" in reg  # True
len(reg)  # 1
reg.clear()  # útil para testes
```

- Registrar nome duplicado → `ValueError` (evita override silencioso).
- `get(unknown)` → `KeyError`.

### `evaluate_strategy()`

Avalia uma spec sobre um dataset.

```python
from crypto_trading_bot.research import evaluate_strategy
from crypto_trading_bot.backtesting import ExecutionCostConfig

result = evaluate_strategy(
    spec=spec,
    candles=candles,
    config_override={"ema_period": 14},   # mescla sobre default_config
    initial_capital=5000.0,
    execution_cost_config=ExecutionCostConfig(taker_fee_pct=0.0006),
    challenge_profit_target_usd=500.0,    # KPI (não bloqueia)
    walk_forward_n_folds=5,               # opcional; None = só single
    walk_forward_train_pct=0.7,
)

print(result.single_report.summary())
print(result.wf_summary)
print(f"Divergência overfitting: ${result.overfitting_divergence_usd:.2f}")
```

**O que faz:**
1. Roda 1 backtest single no dataset inteiro.
2. Se `walk_forward_n_folds` for fornecido, chama `run_walk_forward()` existente.
3. Calcula `overfitting_divergence_usd = |single_pnl - mean(wf_test_pnl)|`.
4. Retorna `StrategyEvaluationResult` imutável.

**`config_override` mescla sobre default_config:** `{**default, **override}`. Spec.default_config NÃO é mutado.

### `compare_strategies()`

Avalia múltiplas specs no MESMO dataset com os MESMOS parâmetros de runner.

```python
from crypto_trading_bot.research import compare_strategies

results = compare_strategies(
    specs=[spec_a, spec_b, spec_c],
    candles=candles,
    walk_forward_n_folds=5,
)
```

- Sem otimização automática.
- Ordem do retorno = ordem de entrada (determinístico).

### `rank_strategies()`

**3 rankings INDEPENDENTES** — sem composite score.

```python
from crypto_trading_bot.research import rank_strategies

# Por expectancy_usd (maior é melhor)
ranked_by_expectancy = rank_strategies(results, metric="expectancy_usd", min_trades=30)

# Por net_profit_factor (maior é melhor; None vai para o fim)
ranked_by_pf = rank_strategies(results, metric="net_profit_factor", min_trades=30)

# Por max_drawdown_pct (menos negativo é melhor)
ranked_by_dd = rank_strategies(results, metric="max_drawdown_pct", min_trades=30)
```

**Métricas e convenções:**

| Métrica | Sinal "melhor" | None? |
|---|---|---|
| `expectancy_usd` | maior é melhor | sempre float |
| `net_profit_factor` | maior é melhor | `None` vai para o FIM |
| `max_drawdown_pct` | maior (menos negativo) é melhor | sempre float |

**`min_trades`** (default 0): filtra resultados com `total_trades < min_trades`. Recomendação: usar `>= 30` em comparações sérias (evita cherry-picking de "1 trade lucrativo sortudo").

**SEM composite score:** métricas têm trade-offs. Uma estratégia com `expectancy_usd` alto pode ter `max_drawdown_pct` péssimo. Componer em um único score esconderia essa nuance. Use os 3 rankings INDEPENDENTEMENTE.

### `summarize_comparison()`

Tabela textual com avisos obrigatórios.

```python
from crypto_trading_bot.research import summarize_comparison

print(summarize_comparison(results))
```

Saída exemplo:

```
================================================================================
  📊 STRATEGY RESEARCH — COMPARISON SUMMARY
  ⚠️  RANKING NÃO GARANTE PERFORMANCE FUTURA.
  ⚠️  Backtest é aproximação; valide em paper/testnet real.
================================================================================
  Estratégias avaliadas: 3

────────────────────────────────────────────────────────────────────────────────
  Strategy                  Trades      PnL$   Expec.     PF  MaxDD%   Flag
────────────────────────────────────────────────────────────────────────────────
  strat_a                       42    +56.20   +1.34    2.10   -3.50
  strat_b                       28   -12.40   -0.44    0.85   -8.20   ⚠️  OF?
  strat_c                       65   +120.50   +1.85    3.20   -2.10
────────────────────────────────────────────────────────────────────────────────

  Legenda:
    Expec. = expectancy_usd (PnL líquido esperado/trade)
    PF     = net_profit_factor
    MaxDD% = max_drawdown_pct (negativo; menos negativo é melhor)
    OF?    = overfitting suspeito (|single - mean_wf| > 20% de |single|)

  ⚠️  Métricas têm trade-offs.
  ⚠️  Não existe 'melhor estratégia única'.
  ⚠️  Use 3 rankings independentes: expectancy / profit_factor / drawdown.
  ⚠️  Backtest NÃO garante performance futura.
================================================================================
```

A flag **`⚠️ OF?`** aparece quando `walk_forward_n_folds` foi fornecido E a divergência walk-forward excede o limiar (default 20% do single PnL).

---

## Proteções contra overfitting incorporadas

1. **Sem auto-tuning de parâmetros.** O runner avalia spec com `default_config + config_override`. Nunca itera buscando "melhor config" automaticamente.

2. **3 rankings independentes** (sem composite). Mascara trade-offs é mais perigoso que admitir que não existe métrica única ótima.

3. **`min_trades` filter** — exclui estratégias com trades insuficientes. Documentação recomenda `>= 30` para comparações sérias.

4. **`overfitting_divergence_usd` exposto.** Se `walk_forward_n_folds` foi fornecido, a divergência entre PnL single e média de PnL de test do walk-forward é calculada e EXIBIDA no summary com flag visual.

5. **Walk-forward opcional, mas recomendado.** Single sozinho é frágil. Documentação reforça o uso.

6. **Avisos obrigatórios em todo output.** `summarize_comparison()` SEMPRE contém o aviso "RANKING NÃO GARANTE PERFORMANCE FUTURA" — não pode ser omitido por flag.

7. **Resultados imutáveis e determinísticos.** `StrategyEvaluationResult` é frozen; `config_used` é read-only; mesmo dataset + mesmas specs → mesmo ranking.

---

## Anti-patterns reconhecidos (NÃO faça)

- ❌ **NÃO** crie 1000 specs variando parâmetros e selecione "a melhor" pelo ranking. Isso é parameter sweep disfarçado e gera overfitting.
- ❌ **NÃO** confie em `expectancy_usd` alto sem olhar drawdown.
- ❌ **NÃO** apresente o ranking a usuários sem o aviso de não-garantia.
- ❌ **NÃO** assuma que walk-forward verde = estratégia robusta. É apenas um sinal a mais.
- ❌ **NÃO** rode walk-forward em datasets minúsculos (folds < 50 candles → zero trades).
- ❌ **NÃO** use min_trades=0 em comparações que terão impacto em decisões reais.

---

## Provider-agnostic

O framework **não menciona `provider_name`** em nenhum ponto. Capital, custos e meta de challenge são parâmetros explícitos do `evaluate_strategy()`. Quem quiser modelar diferentes prop firms passa diferentes `initial_capital` e `ExecutionCostConfig` — sem dependência da string `provider_name`.

```python
# Modelando 3 cenários de conta SEM tocar em provider_name
result_personal = evaluate_strategy(spec, candles, initial_capital=5000.0)
result_funded   = evaluate_strategy(spec, candles, initial_capital=25000.0)
result_with_fee = evaluate_strategy(
    spec, candles,
    initial_capital=5000.0,
    execution_cost_config=ExecutionCostConfig(taker_fee_pct=0.001),
)
```

---

## Status da FASE 3F

- 40 testes dedicados em `tests/test_strategy_research.py`.
- Zero alteração em `src/` fora do novo módulo `research/`.
- Documentação completa neste arquivo.
- Integração com FASE 3E (custos, walk-forward, métricas) via caixa-preta.

> ⚠️ Recapitulação final: backtest, walk-forward, ranking — todos são auxílios à decisão. **NÃO garantem performance futura.** Sempre valide em paper/testnet real.

---

## FASE 10 — Estratégias determinísticas + matriz de robustez offline

A FASE 10 adiciona duas estratégias determinísticas registráveis no
`StrategyRegistry` e uma matriz de robustez 2×4×3 (offline, sintético) para
auditoria humana de comportamento sob diferentes regimes e custos. O escopo é
estritamente de **pesquisa**: nenhuma destas peças promove provider, executa
ordem real, instala dependência nova ou ajusta parâmetros automaticamente.

### Estratégias adicionadas

| Strategy | Arquivo | Lógica de entrada (BUY-only) | Stop / TP |
|---|---|---|---|
| `trend_pullback_default` | `strategies/trend_pullback_strategy.py` | EMA(fast)>EMA(slow) AND close em zona EMA AND RSI<overbought | `entry - k×ATR` (fallback %) / `entry + R:R × risco` |
| `vol_breakout_default` | `strategies/volatility_breakout_strategy.py` | close>bb_upper×(1+buffer) AND bb_bandwidth≥min AND close>EMA(filter) | `entry - k×ATR` (fallback %) / `entry + R:R × risco` |

Ambas:
- Implementam o contrato `BaseStrategy`.
- Recebem `position_size_usd` via construtor/`StrategySpec.default_config` —
  zero hardcode de capital, sizing, leverage ou risco em runtime.
- Garantem invariante BUY: `0 < stop_loss < entry < take_profit`.
- Expõem `build_*_spec()` que devolve `StrategySpec` compatível com
  `evaluate_strategy` / `compare_strategies` / `rank_strategies`.

### Matriz de robustez 2 × 4 × 3

Implementada em `tests/test_strategy_robustness_research.py`.

- **Estratégias:** as 2 acima.
- **Cenários sintéticos:** `trending`, `ranging`, `high_vol`, `choppy_whipsaw`
  (todos gerados por `backtest_data.py` — offline e determinísticos).
- **Perfis de custo:** `zero`, `realistic`, `stressed` — todos via
  `ExecutionCostConfig` existente, sem campos novos. O perfil `stressed`
  usa `entry_latency_candles=2` (não `latency_ms`).

A saída tabular (`_format_matrix`) é multi-coluna humano-legível, **sem
composite score** e **sem "melhor estratégia absoluta"**. Cada célula expõe
`total_trades`, `total_pnl_usd`, `expectancy_usd`, `net_profit_factor` e
`max_drawdown_pct` independentemente.

### Walk-forward como AVALIAÇÃO

A FASE 10 reusa `run_walk_forward` da FASE 3E **sem otimização**:

- Cada fold usa **parâmetros fixos** (os de `spec.default_config` + override
  imutável).
- Cada fold cria **nova instância** de estratégia via `spec.factory(dict(...))`.
- Nenhum estado é compartilhado entre folds (sem leakage).
- Nenhum grid search, parameter sweep ou ajuste para "vencer" um cenário.

### Anti-patterns explicitamente proibidos nesta fase

- Composite score que combine PnL + drawdown + PF em um número único.
- Eleger "melhor estratégia" absoluta a partir de cenário sintético.
- Tuning de parâmetros para casar cenário específico.
- Tornar `challenge_profit_target_usd` um bloqueio.
- Promover provider, alterar `ModeGuard`, `assert_live_allowed`, `RiskEngine`,
  `ProviderRegistry`, `BotEngine`, `PaperTrader`, `BacktestEngine`,
  `BacktestReport`, `walk_forward`, `ExecutionCostConfig`, `BybitClient`,
  `BybitDemoExecutor`, `BybitTestnetExecutor`, providers ou `FeatureEngine`.

> ⚠️ Reforço final: dados sintéticos e custos modelados são aproximações.
> Resultados da matriz **NÃO garantem performance futura**.

> ℹ️ Sobre saídas: TP no backtest é detectado por `candle.high >= tp_price`
> (regra conservadora SL-vence-TP no mesmo candle). Em execução real, o
> preenchimento depende de wick/gap/slippage/livro/tipo de ordem.
> Veja [docs/exit_policy.md](exit_policy.md) (FASE 11).
