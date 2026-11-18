"""
Fontes do Risk Overlay (FASE 63) — manual (offline) + Bybit read-only (gated).
==============================================================================
- manual_source: posicoes/conta de um dict (offline; fallback OBRIGATORIO).
- bybit_readonly_source: conta/posicoes/ordens via BybitReadOnlyAdapter
  (account_readonly => wallet/positions/open_orders). SOMENTE read-only; JAMAIS
  ordem/cancel/close. Rede SO com allow_network=True; sem flag => gated_no_network.
  Adapter INJETAVEL (fake em teste; client real NUNCA em teste).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from crypto_trading_bot.risk_overlay.models import AccountState, Position


def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def manual_source(data: Dict[str, Any]) -> Dict[str, Any]:
    acc = data.get("account", {}) or {}
    account = AccountState(
        equity_usd=float(acc.get("equity_usd", 0.0) or 0.0),
        balance_usd=float(acc.get("balance_usd", 0.0) or 0.0),
        realized_pnl_today_usd=float(acc.get("realized_pnl_today_usd", 0.0)
                                     or 0.0),
        day=acc.get("day"))
    positions = [Position(
        symbol=p["symbol"], side=p.get("side", "long"),
        notional_usd=float(p["notional_usd"]),
        entry_price=float(p["entry_price"]), mark_price=float(p["mark_price"]),
        stop_loss_price=_f(p.get("stop_loss_price")),
        unrealized_pnl_usd=_f(p.get("unrealized_pnl_usd")),
        funding_rate=_f(p.get("funding_rate")))
        for p in (data.get("positions") or [])]
    return {"status": "manual", "account": account, "positions": positions,
            "raw": None}


def _map_account(raw: Dict[str, Any]):
    w = raw.get("wallet") or {}
    equity = _f(w.get("equity") or w.get("total_equity")
                or w.get("totalEquity") or w.get("wallet_balance")
                or w.get("walletBalance"))
    balance = _f(w.get("balance") or w.get("available")
                 or w.get("availableBalance")) or equity
    account = AccountState(equity_usd=equity or 0.0, balance_usd=balance or 0.0)
    positions: List[Position] = []
    for p in (raw.get("positions") or []):
        sym = p.get("symbol")
        size = _f(p.get("size") or p.get("qty"))
        entry = _f(p.get("avgPrice") or p.get("entryPrice")
                   or p.get("entry_price"))
        mark = _f(p.get("markPrice") or p.get("mark_price")) or entry
        if not (sym and size and entry):
            continue
        side = str(p.get("side", "")).lower() or "long"
        side = "long" if side in ("buy", "long") else "short"
        positions.append(Position(
            symbol=sym, side=side, notional_usd=abs(size) * (mark or entry),
            entry_price=entry, mark_price=mark or entry,
            stop_loss_price=_f(p.get("stopLoss") or p.get("stop_loss"))))
    return account, positions


def bybit_readonly_source(*, allow_network: bool, adapter: Any = None,
                          environment: str = "demo") -> Dict[str, Any]:
    if not allow_network:
        return {"status": "gated_no_network", "account": None, "positions": [],
                "raw": None,
                "note": "rede BLOQUEADA: use --allow-network (read-only)."}
    if adapter is None:
        try:
            from crypto_trading_bot.netcomms.adapters.bybit_readonly import (
                BybitReadOnlyAdapter)
            adapter = BybitReadOnlyAdapter(environment=environment)
        except Exception as e:  # noqa: BLE001
            return {"status": "unavailable", "error": type(e).__name__,
                    "account": None, "positions": [], "raw": None}
    try:
        raw = adapter.account_readonly()      # SO read-only (sem ordem)
    except Exception as e:  # noqa: BLE001 (sem credencial/erro => fallback)
        return {"status": "not_configured", "error": type(e).__name__,
                "account": None, "positions": [], "raw": None,
                "note": "conta read-only indisponivel (sem credencial/erro); "
                        "fallback manual."}
    account, positions = _map_account(raw)
    if (account.equity_usd or 0.0) <= 0.0 and not positions:
        # conta read-only VAZIA (ex.: sem credencial em demo) => sem dado util;
        # nao gerar falso-critico de equity 0; sinaliza p/ fallback manual.
        return {"status": "connected_empty", "raw": raw, "account": None,
                "positions": [],
                "note": "conta read-only vazia (sem credencial?); fallback manual."}
    return {"status": "connected", "raw": raw, "account": account,
            "positions": positions}


__all__ = ["manual_source", "bybit_readonly_source"]
