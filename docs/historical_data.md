# Dados Históricos Reais + Data Quality — FASE 3G

> ⚠️ **Dados reais NÃO garantem performance futura.**
> ⚠️ Apenas endpoint público da Bybit (`/v5/market/kline`), sem API key, sem ordens.
> ⚠️ Após download, todos os backtests rodam offline com o cache local.

---

## Visão geral

A FASE 3G adiciona uma camada read-only para baixar, cachear e validar candles históricos públicos da Bybit. O objetivo é substituir gradualmente dados sintéticos por dados reais nos backtests, mantendo:

- Zero uso de API key.
- Zero chamadas a endpoints privados.
- Zero ordens reais.
- Testes 100% offline (BybitClient mockado).
- Cache local determinístico e auditável.

---

## Componentes

| Componente | Arquivo | Responsabilidade |
|---|---|---|
| `DataCache` | [data_cache.py](../src/crypto_trading_bot/data/data_cache.py) | Persistência de candles em CSV local (1 arquivo por `symbol_timeframe`). |
| `DataQualityValidator` | [data_quality.py](../src/crypto_trading_bot/data/data_quality.py) | Funções puras de validação de OHLCV/gaps/duplicatas/inconsistências. |
| `HistoricalDataService` | [historical_data.py](../src/crypto_trading_bot/data/historical_data.py) | Orquestrador: cache → download paginado → validação. |
| `BybitClient.get_candles(..., start_ms, end_ms)` | [bybit_client.py](../src/crypto_trading_bot/exchange/bybit_client.py) | Extensão mínima retrocompatível para paginação por timestamp. |
| `scripts/download_historical_data.py` | [download_historical_data.py](../scripts/download_historical_data.py) | CLI manual para popular o cache. **Não usado em testes.** |

---

## Garantias arquiteturais

| Garantia | Como |
|---|---|
| Reaproveita `BybitClient` existente | Apenas estendido com `start_ms`/`end_ms` opcionais (retrocompatível). |
| `BybitClient` injetado por construtor | `HistoricalDataService(client=...)` — testes substituem por `MagicMock`. |
| Testes 100% offline | Toda chamada de rede passa por mock. Verificado por 33 testes em `tests/test_historical_data.py`. |
| Cache em CSV simples | Reutiliza `candles_to_csv_string()` e `load_candles_from_csv()` existentes. |
| Symbol/timeframe auditáveis | Derivados do nome do arquivo + validação em `DataCache.save()`. |
| Paginação determinística | Cursor avança por `last_ts + timeframe`; dedup por timestamp; ordenação cronológica. |
| Rate limit conservador | `time.sleep` simples entre páginas (default 0.1s). |
| Data quality não-fatal | `validate_candles()` retorna report; `validate_candles_strict()` lança erro. |
| Sem dependências novas | Apenas stdlib + `httpx` (já existia). |

---

## DataCache

Convenção de nomenclatura: `{base_dir}/{symbol}_{timeframe}.csv`

Exemplo: `data/historical/BTCUSDT_15.csv`

```python
from pathlib import Path
from crypto_trading_bot.data import DataCache

cache = DataCache(base_dir=Path("data/historical"))

# Save (sobrescreve arquivo existente; valida consistência interna)
cache.save(candles)   # symbol/timeframe derivados de candles[0]

# Load
candles = cache.load("BTCUSDT", "15")   # KeyError-like se não existir

# Verificação
cache.exists("BTCUSDT", "15")           # bool
cache.path_for("BTCUSDT", "15")         # Path
```

**Política nesta fase:**
- `save()` SOBRESCREVE (sem merge incremental).
- Validação obrigatória: todas as candles devem ter o mesmo symbol+timeframe.
- Diretório `data/historical/` é criado automaticamente se não existir.
- Adicionado ao `.gitignore` — cache nunca é commitado.

### Design: por que symbol/timeframe não são colunas do CSV?

Compatibilidade com `load_candles_from_csv()` existente (que aceita symbol/timeframe via parâmetros). Auditabilidade é garantida por:
1. Nome do arquivo encode symbol+timeframe.
2. `DataCache.save()` valida consistência entre todos os candles antes de salvar.

---

## Data Quality Validator

### Validações realizadas

| Issue | Descrição |
|---|---|
| `duplicate_timestamp` | Timestamp idêntico ao candle anterior. |
| `non_monotonic_timestamp` | Timestamp anterior > seguinte. |
| `high_below_max_oc` | `high < max(open, close)`. |
| `low_above_min_oc` | `low > min(open, close)`. |
| `non_positive_low` | `low <= 0`. |
| `negative_volume` | `volume < 0` (zero é aceito). |
| `gap_detected` | Delta entre candles > timeframe esperado. |
| `symbol_inconsistency` | Candle com symbol diferente do primeiro. |
| `timeframe_inconsistency` | Candle com timeframe diferente do primeiro. |

### Uso

```python
from crypto_trading_bot.data import validate_candles, validate_candles_strict

# Não-fatal: retorna report
report = validate_candles(candles)
print(report.summary())
if not report.ok:
    for issue in report.issues:
        print(f"  [{issue.kind}] idx={issue.index}: {issue.description}")

# Estrito: lança DataQualityError se houver issues
try:
    validate_candles_strict(candles)
except DataQualityError as e:
    print(e.report.summary())
```

