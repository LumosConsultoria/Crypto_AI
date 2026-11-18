# Backtesting — Documentação

> ⚠️ **Resultados de backtest NÃO garantem performance futura.**
> ⚠️ Dados sintéticos NÃO representam condições reais de mercado.
> ⚠️ Valide com dados out-of-sample antes de operar em conta real.

---

## Visão Geral

O módulo de backtesting permite simular estratégias sobre dados históricos sem enviar ordens reais.

**Princípios fundamentais:**
- Zero ordens reais enviadas
- Zero conexão com APIs externas
- Zero API keys necessárias
- Anti-lookahead bias por design
- RiskEngine soberano e obrigatório
- Meta de challenge = apenas KPI (nunca bloqueia trades)
- Bot agnóstico de provider (HyroTrader é apenas template)

**Paper Trading Orquestrado (FASE 4):**
- `PaperTradingOrchestrator` em
  [paper_orchestrator.py](../src/crypto_trading_bot/execution/paper_orchestrator.py):
  sessões contínuas de paper trading reutilizando `BotEngine` (intocado).
- `PaperSessionConfig.capital` é **OBRIGATÓRIO** — sem default 5000.
- Source de candles configurável: `MOCK_EXCHANGE`, `CACHE` (FASE 3G), `INMEMORY`.
- Modo `dry_run` força HOLD em todos os ciclos (audita pipeline sem executar).
- Integra `StrategySpec` da FASE 3F.
- ZERO ordens reais, ZERO API key, ZERO endpoint privado.
- Documentação completa em [paper_trading.md](paper_trading.md).

**Dados Históricos Reais + Data Quality (FASE 3G):**
- Camada read-only para candles públicos da Bybit em
  [historical_data.py](../src/crypto_trading_bot/data/historical_data.py).
- `DataCache` em CSV local + `DataQualityValidator` (gaps, duplicatas, OHLCV inválido).
- `BybitClient` extendido com `start_ms`/`end_ms` opcionais (retrocompatível).
- Cache local em `data/historical/` (gitignorado).
- Script CLI manual: `scripts/download_historical_data.py` (com `--dry-run`).
- **Testes 100% offline** (`BybitClient` mockado).
- Após download, backtests rodam offline.
- Documentação completa em [historical_data.md](historical_data.md).

**Strategy Research Framework (FASE 3F):**
- Camada de pesquisa em [research/strategy_research.py](../src/crypto_trading_bot/research/strategy_research.py):
  `StrategySpec`, `StrategyRegistry`, `evaluate_strategy()`, `compare_strategies()`,
  `rank_strategies()`, `summarize_comparison()`.
- Usa `BacktestEngine` + `ExecutionCostConfig` + `run_walk_forward()` como caixa-preta
  (sem alterar nada da FASE 3E).
- 3 rankings INDEPENDENTES (expectancy / net_profit_factor / max_drawdown_pct) —
  **sem composite score**, sem auto-otimização de parâmetros.
- Divergência walk-forward vs. single exposta como flag de overfitting suspeito.
- Documentação completa em [strategy_research.md](strategy_research.md).

**Latência simulada (FASE 3E.4B):**
- `ExecutionCostConfig.entry_latency_candles` (default 0) controla o atraso
  entre geração do sinal e execução efetiva.
- Latência 0 → execução IMEDIATA no `close` do candle (regressão perfeita
  byte-a-byte com FASE 3E.4A).
- Latência N > 0 → sinal vira "pending"; executa no `open` do candle `i+N`.
- Pending revalidado pelo RiskEngine no momento da execução.
- Estratégia NÃO é chamada enquanto há pending ativo.
- Stop/take usam valores ORIGINAIS do sinal (não recalculam).
- Se candle de execução não existe → pending expira sem trade (log info).
- Anti-lookahead preservado: pending nunca acessa candles futuros.

**Realismo (FASE 3E.1):**
- Custos de execução (fees, slippage, spread) modelados em `ExecutionCostConfig`.
- Custo zero (default) preserva integralmente o comportamento da FASE 3D.5.
- PnL bruto e PnL líquido separados em `BacktestTrade` e `BacktestReport`.
- Ver [backtesting_realism.md](backtesting_realism.md) para detalhes.

**Out-of-Sample + Walk-Forward (FASE 3E.4A):**
- Splits cronológicos em
  [data_splits.py](../src/crypto_trading_bot/backtesting/data_splits.py):
  `split_in_sample_out_of_sample(candles, in_sample_pct=0.7)` e
  `walk_forward_split(candles, n_folds=5, train_pct=0.7)` (rolling/sliding).
