"""
Perp-native families (FASE 47) — F1 Funding-extreme fade + F2 OI-confirmed
momentum. Estruturalmente DIFERENTES das rejeitadas (FASE 44/46 usavam so
preco/ATR): aqui o GATE e um sinal perpetual (funding/OI).

F1 — Funding-extreme fade (reversao de crowding):
  funding em EXTREMO (percentil causal alto/baixo) + preco esticado =>
  FADE em direcao a media. Stop ESTRUTURAL (swing +/- folga ATR).
F2 — OI-confirmed momentum:
  rompimento de swing CONFIRMADO por EXPANSAO de open interest (dinheiro
  novo); divergencia de OI (preco rompe, OI nao expande) => SKIP. Stop
  estrutural.

Determinístico, params FIXOS, anti-lookahead (setup em i usa SO features<=i
e o sinal perp causal). Reusa Setup (mtf_setups) + execucao thin (sem
regime-gate; o sinal perp ja e o gate). RiskEngine/piso 0,5% soberanos
(below_floor so marca; HOLD se < piso).
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any, Dict, List, Optional, Sequence

from crypto_trading_bot.research.htf_regime_filter import _ts_key
from crypto_trading_bot.research.mtf_setups import Setup, _f

_PISO = 0.005

F1_PARAMS = {"high_pctile": 0.90, "low_pctile": 0.10,
             "stretch_high": 0.90, "stretch_low": 0.10,
             "swing_lookback": 20, "atr_buffer": 0.5, "risk_reward": 1.5}
F2_PARAMS = {"oi_expansion": 0.01, "swing_lookback": 20,
             "atr_buffer": 0.5, "risk_reward": 1.5}


def _mk_setup(candles, i, direction, entry, stop, rr, atr_i, interval, tag):
    if direction == "long":
        dist = entry - stop
        target = entry + rr * dist
    else:
        dist = stop - entry
        target = entry - rr * dist
    if dist <= 0 or entry <= 0:
        return None
    dist_pct = dist / entry
    open_ts = candles[i].timestamp
    return Setup(idx=i, open_ts=open_ts,
                 close_ts=open_ts + timedelta(minutes=interval),
                 direction=direction, entry_ref=round(entry, 2),
                 stop=round(stop, 2), target=round(target, 2),
                 stop_dist_pct=round(dist_pct, 6),
                 below_floor=dist_pct < _PISO, atr=atr_i,
                 setup_id=f"{tag}_{i}")


def _features(candles):
    from crypto_trading_bot.data.feature_engine import FeatureEngine
    feats = FeatureEngine().compute(list(candles))
    closes = [_f(x) for x in feats["closes"]]
    highs = [_f(x) for x in feats["highs"]]
    lows = [_f(x) for x in feats["lows"]]
    atr = [_f(x) for x in feats["atr_14"]]
    pb_raw = feats.get("bb_percent_b")
    percent_b = [_f(x) for x in pb_raw] if pb_raw is not None else None
    ema = [_f(x) for x in feats.get("ema_20", feats.get("ema_50", closes))]
    return closes, highs, lows, atr, percent_b, ema


def _stretch(percent_b, ema, closes, atr, i):
    """Retorna (stretched_up, stretched_down) no candle i, via bb_percent_b
    se disponivel, senao distancia da EMA em ATRs."""
    if percent_b is not None and not math.isnan(percent_b[i]):
        return percent_b[i] >= 0.9, percent_b[i] <= 0.1
    a = atr[i]
    if math.isnan(a) or a <= 0 or math.isnan(ema[i]):
        return False, False
    dev = (closes[i] - ema[i]) / a
    return dev >= 2.0, dev <= -2.0


def detect_f1_funding_fade(
    candles: Sequence, funding_pctile: Sequence[Optional[float]], *,
    interval_minutes: int = 15, params: Optional[Dict[str, Any]] = None,
    perp_gate: bool = True,
) -> List[Setup]:
    """F1: funding extremo + preco esticado => FADE a media (causal).

    perp_gate=False => BASELINE 'A' (price-only): ignora o gate de funding e
    fade so pela esticada (isola o valor incremental do sinal de funding).
    """
    if not candles:
        return []
    p = {**F1_PARAMS, **(params or {})}
    closes, highs, lows, atr, percent_b, ema = _features(candles)
    n = len(closes)
    sw = int(p["swing_lookback"]); buf = float(p["atr_buffer"])
    rr = float(p["risk_reward"])
    hi_p, lo_p = float(p["high_pctile"]), float(p["low_pctile"])
    out: List[Setup] = []
    start = max(sw, 55)
    for i in range(start, n):
        a = atr[i]
        if math.isnan(a) or a <= 0 or closes[i] <= 0:
            continue
        fp = funding_pctile[i] if i < len(funding_pctile) else None
        if perp_gate and fp is None:
            continue
        up_str, dn_str = _stretch(percent_b, ema, closes, atr, i)
        c = closes[i]
        # fade: stop ALEM do extremo recente (inclui i) => stop>entry garantido
        swing_high = max(highs[i - sw:i + 1])
        swing_low = min(lows[i - sw:i + 1])
        hi_ok = (fp is not None and fp >= hi_p) if perp_gate else True
        lo_ok = (fp is not None and fp <= lo_p) if perp_gate else True
        if hi_ok and up_str:
            # longs lotados + esticado p/ cima => FADE short
            stop = swing_high + buf * a
            s = _mk_setup(candles, i, "short", c, stop, rr, a,
                          interval_minutes, "F1")
        elif lo_ok and dn_str:
            # shorts lotados + esticado p/ baixo => FADE long
            stop = swing_low - buf * a
            s = _mk_setup(candles, i, "long", c, stop, rr, a,
                          interval_minutes, "F1")
        else:
            continue
        if s is not None:
            out.append(s)
    return out


def detect_f2_oi_momentum(
    candles: Sequence, oi_change: Sequence[Optional[float]], *,
    interval_minutes: int = 15, params: Optional[Dict[str, Any]] = None,
    perp_gate: bool = True,
) -> List[Setup]:
    """F2: rompimento de swing CONFIRMADO por expansao de OI (causal).

    perp_gate=False => BASELINE 'A' (price-only): rompimento SEM confirmacao
    de OI (isola o valor incremental do open interest).
    """
    if not candles:
        return []
    p = {**F2_PARAMS, **(params or {})}
    closes, highs, lows, atr, _pb, _ema = _features(candles)
    n = len(closes)
    sw = int(p["swing_lookback"]); buf = float(p["atr_buffer"])
    rr = float(p["risk_reward"]); exp = float(p["oi_expansion"])
    out: List[Setup] = []
    start = max(sw, 55)
    for i in range(start, n):
        a = atr[i]
        if math.isnan(a) or a <= 0 or closes[i] <= 0:
            continue
        if perp_gate:
            oc = oi_change[i] if i < len(oi_change) else None
            if oc is None or oc < exp:
                continue                 # sem expansao de OI => skip (divergencia)
        c = closes[i]
        swing_high = max(highs[i - sw:i])
        swing_low = min(lows[i - sw:i])
        if c > swing_high:               # rompimento p/ cima confirmado
            stop = swing_low - buf * a
            s = _mk_setup(candles, i, "long", c, stop, rr, a,
                          interval_minutes, "F2")
        elif c < swing_low:              # rompimento p/ baixo confirmado
            stop = swing_high + buf * a
            s = _mk_setup(candles, i, "short", c, stop, rr, a,
                          interval_minutes, "F2")
        else:
            continue
        if s is not None:
            out.append(s)
    return out


# ----------------------------- execucao thin ------------------------------

class PerpSetupStrategy:
    """Executa setups perp (F1/F2) no fechamento do candle de setup. Sem
    regime-gate (o sinal perp ja e o gate, embutido na deteccao). Stop
    estrutural; HOLD se stop_dist_pct < piso. Duck-typed p/ o BacktestEngine.
    """

    def __init__(self, *, setups: Sequence[Setup], family_id: str,
                 position_size_usd: float = 0.0,
                 size_by_id: Optional[Dict[str, float]] = None,
                 piso: float = _PISO) -> None:
        self.name = f"perp_{family_id}"
        self._by_ts = {_ts_key(s.open_ts): s for s in setups}
        self._size = float(position_size_usd)
        self._size_by_id = dict(size_by_id or {})
        self._piso = float(piso)
        self._open = False
        self.blocked_below_floor = 0
        self.vetoed_by_context = 0
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

    def evaluate(self, features):
        from crypto_trading_bot.research.mtf_strategy import _emit, _hold
        sym = str(features.get("symbol") or "BTCUSDT")
        if self._open:
            return _hold(sym, self.name, "posicao aberta")
        ts = self._cur_ts(features)
        if ts is None:
            return _hold(sym, self.name, "sem timestamp")
        s = self._by_ts.get(_ts_key(ts))
        if s is None:
            return _hold(sym, self.name, "sem setup")
        if s.stop_dist_pct < self._piso:
            self.blocked_below_floor += 1
            return _hold(sym, self.name, "structural_stop_below_floor")
        size = self._size_by_id.get(s.setup_id, self._size) \
            if self._size_by_id else self._size
        if size <= 0:
            self.vetoed_by_context += 1
            return _hold(sym, self.name, "context_vetoed")
        return _emit(sym, self.name, s.direction, s.entry_ref, s.stop,
                     s.target, size)


__all__ = [
    "F1_PARAMS", "F2_PARAMS",
    "detect_f1_funding_fade", "detect_f2_oi_momentum", "PerpSetupStrategy",
]
