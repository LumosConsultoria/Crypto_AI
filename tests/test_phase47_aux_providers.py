"""
FASE 47 — providers aux Bybit (funding/OI/instrument). 100% OFFLINE:
transporte SEMPRE fake (zero rede); provider real nunca em teste. Verifica
parsing V5, ordem ascendente, filtro de janela e specs do instrumento.
"""

from __future__ import annotations

from datetime import datetime, timezone

from crypto_trading_bot.historical_data.aux_providers import (
    BybitFundingProvider,
    BybitInstrumentProvider,
    BybitOpenInterestProvider,
    make_fake_transport,
)

_S = datetime(2025, 1, 1, tzinfo=timezone.utc)
_E = datetime(2025, 1, 2, tzinfo=timezone.utc)


def _ms(h):
    return str(int((_S.timestamp() + h * 3600) * 1000))


class TestFunding:

    def test_parses_and_sorts_ascending(self):
        # Bybit retorna DESC; provider deve devolver ASC + filtrar janela
        payload = {"result": {"list": [
            {"fundingRate": "0.0003", "fundingRateTimestamp": _ms(16)},
            {"fundingRate": "0.0001", "fundingRateTimestamp": _ms(8)},
            {"fundingRate": "0.0002", "fundingRateTimestamp": _ms(0)},
        ]}}
        prov = BybitFundingProvider(transport=make_fake_transport(
            {"funding/history": payload}))
        rows = prov.fetch_funding(symbol="BTCUSDT", start=_S, end=_E)
        assert len(rows) == 3
        ts = [r["timestamp"] for r in rows]
        assert ts == sorted(ts)            # ascendente
        assert rows[0]["funding_rate"] == 0.0002


class TestOpenInterest:

    def test_parses_oi(self):
        payload = {"result": {"list": [
            {"openInterest": "1200.5", "timestamp": _ms(2)},
            {"openInterest": "1100.0", "timestamp": _ms(1)},
        ]}}
        prov = BybitOpenInterestProvider(transport=make_fake_transport(
            {"open-interest": payload}))
        rows = prov.fetch_open_interest(symbol="BTCUSDT", tf_minutes=60,
                                        start=_S, end=_E)
        assert len(rows) == 2
        assert rows[0]["open_interest"] == 1100.0   # ascendente

    def test_unsupported_interval_raises(self):
        prov = BybitOpenInterestProvider(transport=make_fake_transport({}))
        import pytest
        from crypto_trading_bot.historical_data.providers import (
            HistoricalDataError)
        with pytest.raises(HistoricalDataError):
            prov.fetch_open_interest(symbol="BTCUSDT", tf_minutes=3,
                                     start=_S, end=_E)


class TestInstrument:

    def test_parses_specs_camelcase(self):
        payload = {"result": {"list": [{
            "symbol": "BTCUSDT", "priceScale": "2",
            "lotSizeFilter": {"minOrderQty": "0.001", "qtyStep": "0.001",
                              "minNotionalValue": "5"},
            "priceFilter": {"tickSize": "0.1"}}]}}
        prov = BybitInstrumentProvider(transport=make_fake_transport(
            {"instruments-info": payload}))
        info = prov.fetch_instrument(symbol="BTCUSDT")
        assert info["available"] is True
        assert info["min_order_qty"] == 0.001
        assert info["tick_size"] == 0.1
        assert info["min_notional"] == 5.0

    def test_empty_is_unavailable(self):
        prov = BybitInstrumentProvider(transport=make_fake_transport(
            {"instruments-info": {"result": {"list": []}}}))
        info = prov.fetch_instrument(symbol="BTCUSDT")
        assert info["available"] is False
