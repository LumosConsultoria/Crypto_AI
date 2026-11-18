"""
Testes de Fluxo Ponta a Ponta
================================
Valida o pipeline completo:
    MockExchange → MarketData → FeatureEngine → EmaRsiStrategy → RiskEngine → PaperTrader

⚠️  ZERO chamadas à internet ou API real.
⚠️  Nenhum teste usa BybitClient ou chaves de API.

Cobertura:
    - Fluxo completo sem API (MockExchange → trade executado)
    - Fluxo sem candles → encerra com segurança
    - Fluxo com candles insuficientes → encerra com segurança
    - HOLD por EMA9 < EMA21 → não executa
    - HOLD por posição já aberta → não duplica trade
    - RiskEngine bloqueia quando capital insuficiente → sem execução
    - Múltiplos ciclos: segundo ciclo com posição aberta → HOLD
    - EmaRsiStrategy: parâmetros inválidos lançam ValueError
    - EmaRsiStrategy: stop por ATR calculado corretamente
    - EmaRsiStrategy: stop fallback quando ATR indisponível
    - StrategySignal: HOLD não é convertível para TradingSignal
    - StrategySignal: BUY com campos válidos converte corretamente
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

import pytest

# Importa helpers determinísticos do conftest
from tests.helpers import make_stub_engine

from crypto_trading_bot.core.bot_engine import BotEngine
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.data.market_data import MarketDataService
from crypto_trading_bot.exchange.mock_exchange import MockExchange
from crypto_trading_bot.execution.paper_trader import PaperTrader
from crypto_trading_bot.risk.risk_engine import RiskEngine
from crypto_trading_bot.strategies.ema_rsi_strategy import EmaRsiStrategy
from crypto_trading_bot.strategies.signal_model import StrategyAction, StrategySignal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_pipeline(
    n_candles: int = 60,
    rsi_overbought: float = 99.9,
    position_size_usd: float = 200.0,
    initial_capital: float = 5000.0,
    trend: float = 50.0,
):
    """
    Constrói o pipeline completo com MockExchange.

    Controla candles via _price_history (interface real do MockExchange):
    - n_candles=0  → lista vazia → action="no_candles"
    - n_candles=3  → insuficiente → action="insufficient_data"
    - trend > 0    → preços crescentes → EMA9 > EMA21 → sinal BUY possível
    - trend < 0    → preços decrescentes → EMA9 < EMA21 → HOLD
    """
    mock_exchange = MockExchange()
    if n_candles == 0:
        mock_exchange._price_history = []
    else:
        mock_exchange._price_history = [
            65000.0 + i * trend for i in range(n_candles)
        ]

    market_data = MarketDataService(exchange=mock_exchange, default_symbol="BTCUSDT")
    feature_engine = FeatureEngine()
    strategy = EmaRsiStrategy(
        rsi_overbought=rsi_overbought,
        position_size_usd=position_size_usd,
    )
    risk_engine = RiskEngine(initial_capital=initial_capital)
    paper_trader = PaperTrader(risk_engine=risk_engine)
    engine = BotEngine(
        market_data_service=market_data,
        feature_engine=feature_engine,
        strategy=strategy,
        risk_engine=risk_engine,
        paper_trader=paper_trader,
    )
    return engine, strategy, risk_engine, paper_trader


# ---------------------------------------------------------------------------
# Testes de Fluxo Completo sem API
# ---------------------------------------------------------------------------

class TestFullPipelineNoAPI:
    """Valida que o pipeline nunca usa API real."""

    def test_pipeline_uses_mock_not_bybit(self):
        """Nenhum componente do pipeline deve acessar Bybit."""
        engine, strategy, *_ = _build_pipeline()
        strategy.set_running()
        result = engine.run_once()
        assert result is not None

    def test_no_bybit_client_in_flow(self):
        """BybitClient nunca aparece no fluxo de teste."""
        engine, strategy, *_ = _build_pipeline()
        assert isinstance(engine._market_data._exchange, MockExchange)

    def test_full_pipeline_returns_cycle_result(self):
        engine, strategy, *_ = _build_pipeline()
        strategy.set_running()
        result = engine.run_once()
        from crypto_trading_bot.core.cycle_result import BotCycleResult
        assert isinstance(result, BotCycleResult)


# ---------------------------------------------------------------------------
# Testes de Fluxo com Dados Ausentes
# ---------------------------------------------------------------------------

class TestPipelineSafeWithBadData:
    """Testa encerramento seguro com dados ausentes ou insuficientes."""

    def test_empty_exchange_no_crash(self):
        engine, strategy, *_ = _build_pipeline(n_candles=0)
        strategy.set_running()
        result = engine.run_once()
        assert result.action == "no_candles"
        assert result.executed is False

    def test_few_candles_no_crash(self):
        engine, strategy, *_ = _build_pipeline(n_candles=3)
        strategy.set_running()
        result = engine.run_once()
        assert result.action == "insufficient_data"
        assert result.executed is False

    def test_empty_result_is_safe(self):
        engine, strategy, *_ = _build_pipeline(n_candles=0)
        strategy.set_running()
        result = engine.run_once()
        assert result.was_safe is True

    def test_insufficient_result_is_safe(self):
        engine, strategy, *_ = _build_pipeline(n_candles=3)
        strategy.set_running()
        result = engine.run_once()
        assert result.was_safe is True


# ---------------------------------------------------------------------------
# Testes de HOLD no Fluxo
# ---------------------------------------------------------------------------

class TestPipelineHoldFlow:
    """Testa que HOLD encerra o ciclo sem execução."""

    def test_hold_when_ema_not_crossed(self):
        """Preços em queda → EMA curta < EMA longa → HOLD."""
        engine, strategy, *_ = _build_pipeline(n_candles=60, trend=-50.0)
        strategy.set_running()
        result = engine.run_once()
        assert result.executed is False

    def test_hold_no_pending_trade(self):
        """HOLD → PaperTrader não deve ter trades abertos (sem condicional)."""
        # trend=-50 garante EMA9 < EMA21 → result.action == "hold"
        engine, strategy, _, paper_trader = _build_pipeline(n_candles=60, trend=-50.0)
        strategy.set_running()
        result = engine.run_once()
        # Qualquer cenário não-executado não deve ter open trades
        assert result.executed is False
        assert len(paper_trader._open_trades) == 0  # sem condicional

    def test_hold_with_open_position_blocks_second_trade(self):
        """
        Segunda execução com posição já aberta → HOLD determinístico.
        Usa StubStrategy para garantir r1=="executed" e r2=="hold".
        """
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, strategy, _, paper_trader = make_stub_engine(
            buy_signal, capital=5000.0, n_candles=60, block_after_trade=True
        )

        r1 = engine.run_once()
        r2 = engine.run_once()

        assert r1.action == "executed"         # sem condicional
        assert r2.action == "hold"             # sem condicional
        assert "posição já aberta" in r2.strategy_signal.reason
        assert len(paper_trader._open_trades) == 1   # não duplicou

    def test_hold_result_is_safe(self):
        engine, strategy, *_ = _build_pipeline(n_candles=60, trend=-50.0)
        strategy.set_running()
        result = engine.run_once()
        assert result.was_safe is True


# ---------------------------------------------------------------------------
# Testes de Risco no Fluxo
# ---------------------------------------------------------------------------

class TestPipelineRiskFlow:
    """Valida integração com RiskEngine no pipeline."""

    def test_risk_engine_is_called_before_paper_trader(self):
        """
        Invariante: RiskEngine é chamado ANTES do PaperTrader.
        StubStrategy(BUY) + capital=1.0 → risk_blocked garantido (sem condicional).
        """
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, _, _, paper_trader = make_stub_engine(
            buy_signal, capital=1.0, n_candles=60
        )
        result = engine.run_once()
        assert result.action == "risk_blocked"      # sem condicional
        assert result.executed is False             # sem condicional
        assert len(paper_trader._open_trades) == 0  # PaperTrader não foi chamado

    def test_insufficient_capital_blocks_trade(self):
        """Capital muito baixo bloqueia o trade via RiskEngine."""
        engine, strategy, *_ = _build_pipeline(
            n_candles=60,
            rsi_overbought=99.9,
            initial_capital=10.0,
            position_size_usd=500.0,
        )
        strategy.set_running()
        result = engine.run_once()
        assert result.executed is False
        assert result.was_safe is True

    def test_normal_capital_allows_trade(self):
        """
        Capital normal + sinal BUY → trade executado (determinístico).
        StubStrategy garante que o sinal BUY é gerado independente de RSI/EMA.
        """
        buy_signal = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, _, _, paper_trader = make_stub_engine(
            buy_signal, capital=5000.0, n_candles=60
        )
        result = engine.run_once()
        assert result.action == "executed"          # sem condicional
        assert result.was_safe is True
        assert len(paper_trader._open_trades) == 1  # trade efetivamente criado


# ---------------------------------------------------------------------------
# Testes da EmaRsiStrategy no Fluxo
# ---------------------------------------------------------------------------

class TestEmaRsiStrategyInFlow:
    """Valida comportamentos específicos da EmaRsiStrategy no pipeline."""

    def test_invalid_ema_periods_raises(self):
        """ema_short >= ema_long deve lançar ValueError."""
        with pytest.raises(ValueError, match="ema_short_period"):
            EmaRsiStrategy(ema_short_period=21, ema_long_period=9)

    def test_invalid_rsi_overbought_raises(self):
        with pytest.raises(ValueError, match="rsi_overbought"):
            EmaRsiStrategy(rsi_overbought=110.0)

    def test_invalid_position_size_raises(self):
        with pytest.raises(ValueError, match="position_size_usd"):
            EmaRsiStrategy(position_size_usd=-100.0)

    def test_stop_by_atr_fallback_when_nan(self):
        """Se ATR for NaN, stop usa percentual fallback."""
        strategy = EmaRsiStrategy(stop_fallback_pct=0.02)
        stop = strategy._calculate_stop_loss(65000.0, float("nan"))
        expected = round(65000.0 * 0.98, 2)
        assert stop == expected

    def test_stop_by_atr_when_available(self):
        """Se ATR disponível, stop = entry - 2*ATR."""
        strategy = EmaRsiStrategy(stop_atr_multiplier=2.0)
        stop = strategy._calculate_stop_loss(65000.0, 500.0)
        expected = round(65000.0 - 2.0 * 500.0, 2)
        assert stop == expected

    def test_evaluate_returns_hold_when_warming_up(self):
        """evaluate() retorna HOLD se estratégia em WARMING_UP."""
        strategy = EmaRsiStrategy()
        features: Dict[str, Any] = {
            "has_sufficient_data": True,
            "symbol": "BTCUSDT",
            "last_close": 65000.0,
        }
        signal = strategy.evaluate(features)
        assert signal.action == StrategyAction.HOLD

    def test_evaluate_returns_hold_insufficient_data(self):
        """evaluate() retorna HOLD se has_sufficient_data=False."""
        strategy = EmaRsiStrategy()
        strategy.set_running()
        features: Dict[str, Any] = {
            "has_sufficient_data": False,
            "n_candles": 10,
            "symbol": "BTCUSDT",
        }
        signal = strategy.evaluate(features)
        assert signal.action == StrategyAction.HOLD

    def test_evaluate_hold_when_ema_not_crossed(self):
        """EMA curta <= EMA longa → HOLD."""
        import pandas as pd
        strategy = EmaRsiStrategy()
        strategy.set_running()
        features: Dict[str, Any] = {
            "has_sufficient_data": True,
            "symbol": "BTCUSDT",
            "last_close": 65000.0,
            "last_ema_9": 64000.0,
            "ema_21": pd.Series([65000.0] * 50),
            "last_rsi": 50.0,
            "last_atr": 500.0,
        }
        signal = strategy.evaluate(features)
        assert signal.action == StrategyAction.HOLD

    def test_evaluate_buy_when_conditions_met(self):
        """EMA9 > EMA21 + RSI abaixo de limite → BUY."""
        import pandas as pd
        strategy = EmaRsiStrategy(rsi_overbought=99.9)
        strategy.set_running()
        features: Dict[str, Any] = {
            "has_sufficient_data": True,
            "symbol": "BTCUSDT",
            "last_close": 65000.0,
            "last_ema_9": 65500.0,
            "ema_21": pd.Series([64000.0] * 50),
            "last_rsi": 50.0,
            "last_atr": 500.0,
        }
        signal = strategy.evaluate(features)
        assert signal.action == StrategyAction.BUY
        assert signal.entry_price == 65000.0
        assert signal.stop_loss_price < signal.entry_price
        assert signal.position_size_usd == 200.0

    def test_evaluate_hold_when_rsi_overbought(self):
        """RSI >= rsi_overbought → HOLD."""
        import pandas as pd
        strategy = EmaRsiStrategy(rsi_overbought=65.0)
        strategy.set_running()
        features: Dict[str, Any] = {
            "has_sufficient_data": True,
            "symbol": "BTCUSDT",
            "last_close": 65000.0,
            "last_ema_9": 65500.0,
            "ema_21": pd.Series([64000.0] * 50),
            "last_rsi": 70.0,
            "last_atr": 500.0,
        }
        signal = strategy.evaluate(features)
        assert signal.action == StrategyAction.HOLD

    def test_evaluate_hold_when_position_open(self):
        """Posição aberta → segunda chamada retorna HOLD."""
        import pandas as pd
        strategy = EmaRsiStrategy(rsi_overbought=99.9)
        strategy.set_running()
        features: Dict[str, Any] = {
            "has_sufficient_data": True,
            "symbol": "BTCUSDT",
            "last_close": 65000.0,
            "last_ema_9": 65500.0,
            "ema_21": pd.Series([64000.0] * 50),
            "last_rsi": 50.0,
            "last_atr": 500.0,
        }
        s1 = strategy.evaluate(features)
        assert s1.action == StrategyAction.BUY

        from crypto_trading_bot.risk.risk_engine import OrderSide, TradingSignal
        strategy.on_signal_approved(TradingSignal(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            entry_price=65000.0,
            stop_loss_price=64000.0,
            position_size_usd=200.0,
            strategy_name=strategy.name,
        ))

        s2 = strategy.evaluate(features)
        assert s2.action == StrategyAction.HOLD
        assert "posição já aberta" in s2.reason


# ---------------------------------------------------------------------------
# Testes do StrategySignal
# ---------------------------------------------------------------------------

class TestStrategySignalModel:
    """Testa o modelo StrategySignal e suas conversões."""

    def test_hold_is_not_actionable(self):
        sig = StrategySignal.hold("BTCUSDT", "test")
        assert sig.is_actionable is False

    def test_buy_is_actionable(self):
        sig = StrategySignal.buy("BTCUSDT", "test", 65000.0, 64000.0, 200.0)
        assert sig.is_actionable is True

    def test_sell_is_actionable(self):
        sig = StrategySignal.sell("BTCUSDT", "test", 65000.0, 66000.0, 200.0)
        assert sig.is_actionable is True

    def test_hold_cannot_convert_to_trading_signal(self):
        """HOLD.to_trading_signal() deve lançar ValueError."""
        sig = StrategySignal.hold("BTCUSDT", "test")
        with pytest.raises(ValueError, match="HOLD"):
            sig.to_trading_signal()

    def test_buy_converts_to_trading_signal(self):
        from crypto_trading_bot.risk.risk_engine import OrderSide
        sig = StrategySignal.buy("BTCUSDT", "test", 65000.0, 64000.0, 200.0)
        ts = sig.to_trading_signal()
        assert ts.symbol == "BTCUSDT"
        assert ts.side == OrderSide.BUY
        assert ts.entry_price == 65000.0
        assert ts.stop_loss_price == 64000.0
        assert ts.position_size_usd == 200.0

    def test_sell_converts_to_trading_signal(self):
        from crypto_trading_bot.risk.risk_engine import OrderSide
        sig = StrategySignal.sell("BTCUSDT", "test", 65000.0, 66000.0, 200.0)
        ts = sig.to_trading_signal()
        assert ts.side == OrderSide.SELL

    def test_buy_with_zero_entry_raises(self):
        sig = StrategySignal.buy("BTCUSDT", "test", 0.0, 64000.0, 200.0)
        with pytest.raises(ValueError, match="entry_price"):
            sig.to_trading_signal()

    def test_stop_loss_pct_calculated(self):
        sig = StrategySignal.buy("BTCUSDT", "test", 65000.0, 64000.0, 200.0)
        expected = 1000.0 / 65000.0
        assert abs(sig.stop_loss_pct - expected) < 1e-6

    def test_hold_stop_loss_pct_is_zero(self):
        sig = StrategySignal.hold("BTCUSDT", "test")
        assert sig.stop_loss_pct == 0.0

    def test_hold_with_reason(self):
        sig = StrategySignal.hold("BTCUSDT", "test", reason="RSI muito alto")
        assert "RSI" in sig.reason

    def test_repr_hold(self):
        sig = StrategySignal.hold("BTCUSDT", "test")
        r = repr(sig)
        assert "HOLD" in r

    def test_repr_buy(self):
        sig = StrategySignal.buy("BTCUSDT", "test", 65000.0, 64000.0, 200.0)
        r = repr(sig)
        assert "BUY" in r
