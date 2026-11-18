"""
run_polymarket_collect (FASE 47) — coletor PROSPECTIVO de snapshots Polymarket
==============================================================================
Captura snapshots ATUAIS (preco/probabilidade) de mercados BTC elegiveis e
ANEXA ao store canonico versionado (shadow prospectivo). READ-ONLY; nunca
aposta/ordem; sem secret. GATED por --allow-network.

Uso (shadow, a partir de agora):
  python scripts/run_polymarket_collect.py \
      --store data/polymarket/btc_shadow.json --allow-network
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_GAMMA = "https://gamma-api.polymarket.com"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Polymarket collect (FASE 47)")
    ap.add_argument("--store", default="data/polymarket/btc_shadow.json")
    ap.add_argument("--max-markets", type=int, default=50)
    ap.add_argument("--allow-network", action="store_true")
    args = ap.parse_args(argv)

    if not args.allow_network:
        print("BLOQUEADO: rede gated. Use --allow-network (autorizado).")
        return 3

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from crypto_trading_bot.prediction_markets.polymarket_history import (
        PolymarketHistory, default_polymarket_transport, is_btc_eligible,
        load_canonical, load_snapshots, save_canonical)

    fetch = default_polymarket_transport()
    now = datetime.now(timezone.utc).isoformat()
    rows = [s.to_dict() for s in load_canonical(args.store)]
    added = 0
    try:
        markets = fetch(f"{_GAMMA}/markets?active=true&closed=false"
                        f"&limit={args.max_markets}")
        if isinstance(markets, dict):
            markets = markets.get("data") or markets.get("markets") or []
        for m in (markets or [])[:args.max_markets]:
            q = str(m.get("question", ""))
            if not is_btc_eligible(q, str(m.get("category", ""))):
                continue
            price = m.get("lastTradePrice") or m.get("outcomePrices")
            if isinstance(price, str):
                try:
                    price = json.loads(price)[0]
                except Exception:  # noqa: BLE001
                    price = None
            if price is None:
                continue
            rows.append({
                "market_id": str(m.get("id", "")), "question": q,
                "category": str(m.get("category", "")),
                "created_at": m.get("startDate"),
                "resolved_at": m.get("endDate"),
                "timestamp": now, "prob_yes": float(price)})
            added += 1
    except Exception as e:  # noqa: BLE001
        print(f"falha fetch (sem segredos): {type(e).__name__}")

    snaps = load_snapshots(rows)
    save_canonical(args.store, snaps, meta={"source": "polymarket_collect",
                                            "last_collect": now})
    cov = PolymarketHistory(snaps).coverage()
    print(json.dumps({"added": added, "total": len(snaps),
                      "coverage": cov, "store": args.store}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
