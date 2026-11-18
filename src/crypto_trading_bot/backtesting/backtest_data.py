"""
BacktestDataLoader — Carregamento de Dados Históricos para Backtesting
=======================================================================
Fornece candles históricos de fontes locais para o BacktestEngine.

⚠️  Este módulo é EXCLUSIVO para backtesting.
    Não baixa dados da internet. Não usa API keys. Não conecta exchanges.

Fontes suportadas:
    - Dados em memória (List[dict] ou List[Candle])
    - CSV local no formato padrão OHLCV
    - Geradores determinísticos para testes (trending, ranging, etc.)

Formato do CSV esperado (separador vírgula, header obrigatório):
    timestamp,open,high,low,close,volume
    2024-01-01T00:00:00+00:00,65000.0,65500.0,64800.0,65200.0,1000.0
    ...

    Campos:
        timestamp : ISO 8601 ou Unix timestamp (ms)
        open      : preço de abertura
        high      : máxima do período
        low       : mínima do período
        close     : preço de fechamento
        volume    : volume negociado

Geradores determinísticos:
    generate_trending_candles() → candles com tendência de alta ou baixa
    generate_ranging_candles()  → candles lateralizados (ranging market)
    generate_volatile_candles() → candles com alta volatilidade
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.logging_system.logger import get_logger

_logger = get_logger(__name__)

# Colunas obrigatórias em um CSV de candles
_REQUIRED_COLUMNS = {"timestamp", "open", "high", "low", "close", "volume"}


class BacktestDataError(Exception):
    """Erro específico de carregamento de dados de backtest."""
    pass


def load_candles_from_list(
    data: List[Dict[str, Any]],
    symbol: str = "BTCUSDT",
    timeframe: str = "15",
) -> List[Candle]:
    """
    Converte uma lista de dicionários OHLCV em List[Candle].

    Args:
        data:      Lista de dicts com chaves: timestamp, open, high, low, close, volume
        symbol:    Símbolo do ativo. Padrão: "BTCUSDT"
        timeframe: Timeframe em minutos. Padrão: "15"

    Returns:
        Lista de Candle em ordem cronológica (mais antigo → mais recente).

    Raises:
        BacktestDataError: Se a lista estiver vazia ou com campos ausentes.

    Exemplo:
        candles = load_candles_from_list([
            {"timestamp": "2024-01-01T00:00:00+00:00",
             "open": 65000.0, "high": 65500.0, "low": 64800.0,
             "close": 65200.0, "volume": 1000.0},
            ...
        ])
    """
    if not data:
        raise BacktestDataError("Lista de dados vazia. Forneça pelo menos 1 candle.")

    candles = []
    for i, row in enumerate(data):
        missing = _REQUIRED_COLUMNS - set(row.keys())
        if missing:
            raise BacktestDataError(
                f"Linha {i}: campos ausentes: {sorted(missing)}. "
                f"Campos obrigatórios: {sorted(_REQUIRED_COLUMNS)}"
            )

        timestamp = _parse_timestamp(row["timestamp"], row_idx=i)

        try:
            candle = Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=timestamp,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
        except (TypeError, ValueError) as e:
            raise BacktestDataError(f"Linha {i}: erro ao converter valores: {e}") from e

        candles.append(candle)

    # Ordena por timestamp (garante ordem cronológica)
    candles.sort(key=lambda c: c.timestamp)

    _logger.info(
        f"BacktestData: {len(candles)} candles carregados de lista | "
        f"symbol={symbol} | "
        f"de={candles[0].timestamp.date()} | "
        f"até={candles[-1].timestamp.date()}"
    )
    return candles


def load_candles_from_csv(
    path: Union[str, Path],
    symbol: str = "BTCUSDT",
    timeframe: str = "15",
    delimiter: str = ",",
) -> List[Candle]:
    """
    Carrega candles de um arquivo CSV local.

    ⚠️  Não baixa dados da internet. Apenas lê arquivo local.

    Args:
        path:      Caminho para o arquivo CSV.
        symbol:    Símbolo do ativo.
        timeframe: Timeframe em minutos.
        delimiter: Separador do CSV. Padrão: vírgula.

    Returns:
        Lista de Candle em ordem cronológica.

    Raises:
        BacktestDataError: Se o arquivo não existir, estiver vazio ou mal formatado.

    Formato esperado:
        timestamp,open,high,low,close,volume
        2024-01-01T00:00:00+00:00,65000.0,65500.0,64800.0,65200.0,1000.0
    """
    path = Path(path)

    if not path.exists():
        raise BacktestDataError(
            f"Arquivo CSV não encontrado: {path}. "
            f"O backtest usa apenas dados locais — não baixa dados da internet."
        )

    if path.stat().st_size == 0:
        raise BacktestDataError(f"Arquivo CSV vazio: {path}")

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=delimiter)

        # Verifica colunas obrigatórias
        if reader.fieldnames is None:
            raise BacktestDataError(f"CSV sem cabeçalho: {path}")

        fieldnames_lower = {col.strip().lower() for col in reader.fieldnames}
        missing = _REQUIRED_COLUMNS - fieldnames_lower
        if missing:
            raise BacktestDataError(
                f"CSV {path}: colunas ausentes: {sorted(missing)}. "
                f"Colunas obrigatórias: {sorted(_REQUIRED_COLUMNS)}"
            )

        rows = list(reader)

    if not rows:
        raise BacktestDataError(f"CSV {path}: nenhum dado além do cabeçalho.")

    # Normaliza nomes de colunas para lowercase
    normalized = [
        {k.strip().lower(): v.strip() for k, v in row.items()}
        for row in rows
    ]

    candles = load_candles_from_list(normalized, symbol=symbol, timeframe=timeframe)

    _logger.info(f"BacktestData: {len(candles)} candles carregados de {path}")
    return candles


def load_candles_from_csv_string(
    csv_content: str,
    symbol: str = "BTCUSDT",
    timeframe: str = "15",
) -> List[Candle]:
    """
    Carrega candles de uma string CSV (útil para testes sem arquivo real).

    Args:
        csv_content: Conteúdo CSV como string.
        symbol:      Símbolo do ativo.
        timeframe:   Timeframe em minutos.

    Returns:
        Lista de Candle em ordem cronológica.
    """
    if not csv_content.strip():
        raise BacktestDataError("CSV string vazio.")

    reader = csv.DictReader(io.StringIO(csv_content))
    rows = list(reader)

    if not rows:
        raise BacktestDataError("CSV string sem dados além do cabeçalho.")

    normalized = [
        {k.strip().lower(): v.strip() for k, v in row.items()}
        for row in rows
    ]

    return load_candles_from_list(normalized, symbol=symbol, timeframe=timeframe)


# ---------------------------------------------------------------------------
# Geradores Determinísticos de Candles (para testes e demonstrações)
# ⚠️  Dados sintéticos — NÃO representam mercado real.
# ⚠️  Resultados de backtest com dados sintéticos NÃO garantem performance futura.
# ---------------------------------------------------------------------------

def generate_trending_candles(
    n: int = 200,
    base_price: float = 65000.0,
    trend_pct_per_candle: float = 0.001,
    volatility_pct: float = 0.005,
    volume_base: float = 1000.0,
    symbol: str = "BTCUSDT",
    timeframe: str = "15",
    start: Optional[datetime] = None,
) -> List[Candle]:
    """
    Gera candles com tendência configurável.

    trend_pct_per_candle > 0 → tendência de alta  (útil para testar BUY)
    trend_pct_per_candle < 0 → tendência de baixa (útil para testar SELL ou HOLD)

    ⚠️  Dados sintéticos — não representam mercado real.

    Args:
        n:                      Número de candles a gerar.
        base_price:             Preço inicial.
        trend_pct_per_candle:   Variação percentual de tendência por candle.
                                Ex: 0.001 = +0.1% por candle (alta); -0.001 = baixa.
        volatility_pct:         Spread intracandle (high-low como % do preço).
                                Ex: 0.005 = 0.5% de spread.
        volume_base:            Volume base por candle.
        symbol:                 Símbolo do ativo.
        timeframe:              Timeframe em minutos.
        start:                  Timestamp inicial. Padrão: 2024-01-01 UTC.

    Returns:
        Lista de candles com tendência determinística.

    Exemplo:
        # 200 candles de alta para testar estratégia BUY
        candles = generate_trending_candles(200, trend_pct_per_candle=0.001)

        # 200 candles de baixa para testar HOLD/SELL
        candles = generate_trending_candles(200, trend_pct_per_candle=-0.001)
    """
    if n <= 0:
        raise BacktestDataError(f"n deve ser positivo: {n}")
    if base_price <= 0:
        raise BacktestDataError(f"base_price deve ser positivo: {base_price}")

    if start is None:
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)

    candles = []
    current_price = base_price
    interval = timedelta(minutes=int(timeframe))

    for i in range(n):
        # Preço de abertura = close anterior (ou base no início)
        open_price = current_price

        # Preço de fechamento com tendência determinística
        close_price = open_price * (1 + trend_pct_per_candle)

        # High e Low baseados em spread determinístico
        # Garantimos que high >= max(open, close) e low <= min(open, close)
        spread = current_price * volatility_pct
        high = max(open_price, close_price) + spread * 0.5
        low = min(open_price, close_price) - spread * 0.5

        # Garante low > 0
        low = max(low, 0.01)

        candles.append(Candle(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=start + interval * i,
            open=round(open_price, 2),
            high=round(high, 2),
            low=round(low, 2),
            close=round(close_price, 2),
            volume=round(volume_base + i * 10, 2),
        ))

        current_price = close_price

    _logger.debug(
        f"BacktestData.generate_trending: {n} candles | "
        f"trend={trend_pct_per_candle:+.3%}/candle | "
        f"start={candles[0].close:.2f} | end={candles[-1].close:.2f}"
    )
    return candles


def generate_ranging_candles(
    n: int = 200,
    center_price: float = 65000.0,
    range_pct: float = 0.02,
    volume_base: float = 1000.0,
    symbol: str = "BTCUSDT",
    timeframe: str = "15",
    start: Optional[datetime] = None,
) -> List[Candle]:
    """
    Gera candles lateralizados (ranging/consolidação) sem tendência definida.

    Útil para testar comportamento de estratégias em mercados sem tendência.

    ⚠️  Dados sintéticos — não representam mercado real.

    Args:
        n:            Número de candles.
        center_price: Preço central do range.
        range_pct:    Amplitude do range como % do center_price.
                      Ex: 0.02 = range de ±2%.
        volume_base:  Volume base.
        symbol:       Símbolo.
        timeframe:    Timeframe em minutos.
        start:        Timestamp inicial.

    Returns:
        Lista de candles com comportamento ranging determinístico (zig-zag).
    """
    if n <= 0:
        raise BacktestDataError(f"n deve ser positivo: {n}")

    if start is None:
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)

    candles = []
    interval = timedelta(minutes=int(timeframe))
    half_range = center_price * range_pct

    for i in range(n):
        # Oscilação senoidal determinística → zig-zag sem tendência
        import math
        phase = (i * 2 * math.pi) / 20  # período de 20 candles
        mid = center_price + half_range * math.sin(phase)

        spread = center_price * 0.003  # spread fixo de 0.3%
        open_price = mid - spread * 0.1 if i % 2 == 0 else mid + spread * 0.1
        close_price = mid + spread * 0.1 if i % 2 == 0 else mid - spread * 0.1
        high = max(open_price, close_price) + spread * 0.5
        low = max(min(open_price, close_price) - spread * 0.5, 0.01)

        candles.append(Candle(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=start + interval * i,
            open=round(open_price, 2),
            high=round(high, 2),
            low=round(low, 2),
            close=round(close_price, 2),
            volume=round(volume_base, 2),
        ))

    _logger.debug(f"BacktestData.generate_ranging: {n} candles | center={center_price}")
    return candles


def generate_volatile_candles(
    n: int = 200,
    base_price: float = 65000.0,
    volatility_pct: float = 0.05,
    trend_pct_per_candle: float = 0.0,
    volume_base: float = 1000.0,
    symbol: str = "BTCUSDT",
    timeframe: str = "15",
    start: Optional[datetime] = None,
) -> List[Candle]:
    """
    Gera candles com ALTA VOLATILIDADE determinística (sem random).

    Cada candle exibe:
        - Movimento close-to-close grande (oscilação senoidal de período curto).
        - Spread intracandle amplo proporcional a volatility_pct.

    ⚠️  Dados sintéticos — não representam mercado real.
    ⚠️  Determinístico: chamadas idênticas produzem candles idênticos.

    Args:
        n:                    Número de candles a gerar (> 0).
        base_price:           Preço inicial (> 0).
        volatility_pct:       Amplitude da volatilidade como fração do preço.
                              Ex: 0.05 = movimento de até ±5% por candle e spread
                              intracandle de ~5% do preço.
        trend_pct_per_candle: Tendência opcional sobreposta à volatilidade
                              (default 0.0 = volatilidade pura sem tendência).
        volume_base:          Volume base por candle.
        symbol:               Símbolo do ativo.
        timeframe:            Timeframe em minutos.
        start:                Timestamp inicial. Padrão: 2024-01-01 UTC.

    Returns:
        Lista de candles com volatilidade alta determinística.

    Raises:
        BacktestDataError: Se n <= 0 ou base_price <= 0.

    Garantias OHLCV:
        - high >= max(open, close)
        - low  <= min(open, close)
        - low  >  0 (clamp em 0.01)
        - volume >= 0
        - timestamps estritamente crescentes
        - symbol e timeframe preservados
    """
    if n <= 0:
        raise BacktestDataError(f"n deve ser positivo: {n}")
    if base_price <= 0:
        raise BacktestDataError(f"base_price deve ser positivo: {base_price}")

    if start is None:
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)

    import math

    candles: List[Candle] = []
    interval = timedelta(minutes=int(timeframe))
    current_price = base_price

    for i in range(n):
        open_price = current_price

        # Oscilação senoidal forte (período curto = 7 candles → alta freq.)
        phase = (i * 2 * math.pi) / 7
        direction = math.sin(phase)
        close_price = open_price * (
            1.0 + trend_pct_per_candle + direction * volatility_pct
        )

        # Spread intracandle = volatility_pct do preço atual (amplo)
        spread = current_price * volatility_pct
        high = max(open_price, close_price) + spread * 0.5
        low = min(open_price, close_price) - spread * 0.5
        low = max(low, 0.01)  # garante low > 0

        candles.append(Candle(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=start + interval * i,
            open=round(open_price, 2),
            high=round(high, 2),
            low=round(low, 2),
            close=round(close_price, 2),
            volume=round(volume_base, 2),
        ))

        current_price = close_price

    _logger.debug(
        f"BacktestData.generate_volatile: {n} candles | "
        f"volatility={volatility_pct:.2%} | "
        f"start={candles[0].close:.2f} | end={candles[-1].close:.2f}"
    )
    return candles


def generate_candles_with_stop_hit(
    entry_price: float = 65000.0,
    stop_price: float = 64000.0,
    take_profit_price: Optional[float] = 67000.0,
    n_before_entry: int = 60,
    n_after_entry: int = 5,
    hit_what: str = "stop",  # "stop", "tp", "both"
    symbol: str = "BTCUSDT",
    timeframe: str = "15",
    start: Optional[datetime] = None,
) -> List[Candle]:
    """
    Gera candles determinísticos para testar fechamento de posição por stop/TP.

    Cria um dataset onde:
    - n_before_entry candles com tendência de alta (para gerar sinal BUY)
    - 1 candle de entrada ao preço de entry_price
    - n_after_entry candles neutros
    - 1 candle final que atinge stop_price e/ou take_profit_price

    Útil para testar:
        - Fechamento por stop loss
        - Fechamento por take profit
        - Ambiguidade (stop e TP no mesmo candle) → stop tem prioridade

    Args:
        hit_what: "stop" → só atinge stop | "tp" → só atinge TP | "both" → ambos no mesmo candle

    Returns:
        Lista de candles determinísticos para testes.
    """
    if start is None:
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)

    # Candles antes da entrada — tendência de alta crescente
    before = generate_trending_candles(
        n=n_before_entry,
        base_price=entry_price * 0.95,
        trend_pct_per_candle=0.001,
        symbol=symbol,
        timeframe=timeframe,
        start=start,
    )

    interval = timedelta(minutes=int(timeframe))
    last_ts = before[-1].timestamp

    # Candle de entrada — fecha exatamente em entry_price
    entry_candle = Candle(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=last_ts + interval,
        open=entry_price * 0.999,
        high=entry_price * 1.002,
        low=entry_price * 0.998,
        close=entry_price,
        volume=1000.0,
    )

    # Candles neutros após entrada (sem atingir stop ou TP)
    neutral = []
    mid_price = entry_price * 1.005  # levemente acima da entrada
    for k in range(n_after_entry):
        neutral.append(Candle(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=entry_candle.timestamp + interval * (k + 1),
            open=mid_price,
            high=mid_price * 1.001,
            low=mid_price * 0.999,
            close=mid_price,
            volume=800.0,
        ))

    last_neutral_ts = neutral[-1].timestamp if neutral else entry_candle.timestamp

    # Candle que atinge stop/TP
    if hit_what == "stop":
        # Low atinge stop_price; High não chega ao TP
        tp_safe = (take_profit_price or (entry_price * 1.10)) * 0.5  # longe do TP
        trigger_candle = Candle(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=last_neutral_ts + interval,
            open=mid_price,
            high=min(tp_safe, mid_price * 1.005),
            low=stop_price * 0.999,  # abaixo do stop → stop atingido
            close=stop_price * 0.99,
            volume=1500.0,
        )
    elif hit_what == "tp" and take_profit_price is not None:
        # High atinge TP; Low não chega ao stop
        stop_safe = stop_price * 1.5  # longe do stop
        trigger_candle = Candle(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=last_neutral_ts + interval,
            open=mid_price,
            high=take_profit_price * 1.001,  # acima do TP → TP atingido
            low=max(stop_safe, mid_price * 0.995),
            close=take_profit_price * 1.001,
            volume=1500.0,
        )
    elif hit_what == "both" and take_profit_price is not None:
        # ⚠️  Ambiguidade: Low <= stop E High >= TP → stop tem prioridade
        trigger_candle = Candle(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=last_neutral_ts + interval,
            open=mid_price,
            high=take_profit_price * 1.001,   # atinge TP
            low=stop_price * 0.999,            # atinge stop também
            close=mid_price,
            volume=2000.0,
        )
    else:
        # Fallback: candle neutro
        trigger_candle = Candle(
            symbol=symbol,
            timeframe=timeframe,
            timestamp=last_neutral_ts + interval,
            open=mid_price,
            high=mid_price * 1.001,
            low=mid_price * 0.999,
            close=mid_price,
            volume=800.0,
        )

    return before + [entry_candle] + neutral + [trigger_candle]


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------

def candles_to_csv_string(
    candles: List[Candle],
    include_header: bool = True,
) -> str:
    """
    Serializa uma lista de candles para formato CSV string.

    Útil para salvar dados gerados ou para testes.

    Args:
        candles:        Lista de candles.
        include_header: Se True, inclui linha de cabeçalho.

    Returns:
        String CSV com cabeçalho e dados.
    """
    output = io.StringIO()
    fieldnames = ["timestamp", "open", "high", "low", "close", "volume"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)

    if include_header:
        writer.writeheader()

    for candle in candles:
        writer.writerow({
            "timestamp": candle.timestamp.isoformat(),
            "open":      candle.open,
            "high":      candle.high,
            "low":       candle.low,
            "close":     candle.close,
            "volume":    candle.volume,
        })

    return output.getvalue()


def _parse_timestamp(value: Any, row_idx: int = 0) -> datetime:
    """
    Converte um valor de timestamp para datetime com timezone UTC.

    Suporta:
        - ISO 8601 string ("2024-01-01T00:00:00+00:00")
        - String sem timezone ("2024-01-01 00:00:00") → assume UTC
        - Unix timestamp em milissegundos (int/float > 1e10)
        - Unix timestamp em segundos (int/float)
        - datetime já com timezone → mantém
        - datetime sem timezone → adiciona UTC

    Raises:
        BacktestDataError: Se não conseguir converter.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e10:
            ts = ts / 1000  # milissegundos → segundos
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    if isinstance(value, str):
        value = value.strip()
        # Tenta ISO 8601
        for fmt in (
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%d %H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                dt = datetime.strptime(value, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue

        # Última tentativa: Unix timestamp como string
        try:
            return _parse_timestamp(float(value), row_idx=row_idx)
        except ValueError:
            pass

    raise BacktestDataError(
        f"Linha {row_idx}: não foi possível converter timestamp: {value!r}. "
        f"Use formato ISO 8601 (ex: '2024-01-01T00:00:00+00:00') ou Unix timestamp."
    )
