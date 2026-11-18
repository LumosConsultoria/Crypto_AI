"""
Testes de anti-flip da ExitPolicy (FASE 11)
============================================
⚠️  100% offline. ZERO rede.

Cobertura:
    - Sinal contrário com posição aberta gera ExitDecision(OPPOSITE_SIGNAL).
    - ExitPolicy NÃO emite entrada nova; só gera saída.
    - Após saída, a nova entrada oposta só é considerada em fase futura
      (não pertence à ExitPolicy nem é executada aqui).
    - RiskEngine continua como segunda camada — ExitPolicy não o chama.
"""

from __future__ import annotations

from datetime import datetime, timezone

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.execution.provider_capability import ProviderCapability
from crypto_trading_bot.exit_policy import (
    ExitPolicy,
    ExitReason,
    ExitSource,
    OpenPositionState,
    PositionSide,
)
from crypto_trading_bot.strategies.signal_model import (
    StrategyAction,
    StrategySignal,
)


_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _cap() -> ProviderCapability:
    return ProviderCapability(
        provider_id="mock", supports_market_order=True,
        supports_reduce_only=True,
    )


def _candle() -> Candle:
    return Candle(
        symbol="BTCUSDT", timeframe="15", timestamp=_NOW,
        open=65000.0, high=65500.0, low=64500.0, close=65000.0,
        volume=1000.0,
    )


def _buy_position() -> OpenPositionState:
    return OpenPositionState(
        symbol="BTCUSDT", side=PositionSide.BUY,
        entry_price=65000.0, entry_time=_NOW,
        stop_loss_price=64000.0, take_profit_price=67000.0,
        position_size_usd=200.0, entry_candle_idx=10,
    )


def _sell_position() -> OpenPositionState:
    return OpenPositionState(
        symbol="BTCUSDT", side=PositionSide.SELL,
        entry_price=65000.0, entry_time=_NOW,
        stop_loss_price=66000.0, take_profit_price=63000.0,
        position_size_usd=200.0, entry_candle_idx=10,
    )


class TestOppositeSignalProducesExitNotFlip:

    def test_buy_position_sees_sell_signal_produces_exit(self):
        policy = ExitPolicy(
            provider_capability=_cap(),
            allow_close_on_opposite_signal=True,
        )
        d = policy.evaluate(
            position=_buy_position(),
            candle=_candle(),
            now=_NOW,
            candle_idx=11,
            latest_signal=StrategySignal.sell(
                symbol="BTCUSDT", strategy_name="trend",
                entry_price=65000.0, stop_loss_price=66000.0,
                position_size_usd=200.0,
            ),
        )
        # Deve gerar SAÍDA, não entrada
        assert d.should_close is True
        assert d.reason == ExitReason.OPPOSITE_SIGNAL
        assert d.source == ExitSource.RULE_OPPOSITE
        # ExitDecision não fala sobre entrada nova — só fechamento
        assert "opposite_action" in d.metadata
        assert d.metadata["opposite_action"] == StrategyAction.SELL.value

    def test_sell_position_sees_buy_signal_produces_exit(self):
        policy = ExitPolicy(
            provider_capability=_cap(),
            allow_close_on_opposite_signal=True,
        )
        d = policy.evaluate(
            position=_sell_position(),
            candle=_candle(),
            now=_NOW,
            candle_idx=11,
            latest_signal=StrategySignal.buy(
                symbol="BTCUSDT", strategy_name="trend",
                entry_price=65000.0, stop_loss_price=64000.0,
                position_size_usd=200.0,
            ),
        )
        assert d.should_close is True
        assert d.reason == ExitReason.OPPOSITE_SIGNAL


class TestExitDoesNotImplyNewEntry:

    def test_exit_decision_only_describes_close_not_new_entry(self):
        policy = ExitPolicy(
            provider_capability=_cap(),
            allow_close_on_opposite_signal=True,
        )
        d = policy.evaluate(
            position=_buy_position(),
            candle=_candle(),
            now=_NOW,
            candle_idx=11,
            latest_signal=StrategySignal.sell(
                symbol="BTCUSDT", strategy_name="trend",
                entry_price=65000.0, stop_loss_price=66000.0,
                position_size_usd=200.0,
            ),
        )
        # API da ExitDecision não tem nada sobre nova posição —
        # auditabilidade contém só o sinal oposto observado,
        # sem qualquer field "open_new_position" ou similar.
        assert not hasattr(d, "open_new_position")
        assert not hasattr(d, "new_entry_price")
        assert "new_entry_price" not in d.metadata


class TestExitPolicyDoesNotCallRiskEngine:

    def test_exit_policy_module_does_not_import_risk_engine(self):
        """ExitPolicy não pode importar RiskEngine — anti-acoplamento."""
        import crypto_trading_bot.exit_policy.exit_policy as ep_mod
        src = open(ep_mod.__file__, "r", encoding="utf-8").read()
        # Aceita menção no docstring; rejeita import direto
        assert "from crypto_trading_bot.risk.risk_engine import" not in src
        assert "import crypto_trading_bot.risk.risk_engine" not in src

    def test_exit_policy_does_not_import_executors(self):
        import crypto_trading_bot.exit_policy.exit_policy as ep_mod
        src = open(ep_mod.__file__, "r", encoding="utf-8").read()
        forbidden = [
            "from crypto_trading_bot.execution.bybit_demo_executor",
            "from crypto_trading_bot.execution.bybit_testnet_executor",
            "from crypto_trading_bot.execution.paper_trader",
            "from crypto_trading_bot.exchange.bybit_client",
            "import httpx",
        ]
        for line in forbidden:
            assert line not in src, f"ExitPolicy não deve importar: {line}"


class TestSignalNotActionableIsIgnored:

    def test_hold_signal_does_not_trigger_opposite_exit(self):
        policy = ExitPolicy(
            provider_capability=_cap(),
            allow_close_on_opposite_signal=True,
        )
        hold = StrategySignal.hold(
            symbol="BTCUSDT", strategy_name="trend",
            reason="aguardando",
        )
        d = policy.evaluate(
            position=_buy_position(),
            candle=_candle(),
            now=_NOW,
            candle_idx=11,
            latest_signal=hold,
        )
        assert d.should_close is False
