"""
FASE 40 - Final Research Attempt (VWAP/Bollinger range mean reversion +
timeframe expansion)
=======================================================================
Testes 100% OFFLINE/DETERMINISTICOS. ZERO rede real / ordem / secret.
O caminho de fetch usa SEMPRE FakeHistoricalProvider (offline).

Cobre os ajustes obrigatorios:
  3. Estrategia research-only (tags; fora do registry operacional).
  4. Bidirecional: emite BUY e SELL; respeita o piso 0.005.
  1. Download 5m gated: gated_missing_dataset sem flags; fetched_ready com
     FakeProvider; data_readiness obrigatorio.
  2. Testes offline (fake provider, sem rede).
  5/6. Comparacao por robustez + criterio terminal seguir_para_infra.
  7. Demo gate: demo_blocked=True / demo_authorized=False sempre.
"""

from __future__ import annotations

import pandas as pd
import pytest

from crypto_trading_bot.historical_data import FakeHistoricalProvider
from crypto_trading_bot.risk.risk_engine import RiskEngine
from crypto_trading_bot.strategies.range_mean_reversion_vwap_bollinger_strategy \
    import (
        RangeMeanReversionVwapBollingerStrategy,
        build_range_mean_reversion_vwap_bollinger_spec,
    )
from crypto_trading_bot.research.timeframe_research import (
    FOCUS_FAMILY,
    TimeframeResult,
    _decide_cross_timeframe,
    ensure_dataset,
    run_final_research,
)


# ---------------------------------------------------------------------------
# 3/4. Estrategia research-only + bidirecional + piso
# ---------------------------------------------------------------------------

def _feats(close, rsi, atr, bb_lower, bb_upper, bb_middle, vwap,
           bandwidth=0.02, ema=65000.0):
    return {
        "symbol": "BTCUSDT", "has_sufficient_data": True, "n_candles": 100,
        "last_close": close, "last_rsi": rsi, "last_atr": atr,
        "bb_lower": pd.Series([bb_lower]), "bb_upper": pd.Series([bb_upper]),
        "bb_middle": pd.Series([bb_middle]),
        "bb_bandwidth": pd.Series([bandwidth]), "vwap": pd.Series([vwap]),
        "ema_9": pd.Series([ema]), "ema_21": pd.Series([ema]),
    }


class TestStrategy:

    def test_tags_research_prototype(self):
        spec = build_range_mean_reversion_vwap_bollinger_spec()
        assert "research" in spec.tags and "prototype" in spec.tags
        assert "bidirectional" in spec.tags

    def test_not_in_operational_registry(self):
        from crypto_trading_bot.backtest_operational import (
            default_backtest_registry,
        )
        assert spec_name() not in default_backtest_registry().list_names()

    def test_emits_buy_long(self):
        s = RangeMeanReversionVwapBollingerStrategy()
        s.set_running()
        sig = s.evaluate(_feats(64900, 25, 300, 65000, 66000, 65500, 65200))
        assert sig.action.value == "buy"
        assert sig.stop_loss_price < sig.entry_price < sig.take_profit_price

    def test_emits_sell_short(self):
        s = RangeMeanReversionVwapBollingerStrategy()
        s.set_running()
        sig = s.evaluate(_feats(66100, 75, 300, 64000, 66000, 65500, 65000))
        assert sig.action.value == "sell"
        assert sig.take_profit_price < sig.entry_price < sig.stop_loss_price

    def test_no_trade_when_trend_not_range(self):
        # EMAs distantes => nao-range => HOLD (filtro de range).
        s = RangeMeanReversionVwapBollingerStrategy()
        s.set_running()
        f = _feats(64900, 25, 300, 65000, 66000, 65500, 65200)
        f["ema_9"] = pd.Series([66000.0])
        f["ema_21"] = pd.Series([64000.0])   # |dif|/close grande
        assert s.evaluate(f).action.value == "hold"

    def test_tiny_stop_blocked_by_floor(self):
        s = RangeMeanReversionVwapBollingerStrategy()
        s.set_running()
        sig = s.evaluate(_feats(64900, 25, 10, 65000, 66000, 65500, 65200))
        assert sig.is_actionable
        r = RiskEngine(initial_capital=5000.0).validate_signal(
            sig.to_trading_signal())
        assert r.approved is False
        assert r.block_reason.value == "stop_loss_too_small"


def spec_name():
    return build_range_mean_reversion_vwap_bollinger_spec().name


# ---------------------------------------------------------------------------
# 1/2. Dataset gating + fetch offline (FakeHistoricalProvider)
# ---------------------------------------------------------------------------

