"""
MeanReversionStrategy — PROTOTIPO RESEARCH-ONLY (FASE 38)
=========================================================
⚠️  RESEARCH / PROTOTIPO. NAO eh estrategia definitiva. NAO entra no
    registry operacional default. NAO pode ser usada por demo/session
    runner. Serve APENAS para pesquisa offline (descobrir se ha indicio
    de edge por regime). NAO promete performance.
⚠️  ZERO rede / API / IA / ordem. Stop loss obrigatorio. O RiskEngine
    continua soberano (piso 0.005 inalterado): sinais com SL abaixo do
    piso sao bloqueados pelo RiskEngine — comportamento esperado.

HIPOTESE (regime range / baixa volatilidade / chop):
    Reversao a media — comprar quando o preco esta "esticado" para baixo
    (abaixo da banda inferior de Bollinger) e o RSI em zona de sobrevenda,
    visando o retorno a regiao da media (BB middle).

LOGICA DE ENTRADA (BUY-only neste prototipo):
    1. last_close <= bb_lower (preco abaixo da banda inferior).
    2. RSI(period) <= rsi_oversold (ou NaN durante warm-up).
    3. Sem posicao aberta.

RISCO E ALVO (deterministicos):
    - stop_loss_price = entry - stop_atr_multiplier x ATR (fallback %).
    - take_profit_price = entry + risk_reward_ratio x risco (default R:R
      menor, coerente com reversao a media).
    - Garantia: 0 < stop < entry < tp.
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

_DEFAULT_RSI_PERIOD: int = 14
_DEFAULT_RSI_OVERSOLD: float = 30.0
_DEFAULT_STOP_ATR_MULTIPLIER: float = 1.5
_DEFAULT_STOP_FALLBACK_PCT: float = 0.015
_DEFAULT_RISK_REWARD_RATIO: float = 1.5
_DEFAULT_POSITION_SIZE_USD: float = 200.0
_MIN_CANDLES: int = 60


class MeanReversionStrategy(BaseStrategy):
    """Prototipo research-only de reversao a media (BUY-only)."""

    def __init__(
        self,
        rsi_period: int = _DEFAULT_RSI_PERIOD,
        rsi_oversold: float = _DEFAULT_RSI_OVERSOLD,
        stop_atr_multiplier: float = _DEFAULT_STOP_ATR_MULTIPLIER,
        stop_fallback_pct: float = _DEFAULT_STOP_FALLBACK_PCT,
        risk_reward_ratio: float = _DEFAULT_RISK_REWARD_RATIO,
        position_size_usd: float = _DEFAULT_POSITION_SIZE_USD,
    ) -> None:
        if rsi_period <= 0:
            raise ValueError(f"rsi_period deve ser positivo: {rsi_period}")
        if not (0 < rsi_oversold < 100):
            raise ValueError(
                f"rsi_oversold em (0,100): {rsi_oversold}")
        if stop_atr_multiplier <= 0:
            raise ValueError(
                f"stop_atr_multiplier positivo: {stop_atr_multiplier}")
        if not (0 < stop_fallback_pct < 1):
            raise ValueError(
                f"stop_fallback_pct em (0,1): {stop_fallback_pct}")
        if risk_reward_ratio <= 0:
            raise ValueError(
                f"risk_reward_ratio positivo: {risk_reward_ratio}")
        if position_size_usd <= 0:
            raise ValueError(
                f"position_size_usd positivo: {position_size_usd}")

        self._rsi_period = rsi_period
        self._rsi_oversold = rsi_oversold
        self._stop_atr_multiplier = stop_atr_multiplier
        self._stop_fallback_pct = stop_fallback_pct
        self._risk_reward_ratio = risk_reward_ratio
        self._position_size_usd = position_size_usd
        self._has_open_position: bool = False
        super().__init__()

    @property
    def name(self) -> str:
        return f"mean_reversion_research_r{self._rsi_period}"

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
            return StrategySignal.hold(
                symbol=symbol, strategy_name=self.name,
                reason=f"inativa: {self._state.value}")
        if not features.get("has_sufficient_data", False):
            return StrategySignal.hold(
                symbol=symbol, strategy_name=self.name,
                reason=f"dados insuficientes: {features.get('n_candles', 0)}")

        last_close = float(features.get("last_close", 0.0))
        last_rsi = float(features.get("last_rsi", float("nan")))
        last_atr = float(features.get("last_atr", float("nan")))
        bb_lower = _last(features, "bb_lower")
        bb_middle = _last(features, "bb_middle")

        if last_close <= 0 or math.isnan(bb_lower) or math.isnan(bb_middle):
            return StrategySignal.hold(
                symbol=symbol, strategy_name=self.name,
                reason="preco/BB indisponivel")

        oversold_band = last_close <= bb_lower
        rsi_ok = math.isnan(last_rsi) or last_rsi <= self._rsi_oversold
        no_position = not self._has_open_position

        if not (oversold_band and rsi_ok and no_position):
            reasons = []
            if not oversold_band:
                reasons.append(
                    f"close {last_close:.2f} > bb_lower {bb_lower:.2f}")
            if not rsi_ok:
                reasons.append(f"RSI {last_rsi:.1f} > {self._rsi_oversold}")
            if not no_position:
                reasons.append("posicao aberta")
            return StrategySignal.hold(
                symbol=symbol, strategy_name=self.name,
                reason="; ".join(reasons))

        stop = self._stop(last_close, last_atr)
        if stop <= 0 or stop >= last_close:
            return StrategySignal.hold(
                symbol=symbol, strategy_name=self.name,
                reason=f"stop inviavel: {stop:.2f}")
        risk = last_close - stop
        tp = round(last_close + self._risk_reward_ratio * risk, 2)
        if tp <= last_close:
            return StrategySignal.hold(
                symbol=symbol, strategy_name=self.name,
                reason="tp inviavel")

        signal = StrategySignal.buy(
            symbol=symbol, strategy_name=self.name,
            entry_price=round(last_close, 2), stop_loss_price=stop,
            take_profit_price=tp, position_size_usd=self._position_size_usd,
            leverage=1.0,
            metadata={
                "family": "mean_reversion", "prototype": True,
                "bb_lower": round(bb_lower, 2),
                "bb_middle": round(bb_middle, 2),
                "rsi": round(last_rsi, 2) if not math.isnan(last_rsi)
                else None,
            })
        self._signal_count += 1
        self._last_signal = signal
        return signal

    def on_signal_approved(self, signal: TradingSignal) -> None:
        super().on_signal_approved(signal)
        self._has_open_position = True

    def on_trade_closed(self, symbol: str, pnl: float) -> None:
        super().on_trade_closed(symbol, pnl)
        self._has_open_position = False

    def _stop(self, entry: float, atr: float) -> float:
        if not math.isnan(atr) and atr > 0:
            return round(entry - self._stop_atr_multiplier * atr, 2)
        return round(entry * (1.0 - self._stop_fallback_pct), 2)


def _last(features: Dict[str, Any], key: str) -> float:
    s = features.get(key)
    if s is None:
        return float("nan")
    try:
        v = float(s.iloc[-1])
        return v if not math.isnan(v) else float("nan")
    except (IndexError, TypeError, AttributeError):
        return float("nan")


def _mean_reversion_factory(config: Dict[str, Any]) -> MeanReversionStrategy:
    s = MeanReversionStrategy(
        rsi_period=int(config.get("rsi_period", _DEFAULT_RSI_PERIOD)),
        rsi_oversold=float(config.get("rsi_oversold", _DEFAULT_RSI_OVERSOLD)),
        stop_atr_multiplier=float(config.get(
            "stop_atr_multiplier", _DEFAULT_STOP_ATR_MULTIPLIER)),
        stop_fallback_pct=float(config.get(
            "stop_fallback_pct", _DEFAULT_STOP_FALLBACK_PCT)),
        risk_reward_ratio=float(config.get(
            "risk_reward_ratio", _DEFAULT_RISK_REWARD_RATIO)),
        position_size_usd=float(config.get(
            "position_size_usd", _DEFAULT_POSITION_SIZE_USD)),
    )
    s.set_running()
    return s


def build_mean_reversion_spec():
    """StrategySpec do prototipo. tags marcam research/prototype; NAO eh
    registrado no registry operacional default."""
    from crypto_trading_bot.research.strategy_research import StrategySpec
    return StrategySpec(
        name="mean_reversion_research",
        factory=_mean_reversion_factory,
        description=(
            "PROTOTIPO RESEARCH: reversao a media (BUY abaixo da BB "
            "inferior + RSI sobrevendido). Nao definitiva; fora do "
            "registry operacional."),
        default_config={
            "rsi_period": _DEFAULT_RSI_PERIOD,
            "rsi_oversold": _DEFAULT_RSI_OVERSOLD,
            "stop_atr_multiplier": _DEFAULT_STOP_ATR_MULTIPLIER,
            "stop_fallback_pct": _DEFAULT_STOP_FALLBACK_PCT,
            "risk_reward_ratio": _DEFAULT_RISK_REWARD_RATIO,
            "position_size_usd": _DEFAULT_POSITION_SIZE_USD,
        },
        tags=("mean-reversion", "research", "prototype", "deterministic"),
    )
