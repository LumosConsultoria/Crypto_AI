# Backtesting Realismo — FASE 3E.1

Este documento descreve a modelagem de **custos de execução simulados** no backtesting:
fees, slippage e spread. Introduzida na FASE 3E.1.

> ⚠️ **Custos simulados são aproximações.** Não substituem teste em paper/testnet real.
> Resultados de backtest **NÃO garantem performance futura**.

---

## 1. Princípios

1. **Custo zero é o default absoluto.** Instanciar `ExecutionCostConfig()` sem
   argumentos preserva integralmente o comportamento da FASE 3D.5
   (560 testes existentes continuam verdes).
2. **PnL bruto e PnL líquido são separados.** `pnl_usd` continua representando o
   PnL **realizado/líquido** (após custos). `gross_pnl_usd` é o teórico (sem custos).
3. **Detecção de stop/TP usa preço teórico.** A regra `candle.low <= stop_loss_price`
   e `candle.high >= take_profit_price` continua inalterada. Slippage/spread ajustam
   apenas o **preço executado APÓS o hit ser detectado**.
4. **Slippage e spread sempre pioram a execução.**
5. **Regra conservadora preservada.** Stop loss continua tendo prioridade sobre
   take profit quando ambos são atingidos no mesmo candle.
6. **Provider-agnóstico.** Custos são passados por configuração explícita —
   nenhuma lógica condicional por `provider_name` no engine.
7. **Sem novas dependências.** Apenas `dataclasses` da biblioteca padrão.

---

## 2. Modelo de Custos

### `ExecutionCostConfig`

```
@dataclass(frozen=True)
class ExecutionCostConfig:
    taker_fee_pct: float = 0.0
    maker_fee_pct: float = 0.0
    slippage_pct: float = 0.0
    slippage_fixed_price_usd: float = 0.0
    spread_pct: float = 0.0
    spread_fixed_price_usd: float = 0.0
    fee_side: Literal["taker", "maker"] = "taker"
```

### Convenções de nomenclatura

- `*_pct` — fração decimal (`0.0006` = `0.06%`).
- `*_fixed_price_usd` — ajuste **em USD aplicado AO PREÇO DO ATIVO**.
  Exemplo: `slippage_fixed_price_usd=5.0` significa que o BTC é executado 5 USD
  mais caro (BUY entry) ou 5 USD mais barato (BUY exit). **Não é fee.**
- `*_fee_usd` (em outros módulos) — custo financeiro em USD do trade.

Esta separação evita ambiguidade entre "USD do preço do BTC" e "USD de custo do trade".

### Validação

- Todos os campos devem ser `>= 0` (custos não podem ser negativos).
- `fee_side` deve ser `"taker"` ou `"maker"`.
- Dataclass é **frozen** — imutável e safe.

---

## 3. Direção adversa

Slippage e spread **sempre** pioram a execução:

| Lado | Leg | Direção |
|---|---|---|
| BUY | entry | preço executado **maior** que o teórico (compra mais caro) |
| BUY | exit | preço executado **menor** que o teórico (vende mais barato) |
| SELL | entry | preço executado **menor** que o teórico (vende mais barato) |
| SELL | exit | preço executado **maior** que o teórico (cobre mais caro) |

A fórmula combinando slippage + spread:

```
pct_adj = slippage_pct + spread_pct
fixed_adj = slippage_fixed_price_usd + spread_fixed_price_usd

# Quando o ajuste é "para cima" (adverso):
price_executed = price_theoretical * (1 + pct_adj) + fixed_adj

# Quando o ajuste é "para baixo" (adverso):
price_executed = price_theoretical * (1 - pct_adj) - fixed_adj
```

---

## 4. Fees

- Aplicados como percentual sobre o **notional** (`position_size_usd`).
- Cobrados em ambos os legs: `entry_fee_usd` e `exit_fee_usd`.
- `taker` por padrão (`fee_side="taker"`). `maker` configurável.
- Total de fees do trade: `entry_fee_usd + exit_fee_usd`.

---

