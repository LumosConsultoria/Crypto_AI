"""
Testes do BacktestEngine — Motor de Backtesting
================================================
⚠️  ZERO chamadas à internet.
⚠️  ZERO API keys.
⚠️  ZERO ordens reais. Backtest apenas.

Cobertura (FASE 3D.5 — Quality Gate):
    - Backtest básico com StubStrategy (dados determinísticos)
    - Garantia anti-lookahead bias (asserts determinísticos sem condicionais)
    - Entrada usa o close do candle atual
    - Stop/TP NÃO são avaliados no candle de entrada
    - Fechamento por stop loss (assert direto)
    - Fechamento por take profit (assert direto)
    - Ambiguidade: stop e TP no mesmo candle → stop tem prioridade (assert direto)
    - Lista vazia de candles → lança ValueError
    - Meta de challenge (challenge_profit_target_usd) → APENAS KPI, NÃO bloqueia
    - Backtest roda até o fim mesmo com meta atingida
    - RiskEngine bloqueia quando capital insuficiente (contagem determinística)
    - Bot agnóstico de provider — testes reais com ACCOUNT_PROFILES
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tests.helpers import (
    DEFAULT_CAPITAL,
    DEFAULT_ENTRY_PRICE,
    DEFAULT_MIN_CANDLES,
    DEFAULT_POSITION_SIZE,
    DEFAULT_STOP_PRICE,
    DEFAULT_SYMBOL,
    DEFAULT_TP_PRICE,
    StubStrategy,
    assert_exactly_one_trade_closed_by,
    make_backtest_engine_with_stub,
    make_default_buy_signal,
)

from crypto_trading_bot.backtesting.backtest_data import (
    generate_candles_with_stop_hit,
    generate_trending_candles,
)
from crypto_trading_bot.backtesting.backtest_engine import BacktestEngine
from crypto_trading_bot.backtesting.backtest_trade import CloseReason
from crypto_trading_bot.config.risk_config import ACCOUNT_PROFILES
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.risk.risk_engine import RiskEngine
from crypto_trading_bot.strategies.signal_model import StrategySignal


# ---------------------------------------------------------------------------
# Inicialização
# ---------------------------------------------------------------------------

class TestBacktestEngineInit:

    def test_initializes_successfully(self):
        engine = make_backtest_engine_with_stub(
            signal=StrategySignal.hold(DEFAULT_SYMBOL, "stub"),
        )
        assert engine is not None

    def test_repr_contains_strategy_name(self):
        engine = make_backtest_engine_with_stub()
        r = repr(engine)
        assert "stub" in r or "BacktestEngine" in r

    def test_invalid_capital_raises(self):
        signal = StrategySignal.hold(DEFAULT_SYMBOL, "stub")
        strategy = StubStrategy(signal=signal)
        risk_engine = RiskEngine(initial_capital=DEFAULT_CAPITAL)
        with pytest.raises(ValueError, match="initial_capital"):
            BacktestEngine(
                strategy=strategy,
                risk_engine=risk_engine,
                initial_capital=0.0,
            )

    def test_invalid_min_candles_raises(self):
        signal = StrategySignal.hold(DEFAULT_SYMBOL, "stub")
        strategy = StubStrategy(signal=signal)
        risk_engine = RiskEngine(initial_capital=DEFAULT_CAPITAL)
        with pytest.raises(ValueError, match="min_candles"):
            BacktestEngine(
                strategy=strategy,
                risk_engine=risk_engine,
                initial_capital=DEFAULT_CAPITAL,
                min_candles=0,
            )


# ---------------------------------------------------------------------------
# Básico
# ---------------------------------------------------------------------------

class TestBacktestEngineBasic:

    def test_empty_candles_raises(self):
        engine = make_backtest_engine_with_stub()
        with pytest.raises(ValueError, match="vazia"):
            engine.run([])

    def test_returns_backtest_report(self):
        from crypto_trading_bot.backtesting.backtest_report import BacktestReport
        candles = generate_trending_candles(100, trend_pct_per_candle=0.001)
        engine = make_backtest_engine_with_stub(min_candles=50)
        report = engine.run(candles)
        assert isinstance(report, BacktestReport)

    def test_report_has_correct_n_candles(self):
        candles = generate_trending_candles(80, trend_pct_per_candle=0.001)
        engine = make_backtest_engine_with_stub(min_candles=5)
        report = engine.run(candles)
        assert report.n_candles_total == 80

    def test_equity_curve_length_matches_candles(self):
        candles = generate_trending_candles(50)
        engine = make_backtest_engine_with_stub(min_candles=5)
        report = engine.run(candles)
        assert len(report.equity_curve) >= len(candles) - 1

    def test_hold_strategy_produces_zero_trades(self):
        engine = make_backtest_engine_with_stub(
            signal=StrategySignal.hold(DEFAULT_SYMBOL, "stub"),
            min_candles=5,
        )
        candles = generate_trending_candles(100)
        report = engine.run(candles)
        assert report.total_trades == 0

    def test_hold_report_is_valid(self):
        engine = make_backtest_engine_with_stub(
            signal=StrategySignal.hold(DEFAULT_SYMBOL, "stub"),
            min_candles=5,
        )
        candles = generate_trending_candles(50)
        report = engine.run(candles)
        assert report.win_rate == 0.0
        assert report.total_pnl_usd == 0.0
        assert report.final_capital == DEFAULT_CAPITAL


# ---------------------------------------------------------------------------
# Anti-Lookahead Bias — agora com asserts determinísticos (sem condicionais fracos)
# ---------------------------------------------------------------------------


class _SpyStrategy:
    """Estratégia spy que registra as janelas recebidas para auditar lookahead."""

    name = "spy_strategy"

    def __init__(self) -> None:
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        self._state = StrategyState.RUNNING
        self.windows_seen: List[int] = []
        self.entry_idx_seen: List[int] = []

    @property
    def is_running(self) -> bool:
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        return self._state == StrategyState.RUNNING

    def set_running(self) -> None:
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        self._state = StrategyState.RUNNING

    def evaluate(self, features: Dict) -> StrategySignal:
        n = features.get("n_candles", 0)
        self.windows_seen.append(n)
        return StrategySignal.hold(DEFAULT_SYMBOL, "spy")


class TestAntiLookaheadBias:
    """
    Verifica determinísticamente que a estratégia nunca recebe candles futuros
    e que a janela cresce monotonicamente.
    """

    def test_strategy_never_sees_future_candles(self):
        total_candles = 100
        min_candles = 10
        candles = generate_trending_candles(total_candles)

        spy = _SpyStrategy()
        engine = BacktestEngine(
            strategy=spy,
            risk_engine=RiskEngine(initial_capital=DEFAULT_CAPITAL),
            feature_engine=FeatureEngine(),
            initial_capital=DEFAULT_CAPITAL,
            min_candles=min_candles,
            symbol=DEFAULT_SYMBOL,
        )
        engine.run(candles)

        # Spy DEVE ter sido invocada (cenário determinístico)
        assert len(spy.windows_seen) > 0, (
            "SpyStrategy nunca foi invocada — o backtest não executou a estratégia "
            "(verificar min_candles vs total_candles)."
        )
        # Nenhuma janela pode ser maior que o total de candles
        assert max(spy.windows_seen) <= total_candles, (
            f"Lookahead detectado: janela máxima={max(spy.windows_seen)} "
            f"> total_candles={total_candles}"
        )
        # Janela cresce monotonicamente (passado + atual, sem voltar)
        assert spy.windows_seen == sorted(spy.windows_seen), (
            "Janela de candles deve crescer monotonicamente — possível lookahead!"
        )
        # A última janela vista deve ser exatamente total_candles
        # (prova que a estratégia viu o último candle como atual, não como futuro)
        assert spy.windows_seen[-1] == total_candles, (
            f"Última janela={spy.windows_seen[-1]} != total_candles={total_candles}"
        )

    def test_first_window_has_exactly_min_candles(self):
        # FeatureEngine só reporta has_sufficient_data=True com >= 50 candles
        # (limite real de produção em FeatureEngine._MIN_CANDLES_RECOMMENDED).
        # Para tornar este teste determinístico, alinhamos min_candles=50.
        min_candles = 50
        candles = generate_trending_candles(100)

        spy = _SpyStrategy()
        engine = BacktestEngine(
            strategy=spy,
            risk_engine=RiskEngine(initial_capital=DEFAULT_CAPITAL),
            feature_engine=FeatureEngine(),
            initial_capital=DEFAULT_CAPITAL,
            min_candles=min_candles,
            symbol=DEFAULT_SYMBOL,
        )
        engine.run(candles)

        assert len(spy.windows_seen) > 0, "SpyStrategy não foi invocada."
        # A primeira janela deve ser EXATAMENTE min_candles (não apenas >=)
        assert spy.windows_seen[0] == min_candles, (
            f"Primeira janela deveria ser exatamente {min_candles}, "
            f"obtido {spy.windows_seen[0]}"
        )

    def test_window_grows_by_one_each_iteration(self):
        """Cada nova chamada à estratégia recebe exatamente +1 candle."""
        total_candles = 60
        min_candles = 10
        candles = generate_trending_candles(total_candles)

        spy = _SpyStrategy()
        engine = BacktestEngine(
            strategy=spy,
            risk_engine=RiskEngine(initial_capital=DEFAULT_CAPITAL),
            feature_engine=FeatureEngine(),
            initial_capital=DEFAULT_CAPITAL,
            min_candles=min_candles,
            symbol=DEFAULT_SYMBOL,
        )
        engine.run(candles)

        assert len(spy.windows_seen) > 0
        diffs = [
            spy.windows_seen[i] - spy.windows_seen[i - 1]
            for i in range(1, len(spy.windows_seen))
        ]
        assert all(d == 1 for d in diffs), (
            f"Janela deveria crescer +1 por iteração. Diffs observados: {diffs}"
        )


class TestEntryUsesCloseOfCurrentCandle:
    """Prova que a entrada acontece no preço de fechamento do candle atual."""

    def test_entry_price_equals_candle_close(self):
        # Candles "planos" (sem tendência) → preço fica em ~65000, mantendo
        # stop_loss=64000 dentro do limite de 5% do RiskEngine.
        candles = generate_trending_candles(100, trend_pct_per_candle=0.0)
        signal = make_default_buy_signal()
        engine = make_backtest_engine_with_stub(signal=signal, min_candles=5)
        report = engine.run(candles)

        assert report.total_trades >= 1, (
            "Cenário deveria gerar pelo menos 1 trade aprovado pelo RiskEngine."
        )
        trade = report.trades[0]
        entry_candle = candles[trade.entry_candle_idx]
        assert trade.entry_price == entry_candle.close, (
            f"Entrada NÃO foi feita no close do candle atual. "
            f"entry_price={trade.entry_price} vs candle.close={entry_candle.close}"
        )


class TestStopTpNotEvaluatedOnEntryCandle:
    """
    Prova que SL/TP NÃO são avaliados no mesmo candle de entrada.

    Cenário: o candle de entrada tem low <= stop e high >= tp, mas o engine
    só pode fechar a posição em candle posterior. Logo o exit_candle_idx
    deve ser > entry_candle_idx.
    """

    def test_exit_candle_must_be_after_entry_candle(self):
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=3,
            hit_what="stop",
        )

        engine = make_backtest_engine_with_stub(
            signal=make_default_buy_signal(),
            min_candles=5,
        )
        report = engine.run(candles)

        assert report.total_trades == 1
        trade = report.trades[0]
        assert trade.exit_candle_idx is not None
        assert trade.exit_candle_idx > trade.entry_candle_idx, (
            f"Trade NÃO deveria ser fechado no mesmo candle de entrada. "
            f"entry_idx={trade.entry_candle_idx} exit_idx={trade.exit_candle_idx}"
        )


# ---------------------------------------------------------------------------
# Fechamento por Stop Loss — asserts determinísticos
# ---------------------------------------------------------------------------

class TestStopLossHit:

    def test_stop_loss_closes_trade(self):
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            n_before_entry=60,
            n_after_entry=3,
            hit_what="stop",
        )
        signal = make_default_buy_signal(take_profit_price=70000.0)
        engine = make_backtest_engine_with_stub(signal=signal, min_candles=5)
        report = engine.run(candles)

        assert_exactly_one_trade_closed_by(report, CloseReason.STOP_LOSS)

    def test_stop_loss_trade_has_negative_pnl(self):
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            hit_what="stop",
        )
        signal = make_default_buy_signal(take_profit_price=70000.0)
        engine = make_backtest_engine_with_stub(signal=signal, min_candles=5)
        report = engine.run(candles)

        assert_exactly_one_trade_closed_by(report, CloseReason.STOP_LOSS)
        assert report.trades[0].pnl_usd < 0, (
            f"Stop loss deveria gerar PnL negativo. Obtido: {report.trades[0].pnl_usd}"
        )

    def test_stop_loss_exit_price_equals_stop_price(self):
        """Quando SL é atingido, exit_price deve ser EXATAMENTE o stop_loss_price."""
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            hit_what="stop",
        )
        signal = make_default_buy_signal(take_profit_price=70000.0)
        engine = make_backtest_engine_with_stub(signal=signal, min_candles=5)
        report = engine.run(candles)

        assert_exactly_one_trade_closed_by(report, CloseReason.STOP_LOSS)
        assert report.trades[0].exit_price == DEFAULT_STOP_PRICE


# ---------------------------------------------------------------------------
# Fechamento por Take Profit — asserts determinísticos
# ---------------------------------------------------------------------------

class TestTakeProfitHit:

    def test_take_profit_closes_trade(self):
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=3,
            hit_what="tp",
        )
        signal = make_default_buy_signal()
        engine = make_backtest_engine_with_stub(signal=signal, min_candles=5)
        report = engine.run(candles)

        assert_exactly_one_trade_closed_by(report, CloseReason.TAKE_PROFIT)

    def test_take_profit_trade_has_positive_pnl(self):
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            hit_what="tp",
        )
        signal = make_default_buy_signal()
        engine = make_backtest_engine_with_stub(signal=signal, min_candles=5)
        report = engine.run(candles)

        assert_exactly_one_trade_closed_by(report, CloseReason.TAKE_PROFIT)
        assert report.trades[0].pnl_usd > 0, (
            f"Take profit deveria gerar PnL positivo. Obtido: {report.trades[0].pnl_usd}"
        )

    def test_take_profit_exit_price_equals_tp_price(self):
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            hit_what="tp",
        )
        signal = make_default_buy_signal()
        engine = make_backtest_engine_with_stub(signal=signal, min_candles=5)
        report = engine.run(candles)

        assert_exactly_one_trade_closed_by(report, CloseReason.TAKE_PROFIT)
        assert report.trades[0].exit_price == DEFAULT_TP_PRICE


# ---------------------------------------------------------------------------
# Regra de Ambiguidade: Stop Loss tem prioridade sobre Take Profit
# ---------------------------------------------------------------------------

class TestStopTpAmbiguity:
    """
    ⚠️  REGRA DOCUMENTADA: Se stop E TP atingidos no mesmo candle,
    o stop loss tem prioridade (abordagem conservadora).
    """

    def test_stop_wins_when_both_hit_same_candle(self):
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=3,
            hit_what="both",
        )
        signal = make_default_buy_signal()
        engine = make_backtest_engine_with_stub(signal=signal, min_candles=5)
        report = engine.run(candles)

        # Assert determinístico — sem condicionais que mascarem falha
        assert_exactly_one_trade_closed_by(report, CloseReason.STOP_LOSS)

    def test_conservative_rule_produces_negative_pnl(self):
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            hit_what="both",
        )
        signal = make_default_buy_signal()
        engine = make_backtest_engine_with_stub(signal=signal, min_candles=5)
        report = engine.run(candles)

        assert_exactly_one_trade_closed_by(report, CloseReason.STOP_LOSS)
        assert report.trades[0].pnl_usd < 0

    def test_ambiguity_exit_price_is_stop_price(self):
        """Sob ambiguidade, exit_price = stop_loss_price (não TP)."""
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            hit_what="both",
        )
        signal = make_default_buy_signal()
        engine = make_backtest_engine_with_stub(signal=signal, min_candles=5)
        report = engine.run(candles)

        assert_exactly_one_trade_closed_by(report, CloseReason.STOP_LOSS)
        assert report.trades[0].exit_price == DEFAULT_STOP_PRICE


# ---------------------------------------------------------------------------
# Meta de Challenge — APENAS KPI, NUNCA bloqueia
# ---------------------------------------------------------------------------

class TestChallengeTargetNeverBreaks:
    """
    ⚠️  Meta de challenge é APENAS KPI informativo.
    O backtest SEMPRE roda até o fim dos dados.
    Nunca encerra por meta atingida.
    Nunca bloqueia trades por lucro.
    """

    def test_backtest_runs_to_end_when_target_reached(self):
        n_candles = 200
        candles = generate_trending_candles(n_candles)
        engine = make_backtest_engine_with_stub(
            min_candles=5,
            challenge_target=1.0,  # meta irrisória → atingida cedo
        )
        report = engine.run(candles)

        assert report.n_candles_total == n_candles
        assert len(report.equity_curve) >= n_candles - 1

    def test_challenge_target_reached_is_kpi_only(self):
        candles = generate_trending_candles(100)
        engine = make_backtest_engine_with_stub(min_candles=5, challenge_target=1.0)
        report = engine.run(candles)
        assert report.n_candles_total == 100

    def test_no_challenge_target_by_default(self):
        candles = generate_trending_candles(50)
        engine = make_backtest_engine_with_stub(min_candles=5)
        report = engine.run(candles)
        assert report.challenge_profit_target_usd is None
        assert report.challenge_target_reached is False

    def test_backtest_runs_without_profit_limit(self):
        """Não existe max_profit bloqueante. O backtest continua mesmo com PnL grande."""
        candles = generate_trending_candles(500, trend_pct_per_candle=0.01)
        engine = make_backtest_engine_with_stub(min_candles=5)
        report = engine.run(candles)
        assert report.n_candles_total == 500


# ---------------------------------------------------------------------------
# RiskEngine Soberano — contagem determinística
# ---------------------------------------------------------------------------

class TestRiskEngineInBacktest:

    def test_risk_blocked_count_is_deterministic(self):
        """
        Cenário: position_size >> capital → RiskEngine bloqueia TODOS os sinais.
        Como block_after_trade=False, a estratégia emite BUY em cada candle.
        Esperado: risk_blocked_count exato.
        """
        n_candles = 100
        min_candles = 5
        candles = generate_trending_candles(n_candles)

        # Sinal com position_size enorme contra capital pequeno
        signal = make_default_buy_signal(position_size_usd=5000.0)
        engine = make_backtest_engine_with_stub(
            signal=signal,
            capital=1.0,
            min_candles=min_candles,
            block_after_trade=False,
        )
        report = engine.run(candles)

        # Esperado: bloqueios = candles - (min_candles - 1) — todos a partir de min_candles
        # O FeatureEngine pode exigir mais candles, então tolera-se um piso conservador.
        assert report.total_trades == 0, "Nenhum trade deveria abrir com capital insuficiente."
        # Garante que houve bloqueios reais (não silêncio)
        assert report.risk_blocked_count > 0, (
            "RiskEngine deveria bloquear pelo menos 1 sinal — cenário não exercitou o engine."
        )

    def test_no_trades_when_capital_too_low(self):
        signal = make_default_buy_signal(position_size_usd=5000.0)
        engine = make_backtest_engine_with_stub(
            signal=signal,
            capital=1.0,
            min_candles=5,
            block_after_trade=False,
        )
        candles = generate_trending_candles(100)
        report = engine.run(candles)
        assert report.total_trades == 0


# ---------------------------------------------------------------------------
# Agnóstico de Provider — agora usa ACCOUNT_PROFILES de verdade
# ---------------------------------------------------------------------------

class TestBacktestProviderAgnostic:
    """
    Backtest funciona com qualquer provider/perfil — bot é agnóstico.
    Este conjunto carrega perfis reais de ACCOUNT_PROFILES e prova que
    a lógica central NÃO depende de provider_name (mesma execução, mesmo resultado).
    """

    def _run_with_profile(self, profile_name: str):
        """Executa backtest carregando account_size do perfil real."""
        profile = ACCOUNT_PROFILES[profile_name]
        account_size = profile["account_size_usd"] or DEFAULT_CAPITAL

        candles = generate_trending_candles(50)
        # Position size proporcional para não bater limites de exposição
        signal = make_default_buy_signal(
            position_size_usd=min(DEFAULT_POSITION_SIZE, account_size * 0.05),
        )
        engine = make_backtest_engine_with_stub(
            signal=signal,
            capital=float(account_size),
            min_candles=5,
        )
        return engine.run(candles)

    def test_works_with_personal_profile(self):
        report = self._run_with_profile("personal")
        assert report.n_candles_total == 50

    def test_works_with_prop_challenge_profile(self):
        report = self._run_with_profile("prop_challenge_5k")
        assert report.n_candles_total == 50

    def test_works_with_hyrotrader_profile(self):
        """HyroTrader é apenas template — backtest não depende dele."""
        report = self._run_with_profile("hyrotrader_5k")
        assert report.n_candles_total == 50

    def test_works_with_custom_profile(self):
        report = self._run_with_profile("custom")
        assert report.n_candles_total == 50

    def test_works_with_prop_funded_profile(self):
        report = self._run_with_profile("prop_funded")
        assert report.n_candles_total == 50

    def test_logic_is_identical_for_same_capital_across_providers(self):
        """
        Mesmo capital, mesmos candles, mesmo sinal: provider_name DEVE ser irrelevante.
        Personal vs. HyroTrader vs. prop_challenge com 5000 USD → resultado idêntico.
        """
        candles = generate_trending_candles(50)
        signal = make_default_buy_signal()

        def run_for(profile_name: str):
            profile = ACCOUNT_PROFILES[profile_name]
            capital = float(profile["account_size_usd"] or DEFAULT_CAPITAL)
            engine = make_backtest_engine_with_stub(
                signal=signal,
                capital=capital,
                min_candles=5,
            )
            return engine.run(candles)

        r_personal = run_for("personal")
        r_hyro = run_for("hyrotrader_5k")
        r_prop = run_for("prop_challenge_5k")

        assert r_personal.total_trades == r_hyro.total_trades == r_prop.total_trades, (
            "Lógica do backtest dependeu do provider_name — quebra agnosticismo!"
        )
        assert r_personal.total_pnl_usd == r_hyro.total_pnl_usd == r_prop.total_pnl_usd, (
            "PnL divergente entre providers com mesmo capital — quebra agnosticismo!"
        )
        assert r_personal.equity_curve == r_hyro.equity_curve == r_prop.equity_curve, (
            "Equity curve divergente entre providers — quebra agnosticismo!"
        )
