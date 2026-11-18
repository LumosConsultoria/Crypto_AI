"""
run_edge_research_phase62 — H1 variance_ratio_regime_switch_1h (BTCUSDT 1h).
===========================================================================
DEV primeiro; VAL so se DEV passar os 8 criterios; OOS intocado. dual-profile;
custos reais Bybit + funding. Params pre-fixados. Sem ordem/demo/live. Dados 1h
LOCAIS (sem rede); se faltar, abortar (rede so gated, fora deste script).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def _rows(path):
    if not path or not Path(path).is_file():
        return []
    return json.loads(Path(path).read_text(encoding="utf-8-sig")).get("rows") \
        or []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Edge research FASE 62 (H1 VR 1h)")
    ap.add_argument("--base-dir", default="data/historical")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--funding", default="data/perp/funding_BTCUSDT.json")
    ap.add_argument("--oi", default="data/perp/oi_BTCUSDT_60m.json")
    ap.add_argument("--operator-inputs", default="config/operator_inputs.json")
    ap.add_argument("--dev", nargs=2, default=["2025-01-01", "2025-10-01"])
    ap.add_argument("--val", nargs=2, default=["2025-10-01", "2026-02-01"])
    ap.add_argument("--wf-folds", type=int, default=5)
    ap.add_argument("--output", default="reports/edge_research_phase62.json")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from loguru import logger
    logger.disable("crypto_trading_bot")
    from crypto_trading_bot.backtesting import load_candles_from_csv
    from crypto_trading_bot.operator_inputs.store import OperatorInputStore
    from crypto_trading_bot.research.edge_research_phase62 import (
        run_edge_research62)
    from crypto_trading_bot.research.perp_signals import (
        load_funding, load_open_interest)

    sym = args.symbol.upper()
    csv1h = Path(args.base_dir) / sym / "1h" / f"{sym}_1h.csv"
    if not csv1h.is_file():
        print(f"ABORTA: 1h local ausente ({csv1h}). Rede gated fora deste script.")
        return 1
    candles = load_candles_from_csv(str(csv1h), symbol=sym, timeframe="60")

    def _p(d):
        return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    lo, hi = _p(args.dev[0]), _p(args.val[1])
    dv = [c for c in candles
          if lo <= (c.timestamp if c.timestamp.tzinfo else
                    c.timestamp.replace(tzinfo=timezone.utc)) < hi]
    funding = load_funding(_rows(args.funding))
    oi = load_open_interest(_rows(args.oi))
    store = (OperatorInputStore(args.operator_inputs)
             if Path(args.operator_inputs).is_file() else None)
    print(f"1h(DEV+VAL)={len(dv)} funding={len(funding)} => H1 "
          f"variance_ratio_regime_switch (dual-profile; OOS intocado)")

    rep = run_edge_research62(
        dv, symbol=sym, funding_points=funding, oi_points=oi,
        dev=tuple(args.dev), val=tuple(args.val), operator_store=store,
        wf_folds=args.wf_folds, progress=lambda m: print(f"  {m}"))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep.to_dict(), indent=2, default=str),
                   encoding="utf-8")
    d = rep.to_dict()
    h = d["hypothesis"]
    dev = h["dev"]
    sm = dev.get("strategy_metrics") or {}
    g = dev.get("gate") or {}
    att = dev.get("hyro_challenge_attempts") or {}
    print(f"\nDECISAO: {d['decision']}")
    print(f"  setups={h['n_setups']} trades={sm.get('num_trades')} "
          f"net={sm.get('net_pnl_usd')} PF={sm.get('profit_factor_net')} "
          f"exp={sm.get('expectancy_net_usd')} maxDD={sm.get('max_drawdown_pct')} "
          f"win={sm.get('win_rate')}")
    print(f"  fees={sm.get('fees_usd')} funding={sm.get('funding_usd')} "
          f"hyro_attempts={att.get('total_attempts')}/{att.get('pass_rate')}")
    print(f"  gate_passed={g.get('passed')} checks={g.get('checks')}")
    if "val" in h:
        vsm = h["val"].get("strategy_metrics") or {}
        print(f"  VAL: trades={vsm.get('num_trades')} net={vsm.get('net_pnl_usd')} "
              f"PF={vsm.get('profit_factor_net')} "
              f"gate={h['val'].get('gate', {}).get('passed')}")
    print(f"  MOTIVO: {d['reason']}")
    print(f"  confirmacoes: {d['confirmations']}")
    print(f"relatorio: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
