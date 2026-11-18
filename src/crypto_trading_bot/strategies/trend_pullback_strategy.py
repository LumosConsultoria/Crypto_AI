"""
TrendPullbackStrategy — Estratégia Determinística de Tendência + Pullback (FASE 10)
====================================================================================
⚠️  AVISOS OBRIGATÓRIOS:
    - Estratégia determinística para PESQUISA OFFLINE (backtest + paper).
    - NÃO valida lucro em produção. NÃO promete performance.
    - ZERO consumo de API real. ZERO IA/LLM. ZERO rede.
    - Stop loss obrigatório. BUY sempre satisfaz SL < entry < TP.
    - Sem hardcode de capital/sizing/leverage. Tudo via construtor.

LÓGICA DE ENTRADA (BUY-only nesta fase):
    1. Tendência primária estabelecida: EMA(fast) > EMA(slow).
    2. Pullback para suporte: last_close <= EMA(fast) E last_close > EMA(slow).
       (preço regressou da máxima recente até a região da EMA rápida sem
        romper a tendência principal definida pela EMA lenta).
    3. Momentum não esgotado: RSI(rsi_period) < rsi_overbought.
    4. Sem posição aberta no momento.

RISCO E ALVO (determinísticos):
    - stop_loss_price = entry_price - stop_atr_multiplier × ATR
    - Fallback se ATR indisponível: entry_price × (1 - stop_fallback_pct).
    - take_profit_price = entry_price + risk_reward_ratio × (entry - stop)
    - Garantia: 0 < stop_loss_price < entry_price < take_profit_price.

PROVIDER-AGNOSTIC:
    A estratégia consome apenas o dicionário de FeatureEngine. Não depende
    de Bybit/Binance/Tealstreet/CLEO/Polymarket. Não chama exchanges.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from crypto_trading_bot.logging_system.logger import get_logger
from crypto_trading_bot.risk.risk_engine import TradingSignal
from crypto_trading_bot.strategies.base_strategy import BaseStrategy, StrategyState
from crypto_trading_bot.strategies.signal_model import StrategySignal

_logger = get_logger(__name__)


# Defaults — todos sobrescrevíveis via construtor; nenhuma magia escondida.
_DEFAULT_EMA_FAST_PERIOD: int = 20
_DEFAULT_EMA_SLOW_PERIOD: int = 50
_DEFAULT_RSI_PERIOD: int = 14
_DEFAULT_RSI_OVERBOUGHT: float = 70.0
_DEFAULT_STOP_ATR_MULTIPLIER: float = 1.5
_DEFAULT_STOP_FALLBACK_PCT: float = 0.015
_DEFAULT_RISK_REWARD_RATIO: float = 2.0
_DEFAULT_POSITION_SIZE_USD: float = 200.0
_MIN_CANDLES: int = 60   # >= ema_slow_period + margem para warm-up


class TrendPullbackStrategy(BaseStrategy):
    """
    Estratégia determinística baseada em tendência primária + pullback.

    Parâmetros (todos explícitos):
        ema_fast_period:        Período da EMA rápida (default 20).
        ema_slow_period:        Período da EMA lenta (default 50).
        rsi_period:             Período do RSI (default 14).
        rsi_overbought:         Limiar superior de RSI (default 70.0).
        stop_atr_multiplier:    Multiplicador do ATR para stop (default 1.5).
        stop_fallback_pct:      Fallback de stop quando ATR indisponível (default 1.5%).
        risk_reward_ratio:      Razão TP/risco (default 2.0).
        position_size_usd:      Notional em USD por sinal (default 200.0).

    Não há SELL nesta fase; SELL é fora de escopo da FASE 10.
    """

    def __init__(
        self,
        ema_fast_period: int = _DEFAULT_EMA_FAST_PERIOD,
        ema_slow_period: int = _DEFAULT_EMA_SLOW_PERIOD,
        rsi_period: int = _DEFAULT_RSI_PERIOD,
        rsi_overbought: float = _DEFAULT_RSI_OVERBOUGHT,
        stop_atr_multiplier: float = _DEFAULT_STOP_ATR_MULTIPLIER,
        stop_fallback_pct: float = _DEFAULT_STOP_FALLBACK_PCT,
        risk_reward_ratio: float = _DEFAULT_RISK_REWARD_RATIO,
        position_size_usd: float = _DEFAULT_POSITION_SIZE_USD,
    ) -> None:
        if ema_fast_period <= 0 or ema_slow_period <= 0:
            raise ValueError(
                f"Períodos de EMA devem ser positivos: "
                f"fast={ema_fast_period}, slow={ema_slow_period}"
            )
        if ema_fast_period >= ema_slow_period:
            raise ValueError(
                f"ema_fast_period ({ema_fast_period}) deve ser menor que "
                f"ema_slow_period ({ema_slow_period})"
            )
        if rsi_period <= 0:
            raise ValueError(f"rsi_period deve ser positivo: {rsi_period}")
        if not (0 < rsi_overbought <= 100):
            raise ValueError(
                f"rsi_overbought deve estar em (0, 100]: {rsi_overbought}"
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

        self._ema_fast_period = ema_fast_period
        self._ema_slow_period = ema_slow_period
        self._rsi_period = rsi_period
        self._rsi_overbought = rsi_overbought
        self._stop_atr_multiplier = stop_atr_multiplier
        self._stop_fallback_pct = stop_fallback_pct
        self._risk_reward_ratio = risk_reward_ratio
        self._position_size_usd = position_size_usd
        self._has_open_position: bool = False

        super().__init__()

        _logger.info(
            f"[{self.name}] Parâmetros | "
            f"ema={ema_fast_period}/{ema_slow_period} | "
            f"rsi={rsi_period}<{rsi_overbought} | "
            f"stop={stop_atr_multiplier}×ATR (fallback={stop_fallback_pct:.1%}) | "
            f"R:R=1:{risk_reward_ratio} | size_usd={position_size_usd}"
        )

    # -----------------------------------------------------------------------
    # Interface BaseStrategy
    # -----------------------------------------------------------------------

    @property
    def name(self) -> str:
        return (
            f"trend_pullback"
            f"_e{self._ema_fast_period}/{self._ema_slow_period}"
            f"_r{self._rsi_period}"
        )

    def generate_signal(
        self, market_data: Dict[str, Any]
    ) -> Optional[TradingSignal]:
        """Compatibilidade com BaseStrategy. BotEngine usa evaluate()."""
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

        # Estado da estratégia
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

        # Extração de features
        last_close = float(features.get("last_close", 0.0))
        last_rsi = float(features.get("last_rsi", float("nan")))
        last_atr = float(features.get("last_atr", float("nan")))
        ema_fast = self._get_last_from_series(
            features, f"ema_{self._ema_fast_period}"
        )
        ema_slow = self._get_last_from_series(
            features, f"ema_{self._ema_slow_period}"
        )

        if last_close <= 0:
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=self.name,
                reason=f"Preço inválido: last_close={last_close}",
            )
        if math.isnan(ema_fast) or math.isnan(ema_slow):
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=self.name,
                reason=(
                    f"EMA indisponível: "
                    f"fast({self._ema_fast_period})="
                    f"{'NaN' if math.isnan(ema_fast) else f'{ema_fast:.2f}'}, "
                    f"slow({self._ema_slow_period})="
                    f"{'NaN' if math.isnan(ema_slow) else f'{ema_slow:.2f}'}"
                ),
            )

        # Regras determinísticas
        uptrend = ema_fast > ema_slow
        pullback_zone = (last_close <= ema_fast) and (last_close > ema_slow)
        rsi_ok = math.isnan(last_rsi) or (last_rsi < self._rsi_overbought)
        no_position = not self._has_open_position

        _logger.debug(
            f"[{self.name}] {symbol} | close={last_close:.2f} | "
            f"ema_fast={ema_fast:.2f} | ema_slow={ema_slow:.2f} | "
            f"uptrend={uptrend} | pullback_zone={pullback_zone} | "
            f"rsi={'NaN' if math.isnan(last_rsi) else f'{last_rsi:.1f}'} | "
            f"open_pos={self._has_open_position}"
        )

        if not (uptrend and pullback_zone and rsi_ok and no_position):
            reasons = []
            if not uptrend:
                reasons.append(
                    f"EMA{self._ema_fast_period}({ema_fast:.2f})"
                    f" ≤ EMA{self._ema_slow_period}({ema_slow:.2f})"
                )
            if not pullback_zone:
                reasons.append(
                    f"sem pullback: close={last_close:.2f} fora "
                    f"de ({ema_slow:.2f}, {ema_fast:.2f}]"
                )
            if not rsi_ok:
                reasons.append(f"RSI={last_rsi:.1f} ≥ {self._rsi_overbought}")
            if not no_position:
                reasons.append("posição já aberta")
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=self.name,
                reason="; ".join(reasons),
            )

        # Stop loss determinístico (ATR ou fallback %)
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

        # Take profit = entry + R:R × risco
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
            f"ema_fast={ema_fast:.2f} | ema_slow={ema_slow:.2f} | "
            f"rsi={'NaN' if math.isnan(last_rsi) else f'{last_rsi:.1f}'}"
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
                f"ema_{self._ema_fast_period}": round(ema_fast, 2),
                f"ema_{self._ema_slow_period}": round(ema_slow, 2),
                "rsi": round(last_rsi, 2) if not math.isnan(last_rsi) else None,
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
            f"TrendPullbackStrategy("
            f"ema={self._ema_fast_period}/{self._ema_slow_period} | "
            f"rsi<{self._rsi_overbought} | "
            f"stop={self._stop_atr_multiplier}×ATR | "
            f"R:R=1:{self._risk_reward_ratio} | "
            f"size={self._position_size_usd}USD | "
            f"state={self._state.value})"
        )


# ---------------------------------------------------------------------------
# Factory + StrategySpec — registrável via StrategyRegistry
# ---------------------------------------------------------------------------

def _trend_pullback_factory(config: Dict[str, Any]) -> "TrendPullbackStrategy":
    """
    Factory aceitando dicionário de config.

    Os argumentos passados são FORNECIDOS pela StrategySpec.default_config
    (com merge de override em runtime). Nenhum hardcode de capital/sizing.
    """
    strategy = TrendPullbackStrategy(
        ema_fast_period=int(config.get(
            "ema_fast_period", _DEFAULT_EMA_FAST_PERIOD
        )),
        ema_slow_period=int(config.get(
            "ema_slow_period", _DEFAULT_EMA_SLOW_PERIOD
        )),
        rsi_period=int(config.get("rsi_period", _DEFAULT_RSI_PERIOD)),
        rsi_overbought=float(config.get(
            "rsi_overbought", _DEFAULT_RSI_OVERBOUGHT
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


def build_trend_pullback_spec():
    """
    Constrói uma StrategySpec para o framework de pesquisa.

    Import local de StrategySpec evita ciclo de import (research importa
    coisas de strategies em tempo de execução em outros pontos).
    """
    from crypto_trading_bot.research.strategy_research import StrategySpec

    return StrategySpec(
        name="trend_pullback_default",
        factory=_trend_pullback_factory,
        description=(
            "Tendência (EMA fast > EMA slow) + pullback (close em zona EMA) "
            "+ filtro RSI. BUY-only. Stop ATR e TP por razão R:R."
        ),
        default_config={
            "ema_fast_period": _DEFAULT_EMA_FAST_PERIOD,
            "ema_slow_period": _DEFAULT_EMA_SLOW_PERIOD,
            "rsi_period": _DEFAULT_RSI_PERIOD,
            "rsi_overbought": _DEFAULT_RSI_OVERBOUGHT,
            "stop_atr_multiplier": _DEFAULT_STOP_ATR_MULTIPLIER,
            "stop_fallback_pct": _DEFAULT_STOP_FALLBACK_PCT,
            "risk_reward_ratio": _DEFAULT_RISK_REWARD_RATIO,
            "position_size_usd": _DEFAULT_POSITION_SIZE_USD,
        },
        tags=("trend-following", "deterministic", "research"),
    )
