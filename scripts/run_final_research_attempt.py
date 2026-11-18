#!/usr/bin/env python
"""
run_final_research_attempt.py - FASE 40 (Final Research Attempt)
================================================================
ASCII-only. RESEARCH-ONLY. ZERO ordem / API privada / secret / demo.

Avalia a hipotese range_mean_reversion_vwap_bollinger (BIDIRECIONAL no
backtest; short SIMULADO) em multiplos timeframes, comparando por
ROBUSTEZ (nao por PnL). 15m local; 5m pode ser obtido via fetcher
PUBLICO read-only (FASE 37) SOMENTE com --fetch-missing-data
--allow-network. data_readiness obrigatorio; usa so se ready.

⚠️  Demo SEMPRE BLOQUEADA (baixar dados NAO libera demo). Piso 0.005/
    RiskEngine/ModeGuard intactos. Prototipo fora do registry operacional.
    Sem overwrite de dataset sem --force.

O usuario escolhe: --symbol --timeframes --start-date --end-date
--base-dir --families.

Exemplo (15m local; 5m gated):
    python scripts/run_final_research_attempt.py `
        --symbol BTCUSDT --timeframes 15m,5m `
        --start-date 2025-01-01 --end-date 2026-05-31 `
        --fetch-missing-data --allow-network `
        --walk-forward-folds 5 --output reports/fase40.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))

_SECRET_TOKENS = (
    "api_key", "api_secret", "bearer ", "x-bapi", "sign=",
    "authorization:",
)

_REFERENCE_WINDOWS = [
    ("ref_fase38_6m", "2025-12-01", "2026-05-31"),
    ("ref_2026_04_05", "2026-04-01", "2026-05-31"),
]


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(
        description="FASE 40 final research attempt (offline/consultivo).")
    p.add_argument("--symbol", type=str, default="BTCUSDT")
    p.add_argument("--timeframes", type=str, default="15m,5m")
    p.add_argument("--start-date", dest="start_date", type=str,
                   default="2025-01-01")
    p.add_argument("--end-date", dest="end_date", type=str,
                   default="2026-05-31")
    p.add_argument("--base-dir", dest="base_dir", type=str,
                   default="data/historical")
    p.add_argument("--families", type=str, default="")
    p.add_argument("--capital", type=float, default=5000.0)
    p.add_argument("--min-candles", dest="min_candles", type=int,
                   default=60)
    p.add_argument("--regime-lookback", dest="regime_lookback", type=int,
                   default=96)
    p.add_argument("--walk-forward-folds", dest="wf_folds", type=int,
                   default=5)
    p.add_argument("--min-window-candles", dest="min_window_candles",
                   type=int, default=200)
    p.add_argument("--fetch-missing-data", dest="fetch_missing",
                   action="store_true")
    p.add_argument("--allow-network", dest="allow_network",
                   action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--no-reference", dest="no_reference",
                   action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--output", type=str, default="")
    args = p.parse_args(argv)

    from crypto_trading_bot.research.timeframe_research import (
        TimeframeResearchError,
        run_final_research,
    )

    print()
    print("=" * 72)
    print("  FINAL RESEARCH ATTEMPT (FASE 40) - RESEARCH-ONLY")
    print("  Hipotese: range_mean_reversion_vwap_bollinger (bidirecional).")
    print("  ZERO ordem/API privada. Piso 0.005 intacto. Demo BLOQUEADA.")
    print("=" * 72)

    timeframes = [t.strip() for t in args.timeframes.split(",")
                  if t.strip()]
    families = ([f.strip() for f in args.families.split(",") if f.strip()]
                if args.families.strip() else None)
    refs = None if args.no_reference else _REFERENCE_WINDOWS

    if args.fetch_missing and not args.allow_network:
        print("  NOTE --fetch-missing-data exige --allow-network; sem ela "
              "datasets ausentes ficam gated_missing_dataset.")
    print(f"  symbol={args.symbol} timeframes={timeframes} "
          f"range={args.start_date}..{args.end_date}")
    print(f"  fetch_missing={args.fetch_missing} "
          f"allow_network={args.allow_network} force={args.force}")
    print("  (Ctrl+C aborta; nada autoaplicado.)")
    print()

    def _progress(msg: str) -> None:
        if not args.quiet:
            print(f"  ... {msg}")

    try:
        report = run_final_research(
            symbol=args.symbol, timeframes=timeframes,
            start_date=args.start_date, end_date=args.end_date,
            base_dir=args.base_dir, families=families,
            capital=args.capital, min_candles=args.min_candles,
            regime_lookback=args.regime_lookback, wf_folds=args.wf_folds,
            reference_windows=refs, fetch_missing=args.fetch_missing,
            allow_network=args.allow_network, force=args.force,
            provider_name="binance", min_window_candles=args.min_window_candles,
            progress=_progress)
    except TimeframeResearchError as e:
        print(f"  ERROR: {e}")
        return 1
    except KeyboardInterrupt:
        print()
        print("  >> Interrompido (Ctrl+C). Nada autoaplicado.")
        return 130

    _print_report(report)
    if args.output:
        _write(args.output, report.to_dict())
    return 0


def _fmt(v) -> str:
    return "-" if v is None else (
        f"{v:.4f}" if isinstance(v, float) else str(v))


def _print_report(rep) -> None:
    d = rep.to_dict()
    print()
    print(f"  symbol: {d['symbol']} | focus_family: {d['focus_family']}")
    print(f"  demo_blocked: {d['demo_blocked']} | demo_authorized: "
          f"{d['demo_authorized']} | timeframe_sensitive: "
          f"{d['timeframe_sensitive']}")
    print()
    print("  POR TIMEFRAME:")
    for t in d["timeframes"]:
        ds = t["dataset"]
        print(f"    [{t['timeframe']}] dataset={ds['status']} "
              f"readiness={ds['readiness_status']} rows={ds['rows']}")
        if ds.get("note"):
            print(f"        note: {ds['note']}")
        if t["evaluated"]:
            wr = t["window_report"]
            print(f"        full_period regimes="
                  f"{_top_regimes(wr['full_period']['regime_distribution'])}")
            for f in wr["full_period"]["families"]:
                print(f"          {f['family']:<48} reco="
                      f"{f['recommendation']} trades={f['overall_trades']} "
                      f"pf={_fmt(f['overall_pf'])} "
                      f"exp={_fmt(f['overall_expectancy'])}")
            print(f"        focus_verdict={t['focus_verdict']} "
                  f"focus_decision={t['focus_decision']}")
    print()
    print(f"  DECISAO FINAL: {d['decision'].upper()}")
    print(f"    {d['decision_detail']}")
    print()
    print("  NOTAS:")
    for note in d["notes"]:
        print(f"    - {note}")


def _top_regimes(dist: dict) -> str:
    top = sorted(dist.items(), key=lambda kv: -kv[1])[:3]
    return ", ".join(f"{k}={v * 100:.0f}%" for k, v in top)


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
