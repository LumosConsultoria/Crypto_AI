"""
run_testnet_diagnostic.py — CLI de diagnóstico de execução testnet
======================================================================
⚠️  POR PADRÃO: --dry-run está ATIVO. Nenhuma ordem é enviada.
⚠️  Para enviar ordem testnet REAL, todas as 3 flags abaixo são EXIGIDAS:
        --execute-testnet-order
        --confirm-testnet-execution
        --i-understand-this-is-testnet

⚠️  Mesmo com todas as flags, MAINNET continua bloqueado.
⚠️  Testnet usa credentials reais (gere em https://testnet.bybit.com).

Modos:
    1. Default (dry-run):        simula tudo sem chamar API.
    2. --safe-check:             chama APENAS get_balance() (auth check).
    3. As 3 flags acima juntas:  envia 1 ordem testnet com sizing CLI.

Uso típico (em ordem progressiva de risco):
    # 1) Verifica config local sem rede
    python scripts/run_testnet_diagnostic.py

    # 2) Verifica autenticação testnet sem ordem
    python scripts/run_testnet_diagnostic.py --safe-check

    # 3) Envia 1 ordem testnet (exige todas as 3 flags + sizing explícito)
    python scripts/run_testnet_diagnostic.py \\
        --execute-testnet-order \\
        --confirm-testnet-execution \\
        --i-understand-this-is-testnet \\
        --symbol BTCUSDT --side buy \\
        --position-size 5 --entry-price 65000 \\
        --stop-loss 64000 --take-profit 67000 \\
        --capital 1000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))


def _print_banner(dry_run: bool, will_send_order: bool) -> None:
    print()
    print("=" * 70)
    print("  🧪 BYBIT TESTNET DIAGNOSTIC — FASE 5")
    print("  ⚠️  ZERO operações em MAINNET. ZERO ordens live.")
    if will_send_order:
        print("  ⚠️  MODE: SEND REAL TESTNET ORDER (autorizado por 3 flags).")
    elif dry_run:
        print("  ✅ MODE: DRY-RUN (nenhuma ordem enviada, nenhuma rede usada).")
    else:
        print("  ⚠️  MODE: SAFE-CHECK (apenas get_balance, sem ordens).")
    print("=" * 70)
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnóstico de execução testnet. Dry-run por padrão. "
            "Envio de ordem exige 3 flags explícitas + sizing explícito."
        )
    )
    # Modos
    parser.add_argument(
        "--safe-check", action="store_true",
        help="Apenas chama get_balance() (autenticação check). Sem ordens."
    )
    # Triple-lock para envio de ordem
    parser.add_argument(
        "--execute-testnet-order", action="store_true",
        help="Flag 1/3 para enviar ordem testnet real."
    )
    parser.add_argument(
        "--confirm-testnet-execution", action="store_true",
        help="Flag 2/3 — confirmação explícita exigida pelo ModeGuard."
    )
    parser.add_argument(
        "--i-understand-this-is-testnet", action="store_true",
        help=(
            "Flag 3/3 — confirmação humana de que entende que ESTA ORDEM "
            "será enviada à BYBIT TESTNET com credentials reais."
        ),
    )
    # Parâmetros da ordem (OBRIGATÓRIOS quando --execute-testnet-order)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--side", choices=["buy", "sell"], default="buy")
    parser.add_argument(
        "--position-size", type=float,
        help="Tamanho da posição em USD. OBRIGATÓRIO para envio de ordem.",
    )
    parser.add_argument(
        "--entry-price", type=float,
        help="Preço de entrada (do signal). OBRIGATÓRIO para envio.",
    )
    parser.add_argument(
        "--stop-loss", type=float,
        help="Stop loss price. OBRIGATÓRIO para envio (RiskEngine exige)."
    )
    parser.add_argument("--take-profit", type=float, default=None)
    parser.add_argument(
        "--capital", type=float,
        help="Capital usado para inicializar RiskEngine. OBRIGATÓRIO para envio.",
    )
    parser.add_argument("--leverage", type=float, default=1.0)

    args = parser.parse_args()

    # Determina o modo
    will_send_order = bool(args.execute_testnet_order)
    is_safe_check = bool(args.safe_check) and not will_send_order
    is_dry_run = not (will_send_order or is_safe_check)

    _print_banner(dry_run=is_dry_run, will_send_order=will_send_order)

    # Imports tardios
    from crypto_trading_bot.config.exchange_config import ExchangeConfig
    from crypto_trading_bot.config.settings import get_settings
    from crypto_trading_bot.core.mode_guard import ModeGuard
    from crypto_trading_bot.exchange.bybit_client import BybitClient
    from crypto_trading_bot.execution import BybitTestnetExecutor
    from crypto_trading_bot.risk.risk_engine import (
        OrderSide,
        RiskEngine,
        TradingSignal,
    )

    settings = get_settings()
    guard = ModeGuard(settings=settings)
    exchange = ExchangeConfig()

    # Verificação preliminar (sem chamar nada)
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
            print(f"  ❌ Faltam flags: {missing}")
            return 1

        # Sizing OBRIGATÓRIO (sem hardcode)
        required = [
            ("--position-size", args.position_size),
            ("--entry-price", args.entry_price),
            ("--stop-loss", args.stop_loss),
            ("--capital", args.capital),
        ]
        for name, val in required:
            if val is None or val <= 0:
                print(f"  ❌ {name} é OBRIGATÓRIO e > 0 para enviar ordem.")
                return 1

    # Cria cliente Bybit (com credentials se presentes; testnet only)
    api_key = (
        exchange.api_key.get_secret_value() if exchange.api_key else None
    )
    api_secret = (
        exchange.api_secret.get_secret_value() if exchange.api_secret else None
    )
    recv_window = 5000   # Bybit default; pode vir de Settings em fase futura
    client = BybitClient(
        use_testnet=True,                # SEMPRE testnet neste script
        api_key=api_key,
        api_secret=api_secret,
        recv_window=recv_window,
    )

    # RiskEngine: capital vem do CLI (ou default seguro de 100 USD para safe-check)
    capital = args.capital if args.capital else 100.0
    risk = RiskEngine(initial_capital=capital)

    # Executor
    executor = BybitTestnetExecutor(
        client=client,
        mode_guard=guard,
        risk_engine=risk,
        confirm_testnet_execution=bool(args.confirm_testnet_execution),
    )

    # ===== MODOS =====
    if is_dry_run:
        print("  🔍 DRY-RUN: nenhuma chamada de rede será feita.")
        # Apenas mostra config atual
        print()
        print(f"  TRADING_MODE                = {settings.trading_mode.value}")
        print(f"  ENABLE_TESTNET_EXECUTION    = {settings.enable_testnet_execution}")
        print(f"  exchange.use_testnet        = {exchange.use_testnet}")
        print(f"  credentials present in .env = {exchange.has_credentials}")
        print(f"  modeguard.is_safe           = {guard.is_safe}")
        print(f"  modeguard.is_testnet_execution_allowed = "
              f"{guard.is_testnet_execution_allowed}")
        # Simula safe_check_only com dry_run=True
        check = executor.safe_check_only(dry_run=True)
        print()
        print(f"  safe_check(dry_run=True):   success={check.success} | "
              f"reason={check.reason}")
        return 0

    if is_safe_check:
        print("  🛡️  SAFE-CHECK: chamando get_balance() para validar autenticação.")
        result = executor.safe_check_only(dry_run=False)
        print()
        print(f"  Result: success={result.success}")
        print(f"  Reason: {result.reason}")
        return 0 if result.success else 1

    # ===== ENVIO DE ORDEM REAL EM TESTNET =====
    # (já validamos triple-lock + sizing acima)
    print("  🚨 ENVIANDO ORDEM REAL EM TESTNET (não live):")
    print(f"     Symbol:        {args.symbol}")
    print(f"     Side:          {args.side}")
    print(f"     Position size: ${args.position_size:,.2f}")
    print(f"     Entry price:   {args.entry_price}")
    print(f"     Stop loss:     {args.stop_loss}")
    print(f"     Take profit:   {args.take_profit}")
    print(f"     Capital:       ${args.capital:,.2f}")
    print(f"     Leverage:      {args.leverage}x")
    print()

    # Constrói TradingSignal e valida no RiskEngine
    signal = TradingSignal(
        symbol=args.symbol,
        side=OrderSide.BUY if args.side == "buy" else OrderSide.SELL,
        entry_price=args.entry_price,
        stop_loss_price=args.stop_loss,
        take_profit_price=args.take_profit,
        position_size_usd=args.position_size,
        leverage=args.leverage,
        strategy_name="cli_testnet_diagnostic",
    )
    risk_result = risk.validate_signal(signal)
    if not risk_result.approved:
        print(f"  ❌ RiskEngine rejeitou: {risk_result.reason}")
        return 1

    result = executor.execute(risk_result, dry_run=False)
    print(f"  Result: success={result.success}")
    print(f"  Reason: {result.reason}")
    if result.trade is not None:
        print(f"  Trade:")
        print(f"     trade_id:    {result.trade.trade_id}")
        print(f"     order_id:    {result.trade.order_id}")
        print(f"     status:      {result.trade.status.value}")
        print(f"     qty:         {result.trade.qty}")
        print(f"     side:        {result.trade.side}")
    print()
    print("=" * 70)
    print("  ✅ CONFIRMAÇÕES:")
    print("  ✅ Apenas TESTNET (sem mainnet, sem live).")
    print("  ✅ Nenhuma API key foi logada (use_redaction).")
    print("  ⚠️  Testnet NÃO garante performance futura.")
    print("=" * 70)
    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
