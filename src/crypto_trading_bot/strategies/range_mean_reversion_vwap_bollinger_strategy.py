"""
RangeMeanReversionVwapBollingerStrategy — PROTOTIPO RESEARCH-ONLY (FASE 40)
===========================================================================
⚠️  RESEARCH / PROTOTIPO. NAO eh estrategia definitiva. NAO entra no
    registry operacional default. NAO pode ser usada por demo/session
    runner. Pesquisa offline apenas. NAO promete performance.
⚠️  ZERO rede / API / IA / ordem. Stop loss obrigatorio. RiskEngine
    soberano (piso 0.005 inalterado): SL abaixo do piso => bloqueado.
⚠️  BIDIRECIONAL no BACKTEST (long + short SIMULADOS). Execucao real de
    SHORT continua gated/bloqueada fora do backtest (gates intactos).

HIPOTESE (regime range refinado): reversao a media com confirmacao de
VWAP + Bollinger + filtro de range + controle de volatilidade.

LOGICA (parametros FIXOS):
    Filtro de RANGE: |EMA_fast - EMA_slow| / close <= flat_threshold
      (aproxima regime range; evita operar em tendencia forte).
    Controle de VOLATILIDADE: bb_bandwidth em [min_bandwidth,
      max_bandwidth] (pula calmaria extrema e volatilidade extrema).
    LONG:  close <= bb_lower E close < VWAP E RSI <= rsi_oversold.
           SL = close - mult*ATR; TP = bb_middle (saida na media).
    SHORT: close >= bb_upper E close > VWAP E RSI >= rsi_overbought.
           SL = close + mult*ATR; TP = bb_middle (saida na media).
    Garantias: long 0<SL<entry<TP; short TP<entry<SL.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from crypto_trading_bot.logging_system.logger import get_logger
from crypto_trading_bot.risk.risk_engine import TradingSignal
from crypto_trading_bot.strategies.base_strategy import (
    BaseStrategy,
    StrategyState,
)
from crypto_trading_bot.strategies.signal_model import StrategySignal

_logger = get_logger(__name__)

_DEFAULT_RSI_PERIOD = 14
_DEFAULT_RSI_OVERSOLD = 30.0
_DEFAULT_RSI_OVERBOUGHT = 70.0
_DEFAULT_FLAT_THRESHOLD = 0.005       # |emaF-emaS|/close <= 0.5% => range
_DEFAULT_MIN_BANDWIDTH = 0.005        # controle de volatilidade (faixa util)
_DEFAULT_MAX_BANDWIDTH = 0.060
_DEFAULT_STOP_ATR_MULTIPLIER = 1.5
_DEFAULT_STOP_FALLBACK_PCT = 0.015
_DEFAULT_POSITION_SIZE_USD = 200.0
_DEFAULT_ENABLE_LONG = True
_DEFAULT_ENABLE_SHORT = True          # SIMULADO no backtest


class RangeMeanReversionVwapBollingerStrategy(BaseStrategy):
    """Prototipo research-only bidirecional (reversao a media VWAP/BB)."""

    def __init__(
        self,
        rsi_period: int = _DEFAULT_RSI_PERIOD,
        rsi_oversold: float = _DEFAULT_RSI_OVERSOLD,
        rsi_overbought: float = _DEFAULT_RSI_OVERBOUGHT,
        flat_threshold: float = _DEFAULT_FLAT_THRESHOLD,
        min_bandwidth: float = _DEFAULT_MIN_BANDWIDTH,
        max_bandwidth: float = _DEFAULT_MAX_BANDWIDTH,
        stop_atr_multiplier: float = _DEFAULT_STOP_ATR_MULTIPLIER,
        stop_fallback_pct: float = _DEFAULT_STOP_FALLBACK_PCT,
        position_size_usd: float = _DEFAULT_POSITION_SIZE_USD,
        enable_long: bool = _DEFAULT_ENABLE_LONG,
        enable_short: bool = _DEFAULT_ENABLE_SHORT,
    ) -> None:
        if rsi_period <= 0:
            raise ValueError(f"rsi_period positivo: {rsi_period}")
        if not (0 < rsi_oversold < rsi_overbought < 100):
            raise ValueError(
                "rsi: 0 < oversold < overbought < 100")
        if not (0 < flat_threshold < 1):
            raise ValueError("flat_threshold em (0,1)")
        if not (0 <= min_bandwidth < max_bandwidth):
            raise ValueError("0 <= min_bandwidth < max_bandwidth")
        if stop_atr_multiplier <= 0:
            raise ValueError("stop_atr_multiplier positivo")
        if not (0 < stop_fallback_pct < 1):
            raise ValueError("stop_fallback_pct em (0,1)")
        if position_size_usd <= 0:
            raise ValueError("position_size_usd positivo")

        self._rsi_period = rsi_period
        self._rsi_oversold = rsi_oversold
        self._rsi_overbought = rsi_overbought
        self._flat_threshold = flat_threshold
        self._min_bandwidth = min_bandwidth
        self._max_bandwidth = max_bandwidth
        self._stop_atr_multiplier = stop_atr_multiplier
        self._stop_fallback_pct = stop_fallback_pct
        self._position_size_usd = position_size_usd
        self._enable_long = bool(enable_long)
        self._enable_short = bool(enable_short)
        self._has_open_position: bool = False
        super().__init__()

    @property
    def name(self) -> str:
        return (f"range_mean_reversion_vwap_bollinger_research"
                f"_r{self._rsi_period}")

    def generate_signal(
        self, market_data: Dict[str, Any]
    ) -> Optional[TradingSignal]:
        sig = self.evaluate(market_data)
        return sig.to_trading_signal() if sig.is_actionable else None

    def reset(self) -> None:
        self._has_open_position = False
        self._state = StrategyState.WARMING_UP

    def evaluate(self, features: Dict[str, Any]) -> StrategySignal:
        symbol = str(features.get("symbol") or "UNKNOWN")
        if self._state != StrategyState.RUNNING:
            return self._hold(symbol, f"inativa: {self._state.value}")
        if not features.get("has_sufficient_data", False):
            return self._hold(
                symbol, f"dados insuficientes: {features.get('n_candles', 0)}")
        if self._has_open_position:
            return self._hold(symbol, "posicao aberta")

        close = float(features.get("last_close", 0.0))
        rsi = float(features.get("last_rsi", float("nan")))
        atr = float(features.get("last_atr", float("nan")))
        bb_lower = _last(features, "bb_lower")
        bb_upper = _last(features, "bb_upper")
        bb_middle = _last(features, "bb_middle")
        bandwidth = _last(features, "bb_bandwidth")
        vwap = _last(features, "vwap")
        ema_fast = _last(features, "ema_9")
        ema_slow = _last(features, "ema_21")

        if close <= 0 or any(math.isnan(x) for x in (
                bb_lower, bb_upper, bb_middle, vwap, ema_fast, ema_slow)):
            return self._hold(symbol, "preco/VWAP/BB/EMA indisponivel")

        # Filtro de RANGE (evita tendencia forte).
        flat = abs(ema_fast - ema_slow) / close <= self._flat_threshold
        if not flat:
            return self._hold(
                symbol, f"nao-range: |emaF-emaS|/close > "
                f"{self._flat_threshold}")
        # Controle de VOLATILIDADE.
        if not math.isnan(bandwidth) and not (
                self._min_bandwidth <= bandwidth <= self._max_bandwidth):
            return self._hold(
                symbol, f"bandwidth {bandwidth:.4f} fora da faixa util")

        # LONG: esticado abaixo + RSI baixo.
        if self._enable_long and close <= bb_lower and close < vwap \
                and (math.isnan(rsi) or rsi <= self._rsi_oversold):
            stop = self._stop_long(close, atr)
            tp = round(bb_middle, 2)
            if 0 < stop < close < tp:
                return self._mk(StrategySignal.buy, symbol, close, stop, tp,
                                side="long", vwap=vwap, rsi=rsi)
            return self._hold(symbol, "long: ordenacao SL/TP inviavel")

        # SHORT: esticado acima + RSI alto (SIMULADO no backtest).
        if self._enable_short and close >= bb_upper and close > vwap \
                and (math.isnan(rsi) or rsi >= self._rsi_overbought):
            stop = self._stop_short(close, atr)
            tp = round(bb_middle, 2)
            if tp < close < stop:
                return self._mk(StrategySignal.sell, symbol, close, stop, tp,
                                side="short", vwap=vwap, rsi=rsi)
            return self._hold(symbol, "short: ordenacao SL/TP inviavel")

        return self._hold(symbol, "sem setup de reversao a media")

    # ---- callbacks de ciclo de vida ----
    def on_signal_approved(self, signal: TradingSignal) -> None:
        super().on_signal_approved(signal)
        self._has_open_position = True

    def on_trade_closed(self, symbol: str, pnl: float) -> None:
        super().on_trade_closed(symbol, pnl)
        self._has_open_position = False

    # ---- helpers ----
    def _hold(self, symbol: str, reason: str) -> StrategySignal:
        return StrategySignal.hold(
            symbol=symbol, strategy_name=self.name, reason=reason)

    def _stop_long(self, entry: float, atr: float) -> float:
        if not math.isnan(atr) and atr > 0:
            return round(entry - self._stop_atr_multiplier * atr, 2)
        return round(entry * (1.0 - self._stop_fallback_pct), 2)

    def _stop_short(self, entry: float, atr: float) -> float:
        if not math.isnan(atr) and atr > 0:
            return round(entry + self._stop_atr_multiplier * atr, 2)
        return round(entry * (1.0 + self._stop_fallback_pct), 2)

    def _mk(self, ctor, symbol, entry, stop, tp, *, side, vwap, rsi):
        sig = ctor(
            symbol=symbol, strategy_name=self.name,
            entry_price=round(entry, 2), stop_loss_price=stop,
            take_profit_price=tp, position_size_usd=self._position_size_usd,
            leverage=1.0,
            metadata={
                "family": "range_mean_reversion_vwap_bollinger",
                "prototype": True, "side": side,
                "vwap": round(vwap, 2),
                "rsi": round(rsi, 2) if not math.isnan(rsi) else None,
            })
        self._signal_count += 1
        self._last_signal = sig
        return sig


def _last(features: Dict[str, Any], key: str) -> float:
    s = features.get(key)
    if s is None:
        return float("nan")
    try:
        v = float(s.iloc[-1])
        return v if not math.isnan(v) else float("nan")
    except (IndexError, TypeError, AttributeError):
        return float("nan")


def _factory(config: Dict[str, Any]):
    s = RangeMeanReversionVwapBollingerStrategy(
        rsi_period=int(config.get("rsi_period", _DEFAULT_RSI_PERIOD)),
        rsi_oversold=float(config.get("rsi_oversold", _DEFAULT_RSI_OVERSOLD)),
        rsi_overbought=float(config.get(
            "rsi_overbought", _DEFAULT_RSI_OVERBOUGHT)),
        flat_threshold=float(config.get(
            "flat_threshold", _DEFAULT_FLAT_THRESHOLD)),
        min_bandwidth=float(config.get(
            "min_bandwidth", _DEFAULT_MIN_BANDWIDTH)),
        max_bandwidth=float(config.get(
            "max_bandwidth", _DEFAULT_MAX_BANDWIDTH)),
        stop_atr_multiplier=float(config.get(
            "stop_atr_multiplier", _DEFAULT_STOP_ATR_MULTIPLIER)),
        stop_fallback_pct=float(config.get(
            "stop_fallback_pct", _DEFAULT_STOP_FALLBACK_PCT)),
        position_size_usd=float(config.get(
            "position_size_usd", _DEFAULT_POSITION_SIZE_USD)),
        enable_long=bool(config.get("enable_long", _DEFAULT_ENABLE_LONG)),
        enable_short=bool(config.get("enable_short", _DEFAULT_ENABLE_SHORT)),
    )
    s.set_running()
    return s


def build_range_mean_reversion_vwap_bollinger_spec():
    """StrategySpec do prototipo (FASE 40). research/prototype; FORA do
    registry operacional default."""
    from crypto_trading_bot.research.strategy_research import StrategySpec
    return StrategySpec(
        name="range_mean_reversion_vwap_bollinger_research",
        factory=_factory,
        description=(
            "PROTOTIPO RESEARCH (FASE 40): reversao a media com VWAP + "
            "Bollinger + filtro de range + controle de volatilidade. "
            "BIDIRECIONAL no backtest (short simulado). Fora do registry "
            "operacional; nao definitiva."),
        default_config={
            "rsi_period": _DEFAULT_RSI_PERIOD,
            "rsi_oversold": _DEFAULT_RSI_OVERSOLD,
            "rsi_overbought": _DEFAULT_RSI_OVERBOUGHT,
            "flat_threshold": _DEFAULT_FLAT_THRESHOLD,
            "min_bandwidth": _DEFAULT_MIN_BANDWIDTH,
            "max_bandwidth": _DEFAULT_MAX_BANDWIDTH,
            "stop_atr_multiplier": _DEFAULT_STOP_ATR_MULTIPLIER,
            "stop_fallback_pct": _DEFAULT_STOP_FALLBACK_PCT,
            "position_size_usd": _DEFAULT_POSITION_SIZE_USD,
            "enable_long": _DEFAULT_ENABLE_LONG,
            "enable_short": _DEFAULT_ENABLE_SHORT,
        },
        tags=("mean-reversion", "vwap", "bollinger", "research",
              "prototype", "deterministic", "bidirectional"),
    )
