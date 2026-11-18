"""
run_edge_research_phase47 (FASE 47) — orquestrador offline da pesquisa A-E.
===========================================================================
Carrega candles 15m Bybit linear (canonico) + series perp (funding/OI) ja
coletadas + (opcional) historico Polymarket; roda a ablacao A-E com config
EFETIVA dos operator inputs (0,5% soberano), sizing dinamico e funding REAL
no PnL realistic. D/E ficam PENDENTE (IA sem backtest historico legitimo).

OFFLINE: nao baixa nada (use run_bybit_aux_fetch / run_polymarket_history_fetch
antes, gated). OOS so apos DEV(+VAL). Demo/live bloqueados.

Uso:
  python scripts/run_edge_research_phase47.py \
      --candles-15m data/historical/BTCUSDT/15m \
      --funding data/perp/funding_BTCUSDT.json \
      --oi data/perp/oi_BTCUSDT_60m.json \
      --operator-inputs config/operator_inputs.json \
      --output reports/edge_research_phase47_btcusdt.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_perp_rows(path, key):
    if not path:
        return []
    p = Path(path)
    if not p.is_file():
        return []
    data = json.loads(p.read_text(encoding="utf-8-sig"))
    return data.get("rows") or []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Edge research FASE 47 (A-E)")
    ap.add_argument("--base-dir", default="data/historical",
                    help="dir canonico; le {base}/BTCUSDT/15m/BTCUSDT_15m.csv")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--funding", default=None)
    ap.add_argument("--oi", default=None)
    ap.add_argument("--polymarket", default=None,
                    help="canonico polymarket_history (opcional)")
    ap.add_argument("--operator-inputs", default="config/operator_inputs.json")
    ap.add_argument("--dev", nargs=2, default=["2025-01-01", "2025-10-01"])
    ap.add_argument("--val", nargs=2, default=["2025-10-01", "2026-02-01"])
    ap.add_argument("--oos", nargs=2, default=["2026-02-01", "2026-05-31"])
    ap.add_argument("--wf-folds", type=int, default=5)
    ap.add_argument("--no-oos", action="store_true")
    ap.add_argument("--output", default="reports/edge_research_phase47.json")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from loguru import logger
    logger.disable("crypto_trading_bot")
    from crypto_trading_bot.backtesting import load_candles_from_csv
    from crypto_trading_bot.operator_inputs.store import OperatorInputStore
    from crypto_trading_bot.prediction_markets.polymarket_history import (
        PolymarketHistory, load_canonical)
    from crypto_trading_bot.research.edge_research_phase47 import (
        run_edge_research47)
    from crypto_trading_bot.research.perp_signals import (
        load_funding, load_open_interest)

    print("carregando candles 15m...")
    sym = args.symbol.upper()
    csv15 = Path(args.base_dir) / sym / "15m" / f"{sym}_15m.csv"
    candles = load_candles_from_csv(str(csv15), symbol=sym, timeframe="15")
    funding = load_funding(_load_perp_rows(args.funding, "rows"))
    oi = load_open_interest(_load_perp_rows(args.oi, "rows"))

    poly_hist = None
    poly_ok = False
    if args.polymarket and Path(args.polymarket).is_file():
        snaps = load_canonical(args.polymarket)
        poly_hist = PolymarketHistory(snaps)
        cov = poly_hist.coverage()
        poly_ok = cov["verdict"] == "sufficient"
        print(f"polymarket coverage: {cov['verdict']}")

    store = None
    if Path(args.operator_inputs).is_file():
        store = OperatorInputStore(args.operator_inputs)

    print(f"candles={len(candles)} funding={len(funding)} oi={len(oi)}; "
          f"rodando ablacao A-E (D/E PENDENTE - IA prospectiva)...")
    rep = run_edge_research47(
        candles, funding_points=funding, oi_points=oi,
        polymarket_history=poly_hist, polymarket_coverage_ok=poly_ok,
        operator_store=store,
        dev=tuple(args.dev), val=tuple(args.val), oos=tuple(args.oos),
        wf_folds=args.wf_folds, run_oos=not args.no_oos,
        progress=lambda m: print(f"  {m}"))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep.to_dict(), indent=2, default=str),
                   encoding="utf-8")
    print(f"\nOVERALL VERDICT: {rep.overall_verdict} | FINAL(E): "
          f"{rep.final_bot_verdict}")
    print(f"relatorio: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