- Orquestrador em
  [walk_forward.py](../src/crypto_trading_bot/backtesting/walk_forward.py):
  `run_walk_forward()` retorna `List[WalkForwardFoldResult]` com 2 instâncias
  de estratégia FRESH por fold (uma para train, outra para test).
- Helpers `compare_reports(in, out)` e `summarize_walk_forward(folds)` para
  análise multi-fold (média, desvio padrão, min/max, consistency pass rate).
- **Sobra descartada explicitamente** quando `len(candles) % n_folds != 0`
  (folds iguais; última sobra de `n % n_folds` candles vai embora).
- `BacktestEngine` usado como caixa-preta — sem alteração estrutural.
- Custos da FASE 3E.1 propagados uniformemente em todos os folds.
- Challenge target propagado como KPI (não bloqueia).
- Latência simulada **NÃO** está nesta subfase — fica para FASE 3E.4B.

**Stress tests (FASE 3E.3):**
- Cenários offline determinísticos em [tests/test_backtest_stress.py](../tests/test_backtest_stress.py):
  fees/slippage/spread extremos, sequência longa de perdas, gap contra posição,
  alta volatilidade, poucos dados, candles degenerados, combinação de stress.
- Novo gerador `generate_volatile_candles()` em
  [backtest_data.py](../src/crypto_trading_bot/backtesting/backtest_data.py) —
  determinístico (sem random), oscilação senoidal de alta amplitude, mantém
  invariantes OHLCV (incluído em `TestSyntheticCandlesOhlcvInvariants`).
- Cenários combinados validam propriedades estruturais (sem NaN/inf,
  `net <= gross` com custos, métricas calculáveis ou `None` corretamente).
- Ver [backtesting_realism.md](backtesting_realism.md) seção "Stress tests".

**Métricas avançadas (FASE 3E.2):**
- `BacktestReport` ganhou properties: `expectancy_usd`, `payoff_ratio`,
  `net_payoff_ratio`, `gross_payoff_ratio`, `net_profit_factor`,
  `gross_profit_factor`, `max_consecutive_wins`, `max_consecutive_losses`,
  `avg_trade_duration_candles`, `risk_reward_realized_avg`.
- Agregados separados com classificação inequívoca:
  `net_winning_pnl_sum_usd` / `net_losing_pnl_sum_usd` (pelo sinal de `pnl_usd` líquido)
  e `gross_winning_pnl_sum_usd` / `gross_losing_pnl_sum_usd` (pelo sinal de `gross_pnl_usd` bruto).
- Campos legados `gross_profit_usd` / `gross_loss_usd` preservados — apesar do nome,
  somam PnL **líquido** (semântica histórica da FASE 3D). Use os novos nomes para clareza.
- Com custos > 0, `gross_*` e `net_*` podem divergir (trade pode ser bruto vencedor
  e líquido perdedor). Com custo zero, são idênticos.
- Resumo no `summary()` inclui seção "📐 MÉTRICAS AVANÇADAS" (sempre presente,
  exibe "N/A" quando não calculável).

---

## Fluxo do Backtest

```
Dados Históricos (CSV ou memória)
    ↓
BacktestDataLoader.load() → List[Candle]
    ↓
BacktestEngine.run(candles)
    ↓ [loop candle a candle — sem lookahead]
    ├── FeatureEngine.compute(candles[:i+1])   ← apenas passado
    ├── strategy.evaluate(features)            ← sinal da estratégia
    ├── RiskEngine.validate_signal(signal)     ← soberano
    └── BacktestTrade (se aprovado)
    ↓
BacktestReport.from_trades(trades, equity_curve)
    ↓
Métricas + KPIs
```

---

## Garantia Anti-Lookahead Bias

Em cada candle `i`, a estratégia recebe **exatamente** `candles[:i+1]`:

```python
# BacktestEngine._execute_cycle — trecho simplificado
for i in range(n_candles):
    window = candles[:i + 1]   # ← SOMENTE passado + atual
    features = feature_engine.compute(window)
    signal = strategy.evaluate(features)
    ...
```

**Garantias:**
- `candles[i+1:]` nunca é acessado pela estratégia
- Candles futuros são invisíveis
- Entrada ocorre no `close` do candle atual (sem lookahead de preço)
- Stop/TP são verificados **apenas** nos candles posteriores ao de entrada

---

## Regra de Ambiguidade: Stop vs Take Profit

