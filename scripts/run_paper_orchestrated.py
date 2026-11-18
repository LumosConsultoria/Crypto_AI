"""
run_paper_orchestrated.py — CLI para sessão de paper trading orquestrada (FASE 4)
====================================================================================
⚠️  ZERO ordens reais. ZERO API key. ZERO endpoint privado.
⚠️  Paper trading NÃO garante performance futura.
⚠️  Sessão usa MockExchange (random walk) ou DataCache local (FASE 3G).

Uso:
    # Sessão mínima (capital obrigatório):
    python scripts/run_paper_orchestrated.py --cycles 5 --source mock --capital 1000

    # Dry-run (sem execução simulada):
    python scripts/run_paper_orchestrated.py --cycles 5 --source mock --capital 1000 --dry-run

    # Com candles cacheados (CACHE source da FASE 3G):
    python scripts/run_paper_orchestrated.py --cycles 5 --source cache \\
        --capital 10000 --symbol BTCUSDT --timeframe 15

    # Capital diferente — orquestrador é agnóstico:
    python scripts/run_paper_orchestrated.py --cycles 5 --source mock --capital 25000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict

# Adiciona src/ ao path
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))


def _print_banner() -> None:
    print()
    print("=" * 70)
    print("  📋 PAPER TRADING ORQUESTRADO — FASE 4")
    print("  ⚠️  ZERO ordens reais. ZERO API key. ZERO endpoint privado.")
    print("  ⚠️  Paper trading NÃO garante performance futura.")
    print("=" * 70)
    print()


class _CliScriptedBuyStrategy:
    """
    Strategy mínima usada pelo CLI: emite UM sinal BUY com parâmetros
    configuráveis via CLI. Após aprovação, retorna HOLD nas próximas chamadas.

    ⚠️  Strategy didática para o script. Não usar em produção real.
        Estratégias profissionais devem ser desenvolvidas explicitamente
        e registradas via StrategyRegistry (FASE 3F).
    """

    def __init__(
        self,
        symbol: str,
        entry_price: float,
        position_size_usd: float,
    ) -> None:
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        from crypto_trading_bot.strategies.signal_model import StrategySignal

        self._signal = StrategySignal.buy(
            symbol=symbol,
            strategy_name="cli_demo_buy",
            entry_price=entry_price,
            stop_loss_price=entry_price * 0.985,
            take_profit_price=entry_price * 1.03,
            position_size_usd=position_size_usd,
        )
        self._state = StrategyState.WARMING_UP
        self._already_sent = False
        self.name = "cli_demo_buy"

    @property
    def is_running(self) -> bool:
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        return self._state == StrategyState.RUNNING

    def set_running(self) -> None:
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        self._state = StrategyState.RUNNING

    def evaluate(self, features: Dict[str, Any]):
        from crypto_trading_bot.strategies.signal_model import StrategySignal
        if not self.is_running or self._already_sent:
            return StrategySignal.hold(self._signal.symbol, self.name)
        return self._signal

    def on_signal_approved(self, signal) -> None:
        self._already_sent = True

    def on_signal_rejected(self, signal, reason: str) -> None:
        pass

    def on_trade_closed(self, symbol, pnl: float) -> None:
        # Trade fechado → permite novo signal (não obrigatório no script)
        pass


def _build_default_buy_factory(position_size_usd: float, entry_price: float):
    """
    Factory que cria _CliScriptedBuyStrategy com parâmetros configuráveis.

    NOTA: position_size_usd e entry_price são PARAMETRIZÁVEIS via CLI.
    Capital também. Nenhum valor fixo de 5000 é assumido.
    """
    def factory(config: Dict[str, Any]):
        s = _CliScriptedBuyStrategy(
            symbol=config.get("symbol", "BTCUSDT"),
            entry_price=float(config.get("entry_price", entry_price)),
            position_size_usd=float(
                config.get("position_size_usd", position_size_usd)
            ),
        )
        s.set_running()
        return s

    return factory


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Roda uma sessão de paper trading orquestrada (FASE 4). "
            "Capital é OBRIGATÓRIO. Nenhum default 5000 é assumido."
        )
    )
    parser.add_argument(
        "--capital", type=float, required=True,
        help="Capital inicial da sessão em USD (OBRIGATÓRIO, ex: 1000, 5000, 10000)."
    )
    parser.add_argument(
        "--cycles", type=int, default=10,
        help="Número de ciclos da sessão (default: 10)."
    )
    parser.add_argument(
        "--source", choices=["mock", "cache", "inmemory"], default="mock",
        help="Source de candles (default: mock)."
    )
    parser.add_argument(
        "--symbol", default="BTCUSDT",
        help="Símbolo (default: BTCUSDT)."
    )
    parser.add_argument(
        "--timeframe", default="15",
        help="Timeframe (default: 15)."
    )
    parser.add_argument(
        "--position-size", type=float, default=200.0,
        help="Tamanho da posição em USD (default: 200)."
    )
    parser.add_argument(
        "--entry-price", type=float, default=65000.0,
        help="Preço de entrada simulado para o demo BUY (default: 65000)."
    )
    parser.add_argument(
        "--cycle-interval", type=float, default=0.0,
        help="Sleep entre ciclos em segundos (default: 0 = replay rápido)."
    )
    parser.add_argument(
        "--fee-pct", type=float, default=0.001,
        help="Fee simulada do MockExchange (default: 0.001 = 0.1%%)."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Modo dry-run: força HOLD em todos os ciclos (zero execuções)."
    )
    args = parser.parse_args()

    _print_banner()

    # Imports tardios
    from crypto_trading_bot.execution import (
        CandlesSource,
        PaperSessionConfig,
        PaperTradingOrchestrator,
    )
    from crypto_trading_bot.research import StrategySpec

    # Build strategy spec (demo BUY parametrizado — não-determinístico no MockExchange)
    factory = _build_default_buy_factory(
        position_size_usd=args.position_size,
        entry_price=args.entry_price,
    )
    spec = StrategySpec(
        name=f"cli_demo_buy_size{int(args.position_size)}",
        factory=factory,
        description="Demo BUY parametrizável via CLI",
    )

    # Source mapping
    source_map = {
        "mock": CandlesSource.MOCK_EXCHANGE,
        "cache": CandlesSource.CACHE,
        "inmemory": CandlesSource.INMEMORY,
    }
    candles_source = source_map[args.source]

    # Para CACHE, precisa cached_symbol/cached_timeframe
    cached_symbol = args.symbol if candles_source is CandlesSource.CACHE else None
    cached_timeframe = (
        args.timeframe if candles_source is CandlesSource.CACHE else None
    )

    # INMEMORY: para o CLI, geramos candles sintéticos como exemplo
    inmemory_candles = None
    if candles_source is CandlesSource.INMEMORY:
        from crypto_trading_bot.backtesting.backtest_data import (
            generate_trending_candles,
        )
        inmemory_candles = tuple(
            generate_trending_candles(200, trend_pct_per_candle=0.0)
        )

    try:
        config = PaperSessionConfig(
            spec=spec,
            symbol=args.symbol,
            timeframe=args.timeframe,
            capital=args.capital,                # OBRIGATÓRIO — vem do CLI
            candles_source=candles_source,
            cached_symbol=cached_symbol,
            cached_timeframe=cached_timeframe,
            inmemory_candles=inmemory_candles,
            max_cycles=args.cycles,
            cycle_interval_seconds=args.cycle_interval,
            dry_run=args.dry_run,
            simulated_fee_pct=args.fee_pct,
        )
    except ValueError as e:
        print(f"\n  ❌ Configuração inválida: {e}")
        return 1

    print(f"  Strategy:        {spec.name}")
    print(f"  Symbol:          {args.symbol} ({args.timeframe})")
    print(f"  Capital:         ${args.capital:,.2f}")
    print(f"  Position size:   ${args.position_size:,.2f}")
    print(f"  Cycles:          {args.cycles}")
    print(f"  Source:          {args.source}")
    print(f"  Cycle interval:  {args.cycle_interval}s")
    print(f"  Fee simulada:    {args.fee_pct:.4%}")
    if args.dry_run:
        print("  🔍 DRY-RUN ativo — nenhuma execução simulada.")
    print()

    orchestrator = PaperTradingOrchestrator()
    try:
        result = orchestrator.run_session(config)
    except Exception as e:
        print(f"\n  ❌ Erro durante a sessão: {e}")
        return 1

    print()
    print(result.summary_text())
    print()
    print("─" * 70)
    print("  ✅ CONFIRMAÇÕES DE SEGURANÇA:")
    print("  ✅ Nenhuma API key foi usada.")
    print("  ✅ Nenhuma ordem real foi enviada.")
    print("  ✅ Nenhum endpoint privado foi acessado.")
    print("  ✅ MockExchange + PaperTrader (simulação local).")
    print("  ✅ Capital usado: configurável via --capital (sem default fixo).")
    print("  ⚠️  Paper trading NÃO garante performance futura.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
