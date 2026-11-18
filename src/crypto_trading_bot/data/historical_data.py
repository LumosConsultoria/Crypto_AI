"""
HistoricalDataService — FASE 3G
=================================
Orquestrador read-only para candles históricos:
    cache local → download paginado (Bybit público) → validação de qualidade.

⚠️  Sem API key. Sem endpoint privado. Sem ordens.
⚠️  Apenas endpoint público /v5/market/kline (já implementado em BybitClient).
⚠️  Dados reais NÃO garantem performance futura.

DESIGN:
    - BybitClient é INJETADO no construtor (testes substituem por mock).
    - DataCache é INJETADO (default: DataCache() em data/historical/).
    - Paginação por timestamp em ms, avançando no tempo (Bybit retorna até
      1000 candles por chamada e ordena da mais recente → mais antiga;
      BybitClient.get_candles já inverte para cronológica).
    - Dedup por timestamp entre páginas.
    - Rate limit por sleep simples entre páginas (default 0.1s).
    - Validação de qualidade via validate_candles().

Uso típico:
    from crypto_trading_bot.exchange.bybit_client import BybitClient
    from crypto_trading_bot.data import HistoricalDataService
    from datetime import datetime, timezone

    client = BybitClient()       # ⚠️ FORA DOS TESTES — conecta à internet
    svc = HistoricalDataService(client=client)

    candles, report = svc.get(
        symbol="BTCUSDT",
        timeframe="15",
        start=datetime(2024, 1, 1, tzinfo=timezone.utc),
        end=datetime(2024, 1, 7, tzinfo=timezone.utc),
        use_cache=True,
        refresh=False,
    )
    print(report.summary())
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from crypto_trading_bot.data.data_cache import DataCache
from crypto_trading_bot.data.data_quality import (
    DataQualityReport,
    timeframe_to_minutes,
    validate_candles,
    validate_candles_strict,
)
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.logging_system.logger import get_logger

_logger = get_logger(__name__)

# Limite máximo por chamada à Bybit V5 kline (documentado).
_BYBIT_KLINE_MAX_LIMIT = 1000

# Sleep default entre páginas (rate limit conservador).
_DEFAULT_RATE_LIMIT_SLEEP = 0.1


def _dt_to_ms(dt: datetime) -> int:
    """Converte datetime para milissegundos UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


