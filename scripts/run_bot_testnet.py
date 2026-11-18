"""
run_bot_testnet.py — CLI: BotEngine + BybitTestnetExecutor (FASE 6)
=====================================================================
Roda o ciclo completo do BotEngine (dados → features → estratégia → risco →
EXECUTOR) usando o BybitTestnetExecutor via TestnetExecutorBotAdapter, em vez
do PaperTrader.

⚠️  POR PADRÃO: dry_run está ATIVO. Nenhuma ordem é enviada à Bybit.
⚠️  Para enviar ordens testnet REAIS, TODAS as 3 flags abaixo são EXIGIDAS:
        --execute-testnet-order
        --confirm-testnet-execution
        --i-understand-this-is-testnet
⚠️  Mesmo com as 3 flags, MAINNET/LIVE continua BLOQUEADO por design.
⚠️  Testnet usa credentials reais (gere em https://testnet.bybit.com).

🚦 GATE MANUAL OBRIGATÓRIO (FASE 5):
    Antes de QUALQUER uso com dry_run=False contra a testnet externa, valide a
    autenticação manualmente:
        python scripts/run_testnet_diagnostic.py --safe-check
    A implementação offline (mocks) NÃO substitui essa validação manual.

⚠️  Candles: este script usa MockExchange (random walk) para alimentar a
    estratégia — o objetivo é exercitar a INTEGRAÇÃO BotEngine ↔ executor,
    não fazer trading real baseado em mercado real.

Modos (ordem progressiva de risco):
    1. Default (dry-run):    roda ciclos; executor simula (não envia ordem).
    2. As 3 flags acima:     executor envia ordens testnet REAIS por ciclo.

Uso típico:
    # 1) Dry-run (default): prova a fiação BotEngine ↔ testnet executor
    python scripts/run_bot_testnet.py --capital 1000 --cycles 3

    # 2) Envio real em testnet (exige 3 flags + .env testnet configurado)
    python scripts/run_bot_testnet.py \\
        --execute-testnet-order \\
        --confirm-testnet-execution \\
        --i-understand-this-is-testnet \\
        --capital 1000 --cycles 1 \\
        --symbol BTCUSDT --position-size 5 --entry-price 65000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))


def _print_banner(dry_run: bool) -> None:
    print()
    print("=" * 70)
    print("  🤖 BOTENGINE + BYBIT TESTNET EXECUTOR — FASE 6")
    print("  ⚠️  ZERO operações em MAINNET. ZERO ordens live.")
    if dry_run:
        print("  ✅ MODE: DRY-RUN (executor simula; nenhuma ordem enviada).")
    else:
        print("  🚨 MODE: ENVIO REAL EM TESTNET (autorizado por 3 flags).")
        print("  🚦 GATE: confirme que rodou run_testnet_diagnostic.py --safe-check")
    print("=" * 70)
    print()


class _CliScriptedBuyStrategy:
    """
    Strategy mínima para o script: emite UM sinal BUY parametrizável; após
    aprovação, retorna HOLD. Didática — não usar em produção.
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
            strategy_name="cli_bot_testnet_buy",
            entry_price=entry_price,
            stop_loss_price=entry_price * 0.985,
            take_profit_price=entry_price * 1.03,
            position_size_usd=position_size_usd,
        )
        self._state = StrategyState.WARMING_UP
        self._already_sent = False
        self.name = "cli_bot_testnet_buy"

    @property
    def is_running(self) -> bool:
        from crypto_trading_bot.strategies.base_strategy import StrategyState
        return self._state == StrategyState.RUNNING

    @property
    def state(self):
        return self._state

    @property
    def signal_count(self) -> int:
        return 1 if self._already_sent else 0

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
        pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Roda o BotEngine usando o BybitTestnetExecutor (FASE 6). "
            "Dry-run por padrão. Envio real exige 3 flags + .env testnet."
        )
    )
    # Triple-lock CLI para dry_run=False
    parser.add_argument(
        "--execute-testnet-order", action="store_true",
        help="Flag 1/3 para enviar ordens testnet reais (dry_run=False).",
    )
    parser.add_argument(
        "--confirm-testnet-execution", action="store_true",
        help="Flag 2/3 — confirmação exigida pelo ModeGuard.",
    )
    parser.add_argument(
        "--i-understand-this-is-testnet", action="store_true",
        help="Flag 3/3 — confirmação humana de envio à Bybit testnet.",
    )
    # Parâmetros gerais
    parser.add_argument(
        "--capital", type=float, required=True,
        help="Capital inicial do RiskEngine em USD (OBRIGATÓRIO).",
    )
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--timeframe", default="15")
    parser.add_argument("--position-size", type=float, default=5.0)
    parser.add_argument("--entry-price", type=float, default=65000.0)
    args = parser.parse_args()

    will_send_order = bool(args.execute_testnet_order)
    is_dry_run = not will_send_order

    _print_banner(dry_run=is_dry_run)

    # Imports tardios
    from crypto_trading_bot.config.exchange_config import ExchangeConfig
    from crypto_trading_bot.config.settings import get_settings
    from crypto_trading_bot.core.bot_engine import BotEngine
    from crypto_trading_bot.core.mode_guard import ModeGuard
    from crypto_trading_bot.data.feature_engine import FeatureEngine
    from crypto_trading_bot.data.market_data import MarketDataService
    from crypto_trading_bot.exchange.bybit_client import BybitClient
    from crypto_trading_bot.exchange.mock_exchange import MockExchange
    from crypto_trading_bot.execution import (
        BybitTestnetExecutor,
        TestnetExecutorBotAdapter,
    )
    from crypto_trading_bot.risk.risk_engine import RiskEngine

    settings = get_settings()
    guard = ModeGuard(settings=settings)
    exchange = ExchangeConfig()

    print(f"  TRADING_MODE              = {settings.trading_mode.value}")
    print(f"  EXECUTOR_TYPE             = {settings.executor_type}")
    print(f"  ENABLE_TESTNET_EXECUTION  = {settings.enable_testnet_execution}")
    print(f"  exchange.use_testnet      = {exchange.use_testnet}")
    print(f"  credentials present       = {exchange.has_credentials}")
    print(f"  modeguard.is_safe         = {guard.is_safe}")
    print(f"  testnet_exec_allowed      = {guard.is_testnet_execution_allowed}")
    print()

    if will_send_order:
        # Triple-lock CLI: TODAS as 3 flags obrigatórias
        missing = []
        if not args.execute_testnet_order:
            missing.append("--execute-testnet-order")
        if not args.confirm_testnet_execution:
            missing.append("--confirm-testnet-execution")
        if not args.i_understand_this_is_testnet:
            missing.append("--i-understand-this-is-testnet")
        if missing:
            print(f"  ❌ Faltam flags para envio real: {missing}")
            return 1
        print("  🚨 dry_run=False — ordens REAIS serão enviadas à Bybit TESTNET.")
        print("  🚦 Confirme que rodou: run_testnet_diagnostic.py --safe-check")
        print()

    # Cliente Bybit (SEMPRE testnet; credentials apenas se presentes)
    api_key = (
        exchange.api_key.get_secret_value() if exchange.api_key else None
    )
    api_secret = (
        exchange.api_secret.get_secret_value() if exchange.api_secret else None
    )
    client = BybitClient(
        use_testnet=True,
        api_key=api_key,
        api_secret=api_secret,
        recv_window=5000,
    )

    # Pipeline: MockExchange para candles (offline) + RiskEngine + estratégia
    risk = RiskEngine(initial_capital=args.capital)
    mock_exchange = MockExchange(initial_balance_usdt=args.capital)
    market_data = MarketDataService(
        exchange=mock_exchange,
        default_symbol=args.symbol,
        default_timeframe=args.timeframe,
    )
    feature_engine = FeatureEngine()
    strategy = _CliScriptedBuyStrategy(
        symbol=args.symbol,
        entry_price=args.entry_price,
        position_size_usd=args.position_size,
    )
    strategy.set_running()

    # Executor testnet + adapter (dry_run obrigatório, decidido pelas flags)
    testnet_executor = BybitTestnetExecutor(
        client=client,
        mode_guard=guard,
        risk_engine=risk,
        confirm_testnet_execution=bool(args.confirm_testnet_execution),
    )
    adapter = TestnetExecutorBotAdapter(
        testnet_executor=testnet_executor,
        dry_run=is_dry_run,
    )

    # BotEngine com executor injetado (paper_trader=None — caminho FASE 6)
    engine = BotEngine(
        market_data_service=market_data,
        feature_engine=feature_engine,
        strategy=strategy,
        risk_engine=risk,
        executor=adapter,
        settings=settings,
        mode_guard=guard,
    )

    print(f"  ▶️  Rodando {args.cycles} ciclo(s) | symbol={args.symbol} | "
          f"capital=${args.capital:,.2f} | dry_run={is_dry_run}")
    print()

    for i in range(args.cycles):
        result = engine.run_once()
        line = (
            f"  Ciclo #{result.cycle} | action={result.action} | "
            f"risk={result.risk_approved} | exec={result.executed}"
        )
        if result.executor_result is not None:
            er = result.executor_result
            line += (
                f" | success={getattr(er, 'success', '?')} | "
                f"dry_run={getattr(er, 'dry_run', '?')}"
            )
        print(line)

    print()
    print("=" * 70)
    print("  ✅ CONFIRMAÇÕES:")
    print("  ✅ Apenas TESTNET (sem mainnet, sem live).")
    print("  ✅ Nenhuma API key foi logada (log_redaction + SecretStr).")
    print("  ✅ PaperTrader continua sendo o default do BotEngine.")
    if is_dry_run:
        print("  ✅ DRY-RUN: nenhuma ordem foi enviada à Bybit.")
    print("  ⚠️  Testnet NÃO garante performance futura.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
