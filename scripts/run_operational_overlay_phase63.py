"""
run_operational_overlay_phase63 — Overlay operacional NAO-preditivo (FASE 63).
=============================================================================
Padrao OFFLINE/manual (--input JSON). Rede read-only SO com --allow-network
(Bybit account read-only via netcomms; JAMAIS ordem). Fallback manual sempre
disponivel. Relatorio reports/operational_overlay_phase63.json. Sem ordem;
demo/live bloqueados; OOS intocado.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Overlay operacional FASE 63")
    ap.add_argument("--input", default="", help="JSON manual {account,positions}")
    ap.add_argument("--allow-network", action="store_true",
                    help="GATE: tenta Bybit read-only (sem flag NAO toca a rede)")
    ap.add_argument("--environment", default="demo",
                    choices=["demo", "testnet"])
    ap.add_argument("--operator-inputs", default="config/operator_inputs.json")
    ap.add_argument("--output", default="reports/operational_overlay_phase63.json")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from loguru import logger
    logger.disable("crypto_trading_bot")
    from crypto_trading_bot.risk_overlay import RiskLimits
    from crypto_trading_bot.risk_overlay.operational import (
        build_operational_overlay)
    from crypto_trading_bot.risk_overlay.sources import (
        bybit_readonly_source, manual_source)

    # limites = RiskConfig EFETIVO (HyroTrader) se disponivel; senao defaults
    limits = RiskLimits()
    try:
        from crypto_trading_bot.operator_inputs.store import OperatorInputStore
        from crypto_trading_bot.research.effective_config import (
            build_effective_config)
        store = (OperatorInputStore(args.operator_inputs)
                 if Path(args.operator_inputs).is_file() else None)
        eff = build_effective_config(store=store)
        rc, ext = eff.risk_config, eff.external_ceilings
        limits = RiskLimits(
            capital_usd=float(rc.account_size_usd),
            max_risk_per_trade_pct=float(rc.max_risk_per_trade_pct),
            max_daily_loss_pct=float(ext.get("daily_drawdown_pct",
                                             rc.max_daily_loss_pct)),
            max_total_loss_pct=float(ext.get("total_loss_pct",
                                             rc.max_total_loss_pct)),
            max_exposure_pct=1.0, max_leverage=float(rc.max_leverage),
            max_open_positions=int(rc.max_open_positions),
            min_stop_loss_pct=float(rc.min_stop_loss_pct))
    except Exception as e:  # noqa: BLE001
        print(f"  (limites default; effective_config indisponivel: "
              f"{type(e).__name__})")

    manual_data = None
    if args.input and Path(args.input).is_file():
        manual_data = json.loads(Path(args.input).read_text(
            encoding="utf-8-sig"))

    # resolucao de fonte: rede gated -> manual fallback OBRIGATORIO
    src = None
    if args.allow_network:
        src = bybit_readonly_source(allow_network=True,
                                    environment=args.environment)
        if src.get("status") != "connected":
            print(f"  rede read-only status={src.get('status')} "
                  f"=> fallback manual")
            if manual_data is not None:
                m = manual_source(manual_data)
                m["manual_fallback"] = True
                m["network_status"] = src.get("status")
                src = m
    if src is None or src.get("status") not in ("connected", "manual"):
        if manual_data is not None:
            src = manual_source(manual_data)
        elif src is None:
            src = manual_source({"account": {}, "positions": []})
            src["note"] = "sem --input e sem rede: conta vazia (informe --input)."

    rep = build_operational_overlay(src["account"], src["positions"], limits,
                                    source_info=src)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")

    es = rep["exposure_summary"]
    print(f"FONTE: {rep['source']} | STATUS: {rep['overall_status']} | "
          f"readiness={rep['readiness']['status']}")
    print(f"exposicao={es['exposure_pct']} lev={es['effective_leverage']} "
          f"posicoes={es['open_positions']} day_pnl=US${es['day_pnl_usd']}")
    print(f"BLOCKERS ({len(rep['blockers'])}):")
    for b in rep["blockers"]:
        print(f"  [{b['severity'].upper()}] {b['code']} ({b['scope']}) "
              f"=> {b['recommendation']}")
    if not rep["blockers"]:
        print("  (nenhum blocker)")
    print(f"real_execution_allowed={rep['real_execution_allowed']} "
          f"orders_emitted={rep['orders_emitted']} demo_blocked="
          f"{rep['demo_blocked']} live_blocked={rep['live_blocked']}")
    print(f"relatorio: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
