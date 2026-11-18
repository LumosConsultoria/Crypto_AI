"""
Testes de ModeGuard — FASE 5 (testnet execution)
====================================================
⚠️  ZERO chamadas à internet.
⚠️  Settings injetados via fixtures determinísticas.
⚠️  Garantia: assert_live_allowed NÃO foi afrouxado.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.config.settings import Settings, TradingMode
from crypto_trading_bot.core.mode_guard import ModeGuard, TradingModeError


def _make_settings(
    *,
    trading_mode: TradingMode = TradingMode.PAPER,
    enable_live_trading: bool = False,
    enable_testnet_execution: bool = False,
) -> Settings:
    """Cria Settings determinístico para testes (sem ler .env)."""
    return Settings(
        trading_mode=trading_mode,
        enable_live_trading=enable_live_trading,
        enable_testnet_execution=enable_testnet_execution,
        _env_file=None,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# assert_testnet_execution_allowed — caminho feliz
# ---------------------------------------------------------------------------

class TestAssertTestnetExecutionAllowedHappyPath:

    def test_passes_with_triple_check(self):
        """trading_mode=testnet + enable_testnet_execution=true + confirm=True → OK."""
        s = _make_settings(
            trading_mode=TradingMode.TESTNET,
            enable_testnet_execution=True,
        )
        guard = ModeGuard(settings=s)
        # Não deve lançar
        guard.assert_testnet_execution_allowed(
            confirm_testnet_execution=True,
            context="test",
        )

    def test_is_testnet_execution_allowed_property_true(self):
        s = _make_settings(
            trading_mode=TradingMode.TESTNET,
            enable_testnet_execution=True,
        )
        guard = ModeGuard(settings=s)
        assert guard.is_testnet_execution_allowed is True


# ---------------------------------------------------------------------------
# assert_testnet_execution_allowed — bloqueios
# ---------------------------------------------------------------------------

class TestAssertTestnetExecutionBlocked:

    def test_blocks_without_trading_mode_testnet(self):
        s = _make_settings(
            trading_mode=TradingMode.PAPER,
            enable_testnet_execution=True,
        )
        guard = ModeGuard(settings=s)
        with pytest.raises(TradingModeError, match="TRADING_MODE"):
            guard.assert_testnet_execution_allowed(
                confirm_testnet_execution=True,
            )

    def test_blocks_without_enable_testnet_execution(self):
        s = _make_settings(
            trading_mode=TradingMode.TESTNET,
            enable_testnet_execution=False,   # flag false
        )
        guard = ModeGuard(settings=s)
        with pytest.raises(TradingModeError, match="ENABLE_TESTNET_EXECUTION"):
            guard.assert_testnet_execution_allowed(
                confirm_testnet_execution=True,
            )

    def test_blocks_without_confirm_testnet_execution(self):
        s = _make_settings(
            trading_mode=TradingMode.TESTNET,
            enable_testnet_execution=True,
        )
        guard = ModeGuard(settings=s)
        with pytest.raises(TradingModeError, match="confirm_testnet_execution"):
            guard.assert_testnet_execution_allowed(
                confirm_testnet_execution=False,    # default
            )

    def test_is_testnet_execution_allowed_property_false_in_paper(self):
        s = _make_settings(
            trading_mode=TradingMode.PAPER,
            enable_testnet_execution=True,
        )
        guard = ModeGuard(settings=s)
        assert guard.is_testnet_execution_allowed is False

    def test_is_testnet_execution_allowed_property_false_when_flag_off(self):
        s = _make_settings(
            trading_mode=TradingMode.TESTNET,
            enable_testnet_execution=False,
        )
        guard = ModeGuard(settings=s)
        assert guard.is_testnet_execution_allowed is False


# ---------------------------------------------------------------------------
# CRÍTICO: assert_live_allowed continua intacto após FASE 5
# ---------------------------------------------------------------------------

class TestLiveLockNotAfrouxado:

    def test_live_blocked_in_paper_mode_with_testnet_execution_true(self):
        """
        Sanity check: ter enable_testnet_execution=true NÃO permite live.
        """
        s = _make_settings(
            trading_mode=TradingMode.PAPER,
            enable_testnet_execution=True,
            enable_live_trading=False,
        )
        guard = ModeGuard(settings=s)
        with pytest.raises(TradingModeError, match="TRADING_MODE"):
            guard.assert_live_allowed(confirm_live_trading=True)

    def test_live_still_requires_triple_lock_after_testnet_features(self):
        """
        assert_live_allowed continua exigindo TODOS os 3 checks:
            TRADING_MODE=live, ENABLE_LIVE_TRADING=true, confirm_live_trading=True.
        """
        s_partial1 = _make_settings(
            trading_mode=TradingMode.LIVE,
            enable_live_trading=False,
            enable_testnet_execution=True,    # irrelevante para live
        )
        guard = ModeGuard(settings=s_partial1)
        with pytest.raises(TradingModeError, match="ENABLE_LIVE_TRADING"):
            guard.assert_live_allowed(confirm_live_trading=True)

        s_partial2 = _make_settings(
            trading_mode=TradingMode.LIVE,
            enable_live_trading=True,
            enable_testnet_execution=False,
        )
        guard = ModeGuard(settings=s_partial2)
        with pytest.raises(TradingModeError, match="confirm_live_trading"):
            guard.assert_live_allowed(confirm_live_trading=False)

    def test_live_allowed_only_with_full_triple_lock(self):
        s_full = _make_settings(
            trading_mode=TradingMode.LIVE,
            enable_live_trading=True,
        )
        guard = ModeGuard(settings=s_full)
        # Não deve lançar
        guard.assert_live_allowed(confirm_live_trading=True, context="audit")

    def test_testnet_execution_does_not_imply_live(self):
        """is_live continua False mesmo com testnet_execution=true em modo testnet."""
        s = _make_settings(
            trading_mode=TradingMode.TESTNET,
            enable_testnet_execution=True,
            enable_live_trading=False,
        )
        guard = ModeGuard(settings=s)
        assert guard.is_live is False
        assert guard.is_safe is True


# ---------------------------------------------------------------------------
# Status summary inclui campos novos
# ---------------------------------------------------------------------------

class TestStatusSummaryIncludesTestnetFields:

    def test_summary_contains_testnet_execution_fields(self):
        s = _make_settings(
            trading_mode=TradingMode.TESTNET,
            enable_testnet_execution=True,
        )
        guard = ModeGuard(settings=s)
        summary = guard.get_status_summary()
        assert "testnet_execution_env_enabled" in summary
        assert "is_testnet_execution_allowed" in summary
        assert summary["testnet_execution_env_enabled"] is True
        assert summary["is_testnet_execution_allowed"] is True

    def test_summary_legacy_fields_preserved(self):
        """Campos antigos continuam presentes."""
        s = _make_settings()
        guard = ModeGuard(settings=s)
        summary = guard.get_status_summary()
        for key in ("mode", "is_paper", "is_testnet", "is_live", "is_safe",
                    "live_env_enabled"):
            assert key in summary
