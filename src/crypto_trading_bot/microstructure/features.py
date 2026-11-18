"""
Features de microestrutura (FASE 63) — CAUSAIS (so dados <= t). Explicitas:
OFI (Cont-Kukanov-Stoikov), aggression_ratio, microprice/desvio, spread,
profundidade, slippage estimado, absorcao.
"""

from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional, Sequence

from crypto_trading_bot.microstructure.models import BookSnapshot, Trade


def ofi_event(prev: BookSnapshot, cur: BookSnapshot) -> Optional[float]:
    """OFI entre dois snapshots (Cont, Kukanov, Stoikov). >0 = pressao
    compradora; <0 = vendedora. Usa SO o topo do book.
      e = I(Pb>=Pb_)*qb - I(Pb<=Pb_)*qb_ - I(Pa<=Pa_)*qa + I(Pa>=Pa_)*qa_
    """
    pb, qb = (prev.best_bid() or (None, 0.0))
    cb, cqb = (cur.best_bid() or (None, 0.0))
    pa, qa = (prev.best_ask() or (None, 0.0))
    ca, cqa = (cur.best_ask() or (None, 0.0))
    if None in (pb, cb, pa, ca):
        return None
    e_bid = (cqb if cb >= pb else 0.0) - (qb if cb <= pb else 0.0)
    e_ask = -(cqa if ca <= pa else 0.0) + (qa if ca >= pa else 0.0)
    return e_bid + e_ask


def window_ofi(snaps: Sequence[BookSnapshot], now_ts: float, win_s: float
               ) -> Optional[float]:
    """Soma de OFI nos snapshots com ts em (now-win, now]. Causal."""
    sel = [s for s in snaps if now_ts - win_s < s.ts <= now_ts]
    if len(sel) < 2:
        return None
    total = 0.0
    n = 0
    for a, b in zip(sel, sel[1:]):
        e = ofi_event(a, b)
        if e is not None:
            total += e
            n += 1
    return total if n else None


def aggression_ratio(trades: Sequence[Trade], now_ts: float, win_s: float
                     ) -> Optional[Dict[str, float]]:
    """buy_vol/(buy+sell) na janela (now-win, now]. >0,5 = compra dominante."""
    sel = [t for t in trades if now_ts - win_s < t.ts <= now_ts]
    if not sel:
        return None
    buy = sum(t.size for t in sel if t.side == "buy")
    sell = sum(t.size for t in sel if t.side == "sell")
    tot = buy + sell
    if tot <= 0:
        return None
    return {"buy_vol": buy, "sell_vol": sell, "n": len(sel),
            "aggression_ratio": buy / tot}


def microprice_deviation(book: BookSnapshot) -> Optional[float]:
    """(microprice - mid)/spread. >0 pressao p/ cima; <0 p/ baixo. Causal."""
    mid, micro, spr = book.mid(), book.microprice(), book.spread()
    if mid is None or micro is None or not spr or spr <= 0:
        return None
    return (micro - mid) / spr


def spread_bps(book: BookSnapshot) -> Optional[float]:
    mid, spr = book.mid(), book.spread()
    return (spr / mid * 1e4) if (mid and spr is not None and mid > 0) else None


def estimate_slippage_bps(book: BookSnapshot, notional_usd: float,
                          direction: str) -> Optional[float]:
    """Caminha o book do lado de entrada (long=ask, short=bid) p/ preencher
    `notional_usd`; slippage = (avg_fill - mid)/mid em bps (sempre adverso)."""
    mid = book.mid()
    levels = book.asks if direction == "long" else book.bids
    if mid is None or not levels or mid <= 0 or notional_usd <= 0:
        return None
    need = notional_usd
    cost = 0.0
    filled = 0.0
    for price, size in levels:
        cap = price * size
        take = min(need, cap)
        qty = take / price
        cost += qty * price
        filled += qty
        need -= take
        if need <= 1e-9:
            break
    if need > 1e-6 or filled <= 0:
        return None                                 # profundidade insuficiente
    avg = cost / filled
    slip = (avg - mid) / mid if direction == "long" else (mid - avg) / mid
    return slip * 1e4


def depth_supports(book: BookSnapshot, notional_usd: float, direction: str,
                   levels: int = 10) -> bool:
    side = "ask" if direction == "long" else "bid"
    avail = sum(p * s for p, s in
                list(book.asks if direction == "long" else book.bids)[:levels])
    return avail >= notional_usd


def absorption(trades: Sequence[Trade], book: BookSnapshot, prev_mid: float,
               now_ts: float, win_s: float, *, vol_min: float
               ) -> Optional[str]:
    """Absorcao: agressao FORTE com deslocamento de preco PEQUENO.
      - 'sell_absorbed' (BULLISH): venda agressora forte, preco NAO caiu
        proporcional => compradores absorvem.
      - 'buy_absorbed' (BEARISH): compra agressora forte, preco NAO subiu.
    Retorna o tipo ou None. Causal (so trades <= now)."""
    ar = aggression_ratio(trades, now_ts, win_s)
    mid = book.mid()
    if ar is None or mid is None or prev_mid <= 0:
        return None
    tot = ar["buy_vol"] + ar["sell_vol"]
    if tot < vol_min:
        return None
    move = (mid - prev_mid) / prev_mid              # deslocamento relativo
    disp_per_vol = abs(move) / tot
    # limiar de "pouco deslocamento por volume" relativo (heuristica fixa)
    if disp_per_vol > 1e-7:
        return None
    if ar["sell_vol"] > ar["buy_vol"] and move >= 0:
        return "sell_absorbed"                       # bullish
    if ar["buy_vol"] > ar["sell_vol"] and move <= 0:
        return "buy_absorbed"                        # bearish
    return None


def micro_volatility(snaps: Sequence[BookSnapshot], now_ts: float, win_s: float
                     ) -> Optional[float]:
    """Desvio-padrao dos mids na janela / mid atual (vol micro relativa)."""
    sel = [s.mid() for s in snaps if now_ts - win_s < s.ts <= now_ts
           and s.mid() is not None]
    if len(sel) < 3:
        return None
    m = sel[-1]
    return (statistics.pstdev(sel) / m) if m else None


__all__ = ["ofi_event", "window_ofi", "aggression_ratio",
           "microprice_deviation", "spread_bps", "estimate_slippage_bps",
           "depth_supports", "absorption", "micro_volatility"]
