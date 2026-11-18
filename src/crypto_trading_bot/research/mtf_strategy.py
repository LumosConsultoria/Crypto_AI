"""
Multi-timeframe execution strategies (FASE 45). Componente minimo.

Consomem SETUPS de 15m (mtf_setups) + regime 1h alinhado (causal) e
executam:
  - Variante A: no fechamento do candle de setup em 15m (serie 15m).
  - Variante B: apos o MESMO setup 15m, no GATILHO causal do 5m dentro de
    uma janela limitada (serie 5m). Mesmo stop/target/setup_id/sizing.

Stop ESTRUTURAL vem do setup (15m). Se stop_dist_pct < piso 0,5% =>
HOLD com motivo `structural_stop_below_floor` (RiskEngine continua soberano;
sem bypass). Duck-typed p/ o BacktestEngine (name/evaluate/on_*/reset).
"""

from __future__ import annotations

import bisect
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence

from crypto_trading_bot.research.htf_regime_filter import _ts_key

_PISO = 0.005


def _regime_ok(regime: Optional[str], direction: str) -> bool:
    if regime is None:
        return False
    if direction == "long":
        return regime == "trend_up"
    return regime == "trend_down"


def _emit(symbol, name, direction, entry, stop, target, size):
    from crypto_trading_bot.strategies.signal_model import StrategySignal
    if direction == "long":
        return StrategySignal.buy(
            symbol=symbol, strategy_name=name, entry_price=round(entry, 2),
            stop_loss_price=round(stop, 2), take_profit_price=round(target, 2),
            position_size_usd=size, leverage=1.0,
            metadata={"phase": "fase45", "direction": direction})
    return StrategySignal.sell(
        symbol=symbol, strategy_name=name, entry_price=round(entry, 2),
        stop_loss_price=round(stop, 2), take_profit_price=round(target, 2),
        position_size_usd=size, leverage=1.0,
        metadata={"phase": "fase45", "direction": direction})


def _hold(symbol, name, reason):
    from crypto_trading_bot.strategies.signal_model import StrategySignal
    return StrategySignal.hold(symbol=symbol, strategy_name=name,
                               reason=reason)


class _Base:
    def __init__(self, name, regime_map, size, piso):
        self.name = name
        self._regime_map = regime_map
        self._size = float(size)
        self._piso = float(piso)
        self._open = False
        self.blocked_below_floor = 0
        self.regime_rejected = 0
        self.entries = 0

    def on_signal_approved(self, signal) -> None:
        self._open = True
        self.entries += 1

    def on_signal_rejected(self, signal, reason: str) -> None:
        pass

    def on_trade_closed(self, symbol: str, pnl: float) -> None:
        self._open = False

    def reset(self) -> None:
        self._open = False

    def generate_signal(self, market_data):
        return None

    @staticmethod
    def _cur_ts(features):
        tss = features.get("timestamps")
        try:
            if tss is not None and len(tss) > 0:
                return tss.iloc[-1]
        except Exception:  # noqa: BLE001
            return None
        return None


class MtfSetupStrategyA(_Base):
    """Variante A — entrada no fechamento do setup em 15m."""

    def __init__(self, *, setups: Sequence, regime_map: Dict[int, Any],
                 hypothesis_id: str, position_size_usd: float,
                 piso: float = _PISO) -> None:
        super().__init__(f"mtf_{hypothesis_id}_A15m", regime_map,
                         position_size_usd, piso)
        self._by_ts = {_ts_key(s.open_ts): s for s in setups}

    def evaluate(self, features):
        sym = str(features.get("symbol") or "BTCUSDT")
        if self._open:
            return _hold(sym, self.name, "posicao aberta")
        ts = self._cur_ts(features)
        if ts is None:
            return _hold(sym, self.name, "sem timestamp")
        s = self._by_ts.get(_ts_key(ts))
        if s is None:
            return _hold(sym, self.name, "sem setup")
        reg = self._regime_map.get(_ts_key(ts))
        if not _regime_ok(reg, s.direction):
            self.regime_rejected += 1
            return _hold(sym, self.name, f"regime 1h nao confirma:{reg}")
        if s.stop_dist_pct < self._piso:
            self.blocked_below_floor += 1
            return _hold(sym, self.name, "structural_stop_below_floor")
        return _emit(sym, self.name, s.direction, s.entry_ref, s.stop,
                     s.target, self._size)


class MtfSetupStrategyB(_Base):
    """Variante B — gatilho causal no 5m dentro de janela apos o setup 15m."""

    def __init__(self, *, setups: Sequence, regime_map: Dict[int, Any],
                 hypothesis_id: str, position_size_usd: float,
                 window_candles: int = 6, low_interval_minutes: int = 5,
                 piso: float = _PISO) -> None:
        super().__init__(f"mtf_{hypothesis_id}_B5m", regime_map,
                         position_size_usd, piso)
        self._setups = sorted(setups, key=lambda s: s.close_ts)
        self._close_ts = [s.close_ts for s in self._setups]
        self._win = timedelta(minutes=window_candles * low_interval_minutes)
        self._low_delta = timedelta(minutes=low_interval_minutes)
        self._entered_ids: set = set()

    def _active_setup(self, decision_time):
        """Setup mais recente com close_ts <= decision_time e dentro da
        janela (causal). bisect O(log n)."""
        pos = bisect.bisect_right(self._close_ts, decision_time) - 1
        if pos < 0:
            return None
        s = self._setups[pos]
        if decision_time - s.close_ts > self._win:
            return None      # janela expirou (confirmation_missed)
        return s

    def evaluate(self, features):
        sym = str(features.get("symbol") or "BTCUSDT")
        if self._open:
            return _hold(sym, self.name, "posicao aberta")
        ts5 = self._cur_ts(features)
        if ts5 is None:
            return _hold(sym, self.name, "sem timestamp")
        decision = ts5 + self._low_delta
        s = self._active_setup(decision)
        if s is None:
            return _hold(sym, self.name, "sem setup ativo/janela")
        if s.setup_id in self._entered_ids:
            return _hold(sym, self.name, "setup ja executado")
        reg = self._regime_map.get(_ts_key(ts5))
        if not _regime_ok(reg, s.direction):
            self.regime_rejected += 1
            return _hold(sym, self.name, f"regime 1h nao confirma:{reg}")
        c5 = float(features.get("last_close", 0.0) or 0.0)
        trig = ((s.direction == "long" and c5 > s.entry_ref) or
                (s.direction == "short" and c5 < s.entry_ref))
        if not trig or c5 <= 0:
            return _hold(sym, self.name, "aguardando gatilho 5m")
        if s.stop_dist_pct < self._piso:
            self.blocked_below_floor += 1
            return _hold(sym, self.name, "structural_stop_below_floor")
        self._entered_ids.add(s.setup_id)
        # entrada no preco do 5m (c5); stop/target ESTRUTURAIS do setup 15m.
        return _emit(sym, self.name, s.direction, c5, s.stop, s.target,
                     self._size)


__all__ = ["MtfSetupStrategyA", "MtfSetupStrategyB"]
