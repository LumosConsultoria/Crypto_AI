"""
Tests - FASE 36 pos-demo 3: alinhamento Strategy SL x piso do RiskEngine
=========================================================================
100% offline. NUNCA baixa o piso; NUNCA forca ordem; NUNCA chama rede.
Reproduz o cenario demo_real_multi_fase36_003 (SL ATR ~0.47% < 0.5%).
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pandas as pd
import pytest

from crypto_trading_bot.decision_trace import (
    FinalDecision, build_trace_entry,
)
from crypto_trading_bot.research.advisor_recommendations import (
    detect_sl_below_min_recurrence,
)
from crypto_trading_bot.strategies.signal_model import StrategyAction
from crypto_trading_bot.strategies.trend_pullback_bidirectional_strategy \
    import (
        TrendPullbackBidirectionalStrategy,
        plan_risk_aware_stop,
    )

_NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)


def _features(*, ema_fast, ema_slow, last_close, last_rsi, last_atr,
              fast=20, slow=50):
    return {
        "symbol": "BTCUSDT", "has_sufficient_data": True,
        "n_candles": 120, "last_close": last_close,
        "last_high": last_close * 1.001, "last_low": last_close * 0.999,
        "last_volume": 1000.0, "last_rsi": last_rsi,
        "last_atr": last_atr,
        f"ema_{fast}": pd.Series([ema_fast]),
        f"ema_{slow}": pd.Series([ema_slow]),
    }


def _buy_strategy(**kw):
    s = TrendPullbackBidirectionalStrategy(**kw)
    s.set_running()
    return s


# Setup BUY com ATR baixo: SL = 1.5*ATR. entry=65000, ATR=204
# -> SL dist = 306 -> 0.4708% (< piso 0.5%), reproduzindo a demo.
_LOWVOL_BUY = dict(
    ema_fast=65100.0, ema_slow=64900.0, last_close=65000.0,
    last_rsi=50.0, last_atr=204.0,
)


class TestStrategyFloorAwareRejection:

    def test_legacy_none_floor_emits_signal(self):
        # Default (min_stop_loss_pct=None): comportamento legado — emite
        # BUY mesmo com SL abaixo do piso (RiskEngine decide depois).
        s = _buy_strategy()
        sig = s.evaluate(_features(**_LOWVOL_BUY))
        assert sig.action == StrategyAction.BUY
        # planned_sl_pct exposto na metadata para o trace.
        assert sig.metadata["planned_sl_pct"] == pytest.approx(
            0.4708, abs=0.01,
        )

    def test_floor_set_rejects_signal_below_min(self):
        s = _buy_strategy(min_stop_loss_pct=0.005)   # 0.5%
        sig = s.evaluate(_features(**_LOWVOL_BUY))
        assert sig.action == StrategyAction.HOLD
        assert sig.reason == "stop_below_min_risk_floor"
        m = sig.metadata
        assert m["risk_rejection_category"] == "stop_loss_below_minimum"
        assert m["planned_sl_pct"] < m["min_sl_pct_required"]
        assert m["sl_gap_to_min_pct"] > 0
        assert "stop_below_min_risk_floor" in m["failed_conditions_long"]

    def test_floor_exactly_met_emits_signal(self):
        # ATR tal que 1.5*ATR/entry == 0.5% exatamente.
        atr = (0.005 * 65000.0) / 1.5     # = 216.6667
        s = _buy_strategy(min_stop_loss_pct=0.005)
        sig = s.evaluate(_features(
            ema_fast=65100.0, ema_slow=64900.0, last_close=65000.0,
            last_rsi=50.0, last_atr=atr,
        ))
        assert sig.action == StrategyAction.BUY
        assert sig.metadata["planned_sl_pct"] == pytest.approx(
            0.5, abs=0.01,
        )

    def test_floor_above_min_emits_signal(self):
        s = _buy_strategy(min_stop_loss_pct=0.005)
        sig = s.evaluate(_features(
            ema_fast=65100.0, ema_slow=64900.0, last_close=65000.0,
            last_rsi=50.0, last_atr=400.0,   # 1.5*400/65000 = 0.92%
        ))
        assert sig.action == StrategyAction.BUY

    def test_sell_side_floor_rejection(self):
        s = _buy_strategy(min_stop_loss_pct=0.005)
        sig = s.evaluate(_features(
            ema_fast=64900.0, ema_slow=65100.0, last_close=65000.0,
            last_rsi=50.0, last_atr=204.0,   # downtrend, ATR baixo
        ))
        assert sig.action == StrategyAction.HOLD
        assert sig.reason == "stop_below_min_risk_floor"
        assert "stop_below_min_risk_floor" in \
            sig.metadata["failed_conditions_short"]

    def test_invalid_floor_rejected(self):
        with pytest.raises(ValueError, match="min_stop_loss_pct"):
            TrendPullbackBidirectionalStrategy(min_stop_loss_pct=1.5)


class TestDecisionTraceSLDiagnostics:

    def _ts(self, entry=65000.0, stop=64694.0):
        from crypto_trading_bot.strategies.signal_model import (
            StrategySignal,
        )
        return StrategySignal.buy(
            symbol="BTCUSDT", strategy_name="s", entry_price=entry,
            stop_loss_price=stop, take_profit_price=entry + 600,
            position_size_usd=200.0,
        ).to_trading_signal()

    def test_sl_below_min_diagnostics_on_skip(self):
        # SL 64694 em 65000 = 0.4708% < piso 0.5%; RiskEngine reprovou.
        entry = build_trace_entry(
            cycle_idx=12, final_decision=FinalDecision.SKIP,
            final_reason="RiskEngine reprovou: Stop loss muito pequeno",
            trading_signal=self._ts(),
            risk_summary={
                "approved": False,
                "reason": "Stop loss muito pequeno: 0.471% < 0.500%",
                "min_stop_loss_pct": 0.005,
            },
            now=_NOW,
        )
        d = entry.to_dict()
        assert d["planned_sl_pct"] == pytest.approx(0.4708, abs=0.01)
        assert d["min_sl_pct_required"] == pytest.approx(0.5, abs=0.001)
        assert d["sl_gap_to_min_pct"] > 0
        assert d["risk_rejection_category"] == "stop_loss_below_minimum"
        assert d["recommended_action"]
        assert "piso" in d["recommended_action"]

    def test_other_rejection_not_categorized_as_sl(self):
        # SL acima do piso (1%); rejeicao por outro motivo.
        entry = build_trace_entry(
            cycle_idx=1, final_decision=FinalDecision.SKIP,
            final_reason="RiskEngine reprovou: limite diario",
            trading_signal=self._ts(stop=64350.0),  # ~1%
            risk_summary={
                "approved": False, "reason": "limite diario",
                "min_stop_loss_pct": 0.005,
            },
            now=_NOW,
        )
        d = entry.to_dict()
        assert d["planned_sl_pct"] == pytest.approx(1.0, abs=0.02)
        assert d["risk_rejection_category"] is None

    def test_hold_risk_aware_carries_diagnostics(self):
        # HOLD da estrategia (floor set) -> snapshot tem os campos SL.
        s = _buy_strategy(min_stop_loss_pct=0.005)
        sig = s.evaluate(_features(**_LOWVOL_BUY))
        from crypto_trading_bot.demo_endurance.real_runner import (
            _signal_snapshot_fields,
        )
        snap = _signal_snapshot_fields(sig)
        entry = build_trace_entry(
            cycle_idx=3, final_decision=FinalDecision.HOLD,
            final_reason="stop_below_min_risk_floor",
            signal_snapshot=snap, now=_NOW,
        )
        d = entry.to_dict()
        assert d["planned_sl_pct"] is not None
        assert d["min_sl_pct_required"] is not None
        assert d["risk_rejection_category"] == "stop_loss_below_minimum"


class TestPlanRiskAwareStop:

    def test_clamps_to_floor_long(self):
        p = plan_risk_aware_stop(
            side="buy", entry=65000.0, atr=204.0,
            stop_atr_multiplier=1.5, risk_reward_ratio=2.0,
            min_stop_loss_pct=0.005, position_size_usd=200.0,
            max_risk_per_trade_usd=25.0,
        )
        assert p["clamped_to_floor"] is True
        assert p["sl_pct"] == pytest.approx(0.5, abs=0.001)
        assert p["stop"] < p["entry"] < p["take_profit"]
        # risco no piso ~1 USD, MUITO abaixo do teto 25 USD.
        assert p["risk_usd"] == pytest.approx(1.0, abs=0.05)
        assert p["within_risk_budget"] is True
        assert p["tp_valid"] is True

    def test_no_clamp_when_atr_above_floor(self):
        p = plan_risk_aware_stop(
            side="buy", entry=65000.0, atr=400.0,
            stop_atr_multiplier=1.5, risk_reward_ratio=2.0,
            min_stop_loss_pct=0.005, position_size_usd=200.0,
        )
        assert p["clamped_to_floor"] is False
        assert p["sl_pct"] > 0.5

    def test_short_side_coherent(self):
        p = plan_risk_aware_stop(
            side="sell", entry=65000.0, atr=204.0,
            stop_atr_multiplier=1.5, risk_reward_ratio=2.0,
            min_stop_loss_pct=0.005, position_size_usd=200.0,
        )
        assert p["take_profit"] < p["entry"] < p["stop"]
        assert p["tp_valid"] is True

    def test_capped_by_max(self):
        p = plan_risk_aware_stop(
            side="buy", entry=65000.0, atr=5000.0,
            stop_atr_multiplier=1.5, risk_reward_ratio=2.0,
            min_stop_loss_pct=0.005, max_stop_loss_pct=0.05,
            position_size_usd=200.0,
        )
        assert p["capped_to_max"] is True
        assert p["sl_pct"] == pytest.approx(5.0, abs=0.001)

    def test_over_budget_flagged_not_forced(self):
        # Teto de risco minusculo -> sinaliza fora do orcamento (nao
        # mascara, nao altera sizing escondido).
        p = plan_risk_aware_stop(
            side="buy", entry=65000.0, atr=204.0,
            stop_atr_multiplier=1.5, risk_reward_ratio=2.0,
            min_stop_loss_pct=0.005, position_size_usd=200.0,
            max_risk_per_trade_usd=0.5,
        )
        assert p["within_risk_budget"] is False


class TestAdvisorRecurrenceDetection:

    def _trace(self, planned, mn):
        return {
            "risk_rejection_category": "stop_loss_below_minimum",
            "planned_sl_pct": planned, "min_sl_pct_required": mn,
        }

    def test_detects_recurrence_with_three_profiles(self):
        traces = [self._trace(p, 0.5) for p in
                  (0.455, 0.471, 0.488, 0.495)]
        r = detect_sl_below_min_recurrence(traces, min_occurrences=3)
        assert r["detected"] is True
        assert r["occurrences"] == 4
        profiles = {rec["suggestion_profile"]
                    for rec in r["recommendations"]}
        assert profiles == {"conservador", "moderado", "arrojado"}
        assert all(rec["needs_backtest"]
                   for rec in r["recommendations"])
        # moderado sugere piso strategy-side = piso do RiskEngine.
        mod = next(rec for rec in r["recommendations"]
                   if rec["suggestion_profile"] == "moderado")
        assert mod["suggested_min_stop_loss_pct"] == pytest.approx(
            0.005, abs=1e-4,
        )
        # arrojado sugere fator de multiplicador (~0.5/0.477).
        arr = next(rec for rec in r["recommendations"]
                   if rec["suggestion_profile"] == "arrojado")
        assert arr["suggested_multiplier_factor"] > 1.0

    def test_below_threshold_no_detection(self):
        r = detect_sl_below_min_recurrence(
            [self._trace(0.47, 0.5)], min_occurrences=3,
        )
        assert r["detected"] is False
        assert r["recommendations"] == []

    def test_ignores_non_sl_rejections(self):
        traces = [
            {"risk_rejection_category": None},
            {"final_decision": "hold"},
        ]
        r = detect_sl_below_min_recurrence(traces)
        assert r["occurrences"] == 0
        assert r["detected"] is False

    def test_never_lowers_floor_note(self):
        r = detect_sl_below_min_recurrence(
            [self._trace(0.47, 0.5)] * 3,
        )
        assert "NAO baixa o piso" in r["note"]


class TestStrategyRegressionPreserved:

    def test_default_strategy_unchanged_actionable(self):
        # Sem floor, setup valido normal continua BUY (FASE 29.x).
        s = _buy_strategy()
        sig = s.evaluate(_features(
            ema_fast=100.0, ema_slow=90.0, last_close=95.0,
            last_rsi=50.0, last_atr=2.0,
        ))
        assert sig.action == StrategyAction.BUY
        assert sig.stop_loss_price < sig.entry_price < \
            sig.take_profit_price
