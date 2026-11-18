"""
run_polymarket_history_fetch (FASE 47) — PoC de viabilidade historica (gated)
==============================================================================
Descobre mercados BTC ELEGIVEIS (termos pre-definidos; sem cherry-pick por
desfecho) na API publica do Polymarket (Gamma) e tenta montar historico de
preco/probabilidade por timestamp (CLOB prices-history). Salva canonico +
cobertura/readiness. READ-ONLY; nunca aposta/ordem; sem secret.

GATED: so toca a rede com --allow-network. Se a cobertura for insuficiente/
irrelevante p/ BTC => verdict insufficient_history => Polymarket vai p/ shadow
(C nao roda historico; sem inventar dados retroativos).

Uso (apos autorizacao):
  python scripts/run_polymarket_history_fetch.py --start 2025-01-01 \
      --end 2026-05-31 --out data/polymarket/btc_history.json --allow-network
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_GAMMA = "https://gamma-api.polymarket.com"
_CLOB = "https://clob.polymarket.com"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Polymarket PoC (FASE 47)")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default="data/polymarket/btc_history.json")
    ap.add_argument("--max-markets", type=int, default=50)
    ap.add_argument("--allow-network", action="store_true")
    args = ap.parse_args(argv)

    if not args.allow_network:
        print("BLOQUEADO: rede gated. Use --allow-network (autorizado).")
        return 3

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from crypto_trading_bot.prediction_markets.polymarket_history import (
        PolymarketHistory, PolymarketSnapshot, default_polymarket_transport,
        is_btc_eligible, load_snapshots, save_canonical)

    fetch = default_polymarket_transport()
    start = datetime.strptime(args.start, "%Y-%m-%d").replace(
        tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    # 1) descoberta de mercados BTC elegiveis (Gamma)
    print("descobrindo mercados BTC elegiveis (Gamma, read-only)...")
    snaps_rows = []
    discovered = 0
    try:
        markets = fetch(f"{_GAMMA}/markets?closed=true&limit={args.max_markets}"
                        f"&order=startDate&ascending=true")
        if isinstance(markets, dict):
            markets = markets.get("data") or markets.get("markets") or []
        for m in (markets or [])[:args.max_markets]:
            q = str(m.get("question", ""))
            if not is_btc_eligible(q, str(m.get("category", ""))):
                continue
            discovered += 1
            created = m.get("startDate") or m.get("createdAt")
            resolved = m.get("endDate") or m.get("closedTime")
            # token CLOB p/ historico de preco
            token = None
            toks = m.get("clobTokenIds") or m.get("tokens") or []
            if isinstance(toks, str):
                try:
                    toks = json.loads(toks)
                except Exception:  # noqa: BLE001
                    toks = []
            if toks:
                token = toks[0] if isinstance(toks[0], str) else \
                    toks[0].get("token_id")
            if not token:
                continue
            try:
                hist = fetch(f"{_CLOB}/prices-history?market={token}"
                             f"&interval=max&fidelity=60")
                points = (hist or {}).get("history") or []
            except Exception:  # noqa: BLE001
                points = []
            for pt in points:
                ts = pt.get("t")
                price = pt.get("p")
                if ts is None or price is None:
                    continue
                tdt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
                snaps_rows.append({
                    "market_id": str(m.get("id") or token),
                    "question": q, "category": str(m.get("category", "")),
                    "created_at": created, "resolved_at": resolved,
                    "timestamp": tdt.isoformat(), "prob_yes": float(price)})
    except Exception as e:  # noqa: BLE001
        print(f"falha na descoberta/fetch (sem segredos): {type(e).__name__}")

    snaps = load_snapshots(snaps_rows)
    hist = PolymarketHistory(snaps)
    cov = hist.coverage(start, end)
    save_canonical(args.out, snaps, meta={
        "source": "polymarket_gamma+clob", "discovered_btc_markets":
        discovered, "window": [args.start, args.end]})
    report = {"schema": "polymarket_poc_v1", "discovered_btc_markets":
              discovered, "coverage": cov, "out": args.out}
    print(json.dumps(report, indent=2))
    if cov["verdict"] == "insufficient_history":
        print("=> insufficient_history: Polymarket vai p/ SHADOW (C nao roda "
              "historico). Sem inventar dados retroativos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
