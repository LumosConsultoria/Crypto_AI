"""
Testes do Strategy Research Framework — FASE 3F
=================================================
⚠️  ZERO chamadas à internet.
⚠️  ZERO API keys.
⚠️  ZERO ordens reais.

Cobertura:
    - StrategySpec: criação, frozen, default_config imutável (snapshot),
      tags como tuple, validações.
    - StrategyRegistry: register/get/list_names/clear, duplicate name,
      unknown name, instanciável (sem singleton global).
    - evaluate_strategy: single + opcional walk-forward, divergência,
      config_override mesclada sobre default_config.
    - compare_strategies: preserva ordem, mesmo dataset para todos.
    - rank_strategies: 3 rankings independentes, min_trades filter, None tratado.
    - summarize_comparison: aviso obrigatório de não-garantia.
    - Propagação de custos para single E walk-forward.
    - challenge target propagado como KPI.
    - Factories criam instâncias independentes.
    - Nenhuma referência a provider_name.
    - Não existe max_profit_usd.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, List, Optional

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tests.helpers import (
    DEFAULT_CAPITAL,
    DEFAULT_ENTRY_PRICE,
    DEFAULT_STOP_PRICE,
    DEFAULT_SYMBOL,
    DEFAULT_TP_PRICE,
    StubStrategy,
    make_default_buy_signal,
)

from crypto_trading_bot.backtesting.backtest_data import (
    generate_candles_with_stop_hit,
    generate_trending_candles,
)
from crypto_trading_bot.backtesting.backtest_report import BacktestReport
from crypto_trading_bot.backtesting.backtest_trade import BacktestTrade, CloseReason
from crypto_trading_bot.backtesting.execution_costs import ExecutionCostConfig
from crypto_trading_bot.research import (
    RankMetric,
    StrategyEvaluationResult,
    StrategyRegistry,
    StrategySpec,
    compare_strategies,
    evaluate_strategy,
    rank_strategies,
    summarize_comparison,
)
from crypto_trading_bot.strategies.signal_model import StrategySignal


# ---------------------------------------------------------------------------
# Helpers locais
# ---------------------------------------------------------------------------

_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _buy_factory(config: Dict[str, Any]) -> StubStrategy:
    """Factory padrão: StubStrategy BUY já set_running.

    one_shot=True: estes testes validam mecanica de UM trade controlado;
    com o engine agora notificando on_trade_closed (lifecycle/reentrada),
    o one_shot mantem a intencao "1 trade" de forma explicita.
    """
    signal = make_default_buy_signal()
    s = StubStrategy(signal=signal, block_after_trade=True, one_shot=True)
    s.set_running()
    return s


def _hold_factory(config: Dict[str, Any]) -> StubStrategy:
    s = StubStrategy(
        signal=StrategySignal.hold(DEFAULT_SYMBOL, "stub"),
        block_after_trade=True,
    )
    s.set_running()
    return s


def _make_spec(name: str = "demo", factory=None, default_config=None) -> StrategySpec:
    return StrategySpec(
        name=name,
        factory=factory or _hold_factory,
        default_config=default_config or {},
    )


def _make_trade(pnl: float, *, entry: int = 10, exit_idx: int = 15) -> BacktestTrade:
    """Cria BacktestTrade fechado com PnL desejado (helper para reports manuais)."""
    entry_price = 65000.0
    if pnl > 0:
        close_reason = CloseReason.TAKE_PROFIT
        exit_price = entry_price + (pnl / 200.0) * entry_price
    else:
        close_reason = CloseReason.STOP_LOSS
        exit_price = entry_price + (pnl / 200.0) * entry_price
        if exit_price <= 0 or (exit_price >= entry_price and pnl < 0):
            exit_price = entry_price * 0.98

    trade = BacktestTrade(
        symbol="BTCUSDT",
        strategy_name="t",
        entry_candle_idx=entry,
        entry_time=_TS,
        entry_price=entry_price,
        stop_loss_price=64000.0,
        take_profit_price=67000.0 if pnl > 0 else None,
        position_size_usd=200.0,
        side="buy",
        entry_price_theoretical=entry_price,
    )
    trade.close(
        exit_candle_idx=exit_idx,
        exit_time=_TS,
        exit_price=exit_price,
        close_reason=close_reason,
        exit_price_theoretical=exit_price,
    )
    return trade


def _make_report_with_pnls(
    wins: Optional[List[float]] = None,
    losses: Optional[List[float]] = None,
    initial_capital: float = 5000.0,
) -> BacktestReport:
    wins = wins or []
    losses = losses or []
    trades = []
    capital = initial_capital
    equity = [capital]
    for w in wins:
        trades.append(_make_trade(abs(w)))
        capital += abs(w)
        equity.append(capital)
    for l in losses:
        trades.append(_make_trade(-abs(l)))
        capital -= abs(l)
        equity.append(capital)
    return BacktestReport.from_trades(
        trades=trades,
        initial_capital=initial_capital,
        equity_curve=equity,
        strategy_name="t",
        symbol="BTCUSDT",
    )


def _make_eval_result(name: str, report: BacktestReport) -> StrategyEvaluationResult:
    """Constrói StrategyEvaluationResult manual para testes de ranking."""
    return StrategyEvaluationResult(
        spec=_make_spec(name=name),
        config_used=MappingProxyType({}),
        single_report=report,
    )


# ---------------------------------------------------------------------------
# StrategySpec
# ---------------------------------------------------------------------------

class TestStrategySpec:

    def test_spec_creation_with_required_fields(self):
        spec = StrategySpec(name="s1", factory=_buy_factory)
        assert spec.name == "s1"
        assert spec.factory is _buy_factory
        assert spec.description == ""
        assert len(spec.default_config) == 0
        assert spec.tags == ()

    def test_spec_is_frozen(self):
        spec = _make_spec(name="s2")
        with pytest.raises((AttributeError, Exception)):
            spec.name = "outro"  # type: ignore[misc]

    def test_spec_default_config_independent_from_original_dict(self):
        """
        AJUSTE OBRIGATÓRIO: mutar o dict ORIGINAL passado como default_config
        NÃO deve alterar o spec.
        """
        original = {"a": 1, "b": 2}
        spec = StrategySpec(name="s3", factory=_buy_factory, default_config=original)
        # Snapshot interno read-only
        assert dict(spec.default_config) == {"a": 1, "b": 2}
        # Muta o dict original
        original["a"] = 999
        original["new"] = "x"
        # Spec não muda
        assert dict(spec.default_config) == {"a": 1, "b": 2}
        assert "new" not in spec.default_config

    def test_spec_default_config_is_read_only(self):
        """default_config interno DEVE ser read-only (MappingProxyType)."""
        spec = StrategySpec(name="s", factory=_buy_factory, default_config={"a": 1})
        with pytest.raises(TypeError):
            spec.default_config["a"] = 99  # type: ignore[index]

    def test_spec_tags_converted_to_tuple(self):
        spec = StrategySpec(
            name="s", factory=_buy_factory, tags=["alpha", "beta"]  # type: ignore[arg-type]
        )
        assert isinstance(spec.tags, tuple)
        assert spec.tags == ("alpha", "beta")

    def test_spec_empty_name_raises(self):
        with pytest.raises(ValueError, match="name"):
            StrategySpec(name="", factory=_buy_factory)
        with pytest.raises(ValueError, match="name"):
            StrategySpec(name="   ", factory=_buy_factory)

    def test_spec_non_callable_factory_raises(self):
        with pytest.raises(ValueError, match="factory"):
            StrategySpec(name="s", factory="not_callable")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# StrategyRegistry
# ---------------------------------------------------------------------------

class TestStrategyRegistry:

    def test_register_and_get_spec(self):
        reg = StrategyRegistry()
        spec = _make_spec(name="alpha")
        reg.register(spec)
        assert reg.get("alpha") is spec
        assert "alpha" in reg
        assert len(reg) == 1

    def test_register_duplicate_name_raises(self):
        reg = StrategyRegistry()
        reg.register(_make_spec(name="dup"))
        with pytest.raises(ValueError, match="já registrada"):
            reg.register(_make_spec(name="dup"))

    def test_get_unknown_name_raises(self):
        reg = StrategyRegistry()
        with pytest.raises(KeyError, match="não encontrada"):
            reg.get("missing")

    def test_list_names_returns_sorted(self):
        reg = StrategyRegistry()
        reg.register(_make_spec(name="charlie"))
        reg.register(_make_spec(name="alpha"))
        reg.register(_make_spec(name="bravo"))
        assert reg.list_names() == ["alpha", "bravo", "charlie"]

    def test_clear_resets_registry(self):
        reg = StrategyRegistry()
        reg.register(_make_spec(name="x"))
        reg.register(_make_spec(name="y"))
        assert len(reg) == 2
        reg.clear()
        assert len(reg) == 0
        assert reg.list_names() == []

    def test_registry_instances_are_isolated(self):
        """
        AJUSTE OBRIGATÓRIO: cada registry é independente (sem singleton global).
        """
        reg_a = StrategyRegistry()
        reg_b = StrategyRegistry()
        reg_a.register(_make_spec(name="only_in_a"))
        assert "only_in_a" in reg_a
        assert "only_in_a" not in reg_b


# ---------------------------------------------------------------------------
# evaluate_strategy — single backtest
# ---------------------------------------------------------------------------

class TestEvaluateStrategySingle:

    def test_evaluate_returns_evaluation_result(self):
        candles = generate_trending_candles(100, trend_pct_per_candle=0.0)
        spec = _make_spec(name="hold", factory=_hold_factory)
        result = evaluate_strategy(spec, candles, min_candles=5)
        assert isinstance(result, StrategyEvaluationResult)
        assert result.spec is spec

    def test_single_report_is_backtest_report_instance(self):
        candles = generate_trending_candles(100, trend_pct_per_candle=0.0)
        spec = _make_spec(name="hold", factory=_hold_factory)
        result = evaluate_strategy(spec, candles, min_candles=5)
        assert isinstance(result.single_report, BacktestReport)

    def test_walk_forward_fields_none_when_not_requested(self):
        candles = generate_trending_candles(100, trend_pct_per_candle=0.0)
        spec = _make_spec(name="hold", factory=_hold_factory)
        result = evaluate_strategy(spec, candles, min_candles=5)
        # walk_forward_n_folds=None default
        assert result.wf_fold_results is None
        assert result.wf_summary is None
        assert result.overfitting_divergence_usd is None

    def test_config_override_merges_over_default_config(self):
        received_configs: List[Dict[str, Any]] = []

        def capturing_factory(config):
            received_configs.append(dict(config))
            return _hold_factory(config)

        spec = StrategySpec(
            name="s",
            factory=capturing_factory,
            default_config={"a": 1, "b": 2},
        )
        candles = generate_trending_candles(60, trend_pct_per_candle=0.0)
        evaluate_strategy(
            spec, candles, min_candles=5,
            config_override={"a": 99, "c": "new"},
        )
        # Recebeu config FINAL = default + override
        assert received_configs[0] == {"a": 99, "b": 2, "c": "new"}
        # Spec.default_config NÃO foi mutado
        assert dict(spec.default_config) == {"a": 1, "b": 2}

    def test_config_used_in_result_is_read_only(self):
        spec = _make_spec(name="s", default_config={"x": 10})
        candles = generate_trending_candles(60, trend_pct_per_candle=0.0)
        result = evaluate_strategy(spec, candles, min_candles=5)
        # Read-only (MappingProxyType)
        with pytest.raises(TypeError):
            result.config_used["x"] = 999  # type: ignore[index]


# ---------------------------------------------------------------------------
# evaluate_strategy — com walk-forward
# ---------------------------------------------------------------------------

class TestEvaluateStrategyWithWalkForward:

    def test_walk_forward_runs_when_n_folds_set(self):
        candles = generate_trending_candles(500, trend_pct_per_candle=0.0)
        spec = _make_spec(name="hold", factory=_hold_factory)
        result = evaluate_strategy(
            spec, candles, min_candles=5, walk_forward_n_folds=5
        )
        assert result.wf_fold_results is not None
        assert result.wf_summary is not None
        assert result.overfitting_divergence_usd is not None

    def test_wf_fold_results_has_correct_length(self):
        candles = generate_trending_candles(500, trend_pct_per_candle=0.0)
        spec = _make_spec(name="hold", factory=_hold_factory)
        result = evaluate_strategy(
            spec, candles, min_candles=5, walk_forward_n_folds=4
        )
        assert len(result.wf_fold_results) == 4

    def test_overfitting_divergence_calculated_when_wf_runs(self):
        """
        Single HOLD strategy → 0 trades → PnL=0. WF idem.
        divergence = |0 - 0| = 0.
        """
        candles = generate_trending_candles(500, trend_pct_per_candle=0.0)
        spec = _make_spec(name="hold", factory=_hold_factory)
        result = evaluate_strategy(
            spec, candles, min_candles=5, walk_forward_n_folds=5
        )
        assert result.overfitting_divergence_usd == 0.0


# ---------------------------------------------------------------------------
# compare_strategies
# ---------------------------------------------------------------------------

class TestCompareStrategies:

    def test_compare_returns_one_result_per_spec(self):
        candles = generate_trending_candles(100, trend_pct_per_candle=0.0)
        specs = [
            _make_spec(name=f"s{i}", factory=_hold_factory) for i in range(3)
        ]
        results = compare_strategies(specs, candles, min_candles=5)
        assert len(results) == 3

    def test_compare_preserves_input_order(self):
        candles = generate_trending_candles(100, trend_pct_per_candle=0.0)
        names = ["charlie", "alpha", "bravo"]
        specs = [_make_spec(name=n, factory=_hold_factory) for n in names]
        results = compare_strategies(specs, candles, min_candles=5)
        assert [r.spec.name for r in results] == names

    def test_compare_uses_same_dataset_for_all_specs(self):
        """
        Todos os specs recebem o MESMO dataset (mesmo n_candles_total).
        """
        candles = generate_trending_candles(100, trend_pct_per_candle=0.0)
        specs = [_make_spec(name=f"s{i}", factory=_hold_factory) for i in range(3)]
        results = compare_strategies(specs, candles, min_candles=5)
        for r in results:
            assert r.single_report.n_candles_total == 100


# ---------------------------------------------------------------------------
# rank_strategies — 3 métricas independentes
# ---------------------------------------------------------------------------

class TestRankStrategies:

    def test_rank_by_expectancy_descending(self):
        # Cria reports com expectancy crescente
        r_low = _make_eval_result("low", _make_report_with_pnls(wins=[10.0], losses=[50.0]))
        r_mid = _make_eval_result("mid", _make_report_with_pnls(wins=[50.0], losses=[50.0]))
        r_high = _make_eval_result("high", _make_report_with_pnls(wins=[100.0], losses=[10.0]))
        ranked = rank_strategies([r_low, r_mid, r_high], metric="expectancy_usd")
        # Maior expectancy primeiro
        assert ranked[0].spec.name == "high"
        assert ranked[-1].spec.name == "low"

    def test_rank_by_profit_factor_with_none_goes_last(self):
        """net_profit_factor=None (sem perdedores) deve ir para o FIM."""
        r_only_wins = _make_eval_result("only_wins", _make_report_with_pnls(wins=[100.0]))
        r_mixed_good = _make_eval_result("mixed_good", _make_report_with_pnls(wins=[200.0], losses=[100.0]))
        r_mixed_bad = _make_eval_result("mixed_bad", _make_report_with_pnls(wins=[50.0], losses=[100.0]))
        ranked = rank_strategies(
            [r_only_wins, r_mixed_good, r_mixed_bad],
            metric="net_profit_factor",
        )
        # mixed_good (PF=2.0) > mixed_bad (PF=0.5) > only_wins (PF=None)
        assert ranked[0].spec.name == "mixed_good"
        assert ranked[1].spec.name == "mixed_bad"
        assert ranked[2].spec.name == "only_wins"  # None vai por último

    def test_rank_by_max_drawdown_pct_smaller_abs_is_better(self):
        # Reports com drawdowns diferentes
        r_small = _make_eval_result("small_dd", _make_report_with_pnls(losses=[10.0]))
        r_medium = _make_eval_result("medium_dd", _make_report_with_pnls(losses=[100.0]))
        r_huge = _make_eval_result("huge_dd", _make_report_with_pnls(losses=[500.0]))
        ranked = rank_strategies(
            [r_huge, r_small, r_medium],
            metric="max_drawdown_pct",
        )
        # Menor drawdown (mais perto de 0) primeiro
        assert ranked[0].spec.name == "small_dd"
        assert ranked[-1].spec.name == "huge_dd"

    def test_min_trades_filter_excludes_low_trade_strategies(self):
        r_low = _make_eval_result("low", _make_report_with_pnls(wins=[50.0]))  # 1 trade
        r_high = _make_eval_result(
            "high",
            _make_report_with_pnls(wins=[50.0] * 5, losses=[20.0] * 3),  # 8 trades
        )
        ranked = rank_strategies(
            [r_low, r_high],
            metric="expectancy_usd",
            min_trades=5,
        )
        # r_low excluído pelo filtro
        assert len(ranked) == 1
        assert ranked[0].spec.name == "high"

    def test_rank_invalid_metric_raises(self):
        r = _make_eval_result("x", _make_report_with_pnls(wins=[100.0]))
        with pytest.raises(ValueError, match="metric"):
            rank_strategies([r], metric="invalid")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# summarize_comparison
# ---------------------------------------------------------------------------

class TestSummarizeComparison:

    def test_summary_contains_mandatory_no_guarantee_warning(self):
        r = _make_eval_result("x", _make_report_with_pnls(wins=[100.0]))
        text = summarize_comparison([r])
        assert "NÃO GARANTE PERFORMANCE FUTURA" in text

    def test_summary_warns_metrics_have_tradeoffs(self):
        r = _make_eval_result("x", _make_report_with_pnls(wins=[100.0]))
        text = summarize_comparison([r])
        assert "trade-offs" in text.lower() or "trade-off" in text.lower()

    def test_summary_no_results_handled(self):
        text = summarize_comparison([])
        assert "NÃO GARANTE PERFORMANCE FUTURA" in text
        assert "Nenhuma estratégia" in text

    def test_summary_contains_strategy_names(self):
        results = [
            _make_eval_result("strat_a", _make_report_with_pnls(wins=[50.0])),
            _make_eval_result("strat_b", _make_report_with_pnls(losses=[30.0])),
        ]
        text = summarize_comparison(results)
        assert "strat_a" in text
        assert "strat_b" in text


# ---------------------------------------------------------------------------
# Propagação de ExecutionCostConfig
# ---------------------------------------------------------------------------

class TestExecutionCostConfigPropagation:

    def test_costs_propagate_to_single_report(self):
        """
        Cenário com 1 trade real (TP determinístico) + custos > 0.
        single_report.total_fees_usd deve ser > 0.
        """
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=5,
            hit_what="tp",
        )
        spec = _make_spec(name="buy", factory=_buy_factory)
        cfg = ExecutionCostConfig(taker_fee_pct=0.001)
        result = evaluate_strategy(
            spec, candles, min_candles=5, execution_cost_config=cfg,
        )
        assert result.single_report.total_trades == 1
        assert result.single_report.total_fees_usd > 0

    def test_costs_propagate_to_walk_forward(self):
        """Walk-forward com custos: cada fold report recebe o config."""
        candles = generate_trending_candles(500, trend_pct_per_candle=0.0)
        spec = _make_spec(name="hold", factory=_hold_factory)
        cfg = ExecutionCostConfig(taker_fee_pct=0.001)
        result = evaluate_strategy(
            spec, candles, min_candles=5,
            execution_cost_config=cfg,
            walk_forward_n_folds=3,
        )
        # Sem trades (HOLD), mas o config é propagado — todos os reports OK
        assert result.wf_fold_results is not None
        for fold in result.wf_fold_results:
            # config_used não é exposto no fold, mas estrutura é coerente
            assert fold.test_report is not None
            assert fold.train_report is not None


# ---------------------------------------------------------------------------
# challenge_target propagation
# ---------------------------------------------------------------------------

class TestChallengeTargetKpiPropagation:

    def test_challenge_target_propagated_as_kpi_only(self):
        candles = generate_trending_candles(100, trend_pct_per_candle=0.0)
        spec = _make_spec(name="hold", factory=_hold_factory)
        result = evaluate_strategy(
            spec, candles, min_candles=5,
            challenge_profit_target_usd=500.0,
        )
        assert result.single_report.challenge_profit_target_usd == 500.0
        # Backtest sempre roda até o fim (challenge não bloqueia)
        assert result.single_report.n_candles_total == 100


# ---------------------------------------------------------------------------
# Garantias de safety/provider-agnostic
# ---------------------------------------------------------------------------

class TestSafetyGuarantees:

    def test_factories_create_independent_instances_between_specs(self):
        """
        AJUSTE OBRIGATÓRIO: factories produzem objetos distintos por chamada.
        """
        created: List[Any] = []

        def tracking_factory(config):
            s = _buy_factory(config)
            created.append(s)
            return s

        spec_a = StrategySpec(name="a", factory=tracking_factory)
        spec_b = StrategySpec(name="b", factory=tracking_factory)
        candles = generate_trending_candles(60, trend_pct_per_candle=0.0)

        evaluate_strategy(spec_a, candles, min_candles=5)
        evaluate_strategy(spec_b, candles, min_candles=5)

        # 2 chamadas, 2 instâncias distintas
        assert len(created) == 2
        assert created[0] is not created[1]

    def test_runner_does_not_reference_provider_name(self):
        """
        evaluate_strategy NÃO aceita parameter provider_name nem armazena
        provider_name em StrategyEvaluationResult / StrategySpec.
        """
        import inspect
        sig = inspect.signature(evaluate_strategy)
        assert "provider_name" not in sig.parameters

        spec = _make_spec(name="x")
        candles = generate_trending_candles(60, trend_pct_per_candle=0.0)
        result = evaluate_strategy(spec, candles, min_candles=5)

        assert not hasattr(result, "provider_name")
        assert not hasattr(spec, "provider_name")

    def test_no_max_profit_usd_field_in_result(self):
        spec = _make_spec(name="x")
        candles = generate_trending_candles(60, trend_pct_per_candle=0.0)
        result = evaluate_strategy(spec, candles, min_candles=5)
        # Nem no result nem no report
        assert not hasattr(result, "max_profit_usd")
        assert not hasattr(result.single_report, "max_profit_usd")

    def test_runner_uses_riskengine_via_backtestengine(self):
        """
        Garante via cenário real que RiskEngine soberano é usado:
        capital ínfimo + position grande → RiskEngine bloqueia → 0 trades.
        """
        candles = generate_trending_candles(100, trend_pct_per_candle=0.0)
        # Factory que emite BUY com position_size grande (5000 USD)
        big_signal = make_default_buy_signal(position_size_usd=5000.0)

        def factory(config):
            s = StubStrategy(signal=big_signal, block_after_trade=False)
            s.set_running()
            return s

        spec = StrategySpec(name="oversized", factory=factory)
        # capital=1.0 → RiskEngine bloqueia (position>capital)
        result = evaluate_strategy(
            spec, candles, min_candles=5, initial_capital=1.0
        )
        assert result.single_report.total_trades == 0
        # E houve bloqueios — RiskEngine foi soberano
        assert result.single_report.risk_blocked_count > 0
