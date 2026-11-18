"""
Testes — SafetyFlags + adapters duck-typed (FASE 19)
=======================================================
⚠️  100% offline. ZERO rede. ZERO API real. ZERO secrets.

Garante:
    - SafetyFlags é frozen e tipa rigorosamente os campos.
    - metadata é MappingProxyType (read-only).
    - safety_flags_from_dict aceita Mapping; tolera chaves ausentes.
    - safety_flags_from_result_like aceita duck-typed (SimpleNamespace
      ou objeto incompleto); NÃO exige DemoExecutionResult real.
    - flags_adapter.py NÃO importa BybitClient, BybitDemoExecutor,
      BybitTestnetExecutor, DemoExecutionResult, httpx, requests.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

from crypto_trading_bot.demo_session_readiness import (
    SafetyFlags,
    safety_flags_from_dict,
    safety_flags_from_result_like,
)


_FLAGS_ADAPTER_SRC = (
    Path(__file__).parent.parent
    / "src" / "crypto_trading_bot" / "demo_session_readiness"
    / "flags_adapter.py"
)


def _read_adapter_src() -> str:
    return _FLAGS_ADAPTER_SRC.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Frozen / imutabilidade
# ---------------------------------------------------------------------------

class TestSafetyFlagsImmutability:

    def test_safety_flags_is_frozen_dataclass(self):
        assert dataclasses.is_dataclass(SafetyFlags)
        # Tentativa de atribuição deve falhar.
        flags = SafetyFlags()
        with pytest.raises(dataclasses.FrozenInstanceError):
            flags.manual_review_required = True  # type: ignore[misc]

    def test_metadata_is_mapping_proxy(self):
        flags = SafetyFlags(metadata={"k": "v"})
        assert isinstance(flags.metadata, MappingProxyType)

    def test_metadata_cannot_be_mutated_via_internal_dict(self):
        # Mesmo recebendo dict externo, a cópia interna deve ser
        # protegida contra mutação posterior do dict original.
        ext = {"k": "v"}
        flags = SafetyFlags(metadata=ext)
        ext["k"] = "tampered"
        ext["new"] = "x"
        assert flags.metadata["k"] == "v"
        assert "new" not in flags.metadata

    def test_metadata_proxy_rejects_item_assignment(self):
        flags = SafetyFlags(metadata={"k": "v"})
        with pytest.raises(TypeError):
            flags.metadata["k"] = "tampered"  # type: ignore[index]


# ---------------------------------------------------------------------------
# Validações tipadas
# ---------------------------------------------------------------------------

class TestSafetyFlagsValidation:

    def test_invalid_reconciliation_confidence_raises(self):
        with pytest.raises(ValueError):
            SafetyFlags(reconciliation_confidence="weird_value")

    def test_manual_review_must_be_bool(self):
        with pytest.raises(TypeError):
            SafetyFlags(manual_review_required="true")  # type: ignore[arg-type]

    def test_safety_halt_must_be_bool(self):
        with pytest.raises(TypeError):
            SafetyFlags(safety_halt_recommended=1)  # type: ignore[arg-type]

    def test_defaults_are_clean(self):
        flags = SafetyFlags()
        assert flags.manual_review_required is False
        assert flags.safety_halt_recommended is False
        assert flags.reconciliation_confidence == "canonical"
        assert flags.reason == ""
        assert dict(flags.metadata) == {}

    def test_to_dict_is_json_serializable(self):
        import json
        flags = SafetyFlags(
            manual_review_required=True,
            safety_halt_recommended=False,
            reconciliation_confidence="triangulated",
            reason="incident",
            metadata={"k": "v"},
        )
        encoded = json.dumps(flags.to_dict())
        decoded = json.loads(encoded)
        assert decoded["manual_review_required"] is True
        assert decoded["reconciliation_confidence"] == "triangulated"
        assert decoded["metadata"] == {"k": "v"}


# ---------------------------------------------------------------------------
# safety_flags_from_dict
# ---------------------------------------------------------------------------

class TestSafetyFlagsFromDict:

    def test_empty_dict_returns_defaults(self):
        flags = safety_flags_from_dict({})
        assert flags == SafetyFlags()

    def test_dict_with_all_fields(self):
        flags = safety_flags_from_dict({
            "manual_review_required": True,
            "safety_halt_recommended": True,
            "reconciliation_confidence": "triangulated",
            "reason": "x",
            "metadata": {"a": 1},
        })
        assert flags.manual_review_required is True
        assert flags.safety_halt_recommended is True
        assert flags.reconciliation_confidence == "triangulated"
        assert flags.reason == "x"
        assert dict(flags.metadata) == {"a": 1}

    def test_dict_with_extra_keys_ignored(self):
        flags = safety_flags_from_dict({
            "manual_review_required": True,
            "spurious_key": "value",
        })
        assert flags.manual_review_required is True

    def test_dict_with_none_confidence_uses_default(self):
        flags = safety_flags_from_dict({"reconciliation_confidence": None})
        assert flags.reconciliation_confidence == "canonical"

    def test_non_mapping_raises(self):
        with pytest.raises(TypeError):
            safety_flags_from_dict([1, 2, 3])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# safety_flags_from_result_like — duck-typed
# ---------------------------------------------------------------------------

class TestSafetyFlagsFromResultLike:

    def test_none_returns_defaults(self):
        flags = safety_flags_from_result_like(None)
        assert flags == SafetyFlags()

    def test_simplenamespace_full(self):
        ns = SimpleNamespace(
            manual_review_required=True,
            safety_halt_recommended=False,
            reconciliation_confidence="triangulated",
            reason="incident",
            metadata={"src": "demo"},
        )
        flags = safety_flags_from_result_like(ns)
        assert flags.manual_review_required is True
        assert flags.reconciliation_confidence == "triangulated"
        assert dict(flags.metadata) == {"src": "demo"}

    def test_incomplete_object_uses_defaults(self):
        ns = SimpleNamespace(manual_review_required=True)
        flags = safety_flags_from_result_like(ns)
        assert flags.manual_review_required is True
        assert flags.safety_halt_recommended is False
        assert flags.reconciliation_confidence == "canonical"

    def test_custom_class_duck_typed(self):
        class FakeResult:
            def __init__(self):
                self.manual_review_required = False
                self.safety_halt_recommended = True
                self.reconciliation_confidence = "none"
                self.reason = "rec failed"
                self.metadata = {"attempts": 3}
        flags = safety_flags_from_result_like(FakeResult())
        assert flags.safety_halt_recommended is True
        assert flags.reconciliation_confidence == "none"
        assert dict(flags.metadata) == {"attempts": 3}

    def test_does_not_require_demo_execution_result_type(self):
        # Garante que NENHUM isinstance check é feito contra
        # DemoExecutionResult. Um objeto arbitrário com atributos serve.
        ns = SimpleNamespace(
            manual_review_required=True,
            safety_halt_recommended=False,
            reconciliation_confidence="canonical",
        )
        flags = safety_flags_from_result_like(ns)
        assert isinstance(flags, SafetyFlags)
        assert flags.manual_review_required is True

    def test_non_mapping_metadata_falls_back_to_empty(self):
        ns = SimpleNamespace(metadata="not-a-mapping")
        flags = safety_flags_from_result_like(ns)
        assert dict(flags.metadata) == {}


# ---------------------------------------------------------------------------
# Imports proibidos no flags_adapter.py
# ---------------------------------------------------------------------------

def _executable_lines(src: str) -> str:
    """Devolve apenas linhas que NÃO são docstring/comentário.

    Estratégia simples: remove blocos triple-string e linhas iniciadas por
    '#'. Suficiente para checar tokens proibidos em código executável.
    """
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
        # Detecta abertura de docstring/triple-string em uma linha
        for q in ('"""', "'''"):
            if stripped.startswith(q):
                if stripped.count(q) == 1:
                    in_block = True
                    block_quote = q
                # else: docstring de uma linha — só descarta
                break
        else:
            if stripped.startswith("#"):
                continue
            out.append(line)
            continue
        # Caímos no break → linha de docstring (não adiciona)
    return "\n".join(out)


class TestFlagsAdapterNoForbiddenImports:

    def test_no_bybit_client_import(self):
        src = _executable_lines(_read_adapter_src())
        assert "from crypto_trading_bot.exchange.bybit_client" not in src
        assert "BybitClient" not in src

    def test_no_demo_executor_import(self):
        src = _executable_lines(_read_adapter_src())
        assert "bybit_demo_executor" not in src
        assert "BybitDemoExecutor" not in src

    def test_no_testnet_executor_import(self):
        src = _executable_lines(_read_adapter_src())
        assert "bybit_testnet_executor" not in src
        assert "BybitTestnetExecutor" not in src

    def test_no_demo_execution_result_import(self):
        src = _executable_lines(_read_adapter_src())
        assert "DemoExecutionResult" not in src

    def test_no_network_imports(self):
        src = _read_adapter_src()
        for tok in ("import httpx", "from httpx",
                    "import requests", "from requests"):
            assert tok not in src
