"""
Tests - DemoApiBlueprint types (FASE 22)
=============================================
100% offline. ZERO network. ZERO secrets.

Covers:
    - DemoApiBlueprint frozen + post_init.
    - JSON serializable via to_dict.
    - Schema version stable.
    - tz-aware datetime.
    - command_preview rejects suspicious substrings.
    - Required types (MarketInfo, AccountState, OrderProposal).
    - DemoApiBlueprintRejected is RuntimeError.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from crypto_trading_bot.demo_session_execution import (
    DEFAULT_MAX_SPREAD_PCT,
    DEFAULT_TTL_SECONDS,
    DemoApiBlueprint,
    DemoApiBlueprintRejected,
)
from crypto_trading_bot.execution.bybit_demo_preflight import (
    AccountState,
    MarketInfo,
    OrderProposal,
)


def _make_market_info() -> MarketInfo:
    return MarketInfo(
        symbol="BTCUSDT",
        category="linear",
        best_bid=65000.0,
        best_ask=65020.0,
        mid_price=65010.0,
        last_price=65015.0,
        reference_price=65010.0,
        min_order_qty=0.001,
        max_order_qty=100.0,
        qty_step=0.001,
        min_notional_value=5.0,
        tick_size=0.5,
    )


def _make_account_state() -> AccountState:
    return AccountState(
        wallet_balance_usdt=5000.0,
        available_balance_usdt=4900.0,
        open_positions_count=0,
        open_orders_count=0,
        leverage_confirmable=True,
        leverage_value=1.0,
    )


def _make_proposal() -> OrderProposal:
    return OrderProposal(
        symbol="BTCUSDT",
        side="buy",
        reference_price=65010.0,
        qty=0.001,
        position_size_usd=65.01,
        stop_loss=64034.85,
        take_profit=66950.30,
        leverage=1.0,
        risk_usd=0.98,
        capital=5000.0,
    )


def _make_blueprint(**overrides) -> DemoApiBlueprint:
    defaults = dict(
        blueprint_id="bp-001",
        generated_at=datetime.now(timezone.utc),
        schema_version=2,
        market_info=_make_market_info(),
        account_state=_make_account_state(),
        proposal=_make_proposal(),
        spread_pct=0.031,
        notional_usd=65.01,
        risk_pct=0.0196,
        readiness_summary={"open_positions_count": 0, "open_orders_count": 0},
        manual_confirmations_needed=(),
        command_preview="python scripts/run_bybit_demo_session_gated.py "
                        "--profile personal",
    )
    defaults.update(overrides)
    return DemoApiBlueprint(**defaults)


# ===========================================================================
# Frozen / post_init
# ===========================================================================

class TestDemoApiBlueprintFrozen:

    def test_is_frozen(self):
        bp = _make_blueprint()
        with pytest.raises(dataclasses.FrozenInstanceError):
            bp.blueprint_id = "other"  # type: ignore[misc]

    def test_empty_blueprint_id_rejected(self):
        with pytest.raises(ValueError):
            _make_blueprint(blueprint_id="")

    def test_invalid_schema_version_rejected(self):
        with pytest.raises(ValueError):
            _make_blueprint(schema_version=99)

    def test_naive_datetime_promoted_utc(self):
        naive = datetime(2026, 6, 1, 12, 0, 0)
        bp = _make_blueprint(generated_at=naive)
        assert bp.generated_at.tzinfo is timezone.utc

    def test_market_info_must_be_dataclass(self):
        with pytest.raises(TypeError):
            _make_blueprint(market_info={"symbol": "BTCUSDT"})  # type: ignore[arg-type]

    def test_account_state_must_be_dataclass(self):
        with pytest.raises(TypeError):
            _make_blueprint(account_state={})  # type: ignore[arg-type]

    def test_proposal_must_be_dataclass(self):
        with pytest.raises(TypeError):
            _make_blueprint(proposal={})  # type: ignore[arg-type]

    def test_readiness_summary_mapping_proxy(self):
        bp = _make_blueprint()
        assert isinstance(bp.readiness_summary, MappingProxyType)

    def test_manual_confirmations_is_tuple(self):
        bp = _make_blueprint(manual_confirmations_needed=["a", "b"])
        assert isinstance(bp.manual_confirmations_needed, tuple)


# ===========================================================================
# Command preview sanitization
# ===========================================================================

class TestCommandPreviewSanitization:

    @pytest.mark.parametrize("suspect", [
        "api_key=sk-fake",
        "API_SECRET something",
        "Bearer abcdef",
        "X-BAPI-SIGN sig",
        "sign=value",
        "authorization: token",
    ])
    def test_suspect_text_rejected(self, suspect):
        with pytest.raises(ValueError):
            _make_blueprint(command_preview=suspect)

    def test_clean_text_accepted(self):
        bp = _make_blueprint(
            command_preview="python scripts/run_bybit_demo_session_gated.py",
        )
        assert "python" in bp.command_preview


# ===========================================================================
# Serialization
# ===========================================================================

class TestSerialization:

    def test_to_dict_json_serializable(self):
        bp = _make_blueprint()
        encoded = json.dumps(bp.to_dict())
        decoded = json.loads(encoded)
        assert decoded["blueprint_id"] == "bp-001"
        assert decoded["schema_version"] == 2
        assert decoded["market_info"]["symbol"] == "BTCUSDT"
        assert decoded["proposal"]["side"] == "buy"
        assert decoded["account_state"]["open_positions_count"] == 0

    def test_to_dict_no_secrets(self):
        bp = _make_blueprint()
        encoded = json.dumps(bp.to_dict()).lower()
        for tok in ("api_key", "api_secret", "bearer ", "x-bapi", "sign="):
            assert tok not in encoded


# ===========================================================================
# Constants exported
# ===========================================================================

class TestConstants:

    def test_default_ttl_value(self):
        assert DEFAULT_TTL_SECONDS == 60

    def test_default_max_spread_pct_value(self):
        assert DEFAULT_MAX_SPREAD_PCT == 0.10


# ===========================================================================
# Exception type
# ===========================================================================

class TestExceptionType:

    def test_rejected_is_runtime_error(self):
        assert issubclass(DemoApiBlueprintRejected, RuntimeError)
