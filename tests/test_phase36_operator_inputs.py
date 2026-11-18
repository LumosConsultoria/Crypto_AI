"""
Tests - FASE 36 Bloco L: Operator Required Inputs
==================================================
100% offline (store em tmp_path). Valores aqui sao FIXTURES DE TESTE
explicitamente marcadas — nao sao limites operacionais reais.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from crypto_trading_bot.operator_inputs import (
    InputStatus,
    OperatorInputRequirement,
    OperatorInputStore,
    InputSource,
    InputType,
    build_default_schema,
    build_required_inputs_for_demo_report,
    get_effective_value,
    validate_operator_inputs,
)

_REPO_ROOT = Path(__file__).parent.parent
_NOW = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)

# FIXTURE DE TESTE: valores arbitrarios para exercitar o mecanismo.
_TEST_VALUES = {
    "session_capital_usd": 5000.0,
    "account_type": "demo_validation",
    "account_currency": "USDT",
    "operational_timezone": "America/Sao_Paulo",
    "profile_name": "demo_multi_order_validation",
    "max_risk_per_trade_pct": 0.2,
    "max_daily_loss_pct": 1.0,
    "max_session_loss_pct": 1.0,
    "max_total_loss_pct": 2.0,
    "max_drawdown_pct": 2.0,
    "max_position_notional_usd": 200.0,
    "max_exposure_per_symbol": 200.0,
    "max_total_exposure": 200.0,
    "max_leverage": 1.0,
    "max_open_positions": 1,
    "max_orders_per_session": 2,
    "max_orders_per_day": 3,
    "max_consecutive_losses": 2,
    "cooldown_after_loss_minutes": 30,
    "kill_switch_loss_limit_usd": 100.0,
    "allow_multi_order_sequential": True,
    "strategy_name": "trend_pullback_bidirectional",
    "strategy_params_accepted": True,
    "demo_real_authorized": True,
    "max_real_orders_per_session": 2,
    "max_session_duration_minutes": 30,
    "blueprint_ttl_max_seconds": 60,
}

_CONFIRM_IDS = (
    "allow_multi_order_sequential", "strategy_params_accepted",
    "demo_real_authorized", "allow_auto_reduce_only_close",
)


def _fill_store(store, *, confirm=True):
    for input_id, value in _TEST_VALUES.items():
        store.set_value(
            input_id, value, operator_token="test_operator", now=_NOW,
        )
    store.set_value(
        "allow_auto_reduce_only_close", True,
        operator_token="test_operator", now=_NOW,
    )
    if confirm:
        for input_id in _CONFIRM_IDS:
            store.confirm(
                input_id, operator_token="test_operator", now=_NOW,
            )


class TestSchema:

    def test_schema_covers_all_categories(self):
        schema = build_default_schema()
        cats = {r.category for r in schema}
        assert cats == {
            "account", "risk", "position_mgmt", "strategy",
            "ai_mi", "demo_execution",
        }
        assert len(schema) >= 35

    def test_no_invented_defaults_for_risk_fields(self):
        # NENHUM campo de risco obrigatorio tem default (regra: nao
        # inventar limites).
        for req in build_default_schema():
            if req.category == "risk" and req.required_for_demo:
                assert req.safe_default is None, req.input_id
                assert not req.can_have_default, req.input_id

    def test_dangerous_capabilities_default_off(self):
        schema = {r.input_id: r for r in build_default_schema()}
        assert schema["allow_scale_in"].safe_default is False
        assert schema["allow_partial_reduce"].safe_default is False
        assert schema["allow_reversal"].safe_default == "blocked"


class TestStoreAudit:

    def test_set_and_audit_trail_before_after(self, tmp_path):
        store = OperatorInputStore(str(tmp_path / "inputs.json"))
        store.set_value(
            "session_capital_usd", 5000.0,
            operator_token="op1", now=_NOW,
        )
        store.set_value(
            "session_capital_usd", 6000.0,
            operator_token="op2", now=_NOW + timedelta(hours=1),
        )
        trail = store.audit_trail
        assert len(trail) == 2
        assert trail[1]["old_value"] == 5000.0
        assert trail[1]["new_value"] == 6000.0
        assert trail[1]["operator_token"] == "op2"

    def test_persistence_roundtrip(self, tmp_path):
        path = str(tmp_path / "inputs.json")
        store = OperatorInputStore(path)
        store.set_value(
            "max_leverage", 1.0, operator_token="op", now=_NOW,
        )
        store2 = OperatorInputStore(path)
        val = store2.get("max_leverage")
        assert val is not None and val.value == 1.0

    def test_confirm_flow(self, tmp_path):
        store = OperatorInputStore(str(tmp_path / "i.json"))
        assert store.confirm("x", operator_token="op") is False
        store.set_value(
            "demo_real_authorized", True,
            operator_token="op", now=_NOW,
        )
        assert store.confirm(
            "demo_real_authorized", operator_token="op",
        )
        assert store.get("demo_real_authorized").confirmed

    def test_path_traversal_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="\\.\\."):
            OperatorInputStore(str(tmp_path / ".." / "evil.json"))


class TestValidation:

    def test_empty_store_blocks_everything(self, tmp_path):
        store = OperatorInputStore(str(tmp_path / "i.json"))
        result = validate_operator_inputs(
            schema=build_default_schema(), store=store, now=_NOW,
        )
        assert result.blocks_readiness
        assert result.blocks_execution
        assert any(
            m.input_id == "session_capital_usd"
            for m in result.missing
        )

    def test_filled_and_confirmed_store_unblocks(self, tmp_path):
        store = OperatorInputStore(str(tmp_path / "i.json"))
        _fill_store(store)
        result = validate_operator_inputs(
            schema=build_default_schema(), store=store, now=_NOW,
        )
        assert not result.blocks_execution, [
            m.to_dict() for m in result.missing
        ]
        assert not result.blocks_readiness

    def test_unconfirmed_value_blocks(self, tmp_path):
        store = OperatorInputStore(str(tmp_path / "i.json"))
        _fill_store(store, confirm=False)
        result = validate_operator_inputs(
            schema=build_default_schema(), store=store, now=_NOW,
        )
        assert result.blocks_execution
        st = result.statuses["demo_real_authorized"]
        assert st == InputStatus.NEEDS_CONFIRMATION.value

    def test_invalid_value_blocks(self, tmp_path):
        store = OperatorInputStore(str(tmp_path / "i.json"))
        _fill_store(store)
        store.set_value(
            "max_leverage", 99.0,   # > max 10
            operator_token="op", now=_NOW,
        )
        result = validate_operator_inputs(
            schema=build_default_schema(), store=store, now=_NOW,
        )
        assert result.statuses["max_leverage"] == "invalid"
        assert result.blocks_execution

    def test_stale_value_reblocks(self, tmp_path):
        schema = (OperatorInputRequirement(
            input_id="test_field", label="t", description="t",
            input_type=InputType.DECIMAL, category="risk",
            expected_source=InputSource.OPERATOR_REQUIRED,
            required_for_demo=True,
            blocks_execution_if_missing=True,
            blocks_readiness_if_missing=True,
            max_age_days=7,
        ),)
        store = OperatorInputStore(str(tmp_path / "i.json"))
        store.set_value(
            "test_field", 1.0, operator_token="op",
            now=_NOW - timedelta(days=30),
        )
        result = validate_operator_inputs(
            schema=schema, store=store, now=_NOW,
        )
        assert result.statuses["test_field"] == "stale"
        assert result.blocks_execution

    def test_effective_value_never_invented(self, tmp_path):
        schema = build_default_schema()
        store = OperatorInputStore(str(tmp_path / "i.json"))
        # Sem valor e sem default => None (nunca inventado).
        assert get_effective_value(
            schema=schema, store=store,
            input_id="max_risk_per_trade_pct",
        ) is None
        # Default seguro OFF existe apenas p/ capacidades perigosas.
        assert get_effective_value(
            schema=schema, store=store, input_id="allow_scale_in",
        ) is False


class TestDemoReport:

    def test_report_shape_and_blocking(self, tmp_path):
        store = OperatorInputStore(str(tmp_path / "i.json"))
        report = build_required_inputs_for_demo_report(
            schema=build_default_schema(), store=store, now=_NOW,
        )
        assert report["blocks_execution"] is True
        assert "operator_required" in report["by_source"]
        assert report["missing"]
        assert "NENHUM valor e inventado" in report["note"]

    def test_report_clean_when_filled(self, tmp_path):
        store = OperatorInputStore(str(tmp_path / "i.json"))
        _fill_store(store)
        report = build_required_inputs_for_demo_report(
            schema=build_default_schema(), store=store, now=_NOW,
        )
        assert report["blocks_execution"] is False


class TestInputsCLI:

    def _run(self, *args, timeout=120):
        return subprocess.run(
            [sys.executable,
             str(_REPO_ROOT / "scripts" / "run_operator_inputs.py"),
             *args],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
            timeout=timeout, check=False,
        )

    def test_list_and_set_and_report(self, tmp_path):
        store_path = str(tmp_path / "inputs.json")
        r = self._run("--store", store_path, "--list")
        assert r.returncode == 0
        assert "session_capital_usd" in r.stdout
        r2 = self._run(
            "--store", store_path, "--operator-token", "t_op",
            "--set", "session_capital_usd=5000",
        )
        assert r2.returncode == 0 and "SET" in r2.stdout
        out = tmp_path / "report.json"
        r3 = self._run(
            "--store", store_path, "--report",
            "--output", str(out),
        )
        assert r3.returncode == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["blocks_execution"] is True  # ainda falta muito

    def test_set_requires_token(self, tmp_path):
        r = self._run(
            "--store", str(tmp_path / "i.json"),
            "--set", "max_leverage=1",
        )
        assert r.returncode == 1
        assert "operator-token" in r.stdout

    def test_unknown_id_rejected(self, tmp_path):
        r = self._run(
            "--store", str(tmp_path / "i.json"),
            "--operator-token", "t", "--set", "fake_field=1",
        )
        assert r.returncode == 1


class TestEnduranceCLIIntegration:

    def test_real_multi_requires_inputs_store(self):
        env_args = [
            sys.executable,
            str(_REPO_ROOT / "scripts" / "run_demo_endurance.py"),
            "--profile", "demo_multi_order_validation",
            "--capital", "5000", "--duration-minutes", "30",
            "--demo-only", "--real-time", "--operator-token", "T",
            "--execute-demo-real-multi", "--confirm-demo-real-multi",
            "--first-real-demo-multi-order-fase30",
            "--max-real-orders", "2",
        ]
        r = subprocess.run(
            env_args, capture_output=True, text=True,
            cwd=str(_REPO_ROOT), timeout=120, check=False,
        )
        assert r.returncode == 1
        assert "--inputs-store" in r.stdout

    def test_real_multi_blocked_with_empty_inputs(self, tmp_path):
        store_path = str(tmp_path / "inputs.json")
        OperatorInputStore(store_path)  # vazio
        r = subprocess.run(
            [sys.executable,
             str(_REPO_ROOT / "scripts" / "run_demo_endurance.py"),
             "--profile", "demo_multi_order_validation",
             "--capital", "5000", "--duration-minutes", "30",
             "--demo-only", "--real-time", "--operator-token", "T",
             "--execute-demo-real-multi", "--confirm-demo-real-multi",
             "--first-real-demo-multi-order-fase30",
             "--max-real-orders", "2",
             "--inputs-store", store_path],
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
            timeout=120, check=False,
        )
        assert r.returncode == 1
        assert "blocked_missing_operator_input" in r.stdout
