"""
run_risk_overlay (FASE 57, alternativa C) — Risk & Exposure Overlay ADVISORY.
=============================================================================
Le posicoes/conta de um JSON MANUAL (offline; sem rede) e avalia contra o
RiskConfig efetivo (HyroTrader). Emite alertas + recomendacoes. NUNCA envia
ordem; demo/live bloqueados.

Formato do --input (JSON):
{
  "account": {"equity_usd": 4900, "balance_usd": 5000,
              "realized_pnl_today_usd": -50, "day": "2026-06-24"},
  "positions": [
    {"symbol": "BTCUSDT", "side": "long", "notional_usd": 6000,
     "entry_price": 60000, "mark_price": 59500,
     "stop_loss_price": null, "funding_rate": 0.0003}
  ]
}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Risk & Exposure Overlay (advisory)")
    ap.add_argument("--input", required=True, help="JSON com account+positions")
    ap.add_argument("--operator-inputs", default="config/operator_inputs.json")
    ap.add_argument("--output", default="reports/risk_overlay.json")
    args = ap.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from loguru import logger
    logger.disable("crypto_trading_bot")
    from crypto_trading_bot.risk_overlay import (
        AccountState, Position, RiskLimits, evaluate_risk_overlay)

    data = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
    acc_d = data.get("account", {})
    account = AccountState(
        equity_usd=float(acc_d.get("equity_usd", 0.0)),
        balance_usd=float(acc_d.get("balance_usd", 0.0)),
        realized_pnl_today_usd=float(acc_d.get("realized_pnl_today_usd", 0.0)),
        day=acc_d.get("day"))
    positions = [Position(
        symbol=p["symbol"], side=p.get("side", "long"),
        notional_usd=float(p["notional_usd"]),
        entry_price=float(p["entry_price"]), mark_price=float(p["mark_price"]),
        stop_loss_price=(float(p["stop_loss_price"])
                         if p.get("stop_loss_price") is not None else None),
        unrealized_pnl_usd=(float(p["unrealized_pnl_usd"])
                            if p.get("unrealized_pnl_usd") is not None else None),
        funding_rate=(float(p["funding_rate"])
                      if p.get("funding_rate") is not None else None))
        for p in data.get("positions", [])]

    # limites = RiskConfig EFETIVO (HyroTrader) se operator_inputs disponivel
    limits = RiskLimits()
    try:
        from crypto_trading_bot.operator_inputs.store import OperatorInputStore
        from crypto_trading_bot.research.effective_config import (
            build_effective_config)
        store = (OperatorInputStore(args.operator_inputs)
                 if Path(args.operator_inputs).is_file() else None)
        eff = build_effective_config(store=store)
        rc = eff.risk_config
        ext = eff.external_ceilings
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
    except Exception as e:  # noqa: BLE001  (fallback aos defaults HyroTrader 5k)
        print(f"  (limites default; effective_config indisponivel: "
              f"{type(e).__name__})")

    rep = evaluate_risk_overlay(account, positions, limits)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")

    es = rep["exposure_summary"]
    print(f"STATUS: {rep['overall_status']} | posicoes={es['open_positions']} "
          f"exposicao={es['exposure_pct']} lev={es['effective_leverage']} "
          f"risco_total=US${es['total_risk_to_stop_usd']} "
          f"day_pnl=US${es['day_pnl_usd']}")
    print(f"alertas ({rep['severity_counts']}):")
    for a in rep["alerts"]:
        print(f"  [{a['severity'].upper():8}] {a['code']} ({a['scope']})")
        print(f"      {a['message']}")
        print(f"      => {a['recommendation']}")
    if not rep["alerts"]:
        print("  (nenhum alerta; risco dentro das regras)")
    print(f"\nADVISORY (sem ordem; demo/live bloqueados). relatorio: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
