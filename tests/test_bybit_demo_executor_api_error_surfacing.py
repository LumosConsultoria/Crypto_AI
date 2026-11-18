"""
BybitDemoExecutor — Surfacing de BybitAPIError (FASE 14 hardening)
====================================================================
⚠️  100% offline. ZERO secrets. ZERO rede. ZERO ordens.

Diagnóstico introduzido após Demo v2 falhar com BybitAPIError oculto.
Quando a Bybit responde retCode != 0, o executor deve expor:
    - DemoExecutionResult.ret_code (int)
    - DemoExecutionResult.ret_msg (str descritivo da Bybit)
    - reason: contém retCode e retMsg para auditoria humana.

Critérios:
    - retCode/retMsg disponíveis em execute() (place_order).
    - retCode/retMsg disponíveis em safe_check_only() (get_balance).
    - to_dict() inclui ret_code/ret_msg apenas quando não-None.
    - Exceções não-Bybit (genéricas) NÃO populam ret_code/ret_msg.
    - Cópia defensiva da mensagem (sem mutação do objeto exception).
    - Nenhum teste chama internet; nenhum teste usa API key real.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.exchange.bybit_client import BybitAPIError
from crypto_trading_bot.execution.bybit_demo_executor import (
    DemoExecutionResult,
)

from tests.test_bybit_demo_executor import (
    _approved,
    _make_demo_mock_client,
    _make_executor,
    _make_signal,
)


# ---------------------------------------------------------------------------
# place_order → BybitAPIError → ret_code/ret_msg expostos
# ---------------------------------------------------------------------------

class TestExecutePlaceOrderApiError:

    def test_bybit_api_error_surfaces_ret_code_and_ret_msg(self):
        api_err = BybitAPIError(
            ret_code=110007,
            ret_msg="ab not enough for new order",
            endpoint="/v5/order/create",
        )
        client = _make_demo_mock_client(place_raise=api_err)
        executor, _ = _make_executor(client=client)

        result = executor.execute(_approved(), dry_run=False)

        assert result.success is False
        assert result.operation == "place_order"
        assert result.ret_code == 110007
        assert result.ret_msg == "ab not enough for new order"
        # Reason humano-legível com retCode + retMsg
        assert "110007" in result.reason
        assert "ab not enough" in result.reason
        assert "BybitAPIError" in result.reason

    def test_generic_exception_does_not_populate_ret_fields(self):
        """Exceções não-Bybit não devem fingir ser BybitAPIError."""
        client = _make_demo_mock_client(place_raise=RuntimeError("boom"))
        executor, _ = _make_executor(client=client)

        result = executor.execute(_approved(), dry_run=False)
        assert result.success is False
        assert result.ret_code is None
        assert result.ret_msg is None
        # Reason usa apenas type name (sem str(e))
        assert "RuntimeError" in result.reason
        # E não inclui a string "boom" do detalhe do erro
        assert "boom" not in result.reason


# ---------------------------------------------------------------------------
# safe_check_only → BybitAPIError → ret_code/ret_msg expostos
# ---------------------------------------------------------------------------

class TestSafeCheckApiError:

    def test_bybit_api_error_on_get_balance_surfaces_ret_fields(self):
        api_err = BybitAPIError(
            ret_code=10003,
            ret_msg="API key is invalid",
            endpoint="/v5/account/wallet-balance",
        )
        client = _make_demo_mock_client()
        client.get_balance.side_effect = api_err
        executor, _ = _make_executor(client=client)

        result = executor.safe_check_only(dry_run=False)

        assert result.success is False
        assert result.operation == "safe_check"
        assert result.ret_code == 10003
        assert result.ret_msg == "API key is invalid"
        assert "10003" in result.reason
        assert "API key is invalid" in result.reason


# ---------------------------------------------------------------------------
# to_dict() — inclui ret_code/ret_msg só quando preenchidos
# ---------------------------------------------------------------------------

class TestToDictRetFieldsRetrocompat:

    def test_success_result_does_not_include_ret_fields(self):
        executor, _ = _make_executor()
        result = executor.execute(_approved(), dry_run=False)
        d = result.to_dict()
        # Sucesso → não há ret_code/ret_msg
        assert "ret_code" not in d
        assert "ret_msg" not in d

    def test_dry_run_does_not_include_ret_fields(self):
        executor, _ = _make_executor()
        result = executor.execute(_approved(), dry_run=True)
        d = result.to_dict()
        assert "ret_code" not in d
        assert "ret_msg" not in d

    def test_api_error_result_includes_ret_fields(self):
        api_err = BybitAPIError(
            ret_code=10001, ret_msg="parameter error",
            endpoint="/v5/order/create",
        )
        client = _make_demo_mock_client(place_raise=api_err)
        executor, _ = _make_executor(client=client)
        result = executor.execute(_approved(), dry_run=False)
        d = result.to_dict()
        assert d["ret_code"] == 10001
        assert d["ret_msg"] == "parameter error"


# ---------------------------------------------------------------------------
# DemoExecutionResult — construção direta
# ---------------------------------------------------------------------------

class TestDemoExecutionResultDataclass:

    def test_defaults_keep_ret_fields_none(self):
        r = DemoExecutionResult(
            success=True, operation="place_order",
        )
        assert r.ret_code is None
        assert r.ret_msg is None

    def test_explicit_fields_stored(self):
        r = DemoExecutionResult(
            success=False, operation="place_order",
            ret_code=110007, ret_msg="ab not enough for new order",
        )
        assert r.ret_code == 110007
        assert r.ret_msg == "ab not enough for new order"

    def test_frozen_cannot_mutate(self):
        r = DemoExecutionResult(success=True, operation="place_order")
        with pytest.raises(Exception):
            r.success = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Isolamento estrutural — nenhum import novo proibido
# ---------------------------------------------------------------------------

class TestStructuralIsolation:

    def test_no_new_network_imports(self):
        import crypto_trading_bot.execution.bybit_demo_executor as mod
        src = open(mod.__file__, "r", encoding="utf-8").read()
        # Não pode ter import novo de httpx, requests, etc.
        assert "import httpx" not in src.split("\n")
        assert "import requests" not in src.split("\n")

    def test_no_secrets_in_reason_string_for_api_error(self):
        """retMsg da Bybit é texto público; mas garantir que não vazem
        tokens conhecidos por acidente."""
        api_err = BybitAPIError(
            ret_code=10001, ret_msg="parameter error",
            endpoint="/v5/order/create",
        )
        client = _make_demo_mock_client(place_raise=api_err)
        executor, _ = _make_executor(client=client)
        result = executor.execute(_approved(), dry_run=False)
        reason_lower = result.reason.lower()
        for tok in ("api_key", "api_secret", "x-bapi-sign", "bearer ",
                    "authorization"):
            assert tok not in reason_lower
