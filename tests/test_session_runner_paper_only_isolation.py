"""
Testes de isolamento paper-only do SessionRunner (FASE 17)
=============================================================
⚠️  100% offline. ZERO rede.

Cobertura estrutural:
    - session_runner/* não importa BybitClient, BybitDemoExecutor,
      BybitTestnetExecutor, DemoExecutionResult, httpx, requests.
    - SessionRunner não chama record_trade_opened diretamente.
    - record_trade_opened continua acontecendo apenas pelo fluxo
      BotEngine/PaperTrader/RiskEngine.
"""

from __future__ import annotations

from pathlib import Path

import pytest


_SRC_ROOT = (
    Path(__file__).parent.parent / "src" / "crypto_trading_bot" / "session_runner"
)
_FILES = ("__init__.py", "config.py", "result.py", "runner.py")


def _read_all_src() -> str:
    """Concatena todos os arquivos de session_runner/ para inspeção textual."""
    parts = []
    for name in _FILES:
        path = _SRC_ROOT / name
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Imports proibidos
# ---------------------------------------------------------------------------

class TestNoForbiddenImports:

    def test_no_bybit_client_import(self):
        src = _read_all_src()
        forbidden = [
            "from crypto_trading_bot.exchange.bybit_client",
            "import crypto_trading_bot.exchange.bybit_client",
        ]
        for line in forbidden:
            assert line not in src, f"session_runner não pode importar: {line}"

    def test_no_demo_executor_import(self):
        src = _read_all_src()
        forbidden = [
            "from crypto_trading_bot.execution.bybit_demo_executor",
            "import crypto_trading_bot.execution.bybit_demo_executor",
        ]
        for line in forbidden:
            assert line not in src, f"session_runner não pode importar: {line}"

    def test_no_testnet_executor_import(self):
        src = _read_all_src()
        forbidden = [
            "from crypto_trading_bot.execution.bybit_testnet_executor",
            "import crypto_trading_bot.execution.bybit_testnet_executor",
        ]
        for line in forbidden:
            assert line not in src, f"session_runner não pode importar: {line}"

    def test_no_demo_execution_result_import(self):
        """
        Garante que DemoExecutionResult não é IMPORTADO (menção em
        docstring/comentário é permitida, pois o módulo descreve
        explicitamente o que NÃO deve importar).
        """
        for name in _FILES:
            src = (_SRC_ROOT / name).read_text(encoding="utf-8")
            # Procura apenas em linhas que começam com from/import (não comments)
            for line in src.split("\n"):
                stripped = line.lstrip()
                if (stripped.startswith("from ")
                        or stripped.startswith("import ")):
                    assert "DemoExecutionResult" not in stripped, (
                        f"{name}: import proibido detectado: {line!r}"
                    )

    def test_no_httpx_or_requests(self):
        src = _read_all_src()
        forbidden = [
            "import httpx", "from httpx",
            "import requests", "from requests",
        ]
        for line in forbidden:
            assert line not in src, (
                f"session_runner não pode usar rede: {line}"
            )

    def test_no_provider_registry_promotion(self):
        src = _read_all_src()
        # Não deve promover nenhum provider
        assert "ACTIVE" not in src or "ProviderStatus.ACTIVE" not in src


# ---------------------------------------------------------------------------
# record_trade_opened: não chamado diretamente
# ---------------------------------------------------------------------------

class TestRecordTradeOpenedFlow:

    def test_runner_does_not_call_record_trade_opened_directly(self):
        """
        record_trade_opened continua sendo chamado APENAS via fluxo
        BotEngine → PaperTrader → RiskEngine. SessionRunner não pode
        chamar diretamente.
        """
        src = _read_all_src()
        # Aceita menção em docstring/comentário, mas NÃO em código ativo.
        # Verificação pragmática: o método não deve aparecer como
        # chamada attribute-style.
        assert ".record_trade_opened(" not in src

    def test_runner_does_not_call_record_trade_closed_directly(self):
        src = _read_all_src()
        # Permitido em docstring; sem chamada ativa.
        # close_trade pertence ao PaperTrader; runner usa via paper_trader API
        # apenas em hooks de teste (na suíte). Em src/, sem chamada.
        assert ".record_trade_closed(" not in src


# ---------------------------------------------------------------------------
# Sem rede em runtime — confirmado por chamada
# ---------------------------------------------------------------------------

class TestNoNetworkAtRuntime:

    def test_runner_init_does_not_require_network(self):
        # Smoke: construir runner não deve disparar nenhum import de rede.
        from datetime import datetime, timezone
        from crypto_trading_bot.operational_profile import build_personal_profile
        from crypto_trading_bot.research.strategy_research import StrategySpec
        from crypto_trading_bot.session_runner import (
            SessionRunner, SessionRunnerConfig,
        )
        from tests.test_session_runner_config import _HoldStrategy

        def factory(cfg):
            s = _HoldStrategy()
            s.set_running()
            return s

        spec = StrategySpec(name="x", factory=factory)
        profile = build_personal_profile(account_size_usd=5000.0)
        cfg = SessionRunnerConfig(
            profile=profile, spec=spec, capital=5000.0, max_cycles=1,
            clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
            sleep=lambda s: None,
        )
        runner = SessionRunner(cfg)
        result = runner.run()
        assert result.total_cycles_completed == 1
