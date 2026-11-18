"""
check_testnet_config.py — CLI de verificação SEGURA da config testnet
========================================================================
⚠️  Este script NÃO chama endpoints privados da Bybit.
⚠️  Apenas valida configuração local (.env, Settings, ModeGuard).
⚠️  ZERO API key real é usada. ZERO ordens enviadas.

Uso:
    python scripts/check_testnet_config.py           # validação completa
    python scripts/check_testnet_config.py --dry-run # alias (não há outra opção)
    python scripts/check_testnet_config.py --json    # output JSON
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Adiciona src/ ao path
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))


def _print_banner() -> None:
    print()
    print("=" * 70)
    print("  🔍 BYBIT TESTNET CONFIG CHECK — FASE 5")
    print("  ⚠️  ZERO API key real é usada por este script.")
    print("  ⚠️  ZERO endpoint privado é chamado.")
    print("  ⚠️  Apenas validação local (.env + ModeGuard).")
    print("=" * 70)
    print()


def _collect_diagnostics() -> dict:
    """Coleta diagnóstico SEM expor api_key/api_secret."""
    from crypto_trading_bot.config.exchange_config import ExchangeConfig
    from crypto_trading_bot.config.settings import get_settings
    from crypto_trading_bot.core.mode_guard import ModeGuard

    settings = get_settings()
    guard = ModeGuard(settings=settings)
    exchange = ExchangeConfig()

    # ⚠️  Nunca expõe valores de api_key/api_secret reais; apenas booleans.
    creds_present = exchange.has_credentials

    return {
        "trading_mode": settings.trading_mode.value,
        "enable_live_trading": settings.enable_live_trading,
        "enable_testnet_execution": settings.enable_testnet_execution,
        "is_paper_mode": settings.is_paper_mode,
        "is_testnet_mode": settings.is_testnet_mode,
        "is_live_mode": settings.is_live_mode,
        "is_testnet_execution_enabled": settings.is_testnet_execution_enabled,
        "modeguard": guard.get_status_summary(),
        "exchange": {
            "use_testnet": exchange.use_testnet,
            "credentials_present": creds_present,
            "rest_url": exchange.rest_url,
        },
    }


def _format_check(label: str, ok: bool, detail: str = "") -> str:
    icon = "✅" if ok else "⚠️ "
    base = f"  {icon} {label}"
    return f"{base}: {detail}" if detail else base


def _human_report(d: dict) -> str:
    lines = [
        "  📋 ESTADO ATUAL:",
        f"     TRADING_MODE                  = {d['trading_mode']}",
        f"     ENABLE_LIVE_TRADING           = {d['enable_live_trading']}",
        f"     ENABLE_TESTNET_EXECUTION      = {d['enable_testnet_execution']}",
        f"     exchange.use_testnet          = {d['exchange']['use_testnet']}",
        f"     credentials present in .env   = {d['exchange']['credentials_present']}",
        f"     exchange.rest_url             = {d['exchange']['rest_url']}",
        "",
        "  🛡️  MODEGUARD:",
        f"     is_paper                      = {d['modeguard']['is_paper']}",
        f"     is_testnet                    = {d['modeguard']['is_testnet']}",
        f"     is_live                       = {d['modeguard']['is_live']}",
        f"     is_safe                       = {d['modeguard']['is_safe']}",
        f"     is_testnet_execution_allowed  = {d['modeguard']['is_testnet_execution_allowed']}",
        "",
        "  📌 PRÉ-REQUISITOS PARA EXECUÇÃO TESTNET:",
        _format_check(
            "TRADING_MODE=testnet",
            d["trading_mode"] == "testnet",
            f"atual: {d['trading_mode']}",
        ),
        _format_check(
            "ENABLE_TESTNET_EXECUTION=true",
            d["enable_testnet_execution"],
            f"atual: {d['enable_testnet_execution']}",
        ),
        _format_check(
            "exchange.use_testnet=true",
            d["exchange"]["use_testnet"],
        ),
        _format_check(
            "credentials presentes (api_key + api_secret)",
            d["exchange"]["credentials_present"],
            "verifique BYBIT_API_KEY e BYBIT_API_SECRET no .env"
            if not d["exchange"]["credentials_present"] else "",
        ),
        "",
        "  ⚠️  Mesmo com TODOS os checks acima OK, o BybitTestnetExecutor",
        "      AINDA exige confirm_testnet_execution=True na chamada.",
    ]

    all_ok = (
        d["trading_mode"] == "testnet"
        and d["enable_testnet_execution"]
        and d["exchange"]["use_testnet"]
        and d["exchange"]["credentials_present"]
    )
    lines.append("")
    if all_ok:
        lines.append("  ✅ Config OK. Próximo passo: run_testnet_diagnostic.py --dry-run")
    else:
        lines.append("  ⚠️  Config INCOMPLETA. Veja os ⚠️ acima.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Valida configuração testnet localmente. NÃO chama endpoints "
            "privados nem usa API key real."
        )
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="(default behavior — flag aceita por compat com FASE 3G)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output em JSON em vez de relatório humano."
    )
    args = parser.parse_args()
    _ = args.dry_run   # sempre dry-run

    _print_banner()
    try:
        diag = _collect_diagnostics()
    except Exception as e:
        print(f"  ❌ Erro ao coletar diagnóstico: {type(e).__name__}: {e}")
        return 1

    if args.json:
        print(json.dumps(diag, indent=2))
    else:
        print(_human_report(diag))

    print()
    print("─" * 70)
    print("  ✅ CONFIRMAÇÕES:")
    print("  ✅ Nenhuma API key real foi exibida ou logada.")
    print("  ✅ Nenhum endpoint privado da Bybit foi chamado.")
    print("  ✅ Nenhuma ordem real foi enviada.")
    print("  ⚠️  Testnet NÃO garante performance futura.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
