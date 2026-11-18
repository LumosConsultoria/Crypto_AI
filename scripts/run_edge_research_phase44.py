#!/usr/bin/env python
"""
run_edge_research_phase44.py - Strategy Edge Research (FASE 44)
==============================================================
ASCII-only. 100% OFFLINE (le CSVs canonicos locais; sem rede/ordem/secret).
Orquestra a pesquisa de edge: H1 (tendencia c/ expansao de vol) e H2
(reversao em range), 5m primario + 15m controle, variante HTF (gate de
regime 15m) so no 5m, segmentos DEV/VAL/OOS, custo realista principal +
zero (diag) + stressed (robustez), walk-forward, mensal, regime,
concentracao, IC bootstrap, sensibilidade, baseline. Verdict travado.

NAO promove estrategia automaticamente; demo/live continuam bloqueados.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))


def _canonical(base_dir: str, symbol: str, tf: str) -> Path:
    return Path(base_dir) / symbol.upper() / tf / f"{symbol.upper()}_{tf}.csv"


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(description="Strategy Edge Research FASE 44.")
    p.add_argument("--base-dir", default="data/historical")
    p.add_argument("--symbol", default="BTCUSDT")
    p.add_argument("--tf-primary", default="5m")
    p.add_argument("--tf-control", default="15m")
    p.add_argument("--dev", nargs=2, default=["2025-01-01", "2025-10-01"])
    p.add_argument("--val", nargs=2, default=["2025-10-01", "2026-02-01"])
    p.add_argument("--oos", nargs=2, default=["2026-02-01", "2026-06-01"])
    p.add_argument("--capital", type=float, default=5000.0)
    p.add_argument("--wf-folds", type=int, default=5)
    p.add_argument("--regime-lookback", type=int, default=96)
    p.add_argument("--hypotheses", default="")
    p.add_argument("--no-oos", action="store_true",
                   help="so DEV (diagnostico rapido; nao toca OOS)")
    p.add_argument("--output", default="")
    args = p.parse_args(argv)

    from crypto_trading_bot.backtesting import load_candles_from_csv
    from crypto_trading_bot.research.edge_research_phase44 import (
        run_edge_research,
    )
    # Silencia o logging por-candle do engine (loguru) durante a pesquisa:
    # milhares de linhas/candle dominariam o tempo. Os prints abaixo (print())
    # nao usam loguru e permanecem visiveis.
    from loguru import logger as _loguru
    _loguru.disable("crypto_trading_bot")

    print("=" * 72)
    print("  STRATEGY EDGE RESEARCH (FASE 44) - OFFLINE, sem ordem/rede")
    print("=" * 72)

    c5_path = _canonical(args.base_dir, args.symbol, args.tf_primary)
    c15_path = _canonical(args.base_dir, args.symbol, args.tf_control)
    for path in (c5_path, c15_path):
        if not path.is_file():
            print(f"  ERROR dataset ausente: {path}")
            return 1

    print(f"  carregando {c5_path} ...")
    c5 = load_candles_from_csv(str(c5_path), symbol=args.symbol,
                               timeframe="5")
    print(f"  carregando {c15_path} ...")
    c15 = load_candles_from_csv(str(c15_path), symbol=args.symbol,
                                timeframe="15")
    print(f"  5m candles={len(c5)} | 15m candles={len(c15)}")

    hyps = ([h.strip() for h in args.hypotheses.split(",") if h.strip()]
            or None)
    t0 = time.monotonic()

    def _progress(msg):
        print(f"  [{time.monotonic() - t0:7.1f}s] {msg}")

    try:
        report = run_edge_research(
            c5, c15, symbol=args.symbol, dev=tuple(args.dev),
            val=tuple(args.val), oos=tuple(args.oos), capital=args.capital,
            wf_folds=args.wf_folds, regime_lookback=args.regime_lookback,
            hypotheses=hyps, run_oos=not args.no_oos, progress=_progress)
    except KeyboardInterrupt:
        print("  INTERROMPIDO (Ctrl+C); nada promovido.")
        return 1

    d = report.to_dict()
    print()
    print("-" * 72)
    print(f"  OVERALL VERDICT: {d['overall_verdict']}")
    for h in d["hypotheses"]:
        print(f"    - {h['hypothesis']} ({h['family']}): {h['verdict']} "
              f"[variante 5m: {h.get('chosen_variant_5m')}]")
    print(f"  strategy_promoted={d['strategy_promoted']} | "
          f"demo_blocked={d['demo_blocked']} | live_blocked={d['live_blocked']}")
    print(f"  elapsed={time.monotonic() - t0:.1f}s")
    print("-" * 72)

    out = args.output or (
        f"reports/edge_research_phase44_{args.symbol.lower()}.json")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(d, indent=2, sort_keys=True,
                                    default=str), encoding="utf-8")
    print(f"  Report written to: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
