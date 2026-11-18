#!/usr/bin/env python
"""
run_strategy_backtest.py - Backtest Operational Parity (FASE 37 C/F/H/I)
=======================================================================
ASCII-only. ZERO ordem real / API de execucao / secret. Execucao 100%
simulada (paridade operacional com a demo: RiskEngine soberano, perfil,
custos, decision trace, contexto auditado SEM look-ahead).

Fonte de dados (uma das duas):
    --from-csv P            usa um CSV canonico ja existente (offline).
    --provider/--symbol/--timeframe/--start-date/--end-date
                            busca via fetcher read-only (provider real
                            exige --allow-network).

Selecao (OBRIGATORIA, sem hardcode):
    --strategy NAME         validada contra registry + perfil.
    --symbol SYMBOL         par.
    --timeframe TF          ex.: 15m.
    --capital USD           capital de simulacao (> 0; sem default).

Toggles (default seguro OFF):
    --profile NAME          aplica allowed_strategies do perfil.
    --fees-bps / --slippage-bps
    --enable-ai-context / --enable-polymarket-context /
    --enable-market-intelligence / --enable-funding-context /
    --enable-open-interest-context / --enable-orderbook-context /
    --enable-news-context
    --require-context KIND   (repetivel) contexto obrigatorio.
    --no-allow-missing-context  bloqueia se contexto obrigatorio ausente.
    --context-dataset P      JSON de snapshots reais de contexto.
    --progress-every N
    --output P               grava o relatorio JSON.

Exit: 0 sucesso | 1 erro de selecao/dados/contexto-obrigatorio.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))

_SECRET_TOKENS = (
    "api_key", "api_secret", "bearer ", "x-bapi", "sign=",
    "authorization:",
)

# Acima deste numero de candles, backtest sem precompute (O(n^2)) avisa.
_BIG_BACKTEST_CANDLES = 5000


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(
        description="Backtest operacional (simulado, read-only).",
    )
    src = p.add_argument_group("fonte de dados")
    src.add_argument("--from-csv", dest="from_csv", type=str, default="")
    src.add_argument("--provider", type=str, default="")
    src.add_argument("--symbol", type=str, required=True)
    src.add_argument("--timeframe", type=str, required=True)
    src.add_argument("--start-date", dest="start_date", type=str,
                     default="")
    src.add_argument("--end-date", dest="end_date", type=str, default="")
    src.add_argument("--allow-network", dest="allow_network",
                     action="store_true")

    sel = p.add_argument_group("selecao")
    sel.add_argument("--strategy", type=str, required=True)
    sel.add_argument("--profile", type=str, default="")
    sel.add_argument("--capital", type=float, required=True)
    sel.add_argument("--fees-bps", dest="fees_bps", type=float,
                     default=0.0)
    sel.add_argument("--slippage-bps", dest="slippage_bps", type=float,
                     default=0.0)

    tog = p.add_argument_group("contextos (default OFF)")
    for name in ("ai", "polymarket", "market-intelligence", "funding",
                 "open-interest", "orderbook", "news"):
        tog.add_argument(f"--enable-{name}-context"
                         if name not in ("market-intelligence",)
                         else f"--enable-{name}",
                         dest=f"enable_{name.replace('-', '_')}",
                         action="store_true")
    tog.add_argument("--require-context", dest="require_context",
                     action="append", default=[])
    tog.add_argument("--no-allow-missing-context",
                     dest="allow_missing_context",
                     action="store_false", default=True)
    tog.add_argument("--context-dataset", dest="context_dataset",
                     type=str, default="")

    p.add_argument("--progress-every", dest="progress_every", type=int,
                   default=0,
                   help="Heartbeat a cada N candles (0 = sem heartbeat).")
    p.add_argument("--max-candles", dest="max_candles", type=int,
                   default=0,
                   help="Usa os N candles MAIS RECENTES (0 = todos).")
    p.add_argument("--no-precompute", dest="no_precompute",
                   action="store_true",
                   help="Desliga o precompute O(n) (volta ao O(n^2) "
                        "legado; identico, porem lento).")
    p.add_argument("--output", type=str, default="")
    args = p.parse_args(argv)

    from crypto_trading_bot.backtesting import (
        BacktestDataError,
        load_candles_from_csv,
    )
    from crypto_trading_bot.backtest_operational import (
        BacktestContextError,
        BacktestExecutionContext,
        BacktestRunnerError,
        StrategySelectionError,
        run_operational_backtest,
    )

    print()
    print("=" * 72)
    print("  STRATEGY BACKTEST (FASE 37) - SIMULADO / READ-ONLY")
    print("  ZERO ordem real. RiskEngine soberano. Anti look-ahead.")
    print("=" * 72)

    # --- Obter candles + metadados de fonte ---
    try:
        candles, source_type, checksum = _load_candles(
            args, load_candles_from_csv,
        )
    except (BacktestDataError, ValueError) as e:
        print(f"  ERROR dados: {e}")
        return 1
    except _CliError as e:
        print(f"  {e}")
        return 1

    # Recorte por data (--start-date/--end-date) tambem no caminho
    # --from-csv (antes so o caminho provider respeitava o range).
    if args.from_csv.strip() and (args.start_date or args.end_date):
        try:
            n0 = len(candles)
            candles = _slice_by_date(
                candles, args.start_date, args.end_date)
        except _CliError as e:
            print(f"  {e}")
            return 1
        if not candles:
            print("  ERROR nenhum candle no range solicitado "
                  f"({args.start_date or '-'} .. {args.end_date or '-'}).")
            return 1
        if len(candles) != n0:
            print(f"  recorte por data: {n0} -> {len(candles)} candles "
                  f"({args.start_date or '-'} .. {args.end_date or '-'})")

    # Recorte --max-candles (N mais recentes) p/ bound do custo.
    if args.max_candles and args.max_candles > 0 and \
            len(candles) > args.max_candles:
        n0 = len(candles)
        candles = candles[-args.max_candles:]
        print(f"  recorte --max-candles: {n0} -> {len(candles)} candles")

    # --- Dataset de contexto (opcional, dado REAL) ---
    try:
        ctx_dataset = _load_context_dataset(args.context_dataset)
    except _CliError as e:
        print(f"  ERROR contexto: {e}")
        return 1

    # --- Perfil (allowed_strategies) ---
    profile_allowed = None
    profile_name = args.profile.strip() or None
    if profile_name:
        try:
            from crypto_trading_bot.operational_profile import (
                resolve_profile,
            )
            prof = resolve_profile(profile_name, capital=args.capital)
            profile_allowed = prof.allowed_strategies or None
        except ValueError as e:
            print(f"  ERROR profile: {e}")
            return 1

    # --- Contexto de execucao ---
    try:
        ctx = BacktestExecutionContext(
            strategy=args.strategy,
            profile=profile_name,
            capital_usd=args.capital,
            fees_bps=args.fees_bps,
            slippage_bps=args.slippage_bps,
            enable_ai_context=args.enable_ai,
            enable_polymarket_context=args.enable_polymarket,
            enable_market_intelligence=args.enable_market_intelligence,
            enable_funding_context=args.enable_funding,
            enable_open_interest_context=args.enable_open_interest,
            enable_orderbook_context=args.enable_orderbook,
            enable_news_context=args.enable_news,
            allow_missing_context=args.allow_missing_context,
            required_context_kinds=tuple(args.require_context),
        )
    except BacktestContextError as e:
        print(f"  ERROR context: {e}")
        return 1

    # --- Performance guard (FASE 37.1) ---
    n = len(candles)
    precompute = not args.no_precompute
    if precompute:
        print(f"  precompute-features: ON (O(n)); {n} candles.")
    else:
        print(f"  precompute-features: OFF (O(n^2)); {n} candles.")
        if n > _BIG_BACKTEST_CANDLES:
            print(f"  AVISO backtest GRANDE sem precompute pode demorar "
                  f"muito (O(n^2)). Considere remover --no-precompute ou "
                  f"usar --max-candles N.")
    print("  Ctrl+C interrompe e gera relatorio PARCIAL (sem traceback).")

    # Heartbeat real durante o backtest (pct/candle/ts/elapsed/ETA/...).
    start = time.monotonic()

    def _heartbeat(info: dict) -> None:
        i = int(info.get("i", 0)); total = int(info.get("n", 0) or 1)
        done = i + 1
        pct = done / total * 100.0
        elapsed = time.monotonic() - start
        rate = done / elapsed if elapsed > 0 else 0.0
        eta = (total - done) / rate if rate > 0 else 0.0
        ts = info.get("timestamp")
        ts_s = ts.strftime("%Y-%m-%dT%H:%M:%SZ") if ts is not None else "-"
        print(f"  [{pct:5.1f}%] candle {done}/{total} | {ts_s} | "
              f"elapsed {elapsed:6.1f}s | ETA {eta:6.1f}s | "
              f"trades {info.get('trades', 0)} | "
              f"blocked {info.get('blocked', 0)}")

    try:
        report = run_operational_backtest(
            ctx, candles,
            symbol=args.symbol, timeframe=args.timeframe,
            context_dataset=ctx_dataset,
            profile_allowed=profile_allowed,
            source_type=source_type,
            dataset_checksum=checksum,
            precompute_features=precompute,
            backtest_progress_every=args.progress_every,
            on_backtest_progress=(
                _heartbeat if args.progress_every else None),
        )
    except (StrategySelectionError, BacktestRunnerError) as e:
        print(f"  ERROR backtest: {e}")
        return 1

    _print_report(report)
    if args.output:
        _write(args.output, report.to_dict())

    if report.interrupted:
        print("  >> Backtest interrompido pelo operador; relatorio parcial.")
        return 130
    # Exit 1 se algum contexto obrigatorio ficou indisponivel.
    blocked = any(
        c.blocked_count > 0 for c in report.context_availability
    )
    return 1 if blocked else 0


class _CliError(Exception):
    pass


def _load_candles(args, load_candles_from_csv):
    if args.from_csv.strip():
        path = Path(args.from_csv)
        if any(x == ".." for x in path.parts):
            raise _CliError("ERROR --from-csv contem '..'")
        candles = load_candles_from_csv(
            str(path), symbol=args.symbol,
            timeframe=_tf_minutes(args.timeframe),
        )
        return candles, "csv", None

    # Fetch via provider (fetcher read-only) -> CSV temporario em memoria.
    if not (args.provider and args.start_date and args.end_date):
        raise _CliError(
            "ERROR informe --from-csv OU "
            "(--provider --start-date --end-date)"
        )
    from crypto_trading_bot.backtesting import load_candles_from_csv_string
    from crypto_trading_bot.historical_data import (
        get_provider,
        HistoricalDataError,
    )
    try:
        prov = get_provider(args.provider)
    except HistoricalDataError as e:
        raise _CliError(f"ERROR provider: {e}")
    if prov.is_real and not args.allow_network:
        raise _CliError(
            f"BLOCKED provider real '{prov.name}' exige --allow-network "
            "(use --provider fake para offline)."
        )
    # Reusa o fetcher como gerador read-only (sem gravar arquivo: dry-run
    # nao serve pois nao retorna CSV; usamos provider direto).
    from crypto_trading_bot.historical_data.providers import (
        validate_fetch_request,
    )
    from crypto_trading_bot.historical_data.fetcher import (
        _rows_to_csv_text, _dedup_sort,
    )
    tf_label, tf_min, start, end = validate_fetch_request(
        symbol=args.symbol, timeframe=args.timeframe,
        start_date=args.start_date, end_date=args.end_date,
    )
    rows = _dedup_sort(prov.fetch_candles(
        symbol=args.symbol.upper(), tf_minutes=tf_min,
        start=start, end=end,
    ))
    if not rows:
        raise _CliError("ERROR provider retornou 0 candles")
    csv_text = _rows_to_csv_text(rows)
    candles = load_candles_from_csv_string(
        csv_text, symbol=args.symbol.upper(),
        timeframe=_tf_minutes(args.timeframe),
    )
    source_type = "real" if prov.is_real else "synthetic_fake"
    return candles, source_type, None


def _tf_minutes(timeframe: str) -> str:
    from crypto_trading_bot.historical_data import normalize_timeframe
    _, mins = normalize_timeframe(timeframe)
    return str(mins)


def _parse_cli_date(value: str):
    """Parse YYYY-MM-DD[THH:MM:SS[Z]] em UTC. Retorna (dt, date_only)."""
    from datetime import timezone as _tz
    v = value.strip()
    for fmt, date_only in (
        ("%Y-%m-%d", True),
        ("%Y-%m-%dT%H:%M:%S", False),
        ("%Y-%m-%dT%H:%M:%SZ", False),
    ):
        try:
            return (datetime.strptime(v, fmt).replace(tzinfo=_tz.utc),
                    date_only)
        except ValueError:
            continue
    raise _CliError(f"ERROR data invalida: {value!r}. Use YYYY-MM-DD (UTC).")


def _slice_by_date(candles, start_date: str, end_date: str):
    """Recorta candles pelo range [start, end] (UTC). end date-only eh
    INCLUSIVO do dia inteiro (ex.: 2026-05-31 inclui ate 23:45). Aplicado
    ao --from-csv (e inocuo no caminho provider, ja limitado)."""
    from datetime import timedelta, timezone as _tz
    start_dt = None
    end_excl = None
    if start_date.strip():
        start_dt, _ = _parse_cli_date(start_date)
    if end_date.strip():
        end_dt, date_only = _parse_cli_date(end_date)
        end_excl = end_dt + timedelta(days=1) if date_only else end_dt
    if start_dt is None and end_excl is None:
        return candles

    def _keep(c) -> bool:
        ts = getattr(c, "timestamp", None)
        if ts is None:
            return True
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_tz.utc)
        if start_dt is not None and ts < start_dt:
            return False
        if end_excl is not None and ts >= end_excl:
            return False
        return True

    return [c for c in candles if _keep(c)]


def _load_context_dataset(path: str):
    if not path.strip():
        return None
    from crypto_trading_bot.backtest_operational import (
        ContextDataset,
        ContextSnapshot,
    )
    pp = Path(path)
    if any(x == ".." for x in pp.parts):
        raise _CliError("--context-dataset contem '..'")
    if not pp.is_file():
        raise _CliError(f"context-dataset nao encontrado: {path}")
    data = json.loads(pp.read_text(encoding="utf-8"))
    snaps = []
    for item in data.get("snapshots", []):
        ts = datetime.strptime(
            item["as_of"], "%Y-%m-%dT%H:%M:%SZ",
        ).replace(tzinfo=timezone.utc)
        snaps.append(ContextSnapshot(
            kind=item["kind"], as_of=ts,
            data=item.get("data", {}),
            source=item.get("source", "dataset"),
            confidence=item.get("confidence"),
        ))
    max_stale = data.get("max_staleness_seconds")
    return ContextDataset(snaps, max_staleness_seconds=max_stale)


def _print_report(r) -> None:
    d = r.to_dict()
    res = d["results"]
    print()
    print(f"  strategy/profile:   {d['strategy']} / {d['profile']}")
    print(f"  symbol/timeframe:   {d['symbol']} {d['timeframe']}")
    print(f"  rows:               {d['rows']} "
          f"({d['first_timestamp']}..{d['last_timestamp']})")
    print(f"  source_type:        {d['source_type']}")
    print(f"  real_exec_allowed:  {d['real_execution_allowed']}")
    print(f"  elapsed_seconds:    {d.get('elapsed_seconds')}")
    if d.get("partial") or d.get("interrupted"):
        print(f"  PARTIAL/INTERRUPTED: partial={d.get('partial')} "
              f"interrupted={d.get('interrupted')} "
              f"candles_processed={d.get('candles_processed')}")
    print(f"  total_trades:       {res['total_trades']} "
          f"(W{res['winning_trades']}/L{res['losing_trades']})")
    print(f"  win_rate_pct:       {res['win_rate_pct']}")
    print(f"  total_pnl_usd:      {res['total_pnl_usd']}")
    print(f"  max_drawdown_pct:   {res['max_drawdown_pct']}")
    print(f"  profit_factor:      {res['profit_factor']}")
    print(f"  expectancy_usd:     {res['expectancy_usd']}")
    print(f"  risk_blocked_count: {res['risk_blocked_count']}")
    brs = res.get("blocked_reasons_summary") or {}
    if brs:
        parts = ", ".join(f"{k}={v}" for k, v in sorted(brs.items()))
        print(f"  blocked_reasons:    {parts}")
    print(f"  final_capital:      {res['final_capital']}")
    print(f"  decision_traces:    {d['decision_trace_count']}")
    print("  context (enabled | available | impact | blocked):")
    for c in d["context_availability"]:
        if c["enabled"] or c["blocked_count"]:
            print(f"    - {c['kind']:<20} en={c['enabled']} "
                  f"avail={c['context_available_count']} "
                  f"impact={c['decision_impact_count']} "
                  f"blocked={c['blocked_count']}")
    if d["warnings"]:
        print("  warnings:")
        for w in d["warnings"]:
            print(f"    - {w}")


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
        # Defesa final: interrupt fora do runner nao vira traceback cru.
        print()
        print("  >> Interrompido pelo operador (Ctrl+C). Nada autoaplicado.")
        sys.exit(130)
