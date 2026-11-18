"""
Market Regime Discovery (FASE 38)
=================================
Classifica regimes de mercado no dataset real, de forma DETERMINISTICA e
ANTI-LOOK-AHEAD: o regime do candle i usa SOMENTE candles <= i.

Modelo de rotulo: primary_regime + secondary_flags.
    primary_regime in:
        trend_up | trend_down | range | breakout | chop_noise | unknown
    secondary_flags subset of:
        high_volatility | low_volatility (contraction)

Precedencia determinística do primary (documentada):
    1. breakout   (expansao de bandwidth pos contracao + rompimento)
    2. trend_up / trend_down (EMA alinhada + slope + baixo ruido)
    3. chop_noise (ruido alto, retorno liquido ~0)
    4. range      (default quando nada acima dispara)

Thresholds de volatilidade por PERCENTIL do proprio dataset (calculados
1x sobre todo o ATR%/bandwidth disponivel ate cada ponto NAO — ver nota),
para evitar hardcode arbitrario. ⚠️  Os percentis de referencia sao
estimados a partir de uma JANELA EXPANSIVA causal (so candles passados),
preservando anti-look-ahead.

Reusa FeatureEngine (bb_bandwidth/atr_14/ema/closes/highs/lows) e o
noise_ratio do detect_market_regime.

⚠️  ZERO rede / ordem / API / secret.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Rotulos canonicos.
PRIMARY_REGIMES: Tuple[str, ...] = (
    "trend_up", "trend_down", "range", "breakout", "chop_noise", "unknown",
)
SECONDARY_FLAGS: Tuple[str, ...] = ("high_volatility", "low_volatility")

# Defaults (documentados; nao ajustados a resultado).
_DEFAULT_LOOKBACK = 96            # 1 dia em 15m
_DEFAULT_HIGH_VOL_PCTILE = 0.80   # ATR% acima do p80 (causal) => high vol
_DEFAULT_LOW_VOL_PCTILE = 0.20    # abaixo do p20 => contraction
_DEFAULT_TREND_RETURN_PCT = 1.0   # retorno liquido na janela p/ trend
_DEFAULT_NOISE_CHOP = 0.62        # noise_ratio acima => chop
_DEFAULT_EXPANSION_FACTOR = 1.3   # breakout: bandwidth atual vs media ant.


@dataclass(frozen=True)
class RegimeLabel:
    """Rotulo de UM candle (anti-look-ahead)."""
    index: int
    primary_regime: str
    secondary_flags: Tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "primary_regime": self.primary_regime,
            "secondary_flags": list(self.secondary_flags),
        }


@dataclass(frozen=True)
class RegimeSegment:
    """Trecho contiguo do mesmo primary_regime (para cross-check)."""
    primary_regime: str
    start_index: int
    end_index: int            # inclusivo
    length: int

    def to_dict(self) -> dict:
        return {
            "primary_regime": self.primary_regime,
            "start_index": self.start_index,
            "end_index": self.end_index,
            "length": self.length,
        }


@dataclass(frozen=True)
class RegimeClassification:
    labels: Tuple[RegimeLabel, ...]
    segments: Tuple[RegimeSegment, ...]
    coverage: Dict[str, float]          # primary_regime -> fracao (0..1)
    coverage_counts: Dict[str, int]
    lookback: int
    n_labeled: int

    def primary_at(self, index: int) -> Optional[str]:
        for lab in self.labels:
            if lab.index == index:
                return lab.primary_regime
        return None

    def to_dict(self) -> dict:
        return {
            "lookback": self.lookback,
            "n_labeled": self.n_labeled,
            "coverage": {k: round(v, 6) for k, v in self.coverage.items()},
            "coverage_counts": dict(self.coverage_counts),
            "segments_count": len(self.segments),
            # labels/segments podem ser grandes: resumidos por padrao.
        }


def _atr_pct_and_bandwidth(candles: Sequence) -> Tuple[List[float],
                                                       List[float],
                                                       List[float]]:
    """Series causais via FeatureEngine: (atr_pct, bandwidth, closes).

    Calcula UMA vez sobre o dataset (cada indicador no candle i so usa
    candles <= i, garantido pelo proprio FeatureEngine). Retorna listas
    alinhadas ao indice dos candles.
    """
    from crypto_trading_bot.data.feature_engine import FeatureEngine
    fe = FeatureEngine()
    feats = fe.compute(list(candles))
    closes = [float(getattr(c, "close", 0.0)) for c in candles]
    atr = feats.get(f"atr_{fe._atr_period}")
    bw = feats.get("bb_bandwidth")
    n = len(candles)
    atr_pct: List[float] = []
    bandwidth: List[float] = []
    for i in range(n):
        a = float("nan")
        try:
            av = float(atr.iloc[i]) if atr is not None else float("nan")
            if closes[i] > 0 and not math.isnan(av):
                a = av / closes[i]
        except (IndexError, TypeError, ValueError):
            a = float("nan")
        atr_pct.append(a)
        b = float("nan")
        try:
            bv = float(bw.iloc[i]) if bw is not None else float("nan")
            b = bv if not math.isnan(bv) else float("nan")
        except (IndexError, TypeError, ValueError):
            b = float("nan")
        bandwidth.append(b)
    return atr_pct, bandwidth, closes


def _pctile(values: List[float], q: float) -> Optional[float]:
    vals = sorted(v for v in values if not math.isnan(v))
    if not vals:
        return None
    idx = min(len(vals) - 1, max(0, int(round(q * (len(vals) - 1)))))
    return vals[idx]


def classify_regimes(
    candles: Sequence,
    *,
    lookback: int = _DEFAULT_LOOKBACK,
    high_vol_pctile: float = _DEFAULT_HIGH_VOL_PCTILE,
    low_vol_pctile: float = _DEFAULT_LOW_VOL_PCTILE,
    trend_return_pct: float = _DEFAULT_TREND_RETURN_PCT,
    noise_chop: float = _DEFAULT_NOISE_CHOP,
    expansion_factor: float = _DEFAULT_EXPANSION_FACTOR,
    min_segment_length: int = 30,
) -> RegimeClassification:
    """Classifica cada candle (a partir de `lookback`) sem look-ahead.

    Para o candle i: usa a janela [i-lookback+1, i]; volatilidade alta/
    baixa via percentil CAUSAL (sobre atr% de candles <= i); breakout via
    bandwidth atual vs media da janela ANTERIOR + rompimento do high
    anterior. Indices < lookback ficam sem rotulo (warm-up).
    """
    n = len(candles)
    atr_pct, bandwidth, closes = _atr_pct_and_bandwidth(candles)
    highs = [float(getattr(c, "high", 0.0)) for c in candles]
    ema_fast, ema_slow = _emas(candles)

    labels: List[RegimeLabel] = []
    for i in range(n):
        if i < lookback:
            continue
        win_lo = i - lookback + 1
        # Volatilidade: percentil CAUSAL (candles 0..i).
        hi_thr = _pctile(atr_pct[:i + 1], high_vol_pctile)
        lo_thr = _pctile(atr_pct[:i + 1], low_vol_pctile)
        cur_atr = atr_pct[i]
        flags: List[str] = []
        if hi_thr is not None and not math.isnan(cur_atr) \
                and cur_atr >= hi_thr:
            flags.append("high_volatility")
        if lo_thr is not None and not math.isnan(cur_atr) \
                and cur_atr <= lo_thr:
            flags.append("low_volatility")

        # Retorno liquido e ruido na janela [win_lo, i].
        c0 = closes[win_lo]
        ci = closes[i]
        ret_pct = (ci / c0 - 1.0) * 100.0 if c0 > 0 else 0.0
        noise = _noise_ratio(closes[win_lo:i + 1])

        # Breakout: expansao de bandwidth vs janela ANTERIOR + rompimento.
        prior_bw = [x for x in bandwidth[win_lo:i] if not math.isnan(x)]
        prior_high = max(highs[win_lo:i]) if i > win_lo else float("nan")
        cur_bw = bandwidth[i]
        breakout = (
            bool(prior_bw) and not math.isnan(cur_bw)
            and cur_bw > expansion_factor * (sum(prior_bw) / len(prior_bw))
            and not math.isnan(prior_high) and ci > prior_high
        )

        ef, es = ema_fast[i], ema_slow[i]
        trend_up = (not math.isnan(ef) and not math.isnan(es)
                    and ef > es and ret_pct >= trend_return_pct
                    and noise < noise_chop)
        trend_down = (not math.isnan(ef) and not math.isnan(es)
                      and ef < es and ret_pct <= -trend_return_pct
                      and noise < noise_chop)

        # Precedencia determinística.
        if breakout:
            primary = "breakout"
        elif trend_up:
            primary = "trend_up"
        elif trend_down:
            primary = "trend_down"
        elif noise >= noise_chop:
            primary = "chop_noise"
        else:
            primary = "range"

        labels.append(RegimeLabel(
            index=i, primary_regime=primary,
            secondary_flags=tuple(flags)))

    segments = _build_segments(labels, min_segment_length)
    counts: Dict[str, int] = {}
    for lab in labels:
        counts[lab.primary_regime] = counts.get(lab.primary_regime, 0) + 1
    total = len(labels)
    coverage = {k: (v / total if total else 0.0) for k, v in counts.items()}
    return RegimeClassification(
        labels=tuple(labels), segments=tuple(segments),
        coverage=coverage, coverage_counts=counts,
        lookback=lookback, n_labeled=total)


def _emas(candles: Sequence) -> Tuple[List[float], List[float]]:
    """EMA(20)/EMA(50) causais via FeatureEngine."""
    from crypto_trading_bot.data.feature_engine import FeatureEngine
    fe = FeatureEngine()
    feats = fe.compute(list(candles))
    n = len(candles)

    def _col(key):
        s = feats.get(key)
        out = []
        for i in range(n):
            try:
                v = float(s.iloc[i]) if s is not None else float("nan")
            except (IndexError, TypeError, ValueError):
                v = float("nan")
            out.append(v)
        return out
    # FeatureEngine expoe ema_9/ema_21 por default; usamos as disponiveis
    # mais separadas para slope/alinhamento.
    fast = _col("ema_9")
    slow = _col("ema_21")
    return fast, slow


def _noise_ratio(closes: Sequence[float]) -> float:
    n = len(closes)
    if n < 3:
        return 0.0
    flips = sum(
        1 for i in range(2, n)
        if (closes[i] - closes[i - 1]) * (closes[i - 1] - closes[i - 2]) < 0
    )
    return flips / max(1, n - 2)


def _build_segments(
    labels: Sequence[RegimeLabel], min_length: int,
) -> List[RegimeSegment]:
    segments: List[RegimeSegment] = []
    if not labels:
        return segments
    start = labels[0].index
    cur = labels[0].primary_regime
    prev_idx = labels[0].index
    for lab in labels[1:]:
        if lab.primary_regime == cur and lab.index == prev_idx + 1:
            prev_idx = lab.index
            continue
        segments.append(RegimeSegment(
            primary_regime=cur, start_index=start, end_index=prev_idx,
            length=prev_idx - start + 1))
        start = lab.index
        cur = lab.primary_regime
        prev_idx = lab.index
    segments.append(RegimeSegment(
        primary_regime=cur, start_index=start, end_index=prev_idx,
        length=prev_idx - start + 1))
    return segments


__all__ = [
    "PRIMARY_REGIMES",
    "SECONDARY_FLAGS",
    "RegimeClassification",
    "RegimeLabel",
    "RegimeSegment",
    "classify_regimes",
]
