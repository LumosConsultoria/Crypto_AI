"""
FASE 37.1 - Backtest Progress + Interrupt Handling + Performance Guard
======================================================================
Testes 100% OFFLINE. ZERO rede / ordem / secret.

Cobre:
  * compute_indexed (precompute O(n)) IDENTICO ao compute por janela.
  * BacktestEngine.run com precompute_features produz relatorio
    BIT-IDENTICO ao caminho legado (nao altera logica/resultado de trade).
  * progress_callback emite heartbeat; default-off preserva legado.
  * KeyboardInterrupt -> relatorio PARCIAL (trades fechados) sem traceback.
  * CLI run_strategy_backtest: heartbeat, --no-precompute, --max-candles.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

from crypto_trading_bot.backtesting import BacktestEngine
from crypto_trading_bot.backtesting.backtest_data import (
    generate_ranging_candles,
    generate_trending_candles,
    generate_volatile_candles,
)
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.risk.risk_engine import RiskEngine
from crypto_trading_bot.strategies.trend_pullback_strategy import (
    build_trend_pullback_spec,
)
from crypto_trading_bot.strategies.volatility_breakout_strategy import (
    build_volatility_breakout_spec,
)
from crypto_trading_bot.strategies\
    .trend_pullback_bidirectional_strategy import (
        build_trend_pullback_bidirectional_spec,
    )


def _mk_engine(spec_builder, candles, capital=5000.0):
    spec = spec_builder()
    return BacktestEngine(
        strategy=spec.factory(dict(spec.default_config)),
        risk_engine=RiskEngine(initial_capital=capital),
        feature_engine=FeatureEngine(),
        initial_capital=capital, min_candles=60, symbol="BTCUSDT",
    )


def _report_fingerprint(rep):
    trades = [
        (t.side, round(t.entry_price, 6),
         round(t.exit_price, 6) if t.exit_price is not None else None,
         round(t.pnl_usd, 6) if t.pnl_usd is not None else None,
         t.close_reason.value if t.close_reason is not None else None)
        for t in rep.trades
    ]
    return {
        "total_trades": rep.total_trades,
        "winning": rep.winning_trades,
        "losing": rep.losing_trades,
        "pnl": round(rep.total_pnl_usd, 6),
        "blocked": rep.risk_blocked_count,
        "max_dd": round(rep.max_drawdown_pct, 6),
        "final_capital": round(rep.final_capital, 6),
        "win_rate": rep.win_rate,
        "expectancy": round(rep.expectancy_usd, 6),
        "equity": [round(x, 4) for x in rep.equity_curve],
        "trades": trades,
    }


_GENS = {
    "trend": lambda: generate_trending_candles(
        n=400, base_price=65000.0, trend_pct_per_candle=0.0008,
        volatility_pct=0.012, symbol="BTCUSDT", timeframe="15"),
    "vol": lambda: generate_volatile_candles(
        400, symbol="BTCUSDT", timeframe="15"),
    "range": lambda: generate_ranging_candles(
        400, symbol="BTCUSDT", timeframe="15"),
}
_SPECS = {
    "trend_pullback": build_trend_pullback_spec,
    "volatility_breakout": build_volatility_breakout_spec,
    "bidirectional": build_trend_pullback_bidirectional_spec,
}


# ---------------------------------------------------------------------------
# FeatureEngine.compute_indexed identidade
# ---------------------------------------------------------------------------

class TestComputeIndexed:

    def test_indexed_identical_to_window_compute(self):
        fe = FeatureEngine()
        candles = _GENS["trend"]()
        idx = fe.compute_indexed(candles)
        for i in range(60, len(candles), 11):
            a = fe.compute(candles[:i + 1])
            b = idx.at(i)
            for k in ("last_close", "last_rsi", "last_atr", "last_ema_9",
                      "last_vwap", "last_obv", "n_candles",
                      "has_sufficient_data", "symbol"):
                va, vb = a[k], b[k]
                if isinstance(va, float) and math.isnan(va):
                    assert isinstance(vb, float) and math.isnan(vb)
                else:
                    assert va == vb, (k, va, vb)
            # ultimo valor das series tambem identico
            for sk in ("ema_20", "ema_50", "rsi_14", "atr_14", "closes"):
                if sk in a and sk in b and len(a[sk]) and len(b[sk]):
                    la, lb = float(a[sk].iloc[-1]), float(b[sk].iloc[-1])
                    assert (math.isnan(la) and math.isnan(lb)) or la == lb

    def test_indexed_empty_candles(self):
        fe = FeatureEngine()
        idx = fe.compute_indexed([])
        out = idx.at(0)
        assert out["has_sufficient_data"] is False


# ---------------------------------------------------------------------------
# Equivalencia precompute vs legado (NAO altera resultado de trade)
# ---------------------------------------------------------------------------

class TestPrecomputeEquivalence:

    @pytest.mark.parametrize("gen", list(_GENS))
    @pytest.mark.parametrize("strat", list(_SPECS))
    def test_report_identical(self, gen, strat):
        candles = _GENS[gen]()
        legacy = _report_fingerprint(
            _mk_engine(_SPECS[strat], candles).run(candles))
        pre = _report_fingerprint(
            _mk_engine(_SPECS[strat], candles).run(
                candles, precompute_features=True))
        assert legacy == pre, f"{strat}/{gen} divergiu"

    def test_trades_present_case_identical(self):
        # 'range' + trend_pullback gera trade(s): cobre identidade COM trade.
        candles = generate_ranging_candles(
            500, symbol="BTCUSDT", timeframe="15")
        legacy = _report_fingerprint(
            _mk_engine(build_trend_pullback_spec, candles).run(candles))
        pre = _report_fingerprint(
            _mk_engine(build_trend_pullback_spec, candles).run(
                candles, precompute_features=True))
        assert legacy == pre


# ---------------------------------------------------------------------------
# Progress callback
# ---------------------------------------------------------------------------

class TestProgressCallback:

    def test_fires_with_expected_keys(self):
        candles = _GENS["trend"]()
        ticks = []
        _mk_engine(build_trend_pullback_spec, candles).run(
            candles, progress_every=50,
            progress_callback=lambda d: ticks.append(d))
        assert ticks
        for d in ticks:
            assert {"i", "n", "trades", "blocked", "timestamp"} <= set(d)
        assert ticks[-1]["i"] == len(candles) - 1  # ultimo candle emitido
        assert all(
            ticks[k]["i"] < ticks[k + 1]["i"]
            for k in range(len(ticks) - 1))

    def test_default_off_no_calls(self):
        candles = _GENS["trend"]()
        ticks = []
        _mk_engine(build_trend_pullback_spec, candles).run(
            candles, progress_callback=lambda d: ticks.append(d))
        assert ticks == []   # progress_every=0 default => nunca chama

    def test_callback_exception_is_swallowed(self):
        candles = _GENS["trend"]()

        def boom(d):
            raise RuntimeError("ui error")

        # callback quebrado nao derruba o backtest.
        rep = _mk_engine(build_trend_pullback_spec, candles).run(
            candles, progress_every=50, progress_callback=boom)
        assert rep.n_candles_total == len(candles)


# ---------------------------------------------------------------------------
# KeyboardInterrupt -> relatorio parcial
# ---------------------------------------------------------------------------

class TestInterruptPartial:

    def test_partial_report_via_runner(self):
        from crypto_trading_bot.backtest_operational import (
            BacktestExecutionContext, run_operational_backtest,
        )
        candles = generate_ranging_candles(
            500, symbol="BTCUSDT", timeframe="15")
        ctx = BacktestExecutionContext(
            strategy="trend_pullback", capital_usd=200.0)

        def boom(d):
            if d["i"] >= 200:
                raise KeyboardInterrupt()

        rep = run_operational_backtest(
            ctx, candles, symbol="BTCUSDT", timeframe="15m",
            source_type="synthetic_fake", precompute_features=True,
            backtest_progress_every=25, on_backtest_progress=boom)
        d = rep.to_dict()
        assert d["partial"] is True and d["interrupted"] is True
        assert d["candles_processed"] is not None
        assert d["candles_processed"] <= len(candles)
        assert any("INTERROMPIDO" in w for w in d["warnings"])

    def test_build_partial_report_closed_only(self):
        candles = generate_ranging_candles(
            500, symbol="BTCUSDT", timeframe="15")
        engine = _mk_engine(build_trend_pullback_spec, candles)

        def boom(d):
            if d["i"] >= 150:
                raise KeyboardInterrupt()

        with pytest.raises(KeyboardInterrupt):
            engine.run(candles, progress_every=10, progress_callback=boom)
        partial = engine.build_partial_report()
        assert engine.last_run_interrupted is True
        # so trades fechados aparecem no parcial.
        assert all(not t.is_open for t in partial.trades)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_SCRIPTS = Path(__file__).parent.parent / "scripts"


def _load_script(name):
    spec = importlib.util.spec_from_file_location(
        f"_f371_{name}", _SCRIPTS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_csv(tmp_path):
    from crypto_trading_bot.historical_data import (
        fetch_historical, FakeHistoricalProvider,
    )
    fetch_historical(
        provider="fake", symbol="BTCUSDT", timeframe="15m",
        start_date="2026-01-01", end_date="2026-01-08",
        base_dir=str(tmp_path / "h"),
        provider_obj=FakeHistoricalProvider())
    return tmp_path / "h" / "BTCUSDT" / "15m" / "BTCUSDT_15m.csv"


class TestCli:

    def test_heartbeat_and_default_precompute(self, tmp_path, capsys):
        csv = _make_csv(tmp_path)
        mod = _load_script("run_strategy_backtest.py")
        rc = mod.main([
            "--from-csv", str(csv), "--symbol", "BTCUSDT",
            "--timeframe", "15m", "--strategy", "trend_pullback",
            "--capital", "200", "--progress-every", "200",
        ])
        out = capsys.readouterr().out
        assert rc == 0
        assert "precompute-features: ON" in out
        assert "candle" in out and "ETA" in out

    def test_no_precompute_flag(self, tmp_path, capsys):
        csv = _make_csv(tmp_path)
        mod = _load_script("run_strategy_backtest.py")
        rc = mod.main([
            "--from-csv", str(csv), "--symbol", "BTCUSDT",
            "--timeframe", "15m", "--strategy", "trend_pullback",
            "--capital", "200", "--no-precompute",
        ])
        out = capsys.readouterr().out
        assert rc == 0
        assert "precompute-features: OFF" in out

    def test_max_candles_slices(self, tmp_path, capsys):
        csv = _make_csv(tmp_path)
        mod = _load_script("run_strategy_backtest.py")
        rc = mod.main([
            "--from-csv", str(csv), "--symbol", "BTCUSDT",
            "--timeframe", "15m", "--strategy", "trend_pullback",
            "--capital", "200", "--max-candles", "100",
        ])
        out = capsys.readouterr().out
        assert rc == 0
        assert "recorte --max-candles" in out

    def test_from_csv_respects_date_range(self, tmp_path):
        # CSV largo (2026-01-01..2026-03-01) executado com recorte menor
        # (2026-02-01..2026-02-14): rows/first/last devem refletir o range.
        import json as _json

        from crypto_trading_bot.historical_data import (
            fetch_historical, FakeHistoricalProvider,
        )
        fetch_historical(
            provider="fake", symbol="BTCUSDT", timeframe="15m",
            start_date="2026-01-01", end_date="2026-03-01",
            base_dir=str(tmp_path / "h"),
            provider_obj=FakeHistoricalProvider())
        csv = tmp_path / "h" / "BTCUSDT" / "15m" / "BTCUSDT_15m.csv"
        out = tmp_path / "bt.json"
        mod = _load_script("run_strategy_backtest.py")
        rc = mod.main([
            "--from-csv", str(csv), "--symbol", "BTCUSDT",
            "--timeframe", "15m", "--strategy", "trend_pullback",
            "--capital", "200",
            "--start-date", "2026-02-01", "--end-date", "2026-02-14",
            "--output", str(out),
        ])
        assert rc == 0
        d = _json.loads(out.read_text(encoding="utf-8"))
        # 14 dias * 96 candles/dia (end date-only = dia inteiro inclusivo).
        assert d["rows"] == 14 * 96
        assert d["first_timestamp"] == "2026-02-01T00:00:00Z"
        assert d["last_timestamp"] == "2026-02-14T23:45:00Z"

    def test_from_csv_empty_range_is_error(self, tmp_path):
        csv = _make_csv(tmp_path)  # cobre 2026-01-01..2026-01-08
        mod = _load_script("run_strategy_backtest.py")
        rc = mod.main([
            "--from-csv", str(csv), "--symbol", "BTCUSDT",
            "--timeframe", "15m", "--strategy", "trend_pullback",
            "--capital", "200",
            "--start-date", "2027-01-01", "--end-date", "2027-02-01",
        ])
        assert rc == 1   # nenhum candle no range -> erro claro, sem crash
