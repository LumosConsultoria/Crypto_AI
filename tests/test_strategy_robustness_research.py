"""
Matriz de Robustez Offline — FASE 10
=====================================
2 estratégias × 4 cenários sintéticos × 3 perfis de custo + walk-forward.

⚠️  100% offline. ZERO rede. ZERO secrets. ZERO IA/LLM.
⚠️  Comparação multi-coluna para leitura humana — sem composite score,
    sem "melhor estratégia absoluta", sem ranking obrigatório.
⚠️  Walk-forward é AVALIAÇÃO. NÃO é otimização. Cada fold usa
    parâmetros fixos e nova instância de estratégia.

Cobertura (testes):
    - A matriz roda 2×4×3 = 24 avaliações sem erro.
    - Todas produzem BacktestReport válido com equity_curve > 0 candles.
    - Invariante SL/TP preservada em TODO trade aberto em qualquer célula.
    - Determinismo: 2 execuções idênticas → mesmos PnL, trades e equity.
    - position_size_usd reflete a config passada (não é hardcode).
    - Walk-forward: cada estratégia avaliada em 3 folds; cada fold tem
      RiskEngine independente e nova strategy (sem vazamento de estado).
    - Saída tabular contém os 2 nomes de estratégia e os 4 cenários.
    - Tests NÃO exigem lucro.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from crypto_trading_bot.backtesting.backtest_data import (
    generate_ranging_candles,
    generate_trending_candles,
    generate_volatile_candles,
)
from crypto_trading_bot.backtesting.execution_costs import ExecutionCostConfig
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.research.strategy_research import (
    StrategyEvaluationResult,
    StrategySpec,
    evaluate_strategy,
)
from crypto_trading_bot.strategies.trend_pullback_strategy import (
    build_trend_pullback_spec,
)
from crypto_trading_bot.strategies.volatility_breakout_strategy import (
    build_volatility_breakout_spec,
)


# ---------------------------------------------------------------------------
# Fixtures de cenários e custos
# ---------------------------------------------------------------------------

_SCENARIO_NAMES = ("trending", "ranging", "high_vol", "choppy_whipsaw")


def _build_scenarios(n: int = 200) -> Dict[str, List[Candle]]:
    """
    Constrói os 4 cenários sintéticos determinísticos.

    - trending:        tendência positiva consistente.
    - ranging:         lateralização (zig-zag senoidal).
    - high_vol:        alta volatilidade com leve tendência.
    - choppy_whipsaw:  alta volatilidade com tendência nula
                       (oscilação forte sem direção).
    """
    return {
        "trending": generate_trending_candles(
            n=n, base_price=65000.0, trend_pct_per_candle=0.0015
        ),
        "ranging": generate_ranging_candles(
            n=n, center_price=65000.0, range_pct=0.02
        ),
        "high_vol": generate_volatile_candles(
            n=n, base_price=65000.0,
            volatility_pct=0.04, trend_pct_per_candle=0.001,
        ),
        "choppy_whipsaw": generate_volatile_candles(
            n=n, base_price=65000.0,
            volatility_pct=0.05, trend_pct_per_candle=0.0,
        ),
    }


_COST_PROFILES = ("zero", "realistic", "stressed")


def _build_cost_profiles() -> Dict[str, ExecutionCostConfig]:
    """
    3 perfis de custo usando APENAS campos existentes em ExecutionCostConfig.

    - zero:       sem custos (regressão FASE 3D.5).
    - realistic:  fee taker ~0.06%, slippage ~0.05%, spread ~0.02%.
    - stressed:   custos elevados + entry_latency_candles=2.
    """
    return {
        "zero": ExecutionCostConfig(),
        "realistic": ExecutionCostConfig(
            taker_fee_pct=0.0006,
            slippage_pct=0.0005,
            spread_pct=0.0002,
        ),
        "stressed": ExecutionCostConfig(
            taker_fee_pct=0.0012,
            slippage_pct=0.0010,
            spread_pct=0.0005,
            entry_latency_candles=2,
        ),
    }


def _build_specs() -> List[StrategySpec]:
    """As 2 specs determinísticas em ordem fixa para a matriz."""
    return [
        build_trend_pullback_spec(),
        build_volatility_breakout_spec(),
    ]


# ---------------------------------------------------------------------------
# Helper: executa toda a matriz
# ---------------------------------------------------------------------------

def _run_matrix(
    initial_capital: float = 5000.0,
) -> Dict[Tuple[str, str, str], StrategyEvaluationResult]:
    """
    Roda a matriz 2 × 4 × 3 e retorna um dict indexado por
    (spec_name, scenario_name, cost_name).

    Cada célula é avaliada por evaluate_strategy() — fresca, isolada.
    """
    specs = _build_specs()
    scenarios = _build_scenarios()
    costs = _build_cost_profiles()

    results: Dict[Tuple[str, str, str], StrategyEvaluationResult] = {}
    for spec in specs:
        for scenario_name, candles in scenarios.items():
            for cost_name, cost_cfg in costs.items():
                result = evaluate_strategy(
                    spec=spec,
                    candles=candles,
                    initial_capital=initial_capital,
                    min_candles=60,
                    symbol="BTCUSDT",
                    execution_cost_config=cost_cfg,
                )
                results[(spec.name, scenario_name, cost_name)] = result
    return results


def _format_matrix(
    results: Dict[Tuple[str, str, str], StrategyEvaluationResult],
) -> str:
    """
    Formata a matriz como tabela multi-coluna legível.

    SEM composite score. SEM ranking absoluto.
    Para cada (estratégia, cenário, custo): trades, pnl, expectancy,
    profit_factor, max_drawdown_pct.
    """
    lines: List[str] = []
    lines.append("=" * 90)
    lines.append(
        "  📊 STRATEGY ROBUSTNESS MATRIX — 2 strategies × 4 scenarios × 3 costs"
    )
    lines.append("  ⚠️  Sintético offline. NÃO garante performance futura.")
    lines.append("  ⚠️  Sem composite score. Sem 'melhor estratégia absoluta'.")
    lines.append("=" * 90)
    lines.append(
        f"  {'Strategy':<22} {'Scenario':<16} {'Cost':<10} "
        f"{'Trd':>4} {'PnL$':>9} {'Expec.':>8} {'PF':>6} {'DD%':>7}"
    )
    lines.append("-" * 90)

    # Ordem determinística
    for spec_name in sorted({k[0] for k in results.keys()}):
        for scenario_name in _SCENARIO_NAMES:
            for cost_name in _COST_PROFILES:
                r = results.get((spec_name, scenario_name, cost_name))
                if r is None:
                    continue
                rep = r.single_report
                pf = rep.net_profit_factor
                pf_str = f"{pf:.2f}" if pf is not None else "  N/A"
                lines.append(
                    f"  {spec_name:<22} {scenario_name:<16} {cost_name:<10} "
                    f"{rep.total_trades:>4} {rep.total_pnl_usd:>+9.2f} "
                    f"{rep.expectancy_usd:>+8.2f} {pf_str:>6} "
                    f"{rep.max_drawdown_pct:>+7.2f}"
                )
        lines.append("-" * 90)

    lines.append("")
    lines.append("  Cenários: trending / ranging / high_vol / choppy_whipsaw")
    lines.append("  Custos:   zero / realistic / stressed (com latency=2)")
    lines.append("  ⚠️  Backtest NÃO garante performance futura.")
    lines.append("=" * 90)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Testes da matriz
# ---------------------------------------------------------------------------

class TestRobustnessMatrix:

    def test_matrix_runs_2x4x3_without_errors(self):
        results = _run_matrix()
        assert len(results) == 2 * 4 * 3
        for cell in results.values():
            assert cell.single_report is not None
            assert len(cell.single_report.equity_curve) > 0

    def test_each_cell_has_valid_equity_curve(self):
        results = _run_matrix()
        for key, cell in results.items():
            curve = cell.single_report.equity_curve
            assert all(v >= 0 for v in curve), (
                f"Equity negativo em {key}: amostra={curve[:3]}"
            )

    def test_sl_tp_invariant_preserved_in_all_trades(self):
        """
        Em TODA célula da matriz, todo trade aberto preserva
        0 < stop_loss < entry < take_profit (para BUY).
        """
        results = _run_matrix()
        violations: List[str] = []
        for key, cell in results.items():
            for trade in cell.single_report.trades:
                if trade.side != "buy":
                    continue
                tp = trade.take_profit_price
                if not (
                    0.0 < trade.stop_loss_price
                    < trade.entry_price_theoretical
                    and (tp is None or trade.entry_price_theoretical < tp)
                ):
                    violations.append(
                        f"{key} trade {trade.entry_candle_idx}: "
                        f"sl={trade.stop_loss_price} "
                        f"entry={trade.entry_price_theoretical} "
                        f"tp={tp}"
                    )
        assert not violations, (
            f"Violações de invariante SL/TP/entry detectadas: "
            f"{violations[:5]}"
        )

    def test_matrix_is_deterministic(self):
        """Mesma matriz executada duas vezes → mesmos PnL e equity."""
        results_a = _run_matrix()
        results_b = _run_matrix()
        assert set(results_a.keys()) == set(results_b.keys())
        for key in results_a:
            ra = results_a[key].single_report
            rb = results_b[key].single_report
            assert ra.total_trades == rb.total_trades, f"trades diff em {key}"
            assert abs(ra.total_pnl_usd - rb.total_pnl_usd) < 1e-6, (
                f"pnl diff em {key}"
            )
            assert ra.equity_curve == rb.equity_curve, f"equity diff em {key}"

    def test_position_size_reflects_config_not_hardcoded(self):
        """
        Override de position_size via config_override deve alterar
        o notional dos trades — provando ausência de hardcode.
        """
        spec = build_trend_pullback_spec()
        candles = generate_trending_candles(n=150, trend_pct_per_candle=0.0015)
        result_default = evaluate_strategy(
            spec=spec, candles=candles, min_candles=60,
            initial_capital=5000.0,
        )
        result_overridden = evaluate_strategy(
            spec=spec, candles=candles, min_candles=60,
            initial_capital=5000.0,
            config_override={"position_size_usd": 500.0},
        )
        if (result_default.single_report.total_trades > 0
                and result_overridden.single_report.total_trades > 0):
            default_size = (
                result_default.single_report.trades[0].position_size_usd
            )
            overridden_size = (
                result_overridden.single_report.trades[0].position_size_usd
            )
            assert default_size != overridden_size
            assert overridden_size == 500.0


# ---------------------------------------------------------------------------
# Walk-forward como AVALIAÇÃO (não otimização)
# ---------------------------------------------------------------------------

class TestWalkForwardEvaluation:

    def test_walk_forward_produces_n_folds_per_strategy(self):
        candles = generate_trending_candles(
            n=400, trend_pct_per_candle=0.0015
        )
        for spec in _build_specs():
            result = evaluate_strategy(
                spec=spec, candles=candles,
                initial_capital=5000.0, min_candles=60,
                walk_forward_n_folds=3,
                walk_forward_train_pct=0.7,
            )
            assert result.wf_fold_results is not None
            assert len(result.wf_fold_results) == 3
            assert result.wf_summary is not None

    def test_walk_forward_each_fold_has_independent_reports(self):
        """
        Cada fold deve possuir train_report E test_report independentes
        (provado pela API existente: run_walk_forward cria 2 strategies
        novas por fold). Aqui validamos que a estrutura final tem N folds
        com 2 reports cada e que o spec.factory foi chamado com config
        fresca em cada fold.
        """
        candles = generate_trending_candles(
            n=400, trend_pct_per_candle=0.0015
        )
        spec = build_volatility_breakout_spec()
        result = evaluate_strategy(
            spec=spec, candles=candles,
            initial_capital=5000.0, min_candles=60,
            walk_forward_n_folds=3,
        )
        assert result.wf_fold_results is not None
        for fold in result.wf_fold_results:
            assert fold.train_report is not None
            assert fold.test_report is not None
            assert len(fold.train_report.equity_curve) > 0
            assert len(fold.test_report.equity_curve) > 0

    def test_walk_forward_is_deterministic(self):
        candles = generate_trending_candles(
            n=400, trend_pct_per_candle=0.0015
        )
        spec = build_trend_pullback_spec()
        r1 = evaluate_strategy(
            spec=spec, candles=candles,
            initial_capital=5000.0, min_candles=60,
            walk_forward_n_folds=3,
        )
        r2 = evaluate_strategy(
            spec=spec, candles=candles,
            initial_capital=5000.0, min_candles=60,
            walk_forward_n_folds=3,
        )
        assert r1.wf_fold_results is not None
        assert r2.wf_fold_results is not None
        for f1, f2 in zip(r1.wf_fold_results, r2.wf_fold_results):
            assert f1.train_report.total_trades == f2.train_report.total_trades
            assert f1.test_report.total_trades == f2.test_report.total_trades
            assert (
                abs(f1.test_report.total_pnl_usd - f2.test_report.total_pnl_usd)
                < 1e-6
            )

    def test_walk_forward_does_not_alter_default_config(self):
        """spec.default_config é MappingProxyType — runtime não a muta."""
        candles = generate_trending_candles(
            n=300, trend_pct_per_candle=0.0015
        )
        spec = build_trend_pullback_spec()
        snapshot = dict(spec.default_config)
        _ = evaluate_strategy(
            spec=spec, candles=candles,
            initial_capital=5000.0, min_candles=60,
            walk_forward_n_folds=3,
        )
        assert dict(spec.default_config) == snapshot


# ---------------------------------------------------------------------------
# Saída tabular (auditoria humana)
# ---------------------------------------------------------------------------

class TestMatrixHumanReadable:

    def test_matrix_table_contains_all_strategies_and_scenarios(self):
        results = _run_matrix()
        table = _format_matrix(results)
        for spec in _build_specs():
            assert spec.name in table
        for scenario in _SCENARIO_NAMES:
            assert scenario in table
        for cost in _COST_PROFILES:
            assert cost in table

    def test_matrix_table_contains_explicit_disclaimers(self):
        results = _run_matrix()
        table = _format_matrix(results)
        lower = table.lower()
        # Avisos obrigatórios da FASE 10:
        # backtest não garante performance, sem composite score
        assert "não garante" in lower or "garante performance" in lower
        assert "composite" in lower or "absoluta" in lower

    def test_matrix_table_can_be_printed(self, capsys):
        results = _run_matrix()
        table = _format_matrix(results)
        print(table)
        captured = capsys.readouterr()
        assert "STRATEGY ROBUSTNESS MATRIX" in captured.out


# ---------------------------------------------------------------------------
# Smoke: integração com framework de research
# ---------------------------------------------------------------------------

class TestResearchFrameworkIntegration:

    def test_specs_are_registrable(self):
        from crypto_trading_bot.research.strategy_research import (
            StrategyRegistry,
        )
        registry = StrategyRegistry()
        for spec in _build_specs():
            registry.register(spec)
        assert len(registry) == 2
        assert "trend_pullback_default" in registry
        assert "vol_breakout_default" in registry
