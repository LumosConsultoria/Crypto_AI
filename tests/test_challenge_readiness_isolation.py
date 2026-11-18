"""
Tests - Challenge Readiness isolation (FASE 23)
=====================================================
Structural: challenge_readiness/* must NOT import BybitClient,
BybitDemoExecutor, BybitTestnetExecutor, DemoExecutionResult, httpx,
requests, or session_runner internals (apenas tipos imutaveis).

100% offline. ZERO network.
"""

from __future__ import annotations

from pathlib import Path

import pytest


_MOD_DIR = (
    Path(__file__).parent.parent
    / "src" / "crypto_trading_bot" / "challenge_readiness"
)
_FILES = [
    "stages.py", "readiness.py", "result.py",
    "endurance_runner.py", "__init__.py",
]


def _read(name: str) -> str:
    return (_MOD_DIR / name).read_text(encoding="utf-8")


def _executable_lines(src: str) -> str:
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


class TestNoForbiddenImports:

    @pytest.mark.parametrize("filename", _FILES)
    def test_no_bybit_client_import(self, filename):
        src = _executable_lines(_read(filename))
        assert "from crypto_trading_bot.exchange.bybit_client" not in src
        assert "BybitClient(" not in src

    @pytest.mark.parametrize("filename", _FILES)
    def test_no_bybit_executors(self, filename):
        src = _executable_lines(_read(filename))
        assert "BybitDemoExecutor" not in src
        assert "BybitTestnetExecutor" not in src

    @pytest.mark.parametrize("filename", _FILES)
    def test_no_demo_execution_result(self, filename):
        src = _executable_lines(_read(filename))
        assert "DemoExecutionResult" not in src

    @pytest.mark.parametrize("filename", _FILES)
    def test_no_network_imports(self, filename):
        src = _read(filename)
        for tok in ("import httpx", "from httpx",
                    "import requests", "from requests"):
            assert tok not in src

    @pytest.mark.parametrize("filename", _FILES)
    def test_no_provider_registry_mutation(self, filename):
        src = _executable_lines(_read(filename))
        # Permitido apenas leitura/import; sem .register/.unregister/.promote.
        assert ".register(ProviderEntry" not in src
        assert "ProviderRegistry()" not in src or filename in (
            "__init__.py", "stages.py",
        )

    def test_session_runner_import_lazy_only_in_endurance_runner(self):
        """SessionRunner should only be imported lazily inside the
        endurance runner method body (not at module top), to keep the
        module pure for cases that inject runner_factory."""
        src = _executable_lines(_read("endurance_runner.py"))
        # Top-level imports must NOT include SessionRunner.
        # The lazy import is inside _run_session.
        # Detect by checking that no top-level 'from ... import SessionRunner'
        # appears outside indented code.
        top_imports = [
            line for line in src.splitlines()
            if line.startswith("from ") and "SessionRunner" in line
        ]
        # All SessionRunner imports must be indented (lazy in function body).
        assert top_imports == []
