"""
run_bybit_demo_diagnostic.py — Bybit Demo Trading Diagnostic (FASE 9 Fatia 4B)
================================================================================
⚠️  POR PADRÃO: dry-run. Nenhuma rede é tocada. Nenhuma ordem é enviada.
⚠️  Demo Trading é AMBIENTE SEPARADO de Testnet (endpoint https://api-demo.bybit.com).
⚠️  Mainnet/live continuam BLOQUEADOS independentemente das flags abaixo.
⚠️  Bybit Demo Trading NÃO garante performance futura.

EVOLUÇÃO DAS FATIAS:
    Fatia 1: ExchangeConfig + BybitClient(environment="demo").
    Fatia 2: TradingMode.DEMO, ModeGuard.assert_demo_execution_allowed,
             ProviderRegistry com bybit_demo_linear=CANDIDATE_REVALIDATION.
    Fatia 3: --safe-check chama get_balance() REAL via client.
    Fatia 4A: BybitDemoExecutor dedicado; safe-check passa pelo executor;
              flags de ordem demo registradas.
    Fatia 4B (atual): execute(dry_run=False) IMPLEMENTADO com place_market_order
                      + reconciliação. `--execute-demo-order` envia ordem real
                      demo após TODAS as 7 travas em camadas.
                      `bybit_demo_linear` migrou para OPT_IN no registry
                      (exige confirm_provider=True).

ESCOPO DA FATIA 4B:
    `--execute-demo-order --confirm-demo-execution --i-understand-this-is-demo`
    + sizing explícito → ENVIO REAL via BybitDemoExecutor.execute(dry_run=False).
    Sete travas independentes: triple-flag-lock CLI + sizing > 0 + ModeGuard
    triple-lock + endpoint == api-demo.bybit.com + credentials + provider gate
    (confirm_provider=True) + RiskEngine.validate_signal. Falha em qualquer
    trava aborta ANTES de qualquer chamada de rede.

⚠️  Execução real fica nas mãos do operador. Nenhuma ordem real foi enviada
    durante a implementação automatizada — testes 100% offline mockados.

Modos:
    1. Default (sem flags) ou --dry-run:    mostra config local. ZERO rede, ZERO ordem.
    2. --safe-check --confirm-demo-execution:
         Após travas: BybitDemoExecutor.safe_check_only(dry_run=False)
         → get_balance() em api-demo.bybit.com. READ-ONLY.
    3. --execute-demo-order ... (3 flags + sizing > 0):
         Após as 7 travas: BybitDemoExecutor.execute(dry_run=False)
         → place_market_order REAL em api-demo.bybit.com (gated).

Uso típico:
    # 1) Dry-run: valida config local sem rede e sem ordem
    python scripts/run_bybit_demo_diagnostic.py

    # 2) Safe-check REAL (read-only get_balance, sem ordem)
    python scripts/run_bybit_demo_diagnostic.py --safe-check --confirm-demo-execution

    # 3) Ordem demo REAL (gated por 7 travas; envia em api-demo.bybit.com)
    python scripts/run_bybit_demo_diagnostic.py \\
        --execute-demo-order --confirm-demo-execution --i-understand-this-is-demo \\
        --symbol BTCUSDT --side buy \\
        --capital 1000 --position-size 5 --entry-price 65000 \\
        --stop-loss 64000 --leverage 1.0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))


def _print_banner(mode: str) -> None:
    print()
    print("=" * 70)
    print("  🧪 BYBIT DEMO TRADING DIAGNOSTIC — FASE 9 Fatia 4B")
    print("  ⚠️  ZERO operações em MAINNET. ZERO ordens live.")
    print("  ⚠️  Demo Trading ≠ Testnet (endpoint api-demo.bybit.com).")
    if mode == "dry_run":
        print("  ✅ MODE: DRY-RUN (apenas mostra config local; sem rede; sem ordem).")
    elif mode == "safe_check":
        print("  🛡️  MODE: SAFE-CHECK REAL — read-only get_balance() via executor.")
    elif mode == "prepare_order":
        print("  🛠️  MODE: PREFLIGHT — read-only; propõe ordem mínima sem enviar.")
    elif mode == "prepare_v2":
        print("  📋 MODE: DEMO v2 READINESS — OFFLINE; monta payload SL+TP sem rede.")
    elif mode == "post_session_check":
        print("  🔎 MODE: POST-SESSION CHECK — READ-ONLY; sem ordem, sem cancel, sem close.")
    elif mode == "execute_order":
        print("  🚨 MODE: ORDEM DEMO REAL — GATED (7 travas em camadas).")
        print("  🚨 Envio à api-demo.bybit.com após TODAS as travas passarem.")
    print("=" * 70)
    print()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnóstico de Bybit Demo Trading (FASE 9 Fatia 4B). Default: dry-run. "
            "--safe-check chama BybitDemoExecutor.safe_check_only(dry_run=False) "
            "em api-demo.bybit.com (read-only). "
            "--execute-demo-order envia ordem REAL após as 7 travas passarem."
        )
    )
    # --dry-run é explícito mas idêntico ao default (sem flags).
    parser.add_argument(
        "--dry-run", action="store_true",
        help="(default behavior — flag aceita por compat) Apenas mostra config local.",
    )
    # Modo safe-check: chama get_balance() via executor após validar travas.
    parser.add_argument(
        "--safe-check", action="store_true",
        help=(
            "Chama BybitDemoExecutor.safe_check_only(dry_run=False) em "
            "api-demo.bybit.com APÓS validar: triple-lock demo + endpoint=api-demo "
            "+ credentials. Read-only."
        ),
    )
    # Modo preflight: coleta tudo da API automaticamente e propõe ordem mínima
    parser.add_argument(
        "--prepare-demo-order", action="store_true",
        help=(
            "Preflight automático READ-ONLY: coleta instruments-info + orderbook + "
            "ticker + balance + positions + open orders e propõe ordem mínima "
            "válida. NUNCA envia ordem. Resultado inclui comando final sugerido."
        ),
    )
    # FASE 13 — Demo v2 readiness (OFFLINE: sem rede, sem API).
    parser.add_argument(
        "--prepare-demo-v2-order", action="store_true",
        help=(
            "Demo v2 READINESS — OFFLINE. Monta e imprime payload de ordem "
            "Demo v2 (entrada + SL + TP) usando argumentos CLI ou defaults "
            "sintéticos. NÃO chama rede. NÃO envia ordem. Execução real fica "
            "para FASE 14 atrás de aprovação humana."
        ),
    )
    # FASE 15 — Post-session check (read-only).
    parser.add_argument(
        "--post-session-check", action="store_true",
        help=(
            "POST-SESSION CHECK — READ-ONLY. Valida pós-sessão demo: "
            "posições residuais, open orders residuais, wallet balance vs "
            "baseline opcional. NÃO envia ordem. NÃO fecha posição. "
            "NÃO cancela ordem. NÃO chama endpoint de escrita."
        ),
    )
    parser.add_argument(
        "--baseline-balance", type=float, default=None,
        help=(
            "(--post-session-check) Saldo USDT de referência antes da sessão. "
            "Quando informado, mostra delta vs. saldo atual. Opcional."
        ),
    )
    parser.add_argument(
        "--confirm-demo-execution", action="store_true",
        help="Confirmação explícita exigida pelo ModeGuard/Executor para qualquer chamada demo.",
    )
    # Flags de ordem demo — habilitadas em Fatia 4B (com sete travas).
    parser.add_argument(
        "--execute-demo-order", action="store_true",
        help=(
            "Flag 1/3 para enviar ordem demo REAL. Após as 7 travas "
            "(triple-flag + sizing + ModeGuard + endpoint + credentials + "
            "provider + RiskEngine), o script chama place_market_order em "
            "api-demo.bybit.com."
        ),
    )
    parser.add_argument(
        "--i-understand-this-is-demo", action="store_true",
        help=(
            "Flag 3/3 para enviar ordem demo REAL. Confirmação explícita "
            "de que o operador entende que esta ordem vai à Bybit Demo Trading "
            "(api-demo.bybit.com)."
        ),
    )
    # Parâmetros de sizing — registrados para futura ordem mínima demo.
    # ⚠️  Nenhum default operacional perigoso. Se --execute-demo-order for
    #     usado, todos serão exigidos > 0 (mas o execute() ainda bloqueia).
    parser.add_argument("--symbol", default="BTCUSDT",
                        help="Símbolo (default: BTCUSDT).")
    parser.add_argument("--side", choices=["buy", "sell"], default="buy",
                        help="Lado da ordem (buy/sell).")
    parser.add_argument(
        "--capital", type=float, default=None,
        help="Capital usado para inicializar RiskEngine. OBRIGATÓRIO para ordem futura.",
    )
    parser.add_argument(
        "--position-size", type=float, default=None,
        help="Tamanho da posição em USD. OBRIGATÓRIO para ordem futura.",
    )
    parser.add_argument(
        "--entry-price", type=float, default=None,
        help="Preço de entrada (do signal). OBRIGATÓRIO para ordem futura.",
    )
    parser.add_argument(
        "--stop-loss", type=float, default=None,
        help="Stop loss price. OBRIGATÓRIO para ordem futura (RiskEngine exige).",
    )
    parser.add_argument(
        "--take-profit", type=float, default=None,
        help="Take profit price (opcional na futura ordem mínima).",
    )
    parser.add_argument(
        "--leverage", type=float, default=None,
        help="Alavancagem do sinal. OBRIGATÓRIA para ordem futura.",
    )

    args = parser.parse_args(argv)

    # Determinação de modo
    wants_real_order = bool(args.execute_demo_order)
    wants_safe_check = bool(args.safe_check)
    wants_prepare = bool(args.prepare_demo_order)
    wants_prepare_v2 = bool(args.prepare_demo_v2_order)
    wants_post_session = bool(args.post_session_check)
    is_dry_run = not (
        wants_real_order or wants_safe_check or wants_prepare
        or wants_prepare_v2 or wants_post_session
    )

    if wants_real_order:
        _print_banner("execute_order")
    elif wants_prepare_v2:
        _print_banner("prepare_v2")
    elif wants_post_session:
        _print_banner("post_session_check")
    elif wants_prepare:
        _print_banner("prepare_order")
    elif wants_safe_check:
        _print_banner("safe_check")
    else:
        _print_banner("dry_run")

    # Imports tardios (caches respeitados; lru_cache do get_settings é singleton)
    from crypto_trading_bot.config.exchange_config import ExchangeConfig
    from crypto_trading_bot.config.settings import get_settings
    from crypto_trading_bot.core.mode_guard import ModeGuard, TradingModeError
    from crypto_trading_bot.exchange.bybit_client import BybitClient
    from crypto_trading_bot.execution import (
        BybitDemoExecutor,
        ProviderBlockedError,
        get_registry,
    )
    from crypto_trading_bot.logging_system.log_redaction import redact_sensitive
    from crypto_trading_bot.risk.risk_engine import (
        OrderSide,
        RiskEngine,
        TradingSignal,
    )

    settings = get_settings()
    guard = ModeGuard(settings=settings)
    exchange = ExchangeConfig()

    print(f"  TRADING_MODE                   = {settings.trading_mode.value}")
    print(f"  ENABLE_LIVE_TRADING            = {settings.enable_live_trading}")
    print(f"  ENABLE_TESTNET_EXECUTION       = {settings.enable_testnet_execution}")
    print(f"  ENABLE_DEMO_EXECUTION          = {settings.enable_demo_execution}")
    print(f"  EXECUTOR_TYPE                  = {settings.executor_type}")
    print(f"  PROVIDER_ID                    = {settings.provider_id}")
    print(f"  exchange.resolved_environment  = {exchange.resolved_environment}")
    print(f"  exchange.rest_url              = {exchange.rest_url}")
    print(f"  exchange.has_credentials       = {exchange.has_credentials}")
    print(f"  modeguard.is_safe              = {guard.is_safe}")
    print(f"  modeguard.is_demo              = {guard.is_demo}")
    print(f"  modeguard.is_demo_execution_allowed = {guard.is_demo_execution_allowed}")
    print()

    # ===== PREFLIGHT AUTOMÁTICO (read-only) =====
    if wants_prepare:
        # Trava 1: ModeGuard triple-lock (preflight chama endpoints privados)
        try:
            guard.assert_demo_execution_allowed(
                confirm_demo_execution=True,
                context="run_bybit_demo_diagnostic.prepare_order",
            )
        except TradingModeError as e:
            print(f"  ❌ ModeGuard bloqueou: {redact_sensitive(str(e))}")
            return 1

        # Trava 2: endpoint DEVE ser api-demo.bybit.com
        expected_endpoint = "https://api-demo.bybit.com"
        if exchange.rest_url != expected_endpoint:
            print(f"  ❌ Endpoint resolvido NÃO é {expected_endpoint}")
            print(f"     Resolvido: {exchange.rest_url}")
            print("     Ajuste BYBIT_USE_DEMO=true ou BYBIT_ENVIRONMENT=demo no .env.")
            return 1

        # Trava 3: credentials presentes
        if not exchange.has_credentials:
            print("  ❌ Credentials ausentes — preflight exige api_key/api_secret demo.")
            return 1

        # Tudo OK → construir client + RiskEngine + preflight
        from crypto_trading_bot.execution import BybitDemoPreflight

        api_key = (
            exchange.api_key.get_secret_value() if exchange.api_key else None
        )
        api_secret = (
            exchange.api_secret.get_secret_value() if exchange.api_secret else None
        )
        client = BybitClient(
            environment="demo",
            api_key=api_key,
            api_secret=api_secret,
            recv_window=exchange.recv_window,
        )

        # RiskEngine: capital baseline será sobrescrito pelo capital proposto;
        # iniciamos com valor pequeno só para validação local. Capital REAL
        # do RiskEngine vem do que o preflight propõe a partir da API.
        risk = RiskEngine(initial_capital=100.0)

        preflight = BybitDemoPreflight(
            client=client,
            mode_guard=guard,
            risk_engine=risk,
            symbol="BTCUSDT",
            side="buy",
            leverage_target=1.0,
            confirm_demo_execution=True,
        )

        print()
        print("  🛠️  Coletando dados read-only da Bybit Demo...")
        report = preflight.run()

        try:
            client.close()
        except Exception:
            pass

        # Relatório sanitizado
        print()
        if report.ok:
            print("  ✅ PREFLIGHT OK — proposta de ordem mínima abaixo.")
        else:
            print(f"  ❌ PREFLIGHT ABORT: {report.abort_reason.value if report.abort_reason else 'unknown'}")
            print(f"     details: {redact_sensitive(report.abort_details)}")

        if report.market_info is not None:
            mi = report.market_info
            print()
            print("  📊 MARKET INFO:")
            print(f"     symbol:             {mi.symbol}")
            print(f"     category:           {mi.category}")
            print(f"     best_bid:           {mi.best_bid}")
            print(f"     best_ask:           {mi.best_ask}")
            print(f"     mid_price:          {mi.mid_price}")
            print(f"     last_price:         {mi.last_price}")
            print(f"     reference_price:    {mi.reference_price}")
            print(f"     min_order_qty:      {mi.min_order_qty}")
            print(f"     max_order_qty:      {mi.max_order_qty}")
            print(f"     qty_step:           {mi.qty_step}")
            print(f"     min_notional_value: {mi.min_notional_value}")
            print(f"     tick_size:          {mi.tick_size}")

        if report.account_state is not None:
            ac = report.account_state
            print()
            print("  👤 ACCOUNT STATE (read-only, sem secrets):")
            print(f"     wallet_balance_usdt:    {ac.wallet_balance_usdt}")
            print(f"     available_balance_usdt: {ac.available_balance_usdt}")
            print(f"     open_positions_count:   {ac.open_positions_count}")
            print(f"     open_orders_count:      {ac.open_orders_count}")
            print(f"     leverage_confirmable:   {ac.leverage_confirmable}")
            print(f"     leverage_value:         {ac.leverage_value}")

        if report.proposal is not None:
            p = report.proposal
            print()
            print("  🎯 ORDER PROPOSAL:")
            print(f"     symbol:           {p.symbol}")
            print(f"     side:             {p.side}")
            print(f"     reference_price:  {p.reference_price}")
            print(f"     qty:              {p.qty}")
            print(f"     position_size_usd:{p.position_size_usd:.6f}")
            print(f"     stop_loss:        {p.stop_loss}")
            print(f"     take_profit:      {p.take_profit}")
            print(f"     leverage:         {p.leverage}")
            print(f"     risk_usd:         {p.risk_usd:.6f}")
            print(f"     capital:          {p.capital:.2f}")

        if report.manual_confirmations_needed:
            print()
            print("  ⚠️  CONFIRMAÇÕES MANUAIS NECESSÁRIAS:")
            for note in report.manual_confirmations_needed:
                print(f"     - {note}")

        if report.ok and report.proposal is not None:
            p = report.proposal
            print()
            print("  📋 COMANDO FINAL SUGERIDO (NÃO EXECUTAR sem OK explícito):")
            print()
            cmd = (
                f"python scripts/run_bybit_demo_diagnostic.py `\n"
                f"    --execute-demo-order `\n"
                f"    --confirm-demo-execution `\n"
                f"    --i-understand-this-is-demo `\n"
                f"    --symbol {p.symbol} `\n"
                f"    --side {p.side} `\n"
                f"    --capital {p.capital:.2f} `\n"
                f"    --position-size {p.position_size_usd:.6f} `\n"
                f"    --entry-price {p.reference_price} `\n"
                f"    --stop-loss {p.stop_loss} `\n"
                f"    --leverage {p.leverage}"
            )
            print(cmd)
        print()
        print("=" * 70)
        print("  ✅ CONFIRMAÇÕES:")
        print("  ✅ Preflight é 100% READ-ONLY — nenhuma ordem enviada.")
        print("  ✅ Apenas DEMO TRADING (sem mainnet, sem live).")
        print("  ✅ Nenhuma key foi logada.")
        print("  ⚠️  Execução real continua exigindo OK explícito do operador.")
        print("  ⚠️  Bybit Demo Trading NÃO garante performance futura.")
        return 0 if report.ok else 1

    # ===== DEMO v2 READINESS (FASE 13: OFFLINE — monta payload sem rede) =====
    if wants_prepare_v2:
        # Defaults sintéticos seguros — sem hardcode operacional perigoso.
        # Se o operador passar valores via CLI, eles têm prioridade.
        sym = args.symbol or "BTCUSDT"
        side = args.side or "buy"
        entry = args.entry_price if args.entry_price else 65000.0
        size_usd = args.position_size if args.position_size else 200.0
        sl = args.stop_loss if args.stop_loss else (
            entry * 0.985 if side == "buy" else entry * 1.015
        )
        tp = args.take_profit if args.take_profit else (
            entry * 1.03 if side == "buy" else entry * 0.97
        )

        # Validações determinísticas de SL/TP por side (espelha preflight).
        errors: List[str] = []
        if side == "buy":
            if sl >= entry:
                errors.append(f"BUY: stop_loss ({sl}) deve ser < entry ({entry})")
            if tp <= entry:
                errors.append(f"BUY: take_profit ({tp}) deve ser > entry ({entry})")
        else:
            if sl <= entry:
                errors.append(f"SELL: stop_loss ({sl}) deve ser > entry ({entry})")
            if tp >= entry:
                errors.append(f"SELL: take_profit ({tp}) deve ser < entry ({entry})")
        if entry <= 0 or size_usd <= 0:
            errors.append("entry_price e position_size devem ser > 0")
        if errors:
            print("  ❌ READINESS ABORT — Inválido para Demo v2:")
            for err in errors:
                print(f"     - {err}")
            return 1

        qty = round(size_usd / entry, 8)

        # Monta payload V5 da Bybit (espelhando BybitClient.place_market_order).
        # Não chama rede. Apenas mostra o que seria enviado.
        payload = {
            "category": "linear",
            "symbol": sym,
            "side": "Buy" if side == "buy" else "Sell",
            "orderType": "Market",
            "qty": str(qty),
            "stopLoss": str(sl),
            "takeProfit": str(tp),
        }

        print("  📋 DEMO v2 READINESS — Payload OFFLINE (não envia):")
        print()
        print(f"     symbol:           {sym}")
        print(f"     side:             {side}")
        print(f"     entry_price:      {entry}")
        print(f"     position_size:    {size_usd:.6f} USD")
        print(f"     qty:              {qty}")
        print(f"     stop_loss:        {sl}")
        print(f"     take_profit:      {tp}")
        print(f"     R:R esperado:     1:{abs(tp - entry) / max(abs(entry - sl), 1e-9):.2f}")
        print()
        print("  📦 Payload V5 (preview, NÃO enviado):")
        for k, v in payload.items():
            print(f"     {k:<15} = {v!r}")
        print()
        print("=" * 70)
        print("  ✅ CONFIRMAÇÕES:")
        print("  ✅ OFFLINE — nenhuma chamada de rede.")
        print("  ✅ Nenhuma ordem enviada (demo/testnet/live).")
        print("  ✅ Nenhuma API key utilizada.")
        print("  ⚠️  Execução real fica para FASE 14, exige aprovação humana.")
        print("  ⚠️  SL/TP server-side na Bybit NÃO garante performance futura.")
        print("=" * 70)
        return 0

    # ===== POST-SESSION CHECK (FASE 15: READ-ONLY) =====
    if wants_post_session:
        # Trava 1: ModeGuard demo (precisamos do triple-lock pq chama endpoints
        # privados read-only; é equivalente ao --prepare-demo-order).
        try:
            guard.assert_demo_execution_allowed(
                confirm_demo_execution=True,
                context="run_bybit_demo_diagnostic.post_session_check",
            )
        except TradingModeError as e:
            print(f"  ❌ ModeGuard bloqueou: {redact_sensitive(str(e))}")
            return 1

        # Trava 2: endpoint
        expected_endpoint = "https://api-demo.bybit.com"
        if exchange.rest_url != expected_endpoint:
            print(f"  ❌ Endpoint resolvido NÃO é {expected_endpoint}")
            print(f"     Resolvido: {exchange.rest_url}")
            return 1

        # Trava 3: credentials
        if not exchange.has_credentials:
            print("  ❌ Credentials ausentes — post-session check exige API key demo.")
            return 1

        api_key = (
            exchange.api_key.get_secret_value() if exchange.api_key else None
        )
        api_secret = (
            exchange.api_secret.get_secret_value() if exchange.api_secret else None
        )
        client = BybitClient(
            environment="demo",
            api_key=api_key,
            api_secret=api_secret,
            recv_window=exchange.recv_window,
        )

        symbol = args.symbol or "BTCUSDT"
        print()
        print(f"  🔎 Coletando estado pós-sessão de {symbol}... (read-only)")

        # 1. Posições residuais
        positions_status: str
        positions_payload: list = []
        try:
            positions_payload = client.get_positions(symbol=symbol)
            non_zero = [
                p for p in positions_payload
                if isinstance(p, dict) and float(p.get("size", 0) or 0) > 0
            ]
            if non_zero:
                positions_status = f"⚠️  POSIÇÃO RESIDUAL DETECTADA ({len(non_zero)})"
            else:
                positions_status = "✅ sem posição residual"
        except Exception as e:
            from crypto_trading_bot.exchange.bybit_client import BybitAPIError
            if isinstance(e, BybitAPIError):
                positions_status = (
                    f"❌ BybitAPIError retCode={e.ret_code} "
                    f"retMsg='{redact_sensitive(e.ret_msg)}'"
                )
            else:
                positions_status = f"❌ falha: {type(e).__name__}"

        # 2. Open orders residuais
        open_orders_status: str
        open_orders_payload: list = []
        try:
            open_orders_payload = client.get_open_orders(symbol=symbol)
            if open_orders_payload:
                open_orders_status = (
                    f"⚠️  ORDENS ABERTAS DETECTADAS ({len(open_orders_payload)})"
                )
            else:
                open_orders_status = "✅ sem ordens abertas"
        except Exception as e:
            from crypto_trading_bot.exchange.bybit_client import BybitAPIError
            if isinstance(e, BybitAPIError):
                open_orders_status = (
                    f"❌ BybitAPIError retCode={e.ret_code} "
                    f"retMsg='{redact_sensitive(e.ret_msg)}'"
                )
            else:
                open_orders_status = f"❌ falha: {type(e).__name__}"

        # 3. Wallet balance + baseline opcional
        wallet_status: str
        wallet_balance_usdt: float | None = None
        try:
            balance = client.get_balance()
            # Bybit V5: result.list[0].coin[*] — parse defensivo.
            coins = []
            if isinstance(balance, dict):
                items = balance.get("list") or []
                if items and isinstance(items[0], dict):
                    coins = items[0].get("coin") or []
            for c in coins:
                if isinstance(c, dict) and c.get("coin") == "USDT":
                    try:
                        wallet_balance_usdt = float(c.get("walletBalance", 0))
                    except (TypeError, ValueError):
                        pass
                    break
            if wallet_balance_usdt is not None:
                wallet_status = f"USDT walletBalance = {wallet_balance_usdt:.4f}"
            else:
                wallet_status = "⚠️  USDT não encontrado na wallet"
        except Exception as e:
            from crypto_trading_bot.exchange.bybit_client import BybitAPIError
            if isinstance(e, BybitAPIError):
                wallet_status = (
                    f"❌ BybitAPIError retCode={e.ret_code} "
                    f"retMsg='{redact_sensitive(e.ret_msg)}'"
                )
            else:
                wallet_status = f"❌ falha: {type(e).__name__}"

        try:
            client.close()
        except Exception:
            pass

        # Relatório sanitizado
        print()
        print("  📋 POST-SESSION REPORT")
        print(f"     symbol:             {symbol}")
        print(f"     positions:          {positions_status}")
        print(f"     open_orders:        {open_orders_status}")
        print(f"     wallet:             {wallet_status}")

        # Delta vs baseline (se fornecido)
        if args.baseline_balance is not None and wallet_balance_usdt is not None:
            delta = wallet_balance_usdt - args.baseline_balance
            sign = "+" if delta >= 0 else ""
            print(
                f"     baseline_balance:   {args.baseline_balance:.4f} USDT"
            )
            print(f"     delta vs baseline:  {sign}{delta:.4f} USDT")

        print()
        print("=" * 70)
        print("  ✅ CONFIRMAÇÕES:")
        print("  ✅ Apenas chamadas READ-ONLY (get_positions, get_open_orders, get_balance).")
        print("  ✅ Nenhuma ordem enviada. Nenhum cancel. Nenhum close.")
        print("  ✅ Nenhuma key foi logada.")
        print("  ⚠️  Posição/ordens residuais (se houver) exigem ação manual via UI.")
        print("=" * 70)
        # Retorna 1 se houver posição/ordem residual ou erro grave
        has_residual = (
            "RESIDUAL DETECTADA" in positions_status
            or "ABERTAS DETECTADAS" in open_orders_status
        )
        has_error = "❌" in positions_status or "❌" in open_orders_status
        return 1 if (has_residual or has_error) else 0

    # ===== ORDEM DEMO REAL (FATIA 4B: gated mas LIBERADO) =====
    if wants_real_order:
        # Trava 1: triple-flag-lock completo
        missing_flags = []
        # args.execute_demo_order já é True (entramos aqui por isso)
        if not args.confirm_demo_execution:
            missing_flags.append("--confirm-demo-execution")
        if not args.i_understand_this_is_demo:
            missing_flags.append("--i-understand-this-is-demo")
        if missing_flags:
            print(f"  ❌ Triple-flag-lock incompleto. Faltam: {missing_flags}")
            return 1

        # Trava 2: sizing obrigatório > 0 (sem default operacional perigoso)
        required_sizing = [
            ("--capital", args.capital),
            ("--position-size", args.position_size),
            ("--entry-price", args.entry_price),
            ("--stop-loss", args.stop_loss),
            ("--leverage", args.leverage),
        ]
        for flag_name, val in required_sizing:
            if val is None or val <= 0:
                print(f"  ❌ {flag_name} é OBRIGATÓRIO e > 0 para enviar ordem demo.")
                print(f"     Recebido: {val}")
                return 1

        # Trava 3: ModeGuard triple-lock demo (early abort)
        try:
            guard.assert_demo_execution_allowed(
                confirm_demo_execution=True,
                context="run_bybit_demo_diagnostic.execute_demo_order",
            )
        except TradingModeError as e:
            print(f"  ❌ ModeGuard bloqueou: {redact_sensitive(str(e))}")
            return 1

        # Trava 4: endpoint DEVE ser api-demo.bybit.com
        expected_endpoint = "https://api-demo.bybit.com"
        if exchange.rest_url != expected_endpoint:
            print(f"  ❌ Endpoint resolvido NÃO é {expected_endpoint}")
            print(f"     Resolvido: {exchange.rest_url}")
            print("     Ajuste BYBIT_USE_DEMO=true ou BYBIT_ENVIRONMENT=demo no .env.")
            return 1

        # Trava 5: credentials presentes
        if not exchange.has_credentials:
            print("  ❌ Credentials ausentes — ordem demo exige api_key/api_secret.")
            return 1

        # Trava 6: provider gate (bybit_demo_linear OPT_IN exige confirm_provider=True)
        try:
            guard.assert_provider_allowed(
                "bybit_demo_linear",
                confirm_provider=True,
                context="run_bybit_demo_diagnostic.execute_demo_order",
            )
        except TradingModeError as e:
            print(f"  ❌ Provider bloqueado pelo registry: {redact_sensitive(str(e))}")
            return 1

        # Tudo OK → construir client, RiskEngine, signal, executor
        api_key = (
            exchange.api_key.get_secret_value() if exchange.api_key else None
        )
        api_secret = (
            exchange.api_secret.get_secret_value() if exchange.api_secret else None
        )
        client = BybitClient(
            environment="demo",
            api_key=api_key,
            api_secret=api_secret,
            recv_window=exchange.recv_window,
        )
        risk = RiskEngine(initial_capital=float(args.capital))

        # Constrói TradingSignal a partir dos args (sem defaults perigosos)
        side_enum = OrderSide.BUY if args.side == "buy" else OrderSide.SELL
        signal = TradingSignal(
            symbol=args.symbol,
            side=side_enum,
            entry_price=float(args.entry_price),
            stop_loss_price=float(args.stop_loss),
            take_profit_price=(
                float(args.take_profit) if args.take_profit is not None else None
            ),
            position_size_usd=float(args.position_size),
            leverage=float(args.leverage),
            strategy_name="cli_bybit_demo_minimum_order",
        )

        # Trava 7: RiskEngine soberano
        risk_result = risk.validate_signal(signal)
        if not risk_result.approved:
            print(f"  ❌ RiskEngine rejeitou: {redact_sensitive(risk_result.reason)}")
            print(f"     block_reason: {risk_result.block_reason}")
            try:
                client.close()
            except Exception:
                pass
            return 1

        # Resumo sanitizado da ordem (audit antes do envio)
        print("  🚨 ENVIANDO ORDEM DEMO REAL:")
        print(f"     Symbol:        {signal.symbol}")
        print(f"     Side:          {signal.side.value}")
        print(f"     Position size: ${signal.position_size_usd:,.2f}")
        print(f"     Entry price:   {signal.entry_price}")
        print(f"     Stop loss:     {signal.stop_loss_price}")
        print(f"     Take profit:   {signal.take_profit_price}")
        print(f"     Capital:       ${args.capital:,.2f}")
        print(f"     Leverage:      {signal.leverage}x  (NÃO enviado no payload; configure na UI)")
        print()

        executor = BybitDemoExecutor(
            client=client,
            mode_guard=guard,
            risk_engine=risk,
            confirm_demo_execution=True,
        )

        # ===== Chama execute(dry_run=False) — chamada REAL ao Bybit Demo =====
        result = executor.execute(risk_result, dry_run=False)

        try:
            client.close()
        except Exception:
            pass

        # Relatório sanitizado
        print(f"  Result: success={result.success}")
        print(f"  Reason: {redact_sensitive(result.reason)}")
        # FASE 14 — Quando a Bybit retorna retCode != 0, expõe os campos
        # estruturados (numérico + texto descritivo). NÃO contém secrets.
        if result.ret_code is not None:
            print(f"  Bybit retCode: {result.ret_code}")
        if result.ret_msg is not None:
            print(f"  Bybit retMsg:  {redact_sensitive(result.ret_msg)}")
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
        print("  ✅ Apenas DEMO (sem mainnet, sem live).")
        print("  ✅ Nenhuma API key foi logada.")
        print("  ✅ Provider gate aplicado (bybit_demo_linear OPT_IN + confirm).")
        print("  ⚠️  Fechamento da posição: UI Bybit Demo → Close Position.")
        print("  ⚠️  reduceOnly NÃO suportado nesta fatia — NÃO use --side oposto.")
        print("  ⚠️  Demo Trading NÃO garante performance futura.")
        return 0 if result.success else 1

    # ===== SAFE-CHECK REAL via BybitDemoExecutor =====
    if wants_safe_check:
        # Defesa-em-profundidade 1: triple-lock via ModeGuard (early abort)
        try:
            guard.assert_demo_execution_allowed(
                confirm_demo_execution=bool(args.confirm_demo_execution),
                context="run_bybit_demo_diagnostic.safe_check",
            )
        except TradingModeError as e:
            print(f"  ❌ ModeGuard bloqueou: {redact_sensitive(str(e))}")
            return 1

        # Defesa-em-profundidade 2: endpoint DEVE ser api-demo.bybit.com
        expected_endpoint = "https://api-demo.bybit.com"
        if exchange.rest_url != expected_endpoint:
            print(f"  ❌ Endpoint resolvido NÃO é {expected_endpoint}")
            print(f"     Resolvido: {exchange.rest_url}")
            print("     Ajuste BYBIT_USE_DEMO=true ou BYBIT_ENVIRONMENT=demo no .env.")
            print("     ABORTANDO sem chamar rede.")
            return 1

        # Defesa-em-profundidade 3: credentials presentes
        if not exchange.has_credentials:
            print("  ❌ Credentials ausentes — safe-check exige api_key e api_secret demo.")
            return 1

        # Defesa-em-profundidade 4: registry continua bloqueando provider
        # (CANDIDATE_REVALIDATION ainda — promoção exige fatia futura)
        try:
            get_registry().assert_usable("bybit_demo_linear")
            print("  ❌ Inesperado: registry NÃO bloqueou bybit_demo_linear.")
            print("     Status atual:", get_registry().get("bybit_demo_linear").status.value)
            return 1
        except ProviderBlockedError:
            pass  # esperado — provider segue CANDIDATE_REVALIDATION

        # Tudo OK → constrói client demo + executor + RiskEngine + chama executor
        api_key = (
            exchange.api_key.get_secret_value() if exchange.api_key else None
        )
        api_secret = (
            exchange.api_secret.get_secret_value() if exchange.api_secret else None
        )
        client = BybitClient(
            environment="demo",
            api_key=api_key,
            api_secret=api_secret,
            recv_window=exchange.recv_window,
        )

        # RiskEngine não é usado em safe_check_only, mas o executor exige-o
        # no construtor (invariante de FASE 5/9). Capital baixo é seguro pois
        # não há validação de sinal nesta chamada.
        risk = RiskEngine(initial_capital=100.0)

        executor = BybitDemoExecutor(
            client=client,
            mode_guard=guard,
            risk_engine=risk,
            confirm_demo_execution=True,   # já validado pelas travas acima
        )

        print()
        print("  🛡️  Chamando BybitDemoExecutor.safe_check_only(dry_run=False)...")

        result = executor.safe_check_only(dry_run=False)

        try:
            client.close()
        except Exception:
            pass

        # Relatório SANITIZADO — não inclui valor de saldo nem credenciais.
        report = {
            "success": result.success,
            "endpoint_type": "demo",
            "endpoint": expected_endpoint,
            "credentials_present": True,
            "wallet_check": "ok" if result.success else "fail",
            "executor": "BybitDemoExecutor",
        }
        print()
        if result.success:
            print("  ✅ SAFE-CHECK RESULT — autenticação Bybit Demo validada.")
        else:
            # result.reason vem do executor (já sanitizado: só type name de exceção).
            # Aplicamos redact_sensitive como defesa adicional.
            print(f"  ❌ SAFE-CHECK FAIL: {redact_sensitive(result.reason)}")
        for k, v in report.items():
            print(f"     {k:25} = {v}")
        print()
        print("  ⚠️  Esta validação cobre APENAS autenticação read-only.")
        print("  ⚠️  Envio de ordem demo: use --execute-demo-order (Fatia 4B; gated).")
        print("  ⚠️  Bybit Demo Trading NÃO garante performance futura.")
        return 0 if result.success else 1

    # ===== DRY-RUN =====
    if is_dry_run:
        print("  🔍 DRY-RUN: nenhuma chamada de rede será feita.")
        # Snapshot registry para auditoria
        entry = get_registry().get("bybit_demo_linear")
        print()
        print(f"  Registry status: {entry.status.value}")
        print(f"  Capability supports_market_order: {entry.capability.supports_market_order}")
        print(f"  Capability is_demo_environment: {entry.capability.is_demo_environment}")
        print(f"  Capability confirmed: {entry.capability.confirmed}")
        print()
        print("  ✅ CONFIRMAÇÕES:")
        print("  ✅ Apenas DEMO TRADING (separado de testnet, sem mainnet, sem live).")
        print("  ✅ Nenhuma key foi logada (use_redaction).")
        print("  ✅ Paper continua o default do bot.")
        print("  ✅ Dry-run: nenhuma rede, nenhuma ordem enviada.")
        print("  ℹ️  Para safe-check read-only: adicione --safe-check --confirm-demo-execution.")
        print("  ℹ️  Para ordem REAL demo: --execute-demo-order + 3 flags + sizing (gated por 7 travas).")
        print("  ⚠️  Demo Trading NÃO garante performance futura.")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
