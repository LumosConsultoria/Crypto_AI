#!/usr/bin/env python
"""
run_strategy_parameter_advisor.py - FASE 29.x research CLI
============================================================
ASCII-only. 100% OFFLINE. ZERO network. ZERO order. ZERO secret.

Avalia grids de parametros LONG/SHORT sobre candles historicos e
sugere manter/ajustar/trocar. NUNCA altera execucao real, NUNCA
envia ordem, NUNCA chama API.

Fontes de candles (offline):
    --from-csv <path>      CSV local de candles (load_candles_from_csv).
    --synthetic            gera candles sinteticos determinISTIcos
                           (research only; nao representa mercado real).

Exemplo:
    python scripts/run_strategy_parameter_advisor.py `
        --symbol BTCUSDT --timeframe 1m `
        --from-csv data/historical/BTCUSDT_1.csv `
        --capital 5000 `
        --output reports/strategy_advisor_BTCUSDT.json

    python scripts/run_strategy_parameter_advisor.py `
        --symbol BTCUSDT --timeframe 1m --synthetic `
        --capital 5000

Exit codes:
    0 = advisor rodou (independente da recomendacao)
    1 = input invalido / falha ao carregar candles
    2 = erro inesperado
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
    "authorization:", "origin_string",
)


def _banner() -> None:
    print()
    print("=" * 72)
    print("  STRATEGY PARAMETER ADVISOR (RESEARCH / OFFLINE)")
    print("  NO network. NO order. NO real execution change.")
    print("  Suggestion only; operator approves manually.")
    print("=" * 72)
    print()


def _footer() -> None:
    print()
    print("=" * 72)
    print("  END.")
    print("=" * 72)


def _load_candles(args) -> list:
    """Carrega candles de CSV local OU gera sinteticos. Sem rede."""
    if args.from_csv:
        from crypto_trading_bot.backtesting.backtest_data import (
            load_candles_from_csv,
        )
        path = Path(args.from_csv)
        if any(p == ".." for p in path.parts):
            raise ValueError("--from-csv path contains '..' (rejected)")
        if not path.is_file():
            raise FileNotFoundError(f"csv not found: {args.from_csv}")
        return load_candles_from_csv(
            path=path, symbol=args.symbol, timeframe=args.timeframe,
        )
    # synthetic
    from crypto_trading_bot.backtesting.backtest_data import (
        generate_trending_candles,
    )
    n = int(args.synthetic_candles)
    # generate_trending_candles espera timeframe numerico (minutos).
    # Normaliza "1m"->"1", "15m"->"15"; mantem ja-numericos.
    tf = _timeframe_to_minutes_str(args.timeframe)
    return generate_trending_candles(
        n=n, base_price=60000.0,
        trend_pct_per_candle=0.0012, volatility_pct=0.008,
        symbol=args.symbol, timeframe=tf,
    )


def _timeframe_to_minutes_str(timeframe: str) -> str:
    """Normaliza timeframe para string de minutos (synthetic only)."""
    tf = str(timeframe).strip().lower()
    if tf.isdigit():
        return tf
    if tf.endswith("m") and tf[:-1].isdigit():
        return tf[:-1]
    if tf.endswith("h") and tf[:-1].isdigit():
        return str(int(tf[:-1]) * 60)
    # Default conservador: 1 minuto.
    return "1"


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Strategy Parameter Advisor (research/offline). Suggests "
            "LONG/SHORT params; never changes real execution."
        ),
    )
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    parser.add_argument("--timeframe", type=str, default="1m")
    parser.add_argument(
        "--strategy", type=str, default="trend_pullback",
        help="Strategy NAME under analysis (current). Advisor candidate "
             "is always trend_pullback_bidirectional.",
    )
    parser.add_argument(
        "--from-csv", type=str, default="",
        help="Local CSV path of candles. If absent, use --synthetic.",
    )
    parser.add_argument(
        "--synthetic", action="store_true",
        help="Generate deterministic synthetic candles (research only).",
    )
    parser.add_argument(
        "--synthetic-candles", type=int, default=400,
        help="Number of synthetic candles when --synthetic.",
    )
    parser.add_argument(
        "--lookback-days", type=int, default=30,
        help="Informational only in this offline CLI.",
    )
    parser.add_argument("--capital", type=float, default=5000.0)
    parser.add_argument("--min-candles", type=int, default=60)
    parser.add_argument("--output", type=str, default="")
    # FASE 33 - perfil (metadata consultiva) + comparacao de estrategias
    parser.add_argument(
        "--profile", type=str, default="",
        help="Perfil operacional (FASE 31) incluido no JSON do report.",
    )
    parser.add_argument(
        "--compare-strategies", action="store_true",
        help="Compara estrategias registradas (config default).",
    )
    args = parser.parse_args(argv)

    _banner()

    if not args.from_csv and not args.synthetic:
        print(
            "  ERROR provide --from-csv <path> OR --synthetic "
            "(offline sources only)."
        )
        _footer()
        return 1
    if args.capital <= 0:
        print("  ERROR --capital must be > 0")
        _footer()
        return 1

    try:
        candles = _load_candles(args)
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR loading candles: {type(e).__name__}: {str(e)[:160]}")
        _footer()
        return 1

    if not candles:
        print("  ERROR no candles loaded")
        _footer()
        return 1

    from crypto_trading_bot.research.strategy_parameter_advisor import (
        run_parameter_advisor,
    )

    print(f"  Symbol:       {args.symbol}")
    print(f"  Timeframe:    {args.timeframe}")
    print(f"  Candles:      {len(candles)}")
    print(f"  Current:      {args.strategy}")
    print(f"  Capital:      {args.capital}")
    print()
    print("  Running parameter grids (LONG + SHORT) - may take a moment...")

    try:
        report = run_parameter_advisor(
            candles=candles, symbol=args.symbol, timeframe=args.timeframe,
            current_strategy=args.strategy,
            initial_capital=float(args.capital),
            min_candles=int(args.min_candles),
            profile=args.profile,
            include_strategy_comparison=bool(args.compare_strategies),
        )
    except Exception as e:  # noqa: BLE001
        print(f"  ERROR advisor failed: {type(e).__name__}: {str(e)[:160]}")
        _footer()
        return 2

    print()
    print(report.human_summary())

    _maybe_write_output(args.output, report.to_dict())

    _footer()
    return 0


def _maybe_write_output(path: str, payload: dict) -> None:
    if not path:
        return
    out_path = Path(path)
    if any(p == ".." for p in out_path.parts):
        print("  ERROR --output path contains '..' (rejected)")
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    lower = text.lower()
    for tok in _SECRET_TOKENS:
        if tok in lower:
            print("  ERROR refusing to write output: suspicious token found")
            return
    out_path.write_text(text, encoding="utf-8")
    print(f"  Report written to: {path}")


if __name__ == "__main__":
    sys.exit(main())
