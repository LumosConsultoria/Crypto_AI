"""
Testes anti-mutação do risk_adapter (FASE 18)
================================================
⚠️  100% offline. ZERO rede.

Garante invariantes críticas:
    - risk_adapter NÃO importa RiskEngine, BotEngine, BybitClient,
      executores, providers, httpx, requests.
    - Nenhum branch depende de provider_name == "HyroTrader".
    - apply retorna instância distinta do base.
    - base nunca é mutado.
    - os.environ não é modificado.
    - Função pura: chamadas múltiplas com mesmo input geram mesmo output.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from crypto_trading_bot.config.risk_config import RiskConfig
from crypto_trading_bot.operational_profile import (
    apply_profile_overrides_with_gate,
    build_personal_profile,
    build_risk_override_plan,
)


_SRC = (
    Path(__file__).parent.parent
    / "src" / "crypto_trading_bot" / "operational_profile"
    / "risk_adapter.py"
)


def _read_adapter_src() -> str:
    return _SRC.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Imports proibidos
# ---------------------------------------------------------------------------

class TestNoForbiddenImports:

    def test_no_risk_engine_import(self):
        src = _read_adapter_src()
        assert "from crypto_trading_bot.risk.risk_engine" not in src
        assert "import crypto_trading_bot.risk.risk_engine" not in src

    def test_no_bot_engine_import(self):
        src = _read_adapter_src()
        assert "from crypto_trading_bot.core.bot_engine" not in src

    def test_no_bybit_client_import(self):
        src = _read_adapter_src()
        assert "from crypto_trading_bot.exchange.bybit_client" not in src

    def test_no_demo_executor_import(self):
        src = _read_adapter_src()
        assert "from crypto_trading_bot.execution.bybit_demo_executor" not in src
        assert "from crypto_trading_bot.execution.bybit_testnet_executor" not in src

    def test_no_network_imports(self):
        src = _read_adapter_src()
        for tok in ("import httpx", "from httpx",
                    "import requests", "from requests"):
            assert tok not in src


# ---------------------------------------------------------------------------
# Sem branch por provider_name
# ---------------------------------------------------------------------------

class TestNoProviderNameBranch:

    def test_no_hyrotrader_comparison(self):
        src = _read_adapter_src()
        forbidden = [
            'provider_name == "HyroTrader"',
            "provider_name == 'HyroTrader'",
            'provider_name=="HyroTrader"',
            "provider_name=='HyroTrader'",
        ]
        for tok in forbidden:
            assert tok not in src


# ---------------------------------------------------------------------------
# apply nunca muta base
# ---------------------------------------------------------------------------

class TestBaseImmutability:

    def test_base_unchanged_after_apply(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        base = RiskConfig(account_size_usd=5000.0, max_daily_loss_pct=0.05)
        base_dump_before = base.model_dump()
        apply_profile_overrides_with_gate(
            profile, base,
            confirm=True,
            operator_token="op@example.com",
        )
        base_dump_after = base.model_dump()
        assert base_dump_before == base_dump_after

    def test_id_of_new_config_differs(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        base = RiskConfig(account_size_usd=5000.0)
        new_rc = apply_profile_overrides_with_gate(
            profile, base,
            confirm=True,
            operator_token="op@example.com",
        )
        assert id(new_rc) != id(base)


# ---------------------------------------------------------------------------
# os.environ intocado
# ---------------------------------------------------------------------------

class TestEnvNotMutated:

    def test_environ_not_changed(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        env_before = dict(os.environ)
        apply_profile_overrides_with_gate(
            profile, RiskConfig(account_size_usd=5000.0),
            confirm=True,
            operator_token="op@example.com",
        )
        env_after = dict(os.environ)
        assert env_before == env_after


# ---------------------------------------------------------------------------
# Pureza: idempotência
# ---------------------------------------------------------------------------

class TestPureFunction:

    def test_plan_is_deterministic(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        base = RiskConfig(account_size_usd=5000.0)
        outputs = [
            build_risk_override_plan(profile, base).to_dict()
            for _ in range(10)
        ]
        assert all(o == outputs[0] for o in outputs)

    def test_apply_is_deterministic_in_field_values(self):
        profile = build_personal_profile(
            account_size_usd=5000.0,
            risk_config_overrides={"max_daily_loss_pct": 0.03},
        )
        base = RiskConfig(account_size_usd=5000.0)
        n1 = apply_profile_overrides_with_gate(
            profile, base, confirm=True, operator_token="op@example.com",
        )
        n2 = apply_profile_overrides_with_gate(
            profile, base, confirm=True, operator_token="op@example.com",
        )
        # Mesmo conteúdo (mas instâncias distintas)
        assert n1.model_dump() == n2.model_dump()
        assert id(n1) != id(n2)
