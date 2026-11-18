"""
Collector REST gated (FASE 63) — orderbook + recent-trade + ticker publicos
Bybit V5 (read-only). Transporte INJETAVEL (fake em teste = zero rede). Grava
ticks em JSONL local. NUNCA ordem. v1 usa POLLING REST (sem dep WebSocket);
WS daria maior resolucao (upgrade futuro). Rede SO via CLI com --allow-network.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from crypto_trading_bot.microstructure.models import BookSnapshot, Tick
from crypto_trading_bot.microstructure.parsers import (
    parse_orderbook, parse_trades, trade_id)

Transport = Callable[[str], Mapping[str, Any]]      # url -> result dict
_BASE = "https://api.bybit.com"
_CAT = "linear"


def real_transport(timeout: float = 8.0, retries: int = 2,
                   sleep: float = 0.2) -> Transport:
    def _get(url: str) -> Mapping[str, Any]:
        import urllib.request
        last = None
        for i in range(retries + 1):
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "crypto-ai-readonly"})
                with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
                    return json.loads(r.read().decode("utf-8")).get("result", {})
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(sleep * (i + 1))
        raise RuntimeError(f"falha fetch publico Bybit (sem segredos): "
                           f"{type(last).__name__}")
    return _get


def collect(symbol: str, *, transport: Transport, out_path: str, polls: int,
            cadence_s: float = 1.0, depth: int = 50, trade_limit: int = 200,
            sleep_fn=time.sleep, now_fn=time.time,
            max_consec_fail: int = 15) -> Dict[str, Any]:
    sym = symbol.upper()
    ob_url = f"{_BASE}/v5/market/orderbook?category={_CAT}&symbol={sym}&limit={depth}"
    tr_url = (f"{_BASE}/v5/market/recent-trade?category={_CAT}&symbol={sym}"
              f"&limit={trade_limit}")
    seen: set = set()
    n_ok = n_fail = consec = n_trades = 0
    first_ts = last_ts = None
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        for i in range(polls):
            ts = now_fn()
            try:
                ob = transport(ob_url)
                book = parse_orderbook(ob, ts=ts)
                if book is None:
                    raise ValueError("orderbook vazio")
                tr_res = transport(tr_url)
                new = []
                for r in (tr_res.get("list") or []):
                    tid = trade_id(r)
                    if tid in seen:
                        continue
                    seen.add(tid)
                    new.append(r)
                trades = parse_trades({"list": new})
                tick = Tick(ts=ts, book=book, trades=trades)
                fh.write(json.dumps(tick.to_dict()) + "\n")
                n_ok += 1
                n_trades += len(trades)
                first_ts = first_ts or ts
                last_ts = ts
                consec = 0
            except Exception as e:  # noqa: BLE001 (tolerante/reconexao)
                n_fail += 1
                consec += 1
                if consec >= max_consec_fail:
                    return {"status": "aborted_failures", "polls_ok": n_ok,
                            "failures": n_fail, "reason": type(e).__name__,
                            "out_path": str(out)}
            if i < polls - 1:
                sleep_fn(cadence_s)
    uptime = (last_ts - first_ts) if (first_ts and last_ts) else 0.0
    return {"status": "completed", "symbol": sym, "polls_ok": n_ok,
            "failures": n_fail, "book_updates": n_ok, "trades": n_trades,
            "uptime_seconds": round(uptime, 1), "cadence_s": cadence_s,
            "depth": depth, "out_path": str(out),
            "source": f"{_BASE}/v5/market/{{orderbook,recent-trade}}"}


def load_ticks(path: str) -> List[Tick]:
    out: List[Tick] = []
    p = Path(path)
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        from crypto_trading_bot.microstructure.models import Trade
        book = BookSnapshot(ts=float(d["ts"]),
                            bids=[tuple(x) for x in d.get("bids", [])],
                            asks=[tuple(x) for x in d.get("asks", [])])
        trades = [Trade(ts=float(t["ts"]), price=float(t["price"]),
                        size=float(t["size"]), side=t["side"])
                  for t in d.get("trades", [])]
        out.append(Tick(ts=float(d["ts"]), book=book, trades=trades))
    return out


__all__ = ["Transport", "real_transport", "collect", "load_ticks"]
