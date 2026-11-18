#!/usr/bin/env python
"""
run_strategy_calibration.py - Strategy Calibration Offline (FASE 37.4)
======================================================================
ASCII-only. 100% OFFLINE. ZERO rede / ordem / API / secret.

Calibra e AVALIA variacoes LIMITADAS (OFAT) de estrategias usando o
backtest corrigido como baseline, com cost realism ROTULADO e
walk-forward. Gera recomendacao CONSULTIVA: manter | ajustar | rejeitar |
manual_review | bloquear_demo.

⚠️  NAO baixa o piso 0.005. NAO afrouxa RiskEngine/ModeGuard. NAO envia
    ordem. NAO chama API. NAO autoaplica parametros. O resultado NUNCA
    autoriza demo (demo continua BLOQUEADA, dependente de gates/V1-V12/
    readiness/decisao humana).

Fonte: --from-csv (CSV canonico real). Recorte por data UTC opcional.

Exemplo:
    python scripts/run_strategy_calibration.py `
        --from-csv data/historical/BTCUSDT/15m/BTCUSDT_15m.csv `
        --symbol BTCUSDT --timeframe 15m `
        --start-date 2025-12-01 --end-date 2026-05-31 `
        --candidate trend_pullback_bidirectional `
        --secondary volatility_breakout `
        --capital 5000 --walk-forward-folds 5 --output reports/calib.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))

_SECRET_TOKENS = (
    "api_key", "api_secret", "bearer ", "x-bapi", "sign=",
    "authorization:",
)


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(
        description="Strategy Calibration offline (consultivo).")
    p.add_argument("--from-csv", dest="from_csv", type=str, required=True)
    p.add_argument("--symbol", type=str, default="BTCUSDT")
    p.add_argument("--timeframe", type=str, default="15m")
    p.add_argument("--start-date", dest="start_date", type=str, default="")
    p.add_argument("--end-date", dest="end_date", type=str, default="")
    p.add_argument("--max-candles", dest="max_candles", type=int, default=0)
    p.add_argument("--candidate", type=str,
                   default="trend_pullback_bidirectional")
    p.add_argument("--secondary", type=str, default="volatility_breakout")
    p.add_argument("--capital", type=float, default=5000.0)
    p.add_argument("--min-candles", dest="min_candles", type=int,
                   default=60)
    p.add_argument("--walk-forward-folds", dest="wf_folds", type=int,
                   default=5)
    p.add_argument("--top-n", dest="top_n", type=int, default=3)
    p.add_argument("--no-precompute", dest="no_precompute",
                   action="store_true")
    # Override de custos (BPS). Sem isto, usa o sweep rotulado default.
    p.add_argument("--fees-bps", dest="fees_bps", type=float, default=None)
    p.add_argument("--slippage-bps", dest="slippage_bps", type=float,
                   default=None)
    p.add_argument("--spread-bps", dest="spread_bps", type=float,
                   default=None)
    p.add_argument("--entry-latency", dest="entry_latency", type=int,
                   default=0)
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--output", type=str, default="")
    args = p.parse_args(argv)

    from crypto_trading_bot.backtesting import (
        BacktestDataError,
        load_candles_from_csv,
    )
    from crypto_trading_bot.historical_data import normalize_timeframe
    from crypto_trading_bot.research.calibration_costs import (
        build_cost_scenario,
        default_cost_sweep,
    )
    from crypto_trading_bot.research.strategy_calibration import (
        CalibrationError,
        run_calibration,
    )

    print()
    print("=" * 72)
    print("  STRATEGY CALIBRATION (FASE 37.4) - OFFLINE / CONSULTIVO")
    print("  ZERO ordem/API. Piso 0.005 intacto. Demo BLOQUEADA.")
    print("=" * 72)

    # --- candles ---
    path = Path(args.from_csv)
    if any(x == ".." for x in path.parts):
        print("  ERROR --from-csv contem '..'")
        return 1
    try:
        _, tf_min = normalize_timeframe(args.timeframe)
        candles = load_candles_from_csv(
            str(path), symbol=args.symbol, timeframe=str(tf_min))
    except (BacktestDataError, ValueError) as e:
        print(f"  ERROR dados: {e}")
        return 1

    n0 = len(candles)
    candles = _slice_by_date(candles, args.start_date, args.end_date)
    if not candles:
        print("  ERROR nenhum candle no range solicitado.")
        return 1
    if args.max_candles and args.max_candles > 0 and \
            len(candles) > args.max_candles:
        candles = candles[-args.max_candles:]
    if len(candles) != n0:
        print(f"  recorte: {n0} -> {len(candles)} candles")

    # --- cost scenarios ---
    if any(v is not None for v in (
            args.fees_bps, args.slippage_bps, args.spread_bps)):
        scenarios = [
            build_cost_scenario("zero_cost"),
            build_cost_scenario(
                "operator_override", fees_bps=args.fees_bps,
                slippage_bps=args.slippage_bps, spread_bps=args.spread_bps,
                entry_latency_candles=args.entry_latency),
        ]
    else:
        scenarios = default_cost_sweep(
            entry_latency_candles=args.entry_latency)

    data_source = "real"
    print(f"  candidate={args.candidate} | secondary={args.secondary}")
    print(f"  candles={len(candles)} | wf_folds={args.wf_folds} | "
          f"precompute={'OFF' if args.no_precompute else 'ON'}")
    print("  (Ctrl+C aborta; nada autoaplicado.)")
    print()

    def _progress(msg: str) -> None:
        if not args.quiet:
            print(f"  ... {msg}")

    try:
        report = run_calibration(
            candles, candidate=args.candidate, secondary=args.secondary,
            capital=args.capital, min_candles=args.min_candles,
            symbol=args.symbol, timeframe=args.timeframe,
            data_source=data_source, cost_scenarios=scenarios,
            walk_forward_folds=args.wf_folds, top_n_followup=args.top_n,
            precompute=not args.no_precompute, progress=_progress)
    except CalibrationError as e:
        print(f"  ERROR calibracao: {e}")
        return 1
    except KeyboardInterrupt:
        print()
        print("  >> Interrompido pelo operador (Ctrl+C). Nada autoaplicado.")
        return 130

    _print_report(report)
    if args.output:
        _write(args.output, report.to_dict())
    return 0


class _CliError(Exception):
    pass


def _slice_by_date(candles, start_date: str, end_date: str):
    """Recorta por [start, end] UTC; end date-only = dia inteiro inclusivo."""
    def _parse(v: str):
        v = v.strip()
        if not v:
            return None, False
        for fmt, donly in (("%Y-%m-%d", True),
                           ("%Y-%m-%dT%H:%M:%S", False),
                           ("%Y-%m-%dT%H:%M:%SZ", False)):
            try:
                return (datetime.strptime(v, fmt)
                        .replace(tzinfo=timezone.utc), donly)
            except ValueError:
                continue
        raise _CliError(f"data invalida: {v!r}")

    try:
        start, _ = _parse(start_date)
        end_dt, donly = _parse(end_date)
    except _CliError as e:
        print(f"  ERROR {e}")
        return []
    end_excl = None
    if end_dt is not None:
        end_excl = end_dt + timedelta(days=1) if donly else end_dt
    if start is None and end_excl is None:
        return candles

    def _keep(c):
        ts = getattr(c, "timestamp", None)
        if ts is None:
            return True
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if start is not None and ts < start:
            return False
        if end_excl is not None and ts >= end_excl:
            return False
        return True

    return [c for c in candles if _keep(c)]


def _fmt(v) -> str:
    return "-" if v is None else (
        f"{v:.4f}" if isinstance(v, float) else str(v))


def _print_report(rep) -> None:
    d = rep.to_dict()
    print()
    print(f"  symbol/timeframe: {d['symbol']} {d['timeframe']}")
    print(f"  rows: {d['rows']} ({d['first_timestamp']}.."
          f"{d['last_timestamp']}) source={d['data_source']}")
    print(f"  demo_blocked: {d['demo_blocked']}  (CONSULTIVO)")
    for s in d["strategies"]:
        b = s["baseline"]["metrics"]
        print()
        print(f"  === {s['strategy']} "
              f"({'CANDIDATO' if s['is_candidate'] else 'secundaria'}) ===")
        print(f"    baseline: trades={b['total_trades']} "
              f"pf={_fmt(b['profit_factor'])} "
              f"exp={_fmt(b['expectancy_usd'])} "
              f"dd%={_fmt(b['max_drawdown_pct'])} "
              f"pnl={_fmt(b['total_pnl_usd'])} "
              f"payoff={_fmt(b['payoff'])}")
        if b["blocked_reasons_summary"]:
            print(f"    baseline blocked: {b['blocked_reasons_summary']}")
        # melhores variantes (selecionadas)
        sel = set(s["selected_for_followup"])
        print("    variantes (selecionadas p/ follow-up):")
        for v in s["variants"]:
            if v["name"] in sel:
                m = v["metrics"]
                print(f"      - {v['name']:<34} pf={_fmt(m['profit_factor'])}"
                      f" exp={_fmt(m['expectancy_usd'])} "
                      f"dd%={_fmt(m['max_drawdown_pct'])} "
                      f"trades={m['total_trades']}")
        # walk-forward
        print("    walk-forward:")
        for w in s["walk_forward"]:
            print(f"      - {w['variant_name']:<34} in_pf={_fmt(w['in_sample_pf'])}"
                  f" oos_pf={_fmt(w['out_of_sample_pf'])} "
                  f"stab={_fmt(w['stability'])} "
                  f"overfit={w['overfitting_warning']} "
                  f"inconcl={w['inconclusive']}")
        # cost sweep (resumo por cenario do baseline)
        print("    cost sweep (baseline):")
        for r in s["cost_sweep"]:
            if r["variant_name"] == "baseline":
                m = r["metrics"]
                tag = "ILUSTRATIVO" if r["is_research_illustrative"] else ""
                print(f"      - {r['scenario']:<20} pnl={_fmt(m['total_pnl_usd'])}"
                      f" pf={_fmt(m['profit_factor'])} {tag}")
        print(f"    RECOMENDACAO: {s['recommendation'].upper()}")
        print(f"      {s['recommendation_detail']}")
        if s["suggested_config"]:
            print(f"      suggested_config (CONSULTIVO): {s['suggested_config']}")
        print(f"    demo_authorized: {s['demo_authorized']} | "
              f"gate_satisfied: {s['demo_gate_satisfied']}")
        print(f"      {s['demo_block_reason']}")
    print()
    print("  NOTAS:")
    for note in d["notes"]:
        print(f"    - {note}")


def _write(path: str, payload: dict) -> None:
    out = Path(path)
    if any(x == ".." for x in out.parts):
        print("  ERROR --output contem '..'")
        return
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if any(t in text.lower() for t in _SECRET_TOKENS):
        print("  ERROR token suspeito no report; nao gravado")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"  Report written to: {path}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        print("  >> Interrompido (Ctrl+C). Nada autoaplicado.")
        sys.exit(130)
