"""
FASE 37 - Historical Data Fetcher + Backtest Operational Parity
================================================================
Testes 100% OFFLINE. ZERO rede, ZERO ordem, ZERO secret.
O provider REAL (binance) NUNCA eh chamado: usa-se sempre o
FakeHistoricalProvider deterministico. Cobre: providers, fetcher,
execution context, context availability (anti look-ahead), strategy
registry, runner operacional, report, advisor SL (perf) e ViewModels UI.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest

from crypto_trading_bot.historical_data import (
    FakeHistoricalProvider,
    HistoricalDataError,
    fetch_historical,
    get_provider,
    normalize_timeframe,
    validate_fetch_request,
)
from crypto_trading_bot.historical_data.providers import (
    BinancePublicProvider,
    CandleRow,
)


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class TestProviders:

    def test_normalize_timeframe_label_and_digits(self):
        assert normalize_timeframe("15m") == ("15m", 15)
        assert normalize_timeframe("15") == ("15m", 15)
        assert normalize_timeframe("1h") == ("1h", 60)

    def test_normalize_timeframe_invalid(self):
        with pytest.raises(HistoricalDataError):
            normalize_timeframe("7s")

    def test_validate_fetch_request_ok(self):
        tf, mins, start, end = validate_fetch_request(
            symbol="btcusdt", timeframe="15m",
            start_date="2026-01-01", end_date="2026-01-02",
        )
        assert tf == "15m" and mins == 15
        assert start < end and start.tzinfo is timezone.utc

    def test_validate_fetch_request_end_before_start(self):
        with pytest.raises(HistoricalDataError):
            validate_fetch_request(
                symbol="BTCUSDT", timeframe="15m",
                start_date="2026-01-03", end_date="2026-01-01",
            )

    def test_validate_fetch_request_empty_symbol(self):
        with pytest.raises(HistoricalDataError):
            validate_fetch_request(
                symbol="  ", timeframe="15m",
                start_date="2026-01-01", end_date="2026-01-02",
            )

    def test_validate_fetch_request_symbol_not_allowed(self):
        with pytest.raises(HistoricalDataError):
            validate_fetch_request(
                symbol="DOGEUSDT", timeframe="15m",
                start_date="2026-01-01", end_date="2026-01-02",
                allowed_symbols=("BTCUSDT",),
            )

    def test_get_provider_fake_and_binance(self):
        assert get_provider("fake").is_real is False
        b = get_provider("binance")
        assert isinstance(b, BinancePublicProvider) and b.is_real is True

    def test_get_provider_bybit_linear(self):
        # FASE 46: bybit linear (mercado-alvo) agora E provider real.
        from crypto_trading_bot.historical_data.providers import (
            BybitLinearPublicProvider,
        )
        b = get_provider("bybit")
        assert isinstance(b, BybitLinearPublicProvider) and b.is_real is True
        assert get_provider("bybit_linear").is_real is True

    def test_get_provider_unknown(self):
        with pytest.raises(HistoricalDataError):
            get_provider("nope")

    def test_fake_provider_deterministic(self):
        p = FakeHistoricalProvider()
        a = p.fetch_candles(
            symbol="BTCUSDT", tf_minutes=15,
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end=datetime(2026, 1, 1, 6, tzinfo=timezone.utc),
        )
        b = p.fetch_candles(
            symbol="BTCUSDT", tf_minutes=15,
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end=datetime(2026, 1, 1, 6, tzinfo=timezone.utc),
        )
        assert len(a) == 24
        assert [c.close for c in a] == [c.close for c in b]

    def test_fake_provider_pagination_large(self):
        # > 1000 candles exercita o ponto de paginacao logico.
        p = FakeHistoricalProvider()
        rows = p.fetch_candles(
            symbol="BTCUSDT", tf_minutes=1,
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end=datetime(2026, 1, 1, 20, tzinfo=timezone.utc),
        )
        assert len(rows) == 1200
        assert all(rows[i].timestamp < rows[i + 1].timestamp
                   for i in range(len(rows) - 1))

    def test_candle_row_to_csv_dict_utc(self):
        cr = CandleRow(
            timestamp=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
            open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0,
        )
        d = cr.to_csv_dict()
        assert d["timestamp"] == "2026-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

class TestFetcher:

    def _fetch(self, tmp_path, **kw):
        return fetch_historical(
            provider="fake", symbol="BTCUSDT", timeframe="15m",
            start_date="2026-01-01", end_date="2026-01-02",
            base_dir=str(tmp_path / "h"),
            provider_obj=FakeHistoricalProvider(), **kw,
        )

    def test_fetch_success_and_metadata(self, tmp_path):
        r = self._fetch(tmp_path)
        assert r.rows_saved == 96 and r.rows_downloaded == 96
        meta = json.loads(
            (tmp_path / "h" / "BTCUSDT" / "15m" / "metadata.json")
            .read_text(encoding="utf-8"))
        assert meta["checksum_sha256"] == r.checksum
        assert meta["canonical_schema_version"]
        assert meta["source_type"] == "synthetic_fake"
        assert meta["rows"] == 96

    def test_fetch_checksum_matches_file_no_blank_lines(self, tmp_path):
        r = self._fetch(tmp_path)
        raw = open(r.dataset_path, "rb").read()
        assert hashlib.sha256(raw).hexdigest() == r.checksum
        lines = open(r.dataset_path, encoding="utf-8").read().splitlines()
        assert "" not in lines
        assert lines[0] == "timestamp,open,high,low,close,volume"

    def test_dry_run_writes_nothing(self, tmp_path):
        r = self._fetch(tmp_path, dry_run=True)
        assert r.rows_saved == 0 and r.rows_downloaded == 96
        assert not (tmp_path / "h").exists()

    def test_validate_only(self, tmp_path):
        r = self._fetch(tmp_path, validate_only=True)
        assert r.validate_only and r.rows_downloaded == 0

    def test_overwrite_guard_and_force(self, tmp_path):
        self._fetch(tmp_path)
        blocked = self._fetch(tmp_path)
        assert blocked.overwrite_blocked and blocked.errors
        forced = self._fetch(tmp_path, force=True)
        assert not forced.overwrite_blocked and forced.rows_saved == 96

    def test_run_readiness_integration(self, tmp_path):
        r = fetch_historical(
            provider="fake", symbol="BTCUSDT", timeframe="15m",
            start_date="2026-01-01", end_date="2026-01-10",
            base_dir=str(tmp_path / "h"),
            readiness_report_dir=str(tmp_path / "rep"),
            run_readiness=True,
            provider_obj=FakeHistoricalProvider(),
        )
        assert r.readiness_status is not None
        assert r.readiness_report_path

    def test_path_traversal_blocked(self, tmp_path):
        with pytest.raises(HistoricalDataError):
            fetch_historical(
                provider="fake", symbol="BTCUSDT", timeframe="15m",
                start_date="2026-01-01", end_date="2026-01-02",
                output_path="../escape.csv",
                provider_obj=FakeHistoricalProvider(),
            )


# ---------------------------------------------------------------------------
# Execution context (Parte D)
# ---------------------------------------------------------------------------

from crypto_trading_bot.backtest_operational import (  # noqa: E402
    BacktestContextError,
    BacktestExecutionContext,
    ContextDataset,
    ContextSnapshot,
    LookAheadError,
    StrategySelectionError,
    default_backtest_registry,
    list_backtest_strategies,
    resolve_context,
    resolve_strategy_spec,
    run_operational_backtest,
    with_decision_impact,
)


class TestExecutionContext:

    def test_safe_defaults(self):
        ctx = BacktestExecutionContext(strategy="x", capital_usd=100.0)
        assert ctx.real_execution_allowed is False
        assert ctx.enabled_context_kinds() == ()
        assert ctx.enforce_risk_engine is True
        assert ctx.leverage == 1.0 and ctx.max_open_orders == 1
        assert ctx.enable_position_management is False

    def test_cannot_disable_risk_engine(self):
        with pytest.raises(BacktestContextError):
            BacktestExecutionContext(enforce_risk_engine=False)

    def test_cannot_lower_floor(self):
        with pytest.raises(BacktestContextError):
            BacktestExecutionContext(min_stop_loss_pct=0.001)

    def test_cannot_unset_simulation(self):
        with pytest.raises(BacktestContextError):
            BacktestExecutionContext(simulate_execution_only=False)

    def test_leverage_guard(self):
        with pytest.raises(BacktestContextError):
            BacktestExecutionContext(leverage=0.5)

    def test_negative_costs_guard(self):
        with pytest.raises(BacktestContextError):
            BacktestExecutionContext(fees_bps=-1.0)

    def test_enabled_context_kinds(self):
        ctx = BacktestExecutionContext(
            strategy="x", capital_usd=1.0,
            enable_ai_context=True, enable_funding_context=True,
        )
        assert set(ctx.enabled_context_kinds()) == {"ai", "funding"}

    def test_to_dict_has_schema_and_real_false(self):
        d = BacktestExecutionContext(
            strategy="x", capital_usd=1.0).to_dict()
        assert d["schema"] == "backtest_execution_context_v1"
        assert d["real_execution_allowed"] is False


# ---------------------------------------------------------------------------
# Context availability (Parte E) - anti look-ahead
# ---------------------------------------------------------------------------

def _ai_dataset():
    return ContextDataset([
        ContextSnapshot(
            kind="ai",
            as_of=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
            data={"view": "bull"}),
        ContextSnapshot(
            kind="ai",
            as_of=datetime(2026, 1, 1, 2, 0, tzinfo=timezone.utc),
            data={"view": "bear"}),
    ])


class TestContextAvailability:

    def test_disabled_toggle(self):
        a = resolve_context(
            kind="ai", enabled=False, dataset=_ai_dataset(),
            current_ts=datetime(2026, 1, 1, 1, tzinfo=timezone.utc))
        assert a.enabled is False and a.context_available is False
        assert a.reason == "disabled"

    def test_anti_look_ahead_uses_past_only(self):
        a = resolve_context(
            kind="ai", enabled=True, dataset=_ai_dataset(),
            current_ts=datetime(2026, 1, 1, 1, tzinfo=timezone.utc))
        assert a.context_available is True
        assert a.data["view"] == "bull"          # nao o futuro 'bear'
        assert a.as_of == "2026-01-01T00:00:00Z"

    def test_no_data_before_first_snapshot(self):
        a = resolve_context(
            kind="ai", enabled=True, dataset=_ai_dataset(),
            current_ts=datetime(2025, 12, 31, tzinfo=timezone.utc),
            required=True, allow_missing=False)
        assert a.context_available is False
        assert a.blocked is True
        assert a.reason == "required_context_unavailable"

    def test_missing_optional_not_blocked(self):
        a = resolve_context(
            kind="ai", enabled=True, dataset=None,
            current_ts=datetime(2026, 1, 1, 1, tzinfo=timezone.utc),
            required=False, allow_missing=True)
        assert a.context_available is False and a.blocked is False

    def test_stale_flag(self):
        ds = ContextDataset(
            [ContextSnapshot(
                kind="funding",
                as_of=datetime(2026, 1, 1, 0, tzinfo=timezone.utc),
                data={"rate": 0.01})],
            max_staleness_seconds=60)
        a = resolve_context(
            kind="funding", enabled=True, dataset=ds,
            current_ts=datetime(2026, 1, 1, 1, tzinfo=timezone.utc))
        assert a.context_available is True and a.stale is True

    def test_with_decision_impact_requires_available(self):
        a = resolve_context(
            kind="ai", enabled=True, dataset=None,
            current_ts=datetime(2026, 1, 1, tzinfo=timezone.utc))
        marked = with_decision_impact(a, impact=True)
        # nao disponivel -> impact forcado a False (nunca inventado).
        assert marked.decision_impact is False

    def test_get_as_of_returns_latest_past(self):
        ds = _ai_dataset()
        snap = ds.get_as_of(
            "ai", datetime(2026, 1, 1, 5, tzinfo=timezone.utc))
        assert snap.data["view"] == "bear"

    def test_snapshot_rejects_unknown_kind(self):
        with pytest.raises(ValueError):
            ContextSnapshot(
                kind="weird",
                as_of=datetime(2026, 1, 1, tzinfo=timezone.utc),
                data={})


# ---------------------------------------------------------------------------
# Strategy registry (Parte C)
# ---------------------------------------------------------------------------

class TestStrategyRegistry:

    def test_default_registry_has_canonical(self):
        reg = default_backtest_registry()
        for n in ("trend_pullback", "trend_pullback_bidirectional",
                  "volatility_breakout"):
            assert n in reg
        assert set(list_backtest_strategies()) == set(reg.list_names())

    def test_resolve_ok(self):
        spec = resolve_strategy_spec("trend_pullback")
        assert spec.name == "trend_pullback"

    def test_resolve_unknown(self):
        with pytest.raises(StrategySelectionError):
            resolve_strategy_spec("bogus")

    def test_resolve_empty(self):
        with pytest.raises(StrategySelectionError):
            resolve_strategy_spec("  ")

    def test_not_allowed_by_profile(self):
        with pytest.raises(StrategySelectionError) as ei:
            resolve_strategy_spec(
                "trend_pullback_bidirectional",
                profile_allowed=("trend_pullback",))
        assert "strategy_not_allowed_by_profile" in str(ei.value)

    def test_allowed_by_profile(self):
        spec = resolve_strategy_spec(
            "trend_pullback", profile_allowed=("trend_pullback",))
        assert spec.name == "trend_pullback"


# ---------------------------------------------------------------------------
# Runner (Parte C/F/H/I)
# ---------------------------------------------------------------------------

def _candles(n=140, vol=0.006):
    from crypto_trading_bot.backtesting.backtest_data import (
        generate_trending_candles,
    )
    return generate_trending_candles(
        n=n, base_price=65000.0, trend_pct_per_candle=0.0006,
        volatility_pct=vol, symbol="BTCUSDT", timeframe="15",
    )


class TestRunner:

    def test_runs_and_reports_real_exec_false(self):
        ctx = BacktestExecutionContext(
            strategy="trend_pullback_bidirectional", capital_usd=200.0)
        rep = run_operational_backtest(
            ctx, _candles(), symbol="BTCUSDT", timeframe="15m",
            source_type="synthetic_fake")
        d = rep.to_dict()
        assert d["real_execution_allowed"] is False
        assert d["schema"] == "backtest_operational_report_v1"
        assert d["synthetic_data_warning"] is True
        assert "results" in d

    def test_requires_capital(self):
        ctx = BacktestExecutionContext(
            strategy="trend_pullback", capital_usd=0.0)
        from crypto_trading_bot.backtest_operational import (
            BacktestRunnerError,
        )
        with pytest.raises(BacktestRunnerError):
            run_operational_backtest(
                ctx, _candles(), symbol="BTCUSDT", timeframe="15m")

    def test_no_candles(self):
        ctx = BacktestExecutionContext(
            strategy="trend_pullback", capital_usd=100.0)
        from crypto_trading_bot.backtest_operational import (
            BacktestRunnerError,
        )
        with pytest.raises(BacktestRunnerError):
            run_operational_backtest(
                ctx, [], symbol="BTCUSDT", timeframe="15m")

    def test_strategy_not_allowed_propagates(self):
        ctx = BacktestExecutionContext(
            strategy="trend_pullback_bidirectional", capital_usd=100.0)
        with pytest.raises(StrategySelectionError):
            run_operational_backtest(
                ctx, _candles(), symbol="BTCUSDT", timeframe="15m",
                profile_allowed=("trend_pullback",))

    def test_context_availability_aggregated_no_lookahead(self):
        ctx = BacktestExecutionContext(
            strategy="trend_pullback_bidirectional", capital_usd=200.0,
            enable_ai_context=True)
        ds = ContextDataset([ContextSnapshot(
            kind="ai",
            as_of=_candles()[100].timestamp,
            data={"view": "x"})])
        rep = run_operational_backtest(
            ctx, _candles(), symbol="BTCUSDT", timeframe="15m",
            context_dataset=ds, source_type="synthetic_fake")
        ai = next(c for c in rep.context_availability if c.kind == "ai")
        assert ai.enabled is True
        # disponibilidade so apos o snapshot; impacto SEMPRE 0 (honesto).
        assert ai.context_available_count > 0
        assert ai.decision_impact_count == 0

    def test_required_context_blocks(self):
        ctx = BacktestExecutionContext(
            strategy="trend_pullback", capital_usd=200.0,
            enable_ai_context=True,
            required_context_kinds=("ai",),
            allow_missing_context=False)
        rep = run_operational_backtest(
            ctx, _candles(), symbol="BTCUSDT", timeframe="15m",
            context_dataset=None, source_type="synthetic_fake")
        ai = next(c for c in rep.context_availability if c.kind == "ai")
        assert ai.blocked_count > 0
        assert any("required_context_unavailable" in w
                   for w in rep.warnings)

    def test_decision_traces_structure(self):
        ctx = BacktestExecutionContext(
            strategy="trend_pullback_bidirectional", capital_usd=200.0)
        rep = run_operational_backtest(
            ctx, _candles(n=200, vol=0.02), symbol="BTCUSDT",
            timeframe="15m", source_type="synthetic_fake")
        # Pode ou nao haver trades; se houver, a trace tem os campos-chave.
        for t in rep.decision_traces:
            assert t["final_decision"] in ("enter",)
            assert t["strategy_name"] == "trend_pullback_bidirectional"
            assert t["min_sl_pct_required"] >= 0.005
            assert t["symbol"] == "BTCUSDT"


# ---------------------------------------------------------------------------
# SL calibration advisor (Parte G) - performance / resiliencia
# ---------------------------------------------------------------------------

class TestSlCalibrationPerf:

    def test_diagnostic_only_no_backtests(self):
        from crypto_trading_bot.research.sl_calibration import (
            analyze_sl_calibration,
        )
        rep = analyze_sl_calibration(
            candles=_candles(n=120, vol=0.0024),
            data_source="synthetic_low_vol", run_backtests=False)
        assert rep["status"] == "ok"
        assert rep["backtests_ran"] is False
        assert rep["backtests_mechanism_only"] == {}
        assert rep["sl_stats_by_multiplier"]

    def test_progress_callback_called(self):
        from crypto_trading_bot.research.sl_calibration import (
            analyze_sl_calibration,
        )
        seen = []
        analyze_sl_calibration(
            candles=_candles(n=120, vol=0.02),
            data_source="synthetic", run_backtests=True,
            progress_callback=lambda name, i, t: seen.append((name, i, t)))
        assert len(seen) == 6
        assert seen[0][1] == 1 and seen[-1][2] == 6

    def test_keyboardinterrupt_yields_partial(self, monkeypatch):
        import crypto_trading_bot.research.sl_calibration as mod

        calls = {"n": 0}

        def boom(**kw):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise KeyboardInterrupt()
            return {"total_trades": 0}

        monkeypatch.setattr(mod, "_backtest_variant", boom)
        rep = mod.analyze_sl_calibration(
            candles=_candles(n=120, vol=0.02),
            data_source="synthetic", run_backtests=True)
        assert rep["backtests_partial"] is True
        assert rep["status"] == "ok"        # determinISTIco ainda emitido
        assert rep["backtests_mechanism_only"]["_interrupted_at"]


# ---------------------------------------------------------------------------
# UI ViewModels (Complemento) - NENHUM secret
# ---------------------------------------------------------------------------

from crypto_trading_bot.ui_contracts import (  # noqa: E402
    build_backtest_run_view_model,
    build_historical_data_view_model,
    build_operator_input_view_model,
)


class TestViewModels:

    def _assert_no_secret(self, vm):
        assert vm["no_secret_guarantee"] is True
        for f in vm["fields"]:
            if f["sensitive"]:
                assert f["value"] is None and f["masked"] is True

    def test_historical_view_model(self):
        vm = build_historical_data_view_model(
            values={"provider": "fake", "symbol": "BTCUSDT"})
        self._assert_no_secret(vm)
        names = {f["name"] for f in vm["fields"]}
        assert {"provider", "symbol", "timeframe", "start_date",
                "end_date"} <= names

    def test_backtest_view_model_reflects_toggle(self):
        ctx = BacktestExecutionContext(
            strategy="trend_pullback", capital_usd=200.0,
            enable_ai_context=True)
        vm = build_backtest_run_view_model(context=ctx.to_dict())
        self._assert_no_secret(vm)
        ai = next(f for f in vm["fields"]
                  if f["name"] == "enable_ai_context")
        assert ai["value"] is True
        floor = next(f for f in vm["fields"]
                     if f["name"] == "min_stop_loss_pct")
        assert floor["editable"] is False

    def test_operator_input_view_model_secrets_masked(self):
        vm = build_operator_input_view_model(
            requirements={"capital_usd": {"status": "missing"}})
        self._assert_no_secret(vm)
        secrets = [f for f in vm["fields"] if f["sensitive"]]
        assert len(secrets) >= 3
        assert all(f["value"] is None for f in secrets)

    def test_view_models_json_serializable(self):
        ctx = BacktestExecutionContext(
            strategy="trend_pullback", capital_usd=1.0)
        for vm in (
            build_historical_data_view_model(),
            build_backtest_run_view_model(context=ctx.to_dict()),
            build_operator_input_view_model(),
        ):
            json.dumps(vm)  # nao levanta


# ---------------------------------------------------------------------------
# Edge cases adicionais
# ---------------------------------------------------------------------------

class TestEdges:

    def test_binance_provider_no_network_on_construct(self):
        # Construir o provider real NAO faz rede (urllib eh lazy).
        b = BinancePublicProvider()
        assert b.name == "binance" and b.is_real is True

    def test_candle_row_aware_utc_format(self):
        # Contrato: providers emitem timestamps tz-aware em UTC.
        cr = CandleRow(
            timestamp=datetime(2026, 1, 1, 12, 30, tzinfo=timezone.utc),
            open=1, high=2, low=1, close=1.5, volume=1)
        assert cr.to_csv_dict()["timestamp"] == "2026-01-01T12:30:00Z"

    def test_fetcher_dedup(self, tmp_path):
        class DupProvider:
            name = "dup"
            is_real = False

            def fetch_candles(self, *, symbol, tf_minutes, start, end):
                ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
                row = CandleRow(timestamp=ts, open=1, high=2, low=1,
                                close=1.5, volume=1)
                row2 = CandleRow(
                    timestamp=datetime(2026, 1, 1, 0, 15,
                                       tzinfo=timezone.utc),
                    open=1, high=2, low=1, close=1.5, volume=1)
                return [row, row, row2]

        r = fetch_historical(
            provider="fake", symbol="BTCUSDT", timeframe="15m",
            start_date="2026-01-01", end_date="2026-01-02",
            base_dir=str(tmp_path / "h"),
            provider_obj=DupProvider())
        assert r.rows_downloaded == 3 and r.rows_saved == 2
        assert any("duplicatas" in w for w in r.warnings)

    def test_fetcher_zero_candles_error(self, tmp_path):
        class EmptyProvider:
            name = "empty"
            is_real = False

            def fetch_candles(self, **kw):
                return []

        r = fetch_historical(
            provider="fake", symbol="BTCUSDT", timeframe="15m",
            start_date="2026-01-01", end_date="2026-01-02",
            base_dir=str(tmp_path / "h"),
            provider_obj=EmptyProvider())
        assert r.rows_saved == 0 and r.errors

    def test_context_dataset_has_kind(self):
        ds = _ai_dataset()
        assert ds.has_kind("ai") is True
        assert ds.has_kind("news") is False

    def test_report_context_summary_to_dict(self):
        from crypto_trading_bot.backtest_operational.report import (
            ContextAvailabilitySummary,
        )
        s = ContextAvailabilitySummary(
            kind="ai", enabled=True, decision_points=10,
            context_available_count=4)
        d = s.to_dict()
        assert d["kind"] == "ai" and d["decision_points"] == 10

    def test_runner_notes_declare_no_invented_impact(self):
        ctx = BacktestExecutionContext(
            strategy="trend_pullback", capital_usd=100.0)
        rep = run_operational_backtest(
            ctx, _candles(), symbol="BTCUSDT", timeframe="15m",
            source_type="synthetic_fake")
        joined = " ".join(rep.notes)
        assert "decision_impact=0" in joined
        assert "simulada" in joined

    def test_sl_insufficient_data(self):
        from crypto_trading_bot.research.sl_calibration import (
            analyze_sl_calibration,
        )
        rep = analyze_sl_calibration(
            candles=_candles(n=10), data_source="synthetic",
            run_backtests=False, min_candles=60)
        assert rep["status"] == "insufficient_data"

    def test_fetch_dataset_path_canonical_layout(self, tmp_path):
        r = fetch_historical(
            provider="fake", symbol="ethusdt", timeframe="1h",
            start_date="2026-01-01", end_date="2026-01-03",
            base_dir=str(tmp_path / "h"),
            provider_obj=FakeHistoricalProvider())
        assert r.dataset_path.replace("\\", "/").endswith(
            "ETHUSDT/1h/ETHUSDT_1h.csv")


# ---------------------------------------------------------------------------
# CLIs (carregadas por caminho; provider fake; NUNCA rede)
# ---------------------------------------------------------------------------

import importlib.util  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

_SCRIPTS = _Path(__file__).parent.parent / "scripts"


def _load_script(name):
    spec = importlib.util.spec_from_file_location(
        f"_fase37_{name}", _SCRIPTS / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestClis:

    def test_fetcher_cli_fake(self, tmp_path):
        mod = _load_script("run_historical_data_fetcher.py")
        rc = mod.main([
            "--provider", "fake", "--symbol", "BTCUSDT",
            "--timeframe", "15m", "--start-date", "2026-01-01",
            "--end-date", "2026-01-03", "--base-dir",
            str(tmp_path / "h"),
        ])
        assert rc == 0

    def test_fetcher_cli_binance_blocked_without_network(self, tmp_path):
        mod = _load_script("run_historical_data_fetcher.py")
        rc = mod.main([
            "--provider", "binance", "--symbol", "BTCUSDT",
            "--timeframe", "15m", "--start-date", "2026-01-01",
            "--end-date", "2026-01-02", "--base-dir", str(tmp_path / "h"),
        ])
        assert rc == 1   # exige --allow-network; nunca chama rede

    def test_backtest_cli_from_csv(self, tmp_path):
        # gera CSV via fetcher e roda o backtest CLI offline.
        fetch_historical(
            provider="fake", symbol="BTCUSDT", timeframe="15m",
            start_date="2026-01-01", end_date="2026-01-06",
            base_dir=str(tmp_path / "h"),
            provider_obj=FakeHistoricalProvider())
        csv = (tmp_path / "h" / "BTCUSDT" / "15m" / "BTCUSDT_15m.csv")
        mod = _load_script("run_strategy_backtest.py")
        rc = mod.main([
            "--from-csv", str(csv), "--symbol", "BTCUSDT",
            "--timeframe", "15m", "--strategy",
            "trend_pullback_bidirectional", "--capital", "200",
        ])
        assert rc == 0

    def test_backtest_cli_unknown_strategy(self, tmp_path):
        fetch_historical(
            provider="fake", symbol="BTCUSDT", timeframe="15m",
            start_date="2026-01-01", end_date="2026-01-03",
            base_dir=str(tmp_path / "h"),
            provider_obj=FakeHistoricalProvider())
        csv = (tmp_path / "h" / "BTCUSDT" / "15m" / "BTCUSDT_15m.csv")
        mod = _load_script("run_strategy_backtest.py")
        rc = mod.main([
            "--from-csv", str(csv), "--symbol", "BTCUSDT",
            "--timeframe", "15m", "--strategy", "bogus",
            "--capital", "200",
        ])
        assert rc == 1

    def test_advisor_cli_diagnostic_only(self, tmp_path):
        mod = _load_script("run_sl_calibration_advisor.py")
        rc = mod.main([
            "--synthetic", "--low-vol", "--synthetic-candles", "120",
            "--output", str(tmp_path / "adv.json"),
        ])
        assert rc == 0
        rep = json.loads((tmp_path / "adv.json").read_text(
            encoding="utf-8"))
        assert rep["backtests_ran"] is False