> ⚠️ **Decisão de design documentada aqui.**

**Situação:** Um candle tem simultaneamente:
- `low <= stop_loss_price` (stop atingido)
- `high >= take_profit_price` (take profit atingido)

**Regra adotada:** O **stop loss tem prioridade** (abordagem conservadora).

**Motivo:**
- Evita superestimação de performance
- Em mercados reais, a sequência intracandle é desconhecida
- A abordagem pessimista (stop primeiro) é mais honesta
- Evita overfitting baseado em resultados falsos positivos

**Implementação:**
```python
# BacktestEngine._check_exit_conditions
if stop_hit:
    trade.close(..., CloseReason.STOP_LOSS)   # ← stop tem prioridade
    return trade

if tp_hit:
    trade.close(..., CloseReason.TAKE_PROFIT)
    return trade
```

---

## Meta de Challenge — Apenas KPI Informativo

> ⚠️ **Meta de challenge NUNCA bloqueia trades.**
> ⚠️ **Lucro é métrica de performance, não trava de segurança.**

A meta de challenge (`challenge_profit_target_usd`) é apenas um KPI informativo no relatório final:

```python
# BacktestReport — apenas informativo
@property
def challenge_target_reached(self) -> bool:
    """APENAS INFORMATIVO — não encerra backtest."""
    if self.challenge_profit_target_usd is None:
        return False
    return self.total_pnl_usd >= self.challenge_profit_target_usd
```

**O backtest SEMPRE roda até o último candle**, independente do PnL ou meta atingida.

**Não existe:**
- `max_profit_usd` bloqueante
- Encerramento automático por lucro
- Bloqueio de novos trades por meta atingida

**Como configurar a meta (opcional):**
```python
engine = BacktestEngine(
    ...
    challenge_profit_target_usd=500.0,  # KPI: meta de 10% em conta de 5k
)
# O backtest roda normalmente — meta é apenas exibida no relatório
```

---

## Bot Agnóstico de Provider

> ⚠️ **HyroTrader é apenas um template/exemplo. Não é dependência central.**

O bot funciona com qualquer conta:

| Provider Type | Descrição |
|---------------|-----------|
| `personal` | Conta pessoal/exchange, sem restrições de prop |
| `prop_challenge` | Fase de challenge de qualquer prop firm |
| `prop_funded` | Conta funded após aprovação |
| `exchange` | Conta direta na exchange (Bybit, etc.) |
| `custom` | Perfil totalmente customizável |

**A lógica central nunca verifica `provider_name`** para tomar decisões de risco.

Templates disponíveis em `ACCOUNT_PROFILES` (apenas referência):
- `personal` — conta pessoal genérica
- `prop_challenge_5k` — challenge genérico de $5k
- `prop_challenge_10k` — challenge genérico de $10k
- `hyrotrader_5k` — HyroTrader $5k (apenas template)
- `custom` — perfil personalizado

---

## Métricas do BacktestReport

### Performance

| Métrica | Descrição |
|---------|-----------|
| `total_trades` | Total de trades executados |
| `winning_trades` | Trades com PnL > 0 |
| `losing_trades` | Trades com PnL ≤ 0 |
| `win_rate` | winning / total (%) |
| `total_pnl_usd` | PnL total em USD |
| `return_pct` | Retorno como % do capital inicial |
| `avg_win_usd` | Ganho médio por trade vencedor |
| `avg_loss_usd` | Perda média por trade perdedor (negativo) |
| `profit_factor` | gross_profit / \|gross_loss\| |
| `largest_win_usd` | Maior ganho individual |
| `largest_loss_usd` | Maior perda individual |
| `initial_capital` | Capital inicial |
| `final_capital` | Capital final |
| `peak_capital` | Maior capital atingido |

### Drawdown

| Métrica | Descrição |
|---------|-----------|
| `max_drawdown_usd` | Maior queda do pico ao vale (negativo) |
| `max_drawdown_pct` | Máximo drawdown em % (negativo) |
| `equity_curve` | `List[float]` — evolução do capital |

### KPIs de Challenge (apenas informativos)

| KPI | Descrição |
|-----|-----------|
| `challenge_profit_target_usd` | Meta configurada (None se não configurada) |
| `challenge_target_reached` | True se PnL ≥ meta — **não encerra backtest** |
| `account_goal_progress_pct` | Progresso em % — pode ser > 100% |

---

## Integração com RiskEngine

O mesmo RiskEngine de produção é usado — **sem modificações**:

