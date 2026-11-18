"""
HTF Regime Filter (FASE 44) — confirmacao de regime em timeframe superior.
==========================================================================
Aplica o regime de um timeframe SUPERIOR (15m) como gate causal sobre os
sinais de um timeframe INFERIOR (5m). SOMENTE no 5m (o controle 15m nunca
recebe HTF).

Causalidade (anti-lookahead) por CLOSE_TIME:
  - o candle armazena `timestamp` = OPEN time da barra (confirmado no
    dataset canonico). A DECISAO no candle 5m i ocorre no FECHAMENTO da
    barra: decision_time = open_time(5m i) + intervalo_5m.
  - usa-se o regime do ULTIMO bar 15m cujo CLOSE_TIME
    (= open_time(15m j) + intervalo_15m) seja <= decision_time(5m i).
  - um bar 15m que fecha exatamente no fim do 5m E elegivel; o que fecha
    1 unidade depois NAO e (anti off-by-one). Nunca usa barra futura.

NAO altera RiskEngine/ModeGuard/piso. NAO envia ordem. Determinístico.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, Iterable, Optional, Sequence

# Conjuntos de regime permitidos por tipo de hipotese (primary_regime do
# market_regime: trend_up|trend_down|range|breakout|chop_noise|unknown).
TREND_REGIMES = ("trend_up", "trend_down", "breakout")
RANGE_REGIMES = ("range",)


def _ts_key(ts: Any) -> int:
    """Chave estavel p/ timestamp (datetime ou pd.Timestamp) em ns."""
    import pandas as pd
    return int(pd.Timestamp(ts).value)


def select_htf_index_by_close(
    candles_low: Sequence, candles_high: Sequence, *,
    low_interval_minutes: int = 5, high_interval_minutes: int = 15,
) -> list:
    """PURO/CAUSAL: p/ cada candle do TF inferior, devolve o INDICE do
    ultimo candle do TF superior cujo CLOSE_TIME (open+intervalo) <=
    decision_time (open_low+intervalo). -1 se nenhum bar HTF fechou ainda.
    Determinístico; testavel sem classificar regime (anti off-by-one)."""
    hi_delta = timedelta(minutes=high_interval_minutes)
    lo_delta = timedelta(minutes=low_interval_minutes)
    hi_close = [c.timestamp + hi_delta for c in candles_high]
    n_hi = len(hi_close)
    out = []
    j = 0
    for c in candles_low:
        decision_time = c.timestamp + lo_delta
        while j + 1 < n_hi and hi_close[j + 1] <= decision_time:
            j += 1
        out.append(j if (n_hi and hi_close[j] <= decision_time) else -1)
    return out


def regime_ts_map(candles_high: Sequence, classification) -> Dict[int, str]:
    """{ts_key(open_high) -> primary_regime} a partir de uma classificacao
    JA computada (reuso; evita re-classificar O(n^2))."""
    out: Dict[int, str] = {}
    for lab in classification.labels:
        out[_ts_key(candles_high[lab.index].timestamp)] = lab.primary_regime
    return out


def align_from_classification(
    candles_low: Sequence, candles_high: Sequence, classification, *,
    low_interval_minutes: int = 5, high_interval_minutes: int = 15,
) -> Dict[int, Optional[str]]:
    """Como align_htf_regime, porem REUSA uma RegimeClassification ja
    computada do TF superior (nao re-classifica)."""
    reg_by_idx = {lab.index: lab.primary_regime
                  for lab in classification.labels}
    idxs = select_htf_index_by_close(
        candles_low, candles_high,
        low_interval_minutes=low_interval_minutes,
        high_interval_minutes=high_interval_minutes)
    out: Dict[int, Optional[str]] = {}
    for c, hj in zip(candles_low, idxs):
        out[_ts_key(c.timestamp)] = reg_by_idx.get(hj) if hj >= 0 else None
    return out


def align_htf_regime(
    candles_low: Sequence,
    candles_high: Sequence,
    *,
    lookback: int = 96,
    low_interval_minutes: int = 5,
    high_interval_minutes: int = 15,
) -> Dict[int, Optional[str]]:
    """Mapeia cada candle do TF inferior -> primary_regime do TF superior,
    de forma CAUSAL por close_time. Retorna {ts_key(open_low) -> regime|None}.
    None quando ainda nao ha barra HTF FECHADA com regime conhecido (inclui
    warmup do classificador). Classifica internamente (conveniencia/teste);
    no orquestrador use align_from_classification p/ reusar a classificacao."""
    from crypto_trading_bot.research.market_regime import classify_regimes

    if not candles_low or not candles_high:
        return {}
    rc = classify_regimes(candles_high, lookback=lookback)
    return align_from_classification(
        candles_low, candles_high, rc,
        low_interval_minutes=low_interval_minutes,
        high_interval_minutes=high_interval_minutes)


class HtfRegimeGatedStrategy:
    """Wrapper que SUPRIME entradas (HOLD) quando o regime do TF superior
    nao esta no conjunto permitido. Delega TODO o resto a estrategia base
    (incluindo callbacks de ciclo de vida p/ reentrada). Duck-typed: expoe
    os mesmos metodos que o BacktestEngine consome (name/evaluate/
    on_signal_*/on_trade_closed/reset)."""

    def __init__(self, base_strategy, regime_map: Dict[int, Optional[str]],
                 allowed_regimes: Iterable[str]) -> None:
        self._base = base_strategy
        self._regime_map = dict(regime_map)
        self._allowed = set(allowed_regimes)
        self.blocked_by_htf = 0

    @property
    def name(self) -> str:
        return f"{self._base.name}_htf15m"

    def evaluate(self, features: Dict[str, Any]):
        from crypto_trading_bot.strategies.signal_model import (
            StrategyAction,
            StrategySignal,
        )
        sig = self._base.evaluate(features)
        if sig.action == StrategyAction.HOLD:
            return sig
        tss = features.get("timestamps")
        ts = None
        try:
            if tss is not None and len(tss) > 0:
                ts = tss.iloc[-1]
        except Exception:  # noqa: BLE001
            ts = None
        regime = self._regime_map.get(_ts_key(ts)) if ts is not None else None
        if regime is None or regime not in self._allowed:
            self.blocked_by_htf += 1
            return StrategySignal.hold(
                symbol=sig.symbol, strategy_name=self.name,
                reason=f"htf_regime_block:{regime}")
        return sig

    # --- delegacao de ciclo de vida (preserva estado/reentrada da base) ---
    def generate_signal(self, market_data: Dict[str, Any]):
        return self._base.generate_signal(market_data)

    def on_signal_approved(self, signal) -> None:
        self._base.on_signal_approved(signal)

    def on_signal_rejected(self, signal, reason: str) -> None:
        self._base.on_signal_rejected(signal, reason)

    def on_trade_closed(self, symbol: str, pnl: float) -> None:
        self._base.on_trade_closed(symbol, pnl)

    def reset(self) -> None:
        reset = getattr(self._base, "reset", None)
        if callable(reset):
            reset()


def allowed_regimes_for(hypothesis: str) -> tuple:
    """Conjunto de regime 15m permitido por hipotese (HTF)."""
    h = hypothesis.lower()
    if "trend" in h or "volatility_contraction" in h or "breakout" in h:
        return TREND_REGIMES
    if "range" in h or "mean_reversion" in h:
        return RANGE_REGIMES
    return ()


__all__ = [
    "RANGE_REGIMES",
    "TREND_REGIMES",
    "HtfRegimeGatedStrategy",
    "align_from_classification",
    "align_htf_regime",
    "allowed_regimes_for",
    "regime_ts_map",
    "select_htf_index_by_close",
]
