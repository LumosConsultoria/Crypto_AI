"""
Signal engine btc_ofi_absorption_scalper_v1 (FASE 63). CAUSAL (so dados <= t;
sem lookahead). Calibracao por QUANTIL do WARMUP (sem olhar PnL futuro).
Emite Signal (aprovado) ou com vetos de MERCADO (spread/slippage/depth/vol).
Vetos de RISCO (cooldown/max-trades/piso) ficam no shadow.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from crypto_trading_bot.microstructure import features as F
from crypto_trading_bot.microstructure.models import (
    BookSnapshot, Signal, Tick, Trade)


@dataclass(frozen=True)
class ScalperConfig:
    warmup_seconds: float = 1800.0           # 30 min
    ofi_windows: Sequence[float] = (3.0, 10.0, 30.0)
    tape_windows: Sequence[float] = (10.0, 30.0)
    imbalance_threshold: float = 0.0         # calibrado (quantil 80 warmup)
    aggression_threshold: float = 0.62
    micro_dev_strong: float = 0.25
    max_spread_bps: float = 3.0              # calibrado (warmup + teto)
    max_slippage_bps: float = 5.0           # teto fixo conservador
    max_micro_vol: float = 0.0008
    absorption_vol_min: float = 5.0
    notional_for_slippage_usd: float = 5000.0


def calibrate(ticks: Sequence[Tick], cfg: ScalperConfig) -> ScalperConfig:
    """Deriva imbalance_threshold (quantil 80 do |OFI 10s|) e max_spread_bps
    (p75 do spread do warmup, com teto fixo). SEM PnL futuro."""
    snaps = [t.book for t in ticks]
    ofis = []
    for t in ticks:
        v = F.window_ofi(snaps, t.ts, 10.0)
        if v is not None:
            ofis.append(abs(v))
    spreads = [s for s in (F.spread_bps(t.book) for t in ticks) if s is not None]
    imb = (statistics.quantiles(ofis, n=5)[3] if len(ofis) >= 5
           else cfg.imbalance_threshold)
    if spreads:
        p75 = (statistics.quantiles(spreads, n=4)[2] if len(spreads) >= 4
               else max(spreads))
        max_spr = min(max(p75 * 1.5, 1.0), 8.0)     # teto fixo 8 bps
    else:
        max_spr = cfg.max_spread_bps
    return ScalperConfig(
        warmup_seconds=cfg.warmup_seconds, ofi_windows=cfg.ofi_windows,
        tape_windows=cfg.tape_windows, imbalance_threshold=round(imb, 6),
        aggression_threshold=cfg.aggression_threshold,
        micro_dev_strong=cfg.micro_dev_strong, max_spread_bps=round(max_spr, 4),
        max_slippage_bps=cfg.max_slippage_bps, max_micro_vol=cfg.max_micro_vol,
        absorption_vol_min=cfg.absorption_vol_min,
        notional_for_slippage_usd=cfg.notional_for_slippage_usd)


class SignalEngine:
    def __init__(self, cfg: ScalperConfig) -> None:
        self.cfg = cfg
        self._snaps: List[BookSnapshot] = []
        self._trades: List[Trade] = []
        self._prev_mid: Optional[float] = None

    def ingest(self, tick: Tick) -> None:
        self._snaps.append(tick.book)
        self._trades.extend(tick.trades)
        horizon = max(self.cfg.ofi_windows + self.cfg.tape_windows) + 5.0
        cutoff = tick.ts - horizon
        self._snaps = [s for s in self._snaps if s.ts >= cutoff]
        self._trades = [t for t in self._trades if t.ts >= cutoff]

    def evaluate(self, now_ts: float) -> Optional[Signal]:
        """Avalia no instante now_ts (so dados <= now). None se sem setup."""
        if not self._snaps:
            return None
        book = self._snaps[-1]
        c = self.cfg
        ofi3 = F.window_ofi(self._snaps, now_ts, c.ofi_windows[0])
        ofi10 = F.window_ofi(self._snaps, now_ts, c.ofi_windows[1])
        ar10 = F.aggression_ratio(self._trades, now_ts, c.tape_windows[0])
        mdev = F.microprice_deviation(book)
        if None in (ofi3, ofi10, mdev) or ar10 is None:
            self._prev_mid = book.mid()
            return None
        absor = (F.absorption(self._trades, book, self._prev_mid or book.mid(),
                              now_ts, c.tape_windows[0],
                              vol_min=c.absorption_vol_min)
                 if self._prev_mid else None)
        aggr = ar10["aggression_ratio"]
        feats = {"ofi_3s": round(ofi3, 4), "ofi_10s": round(ofi10, 4),
                 "aggression_ratio": round(aggr, 4),
                 "microprice_dev": round(mdev, 4), "absorption": absor,
                 "spread_bps": F.spread_bps(book),
                 "micro_vol": F.micro_volatility(self._snaps, now_ts, 10.0)}
        direction = None
        long_setup = (ofi3 > 0 and ofi10 > 0 and ofi10 >= c.imbalance_threshold
                      and aggr >= c.aggression_threshold and mdev > 0
                      and (absor == "sell_absorbed" or mdev >= c.micro_dev_strong))
        short_setup = (ofi3 < 0 and ofi10 < 0
                       and abs(ofi10) >= c.imbalance_threshold
                       and aggr <= (1.0 - c.aggression_threshold) and mdev < 0
                       and (absor == "buy_absorbed" or mdev <= -c.micro_dev_strong))
        if long_setup:
            direction = "long"
        elif short_setup:
            direction = "short"
        self._prev_mid = book.mid()
        if direction is None:
            return None
        # vetos de MERCADO
        vetoes: List[str] = []
        spr = F.spread_bps(book)
        if spr is None or spr > c.max_spread_bps:
            vetoes.append("spread")
        slip = F.estimate_slippage_bps(book, c.notional_for_slippage_usd,
                                       direction)
        if slip is None or slip > c.max_slippage_bps:
            vetoes.append("slippage")
        if not F.depth_supports(book, c.notional_for_slippage_usd, direction):
            vetoes.append("depth")
        mv = feats["micro_vol"]
        if mv is not None and mv > c.max_micro_vol:
            vetoes.append("micro_vol")
        feats["slippage_bps"] = (round(slip, 4) if slip is not None else None)
        return Signal(ts=now_ts, direction=direction, entry_ref=book.mid(),
                      features=feats, vetoes=tuple(vetoes))


__all__ = ["ScalperConfig", "calibrate", "SignalEngine"]
