"""
run_paper_trading.py — Iniciar Bot em Modo Paper Trading
=========================================================
⚠️  MODO SIMULADO — Nenhuma ordem real é enviada.
⚠️  Usa MockExchange por padrão (sem internet necessária).
⚠️  Para usar Bybit Testnet, configure TRADING_MODE=testnet no .env.

Fluxo:
    MockExchange → MarketData → FeatureEngine
        → EmaRsiStrategy ⚠️(PLACEHOLDER)
        → RiskEngine (soberano)
        → PaperTrader (simulado)
        → BotCycleResult (auditável)

Como executar:
    python scripts/run_paper_trading.py
    python scripts/run_paper_trading.py --cycles 10
    python scripts/run_paper_trading.py --symbol BTCUSDT --cycles 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Garante que o src/ está no path quando executado diretamente
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))


def _build_pipeline(symbol: str, capital: float, position_size: float):
    """
    Constrói o pipeline completo com MockExchange.

    Usa _price_history do MockExchange para gerar candles simulados
    sem depender de API ou internet.

    Retorna (engine, strategy, risk_engine, paper_trader).
    """
    from crypto_trading_bot.core.bot_engine import BotEngine
    from crypto_trading_bot.data.feature_engine import FeatureEngine
    from crypto_trading_bot.data.market_data import MarketDataService
    from crypto_trading_bot.exchange.mock_exchange import MockExchange
    from crypto_trading_bot.execution.paper_trader import PaperTrader
    from crypto_trading_bot.risk.risk_engine import RiskEngine
    from crypto_trading_bot.strategies.ema_rsi_strategy import EmaRsiStrategy

    # Injeta preços simulados via _price_history (interface real do MockExchange)
    # trend=50 garante EMA9 > EMA21 após warm-up → sinal BUY testável
    print("📊 Gerando candles simulados (sem internet)...")
    mock_exchange = MockExchange()
    mock_exchange._price_history = [65000.0 + i * 50.0 for i in range(100)]

    market_data = MarketDataService(exchange=mock_exchange, default_symbol=symbol)
    feature_engine = FeatureEngine()

    strategy = EmaRsiStrategy(
        ema_short_period=9,
        ema_long_period=21,
        rsi_period=14,
        rsi_overbought=65.0,
        stop_atr_multiplier=2.0,
        stop_fallback_pct=0.015,
        position_size_usd=position_size,
    )

    risk_engine = RiskEngine(initial_capital=capital)
    paper_trader = PaperTrader(risk_engine=risk_engine)

    engine = BotEngine(
        market_data_service=market_data,
        feature_engine=feature_engine,
        strategy=strategy,
        risk_engine=risk_engine,
        paper_trader=paper_trader,
        candles_limit=100,
    )

    return engine, strategy, risk_engine, paper_trader


def _print_banner():
    print()
    print("=" * 60)
    print("  🤖 CRYPTO TRADING BOT — PAPER TRADING")
    print("  ⚠️  MODO SIMULADO | SEM ORDENS REAIS")
    print("  ⚠️  EmaRsiStrategy = PLACEHOLDER (não validada)")
    print("=" * 60)
    print()


def _print_result(result, paper_trader):
    """Imprime resultado de um ciclo de forma legível."""
    icon = {
        "executed":          "✅",
        "hold":              "⏸ ",
        "risk_blocked":      "⛔",
        "no_candles":        "📭",
        "insufficient_data": "📉",
        "strategy_inactive": "💤",
        "safety_blocked":    "🔒",
        "error":             "❌",
    }.get(result.action, "❓")

    print(
        f"  Ciclo #{result.cycle:3d} | "
        f"{icon} {result.action:<20} | "
        f"exec={result.executed} | "
        f"risk={result.risk_approved}"
    )

    if result.action == "executed" and result.trade:
        summary = paper_trader.get_summary()
        print(
            f"           └─ 💰 Trade simulado | "
            f"Trades abertos: {summary.get('open_trades', 0)} | "
            f"PnL realizado: {summary.get('realized_pnl', 0.0):+.2f} USD"
        )
    elif result.action == "risk_blocked":
        print(f"           └─ Motivo: {result.reason[:60]}")
    elif result.action == "hold" and result.strategy_signal:
        reason = result.strategy_signal.reason
        if reason:
            print(f"           └─ {reason[:60]}")


def main():
    parser = argparse.ArgumentParser(
        description="Executa o bot em modo paper trading (sem ordens reais)"
    )
    parser.add_argument(
        "--symbol", default="BTCUSDT",
        help="Símbolo de trading (default: BTCUSDT)"
    )
    parser.add_argument(
        "--cycles", type=int, default=10,
        help="Número de ciclos a executar (default: 10)"
    )
    parser.add_argument(
        "--capital", type=float, default=5000.0,
        help="Capital inicial simulado em USD (default: 5000.0)"
    )
    parser.add_argument(
        "--position-size", type=float, default=200.0,
        help="Tamanho de posição em USD (default: 200.0)"
    )
    args = parser.parse_args()

    _print_banner()

    print(f"  Símbolo:      {args.symbol}")
    print(f"  Capital:      ${args.capital:,.2f} USD (simulado)")
    print(f"  Posição:      ${args.position_size:,.2f} USD")
    print(f"  Ciclos:       {args.cycles}")
    print()

    # Constrói pipeline
    engine, strategy, risk_engine, paper_trader = _build_pipeline(
        symbol=args.symbol,
        capital=args.capital,
        position_size=args.position_size,
    )

    # Ativa estratégia
    strategy.set_running()

    print(f"  Estratégia:   {strategy.name}")
    print(f"  Modo:         PAPER (MockExchange — sem internet)")
    print()
    print("─" * 60)
    print("  Executando ciclos...")
    print("─" * 60)

    # Executa ciclos
    results = []
    for _ in range(args.cycles):
        result = engine.run_once()
        results.append(result)
        _print_result(result, paper_trader)

    # Resumo final
    print()
    print("─" * 60)
    print("  📋 RESUMO FINAL")
    print("─" * 60)

    actions_count: dict = {}
    for r in results:
        actions_count[r.action] = actions_count.get(r.action, 0) + 1

    for action, count in sorted(actions_count.items()):
        print(f"  {action:<25} {count:3d} ciclo(s)")

    summary = paper_trader.get_summary()
    risk_summary = risk_engine.get_status_summary()

    print()
    print(f"  Capital inicial:  ${args.capital:>10,.2f}")
    print(f"  Capital atual:    ${risk_summary['current_capital']:>10,.2f}")
    print(f"  PnL realizado:    ${summary.get('realized_pnl', 0.0):>+10.2f}")
    print(f"  Trades abertos:   {summary.get('open_trades', 0):>10}")
    print(f"  Trades hoje:      {risk_summary['trades_today']:>10}")
    print()

    # Verifica que todos os ciclos foram seguros
    unsafe = [r for r in results if not r.was_safe]
    if unsafe:
        print(f"  ⚠️  ATENÇÃO: {len(unsafe)} ciclo(s) não seguros detectados!")
    else:
        print("  ✅ Todos os ciclos foram executados com segurança.")

    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
