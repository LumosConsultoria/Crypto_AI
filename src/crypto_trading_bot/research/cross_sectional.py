"""
Cross-Sectional Universe + Backtest (FASE 60) — multi-asset perp scan/ranking.
==============================================================================
Alinha N ativos por timestamp (5m), expoe closes/highs/lows/atr + retornos. O
backtest e SEQUENCIAL de 1 POSICAO: a cada ciclo escolhe SOMENTE o melhor ativo
elegivel (sem basket simultaneo; max_open_positions=1). Custos reais (26bps
round-trip). Saida por stop/alvo (path do ativo) ou tempo. Produz um objeto
rep-like consumido pelo standard_report (dual-profile). Funding ~0 (holds ~2h <<
8h) — registrado; sera modelado por ativo antes de qualquer promocao.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence

from crypto_trading_bot.research.normal_families import _atr

_PISO = 0.005
_MIN_STOP, _MAX_STOP = 0.005, 0.05
REALISTIC_COST = 0.0026


@dataclass(frozen=True)
class XSetup:
    idx: int
    ts: datetime
    symbol: str
    direction: str          # long | short
    entry: float
    stop: float
    target: float
    stop_dist_pct: float


def mk_xsetup(ts, symbol, idx, direction, entry, stop, rr) -> Optional[XSetup]:
    dist = (entry - stop) if direction == "long" else (stop - entry)
    if dist <= 0 or entry <= 0:
        return None
    dpct = dist / entry
    if dpct < _MIN_STOP or dpct > _MAX_STOP:      # piso/cap soberanos
        return None
    target = entry + rr * dist if direction == "long" else entry - rr * dist
    return XSetup(idx, ts, symbol, direction, round(entry, 4), round(stop, 4),
                  round(target, 4), round(dpct, 6))


class Universe:
    """Series multi-asset alinhadas pela INTERSECCAO de timestamps (5m)."""

    def __init__(self, candles_by_symbol: Dict[str, Sequence]) -> None:
        sets = [set(c.timestamp for c in cs)
                for cs in candles_by_symbol.values() if cs]
        common = sorted(set.intersection(*sets)) if sets else []
        self.timestamps: List[datetime] = common
        self.n = len(common)
        self.symbols = list(candles_by_symbol.keys())
        self.closes: Dict[str, List[float]] = {}
        self.highs: Dict[str, List[float]] = {}
        self.lows: Dict[str, List[float]] = {}
        self.atr: Dict[str, List[float]] = {}
        for sym, cs in candles_by_symbol.items():
            by_ts = {c.timestamp: c for c in cs}
            aligned = [by_ts[ts] for ts in common]
            self.closes[sym] = [float(c.close) for c in aligned]
            self.highs[sym] = [float(c.high) for c in aligned]
            self.lows[sym] = [float(c.low) for c in aligned]
            self.atr[sym] = _atr(aligned)

    def ret(self, sym: str, i: int, L: int) -> Optional[float]:
        cl = self.closes[sym]
        if i - L < 0 or cl[i - L] <= 0:
            return None
        return cl[i] / cl[i - L] - 1.0


def run_xs_backtest(universe: Universe, setups: Sequence[XSetup], *,
                    capital: float = 5000.0, risk_base_pct: float = 0.005,
                    max_notional: Optional[float] = None,
                    cost_pct: float = REALISTIC_COST, max_holding: int = 24,
                    seg_lo: int = 0, seg_hi: Optional[int] = None) -> Any:
    """Sim SEQUENCIAL 1-posicao no segmento [seg_lo, seg_hi). Escolhe o proximo
    setup elegivel (>= saida anterior); simula stop/alvo/tempo no PATH do ativo;
    custo 26bps. Retorna rep-like p/ o standard_report."""
    hi_lim = universe.n if seg_hi is None else min(seg_hi, universe.n)
    sset = sorted((s for s in setups if seg_lo <= s.idx < hi_lim),
                  key=lambda s: s.idx)
    risk_base = risk_base_pct * capital
    trades: List[Any] = []
    last_exit = seg_lo - 1
    for s in sset:
        if s.idx <= last_exit:
            continue
        sym = s.symbol
        H, L, C = universe.highs[sym], universe.lows[sym], universe.closes[sym]
        sign = 1.0 if s.direction == "long" else -1.0
        notional = min(risk_base / s.stop_dist_pct, capital)
        if max_notional:
            notional = min(notional, max_notional)
        end = min(s.idx + max_holding, hi_lim - 1)
        exit_idx, exit_price = end, C[end]
        for j in range(s.idx + 1, end + 1):
            if s.direction == "long":
                if L[j] <= s.stop:
                    exit_idx, exit_price = j, s.stop; break
                if H[j] >= s.target:
                    exit_idx, exit_price = j, s.target; break
            else:
                if H[j] >= s.stop:
                    exit_idx, exit_price = j, s.stop; break
                if L[j] <= s.target:
                    exit_idx, exit_price = j, s.target; break
        gross_ret = sign * (exit_price / s.entry - 1.0)
        gross_usd = gross_ret * notional
        cost_usd = cost_pct * notional
        trades.append(SimpleNamespace(
            entry_time=universe.timestamps[s.idx],
            exit_time=universe.timestamps[exit_idx],
            pnl_usd=round(gross_usd - cost_usd, 6),
            gross_pnl_usd=round(gross_usd, 6),
            position_size_usd=round(notional, 2),
            side=("buy" if s.direction == "long" else "sell"),
            stop_loss_price=s.stop, symbol=sym))
        last_exit = exit_idx
    eq = capital
    peak = capital
    maxdd = 0.0
    for t in sorted(trades, key=lambda x: x.exit_time):
        eq += t.pnl_usd
        peak = max(peak, eq)
        if peak > 0:
            maxdd = max(maxdd, (peak - eq) / peak)
    return SimpleNamespace(
        trades=trades, total_fees_usd=round(sum(cost_pct * t.position_size_usd
                                                for t in trades), 4),
        total_slippage_usd=0.0, max_drawdown_pct=round(-maxdd * 100, 4),
        total_trades=len(trades))


__all__ = ["XSetup", "mk_xsetup", "Universe", "run_xs_backtest",
           "REALISTIC_COST"]
