"""
Opposite-signal no BacktestEngine via ExitPolicy (FASE 12)
===========================================================
⚠️  100% offline. ZERO rede.

Cobertura:
    - Desligado por default: nenhum trade fecha por OPPOSITE_SIGNAL.
    - Habilitado + estratégia emite sinal oposto após entrada → fecha.
    - Anti-flip: nenhuma nova posição é aberta no mesmo ciclo.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from crypto_trading_bot.backtesting.backtest_data import (
    generate_trending_candles,
)
from crypto_trading_bot.backtesting.backtest_engine import BacktestEngine
from crypto_trading_bot.backtesting.backtest_trade import CloseReason
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.execution.provider_capability import ProviderCapability
from crypto_trading_bot.exit_policy import ExitPolicy
from crypto_trading_bot.risk.risk_engine import RiskEngine
from crypto_trading_bot.strategies.base_strategy import StrategyState
from crypto_trading_bot.strategies.signal_model import StrategySignal


def _cap() -> ProviderCapability:
    return ProviderCapability(
        provider_id="mock", supports_market_order=True,
        supports_reduce_only=True,
    )


# ---------------------------------------------------------------------------
# Stub de estratégia: emite BUY uma vez, depois SELL após N avaliações
# ---------------------------------------------------------------------------

class FlipAfterNStrategy:
    """
    Estratégia stub que:
      - emite BUY na primeira chamada acionável,
      - depois emite SELL após `flip_after` avaliações acionáveis.

    Fora dessa janela retorna HOLD. Usada para testar opposite-signal.
    """

    def __init__(self, *, flip_after: int = 5):
        self._state = StrategyState.WARMING_UP
        self._n_eval = 0
        self._flip_after = flip_after
        self._signal_count = 0

    @property
    def name(self) -> str:
        return "flip_after_n_stub"

    @property
    def state(self):
        return self._state

    def set_running(self) -> None:
        self._state = StrategyState.RUNNING

    def evaluate(self, features: Dict[str, Any]) -> StrategySignal:
        if self._state != StrategyState.RUNNING:
            return StrategySignal.hold(
                symbol="BTCUSDT", strategy_name=self.name,
                reason="not_running",
            )
        if not features.get("has_sufficient_data", False):
            return StrategySignal.hold(
                symbol="BTCUSDT", strategy_name=self.name,
                reason="warming",
            )
        self._n_eval += 1
        # Primeira chamada → BUY (SL dentro do limite RiskEngine 5%)
        if self._n_eval == 1:
            self._signal_count += 1
            return StrategySignal.buy(
                symbol="BTCUSDT", strategy_name=self.name,
                entry_price=65000.0, stop_loss_price=63000.0,  # 3.08%
                take_profit_price=200000.0, position_size_usd=200.0,
            )
        # Após flip_after avaliações → SELL contrário (também 3.08%)
        if self._n_eval >= self._flip_after:
            self._signal_count += 1
            return StrategySignal.sell(
                symbol="BTCUSDT", strategy_name=self.name,
                entry_price=65000.0, stop_loss_price=67000.0,
                take_profit_price=60000.0, position_size_usd=200.0,
            )
        return StrategySignal.hold(
            symbol="BTCUSDT", strategy_name=self.name, reason="waiting",
        )

    def generate_signal(self, market_data: Dict[str, Any]) -> Optional[Any]:
        return None

    def on_signal_approved(self, signal) -> None:
        pass

    def on_signal_rejected(self, signal, reason: str) -> None:
        pass

    def on_trade_closed(self, symbol: str, pnl: float) -> None:
        pass

    def reset(self) -> None:
        self._n_eval = 0
        self._state = StrategyState.WARMING_UP


def _build(*, allow_opposite: bool):
    # Tendência leve para manter SL/TP válidos ao longo do backtest.
    candles = generate_trending_candles(
        n=80, base_price=65000.0, trend_pct_per_candle=0.0001,
        volatility_pct=0.001,
    )
    strategy = FlipAfterNStrategy(flip_after=4)
    strategy.set_running()
    policy = ExitPolicy(
        provider_capability=_cap(),
        allow_close_on_opposite_signal=allow_opposite,
    )
    engine = BacktestEngine(
        strategy=strategy,
        risk_engine=RiskEngine(initial_capital=5000.0),
        feature_engine=FeatureEngine(),
        initial_capital=5000.0,
        min_candles=5,
        symbol="BTCUSDT",
        use_exit_policy=True,
        exit_policy=policy,
    )
    report = engine.run(candles)
    return engine, strategy, report


class TestOppositeSignalGate:

    def test_disabled_does_not_fire(self):
        _, _, report = _build(allow_opposite=False)
        for t in report.trades:
            assert t.close_reason != CloseReason.OPPOSITE_SIGNAL


class TestOppositeSignalCloses:

    def test_enabled_fires_close(self):
        _, _, report = _build(allow_opposite=True)
        # Deve haver pelo menos 1 trade aberto e algum fechado por OPPOSITE
        close_reasons = [t.close_reason for t in report.trades]
        assert any(r == CloseReason.OPPOSITE_SIGNAL for r in close_reasons), (
            f"Esperado pelo menos 1 OPPOSITE_SIGNAL, obtido {close_reasons}"
        )

    def test_no_flip_after_opposite_in_same_cycle(self):
        """
        Após fechar por OPPOSITE no candle i, o BacktestEngine NÃO abre
        nova posição no candle i — invariante de anti-flip preservada.
        """
        engine, _, report = _build(allow_opposite=True)
        # Encontra o primeiro fechamento por OPPOSITE
        first_opp = next(
            (t for t in report.trades
             if t.close_reason == CloseReason.OPPOSITE_SIGNAL),
            None,
        )
        assert first_opp is not None
        exit_idx = first_opp.exit_candle_idx
        # Qualquer trade aberto no exit_idx (mesmo candle) é flip — proibido
        flipped = [
            t for t in report.trades
            if t.entry_candle_idx == exit_idx and t is not first_opp
        ]
        assert flipped == [], (
            f"Flip detectado no candle {exit_idx}: {flipped}"
        )


class TestSnapshotForOppositeSignal:

    def test_snapshot_contains_opposite_metadata(self):
        _, _, report = _build(allow_opposite=True)
        opp = next(
            (t for t in report.trades
             if t.close_reason == CloseReason.OPPOSITE_SIGNAL),
            None,
        )
        assert opp is not None
        snap = opp.exit_decision_snapshot
        assert snap is not None
        assert snap["reason"] == "opposite_signal"
        assert snap["source"] == "rule_opposite"
        assert "opposite_action" in snap
