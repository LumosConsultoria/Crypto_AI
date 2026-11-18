#!/usr/bin/env python
"""
run_sl_calibration_advisor.py - Calibracao SL x piso (FASE 36)
===============================================================
ASCII-only. 100% OFFLINE. ZERO rede, ZERO ordem, ZERO secret.

Compara os 3 caminhos (conservador/moderado/arrojado) para o
desalinhamento SL x piso do RiskEngine observado na demo 3.

Fontes de candle:
    --from-csv <path>   dados REAIS locais (load_candles_from_csv).
    --synthetic         candles sinteticos (mecanismo; NAO performance).
    --low-vol           sintetico calibrado p/ baixa vol (reproduz a
                        demo 3: ATR ~0.3%).

NAO busca dado por API. Se faltar dado real, roda em sintetico e
ROTULA claramente que metricas de trade sao ilustrativas.

Exemplo:
    python scripts/run_sl_calibration_advisor.py --synthetic --low-vol `
        --output reports/sl_calibration.json
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


def _banner() -> None:
    print()
    print("=" * 72)
    print("  SL CALIBRATION ADVISOR (FASE 36) - OFFLINE")
    print("  NAO baixa o piso. NAO autoaplica. NAO chama API.")
    print("=" * 72)


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(
        description="SL x piso RiskEngine calibration (offline).",
    )
    p.add_argument("--from-csv", type=str, default="")
    p.add_argument("--synthetic", action="store_true")
    p.add_argument(
        "--low-vol", action="store_true",
        help="Sintetico de baixa vol (reproduz demo 3, ATR ~0.3%).",
    )
    p.add_argument("--symbol", type=str, default="BTCUSDT")
    p.add_argument("--timeframe", type=str, default="15")
    p.add_argument("--synthetic-candles", type=int, default=400)
    p.add_argument("--min-stop-loss-pct", type=float, default=0.005)
    p.add_argument("--position-size-usd", type=float, default=200.0)
    p.add_argument("--risk-reward-ratio", type=float, default=2.0)
    p.add_argument(
        "--max-risk-per-trade-usd", type=float, default=None,
        help="Opcional (operator input V2). Ausente => budget check "
             "PULADO (nunca inventado).",
    )
    p.add_argument("--initial-capital", type=float, default=5000.0)
    p.add_argument("--min-candles", type=int, default=60)
    # FASE 37 Parte G: performance + controle.
    p.add_argument("--start-date", dest="start_date", type=str,
                   default="", help="Recorta candles >= esta data (UTC).")
    p.add_argument("--end-date", dest="end_date", type=str, default="",
                   help="Recorta candles < esta data (UTC).")
    p.add_argument("--max-candles", dest="max_candles", type=int,
                   default=0,
                   help="Limita ao N candles MAIS RECENTES (0 = todos). "
                        "Bound contra O(n^2) do --full-backtest.")
    p.add_argument("--progress-every", dest="progress_every", type=int,
                   default=1, help="Imprime progresso de backtest.")
    p.add_argument("--diagnostic-only", dest="diagnostic_only",
                   action="store_true",
                   help="Apenas analise determinISTIca SL x piso (O(n), "
                        "rapida). NAO roda backtests. (DEFAULT)")
    p.add_argument("--full-backtest", dest="full_backtest",
                   action="store_true",
                   help="Roda os backtests (O(n^2); use --max-candles).")
    p.add_argument("--strategy", type=str,
                   default="trend_pullback_bidirectional")
    p.add_argument("--profile", type=str, default="")
    p.add_argument("--output", type=str, default="")
    args = p.parse_args(argv)

    _banner()

    if not args.from_csv and not args.synthetic:
        print("  ERROR informe --from-csv <path> OU --synthetic")
        return 1

    # --- Validar estrategia contra registry + perfil (sem hardcode) ---
    profile_allowed = None
    if args.profile.strip():
        try:
            from crypto_trading_bot.operational_profile import (
                resolve_profile,
            )
            prof = resolve_profile(
                args.profile.strip(), capital=float(args.initial_capital),
            )
            profile_allowed = prof.allowed_strategies or None
        except ValueError as e:
            print(f"  ERROR profile: {e}")
            return 1
    try:
        from crypto_trading_bot.backtest_operational import (
            resolve_strategy_spec,
            StrategySelectionError,
        )
        resolve_strategy_spec(
            args.strategy, profile_allowed=profile_allowed,
        )
    except StrategySelectionError as e:
        print(f"  ERROR strategy: {e}")
        return 1

    # --- carregar candles (offline) ---
    data_source = "synthetic"
    real_dataset_available = False
    walk_forward_available = False
    if args.from_csv:
        from crypto_trading_bot.backtesting.backtest_data import (
            load_candles_from_csv,
        )
        from crypto_trading_bot.data_readiness import (
            validate_candle_dataset,
        )
        path = Path(args.from_csv)
        if any(x == ".." for x in path.parts):
            print("  ERROR --from-csv contem '..'")
            return 1
        if not path.is_file():
            print(f"  ERROR csv nao encontrado: {args.from_csv}")
            print(
                "  Nenhuma busca por API. Forneca um CSV historico "
                "real (ver scripts/run_data_readiness.py --contract)."
            )
            return 1
        # FASE 36.x: valida o dataset ANTES de calibrar.
        readiness = validate_candle_dataset(
            csv_path=str(path), symbol=args.symbol,
            timeframe=args.timeframe, source="sl_advisor",
        )
        print(f"  Data readiness: status={readiness.readiness_status.value}"
              f" | real_available={readiness.real_dataset_available}"
              f" | blocks_wf={readiness.blocks_walk_forward}")
        if readiness.blocks_backtest:
            print("  BLOCKED dataset nao apto a backtest:")
            for b in readiness.blockers:
                print(f"    - {b}")
            print(
                "  Recomendacoes arrojadas permanecem NAO prontas para "
                "uso real."
            )
            return 1
        real_dataset_available = readiness.real_dataset_available
        walk_forward_available = not readiness.blocks_walk_forward
        candles = load_candles_from_csv(
            path=path, symbol=args.symbol, timeframe=args.timeframe,
        )
        data_source = f"csv:{args.from_csv}"
    else:
        from crypto_trading_bot.backtesting.backtest_data import (
            generate_trending_candles,
        )
        # low-vol calibrado p/ reproduzir a demo 3 (ATR ~0.31%, mult
        # 1.5 abaixo do piso de 0.5%).
        vol = 0.0024 if args.low_vol else 0.008
        candles = generate_trending_candles(
            n=int(args.synthetic_candles), base_price=65000.0,
            trend_pct_per_candle=0.0004, volatility_pct=vol,
            symbol=args.symbol, timeframe=args.timeframe,
        )
        data_source = (
            "synthetic_low_vol" if args.low_vol else "synthetic"
        )
        print(
            "  NOTE candles SINTETICOS: mecanismo, NAO performance. "
            "Walk-forward em dados reais obrigatorio antes de uso real."
        )

    # --- Recorte de candles (range + max-candles) p/ bound O(n^2) ---
    n_before = len(candles)
    candles = _slice_candles(
        candles, args.start_date, args.end_date, args.max_candles,
    )
    if len(candles) != n_before:
        print(f"  recorte aplicado: {n_before} -> {len(candles)} candles "
              f"(range/max-candles)")

    print(f"  data_source: {data_source} | candles: {len(candles)}")

    # Modo: diagnostic-only (default seguro/rapido) vs full-backtest.
    run_backtests = bool(args.full_backtest)
    if args.diagnostic_only and args.full_backtest:
        print("  ERROR use apenas um de --diagnostic-only / --full-backtest")
        return 1
    if run_backtests:
        print(f"  MODO full-backtest (O(n^2)); {len(candles)} candles. "
              "Ctrl+C gera relatorio PARCIAL (nunca silencioso).")
    else:
        print("  MODO diagnostic-only (O(n)): SL x piso determinISTIco, "
              "sem backtests. Use --full-backtest p/ metricas de trade.")
    print()

    from crypto_trading_bot.research.sl_calibration import (
        analyze_sl_calibration,
    )

    def _progress(name: str, idx: int, total: int) -> None:
        if args.progress_every and idx % max(1, args.progress_every) == 0:
            print(f"  ...backtest {idx}/{total}: {name}")

    try:
        report = analyze_sl_calibration(
            candles=candles, data_source=data_source,
            min_stop_loss_pct=float(args.min_stop_loss_pct),
            position_size_usd=float(args.position_size_usd),
            risk_reward_ratio=float(args.risk_reward_ratio),
            max_risk_per_trade_usd=args.max_risk_per_trade_usd,
            initial_capital=float(args.initial_capital),
            min_candles=int(args.min_candles), symbol=args.symbol,
            run_backtests=run_backtests,
            real_dataset_available=real_dataset_available,
            walk_forward_available=walk_forward_available,
            progress_callback=_progress if run_backtests else None,
        )
    except KeyboardInterrupt:
        print()
        print("  INTERROMPIDO pelo usuario (Ctrl+C). Relatorio PARCIAL: a "
              "analise determinISTIca pode nao ter concluido.")
        partial = {
            "schema": "sl_calibration_v1",
            "status": "interrupted",
            "data_source": data_source,
            "candles": len(candles),
            "message": "interrompido durante a analise; nada autoaplicado.",
        }
        _write(args.output, partial)
        return 1

    if report["status"] != "ok":
        print(f"  STATUS: {report['status']}")
        print(f"  {report.get('message', '')}")
        _write(args.output, report)
        return 1

    a = report["atr_summary"]
    print(f"  ATR mediano: {a['median_atr_pct']}% | piso: "
          f"{report['min_sl_pct_required']}%")
    print(f"  multiplicador implicito p/ cruzar piso: "
          f"~{report['implied_multiplier_to_clear_floor']}")
    print(f"  menor multiplicador que zera rejeicao: "
          f"{report['smallest_multiplier_clearing_floor']}")
    print()
    print("  SL% x piso por multiplicador:")
    print(f"    {'mult':>5} {'rej%':>7} {'medianaSL%':>11} "
          f"{'riscoUSD':>9}")
    for s in report["sl_stats_by_multiplier"]:
        print(f"    {s['stop_atr_multiplier']:>5} "
              f"{s['rejection_pct']:>7} {s['median_sl_pct']:>11} "
              f"{s['median_risk_usd']:>9}")
    print()
    print("  Recomendacoes por perfil:")
    for rec in report["recommendations"]:
        print(f"    [{rec['profile']}] {rec['action']}")
        print(f"      {rec['detail']}")
    print()
    print(f"  backtests_ran: {report.get('backtests_ran')} | "
          f"partial: {report.get('backtests_partial')}")
    if report.get("backtests_partial"):
        print("  (backtests interrompidos; metricas de trade parciais)")
    print(f"  {report['note']}")

    _write(args.output, report)
    print()
    print("=" * 72)
    print("  END.")
    print("=" * 72)
    return 0


def _slice_candles(candles, start_date: str, end_date: str,
                   max_candles: int):
    """Recorta candles por range de data (UTC) e/ou N mais recentes."""
    from datetime import datetime, timezone

    def _parse(v: str):
        v = v.strip()
        if not v:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(v, fmt).replace(
                    tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    start = _parse(start_date)
    end = _parse(end_date)
    out = candles
    if start or end:
        def _in_range(c) -> bool:
            ts = getattr(c, "timestamp", None)
            if ts is None:
                return True
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if start and ts < start:
                return False
            if end and ts >= end:
                return False
            return True
        out = [c for c in out if _in_range(c)]
    if max_candles and max_candles > 0 and len(out) > max_candles:
        out = out[-max_candles:]
    return out


def _write(path: str, payload: dict) -> None:
    if not path:
        return
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
    sys.exit(main())
