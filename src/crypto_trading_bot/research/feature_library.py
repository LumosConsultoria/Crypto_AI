"""
Feature Library (FASE 49) — features CAUSAIS candidatas p/ o diagnostico.
=========================================================================
Constroi, sobre uma serie base (1h), as features candidatas (valor em i usa
SO dados <= i): EMA-slope, distancia da EMA, tendencia 1h/4h/1d, Donchian
position, range position, ATR%, expansao de vol, volume z-score, funding,
funding percentil, OI, variacao de OI, price-OI divergence, funding+direcao,
regime de vol, hora/dia-da-semana, rally/drawdown recente.

basis: omitido (sem dado spot legitimo). Polymarket: omitido (insufficient_
history => shadow). Reusa FeatureEngine, perp_signals, htf_direction-style
slope, timeframe_resample + alinhamento causal por close_time.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple


def _num(v) -> float:
    try:
        x = float(v)
        return x
    except (TypeError, ValueError):
        return float("nan")


def _ema_slope_numeric(ema: Sequence[float], k: int) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for i in range(len(ema)):
        if i < k or math.isnan(ema[i]) or math.isnan(ema[i - k]) \
                or ema[i - k] == 0:
            out.append(None)
        else:
            out.append((ema[i] - ema[i - k]) / abs(ema[i - k]))
    return out


def _causal_pctile(series: Sequence[Optional[float]], window: int):
    from crypto_trading_bot.research.perp_signals import (
        causal_percentile_rank)
    return causal_percentile_rank(series, window=window)


def _align_htf_numeric(candles_base, candles_htf, htf_values, *,
                       low_min: int, high_min: int) -> List[Optional[float]]:
    from crypto_trading_bot.research.htf_regime_filter import (
        select_htf_index_by_close)
    idxs = select_htf_index_by_close(candles_base, candles_htf,
                                     low_interval_minutes=low_min,
                                     high_interval_minutes=high_min)
    out = []
    for j in idxs:
        out.append(htf_values[j] if 0 <= j < len(htf_values) else None)
    return out


def build_feature_library(
    candles_base: Sequence, *, funding_points: Sequence = (),
    oi_points: Sequence = (), base_minutes: int = 60,
) -> Tuple[Dict[str, List[Optional[float]]], Dict[int, str], List[float]]:
    """Retorna (features, regime_by_idx, closes). features: {nome -> lista
    causal alinhada a candles_base}. regime_by_idx: {idx -> regime de vol}."""
    from crypto_trading_bot.data.feature_engine import FeatureEngine
    from crypto_trading_bot.research.perp_signals import (
        build_perp_features, causal_pct_change)
    from crypto_trading_bot.research.timeframe_resample import resample

    fe = FeatureEngine().compute(list(candles_base))
    n = len(candles_base)
    closes = [_num(x) for x in fe["closes"]]
    highs = [_num(x) for x in fe["highs"]]
    lows = [_num(x) for x in fe["lows"]]
    vols = [_num(x) for x in fe["volumes"]] if "volumes" in fe else \
        [float(c.volume) for c in candles_base]
    atr = [_num(x) for x in fe["atr_14"]]
    ema50 = [_num(x) for x in fe.get("ema_50", closes)]
    bw = [_num(x) for x in fe.get("bb_bandwidth", [float("nan")] * n)]
    pb = fe.get("bb_percent_b")
    rsi = fe.get("rsi_14")
    if rsi is None:
        rsi = fe.get("rsi")

    feats: Dict[str, List[Optional[float]]] = {}

    # --- preco / EMA / tendencia ---
    feats["ema50_slope_1h"] = _ema_slope_numeric(ema50, 6)
    feats["dist_from_ema_atr"] = [
        ((closes[i] - ema50[i]) / atr[i]) if (not math.isnan(atr[i])
         and atr[i] > 0 and not math.isnan(ema50[i])) else None
        for i in range(n)]

    # tendencia 4h e 1d (slope numerico no HTF, alinhado causal ao 1h)
    if base_minutes == 60:
        c4 = resample(candles_base, factor_minutes=240, base_minutes=60)
        c1d = resample(candles_base, factor_minutes=1440, base_minutes=60)
        for c, lbl, hm in ((c4, "trend_4h", 240), (c1d, "trend_1d", 1440)):
            if len(c) > 60:
                fe_h = FeatureEngine().compute(list(c))
                ema_h = [_num(x) for x in fe_h.get("ema_50",
                         [float("nan")] * len(c))]
                slope_h = _ema_slope_numeric(ema_h, 6)
                feats[lbl + "_slope"] = _align_htf_numeric(
                    candles_base, c, slope_h, low_min=60, high_min=hm)

    # --- Donchian / range position ---
    def _channel_pos(win):
        out = []
        for i in range(n):
            if i < win:
                out.append(None); continue
            hi = max(highs[i - win:i]); lo = min(lows[i - win:i])
            out.append((closes[i] - lo) / (hi - lo) if hi > lo else None)
        return out
    feats["donchian_pos_20"] = _channel_pos(20)
    feats["range_pos_50"] = _channel_pos(50)

    # --- volatilidade ---
    feats["atr_pct"] = [(atr[i] / closes[i]) if (not math.isnan(atr[i])
                        and closes[i] > 0) else None for i in range(n)]
    feats["vol_expansion"] = [
        (bw[i] / (sum(bw[i - 10:i]) / 10)) if (i >= 10
         and not math.isnan(bw[i]) and all(not math.isnan(x)
         for x in bw[i - 10:i]) and sum(bw[i - 10:i]) > 0) else None
        for i in range(n)]
    feats["vol_regime_pctile"] = _causal_pctile(feats["atr_pct"], 200)

    # --- volume z-score ---
    def _zscore(series, win):
        out = []
        for i in range(len(series)):
            if i < win:
                out.append(None); continue
            w = series[i - win:i]
            mu = sum(w) / win
            sd = math.sqrt(sum((x - mu) ** 2 for x in w) / win)
            out.append(((series[i] - mu) / sd) if sd > 0 else None)
        return out
    feats["volume_zscore_50"] = _zscore(vols, 50)

    # --- rally / drawdown recente (momentum) ---
    feats["recent_return_24"] = [
        (closes[i] / closes[i - 24] - 1.0) if (i >= 24 and closes[i - 24] > 0)
        else None for i in range(n)]
    feats["recent_drawdown_72"] = [
        ((closes[i] - max(closes[i - 72:i + 1])) / max(closes[i - 72:i + 1]))
        if i >= 72 else None for i in range(n)]

    # --- RSI / percent_b ---
    if rsi is not None:
        feats["rsi_14"] = [_num(x) for x in rsi]
    if pb is not None:
        feats["bb_percent_b"] = [_num(x) for x in pb]

    # --- perp: funding / OI ---
    pf = build_perp_features(candles_base, interval_minutes=base_minutes,
                             funding_points=list(funding_points),
                             oi_points=list(oi_points))
    feats["funding_rate"] = list(pf.funding)
    feats["funding_pctile"] = list(pf.funding_pctile)
    feats["open_interest"] = list(pf.oi)
    feats["oi_change"] = list(pf.oi_change)
    # price-OI divergence: retorno recente * variacao de OI (sinal oposto =>
    # divergencia; <0 indica preco e OI em direcoes opostas)
    oi_chg = list(pf.oi_change)
    feats["price_oi_divergence"] = [
        (feats["recent_return_24"][i] * oi_chg[i])
        if (feats["recent_return_24"][i] is not None and oi_chg[i] is not None)
        else None for i in range(n)]
    # funding + direcao (funding alinhado com momentum recente)
    feats["funding_x_momentum"] = [
        (pf.funding[i] * feats["recent_return_24"][i])
        if (pf.funding[i] is not None
            and feats["recent_return_24"][i] is not None) else None
        for i in range(n)]

    # --- sazonalidade ---
    feats["hour_of_day"] = [float(c.timestamp.hour) for c in candles_base]
    feats["day_of_week"] = [float(c.timestamp.weekday())
                            for c in candles_base]

    # --- regime de vol (rotulo p/ estratificacao) ---
    vp = feats["vol_regime_pctile"]
    regime_by_idx: Dict[int, str] = {}
    for i in range(n):
        p = vp[i]
        if p is None:
            continue
        regime_by_idx[i] = ("highvol" if p >= 0.66 else
                            "lowvol" if p <= 0.33 else "midvol")

    return feats, regime_by_idx, closes


__all__ = ["build_feature_library"]
