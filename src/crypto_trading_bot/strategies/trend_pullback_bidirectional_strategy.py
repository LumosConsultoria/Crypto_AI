"""
TrendPullbackBidirectionalStrategy — LONG + SHORT (FASE 29.x)
=============================================================
Estrategia deterministica de tendencia + pullback BIDIRECIONAL.
Gera BUY (long), SELL (short) ou HOLD, com criterios proprios para
cada lado e metadata rica para observabilidade.

⚠️  AVISOS OBRIGATORIOS:
    - Deterministica para PESQUISA OFFLINE (backtest + paper + demo).
    - NAO promete performance. ZERO IA/LLM. ZERO rede.
    - Stop loss obrigatorio. BUY: SL < entry < TP. SELL: TP < entry < SL.
    - Sem hardcode de capital/sizing/leverage; tudo via construtor.
    - NAO remove nem altera TrendPullbackStrategy (long-only) existente.

LOGICA LONG (BUY):
    1. uptrend:        EMA(fast) > EMA(slow).
    2. pullback_zone:  last_close <= EMA(fast) [+ k*ATR opcional] E
                       last_close > EMA(slow).
    3. rsi_ok:         RSI < rsi_long_overbought (ou RSI NaN tolerado).
    4. no_position.

LOGICA SHORT (SELL):
    1. downtrend:      EMA(fast) < EMA(slow).
    2. pullback_zone:  last_close >= EMA(fast) [- k*ATR opcional] E
                       last_close < EMA(slow).
    3. rsi_ok:         RSI > rsi_short_oversold (ou RSI NaN tolerado).
    4. no_position.

PRIORIZACAO:
    uptrend e downtrend sao mutuamente exclusivos (EMA fast>slow XOR
    fast<slow). Logo long_valid e short_valid nunca sao True juntos.
    Defesa em profundidade: se por qualquer motivo ambos derem True,
    retorna HOLD com hold_reason="ambiguous_long_short_conflict"
    (resultado controlado, nunca envia ordem ambigua).

RISCO/ALVO:
    BUY:  stop = entry - mult*ATR (fallback entry*(1-fallback_pct));
          tp   = entry + RR*(entry - stop).
    SELL: stop = entry + mult*ATR (fallback entry*(1+fallback_pct));
          tp   = entry - RR*(stop - entry).

PULLBACK COM TOLERANCIA ATR (research/opcional):
    pullback_atr_tolerance_k > 0 afrouxa a zona de pullback usando ATR.
    Default 0.0 = strict (sem tolerancia). NUNCA usado em demo real
    sem aprovacao explicita; eh parametro de pesquisa.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from crypto_trading_bot.logging_system.logger import get_logger
from crypto_trading_bot.risk.risk_engine import TradingSignal
from crypto_trading_bot.strategies.base_strategy import BaseStrategy, StrategyState
from crypto_trading_bot.strategies.signal_model import (
    StrategyAction, StrategySignal,
)

_logger = get_logger(__name__)


# Defaults LONG
_DEFAULT_EMA_FAST_PERIOD: int = 20
_DEFAULT_EMA_SLOW_PERIOD: int = 50
_DEFAULT_RSI_PERIOD: int = 14
_DEFAULT_RSI_LONG_OVERBOUGHT: float = 70.0
# Defaults SHORT
_DEFAULT_RSI_SHORT_OVERSOLD: float = 30.0
# Risco/alvo
_DEFAULT_STOP_ATR_MULTIPLIER: float = 1.5
_DEFAULT_STOP_FALLBACK_PCT: float = 0.015
_DEFAULT_RISK_REWARD_RATIO: float = 2.0
_DEFAULT_POSITION_SIZE_USD: float = 200.0
_DEFAULT_PULLBACK_ATR_TOLERANCE_K: float = 0.0   # 0 = strict
_MIN_CANDLES: int = 60


class TrendPullbackBidirectionalStrategy(BaseStrategy):
    """Estrategia bidirecional (BUY/SELL/HOLD) de tendencia + pullback.

    enable_long / enable_short permitem restringir a direcao avaliada
    (default ambos True). Mesmo com enable_short=True, a EXECUCAO REAL
    demo de SELL depende de gate proprio (DEMO_30_MIN_ALLOW_SHORT_
    PHASE29_ENABLED) na camada de execucao — esta classe apenas gera o
    sinal.
    """

    def __init__(
        self,
        ema_fast_period: int = _DEFAULT_EMA_FAST_PERIOD,
        ema_slow_period: int = _DEFAULT_EMA_SLOW_PERIOD,
        rsi_period: int = _DEFAULT_RSI_PERIOD,
        rsi_long_overbought: float = _DEFAULT_RSI_LONG_OVERBOUGHT,
        rsi_short_oversold: float = _DEFAULT_RSI_SHORT_OVERSOLD,
        stop_atr_multiplier: float = _DEFAULT_STOP_ATR_MULTIPLIER,
        stop_fallback_pct: float = _DEFAULT_STOP_FALLBACK_PCT,
        risk_reward_ratio: float = _DEFAULT_RISK_REWARD_RATIO,
        position_size_usd: float = _DEFAULT_POSITION_SIZE_USD,
        pullback_atr_tolerance_k: float = _DEFAULT_PULLBACK_ATR_TOLERANCE_K,
        enable_long: bool = True,
        enable_short: bool = True,
        min_stop_loss_pct: Optional[float] = None,
    ) -> None:
        if ema_fast_period <= 0 or ema_slow_period <= 0:
            raise ValueError(
                f"Periodos de EMA devem ser positivos: "
                f"fast={ema_fast_period}, slow={ema_slow_period}"
            )
        if ema_fast_period >= ema_slow_period:
            raise ValueError(
                f"ema_fast_period ({ema_fast_period}) deve ser < "
                f"ema_slow_period ({ema_slow_period})"
            )
        if rsi_period <= 0:
            raise ValueError(f"rsi_period deve ser positivo: {rsi_period}")
        if not (0 < rsi_long_overbought <= 100):
            raise ValueError(
                f"rsi_long_overbought em (0,100]: {rsi_long_overbought}"
            )
        if not (0 <= rsi_short_oversold < 100):
            raise ValueError(
                f"rsi_short_oversold em [0,100): {rsi_short_oversold}"
            )
        if stop_atr_multiplier <= 0:
            raise ValueError(
                f"stop_atr_multiplier deve ser positivo: {stop_atr_multiplier}"
            )
        if not (0 < stop_fallback_pct < 1):
            raise ValueError(
                f"stop_fallback_pct em (0,1): {stop_fallback_pct}"
            )
        if risk_reward_ratio <= 0:
            raise ValueError(
                f"risk_reward_ratio deve ser positivo: {risk_reward_ratio}"
            )
        if position_size_usd <= 0:
            raise ValueError(
                f"position_size_usd deve ser positivo: {position_size_usd}"
            )
        if pullback_atr_tolerance_k < 0:
            raise ValueError(
                f"pullback_atr_tolerance_k deve ser >= 0: "
                f"{pullback_atr_tolerance_k}"
            )
        if not enable_long and not enable_short:
            raise ValueError(
                "ao menos um de enable_long/enable_short deve ser True"
            )
        if min_stop_loss_pct is not None and \
                not (0 < min_stop_loss_pct < 1):
            raise ValueError(
                f"min_stop_loss_pct em (0,1) ou None: {min_stop_loss_pct}"
            )

        # Piso de SL (fracao, ex.: 0.005 = 0.5%). None = comportamento
        # legado (estrategia NAO conhece o piso; RiskEngine decide).
        # Quando definido, alinha a estrategia ao piso de risco:
        # sinal com SL abaixo do piso vira HOLD risk-aware ANTES de
        # chegar ao RiskEngine (nunca baixa o piso; nunca forca ordem).
        self._min_stop_loss_pct = min_stop_loss_pct
        self._ema_fast_period = ema_fast_period
        self._ema_slow_period = ema_slow_period
        self._rsi_period = rsi_period
        self._rsi_long_overbought = rsi_long_overbought
        self._rsi_short_oversold = rsi_short_oversold
        self._stop_atr_multiplier = stop_atr_multiplier
        self._stop_fallback_pct = stop_fallback_pct
        self._risk_reward_ratio = risk_reward_ratio
        self._position_size_usd = position_size_usd
        self._pullback_atr_tolerance_k = pullback_atr_tolerance_k
        self._enable_long = bool(enable_long)
        self._enable_short = bool(enable_short)
        self._has_open_position: bool = False

        super().__init__()

        _logger.info(
            f"[{self.name}] Parametros | "
            f"ema={ema_fast_period}/{ema_slow_period} | "
            f"rsi={rsi_period} long<{rsi_long_overbought} "
            f"short>{rsi_short_oversold} | "
            f"long={self._enable_long} short={self._enable_short} | "
            f"atr_tol_k={pullback_atr_tolerance_k}"
        )

    # -----------------------------------------------------------------------
    # Interface BaseStrategy
    # -----------------------------------------------------------------------

    @property
    def name(self) -> str:
        return (
            f"trend_pullback_bidirectional"
            f"_e{self._ema_fast_period}/{self._ema_slow_period}"
            f"_r{self._rsi_period}"
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

    def on_signal_approved(self, signal: TradingSignal) -> None:
        super().on_signal_approved(signal)
        self._has_open_position = True

    def on_trade_closed(self, symbol: str, pnl: float) -> None:
        super().on_trade_closed(symbol, pnl)
        self._has_open_position = False

    # -----------------------------------------------------------------------
    # evaluate() — bidirecional
    # -----------------------------------------------------------------------

    def evaluate(self, features: Dict[str, Any]) -> StrategySignal:
        symbol: str = str(features.get("symbol") or "UNKNOWN")

        if self._state != StrategyState.RUNNING:
            return self._hold(
                symbol, hold_reason="strategy_inactive",
                failed_long=["strategy_inactive"],
                failed_short=["strategy_inactive"],
                extra={"state": self._state.value},
            )

        if not features.get("has_sufficient_data", False):
            n = int(features.get("n_candles", 0) or 0)
            return self._hold(
                symbol, hold_reason="insufficient_candles",
                failed_long=["insufficient_candles"],
                failed_short=["insufficient_candles"],
                extra={
                    "candles_available": n,
                    "min_candles_required": _MIN_CANDLES,
                    "data_quality_ok": False,
                },
            )

        last_close = float(features.get("last_close", 0.0))
        last_high = float(features.get("last_high", float("nan")))
        last_low = float(features.get("last_low", float("nan")))
        last_volume = float(features.get("last_volume", float("nan")))
        last_rsi = float(features.get("last_rsi", float("nan")))
        last_atr = float(features.get("last_atr", float("nan")))
        ema_fast = self._get_last_from_series(
            features, f"ema_{self._ema_fast_period}"
        )
        ema_slow = self._get_last_from_series(
            features, f"ema_{self._ema_slow_period}"
        )
        candles_available = int(features.get("n_candles", 0) or 0)

        base_meta = self._base_metadata(
            symbol=symbol, last_close=last_close, last_high=last_high,
            last_low=last_low, last_volume=last_volume,
            last_rsi=last_rsi, last_atr=last_atr,
            ema_fast=ema_fast, ema_slow=ema_slow,
            candles_available=candles_available,
        )

        if last_close <= 0:
            return self._hold(
                symbol, hold_reason="data_quality_failed",
                failed_long=["invalid_price"],
                failed_short=["invalid_price"],
                extra={**base_meta, "data_quality_ok": False},
            )
        if math.isnan(ema_fast) or math.isnan(ema_slow):
            return self._hold(
                symbol, hold_reason="ema_unavailable",
                failed_long=["ema_unavailable"],
                failed_short=["ema_unavailable"],
                extra=base_meta,
            )

        no_position = not self._has_open_position

        # --- LONG conditions ---
        atr_tol = (
            self._pullback_atr_tolerance_k * last_atr
            if (self._pullback_atr_tolerance_k > 0
                and not math.isnan(last_atr) and last_atr > 0)
            else 0.0
        )
        uptrend = ema_fast > ema_slow
        pullback_long = (
            (last_close <= ema_fast + atr_tol) and (last_close > ema_slow)
        )
        rsi_ok_long = math.isnan(last_rsi) or (
            last_rsi < self._rsi_long_overbought
        )
        long_valid = (
            self._enable_long and uptrend and pullback_long
            and rsi_ok_long and no_position
        )

        # --- SHORT conditions ---
        downtrend = ema_fast < ema_slow
        pullback_short = (
            (last_close >= ema_fast - atr_tol) and (last_close < ema_slow)
        )
        rsi_ok_short = math.isnan(last_rsi) or (
            last_rsi > self._rsi_short_oversold
        )
        short_valid = (
            self._enable_short and downtrend and pullback_short
            and rsi_ok_short and no_position
        )

        long_conditions = {
            "uptrend": uptrend, "pullback_zone": pullback_long,
            "rsi_ok": rsi_ok_long, "no_position": no_position,
            "enabled": self._enable_long,
        }
        short_conditions = {
            "downtrend": downtrend, "pullback_zone": pullback_short,
            "rsi_ok": rsi_ok_short, "no_position": no_position,
            "enabled": self._enable_short,
        }
        failed_long = self._failed_long(long_conditions)
        failed_short = self._failed_short(short_conditions)

        cond_meta = {
            **base_meta,
            "data_quality_ok": True,
            "uptrend": uptrend, "downtrend": downtrend,
            "pullback_zone_long": pullback_long,
            "pullback_zone_short": pullback_short,
            "rsi_ok_long": rsi_ok_long, "rsi_ok_short": rsi_ok_short,
            "no_position": no_position,
            "long_conditions": long_conditions,
            "short_conditions": short_conditions,
            "failed_conditions_long": failed_long,
            "failed_conditions_short": failed_short,
        }

        # Priorizacao: uptrend XOR downtrend; conflito eh estruturalmente
        # impossivel. Defesa em profundidade:
        if long_valid and short_valid:
            return self._hold(
                symbol, hold_reason="ambiguous_long_short_conflict",
                failed_long=failed_long, failed_short=failed_short,
                extra=cond_meta,
                rejected_direction_reason="both_directions_valid",
            )

        if long_valid:
            return self._build_directional_signal(
                symbol, side="buy", last_close=last_close,
                last_atr=last_atr, cond_meta=cond_meta,
            )
        if short_valid:
            return self._build_directional_signal(
                symbol, side="sell", last_close=last_close,
                last_atr=last_atr, cond_meta=cond_meta,
            )

        return self._hold(
            symbol, hold_reason="no_valid_long_or_short_setup",
            failed_long=failed_long, failed_short=failed_short,
            extra=cond_meta,
        )

    # -----------------------------------------------------------------------
    # Builders internos
    # -----------------------------------------------------------------------

    def _build_directional_signal(
        self, symbol: str, *, side: str, last_close: float,
        last_atr: float, cond_meta: Dict[str, Any],
    ) -> StrategySignal:
        entry = round(last_close, 2)
        if side == "buy":
            stop = self._stop_long(entry, last_atr)
            if stop <= 0 or stop >= entry:
                return self._hold(
                    symbol, hold_reason="stop_loss_invalid",
                    failed_long=["stop_loss_invalid"],
                    failed_short=cond_meta.get(
                        "failed_conditions_short", []
                    ),
                    extra=cond_meta,
                )
            risk = entry - stop
            floor_hold = self._reject_if_sl_below_floor(
                symbol, side="buy", entry=entry, stop=stop,
                cond_meta=cond_meta,
            )
            if floor_hold is not None:
                return floor_hold
            tp = round(entry + self._risk_reward_ratio * risk, 2)
            direction = "long"
            actionable_meta = {
                **cond_meta, "selected_direction": "long",
                "planned_sl_pct": round(abs(entry - stop) / entry
                                        * 100.0, 4),
            }
            _logger.info(
                f"[{self.name}] SINAL BUY | {symbol} | entry={entry} | "
                f"stop={stop} | tp={tp}"
            )
            sig = StrategySignal.buy(
                symbol=symbol, strategy_name=self.name,
                entry_price=entry, stop_loss_price=stop,
                take_profit_price=tp,
                position_size_usd=self._position_size_usd,
                leverage=1.0,
                metadata=self._signal_metadata(
                    direction=direction, side="buy", actionable=True,
                    cond_meta=actionable_meta,
                ),
            )
        else:  # sell
            stop = self._stop_short(entry, last_atr)
            if stop <= 0 or stop <= entry:
                return self._hold(
                    symbol, hold_reason="stop_loss_invalid",
                    failed_long=cond_meta.get(
                        "failed_conditions_long", []
                    ),
                    failed_short=["stop_loss_invalid"],
                    extra=cond_meta,
                )
            risk = stop - entry
            floor_hold = self._reject_if_sl_below_floor(
                symbol, side="sell", entry=entry, stop=stop,
                cond_meta=cond_meta,
            )
            if floor_hold is not None:
                return floor_hold
            tp = round(entry - self._risk_reward_ratio * risk, 2)
            if tp <= 0 or tp >= entry:
                return self._hold(
                    symbol, hold_reason="take_profit_invalid",
                    failed_long=cond_meta.get(
                        "failed_conditions_long", []
                    ),
                    failed_short=["take_profit_invalid"],
                    extra=cond_meta,
                )
            direction = "short"
            actionable_meta = {
                **cond_meta, "selected_direction": "short",
                "planned_sl_pct": round(abs(entry - stop) / entry
                                        * 100.0, 4),
            }
            _logger.info(
                f"[{self.name}] SINAL SELL | {symbol} | entry={entry} | "
                f"stop={stop} | tp={tp}"
            )
            sig = StrategySignal.sell(
                symbol=symbol, strategy_name=self.name,
                entry_price=entry, stop_loss_price=stop,
                take_profit_price=tp,
                position_size_usd=self._position_size_usd,
                leverage=1.0,
                metadata=self._signal_metadata(
                    direction=direction, side="sell", actionable=True,
                    cond_meta=actionable_meta,
                ),
            )
        self._signal_count += 1
        self._last_signal = sig
        return sig

    def _reject_if_sl_below_floor(
        self, symbol: str, *, side: str, entry: float, stop: float,
        cond_meta: Dict[str, Any],
    ) -> Optional[StrategySignal]:
        """HOLD risk-aware se o SL planejado fica abaixo do piso.

        Default (min_stop_loss_pct=None): retorna None (comportamento
        legado; RiskEngine continua soberano). Quando o piso eh
        definido, a estrategia NAO emite sinal executavel doomed —
        registra rejeicao tecnica com diagnostico para o trace/advisor.
        NUNCA baixa o piso; NUNCA forca ordem.
        """
        floor = self._min_stop_loss_pct
        if floor is None or entry <= 0:
            return None
        sl_pct = abs(entry - stop) / entry
        if sl_pct >= floor:
            return None
        planned_pct = round(sl_pct * 100.0, 4)
        min_pct = round(floor * 100.0, 4)
        diag = {
            "planned_sl_pct": planned_pct,
            "min_sl_pct_required": min_pct,
            "sl_gap_to_min_pct": round(min_pct - planned_pct, 4),
            "risk_rejection_category": "stop_loss_below_minimum",
        }
        _logger.info(
            f"[{self.name}] HOLD risk-aware | {symbol} {side} | "
            f"SL planejado {planned_pct}% < piso {min_pct}% "
            "(sinal nao enviado ao executor)"
        )
        failed = ["stop_below_min_risk_floor"]
        return self._hold(
            symbol, hold_reason="stop_below_min_risk_floor",
            failed_long=failed if side == "buy" else cond_meta.get(
                "failed_conditions_long", []),
            failed_short=failed if side == "sell" else cond_meta.get(
                "failed_conditions_short", []),
            extra={**cond_meta, **diag},
        )

    def _stop_long(self, entry: float, atr: float) -> float:
        if not math.isnan(atr) and atr > 0:
            return round(entry - self._stop_atr_multiplier * atr, 2)
        return round(entry * (1.0 - self._stop_fallback_pct), 2)

    def _stop_short(self, entry: float, atr: float) -> float:
        if not math.isnan(atr) and atr > 0:
            return round(entry + self._stop_atr_multiplier * atr, 2)
        return round(entry * (1.0 + self._stop_fallback_pct), 2)

    def _hold(
        self, symbol: str, *, hold_reason: str,
        failed_long: List[str], failed_short: List[str],
        extra: Optional[Dict[str, Any]] = None,
        rejected_direction_reason: Optional[str] = None,
    ) -> StrategySignal:
        meta = self._signal_metadata(
            direction="none", side="hold", actionable=False,
            cond_meta={
                **(extra or {}),
                "failed_conditions_long": failed_long,
                "failed_conditions_short": failed_short,
                "rejected_direction_reason": rejected_direction_reason,
            },
            hold_reason=hold_reason,
        )
        return StrategySignal(
            action=StrategyAction.HOLD,
            symbol=symbol,
            strategy_name=self.name,
            reason=hold_reason,
            metadata=meta,
        )

    # -----------------------------------------------------------------------
    # Metadata / observabilidade
    # -----------------------------------------------------------------------

    def _base_metadata(
        self, *, symbol, last_close, last_high, last_low, last_volume,
        last_rsi, last_atr, ema_fast, ema_slow, candles_available,
    ) -> Dict[str, Any]:
        def _f(v):
            return None if (v is None or (isinstance(v, float)
                            and math.isnan(v))) else round(float(v), 6)
        return {
            "strategy_name": self.name,
            "strategy_id": "trend_pullback_bidirectional_v1",
            "symbol": symbol,
            "ema_fast_period": self._ema_fast_period,
            "ema_slow_period": self._ema_slow_period,
            "ema_fast_value": _f(ema_fast),
            "ema_slow_value": _f(ema_slow),
            "rsi_period": self._rsi_period,
            "rsi_value": _f(last_rsi),
            "rsi_long_overbought": self._rsi_long_overbought,
            "rsi_short_oversold": self._rsi_short_oversold,
            "atr_period": 14,
            "atr_value": _f(last_atr),
            "last_close": _f(last_close),
            "last_high": _f(last_high),
            "last_low": _f(last_low),
            "last_volume": _f(last_volume),
            "min_candles_required": _MIN_CANDLES,
            "candles_available": candles_available,
            "has_open_position": self._has_open_position,
            "pullback_atr_tolerance_k": self._pullback_atr_tolerance_k,
        }

    def _signal_metadata(
        self, *, direction: str, side: str, actionable: bool,
        cond_meta: Dict[str, Any], hold_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        meta = dict(cond_meta)
        meta["signal_side"] = side
        meta["direction"] = direction
        meta["actionable"] = actionable
        if hold_reason is not None:
            meta["hold_reason"] = hold_reason
        return meta

    @staticmethod
    def _failed_long(conds: Dict[str, bool]) -> List[str]:
        failed = []
        if not conds.get("enabled", True):
            failed.append("long_disabled")
        if not conds.get("uptrend"):
            failed.append("no_uptrend")
        if not conds.get("pullback_zone"):
            failed.append("no_pullback_zone")
        if not conds.get("rsi_ok"):
            failed.append("rsi_overbought")
        if not conds.get("no_position"):
            failed.append("position_already_open")
        return failed

    @staticmethod
    def _failed_short(conds: Dict[str, bool]) -> List[str]:
        failed = []
        if not conds.get("enabled", True):
            failed.append("short_disabled")
        if not conds.get("downtrend"):
            failed.append("no_downtrend")
        if not conds.get("pullback_zone"):
            failed.append("no_pullback_zone")
        if not conds.get("rsi_ok"):
            failed.append("rsi_oversold")
        if not conds.get("no_position"):
            failed.append("position_already_open")
        return failed

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
            f"TrendPullbackBidirectionalStrategy("
            f"ema={self._ema_fast_period}/{self._ema_slow_period} | "
            f"long={self._enable_long} short={self._enable_short} | "
            f"state={self._state.value})"
        )


# ---------------------------------------------------------------------------
# Factory + StrategySpec
# ---------------------------------------------------------------------------

def _bidirectional_factory(
    config: Dict[str, Any],
) -> "TrendPullbackBidirectionalStrategy":
    strategy = TrendPullbackBidirectionalStrategy(
        ema_fast_period=int(config.get(
            "ema_fast_period", _DEFAULT_EMA_FAST_PERIOD
        )),
        ema_slow_period=int(config.get(
            "ema_slow_period", _DEFAULT_EMA_SLOW_PERIOD
        )),
        rsi_period=int(config.get("rsi_period", _DEFAULT_RSI_PERIOD)),
        rsi_long_overbought=float(config.get(
            "rsi_long_overbought", _DEFAULT_RSI_LONG_OVERBOUGHT
        )),
        rsi_short_oversold=float(config.get(
            "rsi_short_oversold", _DEFAULT_RSI_SHORT_OVERSOLD
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
        pullback_atr_tolerance_k=float(config.get(
            "pullback_atr_tolerance_k", _DEFAULT_PULLBACK_ATR_TOLERANCE_K
        )),
        enable_long=bool(config.get("enable_long", True)),
        enable_short=bool(config.get("enable_short", True)),
        min_stop_loss_pct=(
            float(config["min_stop_loss_pct"])
            if config.get("min_stop_loss_pct") is not None else None
        ),
    )
    strategy.set_running()
    return strategy


def build_trend_pullback_bidirectional_spec():
    """Constroi StrategySpec da estrategia bidirecional."""
    from crypto_trading_bot.research.strategy_research import StrategySpec

    return StrategySpec(
        name="trend_pullback_bidirectional_default",
        factory=_bidirectional_factory,
        description=(
            "Tendencia + pullback BIDIRECIONAL (BUY long / SELL short). "
            "Criterios e parametros proprios por lado. SL/TP coerentes "
            "com o side. SELL real depende de gate proprio."
        ),
        default_config={
            "ema_fast_period": _DEFAULT_EMA_FAST_PERIOD,
            "ema_slow_period": _DEFAULT_EMA_SLOW_PERIOD,
            "rsi_period": _DEFAULT_RSI_PERIOD,
            "rsi_long_overbought": _DEFAULT_RSI_LONG_OVERBOUGHT,
            "rsi_short_oversold": _DEFAULT_RSI_SHORT_OVERSOLD,
            "stop_atr_multiplier": _DEFAULT_STOP_ATR_MULTIPLIER,
            "stop_fallback_pct": _DEFAULT_STOP_FALLBACK_PCT,
            "risk_reward_ratio": _DEFAULT_RISK_REWARD_RATIO,
            "position_size_usd": _DEFAULT_POSITION_SIZE_USD,
            "pullback_atr_tolerance_k": _DEFAULT_PULLBACK_ATR_TOLERANCE_K,
            "enable_long": True,
            "enable_short": True,
        },
        tags=("trend-following", "bidirectional", "deterministic",
              "research"),
    )


# ---------------------------------------------------------------------------
# Planejador de SL risk-aware (FASE 36 pos-demo 3) - PURO / DIAGNOSTICO
# ---------------------------------------------------------------------------

def plan_risk_aware_stop(
    *,
    side: str,
    entry: float,
    atr: float,
    stop_atr_multiplier: float,
    risk_reward_ratio: float,
    min_stop_loss_pct: float,
    position_size_usd: float,
    max_stop_loss_pct: Optional[float] = None,
    max_risk_per_trade_usd: Optional[float] = None,
) -> Dict[str, Any]:
    """Propoe um SL que RESPEITA o piso de risco, sem baixar o piso.

    Ferramenta de PESQUISA/DIAGNOSTICO (nao e auto-wired na execucao;
    o operador decide). Calcula:
        - distancia base do SL = stop_atr_multiplier * ATR;
        - distancia efetiva = max(base, piso) (clamp ao piso);
        - aplica teto max_stop_loss_pct se informado;
        - SL/TP coerentes por lado (BUY: SL<entry<TP; SELL: TP<entry<SL),
          preservando o risk_reward_ratio;
        - risk_usd = sl_pct * position_size_usd (qty = notional/entry);
        - valida contra max_risk_per_trade_usd (se informado).

    Retorna proposta auditavel. NUNCA envia ordem, NUNCA altera sizing
    de forma escondida: se o piso exigir risco acima do teto, sinaliza
    `within_risk_budget=False` para decisao humana.
    """
    if entry <= 0 or min_stop_loss_pct <= 0 or position_size_usd <= 0:
        raise ValueError("entry/min_stop_loss_pct/position_size_usd > 0")
    side_n = str(side).strip().lower()
    base_dist = (
        stop_atr_multiplier * atr
        if (atr is not None and atr > 0) else 0.0
    )
    floor_dist = entry * min_stop_loss_pct
    eff_dist = max(base_dist, floor_dist)
    clamped = eff_dist > base_dist + 1e-12
    capped = False
    if max_stop_loss_pct is not None:
        cap_dist = entry * max_stop_loss_pct
        if eff_dist > cap_dist:
            eff_dist = cap_dist
            capped = True
    if side_n in ("buy", "long"):
        stop = round(entry - eff_dist, 2)
        tp = round(entry + risk_reward_ratio * eff_dist, 2)
    elif side_n in ("sell", "short"):
        stop = round(entry + eff_dist, 2)
        tp = round(entry - risk_reward_ratio * eff_dist, 2)
    else:
        raise ValueError(f"side invalido: {side!r}")
    sl_pct = eff_dist / entry
    risk_usd = sl_pct * position_size_usd
    within_budget = (
        max_risk_per_trade_usd is None
        or risk_usd <= max_risk_per_trade_usd + 1e-9
    )
    return {
        "side": side_n,
        "entry": round(entry, 2),
        "stop": stop,
        "take_profit": tp,
        "sl_pct": round(sl_pct * 100.0, 4),
        "min_sl_pct_required": round(min_stop_loss_pct * 100.0, 4),
        "base_atr_sl_pct": round(
            (base_dist / entry) * 100.0, 4,
        ) if entry else None,
        "clamped_to_floor": bool(clamped),
        "capped_to_max": bool(capped),
        "risk_reward_ratio": float(risk_reward_ratio),
        "risk_usd": round(risk_usd, 6),
        "max_risk_per_trade_usd": max_risk_per_trade_usd,
        "within_risk_budget": bool(within_budget),
        "tp_valid": (tp > 0 and (
            tp > entry if side_n in ("buy", "long") else tp < entry
        )),
    }


__all__ = [
    "TrendPullbackBidirectionalStrategy",
    "build_trend_pullback_bidirectional_spec",
    "plan_risk_aware_stop",
]