## 5. Detecção de hit usa preço TEÓRICO

A regra de hit do `BacktestEngine` permanece exatamente como na FASE 3D.5:

```
# BUY
stop_hit = candle.low <= trade.stop_loss_price
tp_hit   = candle.high >= trade.take_profit_price
```

Apenas **depois** que o hit é detectado, o preço executado é ajustado por
slippage/spread. Para BUY com SL hit:

```
exit_price_theoretical = trade.stop_loss_price  # rastreado em BacktestTrade
exit_price (executado) = stop_loss_price * (1 - slippage_pct - spread_pct) - fixed
```

> ⚠️ É realista — e esperado — que o `exit_price` final possa ficar **abaixo**
> do `stop_loss_price` quando o preço deslizou através do nível. Isto é o "stop drift".

### Regra de ambiguidade

Inalterada: se um candle satisfaz `stop_hit` **E** `tp_hit`, o **STOP LOSS** tem
prioridade (conservador). Custos não alteram essa ordem de prioridade.

---

## 6. PnL Bruto vs. PnL Líquido

| Campo (BacktestTrade) | Significado |
|---|---|
| `entry_price_theoretical` | Preço de entrada SEM custos (close do candle) |
| `entry_price` | Preço de entrada EXECUTADO (com slippage/spread) |
| `exit_price_theoretical` | Preço de saída SEM custos (stop_loss_price / TP / EOD close) |
| `exit_price` | Preço de saída EXECUTADO (com slippage/spread) |
| `entry_fee_usd` | Fee paga ao abrir o trade |
| `exit_fee_usd` | Fee paga ao fechar o trade |
| `entry_slippage_cost_usd` | Custo de slippage+spread na entrada, em USD sobre o notional |
| `exit_slippage_cost_usd` | Custo de slippage+spread na saída, em USD sobre o notional |
| `gross_pnl_usd` | PnL teórico (preços teóricos, sem fees) |
| `pnl_usd` | **PnL LÍQUIDO realizado** (preços executados, menos fees) |

Para `BacktestReport`:

| Campo | Significado |
|---|---|
| `total_pnl_usd` | PnL líquido total (inalterado em significado desde FASE 3D) |
| `gross_total_pnl_usd` | Soma dos `gross_pnl_usd` dos trades |
| `net_total_pnl_usd` | Alias semântico de `total_pnl_usd` |
| `total_fees_usd` | Soma de `entry_fee + exit_fee` de todos os trades |
| `total_slippage_usd` | Soma de `entry_slippage + exit_slippage` de todos os trades |
| `total_execution_cost_usd` | `total_fees_usd + total_slippage_usd` |

> Com `ExecutionCostConfig()` zerado: `gross_total_pnl_usd == net_total_pnl_usd` e
> todos os custos somam zero.

---

## 7. Challenge target continua apenas KPI

`challenge_target_reached` continua olhando `total_pnl_usd` (líquido).
- Backtest **sempre** roda até o fim dos dados.
- Sem `max_profit_usd` bloqueante.
- Sem trava de lucro.
- Com custos > 0, basta o PnL **líquido** atingir a meta para o KPI ficar `True` —
  e ainda assim o backtest não é interrompido.

---

## 8. Provider-agnóstico

Custos **nunca** são inferidos de `provider_name`. Cada cenário passa
`ExecutionCostConfig` explicitamente. Exemplos:

```python
# Conta personal com custos típicos de exchange spot
ExecutionCostConfig(taker_fee_pct=0.001, slippage_pct=0.0003, spread_pct=0.0002)

# Prop firm (custos hipotéticos — configure conforme realidade)
ExecutionCostConfig(taker_fee_pct=0.0006, slippage_pct=0.0005, spread_pct=0.0002)
```

Os perfis em `ACCOUNT_PROFILES` **não** carregam custos. Quem quiser combiná-los
faz isso na chamada ao `BacktestEngine`.

---

## 9. Uso no `run_backtest.py`

