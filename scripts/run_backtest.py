"""
run_backtest.py — Executar Backtest com Dados Locais/Mockados
=============================================================
⚠️  MODO SEGURO — Nenhuma ordem real é enviada.
⚠️  Usa dados locais ou gerados em memória — sem internet.
⚠️  Resultados NÃO garantem performance futura.
⚠️  Meta de challenge (se configurada) é APENAS KPI informativo.

Como executar:
    python scripts/run_backtest.py
    python scripts/run_backtest.py --candles 500
    python scripts/run_backtest.py --trend 0.001 --candles 300
    python scripts/run_backtest.py --csv data/btcusdt_15m.csv
    python scripts/run_backtest.py --challenge-target 500

Fontes de dados (ordem de prioridade):
    1. --csv  → arquivo CSV local
    2. memoria → generate_trending_candles() (padrão)

O bot é agnóstico de provider:
    - HyroTrader é apenas um template/exemplo
    - A lógica não depende do provider_name
    - Configure qualquer conta via parâmetros
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Garante que o src/ está no path quando executado diretamente
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))


def _print_banner():
    print()
    print("=" * 70)
    print("  📊 CRYPTO TRADING BOT — BACKTESTING")
    print("  ⚠️  Resultados NÃO garantem performance futura.")
    print("  ⚠️  MODO SEGURO | SEM ORDENS REAIS | SEM API")
    print("=" * 70)
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Executa backtest com dados locais/mockados (sem API real)"
    )
    parser.add_argument(
        "--candles", type=int, default=300,
        help="Número de candles sintéticos a gerar (padrão: 300)"
    )
    parser.add_argument(
        "--trend", type=float, default=0.001,
        help="Tendência por candle (ex: 0.001=alta, -0.001=baixa) (padrão: 0.001)"
    )
    parser.add_argument(
        "--capital", type=float, default=5000.0,
        help="Capital inicial simulado em USD (padrão: 5000.0)"
    )
    parser.add_argument(
        "--position-size", type=float, default=200.0,
        help="Tamanho de posição em USD (padrão: 200.0)"
    )
    parser.add_argument(
        "--symbol", default="BTCUSDT",
        help="Símbolo de trading (padrão: BTCUSDT)"
    )
    parser.add_argument(
        "--csv", type=str, default=None,
        help="Caminho para arquivo CSV local (opcional)"
    )
    parser.add_argument(
        "--challenge-target", type=float, default=None,
        help="Meta de challenge em USD — APENAS KPI informativo (padrão: None)"
    )
    parser.add_argument(
        "--min-candles", type=int, default=50,
        help="Mínimo de candles para iniciar estratégia (padrão: 50)"
    )
    # FASE 3E.1 — Flags de custos de execução (opcionais; defaults zero
    # preservam o comportamento da FASE 3D.5)
    parser.add_argument(
        "--fee-pct", type=float, default=0.0,
        help="Taker fee em fração decimal (ex: 0.0006=0.06%%). Default: 0.0 (sem fee)"
    )
    parser.add_argument(
        "--slippage-pct", type=float, default=0.0,
        help="Slippage adverso em fração decimal (ex: 0.0005=0.05%%). Default: 0.0"
    )
    parser.add_argument(
        "--spread-pct", type=float, default=0.0,
        help="Spread em fração decimal (ex: 0.0002=0.02%%). Default: 0.0"
    )

    args = parser.parse_args()

    _print_banner()

    # Imports dentro da função (garante path correto)
    from crypto_trading_bot.backtesting.backtest_data import (
        generate_trending_candles,
        load_candles_from_csv,
    )
    from crypto_trading_bot.backtesting.backtest_engine import BacktestEngine
    from crypto_trading_bot.backtesting.execution_costs import ExecutionCostConfig
    from crypto_trading_bot.data.feature_engine import FeatureEngine
    from crypto_trading_bot.risk.risk_engine import RiskEngine
    from crypto_trading_bot.strategies.ema_rsi_strategy import EmaRsiStrategy

    # ─── Carregar dados ───────────────────────────────────────────────────
    if args.csv:
        print(f"  📁 Carregando dados de: {args.csv}")
        try:
            candles = load_candles_from_csv(
                path=args.csv,
                symbol=args.symbol,
            )
        except Exception as e:
            print(f"\n  ❌ Erro ao carregar CSV: {e}")
            sys.exit(1)
    else:
        print(f"  📊 Gerando {args.candles} candles sintéticos (sem internet)...")
        candles = generate_trending_candles(
            n=args.candles,
            trend_pct_per_candle=args.trend,
            symbol=args.symbol,
        )

    n = len(candles)
    print(f"  ✅ {n} candles prontos | {candles[0].timestamp.date()} → {candles[-1].timestamp.date()}")
    print()

    # ─── Configurar componentes ───────────────────────────────────────────
    print(f"  Capital:           ${args.capital:,.2f} USD")
    print(f"  Posição:           ${args.position_size:,.2f} USD")
    print(f"  Símbolo:           {args.symbol}")
    print(f"  Tendência candle:  {args.trend:+.3%}/candle")
    print(f"  Min candles:       {args.min_candles}")
    if args.challenge_target is not None:
        print(f"  Challenge target:  ${args.challenge_target:,.2f} [APENAS KPI — não bloqueia]")

    # FASE 3E.1 — Custos de execução
    cost_config = ExecutionCostConfig(
        taker_fee_pct=args.fee_pct,
        slippage_pct=args.slippage_pct,
        spread_pct=args.spread_pct,
    )
    if not cost_config.is_zero:
        print(
            f"  Custos:            fee={args.fee_pct:.4%} | "
            f"slippage={args.slippage_pct:.4%} | spread={args.spread_pct:.4%}"
        )
    print()

    strategy = EmaRsiStrategy(
        ema_short_period=9,
        ema_long_period=21,
        rsi_period=14,
        rsi_overbought=65.0,
        stop_atr_multiplier=2.0,
        stop_fallback_pct=0.015,
        position_size_usd=args.position_size,
    )
    strategy.set_running()

    risk_engine = RiskEngine(initial_capital=args.capital)
    feature_engine = FeatureEngine()

    engine = BacktestEngine(
        strategy=strategy,
        risk_engine=risk_engine,
        feature_engine=feature_engine,
        initial_capital=args.capital,
        min_candles=args.min_candles,
        symbol=args.symbol,
        challenge_profit_target_usd=args.challenge_target,
        execution_cost_config=cost_config,
    )

    # ─── Executar backtest ────────────────────────────────────────────────
    print("─" * 70)
    print(f"  ▶ Executando backtest com {strategy.name}...")
    print("─" * 70)
    print()

    try:
        report = engine.run(candles)
    except Exception as e:
        print(f"\n  ❌ Erro durante o backtest: {e}")
        sys.exit(1)

    # ─── Exibir relatório ─────────────────────────────────────────────────
    print(report.summary())

    # ─── Confirmações de segurança ────────────────────────────────────────
    print()
    print("─" * 70)
    print("  ✅ CONFIRMAÇÕES DE SEGURANÇA:")
    print("─" * 70)
    print("  ✅ Nenhuma API real foi usada.")
    print("  ✅ Nenhuma ordem real foi enviada.")
    print("  ✅ Nenhuma API key foi usada.")
    print("  ✅ Bot agnóstico de provider (HyroTrader é apenas template).")
    if args.challenge_target is not None:
        status = "✅ SIM" if report.challenge_target_reached else "❌ NÃO"
        print(f"  ⚠️  Meta de challenge ({status}) — APENAS KPI, não bloqueou trades.")
    print("  ⚠️  Resultados NÃO garantem performance futura.")
    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
