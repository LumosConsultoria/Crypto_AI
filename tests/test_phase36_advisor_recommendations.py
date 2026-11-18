"""
Tests - FASE 36 Bloco E: Advisor completo (regime + 3 perfis +
lifecycle de aceite auditavel)
================================================================
100% offline. Caps/validacoes usam FIXTURES DE TESTE marcadas.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from crypto_trading_bot.research.advisor_recommendations import (
    ParameterRecommendation,
    RecommendationStore,
    build_recommendations,
    detect_market_regime,
)

_NOW = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)

_CURRENT_CONFIG = {
    "ema_fast_period": 20, "ema_slow_period": 50,
    "rsi_period": 14, "rsi_long_overbought": 70.0,
    "rsi_short_oversold": 30.0, "pullback_atr_tolerance_k": 0.0,
    "stop_atr_multiplier": 1.5, "risk_reward_ratio": 2.0,
}

_REPORT = {
    "candidate_strategy": "trend_pullback_bidirectional",
    "long": {
        "recommended_config": {
            "ema_fast_period": 9, "ema_slow_period": 21,
            "rsi_long_overbought": 75.0,
            "pullback_atr_tolerance_k": 0.2,
            "enable_long": True, "enable_short": False,
        },
        "performance": {
            "profit_factor": 1.8, "total_trades": 12,
            "overfitting_warning": False,
        },
    },
    "short": {"recommended_config": None, "performance": {}},
}


def _candles(trend=0.002, vol=0.004, n=120):
    from crypto_trading_bot.backtesting.backtest_data import (
        generate_trending_candles,
    )
    return generate_trending_candles(
        n=n, base_price=100.0, trend_pct_per_candle=trend,
        volatility_pct=vol, symbol="BTCUSDT", timeframe="15",
    )


class TestRegimeDetection:

    def test_trending_up(self):
        regime = detect_market_regime(_candles(trend=0.004, vol=0.001))
        assert regime["regime"] in ("trending_up", "high_volatility")
        assert regime["evidence"]["total_return_pct"] > 3.0

    def test_unknown_with_few_candles(self):
        regime = detect_market_regime(_candles(n=120)[:10])
        assert regime["regime"] == "unknown"

    def test_evidence_fields(self):
        regime = detect_market_regime(_candles())
        for key in ("total_return_pct", "atr_pct", "noise_ratio"):
            assert key in regime["evidence"]


class TestBuildRecommendations:

    def test_three_profiles_generated(self):
        recs = build_recommendations(
            advisor_report=_REPORT,
            regime={"regime": "trending_up"},
            current_config=_CURRENT_CONFIG, now=_NOW,
        )
        profiles = {r.suggestion_profile for r in recs}
        assert profiles == {"conservador", "moderado", "arrojado"}

    def test_conservador_smaller_delta_than_arrojado(self):
        recs = build_recommendations(
            advisor_report=_REPORT,
            regime={"regime": "ranging"},
            current_config=_CURRENT_CONFIG, now=_NOW,
        )
        by_profile = {r.suggestion_profile: r for r in recs}
        cons = by_profile["conservador"].suggested_config
        arro = by_profile["arrojado"].suggested_config
        # rsi 70 -> 75: conservador anda 1/3 (71.65), arrojado 75.
        assert cons["rsi_long_overbought"] < \
            arro["rsi_long_overbought"]
        assert arro["rsi_long_overbought"] == 75.0
        # EMA (estrutural) so muda no arrojado.
        assert cons["ema_fast_period"] == 20
        assert arro["ema_fast_period"] == 9

    def test_required_fields_per_recommendation(self):
        recs = build_recommendations(
            advisor_report=_REPORT,
            regime={"regime": "ranging"},
            current_config=_CURRENT_CONFIG, now=_NOW,
        )
        d = recs[0].to_dict()
        for key in (
            "recommendation_id", "strategy", "suggestion_profile",
            "current_config", "suggested_config", "reason",
            "evidence", "risk_note", "expected_impact", "regime",
            "needs_backtest", "needs_walk_forward",
            "needs_human_approval", "status", "created_at",
        ):
            assert key in d, key
        assert d["needs_human_approval"] is True
        assert d["status"] == "suggested"

    def test_overfitting_flag_propagated(self):
        report = {
            **_REPORT,
            "long": {
                **_REPORT["long"],
                "performance": {
                    **_REPORT["long"]["performance"],
                    "overfitting_warning": True,
                },
            },
        }
        recs = build_recommendations(
            advisor_report=report, regime={"regime": "ranging"},
            current_config=_CURRENT_CONFIG, now=_NOW,
        )
        assert all(r.overfitting_flag for r in recs)


class TestRecommendationLifecycle:

    def _store_with_recs(self, tmp_path, overfit=False):
        report = _REPORT if not overfit else {
            **_REPORT,
            "long": {
                **_REPORT["long"],
                "performance": {
                    **_REPORT["long"]["performance"],
                    "overfitting_warning": True,
                },
            },
        }
        recs = build_recommendations(
            advisor_report=report, regime={"regime": "ranging"},
            current_config=_CURRENT_CONFIG, now=_NOW,
        )
        store = RecommendationStore(str(tmp_path / "recs.json"))
        store.save(recs)
        return store, recs

    def test_accept_requires_cap_no_default(self, tmp_path):
        store, recs = self._store_with_recs(tmp_path)
        ok, why = store.accept(
            recs[0].recommendation_id,
            operator_token="op_test",
            max_change_pct=None,        # Q9 sem resposta => bloqueia
            backtest_validated=True, walk_forward_validated=True,
        )
        assert not ok
        assert "blocked_missing_limits" in why

    def test_accept_requires_backtest_and_walk_forward(self, tmp_path):
        store, recs = self._store_with_recs(tmp_path)
        ok, why = store.accept(
            recs[0].recommendation_id, operator_token="op_test",
            max_change_pct=50.0,        # FIXTURE DE TESTE
            backtest_validated=False, walk_forward_validated=True,
        )
        assert not ok and "backtest" in why
        ok2, why2 = store.accept(
            recs[0].recommendation_id, operator_token="op_test",
            max_change_pct=50.0,
            backtest_validated=True, walk_forward_validated=False,
        )
        assert not ok2 and "walk-forward" in why2

    def test_accept_enforces_change_cap(self, tmp_path):
        store, recs = self._store_with_recs(tmp_path)
        arrojado = next(
            r for r in recs if r.suggestion_profile == "arrojado"
        )
        # EMA 20->9 = 55% de mudanca > cap 10% (FIXTURE) => bloqueia.
        ok, why = store.accept(
            arrojado.recommendation_id, operator_token="op_test",
            max_change_pct=10.0,
            backtest_validated=True, walk_forward_validated=True,
        )
        assert not ok
        assert "cap" in why

    def test_accept_happy_path_audited_not_applied(self, tmp_path):
        store, recs = self._store_with_recs(tmp_path)
        cons = next(
            r for r in recs
            if r.suggestion_profile == "conservador"
        )
        ok, why = store.accept(
            cons.recommendation_id, operator_token="op_test",
            max_change_pct=50.0,   # FIXTURE DE TESTE
            backtest_validated=True, walk_forward_validated=True,
            now=_NOW,
        )
        assert ok, why
        assert "NAO aplicado automaticamente" in why
        rec = store.get(cons.recommendation_id)
        assert rec["status"] == "accepted"
        assert rec["accepted_by"] == "op_test"
        trail = store.audit_trail
        assert trail[-1]["action"] == "accept"
        assert trail[-1]["old_config"] == dict(_CURRENT_CONFIG)
        # Config corrente do projeto NAO foi alterada.
        from crypto_trading_bot.strategies \
            .trend_pullback_bidirectional_strategy import (
                build_trend_pullback_bidirectional_spec,
            )
        spec_cfg = dict(
            build_trend_pullback_bidirectional_spec().default_config,
        )
        assert spec_cfg["ema_fast_period"] == 20  # intacto

    def test_overfitting_ineligible(self, tmp_path):
        store, recs = self._store_with_recs(tmp_path, overfit=True)
        ok, why = store.accept(
            recs[0].recommendation_id, operator_token="op_test",
            max_change_pct=50.0,
            backtest_validated=True, walk_forward_validated=True,
        )
        assert not ok
        assert "INELEGIVEL" in why

    def test_reject_and_expire(self, tmp_path):
        store, recs = self._store_with_recs(tmp_path)
        assert store.reject(
            recs[0].recommendation_id, operator_token="op_test",
            reason="nao desejado",
        )
        assert store.get(
            recs[0].recommendation_id,
        )["status"] == "rejected"
        expired = store.expire_old(
            max_age_days=7, now=_NOW + timedelta(days=30),
        )
        assert expired >= 1
        assert all(
            r["status"] in ("rejected", "expired")
            for r in store.list_all()
        )

    def test_double_accept_blocked(self, tmp_path):
        store, recs = self._store_with_recs(tmp_path)
        cons = next(
            r for r in recs
            if r.suggestion_profile == "conservador"
        )
        store.accept(
            cons.recommendation_id, operator_token="op",
            max_change_pct=50.0, backtest_validated=True,
            walk_forward_validated=True,
        )
        ok, why = store.accept(
            cons.recommendation_id, operator_token="op",
            max_change_pct=50.0, backtest_validated=True,
            walk_forward_validated=True,
        )
        assert not ok and "accepted" in why