```python
# BacktestEngine.run — trecho simplificado
risk_result = risk_engine.validate_signal(trading_signal)

if not risk_result.approved:
    risk_blocked_count += 1
    continue   # ← trade não entra no backtest

# Apenas aqui o trade é aberto (após aprovação do RiskEngine)
trade = BacktestTrade(...)
risk_engine.record_trade_opened(trading_signal)
```

**Quando uma posição é fechada:**
```python
risk_engine.record_trade_closed(
    symbol=trade.symbol,
    pnl=trade.pnl_usd,
    size_usd=trade.position_size_usd,
)
```

Isso garante que o capital do RiskEngine é atualizado corretamente.

---

## Como Usar

### Backtest básico (memória, sem CSV)

```python
from crypto_trading_bot.backtesting import (
    BacktestEngine,
    generate_trending_candles,
)
from crypto_trading_bot.strategies.ema_rsi_strategy import EmaRsiStrategy
from crypto_trading_bot.risk.risk_engine import RiskEngine

# Dados sintéticos — sem internet
candles = generate_trending_candles(300, trend_pct_per_candle=0.001)

# Estratégia (placeholder — não validada para trading real)
strategy = EmaRsiStrategy(position_size_usd=200.0)
strategy.set_running()

# Backtest
engine = BacktestEngine(
    strategy=strategy,
    risk_engine=RiskEngine(initial_capital=5000.0),
    initial_capital=5000.0,
)
report = engine.run(candles)
print(report.summary())
```

### Backtest com CSV local

```python
from crypto_trading_bot.backtesting import BacktestEngine, load_candles_from_csv

candles = load_candles_from_csv("data/btcusdt_15m.csv")
# ... mesmo fluxo acima
```

### Formato do CSV

```
timestamp,open,high,low,close,volume
2024-01-01T00:00:00+00:00,65000.0,65500.0,64800.0,65200.0,1000.0
2024-01-01T00:15:00+00:00,65200.0,65700.0,65000.0,65400.0,1200.0
...
```

### Via script

```bash
python scripts/run_backtest.py
python scripts/run_backtest.py --candles 500 --trend 0.001
python scripts/run_backtest.py --csv data/btcusdt_15m.csv
python scripts/run_backtest.py --challenge-target 500  # KPI apenas
```

---

## Limitações Conhecidas

1. **Stop/TP intracandle**: Não é possível saber a ordem real das execuções.
   → Usamos regra conservadora: stop tem prioridade.

2. **Slippage e spread**: Modelados desde a FASE 3E.1 via `ExecutionCostConfig`
   (slippage_pct, slippage_fixed_price_usd, spread_pct, spread_fixed_price_usd).
   Modelagem é APROXIMAÇÃO — não substitui paper/testnet real.

3. **Latência**: Modelada desde a FASE 3E.4B via
   `ExecutionCostConfig.entry_latency_candles`. Default 0 mantém execução
   imediata. Latência > 0 atrasa em N candles e executa no `open`.

4. **Liquidez**: O backtest assume liquidez infinita.
   → Ordens grandes podem ter impacto diferente no mercado real.

5. **Fees por tier de volume**: não modelado (taker/maker fixos).

6. **Funding rate / borrow cost**: fora de escopo (perpetual futures).

7. **EmaRsiStrategy é placeholder**: Não foi validada por backtesting profissional.
   → Não use para trading real sem validação extensiva.

8. **Dados sintéticos**: Candles gerados em memória não representam mercado real.
   → Use dados históricos reais para análise séria.

---

## Glossário

| Termo | Significado |
|-------|-------------|
| Lookahead bias | Usar dados futuros para tomar decisão no passado |
| Drawdown | Queda percentual do pico ao vale do capital |
| Profit Factor | gross_profit / \|gross_loss\| — > 1.0 = lucrativo |
| Win Rate | % de trades vencedores sobre o total |
| equity_curve | Evolução do capital ao longo do tempo |
| out-of-sample | Dados não usados no desenvolvimento da estratégia |
| challenge KPI | Metadado informativo de meta de trading challenge |

---

*Última atualização: **FASE 3E completa** — Backtesting Avançado + Realismo*
*(3E.1 custos · 3E.2 métricas avançadas · 3E.3 stress tests · 3E.4A out-of-sample/walk-forward · 3E.4B latência simulada)*

> ⚠️ **Aviso reforçado:** backtest, por mais avançado que seja, NÃO garante
> performance futura. Sempre valide em ambiente paper/testnet real antes de
> qualquer execução em conta real.
