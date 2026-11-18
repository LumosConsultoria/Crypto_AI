"""
Testes de latência simulada — FASE 3E.4B
==========================================
⚠️  ZERO chamadas à internet.
⚠️  ZERO API keys.
⚠️  ZERO ordens reais.

Cobertura:
    - ExecutionCostConfig.entry_latency_candles (default, validação, is_zero).
    - Regressão BYTE-A-BYTE com entry_latency_candles=0.
    - Latência 1: executa no `open` do próximo candle.
    - Latência N: executa no `open` do candle i+N.
    - Pending signal não acessa candles futuros (anti-lookahead preservado).
    - Estratégia NÃO é chamada enquanto há pending.
    - Pending expira sem trade se candle de execução não existe.
    - Expiração NÃO incrementa risk_blocked_count.
    - RiskEngine REVALIDA pending no candle de execução.
    - Revalidação rejeitada incrementa risk_blocked_count uma única vez.
    - Stop/take usam valores ORIGINAIS do sinal.
    - SL/TP NÃO são avaliados no candle de entrada (mesmo com latência).
    - Challenge target continua apenas KPI com latência.
    - Walk-forward propaga latência via ExecutionCostConfig.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

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
from crypto_trading_bot.backtesting.execution_costs import ExecutionCostConfig
from crypto_trading_bot.backtesting.walk_forward import run_walk_forward
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.risk.risk_engine import RiskEngine
from crypto_trading_bot.strategies.signal_model import StrategySignal


# ---------------------------------------------------------------------------
# ExecutionCostConfig — campo entry_latency_candles
# ---------------------------------------------------------------------------

class TestExecutionCostConfigLatency:

    def test_default_latency_is_zero(self):
        cfg = ExecutionCostConfig()
        assert cfg.entry_latency_candles == 0

    def test_is_zero_remains_true_with_latency_zero(self):
        cfg = ExecutionCostConfig(entry_latency_candles=0)
        assert cfg.is_zero is True

    def test_is_zero_false_with_latency_nonzero(self):
        cfg = ExecutionCostConfig(entry_latency_candles=1)
        assert cfg.is_zero is False

    def test_negative_latency_raises(self):
        with pytest.raises(ValueError, match="entry_latency_candles"):
            ExecutionCostConfig(entry_latency_candles=-1)


# ---------------------------------------------------------------------------
# Regressão BYTE-A-BYTE: latency=0 produz comportamento idêntico ao da 3E.4A
# ---------------------------------------------------------------------------

class TestZeroLatencyRegression:
    """
    Compara backtests com config=None (caminho 3E.4A) vs.
    config=ExecutionCostConfig(entry_latency_candles=0).
    Resultados devem ser BYTE-A-BYTE idênticos.
    """

    def _pair(self, candles, *, signal=None):
        signal = signal or make_default_buy_signal()
        engine_a = make_backtest_engine_with_stub(
            signal=signal,
            min_candles=DEFAULT_MIN_CANDLES,
            execution_cost_config=None,
        )
        engine_b = make_backtest_engine_with_stub(
            signal=signal,
            min_candles=DEFAULT_MIN_CANDLES,
            execution_cost_config=ExecutionCostConfig(entry_latency_candles=0),
        )
        return engine_a.run(candles), engine_b.run(candles)

    def test_zero_latency_total_trades_identical(self):
        candles = generate_trending_candles(100)
        r1, r2 = self._pair(candles)
        assert r1.total_trades == r2.total_trades

    def test_zero_latency_equity_curve_identical(self):
        candles = generate_trending_candles(100, trend_pct_per_candle=0.0)
        r1, r2 = self._pair(candles)
        assert r1.equity_curve == r2.equity_curve

    def test_zero_latency_stop_loss_scenario_identical(self):
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=3,
            hit_what="stop",
        )
        r1, r2 = self._pair(candles)
        assert r1.total_trades == r2.total_trades == 1
        t1, t2 = r1.trades[0], r2.trades[0]
        assert t1.entry_candle_idx == t2.entry_candle_idx
        assert t1.entry_price == t2.entry_price
        assert t1.exit_price == t2.exit_price
        assert t1.close_reason == t2.close_reason
        assert t1.pnl_usd == t2.pnl_usd

    def test_zero_latency_take_profit_scenario_identical(self):
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=3,
            hit_what="tp",
        )
        r1, r2 = self._pair(candles)
        assert r1.total_pnl_usd == r2.total_pnl_usd
        assert r1.final_capital == r2.final_capital

    def test_zero_latency_ambiguity_scenario_identical(self):
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=3,
            hit_what="both",
        )
        r1, r2 = self._pair(candles)
        assert r1.total_trades == r2.total_trades == 1
        assert r1.trades[0].close_reason == r2.trades[0].close_reason == CloseReason.STOP_LOSS


# ---------------------------------------------------------------------------
# Latência 1: executa no `open` do próximo candle
# ---------------------------------------------------------------------------

class TestLatencyOneCandleExecution:

    def _scenario(self):
        """Cenário TP determinístico — garante 1 trade."""
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=10,  # margem para latência + SL/TP
            hit_what="tp",
        )
        engine = make_backtest_engine_with_stub(
            signal=make_default_buy_signal(),
            min_candles=DEFAULT_MIN_CANDLES,
            execution_cost_config=ExecutionCostConfig(entry_latency_candles=1),
        )
        report = engine.run(candles)
        return candles, report

    def test_latency_one_produces_trade(self):
        _, report = self._scenario()
        assert report.total_trades == 1

    def test_latency_one_entry_candle_idx_is_signal_idx_plus_one(self):
        """
        Estratégia é chamada pela primeira vez em i=49 (FeatureEngine kicka em 50 candles).
        Com latência 1, trade é EXECUTADO em i=50.
        """
        _, report = self._scenario()
        trade = report.trades[0]
        assert trade.entry_candle_idx == 50, (
            f"Esperado entry_candle_idx=50 (49+1 latência), obtido {trade.entry_candle_idx}"
        )

    def test_latency_one_entry_price_theoretical_equals_next_candle_open(self):
        """entry_price_theoretical (sem custos) == candles[50].open."""
        candles, report = self._scenario()
        trade = report.trades[0]
        assert trade.entry_price_theoretical == candles[50].open

    def test_latency_one_entry_price_equals_executed_open(self):
        """Sem custos: entry_price == entry_price_theoretical == candles[50].open."""
        candles, report = self._scenario()
        trade = report.trades[0]
        # ExecutionCostConfig só tem latency, sem fee/slippage/spread →
        # entry_executed == entry_theoretical == open do candle de execução
        assert trade.entry_price == candles[50].open


# ---------------------------------------------------------------------------
# Latência N: executa no `open` do candle i+N
# ---------------------------------------------------------------------------

class TestLatencyMultipleCandles:

    @pytest.mark.parametrize("latency", [2, 3, 5])
    def test_latency_n_entry_candle_idx_is_signal_plus_n(self, latency):
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=15,  # margem confortável
            hit_what="tp",
        )
        engine = make_backtest_engine_with_stub(
            signal=make_default_buy_signal(),
            min_candles=DEFAULT_MIN_CANDLES,
            execution_cost_config=ExecutionCostConfig(entry_latency_candles=latency),
        )
        report = engine.run(candles)
        assert report.total_trades == 1
        trade = report.trades[0]
        # Sinal gerado em i=49 (primeira janela com 50 candles)
        assert trade.entry_candle_idx == 49 + latency

    def test_latency_n_entry_price_equals_open_of_execution_candle(self):
        latency = 3
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=15,
            hit_what="tp",
        )
        engine = make_backtest_engine_with_stub(
            signal=make_default_buy_signal(),
            min_candles=DEFAULT_MIN_CANDLES,
            execution_cost_config=ExecutionCostConfig(entry_latency_candles=latency),
        )
        report = engine.run(candles)
        trade = report.trades[0]
        expected_idx = 49 + latency
        assert trade.entry_price == candles[expected_idx].open


# ---------------------------------------------------------------------------
# Pending signal não acessa candles futuros + estratégia bloqueada com pending
# ---------------------------------------------------------------------------

class _SpyStubStrategy:
    """
    Spy strategy: retorna BUY apenas na primeira chamada actionable; HOLD depois.
    Registra (idx_call, n_candles_window) a cada chamada de evaluate().

    Útil para verificar:
      - Anti-lookahead: janelas monotônicas.
      - Bloqueio durante pending: número de chamadas reduzido quando há pending.
    """

    name = "spy_stub"

    def __init__(self, buy_signal: StrategySignal):
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        self._state = StrategyState.RUNNING
        self._buy_signal = buy_signal
        self._buy_sent = False
        self.windows_seen: List[int] = []

    @property
    def is_running(self) -> bool:
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        return self._state == StrategyState.RUNNING

    def set_running(self) -> None:
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        self._state = StrategyState.RUNNING

    def evaluate(self, features: Dict[str, Any]) -> StrategySignal:
        self.windows_seen.append(features.get("n_candles", 0))
        if self._buy_sent:
            return StrategySignal.hold(DEFAULT_SYMBOL, self.name)
        self._buy_sent = True
        return self._buy_signal

    def on_signal_approved(self, signal) -> None:
        pass

    def on_signal_rejected(self, signal, reason: str) -> None:
        pass


class TestPendingSignalAntiLookahead:

    def test_pending_does_not_make_strategy_see_future_candles(self):
        """Janelas vistas pela estratégia continuam monotônicas crescentes com latência."""
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=10,
            hit_what="tp",
        )
        spy = _SpyStubStrategy(make_default_buy_signal())
        engine = BacktestEngine(
            strategy=spy,
            risk_engine=RiskEngine(initial_capital=DEFAULT_CAPITAL),
            feature_engine=FeatureEngine(),
            initial_capital=DEFAULT_CAPITAL,
            min_candles=DEFAULT_MIN_CANDLES,
            symbol=DEFAULT_SYMBOL,
            execution_cost_config=ExecutionCostConfig(entry_latency_candles=3),
        )
        engine.run(candles)

        assert len(spy.windows_seen) > 0, "Spy nunca foi chamada — backtest não executou"
        assert spy.windows_seen == sorted(spy.windows_seen), (
            "Janelas não monotônicas — possível lookahead!"
        )
        assert max(spy.windows_seen) <= len(candles)

    def test_strategy_not_called_while_pending_active(self):
        """
        Com latência 5: spy gera BUY em i=49 → pending criado.
        Pending executa em i=54. Entre 49 e 54 a estratégia NÃO é chamada.
        """
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=15,
            hit_what="tp",
        )
        spy = _SpyStubStrategy(make_default_buy_signal())
        engine = BacktestEngine(
            strategy=spy,
            risk_engine=RiskEngine(initial_capital=DEFAULT_CAPITAL),
            feature_engine=FeatureEngine(),
            initial_capital=DEFAULT_CAPITAL,
            min_candles=DEFAULT_MIN_CANDLES,
            symbol=DEFAULT_SYMBOL,
            execution_cost_config=ExecutionCostConfig(entry_latency_candles=5),
        )
        engine.run(candles)

        # spy.windows_seen contém o tamanho da janela em cada chamada.
        # Primeira chamada = i=49 → window=50. BUY → pending criado.
        # Próxima chamada possível seria i=50, mas pending bloqueia.
        # Pending executa em i=54 → abre trade.
        # Trade fica aberto até TP. Estratégia bloqueada por open_trade.
        # Logo: deve haver exatamente 1 chamada com window=50 (i=49).
        assert spy.windows_seen[0] == 50
        # Não deve haver chamadas com window=51, 52, 53, 54 (pending bloqueando)
        for forbidden in (51, 52, 53, 54):
            assert forbidden not in spy.windows_seen, (
                f"Estratégia foi chamada com window={forbidden} durante o pending — bug!"
            )


# ---------------------------------------------------------------------------
# Pending expiration
# ---------------------------------------------------------------------------

class TestPendingSignalExpiration:

    def test_pending_expires_when_no_future_candle_available(self):
        """
        Latência absurdamente alta (100) com cenário de 65 candles:
        pending criado em i=49, esperaria executar em i=149 — nunca chega.
        Backtest termina sem trade.
        """
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=3,
            hit_what="tp",
        )
        # Total ~65 candles; latência 100 garante expiração
        engine = make_backtest_engine_with_stub(
            signal=make_default_buy_signal(),
            min_candles=DEFAULT_MIN_CANDLES,
            execution_cost_config=ExecutionCostConfig(entry_latency_candles=100),
        )
        report = engine.run(candles)

        assert report.total_trades == 0, (
            "Pending deveria ter expirado sem virar trade"
        )

    def test_expired_pending_does_not_increment_risk_blocked_count(self):
        """Expiração ≠ bloqueio do RiskEngine. risk_blocked_count == 0."""
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=3,
            hit_what="tp",
        )
        engine = make_backtest_engine_with_stub(
            signal=make_default_buy_signal(),
            min_candles=DEFAULT_MIN_CANDLES,
            execution_cost_config=ExecutionCostConfig(entry_latency_candles=100),
        )
        report = engine.run(candles)
        assert report.total_trades == 0
        assert report.risk_blocked_count == 0


# ---------------------------------------------------------------------------
# Pending: revalidação do RiskEngine no candle de execução
# ---------------------------------------------------------------------------

class _RiskEngineRejectOnNthCall:
    """
    Wrapper de RiskEngine que aprova as chamadas a validate_signal,
    EXCETO a N-ésima — que é rejeitada (simula "limite estourou durante espera").

    Útil junto com SpyStubStrategy que emite BUY apenas 1 vez, garantindo
    que não há novo sinal após a rejeição da revalidação.

    Para qualquer outro método (record_*, get_status_summary), delega ao real.
    """

    def __init__(self, real_engine: RiskEngine, reject_on_call: int):
        self._real = real_engine
        self._reject_on = reject_on_call
        self._n_calls = 0

    def validate_signal(self, signal):
        self._n_calls += 1
        if self._n_calls == self._reject_on:
            from crypto_trading_bot.risk.risk_engine import RiskResult
            return RiskResult(
                approved=False,
                reason="Mocked revalidation rejection",
                signal=signal,
            )
        return self._real.validate_signal(signal)

    def __getattr__(self, name):
        return getattr(self._real, name)


class TestPendingSignalRiskEngineRevalidation:

    def test_riskengine_revalidates_pending_at_execution(self):
        """
        Mock: aprova 1ª validação (geração) e rejeita 2ª (revalidação).
        SpyStubStrategy emite BUY apenas uma vez → sem novo sinal após rejeição.
        Resultado: pending criado, mas rejeitado na execução → 0 trades, 1 bloqueio.
        """
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=10,
            hit_what="tp",
        )
        real_risk = RiskEngine(initial_capital=DEFAULT_CAPITAL)
        mock_risk = _RiskEngineRejectOnNthCall(real_risk, reject_on_call=2)

        # Spy emite BUY 1 vez; depois HOLD (não gera novo pending após rejeição).
        strategy = _SpyStubStrategy(make_default_buy_signal())
        engine = BacktestEngine(
            strategy=strategy,
            risk_engine=mock_risk,
            feature_engine=FeatureEngine(),
            initial_capital=DEFAULT_CAPITAL,
            min_candles=DEFAULT_MIN_CANDLES,
            symbol=DEFAULT_SYMBOL,
            execution_cost_config=ExecutionCostConfig(entry_latency_candles=2),
        )
        report = engine.run(candles)

        # Pending criado mas rejeitado na revalidação → nenhum trade
        assert report.total_trades == 0
        # Bloqueio contabilizado UMA vez (na revalidação)
        assert report.risk_blocked_count == 1

    def test_approved_revalidation_creates_trade_normally(self):
        """
        Sanity check: sem mock, revalidação sempre passa (mesmo cenário) →
        trade aberto normalmente.
        """
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=10,
            hit_what="tp",
        )
        engine = make_backtest_engine_with_stub(
            signal=make_default_buy_signal(),
            min_candles=DEFAULT_MIN_CANDLES,
            execution_cost_config=ExecutionCostConfig(entry_latency_candles=2),
        )
        report = engine.run(candles)
        assert report.total_trades == 1
        assert report.risk_blocked_count == 0


# ---------------------------------------------------------------------------
# Stop/take usam valores ORIGINAIS do sinal mesmo após latência
# ---------------------------------------------------------------------------

class TestStopTpUseOriginalSignalPricesAfterLatency:

    def test_stop_loss_price_in_trade_equals_signal_original(self):
        latency = 3
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=15,
            hit_what="tp",
        )
        engine = make_backtest_engine_with_stub(
            signal=make_default_buy_signal(),
            min_candles=DEFAULT_MIN_CANDLES,
            execution_cost_config=ExecutionCostConfig(entry_latency_candles=latency),
        )
        report = engine.run(candles)
        trade = report.trades[0]
        assert trade.stop_loss_price == DEFAULT_STOP_PRICE
        assert trade.take_profit_price == DEFAULT_TP_PRICE

    def test_sl_tp_not_evaluated_on_actual_entry_candle_with_latency(self):
        """
        Pending executa em i=50 (latency=1). SL/TP só podem ser avaliados em i>50.
        Logo trade.exit_candle_idx > trade.entry_candle_idx.
        """
        latency = 1
        candles = generate_candles_with_stop_hit(
            entry_price=DEFAULT_ENTRY_PRICE,
            stop_price=DEFAULT_STOP_PRICE,
            take_profit_price=DEFAULT_TP_PRICE,
            n_before_entry=60,
            n_after_entry=10,
            hit_what="tp",
        )
        engine = make_backtest_engine_with_stub(
            signal=make_default_buy_signal(),
            min_candles=DEFAULT_MIN_CANDLES,
            execution_cost_config=ExecutionCostConfig(entry_latency_candles=latency),
        )
        report = engine.run(candles)
        trade = report.trades[0]
        assert trade.exit_candle_idx is not None
        assert trade.exit_candle_idx > trade.entry_candle_idx, (
            f"SL/TP avaliado no candle de entrada! "
            f"entry={trade.entry_candle_idx} exit={trade.exit_candle_idx}"
        )


# ---------------------------------------------------------------------------
# Challenge target continua KPI mesmo com latência
# ---------------------------------------------------------------------------

class TestChallengeTargetWithLatency:

    def test_challenge_target_still_kpi_with_latency(self):
        candles = generate_trending_candles(150)
        engine = make_backtest_engine_with_stub(
            min_candles=5,
            challenge_target=1.0,
            execution_cost_config=ExecutionCostConfig(entry_latency_candles=2),
        )
        report = engine.run(candles)
        # Backtest sempre roda até o fim, independente do KPI
        assert report.n_candles_total == 150
        # Sem max_profit_usd bloqueante
        assert not hasattr(report, "max_profit_usd")


# ---------------------------------------------------------------------------
# Walk-forward propaga latência via ExecutionCostConfig
# ---------------------------------------------------------------------------

class TestWalkForwardWithLatency:

    def test_walk_forward_propagates_latency_to_each_fold(self):
        """
        Walk-forward usa BacktestEngine como caixa-preta — latência via
        ExecutionCostConfig é propagada transparentemente para cada fold.
        """
        candles = generate_trending_candles(500, trend_pct_per_candle=0.0)

        def factory():
            s = StubStrategy(
                signal=StrategySignal.hold(DEFAULT_SYMBOL, "stub"),
                block_after_trade=True,
            )
            s.set_running()
            return s

        results = run_walk_forward(
            strategy_factory=factory,
            candles=candles,
            n_folds=5,
            train_pct=0.7,
            min_candles=5,
            execution_cost_config=ExecutionCostConfig(entry_latency_candles=2),
        )
        # 5 folds executados sem erro com latência ativa
        assert len(results) == 5
        # HOLD strategy → zero trades em todos os folds (sanity check)
        for r in results:
            assert r.train_report.total_trades == 0
            assert r.test_report.total_trades == 0
