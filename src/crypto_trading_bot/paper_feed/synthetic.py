"""
Synthetic and cache feed builders (FASE 25 Bloco 3)
====================================================
Reaproveita generators de backtesting/backtest_data.py para construir
feeds sinteticos determinISTIcos. Inclui carregamento de cache local
(DataCache existente) sem qualquer download.

Templates documentados como FIXTURE/CONTROL SCENARIO. NAO sao tuning
operacional. Mudar parametros eh decisao consciente do operador.

SEGURANCA:
    - NAO importa BybitClient.
    - NAO importa HistoricalDataService (que poderia baixar).
    - NAO chama rede.
    - cache: APENAS leitura local, falha em cache miss.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from crypto_trading_bot.backtesting.backtest_data import (
    generate_ranging_candles,
    generate_trending_candles,
)
from crypto_trading_bot.data.data_cache import DataCache, DataCacheError
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.paper_feed.adapter import PaperFeedAdapter
from crypto_trading_bot.paper_feed.types import PaperFeedType


# ----------------------------------------------------------------------------
# Templates de fixture (control scenarios). NAO sao tuning operacional.
# ----------------------------------------------------------------------------

# Para signal exercise de trend_pullback: tendencia clara o suficiente para
# EMA20 > EMA50 com pullbacks intermitentes. trend_pct_per_candle=0.0015 (+0.15%
# por candle) gera ~30% de subida em 200 candles, suficiente para warm-up de
# 50 candles + sinal valido. volatility_pct=0.008 gera pullbacks visiveis.
DEFAULT_TRENDING_TREND_PCT = 0.0015
DEFAULT_TRENDING_VOLATILITY_PCT = 0.008
DEFAULT_TRENDING_BASE_PRICE = 65000.0
DEFAULT_TRENDING_N = 200

# Para signal exercise de volatility_breakout: range com pico de volatilidade
# suficiente para BB bandwidth >= min_bandwidth (0.015 default da strategy).
DEFAULT_RANGING_RANGE_PCT = 0.03
DEFAULT_RANGING_CENTER_PRICE = 65000.0
DEFAULT_RANGING_N = 200


def build_synthetic_trending_feed(
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "15",
    n: int = DEFAULT_TRENDING_N,
    base_price: float = DEFAULT_TRENDING_BASE_PRICE,
    trend_pct_per_candle: float = DEFAULT_TRENDING_TREND_PCT,
    volatility_pct: float = DEFAULT_TRENDING_VOLATILITY_PCT,
) -> PaperFeedAdapter:
    """Constroi PaperFeedAdapter sintetico com tendencia de alta.

    FIXTURE/CONTROL SCENARIO. Parametros sao TEMPLATE EDITAVEL — nao
    sao tuning operacional. Documentados como exemplo de cenario que
    permite exercitar entrada/saida de trade no pipeline paper.

    Args:
        symbol:               Symbol da fixture (default BTCUSDT).
        timeframe:            Timeframe (default 15).
        n:                    Numero de candles (default 200).
        base_price:           Preco inicial (default 65000.0).
        trend_pct_per_candle: Tendencia por candle (default +0.15%).
        volatility_pct:       Spread intra-candle (default 0.8%).

    Returns:
        PaperFeedAdapter pronto para injetar no SessionRunner.
    """
    if n <= 0:
        raise ValueError(f"n deve ser positivo: {n}")
    candles = generate_trending_candles(
        n=n,
        base_price=base_price,
        trend_pct_per_candle=trend_pct_per_candle,
        volatility_pct=volatility_pct,
        symbol=symbol,
        timeframe=timeframe,
    )
    return PaperFeedAdapter(
        candles=tuple(candles),
        feed_type=PaperFeedType.SYNTHETIC_TRENDING,
        source_description=(
            f"synthetic trending n={n} trend={trend_pct_per_candle:+.4f}/"
            f"candle base={base_price} vol={volatility_pct:.4f}"
        ),
        symbol=symbol,
        timeframe=timeframe,
    )


def build_synthetic_trend_pullback_feed(
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "15",
    base_price: float = 65000.0,
    n_uptrend_warmup: int = 80,
    n_pullback: int = 8,
    n_continuation: int = 30,
    uptrend_pct_per_candle: float = 0.0020,
    pullback_pct_per_candle: float = -0.0035,
    continuation_pct_per_candle: float = 0.0025,
    volatility_pct: float = 0.005,
) -> PaperFeedAdapter:
    """Constroi fixture com fase de subida + pullback + continuacao.

    FIXTURE/CONTROL SCENARIO especifica para trend_pullback. Estrutura:
        1. n_uptrend_warmup candles subindo (estabelece EMA_fast > EMA_slow).
        2. n_pullback candles caindo (close volta para zona EMA, RSI esfria).
        3. n_continuation candles retomando subida (alcanca TP).

    Parametros sao TEMPLATE EDITAVEL — nao sao tuning operacional.
    Cenario controlado para exercitar entrada paper. NAO eh evidencia
    de performance.
    """
    if n_uptrend_warmup < 50:
        raise ValueError(
            f"n_uptrend_warmup deve ser >= 50 (warm-up de EMA): "
            f"{n_uptrend_warmup}"
        )
    if n_pullback <= 0:
        raise ValueError(f"n_pullback deve ser > 0: {n_pullback}")
    if n_continuation < 0:
        raise ValueError(f"n_continuation deve ser >= 0: {n_continuation}")
    if base_price <= 0:
        raise ValueError(f"base_price deve ser > 0: {base_price}")

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    interval = timedelta(minutes=int(timeframe))

    candles = []
    price = float(base_price)
    idx = 0

    # Fase 1: warmup uptrend
    for _ in range(n_uptrend_warmup):
        open_price = price
        close_price = open_price * (1.0 + uptrend_pct_per_candle)
        spread = price * volatility_pct
        high = max(open_price, close_price) + spread * 0.5
        low = min(open_price, close_price) - spread * 0.5
        low = max(low, 0.01)
        candles.append(Candle(
            symbol=symbol, timeframe=timeframe,
            timestamp=start + interval * idx,
            open=round(open_price, 2), high=round(high, 2),
            low=round(low, 2), close=round(close_price, 2),
            volume=round(1000.0 + idx * 5, 2),
        ))
        price = close_price
        idx += 1

    # Fase 2: pullback
    for _ in range(n_pullback):
        open_price = price
        close_price = open_price * (1.0 + pullback_pct_per_candle)
        spread = price * volatility_pct
        high = max(open_price, close_price) + spread * 0.5
        low = min(open_price, close_price) - spread * 0.5
        low = max(low, 0.01)
        candles.append(Candle(
            symbol=symbol, timeframe=timeframe,
            timestamp=start + interval * idx,
            open=round(open_price, 2), high=round(high, 2),
            low=round(low, 2), close=round(close_price, 2),
            volume=round(1000.0 + idx * 5, 2),
        ))
        price = close_price
        idx += 1

    # Fase 3: continuacao
    for _ in range(n_continuation):
        open_price = price
        close_price = open_price * (1.0 + continuation_pct_per_candle)
        spread = price * volatility_pct
        high = max(open_price, close_price) + spread * 0.5
        low = min(open_price, close_price) - spread * 0.5
        low = max(low, 0.01)
        candles.append(Candle(
            symbol=symbol, timeframe=timeframe,
            timestamp=start + interval * idx,
            open=round(open_price, 2), high=round(high, 2),
            low=round(low, 2), close=round(close_price, 2),
            volume=round(1000.0 + idx * 5, 2),
        ))
        price = close_price
        idx += 1

    return PaperFeedAdapter(
        candles=tuple(candles),
        feed_type=PaperFeedType.SYNTHETIC_TRENDING,
        source_description=(
            f"synthetic trend+pullback warmup={n_uptrend_warmup} "
            f"pullback={n_pullback} cont={n_continuation} "
            f"base={base_price}"
        ),
        symbol=symbol,
        timeframe=timeframe,
    )


def build_synthetic_ranging_feed(
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "15",
    n: int = DEFAULT_RANGING_N,
    center_price: float = DEFAULT_RANGING_CENTER_PRICE,
    range_pct: float = DEFAULT_RANGING_RANGE_PCT,
) -> PaperFeedAdapter:
    """Constroi PaperFeedAdapter sintetico com range/oscilacao.

    FIXTURE/CONTROL SCENARIO. Pensado para volatility_breakout.
    """
    if n <= 0:
        raise ValueError(f"n deve ser positivo: {n}")
    candles = generate_ranging_candles(
        n=n,
        center_price=center_price,
        range_pct=range_pct,
        symbol=symbol,
        timeframe=timeframe,
    )
    return PaperFeedAdapter(
        candles=tuple(candles),
        feed_type=PaperFeedType.SYNTHETIC_RANGING,
        source_description=(
            f"synthetic ranging n={n} center={center_price} "
            f"range={range_pct:.4f}"
        ),
        symbol=symbol,
        timeframe=timeframe,
    )


def build_cache_feed(
    *,
    symbol: str,
    timeframe: str,
    cache: Optional[DataCache] = None,
) -> PaperFeedAdapter:
    """Constroi PaperFeedAdapter a partir de cache local (CSV).

    NAO baixa. Cache miss falha com DataCacheError clara.

    Args:
        symbol:    Symbol do cache (ex: BTCUSDT).
        timeframe: Timeframe do cache (ex: 15).
        cache:     DataCache injetavel; default = DataCache() (data/historical/).

    Returns:
        PaperFeedAdapter com feed_type=CACHE.

    Raises:
        DataCacheError: arquivo nao existe (sem rede, sem download).
    """
    if cache is None:
        cache = DataCache()
    candles = cache.load(symbol, timeframe)  # raises DataCacheError se miss
    if not candles:
        raise DataCacheError(
            f"Cache vazio para {symbol}/{timeframe} em {cache.path_for(symbol, timeframe)}"
        )
    return PaperFeedAdapter(
        candles=tuple(candles),
        feed_type=PaperFeedType.CACHE,
        source_description=(
            f"local cache {cache.path_for(symbol, timeframe)} "
            f"n={len(candles)}"
        ),
        symbol=symbol,
        timeframe=timeframe,
    )
