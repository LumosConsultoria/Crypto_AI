"""
VolatilityContractionExpansionStrategy — PROTOTIPO RESEARCH-ONLY (FASE 38)
==========================================================================
⚠️  RESEARCH / PROTOTIPO. NAO eh estrategia definitiva. NAO entra no
    registry operacional default. NAO pode ser usada por demo/session
    runner. Pesquisa offline apenas. NAO promete performance.
⚠️  ZERO rede / API / IA / ordem. Stop loss obrigatorio. RiskEngine
    soberano (piso 0.005 inalterado).

HIPOTESE (regime breakout pos baixa volatilidade):
    Apos um periodo de CONTRACAO de volatilidade (Bollinger bandwidth
    baixo), uma EXPANSAO acompanhada de rompimento de preco para cima
    tende a iniciar um movimento direcional. Compra no rompimento.

ANTI-LOOK-AHEAD (critico):
    - `contraction` e a referencia (media de bandwidth e maxima de high)
      vem APENAS de candles ANTERIORES (janela [i-K, i-1]).
    - O rompimento/expansao e confirmado no candle ATUAL (i).
    - NUNCA usa candles futuros (o FeatureEngine entrega series ate i).

LOGICA DE ENTRADA (BUY-only neste prototipo):
    1. expansion: bb_bandwidth[i] > expansion_factor x media(bandwidth
       em [i-K, i-1]).
    2. breakout: last_close > max(high em [i-K, i-1]).
    3. Sem posicao aberta.

RISCO E ALVO (deterministicos):
    - stop = entry - stop_atr_multiplier x ATR (fallback %).
    - tp = entry + risk_reward_ratio x risco.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from crypto_trading_bot.logging_system.logger import get_logger
from crypto_trading_bot.risk.risk_engine import TradingSignal
from crypto_trading_bot.strategies.base_strategy import (
    BaseStrategy,
    StrategyState,
)
from crypto_trading_bot.strategies.signal_model import StrategySignal

_logger = get_logger(__name__)

_DEFAULT_LOOKBACK: int = 20
_DEFAULT_EXPANSION_FACTOR: float = 1.3
_DEFAULT_STOP_ATR_MULTIPLIER: float = 1.5
_DEFAULT_STOP_FALLBACK_PCT: float = 0.015
_DEFAULT_RISK_REWARD_RATIO: float = 2.0
_DEFAULT_POSITION_SIZE_USD: float = 200.0
_MIN_CANDLES: int = 60


class VolatilityContractionExpansionStrategy(BaseStrategy):
    """Prototipo research-only de contracao/expansao de volatilidade."""

    def __init__(
        self,
        lookback: int = _DEFAULT_LOOKBACK,
        expansion_factor: float = _DEFAULT_EXPANSION_FACTOR,
        stop_atr_multiplier: float = _DEFAULT_STOP_ATR_MULTIPLIER,
        stop_fallback_pct: float = _DEFAULT_STOP_FALLBACK_PCT,
        risk_reward_ratio: float = _DEFAULT_RISK_REWARD_RATIO,
        position_size_usd: float = _DEFAULT_POSITION_SIZE_USD,
    ) -> None:
        if lookback < 5:
            raise ValueError(f"lookback >= 5: {lookback}")
        if expansion_factor <= 1.0:
            raise ValueError(
                f"expansion_factor > 1.0: {expansion_factor}")
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

        self._lookback = lookback
        self._expansion_factor = expansion_factor
        self._stop_atr_multiplier = stop_atr_multiplier
        self._stop_fallback_pct = stop_fallback_pct
        self._risk_reward_ratio = risk_reward_ratio
        self._position_size_usd = position_size_usd
        self._has_open_position: bool = False
        super().__init__()

    @property
    def name(self) -> str:
        return f"vol_contraction_expansion_research_k{self._lookback}"

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
        last_atr = float(features.get("last_atr", float("nan")))
        # FASE 44: materializa SO a cauda necessaria (lookback+1) — O(lookback)
        # por candle (antes era O(i): lista da historia inteira => O(n^2)).
        bw = _series(features, "bb_bandwidth", tail=self._lookback + 1)
        highs = _series(features, "highs", tail=self._lookback + 1)
        if last_close <= 0 or len(bw) <= self._lookback or \
                len(highs) <= self._lookback:
            return StrategySignal.hold(
                symbol=symbol, strategy_name=self.name,
                reason="series insuficientes p/ lookback")

        # ANTI-LOOK-AHEAD: referencias APENAS de candles anteriores.
        prior_bw = [x for x in bw[-(self._lookback + 1):-1]
                    if not math.isnan(x)]
        prior_highs = [x for x in highs[-(self._lookback + 1):-1]
                       if not math.isnan(x)]
        cur_bw = bw[-1]
        if not prior_bw or not prior_highs or math.isnan(cur_bw):
            return StrategySignal.hold(
                symbol=symbol, strategy_name=self.name,
                reason="bandwidth/high indisponivel")

        mean_prior_bw = sum(prior_bw) / len(prior_bw)
        prior_high = max(prior_highs)

        expansion = cur_bw > self._expansion_factor * mean_prior_bw
        breakout = last_close > prior_high
        no_position = not self._has_open_position

        if not (expansion and breakout and no_position):
            reasons = []
            if not expansion:
                reasons.append(
                    f"sem expansao: bw {cur_bw:.4f} <= "
                    f"{self._expansion_factor}x{mean_prior_bw:.4f}")
            if not breakout:
                reasons.append(
                    f"sem breakout: close {last_close:.2f} <= "
                    f"prior_high {prior_high:.2f}")
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
                "family": "volatility_contraction_expansion",
                "prototype": True,
                "cur_bandwidth": round(cur_bw, 6),
                "mean_prior_bandwidth": round(mean_prior_bw, 6),
                "prior_high": round(prior_high, 2),
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


def _series(features: Dict[str, Any], key: str,
            tail: Optional[int] = None) -> List[float]:
    """Lista de floats da serie `key`. Com `tail`, materializa SO os
    ultimos `tail` elementos (O(tail), nao O(n)) — evita O(n^2) no backtest.
    Suporta pd.Series (.iloc), _FastSeries (.iloc->ndarray), list e ndarray."""
    s = features.get(key)
    if s is None:
        return []
    try:
        if tail is not None:
            iloc = getattr(s, "iloc", None)
            seg = iloc[-tail:] if iloc is not None else s[-tail:]
        else:
            seg = s
        return [float(x) for x in seg]
    except (TypeError, ValueError):
        return []


def _vce_factory(
    config: Dict[str, Any],
) -> VolatilityContractionExpansionStrategy:
    s = VolatilityContractionExpansionStrategy(
        lookback=int(config.get("lookback", _DEFAULT_LOOKBACK)),
        expansion_factor=float(config.get(
            "expansion_factor", _DEFAULT_EXPANSION_FACTOR)),
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


def build_volatility_contraction_expansion_spec():
    """StrategySpec do prototipo. tags research/prototype; fora do
    registry operacional default."""
    from crypto_trading_bot.research.strategy_research import StrategySpec
    return StrategySpec(
        name="volatility_contraction_expansion_research",
        factory=_vce_factory,
        description=(
            "PROTOTIPO RESEARCH: contracao -> expansao de volatilidade "
            "com rompimento (BUY). Anti-look-ahead. Nao definitiva; fora "
            "do registry operacional."),
        default_config={
            "lookback": _DEFAULT_LOOKBACK,
            "expansion_factor": _DEFAULT_EXPANSION_FACTOR,
            "stop_atr_multiplier": _DEFAULT_STOP_ATR_MULTIPLIER,
            "stop_fallback_pct": _DEFAULT_STOP_FALLBACK_PCT,
            "risk_reward_ratio": _DEFAULT_RISK_REWARD_RATIO,
            "position_size_usd": _DEFAULT_POSITION_SIZE_USD,
        },
        tags=("volatility", "breakout", "research", "prototype",
              "deterministic"),
    )
