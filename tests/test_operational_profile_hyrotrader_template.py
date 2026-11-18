"""
Testes de HyroTrader template editável (FASE 16)
==================================================
⚠️  100% offline. ZERO rede. ZERO secrets.

Cobertura:
    - Template marcado como editável (description).
    - Builder aceita overrides em todos os campos relevantes.
    - Nenhum hardcode de regras vinculantes (max_profit_usd etc.).
    - Nenhum módulo de produção consulta provider_name == "HyroTrader".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from crypto_trading_bot.operational_profile import (
    OperationalProfile,
    build_hyrotrader_demo_template,
)


_SRC_ROOT = Path(__file__).parent.parent / "src" / "crypto_trading_bot"


class TestHyroTraderTemplateEditable:

    def test_description_mentions_template_and_editable(self):
        p = build_hyrotrader_demo_template(account_size_usd=5000.0)
        desc = p.description
        assert "template" in desc.lower()
        # "editável" / "editar" / "edit"
        assert "edit" in desc.lower()

    def test_overrides_apply_to_all_relevant_fields(self):
        p = build_hyrotrader_demo_template(
            account_size_usd=25000.0,
            max_concurrent_positions=4,
            max_session_minutes=300,
            pause_after_consecutive_losses=3,
            max_trades_per_session=10,
            allowed_symbols=("BTCUSDT", "ETHUSDT"),
            allowed_hours_utc=((13, 20),),
            kill_switch_enabled=False,
            conservative_mode=False,
            require_manual_ack_on_triangulation=False,
            risk_config_overrides={"max_daily_loss_pct": 0.025},
        )
        assert p.account_size_usd == 25000.0
        assert p.max_concurrent_positions == 4
        assert p.max_session_minutes == 300
        assert p.pause_after_consecutive_losses == 3
        assert p.max_trades_per_session == 10
        assert p.allowed_symbols == ("BTCUSDT", "ETHUSDT")
        assert p.allowed_hours_utc == ((13, 20),)
        assert p.kill_switch_enabled is False
        assert p.conservative_mode is False
        assert p.require_manual_ack_on_triangulation is False
        assert dict(p.risk_config_overrides) == {"max_daily_loss_pct": 0.025}

    def test_no_max_profit_field_exists(self):
        """Challenge target é apenas KPI — nunca regra obrigatória."""
        p = build_hyrotrader_demo_template(account_size_usd=5000.0)
        assert not hasattr(p, "max_profit_usd")
        assert not hasattr(p, "enforce_profit_target")

    def test_no_provider_name_field(self):
        """Diferenciação via flags, não por provider_name."""
        p = build_hyrotrader_demo_template(account_size_usd=5000.0)
        assert not hasattr(p, "provider_name")


class TestProductionDoesNotDependOnHyroTraderName:
    """
    Defesa estrutural: nenhum módulo em core/, risk/ ou execution/ deve
    tomar decisão de comportamento baseado em provider_name == "HyroTrader".
    """

    def _read_module(self, *parts: str) -> str:
        return (_SRC_ROOT.joinpath(*parts)).read_text(encoding="utf-8")

    @pytest.mark.parametrize("rel_path", [
        ("core", "bot_engine.py"),
        ("risk", "risk_engine.py"),
        ("execution", "bybit_demo_executor.py"),
        ("execution", "paper_trader.py"),
    ])
    def test_no_hyrotrader_comparison_in_module(self, rel_path):
        src = self._read_module(*rel_path)
        # Comparações suspeitas (provider_name == "HyroTrader" e variantes)
        forbidden_patterns = [
            'provider_name == "HyroTrader"',
            "provider_name == 'HyroTrader'",
            'provider_name=="HyroTrader"',
            "provider_name=='HyroTrader'",
        ]
        for pattern in forbidden_patterns:
            assert pattern not in src, (
                f"{rel_path}: comparação por provider_name detectada: {pattern}"
            )


class TestTemplateDefaultsAreSafe:

    def test_defaults_force_manual_ack_on_triangulation(self):
        p = build_hyrotrader_demo_template(account_size_usd=5000.0)
        assert p.require_manual_ack_on_triangulation is True

    def test_defaults_enable_kill_switch(self):
        p = build_hyrotrader_demo_template(account_size_usd=5000.0)
        assert p.kill_switch_enabled is True

    def test_defaults_enable_conservative_mode(self):
        p = build_hyrotrader_demo_template(account_size_usd=5000.0)
        assert p.conservative_mode is True


class TestTemplateIsValid:

    def test_self_validation_passes(self):
        from crypto_trading_bot.operational_profile import validate_profile_self
        p = build_hyrotrader_demo_template(account_size_usd=5000.0)
        assert validate_profile_self(p) == []