### Detecção de gaps

Gaps usam `timeframe_to_minutes(timeframe)` para inferir o intervalo esperado. Timeframes suportados:

| String | Minutos |
|---|---|
| `"1"`, `"3"`, `"5"`, `"15"`, `"30"` | minutos diretos |
| `"60"`, `"120"`, `"240"`, `"360"`, `"720"` | minutos diretos |
| `"D"` | 1440 (1 dia) |
| `"W"` | 10080 (1 semana) |
| Qualquer inteiro positivo | minutos diretos |

Timeframes não suportados → `ValueError` claro.

---

## HistoricalDataService

### Construtor

```python
from crypto_trading_bot.data import HistoricalDataService, DataCache
from crypto_trading_bot.exchange.bybit_client import BybitClient

# ⚠️ Em produção (fora de testes), BybitClient conecta à internet pública:
client = BybitClient()

svc = HistoricalDataService(
    client=client,                       # injeção (testes usam MagicMock)
    cache=DataCache(),                   # default: data/historical/
    rate_limit_sleep_seconds=0.1,        # entre páginas
    page_limit=1000,                     # Bybit V5 max
)
```

### `get()` — orquestrador principal

```python
candles, report = svc.get(
    symbol="BTCUSDT",
    timeframe="15",
    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
    end=datetime(2024, 1, 7, tzinfo=timezone.utc),
    use_cache=True,      # carrega do cache se existir
    refresh=False,       # True → força redownload + sobrescreve cache
    strict_quality=False,  # True → lança DataQualityError em issues
    category="linear",
)
```

**Política:**
- `use_cache=True + cache exists + refresh=False` → load do cache; cliente NÃO é chamado.
- `refresh=True` → download + sobrescreve cache (exige `start` e `end`).
- Cache miss + `start`/`end` ausentes → `DataCacheError`.
- Validação de qualidade SEMPRE executada (retornada no `report`).

### `download()` — paginação explícita

```python
candles = svc.download(
    symbol="BTCUSDT",
    timeframe="15",
    start=datetime(2024, 1, 1, tzinfo=timezone.utc),
    end=datetime(2024, 1, 7, tzinfo=timezone.utc),
)
```

**Características:**
- Paginação por timestamp: cada chamada usa `start_ms = last_seen_ts + timeframe`.
- Dedup por timestamp entre páginas.
- Ordenação cronológica defensiva.
- Filtro: candles fora de `[start, end]` são ignorados.
- Parada em página vazia OU timestamp não avança (proteção contra loop infinito).
- Rate limit entre páginas via `time.sleep`.

---

## Script CLI: download manual

```bash
# Dry-run (mostra o que seria baixado, sem chamar API)
python scripts/download_historical_data.py \
    --symbol BTCUSDT --timeframe 15 \
    --start 2024-01-01 --end 2024-01-07 \
    --dry-run

# Download real (conecta à internet pública, read-only)
python scripts/download_historical_data.py \
    --symbol BTCUSDT --timeframe 15 \
    --start 2024-01-01 --end 2024-01-07
```

**Importante:**
- Banner explícito de "sem API key" no output.
- `--dry-run` permite revisar antes de chamar a API.
- Salva em `data/historical/{SYMBOL}_{TIMEFRAME}.csv`.
- **Não é executado nos testes** — uso manual exclusivo.

---

## Integração com Backtesting

Após o download, os backtests rodam offline:

```python
from crypto_trading_bot.data import DataCache, HistoricalDataService
from crypto_trading_bot.backtesting import BacktestEngine
from crypto_trading_bot.research import StrategySpec, evaluate_strategy

# Carrega do cache (zero chamadas à internet)
cache = DataCache()
candles = cache.load("BTCUSDT", "15")

# Backtest direto
report_a = backtest_engine.run(candles)

# Ou via Strategy Research Framework
spec = StrategySpec(name="my_strat", factory=my_factory)
result_b = evaluate_strategy(spec, candles, walk_forward_n_folds=5)
```

Os testes [`test_historical_data.py::TestCacheIntegrationWith*`](../tests/test_historical_data.py) provam que:
- `BacktestEngine` aceita candles do `DataCache` sem alteração.
- `Strategy Research Framework` avalia specs usando candles do cache.

---

## Limitações conhecidas

1. **Sem retry exponencial nesta fase.** Em caso de falha de rede, exceção propaga; usuário tenta novamente.
2. **Sem merge incremental de cache.** `save()` sobrescreve. Para append, baixe range completo.
3. **Sem suporte a WebSocket/streaming.** Apenas REST.
4. **Apenas Bybit V5 pública.** Outras exchanges exigem novos clients.
5. **Sem ajuste por funding/borrow rate.** Apenas OHLCV.
6. **Cache em CSV simples.** Sem compressão; pode crescer para centenas de MB com históricos grandes.

---

## Reforço final

> ⚠️ **Backtest com dados reais NÃO garante performance futura.** Slippage, latência, custos e regimes de mercado podem variar drasticamente entre o histórico baixado e o presente/futuro. Use stress tests da FASE 3E.3 + walk-forward da FASE 3E.4A para auditar robustez antes de qualquer execução real.
