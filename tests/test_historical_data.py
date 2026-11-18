"""
Testes do HistoricalDataService — FASE 3G
============================================
⚠️  ZERO chamadas à internet.
⚠️  ZERO API keys.
⚠️  ZERO ordens reais.
⚠️  BybitClient é SEMPRE MOCKADO (MagicMock) — nenhum teste instancia o real.

Cobertura:
    - Paginação por timestamp com cliente mockado.
    - Dedup entre páginas.
    - Ordenação cronológica defensiva.
    - Filtro por [start, end].
    - Parada em página vazia.
    - Rate limit (time.sleep chamado).
    - get() com cache hit → cliente NÃO é chamado.
    - get() com cache miss → cliente chamado + save no cache.
    - refresh=True força redownload.
    - strict_quality=True lança DataQualityError em dados ruins.
    - Validações: start >= end raises, rate_limit < 0 raises, etc.
    - Integração: candles do cache alimentam BacktestEngine e Strategy Research.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from crypto_trading_bot.backtesting.backtest_engine import BacktestEngine
from crypto_trading_bot.data.data_cache import DataCache, DataCacheError
from crypto_trading_bot.data.data_quality import DataQualityError, DataQualityReport
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.data.historical_data import HistoricalDataService
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.research import StrategySpec, evaluate_strategy
from crypto_trading_bot.risk.risk_engine import RiskEngine
from crypto_trading_bot.strategies.signal_model import StrategySignal

from tests.helpers import StubStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
_15MIN = timedelta(minutes=15)


def _candle(
    i: int,
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "15",
    base_ts: datetime = _TS0,
) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe=timeframe,
        timestamp=base_ts + _15MIN * i,
        open=65000.0 + i,
        high=65100.0 + i,
        low=64900.0 + i,
        close=65050.0 + i,
        volume=1000.0,
    )


def _candles(n: int, **kw) -> List[Candle]:
    return [_candle(i, **kw) for i in range(n)]


def _make_paginated_mock_client(pages: List[List[Candle]]) -> MagicMock:
    """
    Cria mock que retorna `pages[i]` na i-ésima chamada a get_candles().
    Após esgotar pages, retorna [] (sinaliza fim).
    """
    client = MagicMock()
    iterator = iter(pages)

    def _side_effect(**kwargs):
        return next(iterator, [])

    client.get_candles.side_effect = _side_effect
    return client


# ---------------------------------------------------------------------------
# Construtor: validações
# ---------------------------------------------------------------------------

class TestHistoricalDataServiceConstructor:

    def test_negative_rate_limit_raises(self, tmp_path: Path):
        client = MagicMock()
        with pytest.raises(ValueError, match="rate_limit"):
            HistoricalDataService(
                client=client,
                cache=DataCache(base_dir=tmp_path),
                rate_limit_sleep_seconds=-1.0,
            )

    def test_invalid_page_limit_raises(self, tmp_path: Path):
        client = MagicMock()
        with pytest.raises(ValueError, match="page_limit"):
            HistoricalDataService(
                client=client,
                cache=DataCache(base_dir=tmp_path),
                page_limit=0,
            )
        with pytest.raises(ValueError, match="page_limit"):
            HistoricalDataService(
                client=client,
                cache=DataCache(base_dir=tmp_path),
                page_limit=99999,
            )

    def test_default_cache_is_created_if_none(self):
        client = MagicMock()
        svc = HistoricalDataService(client=client, cache=None)
        assert svc._cache is not None


# ---------------------------------------------------------------------------
# download: paginação, dedup, ordenação
# ---------------------------------------------------------------------------

class TestDownloadPagination:

    def test_download_uses_injected_client(self, tmp_path: Path):
        page1 = _candles(3)
        client = _make_paginated_mock_client([page1, []])
        svc = HistoricalDataService(
            client=client,
            cache=DataCache(base_dir=tmp_path),
            rate_limit_sleep_seconds=0.0,
        )
        result = svc.download(
            symbol="BTCUSDT",
            timeframe="15",
            start=_TS0,
            end=_TS0 + _15MIN * 10,
        )
        assert client.get_candles.called
        assert len(result) == 3

    def test_download_handles_multiple_pages(self, tmp_path: Path):
        # Página 1: candles 0..2; Página 2: candles 3..5; Página 3: []
        page1 = _candles(3)
        page2 = [_candle(i) for i in range(3, 6)]
        client = _make_paginated_mock_client([page1, page2, []])
        svc = HistoricalDataService(
            client=client,
            cache=DataCache(base_dir=tmp_path),
            rate_limit_sleep_seconds=0.0,
        )
        result = svc.download(
            symbol="BTCUSDT",
            timeframe="15",
            start=_TS0,
            end=_TS0 + _15MIN * 10,
        )
        # 6 candles únicos, ordenados cronologicamente
        assert len(result) == 6
        for i in range(1, len(result)):
            assert result[i].timestamp > result[i - 1].timestamp

    def test_download_deduplicates_overlapping_pages(self, tmp_path: Path):
        # Página 1: candles 0..3; Página 2: candles 2..5 (sobreposição em 2,3)
        page1 = _candles(4)
        page2 = [_candle(i) for i in range(2, 6)]
        client = _make_paginated_mock_client([page1, page2, []])
        svc = HistoricalDataService(
            client=client,
            cache=DataCache(base_dir=tmp_path),
            rate_limit_sleep_seconds=0.0,
        )
        result = svc.download(
            symbol="BTCUSDT",
            timeframe="15",
            start=_TS0,
            end=_TS0 + _15MIN * 10,
        )
        # 6 candles únicos (sem duplicatas)
        assert len(result) == 6
        timestamps = [c.timestamp for c in result]
        assert len(set(timestamps)) == 6

    def test_download_returns_chronological_order(self, tmp_path: Path):
        # Cliente retorna candles fora de ordem dentro da página
        unordered = [_candle(2), _candle(0), _candle(1)]
        client = _make_paginated_mock_client([unordered, []])
        svc = HistoricalDataService(
            client=client,
            cache=DataCache(base_dir=tmp_path),
            rate_limit_sleep_seconds=0.0,
        )
        result = svc.download(
            symbol="BTCUSDT",
            timeframe="15",
            start=_TS0,
            end=_TS0 + _15MIN * 10,
        )
        for i in range(1, len(result)):
            assert result[i].timestamp > result[i - 1].timestamp

    def test_download_filters_candles_outside_range(self, tmp_path: Path):
        # Página tem candles dentro e fora do range solicitado
        page = [_candle(i) for i in range(10)]  # candles em [_TS0, _TS0 + 9*15min]
        client = _make_paginated_mock_client([page, []])
        svc = HistoricalDataService(
            client=client,
            cache=DataCache(base_dir=tmp_path),
            rate_limit_sleep_seconds=0.0,
        )
        # Range solicitado: somente candles 2..5
        result = svc.download(
            symbol="BTCUSDT",
            timeframe="15",
            start=_TS0 + _15MIN * 2,
            end=_TS0 + _15MIN * 5,
        )
        assert len(result) == 4  # candles 2, 3, 4, 5
        for c in result:
            assert _TS0 + _15MIN * 2 <= c.timestamp <= _TS0 + _15MIN * 5

    def test_download_stops_on_empty_page(self, tmp_path: Path):
        # Primeira página vazia → para imediatamente
        client = _make_paginated_mock_client([[]])
        svc = HistoricalDataService(
            client=client,
            cache=DataCache(base_dir=tmp_path),
            rate_limit_sleep_seconds=0.0,
        )
        result = svc.download(
            symbol="BTCUSDT",
            timeframe="15",
            start=_TS0,
            end=_TS0 + _15MIN * 10,
        )
        assert result == []

    def test_download_start_ge_end_raises(self, tmp_path: Path):
        svc = HistoricalDataService(
            client=MagicMock(),
            cache=DataCache(base_dir=tmp_path),
            rate_limit_sleep_seconds=0.0,
        )
        with pytest.raises(ValueError, match="start"):
            svc.download(
                symbol="BTCUSDT",
                timeframe="15",
                start=_TS0 + _15MIN * 10,
                end=_TS0,
            )

    def test_download_respects_rate_limit_sleep(self, tmp_path: Path):
        # 2 páginas com candles → time.sleep chamado entre elas
        page1 = _candles(3)
        page2 = [_candle(i) for i in range(3, 6)]
        client = _make_paginated_mock_client([page1, page2, []])
        with patch(
            "crypto_trading_bot.data.historical_data.time.sleep"
        ) as mock_sleep:
            svc = HistoricalDataService(
                client=client,
                cache=DataCache(base_dir=tmp_path),
                rate_limit_sleep_seconds=0.25,
            )
            svc.download(
                symbol="BTCUSDT",
                timeframe="15",
                start=_TS0,
                end=_TS0 + _15MIN * 10,
            )
            # sleep chamado ao menos uma vez com 0.25
            assert mock_sleep.called
            assert any(call.args == (0.25,) for call in mock_sleep.call_args_list)


# ---------------------------------------------------------------------------
# get: orquestração cache + download
# ---------------------------------------------------------------------------

class TestGetCacheHit:

    def test_get_uses_cache_when_available(self, tmp_path: Path):
        # Pre-popula cache
        cache = DataCache(base_dir=tmp_path)
        cache.save(_candles(5))

        client = MagicMock()
        svc = HistoricalDataService(
            client=client,
            cache=cache,
            rate_limit_sleep_seconds=0.0,
        )
        candles, report = svc.get(
            symbol="BTCUSDT",
            timeframe="15",
            use_cache=True,
        )
        # Cliente NÃO foi chamado — cache hit
        client.get_candles.assert_not_called()
        assert len(candles) == 5
        assert isinstance(report, DataQualityReport)

    def test_get_downloads_when_cache_missing(self, tmp_path: Path):
        page1 = _candles(3)
        client = _make_paginated_mock_client([page1, []])
        svc = HistoricalDataService(
            client=client,
            cache=DataCache(base_dir=tmp_path),
            rate_limit_sleep_seconds=0.0,
        )
        candles, report = svc.get(
            symbol="BTCUSDT",
            timeframe="15",
            start=_TS0,
            end=_TS0 + _15MIN * 10,
            use_cache=True,
        )
        assert client.get_candles.called
        assert len(candles) == 3
        # Salvou no cache automaticamente
        assert svc._cache.exists("BTCUSDT", "15")

    def test_get_refresh_forces_redownload(self, tmp_path: Path):
        # Pre-popula cache
        cache = DataCache(base_dir=tmp_path)
        cache.save(_candles(5))

        page1 = _candles(3, base_ts=_TS0 + _15MIN * 100)  # candles "novos"
        client = _make_paginated_mock_client([page1, []])
        svc = HistoricalDataService(
            client=client,
            cache=cache,
            rate_limit_sleep_seconds=0.0,
        )
        candles, _ = svc.get(
            symbol="BTCUSDT",
            timeframe="15",
            start=_TS0 + _15MIN * 100,
            end=_TS0 + _15MIN * 200,
            use_cache=True,
            refresh=True,
        )
        # Cliente foi chamado mesmo com cache existente
        assert client.get_candles.called
        assert len(candles) == 3

    def test_get_cache_miss_without_start_end_raises(self, tmp_path: Path):
        client = MagicMock()
        svc = HistoricalDataService(
            client=client,
            cache=DataCache(base_dir=tmp_path),
            rate_limit_sleep_seconds=0.0,
        )
        # Cache vazio + sem start/end → erro
        with pytest.raises(DataCacheError):
            svc.get(symbol="BTCUSDT", timeframe="15", use_cache=True)


# ---------------------------------------------------------------------------
# Validação de qualidade no get
# ---------------------------------------------------------------------------

class TestGetQualityValidation:

    def test_get_returns_quality_report(self, tmp_path: Path):
        cache = DataCache(base_dir=tmp_path)
        cache.save(_candles(5))
        svc = HistoricalDataService(
            client=MagicMock(),
            cache=cache,
            rate_limit_sleep_seconds=0.0,
        )
        candles, report = svc.get(symbol="BTCUSDT", timeframe="15")
        assert isinstance(report, DataQualityReport)
        assert report.ok is True
        assert report.n_candles == 5

    def test_get_strict_mode_raises_on_invalid_data(self, tmp_path: Path):
        """
        Constrói um cenário com gap deliberado e pede strict_quality=True.
        DataQualityError deve ser levantada.
        """
        cache = DataCache(base_dir=tmp_path)
        # Candles com gap (pula 2 índices)
        with_gap = [_candle(0), _candle(1), _candle(5)]
        cache.save(with_gap)

        svc = HistoricalDataService(
            client=MagicMock(),
            cache=cache,
            rate_limit_sleep_seconds=0.0,
        )
        with pytest.raises(DataQualityError):
            svc.get(
                symbol="BTCUSDT",
                timeframe="15",
                strict_quality=True,
            )


# ---------------------------------------------------------------------------
# Integração: cache → BacktestEngine
# ---------------------------------------------------------------------------

class TestCacheIntegrationWithBacktestEngine:

    def test_backtest_engine_runs_with_cached_candles(self, tmp_path: Path):
        # Pre-popula cache com 100 candles válidos
        cache = DataCache(base_dir=tmp_path)
        cache.save(_candles(100))

        svc = HistoricalDataService(
            client=MagicMock(),
            cache=cache,
            rate_limit_sleep_seconds=0.0,
        )
        candles, _ = svc.get(symbol="BTCUSDT", timeframe="15")

        # Alimenta BacktestEngine
        signal = StrategySignal.hold("BTCUSDT", "stub")
        strategy = StubStrategy(signal=signal, block_after_trade=True)
        strategy.set_running()
        engine = BacktestEngine(
            strategy=strategy,
            risk_engine=RiskEngine(initial_capital=5000.0),
            feature_engine=FeatureEngine(),
            initial_capital=5000.0,
            min_candles=5,
            symbol="BTCUSDT",
        )
        report = engine.run(candles)
        # Sem trades (HOLD), mas backtest rodou
        assert report.n_candles_total == 100


# ---------------------------------------------------------------------------
# Integração: cache → Strategy Research
# ---------------------------------------------------------------------------

class TestCacheIntegrationWithStrategyResearch:

    def test_evaluate_strategy_with_cached_candles(self, tmp_path: Path):
        cache = DataCache(base_dir=tmp_path)
        cache.save(_candles(100))
        svc = HistoricalDataService(
            client=MagicMock(),
            cache=cache,
            rate_limit_sleep_seconds=0.0,
        )
        candles, _ = svc.get(symbol="BTCUSDT", timeframe="15")

        # Strategy spec via factory
        def factory(config):
            s = StubStrategy(
                signal=StrategySignal.hold("BTCUSDT", "stub"),
                block_after_trade=True,
            )
            s.set_running()
            return s

        spec = StrategySpec(name="cached_demo", factory=factory)
        result = evaluate_strategy(spec, candles, min_candles=5)
        assert result.single_report.n_candles_total == 100


# ---------------------------------------------------------------------------
# Garantia explícita: testes não chamam internet (todos os testes acima usam
# MagicMock para o cliente; nenhuma instância de BybitClient real é criada).
# ---------------------------------------------------------------------------