```bash
# Backtest sem custos (FASE 3D.5 compatível)
python scripts/run_backtest.py --candles 100 --trend 0.001

# Backtest com custos realistas
python scripts/run_backtest.py --candles 100 --trend 0.001 \
    --fee-pct 0.0006 --slippage-pct 0.0005 --spread-pct 0.0002
```

Quando `--fee-pct`, `--slippage-pct` ou `--spread-pct` for > 0, o `summary()` do
report inclui a seção `💰 CUSTOS DE EXECUÇÃO`. Quando todos forem zero, o summary
permanece idêntico ao da FASE 3D.5.

---

## 10. Stress tests (FASE 3E.3)

A FASE 3E.3 adicionou uma camada de stress tests em
[tests/test_backtest_stress.py](../tests/test_backtest_stress.py) para validar
robustez da modelagem de custos e métricas avançadas contra cenários extremos.
Nenhum componente de execução foi alterado — apenas testes e um novo gerador
de dados.

### Cenários cobertos

| Cenário | Classe de teste | Validação principal |
|---|---|---|
| Fees extremas (5%) | `TestExtremeFees` | Trade bruto vencedor vira líquido perdedor; agregados de fees corretos |
| Slippage extremo (5%) | `TestExtremeSlippage` | `entry_price >= 4%` acima do teórico; `total_slippage_usd` escala com notional |
| Spread amplo (2%) | `TestExtremeSpread` | `total_execution_cost_usd` cresce; detecção de hit ainda usa preço teórico |
| Sequência de 10 perdas | `TestLongLosingStreak` | `max_consecutive_losses==10`, drawdown ≈ soma das perdas, R:R ≈ -1.0 |
| Gap contra posição | `TestGapAgainstPosition` | `exit_price_theoretical == stop_loss_price`; com slippage, `exit_price < stop` |
| Alta volatilidade (5%) | `TestHighVolatilityBacktest` | Engine sobrevive; anti-lookahead preservado |
| Poucos dados | `TestSparseData` | Zero trades; métricas em estado vazio coerente |
| Candles degenerados (vol=0, high==low) | `TestDegenerateButValidCandles` | Carregamento e backtest sem erro |
| Combinação | `TestCombinedStressScenario` | Sem NaN/inf; `net <= gross`; métricas calculáveis ou `None` |

### Novo gerador: `generate_volatile_candles`

```python
from crypto_trading_bot.backtesting import generate_volatile_candles

candles = generate_volatile_candles(
    n=200,
    base_price=65000.0,
    volatility_pct=0.05,           # spread intracandle ~5%
    trend_pct_per_candle=0.0,      # default: volatilidade pura sem tendência
)
```

- Determinístico (sem `random`): chamadas idênticas produzem candles idênticos.
- Mantém todas as invariantes OHLCV verificadas em
  `TestSyntheticCandlesOhlcvInvariants` (parametrizado em 4 geradores).
- Útil para testes de robustez; **não substitui** dados reais para análise de
  performance.

### Interpretando resultados de stress

- **Cenários extremos não preveem performance real** — apenas auditam que o
  engine permanece estável, métricas permanecem calculáveis e o relatório
  permanece coerente sob stress.
- "Trade bruto vencedor / líquido perdedor" mostra como custos podem **inverter**
  o resultado aparente — útil para calibrar expectativas antes de paper trading.
- Sequência longa de perdas valida que `max_drawdown_usd` reflete a queda total
  do pico ao vale, não apenas o último trade.

---

## 11. Out-of-Sample + Walk-Forward (FASE 3E.4A)

A FASE 3E.4A adicionou validação temporal **sem treinar modelo**. Aqui o
walk-forward serve para auditar consistência temporal e detectar overfitting
**qualitativo** (variabilidade entre folds, divergência in-vs-out).

### Componentes

