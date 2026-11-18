"""
FASE 43 — cobertura da infraestrutura NetComms PRESERVADA (realocada de
operational_ui para crypto_trading_bot.netcomms). 100% OFFLINE; sem rede
real / ordem / secret. Extraido dos testes da UI removida. FastAPI-free.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.netcomms import (
    KNOWN_OPERATIONS,
    ConnectionStatus,
    NetCommsRegistry,
    run_network_op,
)
from crypto_trading_bot.netcomms.adapters import (
    BybitReadOnlyAdapter,
    PublicMarketDataAdapter,
)
from crypto_trading_bot.netcomms.adapters import bybit_readonly
from crypto_trading_bot.netcomms.redaction import (
    SecretLeakError,
    assert_no_secret,
    contains_secret_token,
    contains_secret_value,
    safe_error_message,
)


# --------------------------- run_network_op -------------------------------

class TestRunNetworkOp:

    def test_gated_blocks_without_approval(self):
        st = run_network_op("op", lambda: {"ok": True}, gated=True,
                            approved=False)
        assert st.state == "blocked"   # nao tocou rede

    def test_not_configured(self):
        st = run_network_op("op", lambda: {"ok": True}, not_configured=True)
        assert st.state == "not_configured"

    def test_connected_with_fake_adapter(self):
        reg = NetCommsRegistry()
        st = run_network_op("op", lambda: {"reachable": True},
                            gated=True, approved=True, registry=reg)
        assert st.state == "connected" and st.last_success
        assert reg.get("op").state == "connected"

    def test_error_is_sanitized(self):
        def _boom():
            raise ValueError("api_secret=SHOULD_NOT_LEAK")
        st = run_network_op("op", _boom, gated=True, approved=True)
        assert st.state == "failed"
        assert "SHOULD_NOT_LEAK" not in (st.last_error_sanitized or "")

    def test_timeout(self):
        import time

        def _slow():
            time.sleep(2.0)
            return {"ok": True}
        st = run_network_op("op", _slow, gated=True, approved=True,
                            timeout=0.2)
        assert st.state == "failed" and st.last_error_sanitized == "timeout"


# --------------------------- registry / status ----------------------------

class TestRegistryStatus:

    def test_seed_and_all_no_secret(self):
        reg = NetCommsRegistry()
        reg.seed(list(KNOWN_OPERATIONS))
        ops = reg.all()
        assert len(ops) == len(KNOWN_OPERATIONS)
        assert all(o["state"] == "not_configured" for o in ops)
        import json
        assert "secret" not in json.dumps(ops).lower()

    def test_status_invalid_state_becomes_failed(self):
        st = ConnectionStatus(operation="x", state="weird")
        assert st.state == "failed"


# --------------------------- adapters -------------------------------------

class TestAdapters:

    def test_public_market_data_offline(self, tmp_path):
        from crypto_trading_bot.historical_data import FakeHistoricalProvider
        ad = PublicMarketDataAdapter(provider="fake",
                                     provider_obj=FakeHistoricalProvider())
        res = ad.fetch_to_canonical(
            symbol="BTCUSDT", timeframe="15m", start_date="2026-01-01",
            end_date="2026-01-03", base_dir=str(tmp_path), force=True,
            run_readiness=False)
        assert res["symbol"] == "BTCUSDT" and res["rows_saved"] > 0
        assert (tmp_path / "BTCUSDT" / "15m" / "BTCUSDT_15m.csv").is_file()

    def test_bybit_readonly_via_fake_client(self):
        class _FakeTicker:
            last_price = "65000"; bid_price = "64999"; ask_price = "65001"

        class _FakeClient:
            def get_ticker(self, symbol):
                return _FakeTicker()

            def get_instruments_info(self, symbol):
                return {"symbol": symbol, "priceScale": "2",
                        "lotSizeFilter": {"minOrderQty": "0.001",
                                          "qtyStep": "0.001",
                                          "minNotionalValue": "5"},
                        "priceFilter": {"tickSize": "0.1"}}

            def get_balance(self):
                return {"list": [{"totalEquity": "8000",
                                  "totalAvailableBalance": "8000",
                                  "accountType": "UNIFIED"}]}

            def get_positions(self, symbol=None):
                return []

            def get_open_orders(self, symbol=None):
                return []

        ad = BybitReadOnlyAdapter(
            environment="demo",
            client_factory=lambda environment, private: _FakeClient())
        h = ad.health()
        assert h["reachable"] is True
        ins = ad.instrument_info()
        assert ins["min_order_qty"] == 0.001 and ins["parse_status"] == "ok"
        acct = ad.account_readonly()
        assert acct["flat"] is True
        assert acct["wallet"]["total_equity"] == 8000.0

    def test_mainnet_blocked(self):
        ad = BybitReadOnlyAdapter(environment="mainnet")
        with pytest.raises(PermissionError):
            ad.health()

    def test_instrument_parser_camelcase_and_states(self):
        out = bybit_readonly._instrument_fields(
            {"symbol": "X", "priceScale": "2",
             "lotSizeFilter": {"minOrderQty": "0.001", "qtyStep": "0.01",
                               "minNotionalValue": "5"},
             "priceFilter": {"tickSize": "0.1"}})
        assert out["parse_status"] == "ok" and out["tick_size"] == 0.1
        assert bybit_readonly._instrument_fields({})["parse_status"] == \
            "no_data"
        assert bybit_readonly._instrument_fields(
            {"symbol": "X"})["parse_status"] == "fields_missing"


# --------------------------- redaction ------------------------------------

class TestRedaction:

    def test_value_scanner_allows_presence_fields(self):
        # nome de campo de presenca NAO e secret
        assert contains_secret_value("api_key_configured: true") is False
        # VALOR de secret e flagado
        assert contains_secret_value("Authorization: Bearer abc") is True

    def test_strict_scanner_flags_field_names(self):
        assert contains_secret_token("api_secret") is True

    def test_assert_no_secret_raises_on_value(self):
        with pytest.raises(SecretLeakError):
            assert_no_secret({"h": "authorization: bearer xyz"})
        # presence-only nao levanta
        assert_no_secret({"api_key_configured": True})

    def test_safe_error_message_no_secret(self):
        msg = safe_error_message(ValueError("x-bapi-sign=LEAK"))
        assert "LEAK" not in msg
