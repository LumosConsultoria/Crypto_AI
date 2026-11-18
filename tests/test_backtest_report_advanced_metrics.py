"""
Testes das métricas avançadas do BacktestReport — FASE 3E.2
==============================================================
⚠️  ZERO chamadas à internet.
⚠️  ZERO API keys.
⚠️  ZERO ordens reais.

Cobertura:
    - expectancy_usd: sem trades, só wins, só losses, misto.
    - payoff_ratio / net_payoff_ratio (alias) / gross_payoff_ratio.
    - net_profit_factor (alias de profit_factor) / gross_profit_factor.
    - max_consecutive_wins / max_consecutive_losses (sequências conhecidas).
    - avg_trade_duration_candles.
    - risk_reward_realized_avg (sem trades, SL, TP).
    - Cenário OBRIGATÓRIO: bruto vencedor + líquido perdedor (custos > gain).
    - summary() contém "MÉTRICAS AVANÇADAS".
    - to_dict() contém todas as novas chaves SEM remover legadas.
    - challenge target continua apenas KPI.
    - Não existe max_profit_usd.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

import pytest

from crypto_trading_bot.backtesting.backtest_report import BacktestReport
from crypto_trading_bot.backtesting.backtest_trade import BacktestTrade, CloseReason


# ---------------------------------------------------------------------------
# Helpers — construção determinística de trades
# ---------------------------------------------------------------------------

_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _make_trade(
    pnl: float,
    *,
    entry_candle: int = 10,
    exit_candle: int = 15,
    position_size: float = 200.0,
    symbol: str = "BTCUSDT",
    side: str = "buy",
    entry_price: float = 65000.0,
    stop_price: float = 64000.0,
    tp_price: Optional[float] = 67000.0,
) -> BacktestTrade:
    """
    Cria um BacktestTrade fechado com pnl_usd e gross_pnl_usd iguais
    (cenário sem custos — net == gross).
    """
    if pnl > 0:
        close_reason = CloseReason.TAKE_PROFIT
        exit_price = entry_price + (pnl / position_size) * entry_price
    else:
        close_reason = CloseReason.STOP_LOSS
        exit_price = entry_price + (pnl / position_size) * entry_price
        if exit_price >= entry_price and pnl < 0:
            exit_price = entry_price * 0.98

    trade = BacktestTrade(
        symbol=symbol,
        strategy_name="test_strategy",
        entry_candle_idx=entry_candle,
        entry_time=_TS,
        entry_price=entry_price,
        stop_loss_price=stop_price,
        take_profit_price=tp_price,
        position_size_usd=position_size,
        side=side,
        entry_price_theoretical=entry_price,  # sem custos → teórico == executado
    )
    trade.close(
        exit_candle_idx=exit_candle,
        exit_time=_TS,
        exit_price=exit_price,
        close_reason=close_reason,
        exit_price_theoretical=exit_price,
    )
    return trade


def _make_report(
    wins: Optional[List[float]] = None,
    losses: Optional[List[float]] = None,
    initial_capital: float = 5000.0,
    challenge_target: Optional[float] = None,
    durations: Optional[List[int]] = None,
) -> BacktestReport:
    """
    Constrói BacktestReport a partir de listas de PnLs (sem custos).
    Aceita opcionalmente `durations` para definir duration_candles dos trades.
    """
    wins = wins or []
    losses = losses or []
    trades: List[BacktestTrade] = []
    capital = initial_capital
    equity = [capital]
    all_pnls = [abs(w) for w in wins] + [-abs(l) for l in losses]
    durations = durations or [5] * len(all_pnls)
    for i, pnl in enumerate(all_pnls):
        dur = durations[i] if i < len(durations) else 5
        trade = _make_trade(pnl, entry_candle=10, exit_candle=10 + dur)
        trades.append(trade)
        capital += pnl
        equity.append(capital)

    return BacktestReport.from_trades(
        trades=trades,
        initial_capital=initial_capital,
        equity_curve=equity,
        strategy_name="test_strategy",
        symbol="BTCUSDT",
        n_candles_total=100,
        challenge_profit_target_usd=challenge_target,
    )


# ---------------------------------------------------------------------------
# Expectancy
# ---------------------------------------------------------------------------

class TestExpectancy:

    def test_expectancy_zero_with_no_trades(self):
        report = _make_report()
        assert report.expectancy_usd == 0.0

    def test_expectancy_equals_avg_win_with_only_winners(self):
        report = _make_report(wins=[100.0, 50.0, 200.0])
        # win_frac=1, loss_frac=0 → expectancy = avg_win
        assert report.expectancy_usd == pytest.approx(report.avg_win_usd, abs=1e-6)

    def test_expectancy_equals_avg_loss_with_only_losers(self):
        report = _make_report(losses=[100.0, 50.0])
        # win_frac=0, loss_frac=1 → expectancy = avg_loss (negativo)
        assert report.expectancy_usd == pytest.approx(report.avg_loss_usd, abs=1e-6)
        assert report.expectancy_usd < 0

    def test_expectancy_mixed_correct(self):
        # 2 wins de +100, 2 losses de -50 → win_rate=0.5, loss_rate=0.5
        # avg_win=100, avg_loss=-50 → expectancy = 0.5*100 + 0.5*(-50) = 25
        report = _make_report(wins=[100.0, 100.0], losses=[50.0, 50.0])
        assert report.expectancy_usd == pytest.approx(25.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Payoff ratio (net) e alias net_payoff_ratio
# ---------------------------------------------------------------------------

class TestPayoffRatio:

    def test_payoff_ratio_none_with_no_trades(self):
        report = _make_report()
        assert report.payoff_ratio is None

    def test_payoff_ratio_none_with_only_winners(self):
        report = _make_report(wins=[100.0, 50.0])
        # sem perdedores → divisão por zero → None
        assert report.payoff_ratio is None

    def test_payoff_ratio_zero_with_only_losers(self):
        report = _make_report(losses=[50.0, 30.0])
        # sem vencedores: avg_win=0, avg_loss<0 → 0/|loss| = 0
        assert report.payoff_ratio == 0.0

    def test_payoff_ratio_correct_for_mixed(self):
        # avg_win=100, avg_loss=-50 → payoff = 100/50 = 2.0
        report = _make_report(wins=[100.0], losses=[50.0])
        assert report.payoff_ratio == pytest.approx(2.0, abs=1e-4)

    def test_net_payoff_ratio_equals_payoff_ratio(self):
        report = _make_report(wins=[100.0], losses=[50.0])
        assert report.net_payoff_ratio == report.payoff_ratio

    def test_net_payoff_ratio_none_same_as_payoff_ratio(self):
        report = _make_report()
        assert report.net_payoff_ratio is None
        assert report.payoff_ratio is None


# ---------------------------------------------------------------------------
# Gross payoff ratio
# ---------------------------------------------------------------------------

class TestGrossPayoffRatio:

    def test_gross_payoff_ratio_equals_net_when_no_costs(self):
        report = _make_report(wins=[100.0, 50.0], losses=[30.0, 70.0])
        assert report.gross_payoff_ratio == report.net_payoff_ratio

    def test_gross_payoff_ratio_none_with_no_trades(self):
        report = _make_report()
        assert report.gross_payoff_ratio is None

    def test_gross_payoff_ratio_none_with_only_gross_winners(self):
        report = _make_report(wins=[100.0, 50.0])
        # Sem perdedores brutos
        assert report.gross_payoff_ratio is None

    def test_gross_payoff_ratio_zero_with_only_gross_losers(self):
        report = _make_report(losses=[100.0, 50.0])
        assert report.gross_payoff_ratio == 0.0


# ---------------------------------------------------------------------------
# Cenário OBRIGATÓRIO: trade BRUTO vencedor + LÍQUIDO perdedor
# ---------------------------------------------------------------------------

class TestGrossWinnerNetLoser:
    """
    Cenário crítico: custos altos transformam ganho bruto em perda líquida.
    Prova que as classificações gross_* e net_* NÃO usam o mesmo critério.
    """

    def _build_trade_gross_win_net_loss(self) -> BacktestTrade:
        """
        Constrói um trade onde:
          - gross_pnl_usd > 0  (preço subiu)
          - pnl_usd <= 0       (fees consumiram o ganho)
        """
        trade = BacktestTrade(
            symbol="BTCUSDT",
            strategy_name="test",
            entry_candle_idx=10,
            entry_time=_TS,
            entry_price=65000.0,          # executado == teórico (sem slippage)
            stop_loss_price=64000.0,
            take_profit_price=66000.0,
            position_size_usd=1000.0,
            side="buy",
            entry_price_theoretical=65000.0,
        )
        # Preço subiu para 65100 (ganho bruto ~ 1.54 USD).
        # Mas entry_fee=2 + exit_fee=2 = 4 USD → net = 1.54 - 4 = -2.46 USD (perda líquida).
        trade.close(
            exit_candle_idx=20,
            exit_time=_TS,
            exit_price=65100.0,
            close_reason=CloseReason.TAKE_PROFIT,
            exit_price_theoretical=65100.0,
            entry_fee_usd=2.0,
            exit_fee_usd=2.0,
        )
        return trade

    def test_trade_is_gross_winner_and_net_loser(self):
        trade = self._build_trade_gross_win_net_loss()
        assert trade.gross_pnl_usd is not None
        assert trade.gross_pnl_usd > 0, "Cenário deveria ser bruto vencedor"
        assert trade.pnl_usd is not None
        assert trade.pnl_usd <= 0, "Cenário deveria ser líquido perdedor (após fees)"

    def test_gross_sums_count_trade_as_gross_winner(self):
        """gross_winning_pnl_sum_usd DEVE incluir esse trade (bruto vencedor)."""
        trade = self._build_trade_gross_win_net_loss()
        report = BacktestReport.from_trades(
            trades=[trade],
            initial_capital=5000.0,
            equity_curve=[5000.0, 5000.0 + trade.pnl_usd],
            strategy_name="t",
            symbol="BTCUSDT",
        )
        assert report.gross_winning_pnl_sum_usd > 0, (
            "Trade bruto vencedor DEVE contar em gross_winning_pnl_sum_usd."
        )
        assert report.gross_winning_pnl_sum_usd == pytest.approx(
            trade.gross_pnl_usd, abs=1e-4
        )
        # E não deve aparecer no bucket de perdedores brutos
        assert report.gross_losing_pnl_sum_usd == 0.0

    def test_net_sums_count_trade_as_net_loser(self):
        """net_losing_pnl_sum_usd DEVE incluir esse trade (líquido perdedor)."""
        trade = self._build_trade_gross_win_net_loss()
        report = BacktestReport.from_trades(
            trades=[trade],
            initial_capital=5000.0,
            equity_curve=[5000.0, 5000.0 + trade.pnl_usd],
            strategy_name="t",
            symbol="BTCUSDT",
        )
        assert report.net_losing_pnl_sum_usd < 0, (
            "Trade líquido perdedor DEVE contar em net_losing_pnl_sum_usd."
        )
        assert report.net_losing_pnl_sum_usd == pytest.approx(
            trade.pnl_usd, abs=1e-4
        )
        # E não deve aparecer no bucket de vencedores líquidos
        assert report.net_winning_pnl_sum_usd == 0.0

    def test_gross_and_net_classifications_diverge_with_costs(self):
        """
        Prova explícita que as classificações divergem:
        - O mesmo trade está em gross_winning_pnl_sum_usd (bruto)
        - E em net_losing_pnl_sum_usd (líquido)
        """
        trade = self._build_trade_gross_win_net_loss()
        report = BacktestReport.from_trades(
            trades=[trade],
            initial_capital=5000.0,
            equity_curve=[5000.0, 5000.0 + trade.pnl_usd],
            strategy_name="t",
            symbol="BTCUSDT",
        )
        # gross winner sim, gross loser não
        assert report.gross_winning_pnl_sum_usd > 0
        assert report.gross_losing_pnl_sum_usd == 0.0
        # net loser sim, net winner não
        assert report.net_winning_pnl_sum_usd == 0.0
        assert report.net_losing_pnl_sum_usd < 0
        # Classificações divergiram — sucesso do teste.


# ---------------------------------------------------------------------------
# Profit factor: net (alias) e gross (separado)
# ---------------------------------------------------------------------------

class TestProfitFactors:

    def test_net_profit_factor_equals_legacy_profit_factor(self):
        report = _make_report(wins=[200.0, 100.0], losses=[50.0, 50.0])
        # profit_factor legado usa gross_profit_usd / |gross_loss_usd|
        # (que somam pnl_usd dos winners/losers líquidos).
        # net_profit_factor deve produzir o mesmo valor.
        assert report.net_profit_factor == report.profit_factor

    def test_net_profit_factor_none_with_no_losers(self):
        report = _make_report(wins=[100.0])
        assert report.net_profit_factor is None

    def test_gross_profit_factor_equals_net_when_no_costs(self):
        report = _make_report(wins=[200.0], losses=[100.0])
        assert report.gross_profit_factor == report.net_profit_factor

    def test_gross_profit_factor_calculated_from_gross_pnl(self):
        """Numericamente: gross_winning_pnl_sum_usd / |gross_losing_pnl_sum_usd|."""
        report = _make_report(wins=[200.0], losses=[100.0])
        expected = abs(report.gross_winning_pnl_sum_usd / report.gross_losing_pnl_sum_usd)
        assert report.gross_profit_factor == pytest.approx(round(expected, 4), abs=1e-4)

    def test_gross_profit_factor_none_with_no_gross_losers(self):
        report = _make_report(wins=[100.0])
        assert report.gross_profit_factor is None

    def test_gross_diverges_from_net_in_gross_winner_net_loser_scenario(self):
        """
        Combina um trade bruto vencedor / líquido perdedor com um trade neto vencedor.
        gross_profit_factor e net_profit_factor devem dar valores DIFERENTES.
        """
        # Trade 1: bruto vencedor mas líquido perdedor (fees grandes)
        t1 = BacktestTrade(
            symbol="BTCUSDT", strategy_name="t",
            entry_candle_idx=10, entry_time=_TS,
            entry_price=65000.0, stop_loss_price=64000.0,
            take_profit_price=66000.0, position_size_usd=1000.0,
            side="buy", entry_price_theoretical=65000.0,
        )
        t1.close(
            exit_candle_idx=20, exit_time=_TS,
            exit_price=65100.0, close_reason=CloseReason.TAKE_PROFIT,
            exit_price_theoretical=65100.0,
            entry_fee_usd=2.0, exit_fee_usd=2.0,
        )
        # Trade 2: vencedor sem custos (gross == net positivo)
        t2 = _make_trade(150.0, entry_candle=30, exit_candle=40)
        report = BacktestReport.from_trades(
            trades=[t1, t2],
            initial_capital=5000.0,
            equity_curve=[5000.0, 5000.0 + t1.pnl_usd, 5000.0 + t1.pnl_usd + t2.pnl_usd],
            strategy_name="t",
            symbol="BTCUSDT",
        )
        # net_profit_factor: net_winning (só t2) / |net_losing (só t1)|
        # gross_profit_factor: gross_winning (t1+t2 brutos) / |gross_losing (0)|
        # gross não tem perdedores brutos → None
        assert report.gross_profit_factor is None
        assert report.net_profit_factor is not None
        # Confirma que diferem


# ---------------------------------------------------------------------------
# Max consecutive wins/losses
# ---------------------------------------------------------------------------

class TestMaxConsecutive:

    def test_consecutive_zero_with_no_trades(self):
        report = _make_report()
        assert report.max_consecutive_wins == 0
        assert report.max_consecutive_losses == 0

    def test_consecutive_wins_all_winners(self):
        report = _make_report(wins=[100.0, 50.0, 75.0])
        assert report.max_consecutive_wins == 3
        assert report.max_consecutive_losses == 0

    def test_consecutive_losses_all_losers(self):
        report = _make_report(losses=[100.0, 50.0])
        assert report.max_consecutive_losses == 2
        assert report.max_consecutive_wins == 0

    def test_consecutive_wins_with_known_sequence(self):
        """
        Construção manual de sequência [W, W, W, L, W, W]:
        max_wins = 3, max_losses = 1.
        """
        trades = [
            _make_trade(100.0, entry_candle=10, exit_candle=11),
            _make_trade(100.0, entry_candle=12, exit_candle=13),
            _make_trade(100.0, entry_candle=14, exit_candle=15),
            _make_trade(-50.0, entry_candle=16, exit_candle=17),
            _make_trade(100.0, entry_candle=18, exit_candle=19),
            _make_trade(100.0, entry_candle=20, exit_candle=21),
        ]
        report = BacktestReport.from_trades(
            trades=trades, initial_capital=5000.0,
            equity_curve=[5000.0, 5450.0],
            strategy_name="t", symbol="BTCUSDT",
        )
        assert report.max_consecutive_wins == 3
        assert report.max_consecutive_losses == 1

    def test_consecutive_losses_with_known_sequence(self):
        """Sequência [L, L, W, L, L, L, W] → max_losses=3, max_wins=1."""
        pnls = [-50, -50, 100, -50, -50, -50, 100]
        trades = [
            _make_trade(p, entry_candle=10 + i * 2, exit_candle=11 + i * 2)
            for i, p in enumerate(pnls)
        ]
        report = BacktestReport.from_trades(
            trades=trades, initial_capital=5000.0,
            equity_curve=[5000.0, 5000.0 - 50],
            strategy_name="t", symbol="BTCUSDT",
        )
        assert report.max_consecutive_losses == 3
        assert report.max_consecutive_wins == 1


# ---------------------------------------------------------------------------
# Avg trade duration
# ---------------------------------------------------------------------------

class TestAvgTradeDuration:

    def test_avg_duration_zero_with_no_trades(self):
        report = _make_report()
        assert report.avg_trade_duration_candles == 0.0

    def test_avg_duration_correct_for_known_durations(self):
        # Durações: 5, 10, 15 → média 10.0
        report = _make_report(wins=[100.0, 100.0, 100.0], durations=[5, 10, 15])
        assert report.avg_trade_duration_candles == pytest.approx(10.0, abs=1e-2)

    def test_avg_duration_single_trade(self):
        report = _make_report(wins=[100.0], durations=[7])
        assert report.avg_trade_duration_candles == 7.0


# ---------------------------------------------------------------------------
# Risk/Reward realizado
# ---------------------------------------------------------------------------

class TestRiskRewardRealized:

    def test_rr_realized_none_with_no_trades(self):
        report = _make_report()
        assert report.risk_reward_realized_avg is None

    def test_rr_realized_negative_when_all_stop_loss(self):
        """
        Trades fechados no stop loss: pnl_usd / risk_usd ≈ -1.
        BUY: entry=65000, stop=64000 → risk_per_unit=1000, risk_pct=1000/65000≈1.538%
        position=200 → risk_usd ≈ 3.077
        Quando SL é atingido, pnl_usd ≈ -3.077 → rr ≈ -1.0
        """
        # Construção manual para garantir SL realista
        trade = BacktestTrade(
            symbol="BTCUSDT", strategy_name="t",
            entry_candle_idx=10, entry_time=_TS,
            entry_price=65000.0, stop_loss_price=64000.0,
            take_profit_price=70000.0, position_size_usd=200.0,
            side="buy", entry_price_theoretical=65000.0,
        )
        trade.close(
            exit_candle_idx=15, exit_time=_TS,
            exit_price=64000.0, close_reason=CloseReason.STOP_LOSS,
            exit_price_theoretical=64000.0,
        )
        report = BacktestReport.from_trades(
            trades=[trade], initial_capital=5000.0,
            equity_curve=[5000.0, 5000.0 + trade.pnl_usd],
            strategy_name="t", symbol="BTCUSDT",
        )
        assert report.risk_reward_realized_avg is not None
        assert report.risk_reward_realized_avg == pytest.approx(-1.0, abs=1e-2)

    def test_rr_realized_positive_when_take_profit_2to1(self):
        """
        TP atingido em R:R 2:1: pnl_usd ≈ +2 × risk_usd → rr ≈ +2.0
        BUY: entry=65000, stop=64000 (risk_per_unit=1000), tp=67000 (reward_per_unit=2000)
        """
        trade = BacktestTrade(
            symbol="BTCUSDT", strategy_name="t",
            entry_candle_idx=10, entry_time=_TS,
            entry_price=65000.0, stop_loss_price=64000.0,
            take_profit_price=67000.0, position_size_usd=200.0,
            side="buy", entry_price_theoretical=65000.0,
        )
        trade.close(
            exit_candle_idx=15, exit_time=_TS,
            exit_price=67000.0, close_reason=CloseReason.TAKE_PROFIT,
            exit_price_theoretical=67000.0,
        )
        report = BacktestReport.from_trades(
            trades=[trade], initial_capital=5000.0,
            equity_curve=[5000.0, 5000.0 + trade.pnl_usd],
            strategy_name="t", symbol="BTCUSDT",
        )
        assert report.risk_reward_realized_avg == pytest.approx(2.0, abs=1e-2)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

class TestSummaryAdvancedMetricsSection:

    def test_summary_contains_advanced_metrics_header(self):
        report = _make_report(wins=[100.0], losses=[50.0])
        summary = report.summary()
        assert "MÉTRICAS AVANÇADAS" in summary

    def test_summary_contains_expectancy_label(self):
        report = _make_report(wins=[100.0], losses=[50.0])
        summary = report.summary()
        assert "Expectancy/trade" in summary

    def test_summary_advanced_section_present_even_with_no_trades(self):
        report = _make_report()
        summary = report.summary()
        assert "MÉTRICAS AVANÇADAS" in summary
        # Métricas não calculáveis → "N/A"
        assert "N/A" in summary


# ---------------------------------------------------------------------------
# to_dict — novas chaves presentes + chaves antigas preservadas
# ---------------------------------------------------------------------------

class TestToDictAdvancedKeys:

    def test_to_dict_includes_all_new_advanced_keys(self):
        report = _make_report(wins=[100.0], losses=[50.0])
        d = report.to_dict()
        required = [
            "expectancy_usd",
            "payoff_ratio",
            "net_payoff_ratio",
            "gross_payoff_ratio",
            "net_profit_factor",
            "gross_profit_factor",
            "max_consecutive_wins",
            "max_consecutive_losses",
            "avg_trade_duration_candles",
            "risk_reward_realized_avg",
            "net_winning_pnl_sum_usd",
            "net_losing_pnl_sum_usd",
            "gross_winning_pnl_sum_usd",
            "gross_losing_pnl_sum_usd",
        ]
        for key in required:
            assert key in d, f"Chave ausente: {key}"

    def test_to_dict_still_has_all_legacy_keys(self):
        """Nenhuma chave anterior (FASE 3D / 3E.1) pode ter sumido."""
        report = _make_report(wins=[100.0])
        d = report.to_dict()
        legacy_required = [
            # FASE 3D
            "strategy_name", "symbol", "total_trades", "winning_trades", "losing_trades",
            "win_rate", "loss_rate", "total_pnl_usd", "total_pnl_pct", "final_capital",
            "peak_capital", "max_drawdown_usd", "max_drawdown_pct", "avg_win_usd",
            "avg_loss_usd", "gross_profit_usd", "gross_loss_usd",
            "largest_win_usd", "largest_loss_usd", "profit_factor",
            "challenge_profit_target_usd", "challenge_target_reached",
            "account_goal_progress_pct", "equity_curve_length",
            # FASE 3E.1
            "gross_total_pnl_usd", "net_total_pnl_usd",
            "total_fees_usd", "total_slippage_usd", "total_execution_cost_usd",
        ]
        for key in legacy_required:
            assert key in d, f"Chave LEGADA removida indevidamente: {key}"

    def test_to_dict_is_json_serializable_with_new_metrics(self):
        import json
        report = _make_report(wins=[100.0], losses=[50.0])
        json.dumps(report.to_dict())  # não deve lançar


# ---------------------------------------------------------------------------
# Garantias estruturais (challenge KPI, max_profit, etc.)
# ---------------------------------------------------------------------------

class TestStructuralGuarantees:

    def test_challenge_target_continues_kpi_only(self):
        """Mesmo com métricas avançadas, challenge target é KPI."""
        report = _make_report(wins=[600.0], challenge_target=500.0)
        assert report.challenge_target_reached is True
        # Total de trades não é afetado pela meta atingida
        assert report.total_trades == 1

    def test_no_max_profit_usd_field(self):
        report = _make_report(wins=[1000.0])
        assert not hasattr(report, "max_profit_usd")