| Função | Arquivo | Propósito |
|---|---|---|
| `split_in_sample_out_of_sample` | `data_splits.py` | Divisão única treino/teste preservando ordem cronológica |
| `walk_forward_split` | `data_splits.py` | N folds rolling adjacentes; sobra descartada explicitamente |
| `run_walk_forward` | `walk_forward.py` | Orquestra N folds × 2 backtests (train + test) com 2 strategies novas por fold |
| `compare_reports` | `walk_forward.py` | Deltas in-vs-out de métricas chave |
| `summarize_walk_forward` | `walk_forward.py` | Agregados multi-fold (média, std, min/max, consistency_pass_rate) |
| `WalkForwardFoldResult` | `walk_forward.py` | Dataclass imutável `(fold_index, train_report, test_report)` |

### Garantias

- **Ordem cronológica preservada** em todos os splits.
- **Folds adjacentes não-sobrepostos**: nenhum candle aparece em mais de 1 fold.
- **2 strategy_factory calls por fold** (uma para train, outra para test) — zero
  risco de vazamento de estado entre as duas execuções do mesmo fold.
- **Cada fold tem RiskEngine e FeatureEngine independentes** (capital inicial
  fresco por execução).
- `BacktestEngine` não foi alterado — usado como caixa-preta com a mesma
  interface da FASE 3D/3E.1/3E.2.
- `ExecutionCostConfig` propagado uniformemente em todos os folds.
- `challenge_profit_target_usd` propagado a cada `BacktestReport` como KPI
  (jamais bloqueia trades; backtest sempre roda até o fim).

### Sobra de candles (decisão explícita)

Quando `len(candles) % n_folds != 0`, os últimos `(n % n_folds)` candles são
**descartados do final**. Folds ficam com tamanho IGUAL. Comportamento
determinístico, documentado em `data_splits.walk_forward_split.__doc__` e
testado em `test_remainder_is_discarded_when_not_evenly_divisible`.

### Política de `std=None`

`summarize_walk_forward(fold_results)` retorna `std_test_pnl_usd = None`
quando `len(fold_results) == 1`. Justificativa: zero variabilidade observável
não significa "estável" — retornar `0.0` poderia ser interpretado erroneamente.

### Como interpretar resultados

- **`consistency_pass_rate` baixo** (poucos folds lucrativos) sugere que a
  estratégia depende muito de períodos específicos.
- **`std_test_pnl_usd` alto** indica volatilidade de resultado por janela
  temporal (sinal de overfitting ou regime-dependence).
- **Divergência grande em `compare_reports(train, test)` por fold** (in muito
  lucrativo, out perdedor) é o clássico **sinal de overfitting**.
- Reforço: backtest **não garante** performance futura — walk-forward apenas
  reduz risco de cair em overfitting óbvio.

### Limitação reconhecida — sem ajuste de parâmetros

Como o projeto **não treina modelos** e não ajusta parâmetros de estratégia
automaticamente, o "train" aqui não modifica a estratégia. As 2 instâncias por
fold são determinísticas e o `train_report` serve apenas como referência para
comparação com o `test_report`. Esta limitação é INTENCIONAL na FASE 3E.4A.

---

## 12. Latência simulada (FASE 3E.4B)

A FASE 3E.4B adicionou modelagem de latência de execução. Configurada via
`ExecutionCostConfig.entry_latency_candles` (default `0`).

### Comportamento

| Valor | Efeito |
|---|---|
| `entry_latency_candles = 0` | Execução IMEDIATA no `close` do candle de geração (regressão BYTE-A-BYTE com FASE 3E.4A). |
| `entry_latency_candles = N` (N > 0) | Sinal vira "pending"; executa no `open` do candle `i + N`. |

### Regras do pending signal

1. **Estratégia bloqueada enquanto pending ativo.** O `BacktestEngine` NÃO
   chama `strategy.evaluate()` entre a geração do sinal e sua execução.
2. **Stop/Take Profit ORIGINAIS preservados.** O pending carrega `stop_loss_price`
   e `take_profit_price` do sinal original; não recalcula.
3. **RiskEngine REVALIDA no candle de execução.** A 2ª chamada a
   `validate_signal` pode reprovar (limite estourou na espera). Em caso de
   rejeição: pending descartado, `risk_blocked_count += 1`.
