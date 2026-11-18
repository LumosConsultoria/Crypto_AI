"""
run_edge_research_phase60 — Multi-Asset Cross-Sectional Sprint (Bybit Linear 5m).
================================================================================
Audita cobertura multi-asset e roda 3 hipoteses cross-sectional (scan/ranking;
1 posicao; melhor ativo/ciclo; sem basket). DEV; VAL so se DEV passar; OOS
intocado. dual-profile; custos reais. Sem ordem/demo/live.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Edge research FASE 60 (cross-sec)")
    ap.add_argument("--base-dir", default="data/historical")
    ap.add_argument("--symbols", nargs="+",
                    default=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT",
                             "XRPUSDT"])
    ap.add_argument("--operator-inputs", default="config/operator_inputs.json")
    ap.add_argument("--dev", nargs=2, default=["2025-01-01", "2025-10-01"])
    ap.add_argument("--val", nargs=2, default=["2025-10-01", "2026-02-01"])
    ap.add_argument("--output", default="reports/edge_research_phase60.json")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from loguru import logger
    logger.disable("crypto_trading_bot")
    from crypto_trading_bot.backtesting import load_candles_from_csv
    from crypto_trading_bot.operator_inputs.store import OperatorInputStore
    from crypto_trading_bot.research.edge_research_phase60 import (
        run_edge_research60)

    def _p(d):
        return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    lo, hi = _p(args.dev[0]), _p(args.val[1])

    # AUDITORIA de cobertura: carrega todos, exclui INCOMPLETOS (cobertura <98%
    # do maximo) ou ausentes => dados incompletos sao excluidos (regra operador)
    loaded = {}
    audit = {}
    for sym in args.symbols:
        csv5 = Path(args.base_dir) / sym / "5m" / f"{sym}_5m.csv"
        if not csv5.is_file():
            audit[sym] = "EXCLUIDO: sem dataset 5m"
            continue
        cs = load_candles_from_csv(str(csv5), symbol=sym, timeframe="5")
        dv = [c for c in cs if lo <= (c.timestamp if c.timestamp.tzinfo else
                                      c.timestamp.replace(tzinfo=timezone.utc))
              < hi]
        loaded[sym] = dv
    max_bars = max((len(v) for v in loaded.values()), default=0)
    by_symbol = {}
    for sym, dv in loaded.items():
        cov = len(dv) / max_bars if max_bars else 0.0
        if cov < 0.98:
            audit[sym] = (f"EXCLUIDO: dados incompletos ({len(dv)} barras, "
                          f"cobertura {cov*100:.1f}%)")
        else:
            by_symbol[sym] = dv
            audit[sym] = f"OK ({len(dv)} barras 5m, {cov*100:.1f}%)"
    print("AUDITORIA:")
    for s, a in audit.items():
        print(f"  {s}: {a}")
    if "BTCUSDT" not in by_symbol or len(by_symbol) < 2:
        print("ABORTA: universo insuficiente (precisa BTC + >=1 alt).")
        return 1

    store = (OperatorInputStore(args.operator_inputs)
             if Path(args.operator_inputs).is_file() else None)
    rep = run_edge_research60(by_symbol, dev=tuple(args.dev),
                             val=tuple(args.val), operator_store=store,
                             progress=lambda m: print(f"  {m}"))
    d = rep.to_dict()
    d["audit"] = audit
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(d, indent=2, default=str), encoding="utf-8")

    print(f"\nDECISAO: {d['decision']} | universe={d['universe']['symbols']} "
          f"bars={d['universe']['n_bars_aligned']}")
    print("RANKING DEV:")
    for r in d["ranking"]:
        print(f"  {r['name']:42} setups={r['n_setups']} "
              f"trades={r['dev_trades']} net={r['dev_net']} PF={r['dev_pf']} "
              f"criterios={r['dev_criteria_passed']}/9 class={r['dev_classification']}")
    for name, b in d["per_hypothesis"].items():
        print(f"  - {name}: {b.get('reject_reason')}")
    print(f"relatorio: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
