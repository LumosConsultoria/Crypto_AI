"""
Testes do gate de reduceOnly da ExitPolicy (FASE 11)
=====================================================
⚠️  100% offline.

Cobertura:
    - supports_reduce_only=False → auto_execute_blocked=True (sempre).
    - supports_reduce_only=True  → auto_execute_blocked=False (capability OK).
    - require_reduce_only_for_auto_close=True → requires_reduce_only=True.
    - require_reduce_only_for_auto_close=False NÃO libera auto-close
      para providers sem reduceOnly. auto_execute_blocked PERMANECE
      refletindo a capability.
    - Capability ≠ autorização: metadata expõe capability_allows_auto_close
      mas NÃO expõe execution_allowed.
    - Manual e Emergency reportam estados como qualquer outra decisão.
"""

from __future__ import annotations

from datetime import datetime, timezone

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.execution.provider_capability import ProviderCapability
from crypto_trading_bot.exit_policy import (
    ExitPolicy,
    OpenPositionState,
    PositionSide,
)


_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _cap(supports_ro: bool, provider_id: str = "mock") -> ProviderCapability:
    return ProviderCapability(
        provider_id=provider_id,
        supports_market_order=True,
        supports_reduce_only=supports_ro,
    )


def _buy_position() -> OpenPositionState:
    return OpenPositionState(
        symbol="BTCUSDT", side=PositionSide.BUY,
        entry_price=65000.0, entry_time=_NOW,
        stop_loss_price=64000.0, take_profit_price=67000.0,
        position_size_usd=200.0, entry_candle_idx=10,
    )


def _sl_candle() -> Candle:
    return Candle(
        symbol="BTCUSDT", timeframe="15", timestamp=_NOW,
        open=64500.0, high=65000.0, low=63500.0, close=64000.0,
        volume=1000.0,
    )


# ---------------------------------------------------------------------------
# auto_execute_blocked reflete somente a capability
# ---------------------------------------------------------------------------

class TestCapabilityGate:

    def test_no_reduce_only_blocks_auto_execute(self):
        policy = ExitPolicy(
            provider_capability=_cap(supports_ro=False),
        )
        d = policy.evaluate(
            position=_buy_position(),
            candle=_sl_candle(),
            now=_NOW,
            candle_idx=11,
        )
        assert d.should_close is True
        assert d.auto_execute_blocked is True
        assert d.metadata.get("capability_allows_auto_close") is False

    def test_with_reduce_only_capability_unblocks_at_capability_layer(self):
        policy = ExitPolicy(
            provider_capability=_cap(supports_ro=True),
        )
        d = policy.evaluate(
            position=_buy_position(),
            candle=_sl_candle(),
            now=_NOW,
            candle_idx=11,
        )
        assert d.should_close is True
        assert d.auto_execute_blocked is False
        assert d.metadata.get("capability_allows_auto_close") is True


# ---------------------------------------------------------------------------
# require_reduce_only_for_auto_close NÃO libera providers sem reduceOnly
# ---------------------------------------------------------------------------

class TestRequireReduceOnlyOverrideCannotBypass:

    def test_override_does_not_unblock_provider_without_ro(self):
        policy = ExitPolicy(
            provider_capability=_cap(supports_ro=False),
            require_reduce_only_for_auto_close=False,  # override
        )
        d = policy.evaluate(
            position=_buy_position(),
            candle=_sl_candle(),
            now=_NOW,
            candle_idx=11,
        )
        # auto_execute_blocked permanece True — capability é soberana
        assert d.auto_execute_blocked is True
        # requires_reduce_only respeita o override (reporta False)
        assert d.requires_reduce_only is False

    def test_override_true_default_keeps_requires_reduce_only_true(self):
        policy = ExitPolicy(
            provider_capability=_cap(supports_ro=True),
            # require_reduce_only_for_auto_close=True é o default
        )
        d = policy.evaluate(
            position=_buy_position(),
            candle=_sl_candle(),
            now=_NOW,
            candle_idx=11,
        )
        assert d.requires_reduce_only is True

    def test_override_false_with_ro_capability_still_reports_false(self):
        policy = ExitPolicy(
            provider_capability=_cap(supports_ro=True),
            require_reduce_only_for_auto_close=False,
        )
        d = policy.evaluate(
            position=_buy_position(),
            candle=_sl_candle(),
            now=_NOW,
            candle_idx=11,
        )
        # Override é apenas reportagem; auto_execute_blocked segue capability.
        assert d.requires_reduce_only is False
        assert d.auto_execute_blocked is False


# ---------------------------------------------------------------------------
# Capability ≠ autorização (metadata)
# ---------------------------------------------------------------------------

class TestCapabilityIsNotAuthorization:

    def test_metadata_includes_capability_flag_only(self):
        policy = ExitPolicy(provider_capability=_cap(supports_ro=True))
        d = policy.evaluate(
            position=_buy_position(),
            candle=_sl_candle(),
            now=_NOW,
            candle_idx=11,
        )
        # Metadata expõe capability_allows_auto_close
        assert "capability_allows_auto_close" in d.metadata
        # Mas NÃO expõe execution_allowed — capability ≠ autorização
        assert "execution_allowed" not in d.metadata
        assert "executor_authorized" not in d.metadata
        assert "ready_to_execute" not in d.metadata


# ---------------------------------------------------------------------------
# Manual e Emergency reportam estado normalmente
# ---------------------------------------------------------------------------

class TestManualAndEmergencyReportCapability:

    def test_manual_close_reports_capability_state_too(self):
        policy = ExitPolicy(
            provider_capability=_cap(supports_ro=False),
        )
        d = policy.evaluate(
            position=_buy_position(),
            now=_NOW,
            manual_close_requested=True,
        )
        # Humano pode fechar manualmente fora do bot; ainda assim
        # reportamos que auto-execute (via bot) está bloqueado.
        assert d.auto_execute_blocked is True

    def test_emergency_close_reports_capability_state_too(self):
        policy = ExitPolicy(
            provider_capability=_cap(supports_ro=False),
            emergency_close_enabled=True,
        )
        d = policy.evaluate(
            position=_buy_position(),
            now=_NOW,
            emergency_active=True,
        )
        assert d.auto_execute_blocked is True
