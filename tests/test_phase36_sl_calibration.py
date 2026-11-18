"""
Tests - FASE 36 pos-demo 3: SL calibration advisor (offline)
=============================================================
100% offline. Candles sinteticos (seed fixa p/ determinismo).
NUNCA baixa o piso; NUNCA chama rede/ordem.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from crypto_trading_bot.research.sl_calibration import (
    analyze_sl_calibration,
)

_REPO_ROOT = Path(__file__).parent.parent


def _candles(*, vol, n=400, trend=0.0004):
    # Seed fixa: determinismo independente da ordem de coleta.
    random.seed(36003)
    from crypto_trading_bot.backtesting.backtest_data import (
        generate_trending_candles,
    )
    return generate_trending_candles(
        n=n, base_price=65000.0, trend_pct_per_candle=trend,
        volatility_pct=vol, symbol="BTCUSDT", timeframe="15",
    )


class TestAnalyzer:

    def test_low_vol_reproduces_rejection_then_clears(self):
        report = analyze_sl_calibration(
            candles=_candles(vol=0.0024), data_source="synthetic_low_vol",
            run_backtests=False,
        )
        assert report["status"] == "ok"
        stats = {s["stop_atr_multiplier"]: s
                 for s in report["sl_stats_by_multiplier"]}
        # Regime baixo: mult 1.5 rejeita mais que mult 2.0.
        assert stats[1.5]["rejection_pct"] >= stats[2.0]["rejection_pct"]
        # Em baixa vol mult 1.5 fica abaixo do piso (rejeicao alta).
        assert stats[1.5]["rejection_pct"] > 0
        # Multiplicador implicito p/ cruzar piso eh > 1.
        assert report["implied_multiplier_to_clear_floor"] > 1.0
        assert report["min_sl_pct_required"] == pytest.approx(0.5)

    def test_high_vol_low_rejection(self):
        report = analyze_sl_calibration(
            candles=_candles(vol=0.012), data_source="synthetic",
            run_backtests=False,
        )
        stats = {s["stop_atr_multiplier"]: s
                 for s in report["sl_stats_by_multiplier"]}
        # Alta vol: mult 1.5 cruza o piso (rejeicao baixa/zero).
        assert stats[1.5]["rejection_pct"] == 0.0

    def test_three_profiles_plus_safest(self):
        report = analyze_sl_calibration(
            candles=_candles(vol=0.0024), run_backtests=False,
        )
        profiles = [r["profile"] for r in report["recommendations"]]
        assert "conservador" in profiles
        assert "moderado" in profiles
        assert "arrojado" in profiles
        assert "_safest_for_next_demo" in profiles
        for r in report["recommendations"]:
            assert r["needs_backtest"] is True
            assert r["needs_walk_forward"] is True

    def test_synthetic_warning_present(self):
        report = analyze_sl_calibration(
            candles=_candles(vol=0.0024), data_source="synthetic_low_vol",
            run_backtests=False,
        )
        assert report["synthetic_warning"] is not None
        assert "walk-forward" in report["synthetic_warning"].lower()

    def test_csv_source_no_synthetic_warning(self):
        report = analyze_sl_calibration(
            candles=_candles(vol=0.0024),
            data_source="csv:reports/real.csv", run_backtests=False,
        )
        assert report["synthetic_warning"] is None

    def test_planner_clamp_in_low_vol(self):
        report = analyze_sl_calibration(
            candles=_candles(vol=0.0024), run_backtests=False,
        )
        # Em baixa vol, o planner clampa varios candles ao piso.
        assert report["planner_clamp_count"] > 0
        planner = report["planner_at_median_atr"]
        assert planner["clamped_to_floor"] is True
        assert planner["sl_pct"] == pytest.approx(0.5, abs=0.001)

    def test_budget_check_skipped_when_no_operator_input(self):
        report = analyze_sl_calibration(
            candles=_candles(vol=0.0024), run_backtests=False,
            max_risk_per_trade_usd=None,
        )
        assert "skipped" in report["budget_check"]
        assert report["planner_sizing_reduction_needed"] == 0

    def test_budget_check_applied_when_provided(self):
        # Teto minusculo (FIXTURE) -> planner sinaliza reducao de
        # sizing necessaria; NUNCA altera sizing escondido.
        report = analyze_sl_calibration(
            candles=_candles(vol=0.0024), run_backtests=False,
            max_risk_per_trade_usd=0.5, position_size_usd=200.0,
        )
        assert report["budget_check"] == "applied"
        # piso 0.5% * 200 = 1.0 USD > 0.5 -> reducao necessaria.
        assert report["planner_sizing_reduction_needed"] > 0
        assert report["planner_at_median_atr"]["within_risk_budget"] \
            is False

    def test_never_lowers_floor_note(self):
        report = analyze_sl_calibration(
            candles=_candles(vol=0.0024), run_backtests=False,
        )
        assert "NAO baixa o piso" in report["note"]

    def test_insufficient_data(self):
        report = analyze_sl_calibration(
            candles=_candles(vol=0.0024, n=120)[:25],
            run_backtests=False, min_candles=60,
        )
        assert report["status"] == "insufficient_data"
        assert "API" in report["message"]

    def test_backtests_labeled_mechanism(self):
        report = analyze_sl_calibration(
            candles=_candles(vol=0.0024), run_backtests=True,
        )
        bt = report["backtests_mechanism_only"]
        assert "current_1.5" in bt
        assert "strategy_floor_1.5" in bt
        assert "mult_2.0" in bt
        # Cada variante tem as metricas obrigatorias (ou erro).
        for key, val in bt.items():
            if "error" not in val:
                for m in ("total_trades", "win_rate",
                          "total_pnl_usd", "max_drawdown_pct"):
                    assert m in val


class TestCLISourceGuards:

    def _src(self):
        return (
            _REPO_ROOT / "scripts" / "run_sl_calibration_advisor.py"
        ).read_text(encoding="utf-8")

    def test_no_network_no_dotenv_no_order(self):
        src = self._src()
        assert "load_dotenv" not in src
        assert "import httpx" not in src
        assert "requests" not in src
        assert "submit_order" not in src
        assert "place_order" not in src

    def test_no_api_fetch_message(self):
        src = self._src()
        # Recusa explicita de buscar dado por API quando csv ausente.
        assert "Nenhuma busca por API" in src

    def test_offline_run_smoke(self, tmp_path):
        import subprocess
        import sys
        out = tmp_path / "calib.json"
        r = subprocess.run(
            [sys.executable,
             str(_REPO_ROOT / "scripts"
                 / "run_sl_calibration_advisor.py"),
             "--synthetic", "--low-vol", "--output", str(out)],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
            timeout=240, check=False,
        )
        assert r.returncode == 0, r.stdout[-1500:]
        import json
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["status"] == "ok"
        assert data["synthetic_warning"] is not None
