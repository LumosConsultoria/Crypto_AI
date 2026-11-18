"""
run_microstructure_phase63 — btc_ofi_absorption_scalper_v1 (BTCUSDT, FASE 63).
=============================================================================
Modos: collect (rede gated read-only), shadow (offline; orders_emitted=0),
report. NUNCA ordem; sem endpoint privado/de ordem; demo/live bloqueados; OOS
intocado. Rede SO com --allow-network.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Microstructure scalper v1 (FASE 63)")
    ap.add_argument("--mode", required=True,
                    choices=["collect", "shadow", "report"])
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--cache", default="data/microstructure/ticks_BTCUSDT.jsonl")
    ap.add_argument("--allow-network", action="store_true")
    ap.add_argument("--polls", type=int, default=120)
    ap.add_argument("--cadence", type=float, default=1.0)
    ap.add_argument("--depth", type=int, default=50)
    args = ap.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from crypto_trading_bot.microstructure import collector as COL
    from crypto_trading_bot.microstructure.report import (
        build_data_quality, build_shadow_report)
    from crypto_trading_bot.microstructure.shadow import run_shadow

    dq_out = Path("reports/microstructure_phase63_data_quality.json")
    sh_out = Path("reports/microstructure_phase63_shadow.json")
    dq_out.parent.mkdir(parents=True, exist_ok=True)

    if args.mode == "collect":
        if not args.allow_network:
            print(json.dumps({"status": "gated_no_network",
                              "message": "rede BLOQUEADA: use --allow-network "
                                         "(read-only). Nenhuma rede tocada.",
                              "orders_emitted": 0}, indent=2))
            return 0
        print(f"collect read-only {args.symbol} polls={args.polls} "
              f"cadence={args.cadence}s (sem ordem)")
        res = COL.collect(args.symbol, transport=COL.real_transport(),
                          out_path=args.cache, polls=args.polls,
                          cadence_s=args.cadence, depth=args.depth)
        ticks = COL.load_ticks(args.cache)
        dq = build_data_quality(ticks) if ticks else {"status": "empty"}
        dq["collect_result"] = res
        dq_out.write_text(json.dumps(dq, indent=2, default=str),
                          encoding="utf-8")
        print(f"coletado: {res}")
        print(f"data_quality: {dq_out}")
        return 0

    if args.mode == "shadow":
        ticks = COL.load_ticks(args.cache)
        if len(ticks) < 5:
            print(json.dumps({"status": "insufficient_data",
                              "n_ticks": len(ticks),
                              "message": "colete mais (modo collect). Sugestao: "
                                         ">=30min de warmup + tempo p/ >=100 "
                                         "sinais."}, indent=2))
            return 0
        sh = run_shadow(ticks)
        rep = build_shadow_report(sh, ticks)
        sh_out.write_text(json.dumps(rep, indent=2, default=str),
                          encoding="utf-8")
        print(f"SHADOW: status={rep['status']} class={rep['classification']} "
              f"sinais={rep['signals']} fills={rep['fills_simulated']} "
              f"net=US${rep['net_pnl_usd']} PF={rep['profit_factor_net']} "
              f"orders_emitted={rep['orders_emitted']}")
        print(f"decisao={rep['decision']} | shadow: {sh_out}")
        return 0

    # report
    ticks = COL.load_ticks(args.cache)
    dq = build_data_quality(ticks) if ticks else {"status": "empty"}
    print("DATA QUALITY:")
    for k in ("uptime_seconds", "book_updates", "trades_tape",
              "spread_bps_mean", "spread_bps_p95", "ofi_abs_p95",
              "aggression_ratio"):
        print(f"  {k}: {dq.get(k)}")
    if sh_out.is_file():
        rep = json.loads(sh_out.read_text(encoding="utf-8"))
        print(f"SHADOW: class={rep.get('classification')} "
              f"net=US${rep.get('net_pnl_usd')} PF={rep.get('profit_factor_net')} "
              f"decisao={rep.get('decision')}")
    else:
        print("SHADOW: (rode --mode shadow)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
