#!/usr/bin/env python
"""
run_regime_window_analysis.py - Regime Window Analysis (FASE 39)
================================================================
ASCII-only. 100% OFFLINE. ZERO rede / ordem / API / secret / download.

Analise TEMPORAL multi-janela do dataset real JA disponivel: full_period
+ meses-calendario + janelas de referencia (FASE 38). Params FIXOS, sem
tuning. Emite estabilidade por (familia x regime), verdict do
mean_reversion-in-range, backlog de hipoteses (papel) e recomendacao
CONSULTIVA. Demo SEMPRE BLOQUEADA.

⚠️  NAO baixa dados. NAO afrouxa RiskEngine/ModeGuard. Piso 0.005 intacto.
    NAO implementa hipoteses novas. NAO autoriza demo.

Exemplo:
    python scripts/run_regime_window_analysis.py `
        --from-csv data/historical/BTCUSDT/15m/BTCUSDT_15m.csv `
        --symbol BTCUSDT --timeframe 15m `
        --walk-forward-folds 5 --output reports/regime_windows.json
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

# Janelas de referencia da FASE 38 (NAO entram na estatistica de
# estabilidade; apenas comparacao).
_REFERENCE_WINDOWS = [
    ("ref_fase38_6m", "2025-12-01", "2026-05-31"),
    ("ref_2026_04_05", "2026-04-01", "2026-05-31"),
]


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(
        description="Regime Window Analysis (offline, consultivo).")
    p.add_argument("--from-csv", dest="from_csv", type=str, required=True)
    p.add_argument("--symbol", type=str, default="BTCUSDT")
    p.add_argument("--timeframe", type=str, default="15m")
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
    p.add_argument("--no-reference", dest="no_reference",
                   action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--output", type=str, default="")
    args = p.parse_args(argv)

    from crypto_trading_bot.backtesting import (
        BacktestDataError,
        load_candles_from_csv,
    )
    from crypto_trading_bot.historical_data import normalize_timeframe
    from crypto_trading_bot.research.strategy_family_research import (
        FamilyResearchError,
    )
    from crypto_trading_bot.research.regime_window_analysis import (
        run_regime_window_analysis,
    )

    print()
    print("=" * 72)
    print("  REGIME WINDOW ANALYSIS (FASE 39) - OFFLINE / CONSULTIVO")
    print("  ZERO download/ordem/API. Piso 0.005 intacto. Demo BLOQUEADA.")
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

    families = ([f.strip() for f in args.families.split(",") if f.strip()]
                if args.families.strip() else None)
    refs = None if args.no_reference else _REFERENCE_WINDOWS

    print(f"  candles={len(candles)} | wf_folds={args.wf_folds} | "
          f"regime_lookback={args.regime_lookback}")
    print("  (Ctrl+C aborta com relatorio parcial; nada autoaplicado.)")
    print()

    def _progress(msg: str) -> None:
        if not args.quiet:
            print(f"  ... {msg}")

    try:
        report = run_regime_window_analysis(
            candles, families=families, capital=args.capital,
            min_candles=args.min_candles, symbol=args.symbol,
            timeframe=args.timeframe, data_source="real",
            regime_lookback=args.regime_lookback, wf_folds=args.wf_folds,
            reference_windows=refs,
            min_window_candles=args.min_window_candles, progress=_progress)
    except FamilyResearchError as e:
        print(f"  ERROR analise: {e}")
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
    print(f"  symbol/timeframe: {d['symbol']} {d['timeframe']}")
    print(f"  rows: {d['rows']} ({d['first_timestamp']}.."
          f"{d['last_timestamp']}) source={d['data_source']}")
    print(f"  demo_blocked: {d['demo_blocked']} | demo_authorized: "
          f"{d['demo_authorized']} | partial: {d['partial']}")

    if d["full_period"]:
        print()
        print("  FULL_PERIOD:")
        _print_window(d["full_period"])

    print()
    print("  MONTHLY_WINDOWS:")
    for w in d["monthly_windows"]:
        evaluated = "" if w["families"] else " (curto: so distribuicao)"
        print(f"    {w['label']} rows={w['rows']}{evaluated} "
              f"regimes={_top_regimes(w['regime_distribution'])}")
        for f in w["families"]:
            print(f"        {f['family']:<38} reco={f['recommendation']} "
                  f"trades={f['overall_trades']}")

    if d["reference_windows"]:
        print()
        print("  REFERENCE_WINDOWS (comparacao; fora da estatistica):")
        for w in d["reference_windows"]:
            print(f"    {w['label']} rows={w['rows']}")
            for f in w["families"]:
                print(f"        {f['family']:<38} reco="
                      f"{f['recommendation']} trades={f['overall_trades']}")

    print()
    print("  ESTABILIDADE CROSS-MES (so monthly_windows):")
    for s in d["stability"]:
        print(f"    {s['family']:<38} {s['regime']:<12} "
              f"meses={s['n_months']} suf={s['n_sample_sufficient']} "
              f"mean_pf={_fmt(s['mean_pf'])} "
              f"mean_exp={_fmt(s['mean_expectancy'])} "
              f"sign_cons={_fmt(s['sign_consistency'])}")

    mr = d["mean_reversion_range_verdict"]
    if mr:
        print()
        print(f"  MEAN_REVERSION-IN-RANGE VERDICT: {mr['verdict'].upper()}")
        print(f"    full: trades={mr['full_period_trades']} "
              f"pf={_fmt(mr['full_period_pf'])} "
              f"exp={_fmt(mr['full_period_expectancy'])} "
              f"suf={mr['full_period_sample_sufficient']} | "
              f"sign_cons={_fmt(mr['monthly_sign_consistency'])} | "
              f"window_sensitive={mr['window_sensitive']}")
        print(f"    {mr['detail']}")

    print()
    print(f"  DECISAO CONSULTIVA: {d['decision'].upper()}")
    print(f"    {d['decision_detail']}")
    print()
    print("  BACKLOG DE HIPOTESES (PAPEL; nao implementado):")
    for h in d["hypothesis_backlog"]:
        print(f"    - {h['hypothesis']} [{h['target_regime']}] "
              f"prioridade={h['suggested_priority']}")
    print()
    print("  NOTAS:")
    for note in d["notes"]:
        print(f"    - {note}")


def _top_regimes(dist: dict) -> str:
    top = sorted(dist.items(), key=lambda kv: -kv[1])[:3]
    return ", ".join(f"{k}={v * 100:.0f}%" for k, v in top)


def _print_window(w: dict) -> None:
    print(f"    rows={w['rows']} regimes={_top_regimes(w['regime_distribution'])}")
    for f in w["families"]:
        print(f"      {f['family']:<38} reco={f['recommendation']} "
              f"trades={f['overall_trades']} pf={_fmt(f['overall_pf'])} "
              f"exp={_fmt(f['overall_expectancy'])}")


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
