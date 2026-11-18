"""
Tests - LiveDemoBlueprintProvider (FASE 27)
================================================
100% offline. ZERO network. ZERO ordem.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from crypto_trading_bot.demo_endurance import (
    LiveDemoBlueprintError,
    LiveDemoBlueprintProvider,
    PlannedDemoBlueprint,
    LIVE_BLUEPRINT_DEFAULT_TTL_SECONDS,
    LIVE_BLUEPRINT_REFRESH_THRESHOLD_SECONDS,
)


NOW = datetime(2026, 6, 4, 12, tzinfo=timezone.utc)


class _FakePreflight:
    """Substituto offline de PreflightReport para testes."""
    def __init__(self, *, ok=True, manual=(), abort_reason=None):
        self.ok = ok
        self.manual_confirmations_needed = tuple(manual)
        self.abort_reason = abort_reason
        self.abort_details = ""
        if ok:
            self.market_info = MagicMock(
                symbol="BTCUSDT", tick_size=0.5, qty_step=0.001,
                min_notional_value=5.0, reference_price=65000.0,
            )
            self.account_state = MagicMock(
                wallet_balance_usdt=5000.0,
                available_balance_usdt=5000.0,
                open_positions_count=0, open_orders_count=0,
                leverage_confirmable=True, leverage_value=1.0,
            )
            self.proposal = MagicMock(
                symbol="BTCUSDT", side="buy", reference_price=65000.0,
                qty=0.003, position_size_usd=195.0,
                stop_loss=64025.0, take_profit=66950.0,
                leverage=1.0, risk_usd=2.925, capital=5000.0,
            )
        else:
            self.market_info = None
            self.account_state = None
            self.proposal = None


class TestProviderHappyPath:

    def test_preflight_returns_snapshot(self):
        prov = LiveDemoBlueprintProvider(
            preflight_factory=lambda: _FakePreflight(),
            clock=lambda: NOW,
        )
        snap = prov.preflight()
        assert snap.blueprint_id.startswith("BP-")
        assert isinstance(snap.blueprint, PlannedDemoBlueprint)
        assert snap.blueprint.side == "buy"
        assert snap.blueprint.qty == 0.003

    def test_blueprint_id_is_unique_per_call(self):
        prov = LiveDemoBlueprintProvider(
            preflight_factory=lambda: _FakePreflight(),
            clock=lambda: NOW,
        )
        a = prov.preflight()
        b = prov.preflight()
        assert a.blueprint_id != b.blueprint_id

    def test_last_snapshot_cached(self):
        prov = LiveDemoBlueprintProvider(
            preflight_factory=lambda: _FakePreflight(),
            clock=lambda: NOW,
        )
        snap = prov.preflight()
        assert prov.last_snapshot is snap

    def test_ttl_default_60(self):
        prov = LiveDemoBlueprintProvider(
            preflight_factory=lambda: _FakePreflight(),
            clock=lambda: NOW,
        )
        assert prov.ttl_seconds == LIVE_BLUEPRINT_DEFAULT_TTL_SECONDS == 60


class TestProviderRejectsBadPreflight:

    def test_factory_returning_none_raises(self):
        prov = LiveDemoBlueprintProvider(
            preflight_factory=lambda: None,
            clock=lambda: NOW,
        )
        with pytest.raises(LiveDemoBlueprintError):
            prov.preflight()

    def test_not_ok_preflight_raises(self):
        prov = LiveDemoBlueprintProvider(
            preflight_factory=lambda: _FakePreflight(ok=False),
            clock=lambda: NOW,
        )
        with pytest.raises(LiveDemoBlueprintError, match="not ok"):
            prov.preflight()

    def test_manual_confirmations_raises(self):
        prov = LiveDemoBlueprintProvider(
            preflight_factory=lambda: _FakePreflight(
                manual=("low_balance",)
            ),
            clock=lambda: NOW,
        )
        with pytest.raises(LiveDemoBlueprintError, match="manual"):
            prov.preflight()

    def test_missing_take_profit_raises(self):
        pf = _FakePreflight()
        pf.proposal.take_profit = None
        prov = LiveDemoBlueprintProvider(
            preflight_factory=lambda: pf, clock=lambda: NOW,
        )
        with pytest.raises(LiveDemoBlueprintError, match="take_profit"):
            prov.preflight()


class TestFreshnessAndRefresh:

    def test_is_fresh_true_at_generation(self):
        prov = LiveDemoBlueprintProvider(
            preflight_factory=lambda: _FakePreflight(),
            clock=lambda: NOW,
        )
        snap = prov.preflight()
        assert snap.is_fresh(NOW) is True

    def test_is_fresh_false_after_ttl(self):
        prov = LiveDemoBlueprintProvider(
            preflight_factory=lambda: _FakePreflight(),
            clock=lambda: NOW,
        )
        snap = prov.preflight()
        later = NOW + timedelta(seconds=snap.ttl_seconds + 1)
        assert snap.is_fresh(later) is False

    def test_ttl_remaining_decays_to_zero(self):
        prov = LiveDemoBlueprintProvider(
            preflight_factory=lambda: _FakePreflight(),
            clock=lambda: NOW,
        )
        snap = prov.preflight()
        assert snap.ttl_remaining(NOW) == snap.ttl_seconds
        assert snap.ttl_remaining(
            NOW + timedelta(seconds=snap.ttl_seconds + 5)
        ) == 0

    def test_ensure_fresh_returns_cached_when_fresh(self):
        counter = [0]
        def fac():
            counter[0] += 1
            return _FakePreflight()
        # clock fixo: nada envelhece
        prov = LiveDemoBlueprintProvider(
            preflight_factory=fac, clock=lambda: NOW,
        )
        prov.preflight()
        assert counter[0] == 1
        prov.ensure_fresh()
        # ainda fresh -> NAO refizer preflight
        assert counter[0] == 1

    def test_ensure_fresh_reruns_when_stale(self):
        counter = [0]
        def fac():
            counter[0] += 1
            return _FakePreflight()
        prov = LiveDemoBlueprintProvider(
            preflight_factory=fac, clock=lambda: NOW, ttl_seconds=60,
        )
        first = prov.preflight()
        assert counter[0] == 1
        later = NOW + timedelta(seconds=50)  # ttl_remaining=10 (< threshold)
        prov.ensure_fresh(threshold_seconds=30, now=later)
        # re-rodou preflight
        assert counter[0] == 2

    def test_refresh_always_reruns(self):
        counter = [0]
        def fac():
            counter[0] += 1
            return _FakePreflight()
        prov = LiveDemoBlueprintProvider(
            preflight_factory=fac, clock=lambda: NOW,
        )
        prov.preflight()
        prov.refresh()
        assert counter[0] == 2


class TestNeverInstantiatesNetworkClients:
    """Garantia estrutural: provider nunca importa BybitClient/Executor."""

    def test_provider_module_no_forbidden_tokens(self):
        from pathlib import Path
        p = Path(__file__).parent.parent / "src" / "crypto_trading_bot" / \
            "demo_endurance" / "live_blueprint_provider.py"
        src = p.read_text(encoding="utf-8")
        # Strip docs/comments naively
        in_doc = False
        out = []
        for line in src.splitlines():
            s = line.strip()
            if in_doc:
                if s.endswith('"""') or s.endswith("'''"):
                    in_doc = False
                continue
            if s.startswith('"""') or s.startswith("'''"):
                if not (s.endswith('"""') and len(s) > 3):
                    in_doc = True
                continue
            if s.startswith("#"):
                continue
            out.append(line)
        exe = "\n".join(out)
        for tok in (
            "import httpx", "from httpx",
            "import requests", "from requests",
            "BybitClient(", "BybitDemoExecutor(",
            "BybitDemoPreflight(",
            "execute_demo_session_gated(",
            "build_demo_api_blueprint(",
            "load_dotenv",
        ):
            assert tok not in exe, f"forbidden in live provider: {tok}"
