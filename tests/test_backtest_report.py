"""
Testes do BacktestReport — Métricas e Relatório
=================================================
⚠️  ZERO chamadas à internet.
⚠️  ZERO API keys.
⚠️  ZERO ordens reais.

Cobertura:
    - win_rate calculado corretamente
    - profit_factor calculado corretamente
    - drawdown calculado corretamente
    - Meta de challenge é APENAS KPI — não bloqueia trades
    - challenge_target_reached calculado como KPI informativo
    - Backtest sem trades → métricas válidas (não lança exceção)
    - Só vencedores → win_rate = 100%
    - Só perdedores → win_rate = 0%
    - Misto → calculado corretamente
    - equity_curve evolui corretamente
    - summary() retorna texto com avisos obrigatórios
    - to_dict() retorna chaves obrigatórias
    - HyroTrader não é dependência central
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

import pytest

from crypto_trading_bot.backtesting.backtest_report import BacktestReport, _calculate_drawdown
from crypto_trading_bot.backtesting.backtest_trade import BacktestTrade, CloseReason


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _make_trade(
    pnl: float,
    close_reason: CloseReason = CloseReason.STOP_LOSS,
    position_size: float = 200.0,
    symbol: str = "BTCUSDT",
    entry_candle: int = 10,
    exit_candle: int = 15,
) -> BacktestTrade:
    """Cria um BacktestTrade já fechado com o PnL especificado."""
    entry_price = 65000.0
    stop_price = 64000.0

    if pnl > 0:
        close_reason = CloseReason.TAKE_PROFIT
        exit_price = 65000.0 + (pnl / position_size) * 65000.0
    else:
        close_reason = CloseReason.STOP_LOSS
        exit_price = 65000.0 + (pnl / position_size) * 65000.0

    # Para stop loss: exit < entry
    if exit_price >= entry_price and pnl < 0:
        exit_price = entry_price * 0.98

    trade = BacktestTrade(
        symbol=symbol,
        strategy_name="test_strategy",
        entry_candle_idx=entry_candle,
        entry_time=_TS,
        entry_price=entry_price,
        stop_loss_price=stop_price,
        take_profit_price=67000.0 if pnl > 0 else None,
        position_size_usd=position_size,
        side="buy",
    )
    # Fecha manualmente com PnL específico
    trade.exit_candle_idx = exit_candle
    trade.exit_time = _TS
    trade.exit_price = exit_price
    trade.close_reason = close_reason
    trade.pnl_usd = round(pnl, 4)
    trade.pnl_pct = round(pnl / position_size * 100, 4)
    return trade


def _make_report(
    wins: List[float] = None,
    losses: List[float] = None,
    initial_capital: float = 5000.0,
    challenge_target: Optional[float] = None,
) -> BacktestReport:
    """Constrói BacktestReport com trades pré-definidos."""
    wins = wins or []
    losses = losses or []

    trades = []
    capital = initial_capital
    equity = [capital]

    for pnl in wins:
        trades.append(_make_trade(pnl=abs(pnl)))
        capital += abs(pnl)
        equity.append(capital)

    for pnl in losses:
        trades.append(_make_trade(pnl=-abs(pnl)))
        capital -= abs(pnl)
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
# Relatório Vazio (sem trades)
# ---------------------------------------------------------------------------

class TestEmptyReport:

    def test_empty_report_is_valid(self):
        report = _make_report()
        assert report is not None

    def test_empty_win_rate_is_zero(self):
        report = _make_report()
        assert report.win_rate == 0.0

    def test_empty_total_pnl_is_zero(self):
        report = _make_report()
        assert report.total_pnl_usd == 0.0

    def test_empty_final_capital_equals_initial(self):
        report = _make_report(initial_capital=5000.0)
        assert report.final_capital == 5000.0

    def test_empty_total_trades_is_zero(self):
        report = _make_report()
        assert report.total_trades == 0

    def test_empty_profit_factor_is_none(self):
        """Sem perdedores → profit_factor não é calculável."""
        report = _make_report()
        assert report.profit_factor is None

    def test_empty_max_drawdown_is_zero(self):
        report = _make_report()
        assert report.max_drawdown_usd == 0.0
        assert report.max_drawdown_pct == 0.0


# ---------------------------------------------------------------------------
# Win Rate
# ---------------------------------------------------------------------------

class TestWinRate:

    def test_all_winners_win_rate_100(self):
        report = _make_report(wins=[100.0, 50.0, 75.0])
        assert report.win_rate == 100.0

    def test_all_losers_win_rate_0(self):
        report = _make_report(losses=[50.0, 30.0, 20.0])
        assert report.win_rate == 0.0

    def test_mixed_win_rate_50(self):
        report = _make_report(wins=[100.0], losses=[100.0])
        assert report.win_rate == 50.0

    def test_three_wins_one_loss_win_rate_75(self):
        report = _make_report(wins=[40.0, 60.0, 50.0], losses=[30.0])
        assert report.win_rate == 75.0

    def test_win_rate_plus_loss_rate_equals_100(self):
        report = _make_report(wins=[100.0, 50.0], losses=[30.0])
        assert abs(report.win_rate + report.loss_rate - 100.0) < 0.001


# ---------------------------------------------------------------------------
# PnL e Capital
# ---------------------------------------------------------------------------

class TestPnlAndCapital:

    def test_total_pnl_is_sum_of_trades(self):
        report = _make_report(wins=[100.0, 50.0], losses=[30.0])
        expected = 100.0 + 50.0 - 30.0
        assert abs(report.total_pnl_usd - expected) < 0.01

    def test_final_capital_equals_initial_plus_pnl(self):
        initial = 5000.0
        report = _make_report(wins=[100.0], losses=[30.0], initial_capital=initial)
        expected = initial + 100.0 - 30.0
        assert abs(report.final_capital - expected) < 0.01

    def test_all_winners_positive_pnl(self):
        report = _make_report(wins=[100.0, 50.0])
        assert report.total_pnl_usd > 0

    def test_all_losers_negative_pnl(self):
        report = _make_report(losses=[50.0, 30.0])
        assert report.total_pnl_usd < 0

    def test_avg_win_correct(self):
        report = _make_report(wins=[100.0, 50.0])
        assert abs(report.avg_win_usd - 75.0) < 0.01

    def test_avg_loss_correct(self):
        report = _make_report(losses=[40.0, 60.0])
        assert abs(report.avg_loss_usd - (-50.0)) < 0.01


# ---------------------------------------------------------------------------
# Profit Factor
# ---------------------------------------------------------------------------

class TestProfitFactor:

    def test_profit_factor_correct(self):
        """PF = gross_profit / |gross_loss|"""
        report = _make_report(wins=[200.0], losses=[100.0])
        assert report.profit_factor is not None, (
            "Cenário com pelo menos 1 winner e 1 loser DEVE produzir profit_factor."
        )
        assert abs(report.profit_factor - 2.0) < 0.01

    def test_profit_factor_none_with_no_losers(self):
        """Sem perdedores → divisão por zero → None."""
        report = _make_report(wins=[100.0, 50.0])
        assert report.profit_factor is None

    def test_profit_factor_below_one_means_unprofitable(self):
        report = _make_report(wins=[50.0], losses=[100.0])
        assert report.profit_factor is not None, (
            "Cenário com winner e loser DEVE produzir profit_factor."
        )
        assert report.profit_factor < 1.0


# ---------------------------------------------------------------------------
# Drawdown
# ---------------------------------------------------------------------------

class TestDrawdown:

    def test_drawdown_zero_with_all_wins(self):
        """Apenas ganhos → drawdown DEVE ser exatamente 0."""
        report = _make_report(wins=[100.0, 200.0, 150.0])
        assert report.max_drawdown_usd == 0.0, (
            f"Drawdown deveria ser 0 com cenário só de ganhos. "
            f"Obtido: {report.max_drawdown_usd}"
        )
        assert report.max_drawdown_pct == 0.0

    def test_drawdown_negative_with_losses(self):
        """Perdas devem gerar drawdown negativo."""
        report = _make_report(losses=[100.0, 200.0])
        assert report.max_drawdown_usd < 0

    def test_drawdown_calculated_from_peak(self):
        """Drawdown deve ser calculado a partir do pico, não do capital inicial."""
        # Equity: 5000 → 5200 (+200 win) → 4900 (-300 loss)
        # Peak = 5200, valley = 4900 → drawdown = -300
        equity = [5000.0, 5200.0, 4900.0]
        peak, dd_usd, dd_pct = _calculate_drawdown(equity, 5000.0)
        assert peak == 5200.0
        assert abs(dd_usd - (-300.0)) < 0.01

    def test_drawdown_pct_correct(self):
        """Drawdown % = drawdown_usd / peak * 100"""
        equity = [5000.0, 5200.0, 4900.0]
        _, dd_usd, dd_pct = _calculate_drawdown(equity, 5000.0)
        expected_pct = -300.0 / 5200.0 * 100
        assert abs(dd_pct - expected_pct) < 0.01

    def test_empty_equity_curve_returns_zero_drawdown(self):
        _, dd_usd, dd_pct = _calculate_drawdown([], 5000.0)
        assert dd_usd == 0.0
        assert dd_pct == 0.0

    def test_drawdown_curve_peak_then_valley_then_recovery(self):
        """
        Curva 5000 → 5500 → 5200 → 6000 → 5300:
            - Subiu para 5500, caiu para 5200 (drawdown -300, mas peak=5500 ainda)
            - Subiu para 6000 (novo peak)
            - Caiu para 5300 (drawdown -700 do pico)
        Max drawdown DEVE ser -700 (do pico 6000 ao vale 5300).
        """
        equity = [5000.0, 5500.0, 5200.0, 6000.0, 5300.0]
        peak, dd_usd, dd_pct = _calculate_drawdown(equity, 5000.0)

        assert peak == 6000.0, f"Peak esperado=6000, obtido={peak}"
        assert abs(dd_usd - (-700.0)) < 0.01, (
            f"Drawdown USD esperado=-700, obtido={dd_usd}"
        )
        expected_pct = -700.0 / 6000.0 * 100
        assert abs(dd_pct - expected_pct) < 0.01

    def test_drawdown_pct_zero_for_all_wins_in_report(self):
        """No relatório com só ganhos, drawdown_pct DEVE ser 0 (não apenas <= 0)."""
        report = _make_report(wins=[100.0, 200.0, 150.0])
        assert report.max_drawdown_pct == 0.0


# ---------------------------------------------------------------------------
# Meta de Challenge — APENAS KPI, NUNCA bloqueante
# ---------------------------------------------------------------------------

class TestChallengeKpiOnly:
    """
    ⚠️  Meta de challenge é APENAS KPI informativo.
    Lucro é métrica de performance, não trava de segurança.
    """

    def test_challenge_target_reached_when_pnl_exceeds_target(self):
        """challenge_target_reached é True quando PnL >= target."""
        report = _make_report(wins=[600.0], challenge_target=500.0)
        assert report.challenge_target_reached is True

    def test_challenge_target_not_reached_when_pnl_below_target(self):
        report = _make_report(wins=[100.0], challenge_target=500.0)
        assert report.challenge_target_reached is False

    def test_challenge_target_false_when_not_configured(self):
        """Sem target configurado → False."""
        report = _make_report(wins=[1000.0])
        assert report.challenge_target_reached is False

    def test_account_goal_progress_pct_correct(self):
        """Progresso = pnl / target * 100"""
        report = _make_report(wins=[250.0], challenge_target=500.0)
        assert abs(report.account_goal_progress_pct - 50.0) < 0.01

    def test_account_goal_progress_can_exceed_100(self):
        """Progresso pode ser > 100% se PnL superou a meta."""
        report = _make_report(wins=[600.0], challenge_target=500.0)
        assert report.account_goal_progress_pct > 100.0

    def test_account_goal_progress_zero_when_no_target(self):
        report = _make_report(wins=[1000.0])
        assert report.account_goal_progress_pct == 0.0

    def test_challenge_info_in_summary(self):
        """
        challenge_target_reached aparece no summary, mas não bloqueia.

        Validação determinística (sem OR fraco): summary DEVE conter
        a marca 'KPI' (palavra-chave estável) E o valor da meta como número.
        """
        report = _make_report(wins=[600.0], challenge_target=500.0)
        summary = report.summary()
        summary_lower = summary.lower()

        # 1) Marca explícita de que é KPI informativo (não trava)
        assert "kpi" in summary_lower, (
            f"summary() deveria marcar 'KPI' como rótulo explícito do challenge. "
            f"Obtido: {summary!r}"
        )
        # 2) O valor numérico da meta aparece no summary
        assert "500" in summary, (
            f"summary() deveria conter o valor da meta (500). Obtido: {summary!r}"
        )

    def test_no_max_profit_field(self):
        """
        Não deve existir campo max_profit no BacktestReport.
        Lucro não é uma trava de segurança.
        """
        report = _make_report(wins=[1000.0])
        assert not hasattr(report, "max_profit_usd"), \
            "BacktestReport NÃO deve ter max_profit_usd bloqueante!"

    def test_challenge_does_not_stop_report_calculation(self):
        """
        Mesmo com challenge atingido, o relatório contém todos os trades.
        """
        # 3 trades: meta atingida após 1.º, mas todos devem aparecer
        report = _make_report(
            wins=[600.0, 50.0, 30.0],
            challenge_target=500.0,
        )
        assert report.total_trades == 3   # todos os 3 estão no relatório


# ---------------------------------------------------------------------------
# Summary e Serialização
# ---------------------------------------------------------------------------

class TestSummaryAndSerialization:

    def test_summary_contains_warning(self):
        """summary() DEVE conter aviso de performance futura."""
        report = _make_report(wins=[100.0])
        summary = report.summary()
        assert "não garantem" in summary.lower() or "não garante" in summary.lower()

    def test_summary_contains_pnl(self):
        report = _make_report(wins=[100.0], losses=[50.0])
        summary = report.summary()
        assert "50" in summary or "pnl" in summary.lower()

    def test_to_dict_has_required_keys(self):
        report = _make_report(wins=[100.0])
        d = report.to_dict()
        for key in [
            "strategy_name", "total_trades", "winning_trades", "losing_trades",
            "win_rate", "total_pnl_usd", "final_capital", "max_drawdown_usd",
            "challenge_target_reached", "account_goal_progress_pct",
        ]:
            assert key in d, f"Chave ausente: {key}"

    def test_to_dict_challenge_keys_present(self):
        report = _make_report(wins=[100.0], challenge_target=500.0)
        d = report.to_dict()
        assert "challenge_profit_target_usd" in d
        assert "challenge_target_reached" in d
        assert "account_goal_progress_pct" in d

    def test_repr_contains_strategy_name(self):
        report = _make_report()
        r = repr(report)
        assert "test_strategy" in r

    def test_report_is_serializable(self):
        """to_dict deve produzir dicionário serializável."""
        report = _make_report(wins=[100.0], losses=[50.0])
        d = report.to_dict()
        import json
        json.dumps(d)  # não deve lançar exceção


# ---------------------------------------------------------------------------
# Agnóstico de Provider
# ---------------------------------------------------------------------------

class TestReportProviderAgnostic:
    """Relatório não depende de HyroTrader como dependência central."""

    def test_report_does_not_reference_hyrotrader_in_logic(self):
        """BacktestReport não deve ter lógica específica de HyroTrader."""
        report = _make_report(wins=[100.0])
        # O relatório não deve ter campo provider_name bloqueante
        d = report.to_dict()
        # Não deve existir lógica que varia por provider
        assert "hyrotrader" not in str(d).lower(), \
            "Relatório não deve ter referência hardcoded a HyroTrader!"

    def test_same_report_for_any_provider(self):
        """Relatório com mesmos trades deve ser idêntico independente do provider."""
        report1 = _make_report(wins=[100.0, 50.0], losses=[30.0])
        report2 = _make_report(wins=[100.0, 50.0], losses=[30.0])
        assert report1.win_rate == report2.win_rate
        assert report1.total_pnl_usd == report2.total_pnl_usd
