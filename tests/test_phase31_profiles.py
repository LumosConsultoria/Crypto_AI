"""
Tests - FASE 31: perfis operacionais (registry + resolver)
===========================================================
100% offline. ZERO rede. ZERO ordem. ZERO secret.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.operational_profile import (
    SUPPORTED_PROFILE_NAMES,
    derive_endurance_limits,
    is_side_allowed,
    is_strategy_allowed,
    is_symbol_allowed,
    resolve_profile,
)


class TestRegistryResolves:

    def test_all_profiles_resolve(self):
        # 12 da FASE 31 + demo_multi_order_validation (FASE 30.2/36).
        assert len(SUPPORTED_PROFILE_NAMES) == 13
        for name in SUPPORTED_PROFILE_NAMES:
            p = resolve_profile(name, capital=5000.0)
            assert p.name == name or p.name  # nome definido
            assert p.account_size_usd == 5000.0

    def test_unknown_profile_rejected(self):
        with pytest.raises(ValueError, match="desconhecido"):
            resolve_profile("nonexistent", capital=5000.0)

    def test_invalid_capital_rejected(self):
        with pytest.raises(ValueError):
            resolve_profile("personal", capital=0)


class TestPersonalProfile:

    def test_personal_resolves_correctly(self):
        p = resolve_profile("personal", capital=5000.0)
        assert p.allowed_symbols == ("BTCUSDT",)
        assert p.allowed_sides == "both"
        assert p.max_open_positions == 1
        assert p.max_orders_per_session == 1
        assert p.max_orders_per_day == 3
        assert p.require_sl_tp is True
        assert p.allow_demo_real is True
        assert p.allow_short_demo is False       # ate gate explicito
        assert p.allow_multi_order_demo is False  # ate gate explicito
        assert p.allow_ai_assistance is True
        assert p.allow_ai_veto is True
        assert p.prediction_context_mode in ("advisory", "read_only")
        assert p.prediction_market_execution_allowed is False


class TestPropChallengeProfile:

    def test_prop_challenge_tighter_limits(self):
        prop = resolve_profile("prop_challenge", capital=5000.0)
        personal = resolve_profile("personal", capital=5000.0)
        assert prop.max_orders_per_day < personal.max_orders_per_day
        assert prop.max_consecutive_losses < \
            personal.max_consecutive_losses
        assert prop.allow_short_demo is False
        assert prop.allow_multi_order_demo is False
        assert prop.is_prop_firm and prop.is_challenge_account
        # Drawdown do challenge via risk_config_overrides
        assert prop.risk_config_overrides["max_daily_loss_pct"] == 0.02
        # Limites derivados refletem os overrides
        lim = derive_endurance_limits(prop)
        assert lim.max_daily_loss_pct == pytest.approx(2.0)


class TestSidesRespected:

    def test_long_only_blocks_sell(self):
        p = resolve_profile("long_only", capital=5000.0)
        assert is_side_allowed(p, "buy")
        assert is_side_allowed(p, "long")
        assert not is_side_allowed(p, "sell")
        assert not is_side_allowed(p, "short")

    def test_short_only_blocks_buy(self):
        p = resolve_profile("short_only", capital=5000.0)
        assert not is_side_allowed(p, "buy")
        assert is_side_allowed(p, "sell")

    def test_both_allows_both(self):
        p = resolve_profile("long_short", capital=5000.0)
        assert is_side_allowed(p, "buy") and is_side_allowed(p, "sell")

    def test_invalid_side_string_rejected(self):
        p = resolve_profile("personal", capital=5000.0)
        assert not is_side_allowed(p, "hold")
        assert not is_side_allowed(p, "")


class TestStrategiesRespected:

    def test_allowed_strategies_enforced(self):
        p = resolve_profile("personal", capital=5000.0)
        assert is_strategy_allowed(p, "trend_pullback")
        assert is_strategy_allowed(p, "trend_pullback_bidirectional")
        assert not is_strategy_allowed(p, "totally_fake_strategy")

    def test_empty_allowed_strategies_means_all(self):
        p = resolve_profile(
            "personal", capital=5000.0, allowed_strategies=(),
        )
        assert is_strategy_allowed(p, "anything")

    def test_symbol_allowed(self):
        p = resolve_profile("personal", capital=5000.0)
        assert is_symbol_allowed(p, "BTCUSDT")
        assert not is_symbol_allowed(p, "DOGEUSDT")


class TestMainnetLiveForbidden:

    def test_no_profile_allows_live_mainnet(self):
        for name in SUPPORTED_PROFILE_NAMES:
            p = resolve_profile(name, capital=5000.0)
            for env in p.allowed_environments:
                assert env.lower() not in (
                    "live", "mainnet", "production", "prod", "real",
                ), f"{name} permite ambiente proibido {env!r}"
            assert p.prediction_market_execution_allowed is False

    def test_live_environment_override_rejected(self):
        with pytest.raises(ValueError, match="proibido"):
            resolve_profile(
                "personal", capital=5000.0,
                allowed_environments=("demo", "live"),
            )

    def test_prediction_execution_override_rejected(self):
        with pytest.raises(ValueError, match="proibido"):
            resolve_profile(
                "personal", capital=5000.0,
                prediction_market_execution_allowed=True,
            )


class TestDerivedLimits:

    def test_limits_come_from_profile(self):
        p = resolve_profile(
            "personal", capital=5000.0,
            max_orders_per_day=7, max_api_failures=9,
        )
        lim = derive_endurance_limits(p)
        assert lim.max_orders_per_day == 7
        assert lim.max_api_failures == 9
        assert lim.require_sl_tp is True

    def test_to_dict_roundtrip(self):
        p = resolve_profile("ai_assisted_demo", capital=5000.0)
        d = p.to_dict()
        assert d["allow_ai_assistance"] is True
        assert d["prediction_market_execution_allowed"] is False
        assert "allowed_environments" in d
