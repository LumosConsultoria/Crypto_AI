"""
Testes — Isolamento estrutural do módulo demo_session_execution (FASE 20)
============================================================================
⚠️  100% offline. ZERO rede. ZERO secrets. ZERO ordem.

Garante (inspeção estrutural):
    - demo_session_execution/* NÃO importa BybitClient, BybitDemoExecutor,
      BybitTestnetExecutor, DemoExecutionResult, httpx, requests,
      SessionRunner, BotEngine.
    - gate.py NÃO tem for/while no corpo executável.
    - Nenhuma chamada de mutação no ProviderRegistry
      (.register/.unregister/.replace) no código executável.
    - Nenhum branch consulta provider_name == "HyroTrader".
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from crypto_trading_bot.demo_session_execution import (
    execute_demo_session_gated,
)
from crypto_trading_bot.demo_session_execution.gate import (
    _blueprint_to_trading_signal,
)


_MOD_DIR = (
    Path(__file__).parent.parent
    / "src" / "crypto_trading_bot" / "demo_session_execution"
)


def _read(path_name: str) -> str:
    return (_MOD_DIR / path_name).read_text(encoding="utf-8")


def _executable_lines(src: str) -> str:
    """Ignora linhas de docstring e comentários."""
    out: list[str] = []
    in_block = False
    block_quote: str | None = None
    for line in src.splitlines():
        stripped = line.strip()
        if in_block:
            if block_quote and block_quote in line:
                in_block = False
                block_quote = None
            continue
        for q in ('"""', "'''"):
            if stripped.startswith(q):
                if stripped.count(q) == 1:
                    in_block = True
                    block_quote = q
                break
        else:
            if stripped.startswith("#"):
                continue
            out.append(line)
            continue
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Imports proibidos
# ---------------------------------------------------------------------------

_FILES = ["plan.py", "outcome.py", "gate.py", "__init__.py"]


class TestNoForbiddenImports:

    @pytest.mark.parametrize("filename", _FILES)
    def test_no_bybit_client_import(self, filename):
        src = _executable_lines(_read(filename))
        assert "from crypto_trading_bot.exchange.bybit_client" not in src
        assert "BybitClient" not in src

    @pytest.mark.parametrize("filename", _FILES)
    def test_no_bybit_demo_executor_import(self, filename):
        src = _executable_lines(_read(filename))
        # NÃO importa BybitDemoExecutor (Protocol duck-typed em vez disso).
        assert "from crypto_trading_bot.execution.bybit_demo_executor" not in src
        assert "BybitDemoExecutor" not in src

    @pytest.mark.parametrize("filename", _FILES)
    def test_no_bybit_testnet_executor_import(self, filename):
        src = _executable_lines(_read(filename))
        assert "bybit_testnet_executor" not in src
        assert "BybitTestnetExecutor" not in src

    @pytest.mark.parametrize("filename", _FILES)
    def test_no_demo_execution_result_import(self, filename):
        src = _executable_lines(_read(filename))
        # DemoExecutionResult NÃO importado — usamos duck-typing.
        assert "DemoExecutionResult" not in src

    @pytest.mark.parametrize("filename", _FILES)
    def test_no_session_runner_import(self, filename):
        src = _executable_lines(_read(filename))
        assert "SessionRunner" not in src
        assert "session_runner.runner" not in src

    @pytest.mark.parametrize("filename", _FILES)
    def test_no_bot_engine_import(self, filename):
        src = _executable_lines(_read(filename))
        assert "from crypto_trading_bot.core.bot_engine" not in src
        assert "BotEngine" not in src

    @pytest.mark.parametrize("filename", _FILES)
    def test_no_network_imports(self, filename):
        src = _read(filename)
        for tok in ("import httpx", "from httpx",
                    "import requests", "from requests"):
            assert tok not in src

    @pytest.mark.parametrize("filename", _FILES)
    def test_no_hyrotrader_branch(self, filename):
        src = _executable_lines(_read(filename)).lower()
        assert 'provider_name == "hyrotrader"' not in src
        assert "provider_name=='hyrotrader'" not in src

    @pytest.mark.parametrize("filename", _FILES)
    def test_no_apply_overrides_call(self, filename):
        # demo_session_execution NÃO chama o gate da FASE 18.
        src = _executable_lines(_read(filename))
        assert "apply_profile_overrides_with_gate(" not in src


# ---------------------------------------------------------------------------
# Single-shot — execute_demo_session_gated não tem for/while
# ---------------------------------------------------------------------------

class TestSingleShotEnforcement:

    def test_no_for_loop_in_gate_function(self):
        src = inspect.getsource(execute_demo_session_gated)
        # Inspeção textual: nenhuma keyword `for `/`while ` no body.
        # (a função usa apenas if/elif/else.)
        lower = src.lower()
        # Permite menção em comentário, mas inspect.getsource pega o corpo
        # com docstring incluída — vamos remover docstring antes.
        body = src.split('"""', 2)
        # Após docstring (idx 2): execução real.
        executable = body[2] if len(body) >= 3 else src
        executable_no_comments = "\n".join(
            line for line in executable.splitlines()
            if not line.strip().startswith("#")
        )
        for keyword in (" for ", "\nfor ", " while ", "\nwhile "):
            assert keyword not in executable_no_comments, (
                f"Encontrado {keyword!r} em execute_demo_session_gated — "
                "função deve ser single-shot."
            )

    def test_blueprint_to_trading_signal_no_loop(self):
        src = inspect.getsource(_blueprint_to_trading_signal)
        body = src.split('"""', 2)
        executable = body[2] if len(body) >= 3 else src
        for keyword in (" for ", "\nfor ", " while ", "\nwhile "):
            assert keyword not in executable


# ---------------------------------------------------------------------------
# Sem chamadas de mutação no ProviderRegistry
# ---------------------------------------------------------------------------

class TestRegistryReadOnly:

    @pytest.mark.parametrize("filename", _FILES)
    def test_no_registry_register_call(self, filename):
        src = _executable_lines(_read(filename))
        assert "provider_registry.register(" not in src
        assert "provider_registry.unregister(" not in src
        # Aceita .assert_usable e .get
        assert ".register(" not in src or "register(ProviderEntry" not in src

    @pytest.mark.parametrize("filename", _FILES)
    def test_no_safety_machine_reset(self, filename):
        # gate NÃO chama acknowledge/resolve/reset. Operador externo faz.
        src = _executable_lines(_read(filename))
        assert "safety_machine.acknowledge(" not in src
        assert "safety_machine.resolve(" not in src
        assert "safety_machine.reset(" not in src
