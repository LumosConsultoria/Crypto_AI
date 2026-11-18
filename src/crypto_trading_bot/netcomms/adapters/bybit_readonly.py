"""
Bybit read-only adapter (infra; FASE 43 realocado da antiga UI).
================================================================
Encapsula o BybitClient existente em modo SOMENTE READ-ONLY: health,
instrument info (Bybit V5 camelCase), wallet/positions/open orders. JAMAIS
execucao/cancel/close/place. Secret NUNCA sai do backend (credencial
INJETADA pelo chamador; respostas sanitizadas). FastAPI-free.

Ambiente: demo (gated) | testnet (restrito) | mainnet (BLOQUEADO). Em
TESTES injeta-se `client_factory` fake; o client real NUNCA roda em teste.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional


class BybitReadOnlyAdapter:
    def __init__(
        self, *, environment: str = "demo",
        credential_store=None, provider: str = "bybit",
        client_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._env = environment
        self._cs = credential_store     # opcional; duck-typed .get_secret
        self._provider = provider
        self._client_factory = client_factory   # fake em teste

    def _client(self, *, private: bool):
        if self._env == "mainnet":
            raise PermissionError("mainnet bloqueado por politica")
        if self._client_factory is not None:
            return self._client_factory(environment=self._env,
                                        private=private)
        from crypto_trading_bot.exchange.bybit_client import BybitClient
        api_key = api_secret = None
        if private and self._cs is not None:
            api_key = self._cs.get_secret(self._provider, "API_KEY")
            api_secret = self._cs.get_secret(self._provider, "API_SECRET")
        env = self._env if self._env in ("demo", "testnet") else "testnet"
        return BybitClient(environment=env, api_key=api_key,
                           api_secret=api_secret)

    # ---- read-only ops (cada uma chamada via run_network_op) ----
    def health(self, *, symbol: str = "BTCUSDT") -> Dict[str, Any]:
        c = self._client(private=False)
        t = c.get_ticker(symbol)
        return {"environment": self._env, "reachable": True,
                "symbol": symbol,
                "last": getattr(t, "last_price", None)}

    def instrument_info(self, *, symbol: str = "BTCUSDT") -> Dict[str, Any]:
        c = self._client(private=False)
        info = c.get_instruments_info(symbol=symbol)
        out = _instrument_fields(info)
        try:
            t = c.get_ticker(symbol)
            bid = _num(getattr(t, "bid_price", None)
                       or getattr(t, "bid1_price", None))
            ask = _num(getattr(t, "ask_price", None)
                       or getattr(t, "ask1_price", None))
            last = _num(getattr(t, "last_price", None))
            out.update({"bid": bid, "ask": ask, "last": last})
            if bid is not None and ask is not None:
                out["mid"] = round((bid + ask) / 2, 8)
        except Exception:  # noqa: BLE001
            pass
        return out

    def account_readonly(self) -> Dict[str, Any]:
        # read-only: wallet/balance + posicoes/ordens abertas. SEM execucao.
        c = self._client(private=True)
        wallet = _safe(lambda: c.get_balance())
        positions = _safe(lambda: c.get_positions(symbol=None))
        open_orders = _safe(lambda: c.get_open_orders(symbol=None))
        return {
            "environment": self._env,
            "wallet": _sanitize_wallet(wallet),
            "open_positions_count": _count(positions),
            "open_orders_count": _count(open_orders),
            "positions": _sanitize_list(positions),
            "open_orders": _sanitize_list(open_orders),
            "flat": _count(positions) == 0 and _count(open_orders) == 0,
        }


def _num(v):
    """Converte string/num da exchange em float; None se vazio/invalido."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _instrument_fields(info: Any) -> Dict[str, Any]:
    """Parser do snapshot de instrumento Bybit V5 (camelCase aninhado).
    Cada campo: valor (float) | None (=> 'nao disponivel'). parse_status
    distingue 'sem dados' / 'parser incompleto'. Sem secret."""
    d = info if isinstance(info, dict) else getattr(info, "__dict__", {})
    if not isinstance(d, dict):
        d = {}
    lot = d.get("lotSizeFilter") or d.get("lot_size_filter") or {}
    pf = d.get("priceFilter") or d.get("price_filter") or {}
    fields = {
        "symbol": d.get("symbol"),
        "min_order_qty": _num(lot.get("minOrderQty")
                              or lot.get("min_order_qty")),
        "qty_step": _num(lot.get("qtyStep") or lot.get("qty_step")),
        "tick_size": _num(pf.get("tickSize") or pf.get("tick_size")),
        "min_notional": _num(lot.get("minNotionalValue")
                             or lot.get("minOrderAmt")
                             or lot.get("min_notional_value")),
        "price_scale": _num(d.get("priceScale") or d.get("price_scale")),
    }
    core = ("min_order_qty", "qty_step", "tick_size", "min_notional",
            "price_scale")
    have = [k for k in core if fields[k] is not None]
    if not d:
        parse_status = "no_data"
    elif not have:
        parse_status = "fields_missing"
    elif len(have) < len(core):
        parse_status = "partial"
    else:
        parse_status = "ok"
    fields["raw_present"] = bool(d)
    fields["parse_status"] = parse_status
    return fields


def _safe(fn):
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return None


def _count(x) -> int:
    try:
        return len(x) if x is not None else 0
    except TypeError:
        return 0


def _sanitize_list(x):
    if not x:
        return []
    out = []
    for item in (x if isinstance(x, list) else [x])[:20]:
        d = item if isinstance(item, dict) else getattr(item, "__dict__", {})
        out.append({k: d.get(k) for k in (
            "symbol", "side", "size", "qty", "avgPrice", "avg_price",
            "price", "orderStatus", "order_status", "leverage",
            "unrealisedPnl", "unrealised_pnl") if isinstance(d, dict)
            and k in d})
    return out


def _sanitize_wallet(w) -> Dict[str, Any]:
    """Extrai so totais seguros do wallet-balance V5 (sem secret/coins crus)."""
    if not w:
        return {"available": False}
    d = w if isinstance(w, dict) else getattr(w, "__dict__", {})
    rows = d.get("list") if isinstance(d, dict) else None
    src = (rows[0] if isinstance(rows, list) and rows else d)
    if not isinstance(src, dict):
        return {"available": False}
    return {
        "available": True,
        "total_equity": _num(src.get("totalEquity")),
        "total_wallet_balance": _num(src.get("totalWalletBalance")),
        "total_available_balance": _num(src.get("totalAvailableBalance")),
        "account_type": src.get("accountType"),
    }


__all__ = ["BybitReadOnlyAdapter"]
