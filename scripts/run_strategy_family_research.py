#!/usr/bin/env python
"""
run_strategy_family_research.py - Strategy Family Research (FASE 38)
====================================================================
ASCII-only. 100% OFFLINE. ZERO rede / ordem / API / secret.

Descobre, no dataset real, se ha INDICIO de edge por REGIME de mercado
nas estrategias atuais e em 2 familias research-only (mean_reversion,
volatility_contraction_expansion). Trade-tagging (principal) + segmentos
(cross-check) + walk-forward + custo rotulado. Recomendacao CONSULTIVA:
continuar_pesquisa | rejeitar_familia | promover_para_calibracao.

⚠️  Demo SEMPRE BLOQUEADA. NAO baixa o piso 0.005. NAO afrouxa
    RiskEngine/ModeGuard. NAO envia ordem. NAO chama API. NAO autoaplica.
    Prototipos research-only NAO entram no registry operacional.

Exemplo:
    python scripts/run_strategy_family_research.py `
        --from-csv data/historical/BTCUSDT/15m/BTCUSDT_15m.csv `
        --symbol BTCUSDT --timeframe 15m `
        --start-date 2025-12-01 --end-date 2026-05-31 `
        --walk-forward-folds 5 --output reports/family_research.json
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
        description="Strategy Family Research + Regime Discovery (offline).")
    p.add_argument("--from-csv", dest="from_csv", type=str, required=True)
    p.add_argument("--symbol", type=str, default="BTCUSDT")
    p.add_argument("--timeframe", type=str, default="15m")
    p.add_argument("--start-date", dest="start_date", type=str, default="")
    p.add_argument("--end-date", dest="end_date", type=str, default="")
    p.add_argument("--max-candles", dest="max_candles", type=int, default=0)
    p.add_argument("--families", type=str, default="",
                   help="CSV de familias; vazio = todas (atuais+2 proto).")
    p.add_argument("--capital", type=float, default=5000.0)
    p.add_argument("--min-candles", dest="min_candles", type=int,
                   default=60)
    p.add_argument("--regime-lookback", dest="regime_lookback", type=int,
                   default=96)
    p.add_argument("--walk-forward-folds", dest="wf_folds", type=int,
                   default=5)
    p.add_argument("--no-segments", dest="no_segments",
                   action="store_true")
    p.add_argument("--fees-bps", dest="fees_bps", type=float, default=None)
    p.add_argument("--slippage-bps", dest="slippage_bps", type=float,
                   default=None)
    p.add_argument("--spread-bps", dest="spread_bps", type=float,
                   default=None)
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
    )
    from crypto_trading_bot.research.strategy_family_research import (
        FamilyResearchError,
        run_family_research,
    )

    print()
    print("=" * 72)
    print("  STRATEGY FAMILY RESEARCH (FASE 38) - OFFLINE / CONSULTIVO")
    print("  ZERO ordem/API. Piso 0.005 intacto. Demo BLOQUEADA.")
    print("=" * 72)

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
    if candles is None:
        return 1
    if not candles:
        print("  ERROR nenhum candle no range solicitado.")
        return 1
    if args.max_candles and args.max_candles > 0 and \
            len(candles) > args.max_candles:
        candles = candles[-args.max_candles:]
    if len(candles) != n0:
        print(f"  recorte: {n0} -> {len(candles)} candles")

    cost_config = None
    if any(v is not None for v in (
            args.fees_bps, args.slippage_bps, args.spread_bps)):
        cost_config = build_cost_scenario(
            "operator_override", fees_bps=args.fees_bps,
            slippage_bps=args.slippage_bps,
            spread_bps=args.spread_bps).config

    families = ([f.strip() for f in args.families.split(",") if f.strip()]
                if args.families.strip() else None)

    print(f"  candles={len(candles)} | regime_lookback="
          f"{args.regime_lookback} | wf_folds={args.wf_folds} | "
          f"segments={'OFF' if args.no_segments else 'ON'}")
    print("  (Ctrl+C aborta; nada autoaplicado.)")
    print()

    def _progress(msg: str) -> None:
        if not args.quiet:
            print(f"  ... {msg}")

    try:
        report = run_family_research(
            candles, families=families, capital=args.capital,
            min_candles=args.min_candles, symbol=args.symbol,
            timeframe=args.timeframe, data_source="real",
            regime_lookback=args.regime_lookback, wf_folds=args.wf_folds,
            cost_config=cost_config, run_segments=not args.no_segments,
            progress=_progress)
    except FamilyResearchError as e:
        print(f"  ERROR pesquisa: {e}")
        return 1
    except KeyboardInterrupt:
        print()
        print("  >> Interrompido (Ctrl+C). Nada autoaplicado.")
        return 130

    _print_report(report)
    if args.output:
        _write(args.output, report.to_dict())
    return 0


class _CliError(Exception):
    pass


def _slice_by_date(candles, start_date: str, end_date: str):
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
        return None
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
    print("  DISTRIBUICAO DE REGIMES:")
    for reg, cov in sorted(d["regime_distribution"].items(),
                          key=lambda kv: -kv[1]):
        cnt = d["regime_counts"].get(reg, 0)
        print(f"    - {reg:<16} {cov * 100:5.1f}%  ({cnt})")
    for f in d["families"]:
        o = f["overall"]
        tag = "PROTOTIPO" if f["is_prototype"] else "atual"
        print()
        print(f"  === {f['family']} ({tag}) ===")
        print(f"    overall: trades={o['trades']} pf={_fmt(o['profit_factor'])}"
              f" exp={_fmt(o['expectancy_usd'])} "
              f"dd%={_fmt(o['max_drawdown_pct'])} "
              f"pnl={_fmt(o['total_pnl_usd'])}")
        if f["overall_blocked_reasons"]:
            print(f"    blocked: {f['overall_blocked_reasons']}")
        print("    por regime (trade-tagging):")
        for m in f["per_regime_tagging"]:
            print(f"      - {m['regime']:<16} trades={m['trades']:<4} "
                  f"pf={_fmt(m['profit_factor'])} "
                  f"exp={_fmt(m['expectancy_usd'])} "
                  f"dd%={_fmt(m['max_drawdown_pct'])} "
                  f"suf={m['sample_sufficient']}")
        if f["per_regime_segments"]:
            print("    cross-check (segmentos):")
            for m in f["per_regime_segments"]:
                print(f"      - {m['regime']:<16} trades={m['trades']:<4} "
                      f"pf={_fmt(m['profit_factor'])} "
                      f"inconcl={m['inconclusive']}")
        w = f["walk_forward"]
        print(f"    walk-forward: in_pf={_fmt(w['in_sample_pf'])} "
              f"oos_pf={_fmt(w['out_of_sample_pf'])} "
              f"stab={_fmt(w['stability'])} "
              f"overfit={w['overfitting_warning']} "
              f"inconcl={w['inconclusive']}")
        print(f"    custo (realistic_research) pnl="
              f"{_fmt(f['cost_realistic_pnl_usd'])} [ILUSTRATIVO]")
        print(f"    RECOMENDACAO: {f['recommendation'].upper()} "
              f"(best_regime={f['best_regime']})")
        print(f"      {f['recommendation_detail']}")
        print(f"    demo_authorized: {f['demo_authorized']}")
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
