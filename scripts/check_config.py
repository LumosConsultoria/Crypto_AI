"""
check_config.py — Verificador de Configuração
===============================================
Verifica se todas as configurações estão corretas antes de iniciar o bot.

Execute antes de qualquer operação:
    python scripts/check_config.py

Verificações realizadas:
    ✅ Modo de operação atual
    ✅ ModeGuard status
    ✅ RiskEngine configuração
    ✅ Arquivos .env presentes
    ✅ Credenciais de exchange (sem expor valores)
    ✅ Dependências instaladas
    ✅ Avisos de segurança
"""

import sys
from pathlib import Path

# Adiciona o src/ ao path para importações
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def main() -> int:
    """
    Executa todas as verificações de configuração.

    Returns:
        0 se tudo OK, 1 se há erros críticos.
    """
    errors: list[str] = []
    warnings: list[str] = []

    print("\n" + "="*60)
    print("  🤖 CRYPTO TRADING BOT — Verificação de Configuração")
    print("="*60 + "\n")

    # --- Verificação 1: Importações críticas ---
    print("📦 Verificando módulos...")
    try:
        from crypto_trading_bot.config.settings import get_settings
        from crypto_trading_bot.config.risk_config import get_risk_config
        from crypto_trading_bot.config.exchange_config import get_exchange_config
        from crypto_trading_bot.core.mode_guard import ModeGuard
        from crypto_trading_bot.risk.risk_engine import RiskEngine

        # Limpar cache para garantir leitura fresca do .env
        get_settings.cache_clear()
        get_risk_config.cache_clear()
        get_exchange_config.cache_clear()

        print("  ✅ Todos os módulos principais importados com sucesso")
    except ImportError as e:
        errors.append(f"Erro de importação: {e}")
        print(f"  ❌ Erro de importação: {e}")
        print("\n  💡 Execute: pip install -r requirements.txt")
        _print_summary(errors, warnings)
        return 1

    # --- Verificação 2: Configurações gerais ---
    print("\n⚙️  Verificando configurações...")
    try:
        settings = get_settings()
        print(f"  ✅ Modo de operação: {settings.trading_mode.value.upper()}")
        print(f"  ✅ Símbolo padrão: {settings.default_symbol}")
        print(f"  ✅ Timeframe: {settings.default_timeframe}m")
        print(f"  ✅ Nível de log: {settings.log_level}")
        print(f"  ✅ Diretório de logs: {settings.log_dir}")
        print(f"  ✅ Capital simulado: {settings.paper_trading_initial_balance} {settings.paper_trading_currency}")
    except Exception as e:
        errors.append(f"Erro nas configurações gerais: {e}")
        print(f"  ❌ Erro nas configurações: {e}")

    # --- Verificação 3: ModeGuard ---
    print("\n🔒 Verificando ModeGuard...")
    try:
        settings = get_settings()
        guard = ModeGuard(settings)
        status = guard.get_status_summary()

        print(f"  ✅ Modo: {status['mode']}")
        print(f"  ✅ Seguro: {status['is_safe']}")
        print(f"  ✅ Live trading ativo: {status['is_live']}")

        if status["is_live"]:
            msg = "⚠️  ATENÇÃO: LIVE TRADING ATIVO! Ordens reais podem ser enviadas."
            warnings.append(msg)
            print(f"\n  🔴 {msg}")

        if status["warning"]:
            print(f"  ⚠️  {status['warning']}")

        if status["is_safe"]:
            print(f"  ✅ Sistema em modo SEGURO — nenhuma ordem real será enviada")

    except Exception as e:
        errors.append(f"Erro no ModeGuard: {e}")
        print(f"  ❌ Erro no ModeGuard: {e}")

    # --- Verificação 4: Configurações de risco ---
    print("\n⚖️  Verificando configurações de risco...")
    try:
        risk_config = get_risk_config()

        print(f"  ✅ Perda diária máx.: {risk_config.max_daily_loss_pct:.1%}")
        print(f"  ✅ Perda total máx.: {risk_config.max_total_loss_pct:.1%}")
        print(f"  ✅ Trades máx./dia: {risk_config.max_trades_per_day}")
        print(f"  ✅ Exposição máx./ativo: {risk_config.max_exposure_per_asset_pct:.1%}")
        print(f"  ✅ Alavancagem máx.: {risk_config.max_leverage}x")
        print(f"  ✅ Stop loss mínimo: {risk_config.min_stop_loss_pct:.2%}")

        # Verificar se os valores parecem ser placeholders
        if risk_config.max_daily_loss_pct == 0.05 and risk_config.max_total_loss_pct == 0.10:
            warnings.append(
                "Regras de risco com valores placeholder (5%/10%). "
                "Configure com as regras reais do HyroTrader antes de operar."
            )
            print("  ⚠️  Usando valores placeholder — verifique docs/risk_rules.md")

    except Exception as e:
        errors.append(f"Erro nas configurações de risco: {e}")
        print(f"  ❌ Erro nas configurações de risco: {e}")

    # --- Verificação 5: Configuração de exchange ---
    print("\n🔗 Verificando configuração de exchange...")
    try:
        exchange_config = get_exchange_config()
        settings = get_settings()

        print(f"  ✅ Testnet: {exchange_config.use_testnet}")
        print(f"  ✅ URL REST: {exchange_config.rest_url}")
        print(f"  ✅ Credenciais configuradas: {exchange_config.has_credentials}")

        if settings.is_paper_mode:
            print("  ℹ️  Modo PAPER: credenciais de exchange não são necessárias")
        elif not exchange_config.has_credentials:
            msg = "Credenciais de exchange não configuradas. Necessário para testnet/live."
            warnings.append(msg)
            print(f"  ⚠️  {msg}")

        if not exchange_config.use_testnet and not settings.is_paper_mode:
            msg = "ATENÇÃO: BYBIT_USE_TESTNET=false com modo não-paper! Risco de conexão com mainnet."
            errors.append(msg)
            print(f"  ❌ {msg}")

    except Exception as e:
        warnings.append(f"Aviso na configuração de exchange: {e}")
        print(f"  ⚠️  Aviso na configuração de exchange: {e}")

    # --- Verificação 6: Arquivo .env ---
    print("\n📄 Verificando arquivos de configuração...")
    env_path = Path(".env")
    env_example_path = Path(".env.example")

    if env_example_path.exists():
        print(f"  ✅ .env.example encontrado")
    else:
        warnings.append(".env.example não encontrado")
        print(f"  ⚠️  .env.example não encontrado")

    if env_path.exists():
        print(f"  ✅ .env encontrado")
    else:
        warnings.append(
            ".env não encontrado. "
            "Copie .env.example para .env e configure as variáveis."
        )
        print(f"  ⚠️  .env não encontrado — usando valores padrão das Settings")
        print(f"       Execute: copy .env.example .env  (ou cp no Linux/Mac)")

    # --- Verificação 7: Dependências ---
    print("\n📦 Verificando dependências principais...")
    deps_to_check = [
        ("pydantic", "pydantic"),
        ("pydantic_settings", "pydantic-settings"),
        ("loguru", "loguru"),
        ("dotenv", "python-dotenv"),
    ]

    optional_deps = [
        ("pandas", "pandas"),
        ("numpy", "numpy"),
    ]

    for module, pkg_name in deps_to_check:
        try:
            __import__(module)
            print(f"  ✅ {pkg_name}")
        except ImportError:
            errors.append(f"Dependência ausente: {pkg_name}")
            print(f"  ❌ {pkg_name} não instalado — execute: pip install {pkg_name}")

    for module, pkg_name in optional_deps:
        try:
            __import__(module)
            print(f"  ✅ {pkg_name} (opcional)")
        except ImportError:
            print(f"  ⚠️  {pkg_name} não instalado (opcional para FASE 3)")

    # --- Resumo ---
    _print_summary(errors, warnings)

    return 1 if errors else 0


def _print_summary(errors: list, warnings: list) -> None:
    """Imprime o resumo final da verificação."""
    print("\n" + "="*60)
    print("  📊 RESUMO")
    print("="*60)

    if not errors and not warnings:
        print("  ✅ Tudo OK! Sistema pronto para paper trading.")
    else:
        if warnings:
            print(f"\n  ⚠️  {len(warnings)} aviso(s):")
            for w in warnings:
                print(f"     • {w}")

        if errors:
            print(f"\n  ❌ {len(errors)} erro(s) crítico(s):")
            for e in errors:
                print(f"     • {e}")
            print("\n  🛑 Corrija os erros antes de iniciar o bot.")
        else:
            print("\n  ✅ Sem erros críticos. Verifique os avisos antes de operar.")

    print("\n  💡 Para iniciar paper trading: python scripts/run_paper_trading.py")
    print("="*60 + "\n")


if __name__ == "__main__":
    sys.exit(main())
