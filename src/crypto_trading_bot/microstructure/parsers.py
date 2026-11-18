"""
Parsers Bybit V5 (FASE 63) — orderbook, recent-trade, ticker. Read-only.
Tolerantes a campos ausentes; nunca levantam por payload parcial.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Optional

from crypto_trading_bot.microstructure.models import BookSnapshot, Trade


def _lv(rows, reverse: bool) -> List:
    out = []
    for r in (rows or []):
        try:
            out.append((float(r[0]), float(r[1])))
        except (TypeError, ValueError, IndexError):
            continue
    out.sort(key=lambda x: x[0], reverse=reverse)
    return out


def parse_orderbook(result: Mapping[str, Any], *, ts: Optional[float] = None
                    ) -> Optional[BookSnapshot]:
    """Bybit V5 /v5/market/orderbook result: b=bids [[p,s]], a=asks. ts(ms)."""
    if not result:
        return None
    bids = _lv(result.get("b"), reverse=True)     # maior preco primeiro
    asks = _lv(result.get("a"), reverse=False)    # menor preco primeiro
    if not bids or not asks:
        return None
    t = ts
    if t is None:
        raw = result.get("ts") or result.get("cts")
        t = (float(raw) / 1000.0) if raw else 0.0
    return BookSnapshot(ts=float(t), bids=bids, asks=asks)


def parse_trades(result: Mapping[str, Any]) -> List[Trade]:
    """Bybit V5 /v5/market/recent-trade result.list: {price,size,side,time,
    execId}. side = lado do TAKER (Buy/Sell)."""
    out: List[Trade] = []
    for r in (result.get("list") or []):
        try:
            price = float(r.get("price"))
            size = float(r.get("size"))
            side = str(r.get("side", "")).lower()
            tms = float(r.get("time"))
        except (TypeError, ValueError):
            continue
        side = "buy" if side in ("buy",) else "sell"
        out.append(Trade(ts=tms / 1000.0, price=price, size=size, side=side))
    out.sort(key=lambda x: x.ts)
    return out


def parse_ticker(result: Mapping[str, Any]) -> dict:
    """Bybit V5 tickers: bid1Price/ask1Price/bid1Size/ask1Size/lastPrice."""
    lst = result.get("list") or []
    t = lst[0] if lst else result

    def _f(k):
        try:
            return float(t.get(k))
        except (TypeError, ValueError):
            return None
    bid, ask = _f("bid1Price"), _f("ask1Price")
    return {"bid": bid, "ask": ask, "bid_size": _f("bid1Size"),
            "ask_size": _f("ask1Size"), "last": _f("lastPrice"),
            "spread": (ask - bid) if (bid and ask) else None}


def trade_id(r: Mapping[str, Any]) -> str:
    return str(r.get("execId") or r.get("i")
              or f"{r.get('time')}_{r.get('price')}_{r.get('size')}")


__all__ = ["parse_orderbook", "parse_trades", "parse_ticker", "trade_id"]