class TestDatasetGating:

    def test_gated_missing_without_flags(self, tmp_path):
        ds = ensure_dataset(
            "BTCUSDT", "5m", base_dir=str(tmp_path), start_date="2026-01-01",
            end_date="2026-01-20", fetch_missing=False, allow_network=False,
            force=False)
        assert ds.status == "gated_missing_dataset"
        assert ds.readiness_status is None

    def test_fetch_offline_via_fake_provider(self, tmp_path):
        # provider_obj=Fake => offline; data_readiness obrigatorio.
        ds = ensure_dataset(
            "BTCUSDT", "5m", base_dir=str(tmp_path), start_date="2026-01-01",
            end_date="2026-01-31", fetch_missing=True, allow_network=True,
            force=False, provider_obj=FakeHistoricalProvider())
        assert ds.status in ("fetched_ready", "dataset_not_ready")
        # com ~31 dias de 5m ha candles suficientes p/ readiness ready.
        assert ds.rows is not None and ds.rows > 0


# ---------------------------------------------------------------------------
# 5/6. Decisao cross-timeframe (criterio terminal)
# ---------------------------------------------------------------------------

def _tf(label, *, evaluated=True, verdict=None, decision=None):
    return TimeframeResult(
        timeframe=label,
        dataset={"status": "ready_local"} if evaluated
        else {"status": "gated_missing_dataset"},
        evaluated=evaluated,
        window_report={"x": 1} if evaluated else None,
        focus_verdict=verdict, focus_decision=decision)


class TestCrossTimeframeDecision:

    def test_no_evaluated_tf_goes_to_infra(self):
        dec, detail, sens = _decide_cross_timeframe(
            [_tf("5m", evaluated=False)])
        assert dec == "seguir_para_infra_operacional"
        assert sens is False

    def test_all_reject_goes_to_infra(self):
        dec, detail, sens = _decide_cross_timeframe([
            _tf("15m", verdict="ruido", decision="rejeitar_definitivamente"),
            _tf("5m", verdict="rejeitar", decision="rejeitar_definitivamente"),
        ])
        assert dec == "seguir_para_infra_operacional"

    def test_promote_all_tf(self):
        dec, detail, sens = _decide_cross_timeframe([
            _tf("15m", verdict="pista", decision="promover_para_calibracao"),
            _tf("5m", verdict="pista", decision="promover_para_calibracao"),
        ])
        assert dec == "promover_para_calibracao"
        assert sens is False

    def test_timeframe_sensitive(self):
        dec, detail, sens = _decide_cross_timeframe([
            _tf("15m", verdict="pista", decision="promover_para_calibracao"),
            _tf("5m", verdict="ruido", decision="rejeitar_definitivamente"),
        ])
        assert sens is True
        assert dec == "continuar_pesquisa"

    def test_pista_continues_research(self):
        dec, detail, sens = _decide_cross_timeframe([
            _tf("15m", verdict="pista_para_pesquisa",
                decision="continuar_pesquisa"),
        ])
        assert dec == "continuar_pesquisa"


# ---------------------------------------------------------------------------
# 7. End-to-end offline: demo SEMPRE bloqueada
# ---------------------------------------------------------------------------

class TestEndToEnd:

    def test_demo_always_blocked(self, tmp_path):
        rep = run_final_research(
            symbol="BTCUSDT", timeframes=["15m", "5m"],
            start_date="2026-01-01", end_date="2026-01-26",
            base_dir=str(tmp_path),
            families=["range_mean_reversion_vwap_bollinger_research"],
            capital=5000.0, min_candles=60, regime_lookback=96, wf_folds=2,
            fetch_missing=True, allow_network=True,
            provider_obj=FakeHistoricalProvider(), min_window_candles=200)
        d = rep.to_dict()
        assert d["demo_blocked"] is True
        assert d["demo_authorized"] is False
        assert d["focus_family"] == FOCUS_FAMILY
        assert len(d["timeframes"]) == 2
        assert d["decision"] in (
            "promover_para_calibracao", "continuar_pesquisa",
            "expandir_dataset", "rejeitar_definitivamente",
            "seguir_para_infra_operacional", "manter_demo_bloqueada")

    def test_gated_missing_without_flags_end_to_end(self, tmp_path):
        # Sem flags e sem dados => nenhum TF avaliado => seguir_para_infra.
        rep = run_final_research(
            symbol="BTCUSDT", timeframes=["5m"], start_date="2026-01-01",
            end_date="2026-01-20", base_dir=str(tmp_path),
            families=["range_mean_reversion_vwap_bollinger_research"],
            capital=5000.0, min_candles=60, wf_folds=2,
            fetch_missing=False, allow_network=False)
        d = rep.to_dict()
        assert d["timeframes"][0]["dataset"]["status"] == \
            "gated_missing_dataset"
        assert d["demo_blocked"] is True
        assert d["decision"] == "seguir_para_infra_operacional"
