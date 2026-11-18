"""
Tests - DemoApiBlueprint persistence (FASE 22)
====================================================
100% offline. ZERO network. ZERO secrets.

Covers serialize/load roundtrip, TTL freshness, sanitization, schema.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType

import pytest

from crypto_trading_bot.demo_session_execution import (
    DemoApiBlueprintRejected,
    build_demo_api_blueprint,
    load_from_json,
    serialize_to_json,
)
from crypto_trading_bot.execution.bybit_demo_preflight import (
    AccountState,
    MarketInfo,
    OrderProposal,
    PreflightReport,
)


def _report() -> PreflightReport:
    return PreflightReport(
        ok=True,
        market_info=MarketInfo(
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
        ),
        account_state=AccountState(
            wallet_balance_usdt=5000.0,
            available_balance_usdt=4900.0,
            open_positions_count=0,
            open_orders_count=0,
            leverage_confirmable=True,
            leverage_value=1.0,
        ),
        proposal=OrderProposal(
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
        ),
        abort_reason=None,
        abort_details="",
    )


# ===========================================================================
# Roundtrip
# ===========================================================================

class TestRoundtrip:

    def test_serialize_then_load_equals(self, tmp_path: Path):
        bp = build_demo_api_blueprint(_report())
        path = tmp_path / "bp.json"
        serialize_to_json(bp, path)
        loaded = load_from_json(path)
        assert loaded.blueprint_id == bp.blueprint_id
        assert loaded.proposal.side == bp.proposal.side
        assert loaded.market_info.symbol == bp.market_info.symbol
        assert loaded.account_state.wallet_balance_usdt == \
            bp.account_state.wallet_balance_usdt
        assert loaded.spread_pct == pytest.approx(bp.spread_pct)
        assert loaded.notional_usd == pytest.approx(bp.notional_usd)
        assert loaded.risk_pct == pytest.approx(bp.risk_pct)

    def test_serialize_creates_parent_dirs(self, tmp_path: Path):
        bp = build_demo_api_blueprint(_report())
        path = tmp_path / "deep" / "nested" / "bp.json"
        serialize_to_json(bp, path)
        assert path.exists()


# ===========================================================================
# Sanitization
# ===========================================================================

class TestSanitization:

    def test_json_payload_no_secrets(self, tmp_path: Path):
        bp = build_demo_api_blueprint(_report())
        path = tmp_path / "bp.json"
        serialize_to_json(bp, path)
        text = path.read_text(encoding="utf-8").lower()
        for tok in ("api_key", "api_secret", "bearer ", "x-bapi",
                    "sign=", "authorization:"):
            assert tok not in text


# ===========================================================================
# Path traversal
# ===========================================================================

class TestPathTraversal:

    def test_dotdot_in_serialize_rejected(self, tmp_path: Path):
        bp = build_demo_api_blueprint(_report())
        bad = tmp_path / ".." / "bp.json"
        # On Windows .. may be resolved before our check; use a path that
        # explicitly contains '..' as a part.
        bad = Path("..") / "bp.json"
        with pytest.raises(DemoApiBlueprintRejected, match="\\.\\."):
            serialize_to_json(bp, bad)

    def test_dotdot_in_load_rejected(self):
        bad = Path("..") / "bp.json"
        with pytest.raises(DemoApiBlueprintRejected, match="\\.\\."):
            load_from_json(bad)


# ===========================================================================
# Freshness / TTL
# ===========================================================================

class TestFreshness:

    def test_fresh_blueprint_accepted(self, tmp_path: Path):
        bp = build_demo_api_blueprint(_report())
        path = tmp_path / "bp.json"
        serialize_to_json(bp, path)
        loaded = load_from_json(path, max_age_seconds=60)
        assert loaded.blueprint_id == bp.blueprint_id

    def test_stale_blueprint_rejected(self, tmp_path: Path):
        past = datetime.now(timezone.utc) - timedelta(seconds=120)
        bp = build_demo_api_blueprint(_report(), now=past)
        path = tmp_path / "bp.json"
        serialize_to_json(bp, path)
        with pytest.raises(DemoApiBlueprintRejected, match="stale"):
            load_from_json(path, max_age_seconds=60)

    def test_future_blueprint_rejected(self, tmp_path: Path):
        future = datetime.now(timezone.utc) + timedelta(seconds=120)
        bp = build_demo_api_blueprint(_report(), now=future)
        path = tmp_path / "bp.json"
        serialize_to_json(bp, path)
        with pytest.raises(DemoApiBlueprintRejected, match="futuro"):
            load_from_json(path)

    def test_custom_ttl(self, tmp_path: Path):
        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        bp = build_demo_api_blueprint(_report(), now=past)
        path = tmp_path / "bp.json"
        serialize_to_json(bp, path)
        # Tight TTL: 5s -> should reject
        with pytest.raises(DemoApiBlueprintRejected, match="stale"):
            load_from_json(path, max_age_seconds=5)
        # Generous TTL: 30s -> accepted
        loaded = load_from_json(path, max_age_seconds=30)
        assert loaded.blueprint_id == bp.blueprint_id


# ===========================================================================
# Schema / errors
# ===========================================================================

class TestSchema:

    def test_missing_file_rejected(self, tmp_path: Path):
        with pytest.raises(DemoApiBlueprintRejected, match="inexistente"):
            load_from_json(tmp_path / "absent.json")

    def test_malformed_json_rejected(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text("not-json-{", encoding="utf-8")
        with pytest.raises(DemoApiBlueprintRejected, match="json_invalid"):
            load_from_json(path)

    def test_wrong_schema_version_rejected(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
        with pytest.raises(DemoApiBlueprintRejected, match="schema_version"):
            load_from_json(path)

    def test_non_object_json_rejected(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text("[]", encoding="utf-8")
        with pytest.raises(DemoApiBlueprintRejected, match="objeto"):
            load_from_json(path)

    def test_missing_required_fields_rejected(self, tmp_path: Path):
        path = tmp_path / "bad.json"
        path.write_text(
            json.dumps({"schema_version": 2, "blueprint_id": "x"}),
            encoding="utf-8",
        )
        with pytest.raises(DemoApiBlueprintRejected, match="schema_invalid"):
            load_from_json(path)
