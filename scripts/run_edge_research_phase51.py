"""
run_edge_research_phase51 (FASE 51) — F5 funding-swing MR + dual-profile.
=========================================================================
Carrega 1h Bybit linear + funding/OI; resample 4h; monta F5 (funding-swing
mean-reversion) e avalia nos DOIS perfis (HyroTrader + Trader Padrao) via
standard_report, risco 0,5% + analise 1% separada. DEV(+VAL); OOS preservado.
Sem rede; sem ordem/demo/live.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _rows(path):
    if not path or not Path(path).is_file():
        return []
    return json.loads(Path(path).read_text(encoding="utf-8-sig")).get("rows") \
        or []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Edge research FASE 51 (F5 dual)")
    ap.add_argument("--base-dir", default="data/historical")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--funding", default="data/perp/funding_BTCUSDT.json")
    ap.add_argument("--oi", default="data/perp/oi_BTCUSDT_60m.json")
    ap.add_argument("--operator-inputs", default="config/operator_inputs.json")
    ap.add_argument("--dev", nargs=2, default=["2025-01-01", "2025-10-01"])
    ap.add_argument("--val", nargs=2, default=["2025-10-01", "2026-02-01"])
    ap.add_argument("--oos", nargs=2, default=["2026-02-01", "2026-05-31"])
    ap.add_argument("--wf-folds", type=int, default=5)
    ap.add_argument("--no-val", action="store_true")
    ap.add_argument("--output", default="reports/edge_research_phase51.json")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from loguru import logger
    logger.disable("crypto_trading_bot")
    from crypto_trading_bot.backtesting import load_candles_from_csv
    from crypto_trading_bot.operator_inputs.store import OperatorInputStore
    from crypto_trading_bot.research.edge_research_phase51 import (
        run_edge_research51)
    from crypto_trading_bot.research.perp_signals import (
        load_funding, load_open_interest)

    sym = args.symbol.upper()
    csv1h = Path(args.base_dir) / sym / "1h" / f"{sym}_1h.csv"
    candles = load_candles_from_csv(str(csv1h), symbol=sym, timeframe="60")
    funding = load_funding(_rows(args.funding))
    oi = load_open_interest(_rows(args.oi))
    store = (OperatorInputStore(args.operator_inputs)
             if Path(args.operator_inputs).is_file() else None)
    print(f"1h={len(candles)} funding={len(funding)} oi={len(oi)} "
          f"=> F5 funding-swing MR (dual-profile; DEV+VAL; OOS preservado)")

    rep = run_edge_research51(
        candles, symbol=sym, funding_points=funding, oi_points=oi,
        dev=tuple(args.dev), val=tuple(args.val), oos=tuple(args.oos),
        operator_store=store, wf_folds=args.wf_folds, run_val=not args.no_val,
        progress=lambda m: print(f"  {m}"))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep.to_dict(), indent=2, default=str),
                   encoding="utf-8")
    fam = rep.family
    sr = fam["dev_05pct"]["standard_report"]
    sm = sr["strategy_metrics"]
    print(f"\nDECISAO: {rep.decision} | final_classification="
          f"{fam['final_classification']} (DEV={fam['dev_classification']} "
          f"VAL={fam.get('val_classification')})")
    print(f"  setups={fam['n_setups']} early_stop={fam['early_stop']} "
          f"trades={sm['num_trades']} gross={sm['gross_pnl_usd']} "
          f"net={sm['net_pnl_usd']} PF={sm['profit_factor_net']}")
    print(f"  5 verdicts: {fam['verdict']}")
    st1 = fam["standard_trader_1pct_analysis"]
    print(f"  trader@1%: verdict={st1['verdict']} net={st1['net_pnl_usd']} "
          f"PF={st1['profit_factor_net']} maxDD={st1['max_drawdown_pct']}")
    print(f"relatorio: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
