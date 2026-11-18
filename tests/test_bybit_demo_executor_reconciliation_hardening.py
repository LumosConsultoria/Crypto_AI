"""
BybitDemoExecutor — Reconciliation Hardening (FASE 15)
=========================================================
⚠️  100% offline. ZERO secrets. ZERO rede. ZERO ordens.

Cobertura:
    - ReconciliationAttempt captura retCode/retMsg em BybitAPIError.
    - Tentativas ficam em ordem determinística.
    - order/realtime Filled na primeira tentativa preserva caminho legado.
    - order/history fallback preserva comportamento.
    - executions confirma FILLED_BY_TRIANGULATION (com order_id match).
    - positions confirma FILLED_BY_TRIANGULATION apenas com symbol/side/qty.
    - qty mismatch não confirma triangulação.
    - símbolo divergente não confirma triangulação.
    - múltiplas posições no mesmo símbolo são ambíguas → não confirma.
    - todos os fallbacks falhando → RECONCILIATION_FAILED com attempts acumuladas.
    - FILLED_BY_TRIANGULATION NÃO chama record_trade_opened (invariante).
    - FILLED_BY_TRIANGULATION marca manual_review_required + safety_halt_recommended.
    - to_dict inclui reconciliation_attempts apenas quando não-vazio.
    - logs não contêm api_key, api_secret, X-BAPI-SIGN, Bearer, signature.
"""

from __future__ import annotations

import re

import pytest
from unittest.mock import MagicMock

from crypto_trading_bot.exchange.bybit_client import BybitAPIError
from crypto_trading_bot.execution.bybit_demo_executor import (
    DemoExecutionResult,
    DemoTradeStatus,
    ReconciliationAttempt,
)

from tests.test_bybit_demo_executor import (
    _approved,
    _make_demo_mock_client,
    _make_executor,
    _make_signal,
)


# ---------------------------------------------------------------------------
# ReconciliationAttempt dataclass
# ---------------------------------------------------------------------------

class TestReconciliationAttempt:

    def test_to_dict_omits_optional_when_none(self):
        a = ReconciliationAttempt(
            method="order_status_attempt_1",
            endpoint="/v5/order/realtime",
            success=True,
        )
        d = a.to_dict()
        assert d["method"] == "order_status_attempt_1"
        assert d["endpoint"] == "/v5/order/realtime"
        assert d["success"] is True
        assert "ret_code" not in d
        assert "ret_msg" not in d

    def test_to_dict_includes_ret_fields(self):
        a = ReconciliationAttempt(
            method="order_history_fallback",
            endpoint="/v5/order/history",
            success=False,
            ret_code=10001,
            ret_msg="invalid symbol",
            elapsed_ms=312,
        )
        d = a.to_dict()
        assert d["ret_code"] == 10001
        assert d["ret_msg"] == "invalid symbol"
        assert d["elapsed_ms"] == 312

    def test_frozen(self):
        a = ReconciliationAttempt(
            method="x", endpoint="/y", success=False,
        )
        with pytest.raises(Exception):
            a.success = True  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Captura de retCode/retMsg em BybitAPIError
# ---------------------------------------------------------------------------

