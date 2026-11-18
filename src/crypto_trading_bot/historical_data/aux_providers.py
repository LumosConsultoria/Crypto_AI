"""
Bybit AUX providers (FASE 47) — funding history + open interest + instrument.
==============================================================================
READ-ONLY, endpoints PUBLICOS Bybit V5 (mainnet, LINEAR), SEM auth/secret.
Mercado-alvo BTCUSDT linear. Transporte HTTP INJETAVEL (em TESTE injeta-se um
fake => ZERO rede; o provider real NUNCA e chamado em teste).

- funding history:  /v5/market/funding/history  -> [{timestamp, funding_rate}]
- open interest:    /v5/market/open-interest     -> [{timestamp, open_interest}]
- instrument info:  /v5/market/instruments-info  -> dict de specs

⚠️ ZERO execucao/ordem/credencial. Retencao de OI pode ser limitada => o
   chamador AUDITA cobertura antes de comprometer F2.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional

from crypto_trading_bot.historical_data.providers import HistoricalDataError

_BASE = "https://api.bybit.com"
_CATEGORY = "linear"
_PAGE = 200

# transporte: url -> payload JSON (dict). Injetavel p/ teste (sem rede).
Transport = Callable[[str], Mapping[str, Any]]

# intervalo OI Bybit (minutos -> intervalTime)
_OI_INTERVAL = {5: "5min", 15: "15min", 30: "30min", 60: "1h",
                240: "4h", 1440: "1d"}


def _real_transport(timeout: float = 20.0, retries: int = 3,
                    sleep: float = 0.25) -> Transport:
    def _get(url: str) -> Mapping[str, Any]:
        import time
        import urllib.request
        last = None
        for attempt in range(retries):
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "crypto-ai-readonly"})
                with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310
                    return json.loads(r.read().decode("utf-8"))
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(sleep * (attempt + 1))
        raise HistoricalDataError(
            f"falha fetch publico Bybit aux (sem segredos): "
            f"{type(last).__name__}")
    return _get


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000,
                                  tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


class BybitFundingProvider:
    """Funding history (8h) read-only. Pagina por janela (endTime)."""

    name = "bybit_funding"
    is_real = True

    def __init__(self, *, transport: Optional[Transport] = None,
                 **kw) -> None:
        self._t = transport or _real_transport(**kw)

    def fetch_funding(self, *, symbol: str, start: datetime,
                      end: datetime) -> List[Dict[str, Any]]:
        import urllib.parse
        start_ms, end_ms = _ms(start), _ms(end)
        seen = set()
        out: List[Dict[str, Any]] = []
        cur_end = end_ms
        # Bybit retorna DESC; pagina retrocedendo por endTime ate cobrir start.
        for _ in range(10000):
            qs = urllib.parse.urlencode({
                "category": _CATEGORY, "symbol": symbol.upper(),
                "startTime": start_ms, "endTime": cur_end, "limit": _PAGE})
            payload = self._t(f"{_BASE}/v5/market/funding/history?{qs}")
            lst = (((payload or {}).get("result") or {}).get("list")) or []
            if not lst:
                break
            oldest = None
            for r in lst:
                ts = int(r.get("fundingRateTimestamp") or r.get("timestamp"))
                if ts in seen or ts < start_ms or ts >= end_ms:
                    oldest = ts if oldest is None else min(oldest, ts)
                    continue
                seen.add(ts)
                out.append({"timestamp": _iso(ts),
                            "funding_rate": float(r["fundingRate"])})
                oldest = ts if oldest is None else min(oldest, ts)
            if oldest is None or oldest <= start_ms or len(lst) < _PAGE:
                break
            cur_end = oldest - 1
        out.sort(key=lambda x: x["timestamp"])
        return out


class BybitOpenInterestProvider:
    """Open interest read-only por intervalo. Pagina por janela."""

    name = "bybit_oi"
    is_real = True

    def __init__(self, *, transport: Optional[Transport] = None,
                 **kw) -> None:
        self._t = transport or _real_transport(**kw)

    def fetch_open_interest(self, *, symbol: str, tf_minutes: int,
                            start: datetime,
                            end: datetime) -> List[Dict[str, Any]]:
        import urllib.parse
        itv = _OI_INTERVAL.get(tf_minutes)
        if itv is None:
            raise HistoricalDataError(
                f"OI intervalTime sem mapeamento p/ {tf_minutes}m")
        start_ms, end_ms = _ms(start), _ms(end)
        seen = set()
        out: List[Dict[str, Any]] = []
        cur_end = end_ms
        for _ in range(10000):
            qs = urllib.parse.urlencode({
                "category": _CATEGORY, "symbol": symbol.upper(),
                "intervalTime": itv, "startTime": start_ms,
                "endTime": cur_end, "limit": _PAGE})
            payload = self._t(f"{_BASE}/v5/market/open-interest?{qs}")
            lst = (((payload or {}).get("result") or {}).get("list")) or []
            if not lst:
                break
            oldest = None
            for r in lst:
                ts = int(r["timestamp"])
                oldest = ts if oldest is None else min(oldest, ts)
                if ts in seen or ts < start_ms or ts >= end_ms:
                    continue
                seen.add(ts)
                out.append({"timestamp": _iso(ts),
                            "open_interest": float(r["openInterest"])})
            if oldest is None or oldest <= start_ms or len(lst) < _PAGE:
                break
            cur_end = oldest - 1
        out.sort(key=lambda x: x["timestamp"])
        return out


class BybitInstrumentProvider:
    """Instrument info (tickSize/qtyStep/minNotional) read-only."""

    name = "bybit_instrument"
    is_real = True

    def __init__(self, *, transport: Optional[Transport] = None,
                 **kw) -> None:
        self._t = transport or _real_transport(**kw)

    def fetch_instrument(self, *, symbol: str) -> Dict[str, Any]:
        import urllib.parse
        qs = urllib.parse.urlencode({"category": _CATEGORY,
                                     "symbol": symbol.upper()})
        payload = self._t(f"{_BASE}/v5/market/instruments-info?{qs}")
        lst = (((payload or {}).get("result") or {}).get("list")) or []
        if not lst:
            return {"symbol": symbol.upper(), "available": False}
        it = lst[0]
        lot = it.get("lotSizeFilter") or {}
        price = it.get("priceFilter") or {}
        return {
            "symbol": it.get("symbol", symbol.upper()),
            "available": True,
            "min_order_qty": _fnum(lot.get("minOrderQty")),
            "qty_step": _fnum(lot.get("qtyStep")),
            "min_notional": _fnum(lot.get("minNotionalValue")),
            "tick_size": _fnum(price.get("tickSize")),
            "price_scale": _fnum(it.get("priceScale")),
        }


def _fnum(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ----------------------------- fakes (teste) -------------------------------

def make_fake_transport(payloads: Mapping[str, Any]) -> Transport:
    """Transporte fake: casa por substring de path. Para testes (sem rede)."""
    def _get(url: str) -> Mapping[str, Any]:
        for key, payload in payloads.items():
            if key in url:
                return payload
        return {"result": {"list": []}}
    return _get


__all__ = [
    "BybitFundingProvider", "BybitOpenInterestProvider",
    "BybitInstrumentProvider", "make_fake_transport",
]