class HistoricalDataService:
    """
    Serviço orquestrador de dados históricos (read-only, público).

    Atributos:
        client:                  Cliente HTTP (BybitClient ou compatível) — injetado.
        cache:                   DataCache instância — injetado (default novo DataCache).
        rate_limit_sleep_seconds: Sleep entre chamadas paginadas.
        page_limit:              Candles por chamada (Bybit V5: máx 1000).
    """

    def __init__(
        self,
        client,
        cache: Optional[DataCache] = None,
        rate_limit_sleep_seconds: float = _DEFAULT_RATE_LIMIT_SLEEP,
        page_limit: int = _BYBIT_KLINE_MAX_LIMIT,
    ) -> None:
        if rate_limit_sleep_seconds < 0:
            raise ValueError(
                f"rate_limit_sleep_seconds deve ser >= 0: {rate_limit_sleep_seconds}"
            )
        if page_limit <= 0 or page_limit > _BYBIT_KLINE_MAX_LIMIT:
            raise ValueError(
                f"page_limit deve estar em (0, {_BYBIT_KLINE_MAX_LIMIT}]: {page_limit}"
            )
        self._client = client
        self._cache = cache if cache is not None else DataCache()
        self._rate_limit_sleep = float(rate_limit_sleep_seconds)
        self._page_limit = int(page_limit)

    # -----------------------------------------------------------------------
    # download: paginação histórica explícita (sem cache)
    # -----------------------------------------------------------------------

    def download(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        *,
        category: str = "linear",
    ) -> List[Candle]:
        """
        Baixa candles paginando via client.get_candles().

        Cada chamada retorna até page_limit candles (Bybit max 1000).
        Avança no tempo: cada chamada usa start_ms = max(previous_last_ts + 1, start_ms_atual).
        Para quando: (a) range coberto ou (b) chamada retorna 0 candles.

        Args:
            symbol:    Símbolo (ex: "BTCUSDT").
            timeframe: Timeframe (ex: "15").
            start:     Datetime inicial (inclusive). Convertido para UTC se naive.
            end:       Datetime final (inclusive). Convertido para UTC se naive.
            category:  Categoria Bybit (default "linear").

        Returns:
            Lista de Candle em ordem cronológica, sem duplicatas, dentro de [start, end].

        Raises:
            ValueError: se start >= end.

        ⚠️  Esta função CHAMA o cliente injetado (que pode bater na internet).
            Use mock em testes.
        """
        # Normaliza para UTC
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        if start >= end:
            raise ValueError(
                f"start ({start.isoformat()}) deve ser < end ({end.isoformat()})"
            )

        start_ms = _dt_to_ms(start)
        end_ms = _dt_to_ms(end)
        tf_minutes = timeframe_to_minutes(timeframe)
        tf_ms = tf_minutes * 60 * 1000

        _logger.info(
            f"HistoricalDataService.download | {symbol}/{timeframe} | "
            f"{start.isoformat()} → {end.isoformat()} | "
            f"page_limit={self._page_limit} | sleep={self._rate_limit_sleep}s"
        )

        seen_timestamps: set = set()
        all_candles: List[Candle] = []
        cursor_ms = start_ms
        page = 0

        while cursor_ms <= end_ms:
            page += 1
            page_candles: List[Candle] = self._client.get_candles(
                symbol=symbol,
                timeframe=timeframe,
                limit=self._page_limit,
                category=category,
                start_ms=cursor_ms,
                end_ms=end_ms,
            )

            if not page_candles:
                _logger.debug(
                    f"  [page {page}] retornou 0 candles a partir de {cursor_ms} — fim."
                )
                break

            added_this_page = 0
            last_ts_ms: Optional[int] = None
            for c in page_candles:
                ts_ms = _dt_to_ms(c.timestamp)
                # Filtro defensivo: ignora candles fora do range solicitado
                if ts_ms < start_ms or ts_ms > end_ms:
                    continue
                # Dedup por timestamp
                if ts_ms in seen_timestamps:
                    continue
                seen_timestamps.add(ts_ms)
                all_candles.append(c)
                added_this_page += 1
                if last_ts_ms is None or ts_ms > last_ts_ms:
                    last_ts_ms = ts_ms

            _logger.debug(
                f"  [page {page}] +{added_this_page} candles (último ts_ms={last_ts_ms})"
            )

            if added_this_page == 0:
                # Página retornou só duplicatas ou fora do range — fim.
                break

            # Avança cursor para 1 timeframe após o último timestamp visto
            if last_ts_ms is None:
                break
            new_cursor = last_ts_ms + tf_ms
            if new_cursor <= cursor_ms:
                # Proteção contra loop infinito (timestamp não avançou)
                break
            cursor_ms = new_cursor

            # Rate limit conservador entre páginas
            if self._rate_limit_sleep > 0:
                time.sleep(self._rate_limit_sleep)

        # Ordena cronologicamente (defensivo — cliente já retorna ordenado, mas
        # entre páginas podem haver pequenas sobreposições)
        all_candles.sort(key=lambda c: c.timestamp)

        _logger.info(
            f"HistoricalDataService.download concluído | "
            f"{symbol}/{timeframe} | {len(all_candles)} candles | {page} página(s)"
        )
        return all_candles

    # -----------------------------------------------------------------------
    # get: orquestra cache + download + validação
    # -----------------------------------------------------------------------

    def get(
        self,
        symbol: str,
        timeframe: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        *,
        use_cache: bool = True,
        refresh: bool = False,
        strict_quality: bool = False,
        category: str = "linear",
    ) -> Tuple[List[Candle], DataQualityReport]:
        """
        Orquestra: cache → download → validação de qualidade.

        Política:
            - use_cache=True + cache exists + refresh=False → carrega do cache.
            - refresh=True → baixa e SOBRESCREVE cache (requer start E end).
            - cache miss + start/end fornecidos → baixa, salva e retorna.
            - cache miss + start/end ausentes → DataCacheError (não tem como baixar).
            - strict_quality=True → lança DataQualityError em issues.

        Args:
            symbol:         Símbolo.
            timeframe:      Timeframe.
            start:          Datetime inicial (necessário para download).
            end:            Datetime final (necessário para download).
            use_cache:      Se True e cache existir, carrega do cache.
            refresh:        Se True, força download (sobrescreve cache).
            strict_quality: Se True, lança DataQualityError em issues.
            category:       Categoria Bybit (default "linear").

        Returns:
            Tuple (candles, DataQualityReport).
        """
        cache_hit = use_cache and not refresh and self._cache.exists(symbol, timeframe)

        if cache_hit:
            candles = self._cache.load(symbol, timeframe)
            _logger.info(
                f"HistoricalDataService.get | CACHE HIT | "
                f"{symbol}/{timeframe} | {len(candles)} candles"
            )
        else:
            if start is None or end is None:
                from crypto_trading_bot.data.data_cache import DataCacheError
                raise DataCacheError(
                    f"HistoricalDataService.get: cache miss para {symbol}/{timeframe} "
                    f"e start/end não fornecidos para download."
                )
            candles = self.download(
                symbol=symbol,
                timeframe=timeframe,
                start=start,
                end=end,
                category=category,
            )
            if candles:
                self._cache.save(candles)
                _logger.info(
                    f"HistoricalDataService.get | DOWNLOAD+SAVE | "
                    f"{symbol}/{timeframe} | {len(candles)} candles"
                )

        # Validação de qualidade (sempre executada)
        if strict_quality:
            validate_candles_strict(candles)
            report = validate_candles(candles)  # se strict passou, report.ok=True
        else:
            report = validate_candles(candles)

        return candles, report