class TestCaptureRetCodeRetMsg:

    def test_bybit_api_error_in_realtime_captured(self):
        api_err = BybitAPIError(
            ret_code=10001, ret_msg="invalid symbol",
            endpoint="/v5/order/realtime",
        )
        client = _make_demo_mock_client(
            order_status_raise=api_err,
            order_history_raise=api_err,
            executions_raise=api_err,
            positions=[],
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.RECONCILIATION_FAILED
        # Cada attempt deve ter retCode/retMsg quando BybitAPIError ocorre
        ret_codes = [a.ret_code for a in r.reconciliation_attempts]
        ret_msgs = [a.ret_msg for a in r.reconciliation_attempts]
        assert 10001 in ret_codes
        assert "invalid symbol" in ret_msgs

    def test_attempts_in_deterministic_order(self):
        api_err = BybitAPIError(
            ret_code=10001, ret_msg="x", endpoint="/v5/order/realtime",
        )
        client = _make_demo_mock_client(
            order_status_raise=api_err,
            order_history_raise=api_err,
            executions_raise=api_err,
            positions=[],
        )
        executor, _ = _make_executor(client=client, reconciliation_attempts=2)
        r = executor.execute(_approved(), dry_run=False)
        methods = [a.method for a in r.reconciliation_attempts]
        assert methods[0] == "order_status_attempt_1"
        assert methods[1] == "order_status_attempt_2"
        assert "order_history_fallback" in methods
        assert "executions_triangulation" in methods


# ---------------------------------------------------------------------------
# Caminho legado preservado
# ---------------------------------------------------------------------------

class TestLegacyPathPreserved:

    def test_orderstatus_filled_first_attempt_results_in_filled(self):
        client = _make_demo_mock_client(
            order_status_response={"orderStatus": "Filled"},
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.FILLED
        assert r.reconciliation_confidence == "canonical"
        assert r.manual_review_required is False
        assert r.safety_halt_recommended is False

    def test_history_fallback_filled_results_in_filled(self):
        client = _make_demo_mock_client(
            order_status_response={},  # realtime retorna vazio
            order_history_response=[{"orderStatus": "Filled"}],
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.FILLED
        assert r.reconciliation_confidence == "canonical"


# ---------------------------------------------------------------------------
# Triangulação por executions
# ---------------------------------------------------------------------------

class TestTriangulationExecutions:

    def test_executions_with_matching_order_id_confirms(self):
        client = _make_demo_mock_client(
            order_status_response={},
            order_history_response=[],
            executions_response=[
                {"orderId": "DEMO_ORDER_001", "execId": "E1",
                 "symbol": "BTCUSDT", "side": "Buy",
                 "execPrice": "65000.0", "execQty": "0.003"},
            ],
            positions=[],
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.FILLED_BY_TRIANGULATION
        assert r.reconciliation_confidence == "triangulated"
        assert r.manual_review_required is True
        assert r.safety_halt_recommended is True
        # raw_order_status do trade marca triangulação
        assert r.trade.raw_order_status.get("triangulated_by") == "executions"

    def test_executions_with_qty_mismatch_does_not_confirm(self):
        # 200/65000 = 0.003... executor envia 0.003 → mismatch grande
        client = _make_demo_mock_client(
            order_status_raise=ConnectionError("net"),
            order_history_response=[],
            executions_response=[
                {"orderId": "DEMO_ORDER_001",
                 "symbol": "BTCUSDT", "execQty": "0.5"},  # mismatch
            ],
            positions=[],
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        # Triangulation rejeitou; também não há posição → RECONCILIATION_FAILED
        assert r.trade.status is DemoTradeStatus.RECONCILIATION_FAILED

    def test_executions_with_different_order_id_does_not_confirm(self):
        client = _make_demo_mock_client(
            order_status_raise=ConnectionError("net"),
            order_history_response=[],
            executions_response=[
                {"orderId": "ANOTHER_ORDER",
                 "symbol": "BTCUSDT", "execQty": "0.003"},
            ],
            positions=[],
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.RECONCILIATION_FAILED


# ---------------------------------------------------------------------------
# Triangulação por positions
# ---------------------------------------------------------------------------

class TestTriangulationPositions:

    def test_position_matching_symbol_side_qty_confirms(self):
        client = _make_demo_mock_client(
            order_status_response={},
            order_history_response=[],
            executions_response=[],  # executions não confirma
            positions=[{"symbol": "BTCUSDT", "side": "buy", "size": "0.003"}],
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.FILLED_BY_TRIANGULATION
        assert r.trade.raw_order_status.get("triangulated_by") == "positions"

    def test_position_qty_mismatch_does_not_confirm(self):
        client = _make_demo_mock_client(
            order_status_raise=ConnectionError("net"),
            order_history_response=[],
            executions_response=[],
            positions=[{"symbol": "BTCUSDT", "side": "buy", "size": "0.10"}],
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.RECONCILIATION_FAILED

    def test_position_wrong_side_does_not_confirm(self):
        client = _make_demo_mock_client(
            order_status_raise=ConnectionError("net"),
            order_history_response=[],
            executions_response=[],
            positions=[{"symbol": "BTCUSDT", "side": "sell", "size": "0.003"}],
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.RECONCILIATION_FAILED

    def test_position_wrong_symbol_does_not_confirm(self):
        client = _make_demo_mock_client(
            order_status_raise=ConnectionError("net"),
            order_history_response=[],
            executions_response=[],
            positions=[{"symbol": "ETHUSDT", "side": "buy", "size": "0.003"}],
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.RECONCILIATION_FAILED

    def test_multiple_positions_same_symbol_are_ambiguous(self):
        # Defesa: múltiplas linhas de posição (hedge mode) — não confirma.
        client = _make_demo_mock_client(
            order_status_raise=ConnectionError("net"),
            order_history_response=[],
            executions_response=[],
            positions=[
                {"symbol": "BTCUSDT", "side": "buy", "size": "0.003"},
                {"symbol": "BTCUSDT", "side": "sell", "size": "0.001"},
            ],
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.RECONCILIATION_FAILED


# ---------------------------------------------------------------------------
# Invariante de segurança: record_trade_opened
# ---------------------------------------------------------------------------

class TestRecordTradeOpenedInvariant:

    def test_record_trade_opened_NOT_called_for_filled_by_triangulation(self):
        client = _make_demo_mock_client(
            order_status_response={},
            order_history_response=[],
            executions_response=[
                {"orderId": "DEMO_ORDER_001", "symbol": "BTCUSDT",
                 "execQty": "0.003"},
            ],
            positions=[],
        )
        executor, _ = _make_executor(client=client)
        spy = MagicMock(wraps=executor._risk_engine.record_trade_opened)
        executor._risk_engine.record_trade_opened = spy  # type: ignore[method-assign]
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.FILLED_BY_TRIANGULATION
        spy.assert_not_called()

    def test_record_trade_opened_called_for_canonical_filled(self):
        client = _make_demo_mock_client(
            order_status_response={"orderStatus": "Filled"},
        )
        executor, _ = _make_executor(client=client)
        spy = MagicMock(wraps=executor._risk_engine.record_trade_opened)
        executor._risk_engine.record_trade_opened = spy  # type: ignore[method-assign]
        r = executor.execute(_approved(), dry_run=False)
        assert r.trade.status is DemoTradeStatus.FILLED
        spy.assert_called_once()


# ---------------------------------------------------------------------------
# Safety flags expostas no resultado
# ---------------------------------------------------------------------------

class TestSafetyFlags:

    def test_triangulated_marks_manual_review_required(self):
        client = _make_demo_mock_client(
            order_status_response={},
            order_history_response=[],
            executions_response=[
                {"orderId": "DEMO_ORDER_001", "symbol": "BTCUSDT",
                 "execQty": "0.003"},
            ],
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.manual_review_required is True
        assert r.safety_halt_recommended is True
        assert r.reconciliation_confidence == "triangulated"

    def test_canonical_filled_no_safety_halt(self):
        client = _make_demo_mock_client(
            order_status_response={"orderStatus": "Filled"},
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.manual_review_required is False
        assert r.safety_halt_recommended is False
        assert r.reconciliation_confidence == "canonical"

    def test_reconciliation_failed_confidence_none(self):
        api_err = BybitAPIError(10001, "x", "/v5/order/realtime")
        client = _make_demo_mock_client(
            order_status_raise=api_err,
            order_history_raise=api_err,
            executions_raise=api_err,
            positions=[],
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        assert r.reconciliation_confidence == "none"


# ---------------------------------------------------------------------------
# to_dict retrocompat
# ---------------------------------------------------------------------------

class TestToDictRetrocompat:

    def test_to_dict_omits_attempts_when_empty(self):
        r = DemoExecutionResult(success=True, operation="safe_check")
        d = r.to_dict()
        assert "reconciliation_attempts" not in d
        assert "manual_review_required" not in d
        assert "safety_halt_recommended" not in d
        assert "reconciliation_confidence" not in d

    def test_to_dict_includes_attempts_when_present(self):
        attempts = (
            ReconciliationAttempt(
                method="order_status_attempt_1",
                endpoint="/v5/order/realtime",
                success=False, ret_code=10001, ret_msg="x", elapsed_ms=5,
            ),
        )
        r = DemoExecutionResult(
            success=True, operation="place_order",
            reconciliation_attempts=attempts,
            manual_review_required=True,
            safety_halt_recommended=True,
            reconciliation_confidence="triangulated",
        )
        d = r.to_dict()
        assert "reconciliation_attempts" in d
        assert d["reconciliation_attempts"][0]["method"] == "order_status_attempt_1"
        assert d["manual_review_required"] is True
        assert d["safety_halt_recommended"] is True
        assert d["reconciliation_confidence"] == "triangulated"


# ---------------------------------------------------------------------------
# Sanitização — sem secrets
# ---------------------------------------------------------------------------

class TestNoSecretsInLogsOrResult:

    def test_no_api_key_or_secret_in_reason_or_attempts(self):
        api_err = BybitAPIError(10001, "Some error", "/v5/order/realtime")
        client = _make_demo_mock_client(
            order_status_raise=api_err,
            order_history_raise=api_err,
            executions_raise=api_err,
            positions=[],
        )
        executor, _ = _make_executor(client=client)
        r = executor.execute(_approved(), dry_run=False)
        combined = r.reason.lower() + " ".join(
            (a.ret_msg or "").lower() for a in r.reconciliation_attempts
        )
        for tok in ("api_key", "api_secret", "x-bapi-sign", "bearer ",
                    "authorization"):
            assert tok not in combined

    def test_executor_source_does_not_log_secrets_keywords(self):
        import crypto_trading_bot.execution.bybit_demo_executor as mod
        src = open(mod.__file__, "r", encoding="utf-8").read()
        # Os comentários podem mencionar termos como referência; verificamos
        # que nenhuma string de log/audit contém esses tokens.
        audit_lines = re.findall(
            r"_audit\.[a-z]+\(\s*[\"f]([^)]*)\)", src
        )
        # Nenhum bloco de audit deve incluir esses tokens
        for line in audit_lines:
            lower = line.lower()
            for tok in ("api_key", "apikey", "api_secret", "apisecret",
                         "x-bapi-sign", "bearer "):
                assert tok not in lower, (
                    f"audit log line menciona {tok!r}: {line!r}"
                )
