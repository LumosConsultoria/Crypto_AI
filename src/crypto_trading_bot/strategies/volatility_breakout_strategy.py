"""
VolatilityBreakoutStrategy — Rompimento + Volatilidade + Filtro Direcional (FASE 10)
=====================================================================================
⚠️  AVISOS OBRIGATÓRIOS:
    - Estratégia determinística para PESQUISA OFFLINE (backtest + paper).
    - NÃO valida lucro em produção. NÃO promete performance.
    - ZERO consumo de API real. ZERO IA/LLM. ZERO rede.
    - Stop loss obrigatório. BUY sempre satisfaz SL < entry < TP.
    - Sem hardcode de capital/sizing/leverage. Tudo via construtor.

LÓGICA DE ENTRADA (BUY-only nesta fase):
    1. Rompimento de banda superior de Bollinger:
       last_close > bb_upper × (1 + breakout_buffer_pct).
    2. Volatilidade suficiente (filtro de range comprimido):
       bb_bandwidth >= min_bandwidth.
       (bb_bandwidth = (upper - lower) / middle — already provided by
       FeatureEngine).
    3. Filtro direcional: last_close > EMA(direction_filter_period)
       — confirma que o rompimento ocorre acima da tendência de fundo.
    4. Sem posição aberta no momento.

RISCO E ALVO (determinísticos):
    - stop_loss_price = entry_price - stop_atr_multiplier × ATR.
    - Fallback se ATR indisponível: entry_price × (1 - stop_fallback_pct).
    - take_profit_price = entry_price + risk_reward_ratio × (entry - stop).
    - Garantia: 0 < stop_loss_price < entry_price < take_profit_price.

NOTA SOBRE BOLLINGER E FEATUREENGINE:
    A FeatureEngine padrão produz Bollinger de 20 períodos / 2 desvios.
    Esta estratégia consome `bb_upper`, `bb_bandwidth` e `last_close` do
    dicionário de features. Não altera o FeatureEngine (proibição da FASE 10).

PROVIDER-AGNOSTIC:
    Consome apenas o dicionário de FeatureEngine. Não chama exchanges.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from crypto_trading_bot.logging_system.logger import get_logger
from crypto_trading_bot.risk.risk_engine import TradingSignal
from crypto_trading_bot.strategies.base_strategy import BaseStrategy, StrategyState
from crypto_trading_bot.strategies.signal_model import StrategySignal

_logger = get_logger(__name__)


# Defaults — todos sobrescrevíveis via construtor.
_DEFAULT_DIRECTION_FILTER_PERIOD: int = 50
_DEFAULT_MIN_BANDWIDTH: float = 0.015   # bb_bandwidth mínima (sem unidades)
_DEFAULT_BREAKOUT_BUFFER_PCT: float = 0.0   # acima da bb_upper
_DEFAULT_STOP_ATR_MULTIPLIER: float = 1.5
_DEFAULT_STOP_FALLBACK_PCT: float = 0.015
_DEFAULT_RISK_REWARD_RATIO: float = 2.0
_DEFAULT_POSITION_SIZE_USD: float = 200.0


class VolatilityBreakoutStrategy(BaseStrategy):
    """
    Estratégia determinística de rompimento + volatilidade + filtro direcional.

    Parâmetros (todos explícitos):
        direction_filter_period:  Período da EMA usada como filtro direcional.
        min_bandwidth:            bb_bandwidth mínima (filtro de range estreito).
        breakout_buffer_pct:      Margem percentual acima da bb_upper para
                                  considerar rompimento.
        stop_atr_multiplier:      Multiplicador do ATR para stop.
        stop_fallback_pct:        Fallback de stop quando ATR indisponível.
        risk_reward_ratio:        Razão TP/risco.
        position_size_usd:        Notional em USD por sinal.

    Não há SELL nesta fase; SELL é fora de escopo da FASE 10.
    """

    def __init__(
        self,
        direction_filter_period: int = _DEFAULT_DIRECTION_FILTER_PERIOD,
        min_bandwidth: float = _DEFAULT_MIN_BANDWIDTH,
        breakout_buffer_pct: float = _DEFAULT_BREAKOUT_BUFFER_PCT,
        stop_atr_multiplier: float = _DEFAULT_STOP_ATR_MULTIPLIER,
        stop_fallback_pct: float = _DEFAULT_STOP_FALLBACK_PCT,
        risk_reward_ratio: float = _DEFAULT_RISK_REWARD_RATIO,
        position_size_usd: float = _DEFAULT_POSITION_SIZE_USD,
    ) -> None:
        if direction_filter_period <= 0:
            raise ValueError(
                f"direction_filter_period deve ser positivo: "
                f"{direction_filter_period}"
            )
        if min_bandwidth < 0:
            raise ValueError(
                f"min_bandwidth deve ser >= 0: {min_bandwidth}"
            )
        if breakout_buffer_pct < 0:
            raise ValueError(
                f"breakout_buffer_pct deve ser >= 0: {breakout_buffer_pct}"
            )
        if stop_atr_multiplier <= 0:
            raise ValueError(
                f"stop_atr_multiplier deve ser positivo: {stop_atr_multiplier}"
            )
        if not (0 < stop_fallback_pct < 1):
            raise ValueError(
                f"stop_fallback_pct deve estar em (0, 1): {stop_fallback_pct}"
            )
        if risk_reward_ratio <= 0:
            raise ValueError(
                f"risk_reward_ratio deve ser positivo: {risk_reward_ratio}"
            )
        if position_size_usd <= 0:
            raise ValueError(
                f"position_size_usd deve ser positivo: {position_size_usd}"
            )

        self._direction_filter_period = direction_filter_period
        self._min_bandwidth = min_bandwidth
        self._breakout_buffer_pct = breakout_buffer_pct
        self._stop_atr_multiplier = stop_atr_multiplier
        self._stop_fallback_pct = stop_fallback_pct
        self._risk_reward_ratio = risk_reward_ratio
        self._position_size_usd = position_size_usd
        self._has_open_position: bool = False

        super().__init__()

        _logger.info(
            f"[{self.name}] Parâmetros | "
            f"dir_filter=EMA{direction_filter_period} | "
            f"min_bw={min_bandwidth:.4f} | buffer={breakout_buffer_pct:.4%} | "
            f"stop={stop_atr_multiplier}×ATR (fallback={stop_fallback_pct:.1%}) | "
            f"R:R=1:{risk_reward_ratio} | size_usd={position_size_usd}"
        )

    # -----------------------------------------------------------------------
    # Interface BaseStrategy
    # -----------------------------------------------------------------------

    @property
    def name(self) -> str:
        return (
            f"vol_breakout"
            f"_bb_filter_e{self._direction_filter_period}"
            f"_bw{self._min_bandwidth:.3f}"
        )

    def generate_signal(
        self, market_data: Dict[str, Any]
    ) -> Optional[TradingSignal]:
        signal = self.evaluate(market_data)
        if signal.is_actionable:
            return signal.to_trading_signal()
        return None

    def reset(self) -> None:
        self._has_open_position = False
        self._state = StrategyState.WARMING_UP
        _logger.debug(f"[{self.name}] Estado resetado")

    # -----------------------------------------------------------------------
    # evaluate() — consumo direto do FeatureEngine
    # -----------------------------------------------------------------------

    def evaluate(self, features: Dict[str, Any]) -> StrategySignal:
        symbol: str = str(features.get("symbol") or "UNKNOWN")

        if self._state != StrategyState.RUNNING:
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=self.name,
                reason=f"Estratégia inativa: {self._state.value}",
            )

        if not features.get("has_sufficient_data", False):
            n = features.get("n_candles", 0)
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=self.name,
                reason=f"Dados insuficientes: {n} candles",
            )

        last_close = float(features.get("last_close", 0.0))
        last_atr = float(features.get("last_atr", float("nan")))
        bb_upper = float(features.get("last_bb_upper", float("nan")))
        bb_bandwidth = self._get_last_from_series(features, "bb_bandwidth")
        ema_direction = self._get_last_from_series(
            features, f"ema_{self._direction_filter_period}"
        )

        if last_close <= 0:
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=self.name,
                reason=f"Preço inválido: last_close={last_close}",
            )
        if math.isnan(bb_upper) or bb_upper <= 0:
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=self.name,
                reason=f"bb_upper indisponível: {bb_upper}",
            )
        if math.isnan(bb_bandwidth):
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=self.name,
                reason="bb_bandwidth indisponível",
            )
        if math.isnan(ema_direction):
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=self.name,
                reason=(
                    f"Filtro direcional EMA{self._direction_filter_period} "
                    f"indisponível"
                ),
            )

        # Regras determinísticas
        breakout_threshold = bb_upper * (1.0 + self._breakout_buffer_pct)
        breakout = last_close > breakout_threshold
        volatility_ok = bb_bandwidth >= self._min_bandwidth
        directional_ok = last_close > ema_direction
        no_position = not self._has_open_position

        _logger.debug(
            f"[{self.name}] {symbol} | close={last_close:.2f} | "
            f"bb_upper={bb_upper:.2f} (thr={breakout_threshold:.2f}) | "
            f"bw={bb_bandwidth:.4f} (min={self._min_bandwidth:.4f}) | "
            f"ema_dir={ema_direction:.2f} | "
            f"breakout={breakout} | vol_ok={volatility_ok} | "
            f"dir_ok={directional_ok} | open_pos={self._has_open_position}"
        )

        if not (breakout and volatility_ok and directional_ok and no_position):
            reasons = []
            if not breakout:
                reasons.append(
                    f"sem rompimento: close={last_close:.2f} "
                    f"≤ bb_upper*(1+buf)={breakout_threshold:.2f}"
                )
            if not volatility_ok:
                reasons.append(
                    f"bandwidth={bb_bandwidth:.4f} < "
                    f"min={self._min_bandwidth:.4f}"
                )
            if not directional_ok:
                reasons.append(
                    f"filtro direcional: close={last_close:.2f} "
                    f"≤ EMA{self._direction_filter_period}={ema_direction:.2f}"
                )
            if not no_position:
                reasons.append("posição já aberta")
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=self.name,
                reason="; ".join(reasons),
            )

        # Stop loss determinístico
        stop_loss_price = self._calculate_stop_loss(last_close, last_atr)
        if stop_loss_price <= 0 or stop_loss_price >= last_close:
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=self.name,
                reason=(
                    f"Stop loss inviável: stop={stop_loss_price:.2f}, "
                    f"entry={last_close:.2f}"
                ),
            )

        # TP determinístico
        risk_per_unit = last_close - stop_loss_price
        take_profit_price = round(
            last_close + self._risk_reward_ratio * risk_per_unit, 2
        )
        if take_profit_price <= last_close:
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=self.name,
                reason=(
                    f"TP inviável: tp={take_profit_price:.2f}, "
                    f"entry={last_close:.2f}"
                ),
            )

        _logger.info(
            f"[{self.name}] SINAL BUY | symbol={symbol} | "
            f"entry={last_close:.2f} | stop={stop_loss_price:.2f} | "
            f"tp={take_profit_price:.2f} | "
            f"bb_upper={bb_upper:.2f} | bw={bb_bandwidth:.4f}"
        )

        signal = StrategySignal.buy(
            symbol=symbol,
            strategy_name=self.name,
            entry_price=round(last_close, 2),
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            position_size_usd=self._position_size_usd,
            leverage=1.0,
            metadata={
                "bb_upper": round(bb_upper, 2),
                "bb_bandwidth": round(bb_bandwidth, 6),
                f"ema_{self._direction_filter_period}": round(ema_direction, 2),
                "atr": round(last_atr, 4) if not math.isnan(last_atr) else None,
                "stop_source": (
                    "atr" if (not math.isnan(last_atr) and last_atr > 0)
                    else "fallback_pct"
                ),
                "risk_reward_ratio": self._risk_reward_ratio,
            },
        )

        self._signal_count += 1
        self._last_signal = signal
        return signal

    # -----------------------------------------------------------------------
    # Callbacks de ciclo de vida
    # -----------------------------------------------------------------------

    def on_signal_approved(self, signal: TradingSignal) -> None:
        super().on_signal_approved(signal)
        self._has_open_position = True

    def on_trade_closed(self, symbol: str, pnl: float) -> None:
        super().on_trade_closed(symbol, pnl)
        self._has_open_position = False

    # -----------------------------------------------------------------------
    # Métodos privados
    # -----------------------------------------------------------------------

    def _calculate_stop_loss(self, entry_price: float, atr: float) -> float:
        if not math.isnan(atr) and atr > 0:
            stop = entry_price - (self._stop_atr_multiplier * atr)
        else:
            stop = entry_price * (1.0 - self._stop_fallback_pct)
        return round(stop, 2)

    @staticmethod
    def _get_last_from_series(features: Dict[str, Any], key: str) -> float:
        series = features.get(key)
        if series is None:
            return float("nan")
        try:
            val = float(series.iloc[-1])
            return val if not math.isnan(val) else float("nan")
        except (IndexError, TypeError, AttributeError):
            return float("nan")

    def __repr__(self) -> str:
        return (
            f"VolatilityBreakoutStrategy("
            f"dir=EMA{self._direction_filter_period} | "
            f"min_bw={self._min_bandwidth:.4f} | "
            f"buffer={self._breakout_buffer_pct:.4%} | "
            f"stop={self._stop_atr_multiplier}×ATR | "
            f"R:R=1:{self._risk_reward_ratio} | "
            f"size={self._position_size_usd}USD | "
            f"state={self._state.value})"
        )


# ---------------------------------------------------------------------------
# Factory + StrategySpec
# ---------------------------------------------------------------------------

def _volatility_breakout_factory(
    config: Dict[str, Any],
) -> "VolatilityBreakoutStrategy":
    strategy = VolatilityBreakoutStrategy(
        direction_filter_period=int(config.get(
            "direction_filter_period", _DEFAULT_DIRECTION_FILTER_PERIOD
        )),
        min_bandwidth=float(config.get("min_bandwidth", _DEFAULT_MIN_BANDWIDTH)),
        breakout_buffer_pct=float(config.get(
            "breakout_buffer_pct", _DEFAULT_BREAKOUT_BUFFER_PCT
        )),
        stop_atr_multiplier=float(config.get(
            "stop_atr_multiplier", _DEFAULT_STOP_ATR_MULTIPLIER
        )),
        stop_fallback_pct=float(config.get(
            "stop_fallback_pct", _DEFAULT_STOP_FALLBACK_PCT
        )),
        risk_reward_ratio=float(config.get(
            "risk_reward_ratio", _DEFAULT_RISK_REWARD_RATIO
        )),
        position_size_usd=float(config.get(
            "position_size_usd", _DEFAULT_POSITION_SIZE_USD
        )),
    )
    strategy.set_running()
    return strategy


def build_volatility_breakout_spec():
    """Constrói StrategySpec para o framework de pesquisa."""
    from crypto_trading_bot.research.strategy_research import StrategySpec

    return StrategySpec(
        name="vol_breakout_default",
        factory=_volatility_breakout_factory,
        description=(
            "Rompimento de Bollinger superior + filtro de bandwidth + "
            "filtro direcional por EMA. BUY-only. Stop ATR e TP por R:R."
        ),
        default_config={
            "direction_filter_period": _DEFAULT_DIRECTION_FILTER_PERIOD,
            "min_bandwidth": _DEFAULT_MIN_BANDWIDTH,
            "breakout_buffer_pct": _DEFAULT_BREAKOUT_BUFFER_PCT,
            "stop_atr_multiplier": _DEFAULT_STOP_ATR_MULTIPLIER,
            "stop_fallback_pct": _DEFAULT_STOP_FALLBACK_PCT,
            "risk_reward_ratio": _DEFAULT_RISK_REWARD_RATIO,
            "position_size_usd": _DEFAULT_POSITION_SIZE_USD,
        },
        tags=("breakout", "volatility", "deterministic", "research"),
    )
