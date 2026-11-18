"""
download_historical_data.py — CLI manual para baixar candles públicos da Bybit
================================================================================
⚠️  CONECTA À INTERNET PÚBLICA DA BYBIT — APENAS LEITURA.
⚠️  ZERO API KEY. ZERO autenticação. ZERO ordens.
⚠️  Use apenas para popular cache local. Após download, o backtest roda offline.
⚠️  Não é executado pelos testes — uso manual exclusivo.

Como usar:
    # Modo seco (mostra o que seria baixado sem chamar a API)
    python scripts/download_historical_data.py \\
        --symbol BTCUSDT --timeframe 15 \\
        --start 2024-01-01 --end 2024-01-07 \\
        --dry-run

    # Download real
    python scripts/download_historical_data.py \\
        --symbol BTCUSDT --timeframe 15 \\
        --start 2024-01-01 --end 2024-01-07

Output:
    Arquivo CSV salvo em data/historical/{SYMBOL}_{TIMEFRAME}.csv
    Após o download, o backtest pode ler offline via:
        from crypto_trading_bot.data import DataCache
        cache = DataCache()
        candles = cache.load("BTCUSDT", "15")
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# Adiciona src ao path
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))


def _print_safety_banner() -> None:
    print()
    print("=" * 70)
    print("  📥 BYBIT HISTORICAL DATA DOWNLOAD — FASE 3G")
    print("  ⚠️  Conecta à internet pública da Bybit (read-only).")
    print("  ⚠️  SEM API key. SEM autenticação. SEM ordens.")
    print("  ⚠️  Dados reais NÃO garantem performance futura.")
    print("=" * 70)
    print()


def _parse_date(s: str) -> datetime:
    """Aceita YYYY-MM-DD ou ISO 8601 com timezone."""
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"Data inválida: {s!r}. Use YYYY-MM-DD ou ISO 8601."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Baixa candles históricos públicos da Bybit e salva em cache local. "
            "Read-only, sem API key, sem ordens."
        )
    )
    parser.add_argument(
        "--symbol", required=True, type=str,
        help="Símbolo do par (ex: BTCUSDT)."
    )
    parser.add_argument(
        "--timeframe", required=True, type=str,
        help="Timeframe (ex: 15 = 15min; D = diário)."
    )
    parser.add_argument(
        "--start", required=True, type=_parse_date,
        help="Data inicial (inclusive). Formato: YYYY-MM-DD ou ISO 8601."
    )
    parser.add_argument(
        "--end", required=True, type=_parse_date,
        help="Data final (inclusive). Formato: YYYY-MM-DD ou ISO 8601."
    )
    parser.add_argument(
        "--category", default="linear", choices=["linear", "spot", "inverse"],
        help="Categoria Bybit V5 (default: linear)."
    )
    parser.add_argument(
        "--output-dir", default="data/historical",
        help="Diretório de saída (default: data/historical/)."
    )
    parser.add_argument(
        "--rate-limit-sleep", type=float, default=0.2,
        help="Sleep em segundos entre páginas (default: 0.2)."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Modo seco: mostra o que seria baixado SEM chamar a API."
    )
    args = parser.parse_args()

    _print_safety_banner()

    print(f"  Symbol:       {args.symbol}")
    print(f"  Timeframe:    {args.timeframe}")
    print(f"  Period:       {args.start.isoformat()} → {args.end.isoformat()}")
    print(f"  Category:     {args.category}")
    print(f"  Output dir:   {args.output_dir}")
    print(f"  Rate limit:   {args.rate_limit_sleep}s entre páginas")
    print()

    if args.dry_run:
        print("  🔍 DRY-RUN: nenhuma requisição será feita à internet.")
        print("  Use sem --dry-run para baixar de verdade.")
        print()
        print("=" * 70)
        return 0

    # Imports tardios para permitir --dry-run sem rede
    from crypto_trading_bot.data.data_cache import DataCache
    from crypto_trading_bot.data.historical_data import HistoricalDataService
    from crypto_trading_bot.exchange.bybit_client import BybitClient

    print("  🌐 Conectando à Bybit (público, read-only)...")
    client = BybitClient()  # Sem credenciais — apenas endpoints públicos.
    cache = DataCache(base_dir=Path(args.output_dir))
    svc = HistoricalDataService(
        client=client,
        cache=cache,
        rate_limit_sleep_seconds=args.rate_limit_sleep,
    )

    try:
        candles, report = svc.get(
            symbol=args.symbol,
            timeframe=args.timeframe,
            start=args.start,
            end=args.end,
            use_cache=False,    # força download (CLI explícito)
            refresh=True,
            strict_quality=False,
            category=args.category,
        )
    except Exception as e:
        print()
        print(f"  ❌ Erro durante download: {e}")
        return 1

    print()
    print("─" * 70)
    print(f"  ✅ Download concluído: {len(candles)} candles")
    if candles:
        print(f"  Primeiro candle: {candles[0].timestamp.isoformat()}")
        print(f"  Último candle:   {candles[-1].timestamp.isoformat()}")
    print()
    print(report.summary())
    print()
    print("─" * 70)
    print("  ✅ CONFIRMAÇÕES DE SEGURANÇA:")
    print("  ✅ Nenhuma API key foi usada.")
    print("  ✅ Apenas endpoint público /v5/market/kline.")
    print("  ✅ Nenhuma ordem real foi enviada.")
    print("  ⚠️  Dados reais NÃO garantem performance futura.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
