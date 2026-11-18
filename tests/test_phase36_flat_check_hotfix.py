"""
Tests - FASE 36 hotfix: flat-check de posicao estrutural zerada
================================================================
A Bybit Demo retorna estrutura de posicao com size="0" mesmo SEM
exposicao. O flat-check deve diferenciar estrutura zerada de posicao
real. 100% offline; nenhuma ordem; nenhuma rede.
Reproduz o cenario demo_real_multi_fase36_002.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from crypto_trading_bot.demo_endurance import (
    DemoEnduranceRunner, DurationSpec, EnduranceEndedReason,
)
from crypto_trading_bot.demo_endurance.flat_check_validator import (
    is_effectively_flat_position,
    validate_flat,
)
from crypto_trading_bot.operational_profile import (
    derive_endurance_limits, resolve_profile,
)
from tests.test_phase30_demo_endurance import (
    FakeClock, StubFeatureEngine, StubRiskApprove, StubStrategyHold,
    _fresh_candles,
)
from tests.test_phase30_2_real_multi import _ScriptedLifecycle

_START = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helper de posicao efetiva (1-7)
# ---------------------------------------------------------------------------

class TestEffectiveFlatPosition:

    @pytest.mark.parametrize("pos", [
        {"symbol": "BTCUSDT", "size": "0"},
        {"symbol": "BTCUSDT", "size": "0.0"},
        {"symbol": "BTCUSDT", "size": 0.0},
        {"symbol": "BTCUSDT", "size": 0},
        {"symbol": "BTCUSDT", "qty": "0"},
        {"symbol": "BTCUSDT", "position_size": "0"},
        {"symbol": "BTCUSDT", "size": ""},       # presente vazio => 0
        {"symbol": "BTCUSDT", "size": None},      # presente None => 0
    ])
    def test_zero_size_is_flat(self, pos):
        assert is_effectively_flat_position(pos) is True

    @pytest.mark.parametrize("pos", [
        {"symbol": "BTCUSDT", "size": "0.001"},
        {"symbol": "BTCUSDT", "qty": 0.003},
        {"symbol": "BTCUSDT", "size": "-0.01"},   # short real
        {"symbol": "BTCUSDT", "position_value": "120.5"},
    ])
    def test_real_exposure_not_flat(self, pos):
        assert is_effectively_flat_position(pos) is False

    def test_ambiguous_structure_conservative_not_flat(self):
        # Nenhum campo de qty/nocional reconhecido => ambiguo =>
        # conservador (nao mascara posicao real).
        assert is_effectively_flat_position(
            {"symbol": "BTCUSDT", "positionIdx": 0},
        ) is False
        assert is_effectively_flat_position("not-a-dict") is False


# ---------------------------------------------------------------------------
# validate_flat (1-7)
# ---------------------------------------------------------------------------

class TestValidateFlat:

    def test_1_empty_positions_flat(self):
        r = validate_flat(positions=[], open_orders=[],
                          conditional_orders=[])
        assert r.is_flat is True
        assert r.effective_open_positions_count == 0

    def test_2_size_string_zero_flat(self):
        r = validate_flat(positions=[{"symbol": "BTCUSDT",
                                     "size": "0"}])
        assert r.is_flat is True
        assert r.positions_count == 1            # estrutural mantida
        assert r.effective_open_positions_count == 0
        assert r.residual_qty == 0.0

    def test_3_size_float_zero_flat(self):
        r = validate_flat(positions=[{"size": 0.0}])
        assert r.is_flat is True

    def test_4_qty_string_zero_flat(self):
        r = validate_flat(positions=[{"qty": "0"}])
        assert r.is_flat is True

    def test_5_zero_size_but_open_order_blocks(self):
        r = validate_flat(
            positions=[{"size": "0"}],
            open_orders=[{"id": "X"}],
        )
        assert r.is_flat is False
        assert any("open_orders_count" in b for b in r.blockers)

    def test_6_zero_size_but_conditional_blocks(self):
        r = validate_flat(
            positions=[{"size": "0"}],
            conditional_orders=[{"id": "Y"}],
        )
        assert r.is_flat is False
        assert any("conditional_orders_count" in b for b in r.blockers)

    def test_7_small_real_size_not_flat(self):
        r = validate_flat(positions=[{"size": "0.001"}])
        assert r.is_flat is False
        assert r.effective_open_positions_count == 1
        assert r.residual_qty == pytest.approx(0.001)

    def test_fase29_residual_contract_preserved(self):
        # Regressao do contrato FASE 29 (test_phase29_modules).
        r = validate_flat(positions=[{"size": "0.003"}])
        assert r.is_flat is False
        assert r.positions_count == 1
        assert r.residual_qty == 0.003

    def test_to_dict_has_new_field(self):
        d = validate_flat(positions=[{"size": "0"}]).to_dict()
        assert d["effective_open_positions_count"] == 0
        assert d["positions_count"] == 1
        assert d["is_flat"] is True


# ---------------------------------------------------------------------------
# Integracao runner real-multi (8-9): cenario fase36_002
# ---------------------------------------------------------------------------

class TestRunnerNoFalseManualReview:

    def _run(self, *, flat_check, strategy=None, duration_min=10):
        clock = FakeClock(_START)
        profile = resolve_profile(
            "demo_multi_order_validation", capital=5000.0,
        )
        return DemoEnduranceRunner(
            profile=profile,
            duration=DurationSpec(
                duration_minutes=duration_min,
                cycle_interval_seconds=60,
            ),
            limits=derive_endurance_limits(profile),
            symbol="BTCUSDT",
            strategy_name="trend_pullback_bidirectional",
            operator_token="OPTOK_TEST",
            market_data_callable=_fresh_candles(clock),
            feature_engine=StubFeatureEngine(),
            strategy=strategy or StubStrategyHold(),
            risk_engine=StubRiskApprove(),
            real_time=True, clock=clock, sleep=clock.sleep,
            execute_real_multi=True, max_real_orders=2,
            real_trade_lifecycle=_ScriptedLifecycle([{}]),
            flat_check_callable=flat_check,
        ).run()

    def test_8_zero_exposure_not_manual_review(self):
        # Flat-check sempre retorna posicao estrutural size=0.
        def flat_check():
            return validate_flat(
                positions=[{"symbol": "BTCUSDT", "size": "0",
                            "side": ""}],
                open_orders=[], conditional_orders=[],
            ).to_dict()

        outcome = self._run(flat_check=flat_check)
        d = outcome.to_dict()
        assert "flat_check_not_flat" not in d["warnings"]
        assert d["ended_reason"] == "passed_zero_trades"
        assert d["orders_submitted"] == 0
        assert d["final_open_positions_count"] == 0
        # final_flat_check_passed NAO fica null: flat-check rodou e OK.
        assert d["final_flat_check_passed"] is True

    def test_9_zero_signals_inconclusive_not_manual_review(self):
        outcome = self._run(flat_check=None)  # sem flat-check periodico
        d = outcome.to_dict()
        assert d["ended_reason"] == "passed_zero_trades"
        assert "flat_check_not_flat" not in d["warnings"]
        assert d["orders_submitted"] == 0

    def test_real_residual_still_manual_review(self):
        # Posicao REAL (size>0) ainda deve gerar manual review.
        def flat_check():
            return validate_flat(
                positions=[{"symbol": "BTCUSDT", "size": "0.01"}],
            ).to_dict()

        outcome = self._run(flat_check=flat_check)
        d = outcome.to_dict()
        assert d["ended_reason"] == "manual_review_required"
        assert "flat_check_not_flat" in d["warnings"]

    def test_open_order_residual_still_manual_review(self):
        def flat_check():
            return validate_flat(
                positions=[{"size": "0"}],
                open_orders=[{"id": "stuck"}],
            ).to_dict()

        outcome = self._run(flat_check=flat_check)
        d = outcome.to_dict()
        assert d["ended_reason"] == "manual_review_required"
        assert "flat_check_not_flat" in d["warnings"]
