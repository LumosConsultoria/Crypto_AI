"""
Preservação de estado entre ciclos no SessionRunner (FASE 17 — ajuste crítico)
==============================================================================
⚠️  100% offline. ZERO rede.

Ajuste obrigatório do plano: o runner NÃO pode recriar PaperTrader/
RiskEngine/MockExchange/etc. a cada ciclo. Deve construir UMA vez no
__init__ e reutilizar.

Cobertura:
    - Uma posição aberta em um ciclo continua visível no ciclo seguinte.
    - max_concurrent_positions bloqueia nova abertura quando já existe
      posição aberta.
    - execution_count acumula durante a sessão.
    - PnL paper e trades fechados não zeram a cada ciclo.
    - max_trades_per_session funciona com estado acumulado.
    - PaperTrader instance é a MESMA entre ciclos.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from crypto_trading_bot.operational_profile import build_personal_profile
from crypto_trading_bot.research.strategy_research import StrategySpec
from crypto_trading_bot.session_runner import (
    SessionRunner,
    SessionRunnerConfig,
    SessionStopReason,
)
from crypto_trading_bot.session_runner.result import (
    BLOCK_PROFILE_CONCURRENT,
)
from crypto_trading_bot.strategies.signal_model import StrategySignal

from tests.test_session_runner_profile_gates import (
    _AlwaysBuyStrategy,
    _spec_always_buy,
)
from tests.test_session_runner_config import _HoldStrategy


def _spec_hold():
    def factory(cfg):
        s = _HoldStrategy()
        s.set_running()
        return s
    return StrategySpec(name="hold_v1", factory=factory)


def _build_runner(*, max_cycles=5, profile=None, spec=None):
    if profile is None:
        profile = build_personal_profile(
            account_size_usd=5000.0, max_concurrent_positions=1,
        )
    if spec is None:
        spec = _spec_always_buy()
    cfg = SessionRunnerConfig(
        profile=profile,
        spec=spec,
        capital=5000.0,
        max_cycles=max_cycles,
        cycle_interval_seconds=0.0,
        clock=lambda: datetime(2026, 6, 1, 14, 0, 0, tzinfo=timezone.utc),
        sleep=lambda s: None,
        virtual_cycle_seconds=0.0,
    )
    return SessionRunner(cfg)


# ---------------------------------------------------------------------------
# Posição persistente entre ciclos
# ---------------------------------------------------------------------------

class TestPositionPersistsAcrossCycles:

    def test_open_trade_visible_in_next_cycle(self):
        runner = _build_runner(max_cycles=3)
        runner.run()
        # Após a sessão, open_trades deve ter 1 posição (ainda não fechada
        # — paper não tem auto-close por SL/TP)
        assert len(runner.paper_trader.open_trades) == 1

    def test_paper_trader_instance_same_across_cycles(self):
        runner = _build_runner(max_cycles=3)
        before = id(runner.paper_trader)
        runner.run()
        after = id(runner.paper_trader)
        assert before == after, "PaperTrader foi recriado entre run()s"


# ---------------------------------------------------------------------------
# max_concurrent_positions impede nova abertura
# ---------------------------------------------------------------------------

class TestMaxConcurrentBlocksNewOpen:

    def test_no_second_position_opens_when_one_exists(self):
        runner = _build_runner(max_cycles=5)
        result = runner.run()
        # Limite 1 → apenas 1 trade aberto
        assert result.trades_opened == 1
        assert len(runner.paper_trader.open_trades) == 1
        # Ciclos posteriores registraram block CONCURRENT
        concurrent_blocks = [
            b for b in result.blocks
            if b.block_source == BLOCK_PROFILE_CONCURRENT
        ]
        assert len(concurrent_blocks) >= 1


# ---------------------------------------------------------------------------
# execution_count acumula
# ---------------------------------------------------------------------------

class TestExecutionCountAccumulates:

    def test_execution_count_grows_across_cycles(self):
        # Profile permite múltiplas posições para que execution_count cresça
        profile = build_personal_profile(
            account_size_usd=5000.0,
            max_concurrent_positions=10,
        )
        runner = _build_runner(profile=profile, max_cycles=3)
        # Roda 1 vez
        runner.run()
        first_count = runner.paper_trader.execution_count
        # Fecha tudo manualmente (paper)
        for tid in list(runner.paper_trader.open_trades.keys()):
            trade = runner.paper_trader.open_trades[tid]
            runner.paper_trader.close_trade(tid, close_price=65500.0)
            # FASE 17: BotEngine notifica strategy.on_trade_closed em
            # fluxos automáticos; em close manual no teste, replicamos.
            runner._strategy.on_trade_closed(
                trade.signal.symbol, float(trade.pnl or 0.0),
            )
        # Roda outra vez
        runner.run()
        # execution_count deve ter acumulado
        assert runner.paper_trader.execution_count > first_count


# ---------------------------------------------------------------------------
# closed_trades e PnL não zeram
# ---------------------------------------------------------------------------

class TestClosedTradesPersist:

    def test_closed_trades_accumulate_across_runs(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            max_concurrent_positions=10,
        )
        runner = _build_runner(profile=profile, max_cycles=2)
        runner.run()
        for tid in list(runner.paper_trader.open_trades.keys()):
            trade = runner.paper_trader.open_trades[tid]
            runner.paper_trader.close_trade(
                tid, close_price=65500.0, reason="take_profit",
            )
            runner._strategy.on_trade_closed(
                trade.signal.symbol, float(trade.pnl or 0.0),
            )
        n_closed_1 = len(runner.paper_trader.closed_trades)
        assert n_closed_1 >= 1

        # Nova run
        runner.run()
        for tid in list(runner.paper_trader.open_trades.keys()):
            trade = runner.paper_trader.open_trades[tid]
            runner.paper_trader.close_trade(
                tid, close_price=65500.0, reason="take_profit",
            )
            runner._strategy.on_trade_closed(
                trade.signal.symbol, float(trade.pnl or 0.0),
            )
        n_closed_2 = len(runner.paper_trader.closed_trades)
        # closed_trades preservados + novos
        assert n_closed_2 > n_closed_1


# ---------------------------------------------------------------------------
# max_trades_per_session com estado acumulado
# ---------------------------------------------------------------------------

class TestMaxTradesAccumulated:

    def test_limit_respects_accumulated_execution_count(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            max_trades_per_session=2,
            max_concurrent_positions=10,
        )
        runner = _build_runner(profile=profile, max_cycles=10)
        # Abre 1 na primeira run
        runner.run()
        # Fecha
        for tid in list(runner.paper_trader.open_trades.keys()):
            trade = runner.paper_trader.open_trades[tid]
            runner.paper_trader.close_trade(tid, close_price=65500.0)
            # FASE 17: BotEngine notifica strategy.on_trade_closed em
            # fluxos automáticos; em close manual no teste, replicamos.
            runner._strategy.on_trade_closed(
                trade.signal.symbol, float(trade.pnl or 0.0),
            )
        # Run 2: execution_count=1 < 2, deve permitir +1
        runner.run()
        for tid in list(runner.paper_trader.open_trades.keys()):
            trade = runner.paper_trader.open_trades[tid]
            runner.paper_trader.close_trade(tid, close_price=65500.0)
            # FASE 17: BotEngine notifica strategy.on_trade_closed em
            # fluxos automáticos; em close manual no teste, replicamos.
            runner._strategy.on_trade_closed(
                trade.signal.symbol, float(trade.pnl or 0.0),
            )
        # Run 3: execution_count=2, atingiu o limite → PROFILE_TRADES_LIMIT
        result3 = runner.run()
        assert result3.stopped_reason == SessionStopReason.PROFILE_TRADES_LIMIT


# ---------------------------------------------------------------------------
# RiskEngine counters preservados
# ---------------------------------------------------------------------------

class TestRiskEngineCountersPreserved:

    def test_risk_engine_instance_persists(self):
        runner = _build_runner(max_cycles=2)
        rid_before = id(runner._risk_engine)
        runner.run()
        rid_after = id(runner._risk_engine)
        assert rid_before == rid_after, "RiskEngine recriado — estado perdido"

    def test_risk_engine_records_trade_in_paper_trader_flow(self):
        runner = _build_runner(max_cycles=2)
        runner.run()
        # RiskEngine deve ter registrado abertura via PaperTrader
        summary = runner._risk_engine.get_status_summary()
        # current_capital pode ter mudado se trade fechou; aqui só verificamos
        # que summary existe e é uma dict
        assert isinstance(summary, dict)
        assert "current_capital" in summary


# ---------------------------------------------------------------------------
# Mock exchange preservado
# ---------------------------------------------------------------------------

class TestMockExchangePersists:

    def test_mock_exchange_instance_same(self):
        runner = _build_runner(max_cycles=2)
        eid_before = id(runner._mock_exchange)
        runner.run()
        eid_after = id(runner._mock_exchange)
        assert eid_before == eid_after


# ---------------------------------------------------------------------------
# Teste regressivo: garante FALHA se pipeline for recriado
# ---------------------------------------------------------------------------

class TestRegressionPipelineNotRecreated:

    def test_pipeline_construction_count_is_one(self):
        """
        Sanity: o pipeline é construído UMA vez por SessionRunner.
        Múltiplas chamadas a run() não recriam.
        """
        runner = _build_runner(max_cycles=1)
        # Captura identidades de componentes-chave
        ids_initial = {
            "paper_trader": id(runner._paper_trader),
            "risk_engine": id(runner._risk_engine),
            "mock_exchange": id(runner._mock_exchange),
            "feature_engine": id(runner._feature_engine),
            "market_data": id(runner._market_data),
            "strategy": id(runner._strategy),
            "bot_engine": id(runner._bot_engine),
        }
        # Roda 5 sessões consecutivas
        for _ in range(5):
            runner.run()
        ids_after = {
            "paper_trader": id(runner._paper_trader),
            "risk_engine": id(runner._risk_engine),
            "mock_exchange": id(runner._mock_exchange),
            "feature_engine": id(runner._feature_engine),
            "market_data": id(runner._market_data),
            "strategy": id(runner._strategy),
            "bot_engine": id(runner._bot_engine),
        }
        assert ids_initial == ids_after, (
            f"Pipeline foi recriado entre runs: {ids_initial} → {ids_after}"
        )