4. **`on_signal_approved` chamado apenas na EXECUÇÃO** (não na geração).
   Simula "ordem submetida ao exchange, aguardando preenchimento".
5. **`record_trade_opened` apenas na execução real.**
6. **Expiração silenciosa.** Se `i + entry_latency_candles >= len(candles)`,
   pending expira sem trade. Apenas log info; NÃO incrementa
   `risk_blocked_count` (não foi RiskEngine que bloqueou).
7. **SL/TP NÃO avaliados no candle de execução.** Regra existente
   `candle_idx <= entry_candle_idx` continua válida — `entry_candle_idx` passa
   a ser o candle de **execução** (não o de geração).

### Anti-lookahead preservado

Pending nunca acessa candles futuros. A lógica de carry-over usa apenas o
índice ATUAL (`i`) comparado a `executes_at_idx`. Nenhum `candles[i+anything]`
é lido fora do índice corrente. Teste dedicado:
`tests/test_backtest_latency.py::test_pending_does_not_make_strategy_see_future_candles`.

### Direção adversa preservada

Latência interage com slippage/spread (FASE 3E.1) sem mudar a direção adversa:
- BUY entry executada no `open` do candle de destino + slippage/spread
  → preço mais alto (pior).
- SELL entry simétrico → preço mais baixo (pior).
- Exit (SL/TP) continua usando preço teórico para detecção; slippage ajusta
  o exit executado APÓS o hit.

### Garantia de regressão perfeita

Quando `entry_latency_candles == 0`:
- `BacktestEngine.run()` segue o caminho EXATO da FASE 3E.4A.
- Sem criação de pending signal.
- Entrada IMEDIATA no `close` do candle de geração.
- Equity curve, trades e métricas BYTE-A-BYTE idênticos.

Testes dedicados em `tests/test_backtest_latency.py::TestZeroLatencyRegression`:
- `test_zero_latency_total_trades_identical`
- `test_zero_latency_equity_curve_identical`
- `test_zero_latency_stop_loss_scenario_identical`
- `test_zero_latency_take_profit_scenario_identical`
- `test_zero_latency_ambiguity_scenario_identical`

### Compatibilidade com walk-forward

A latência é propagada transparentemente para todos os folds do walk-forward
via `ExecutionCostConfig`. `walk_forward.py` NÃO foi alterado nesta subfase —
usa `BacktestEngine` como caixa-preta. Teste dedicado:
`tests/test_backtest_latency.py::TestWalkForwardWithLatency`.

### Limitações reconhecidas

- **Latência fixa por trade** — não modela jitter ou cancelamentos.
- **Não há "cancelamento de ordem"** durante a espera; pending segue até
  executar ou expirar.
- **Maker/taker mais sofisticado** (sinal escolhe estratégia de ordem) fora
  de escopo.

---

## 13. Limitações conhecidas (FASE 3E completa)

A FASE 3E entregou modelagem realista suficiente para AUDITAR sensibilidade
de estratégias a custos, slippage, spread e latência. Limitações que
permanecem:

- **Funding rate / borrow cost**: fora de escopo (perpetual futures).
- **Profit/loss em moeda da exchange vs. USD**: assume conversão 1:1.
- **Tabelas tier de fee por volume**: não modelado (taker/maker fixos).
- **Slippage assimétrico por tamanho de ordem**: o slippage é fixo, não modela
  market impact por book depth.
- **Latência fixa por trade**: sem jitter ou cancelamentos durante a espera.
- **Sem ajuste de parâmetros automático**: walk-forward apenas valida
  consistência temporal; não treina modelo nem otimiza parâmetros.

A implementação atual é **suficiente para auditar sensibilidade da estratégia a
custos, latência e variabilidade temporal**, mas NÃO substitui:

- Testes em ambiente paper/testnet real.
- Validação em dados históricos reais (não sintéticos).
- Análise out-of-sample com dados desconhecidos ao desenvolvedor.

> ⚠️ **Resultados de backtest NÃO garantem performance futura.** Reforçado em
> cada subfase desde a 3D.
