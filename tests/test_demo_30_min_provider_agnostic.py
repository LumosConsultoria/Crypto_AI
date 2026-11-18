"""
Tests - Demo30Min provider-agnostic (FASE 26)
================================================
Garante que provider_id eh CAMPO (nao import), validado contra
whitelist na readiness. Estrutura permite adicao futura de outros
providers demo sem mudar interface publica.
"""

from __future__ import annotations

from datetime import datetime, timezone

from crypto_trading_bot.demo_endurance import (
    build_default_planned_blueprint,
    build_demo_30_min_plan,
    build_demo_30_min_readiness_report,
    DEMO_30_MIN_PLANNED_PROVIDER_ID,
    Demo30MinReadinessConfig,
    EnvironmentSnapshot,
)


NOW = datetime(2026, 6, 4, 12, tzinfo=timezone.utc)


def _base(**ov):
    bp = ov.pop("planned_blueprint", build_default_planned_blueprint(now=NOW))
    return Demo30MinReadinessConfig(
        symbol=ov.pop("symbol", "BTCUSDT"),
        strategy_name=ov.pop("strategy_name", "trend_pullback"),
        capital_usd=ov.pop("capital_usd", 5000.0),
        max_orders=ov.pop("max_orders", 1),
        max_session_minutes=ov.pop("max_session_minutes", 30),
        max_trades_per_day=ov.pop("max_trades_per_day", 10),
        operator_token=ov.pop("operator_token", "OPTOK"),
        environment_snapshot=ov.pop(
            "environment_snapshot", EnvironmentSnapshot()
        ),
        planned_blueprint=bp,
    )


class TestProviderIdValidatedInReadiness:

    def test_default_provider_passes(self):
        cfg = _base()
        r = build_demo_30_min_readiness_report(cfg, now=NOW)
        assert r.is_ready

    def test_unknown_provider_blocks(self):
        env = EnvironmentSnapshot(provider_id="unknown_provider")
        cfg = _base(environment_snapshot=env)
        r = build_demo_30_min_readiness_report(cfg, now=NOW)
        assert any(i.gate == "provider" for i in r.blockers)


class TestPlanCarriesProviderIdAsField:

    def test_plan_records_provider(self):
        bp = build_default_planned_blueprint(now=NOW)
        plan = build_demo_30_min_plan(
            symbol="BTCUSDT", strategy_name="trend_pullback",
            max_orders=1, max_session_minutes=30,
            risk_thresholds_snapshot={},
            planned_blueprint=bp,
            operator_token="OPTOK", now=NOW,
        )
        assert plan.provider_id == DEMO_30_MIN_PLANNED_PROVIDER_ID

    def test_plan_does_not_import_bybit_specifics(self):
        # Smoke estrutural: importar Demo30MinPlan nao puxa BybitClient.
        from crypto_trading_bot import demo_endurance
        import sys
        # Carregamos demo_endurance, mas BybitClient nao deve estar
        # entre os modulos puxados POR demo_endurance__init__ direto.
        # (eh aceitavel que outras partes do projeto ja tenham
        # importado BybitClient via outros caminhos.)
        # Garantia: o modulo demo_endurance/__init__.py nao importa
        # bybit_client diretamente.
        from pathlib import Path
        p = Path(demo_endurance.__file__)
        src = p.read_text(encoding="utf-8")
        assert "bybit_client" not in src
        assert "bybit_demo_executor" not in src
        assert "bybit_demo_preflight" not in src
