"""
Tests - production_wiring (FASE 28)
========================================
100% offline. ZERO network. ZERO BybitClient real instanciado.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from crypto_trading_bot.demo_endurance.production_wiring import (
    EXPECTED_DEMO_ENDPOINT,
    EXPECTED_PROVIDER_ID,
    ProductionWiringError,
    _resolve_demo_endpoint_safely,
    build_live_blueprint_provider,
    build_live_demo_client,
    build_live_demo_executor,
    build_live_preflight_factory,
    build_provider_registry_with_opt_in,
    build_session_plan_factory,
)


# ---------------------------------------------------------------------------
# _resolve_demo_endpoint_safely
# ---------------------------------------------------------------------------

class TestResolveDemoEndpoint:

    def test_endpoint_attr_preferred(self):
        c = MagicMock()
        c.endpoint = "https://api-demo.bybit.com"
        c.base_url = "should-not-use"
        c._base_url = "should-not-use"
        assert _resolve_demo_endpoint_safely(c) == \
            "https://api-demo.bybit.com"

    def test_base_url_fallback(self):
        c = MagicMock(spec=["base_url", "_base_url"])
        c.base_url = "https://api-demo.bybit.com"
        c._base_url = "should-not-use"
        assert _resolve_demo_endpoint_safely(c) == \
            "https://api-demo.bybit.com"

    def test_private_base_url_last_fallback(self):
        c = MagicMock(spec=["_base_url"])
        c._base_url = "https://api-demo.bybit.com"
        assert _resolve_demo_endpoint_safely(c) == \
            "https://api-demo.bybit.com"

    def test_no_attr_returns_none(self):
        class Bare:
            pass
        assert _resolve_demo_endpoint_safely(Bare()) is None


# ---------------------------------------------------------------------------
# build_live_demo_client
# ---------------------------------------------------------------------------

class _FakeClientOK:
    def __init__(self, environment, api_key, api_secret, timeout):
        self.environment = environment
        self._base_url = EXPECTED_DEMO_ENDPOINT
        self.has_credentials = bool(api_key) and bool(api_secret)


class _FakeClientWrongEnv:
    def __init__(self, environment, api_key, api_secret, timeout):
        # Simula env mismatch (testnet ao inves de demo)
        self.environment = "testnet"
        self._base_url = "https://api-testnet.bybit.com"
        self.has_credentials = True


class _FakeClientWrongEndpoint:
    def __init__(self, environment, api_key, api_secret, timeout):
        self.environment = "demo"
        self._base_url = "https://api.bybit.com"  # mainnet!
        self.has_credentials = True


class TestBuildLiveDemoClient:

    def test_happy_path_with_explicit_creds(self, monkeypatch):
        monkeypatch.delenv("ENABLE_LIVE_TRADING", raising=False)
        c = build_live_demo_client(
            client_class=_FakeClientOK,
            api_key="key", api_secret="secret",
        )
        assert c.environment == "demo"

    def test_env_credentials_used_if_no_explicit(self, monkeypatch):
        monkeypatch.delenv("ENABLE_LIVE_TRADING", raising=False)
        monkeypatch.setenv("BYBIT_DEMO_API_KEY", "envkey")
        monkeypatch.setenv("BYBIT_DEMO_API_SECRET", "envsec")
        c = build_live_demo_client(client_class=_FakeClientOK)
        assert c.has_credentials is True

    def test_aborts_if_live_trading_enabled(self, monkeypatch):
        monkeypatch.setenv("ENABLE_LIVE_TRADING", "true")
        with pytest.raises(
            ProductionWiringError, match="ENABLE_LIVE_TRADING"
        ):
            build_live_demo_client(
                client_class=_FakeClientOK,
                api_key="key", api_secret="secret",
            )

    def test_aborts_if_no_credentials(self, monkeypatch):
        monkeypatch.delenv("ENABLE_LIVE_TRADING", raising=False)
        monkeypatch.delenv("BYBIT_DEMO_API_KEY", raising=False)
        monkeypatch.delenv("BYBIT_DEMO_API_SECRET", raising=False)
        with pytest.raises(
            ProductionWiringError, match="BYBIT_DEMO_API_KEY"
        ):
            build_live_demo_client(client_class=_FakeClientOK)

    def test_aborts_if_environment_mismatch(self, monkeypatch):
        monkeypatch.delenv("ENABLE_LIVE_TRADING", raising=False)
        with pytest.raises(
            ProductionWiringError, match="environment"
        ):
            build_live_demo_client(
                client_class=_FakeClientWrongEnv,
                api_key="key", api_secret="secret",
            )

    def test_aborts_if_endpoint_mismatch(self, monkeypatch):
        monkeypatch.delenv("ENABLE_LIVE_TRADING", raising=False)
        with pytest.raises(
            ProductionWiringError, match="endpoint"
        ):
            build_live_demo_client(
                client_class=_FakeClientWrongEndpoint,
                api_key="key", api_secret="secret",
            )

    def test_default_does_not_instantiate_real_bybit_client(
        self, monkeypatch,
    ):
        """Default client_class=None lazy-imports BybitClient, mas o
        nosso patch impede instanciacao. Helper deve falhar com clareza
        em vez de tocar rede."""
        monkeypatch.delenv("ENABLE_LIVE_TRADING", raising=False)
        monkeypatch.delenv("BYBIT_DEMO_API_KEY", raising=False)
        monkeypatch.delenv("BYBIT_DEMO_API_SECRET", raising=False)
        # Sem credentials -> aborta antes do import.
        with pytest.raises(ProductionWiringError):
            build_live_demo_client()


# ---------------------------------------------------------------------------
# build_live_demo_executor
# ---------------------------------------------------------------------------

class _FakeExecutor:
    def __init__(self, client, mode_guard, risk_engine,
                 confirm_demo_execution=False, **kw):
        self.client = client
        self.mode_guard = mode_guard
        self.risk_engine = risk_engine
        self.confirm_demo_execution = confirm_demo_execution
        self.kw = kw


class TestBuildLiveDemoExecutor:

    def test_requires_client(self):
        with pytest.raises(ProductionWiringError, match="client required"):
            build_live_demo_executor(
                client=None, mode_guard=MagicMock(),
                risk_engine=MagicMock(),
                executor_class=_FakeExecutor,
            )

    def test_requires_demo_environment(self):
        c = MagicMock(environment="testnet")
        with pytest.raises(ProductionWiringError, match="demo"):
            build_live_demo_executor(
                client=c, mode_guard=MagicMock(),
                risk_engine=MagicMock(),
                executor_class=_FakeExecutor,
            )

    def test_requires_mode_guard(self):
        c = MagicMock(environment="demo")
        with pytest.raises(ProductionWiringError, match="mode_guard"):
            build_live_demo_executor(
                client=c, mode_guard=None,
                risk_engine=MagicMock(),
                executor_class=_FakeExecutor,
            )

    def test_requires_risk_engine(self):
        c = MagicMock(environment="demo")
        with pytest.raises(ProductionWiringError, match="risk_engine"):
            build_live_demo_executor(
                client=c, mode_guard=MagicMock(),
                risk_engine=None,
                executor_class=_FakeExecutor,
            )

    def test_happy_path_passes_all_deps(self):
        c = MagicMock(environment="demo")
        mg = MagicMock()
        re = MagicMock()
        ex = build_live_demo_executor(
            client=c, mode_guard=mg, risk_engine=re,
            executor_class=_FakeExecutor,
        )
        assert ex.client is c
        assert ex.mode_guard is mg
        assert ex.risk_engine is re
        # Default confirm_demo_execution is False (gate decides).
        assert ex.confirm_demo_execution is False

    def test_confirm_demo_execution_false_by_default(self):
        """FASE 28: gate FASE 22 sempre recebe dry_run=True; executor
        confirm flag pode ficar False sem afetar o caminho dry-run."""
        c = MagicMock(environment="demo")
        ex = build_live_demo_executor(
            client=c, mode_guard=MagicMock(),
            risk_engine=MagicMock(),
            executor_class=_FakeExecutor,
        )
        assert ex.confirm_demo_execution is False

    def test_extra_kwargs_forwarded(self):
        c = MagicMock(environment="demo")
        ex = build_live_demo_executor(
            client=c, mode_guard=MagicMock(),
            risk_engine=MagicMock(),
            executor_class=_FakeExecutor,
            extra_kwargs={"reconciliation_attempts": 1},
        )
        assert ex.kw.get("reconciliation_attempts") == 1


# ---------------------------------------------------------------------------
# build_live_preflight_factory
# ---------------------------------------------------------------------------

class _FakePreflightClass:
    def __init__(self, **kw):
        self.kw = kw

    def run(self):
        return MagicMock(ok=True, manual_confirmations_needed=())


class TestBuildLivePreflightFactory:

    def test_requires_client_demo(self):
        with pytest.raises(ProductionWiringError, match="demo"):
            build_live_preflight_factory(
                client=MagicMock(environment="testnet"),
                mode_guard=MagicMock(),
                risk_engine=MagicMock(),
                symbol="BTCUSDT",
                preflight_class=_FakePreflightClass,
            )

    def test_requires_mode_guard_and_risk(self):
        c = MagicMock(environment="demo")
        with pytest.raises(ProductionWiringError):
            build_live_preflight_factory(
                client=c, mode_guard=None, risk_engine=MagicMock(),
                symbol="BTCUSDT", preflight_class=_FakePreflightClass,
            )

    def test_factory_callable_returns_preflight_run_result(self):
        c = MagicMock(environment="demo")
        fac = build_live_preflight_factory(
            client=c, mode_guard=MagicMock(),
            risk_engine=MagicMock(), symbol="BTCUSDT",
            preflight_class=_FakePreflightClass,
        )
        result = fac()
        assert getattr(result, "ok", False) is True


# ---------------------------------------------------------------------------
# build_live_blueprint_provider
# ---------------------------------------------------------------------------

class TestBuildLiveBlueprintProvider:

    def test_default_ttl(self):
        from crypto_trading_bot.demo_endurance.live_blueprint_provider \
            import LIVE_BLUEPRINT_DEFAULT_TTL_SECONDS
        prov = build_live_blueprint_provider(
            preflight_factory=lambda: MagicMock(),
        )
        assert prov.ttl_seconds == LIVE_BLUEPRINT_DEFAULT_TTL_SECONDS

    def test_custom_ttl(self):
        prov = build_live_blueprint_provider(
            preflight_factory=lambda: MagicMock(), ttl_seconds=30,
        )
        assert prov.ttl_seconds == 30


# ---------------------------------------------------------------------------
# build_provider_registry_with_opt_in
# ---------------------------------------------------------------------------

class TestBuildProviderRegistryWithOptIn:

    def test_opt_in_accepted(self):
        from crypto_trading_bot.execution.provider_capability import (
            ProviderCapability, ProviderStatus,
        )
        from crypto_trading_bot.execution.provider_registry import (
            ProviderEntry, ProviderRegistry,
        )
        reg = ProviderRegistry()
        reg.register(ProviderEntry(
            provider_id=EXPECTED_PROVIDER_ID,
            capability=ProviderCapability(provider_id=EXPECTED_PROVIDER_ID),
            status=ProviderStatus.OPT_IN, reason="test",
        ))
        out = build_provider_registry_with_opt_in(registry=reg)
        assert out is reg

    def test_active_rejected(self):
        from crypto_trading_bot.execution.provider_capability import (
            ProviderCapability, ProviderStatus,
        )
        from crypto_trading_bot.execution.provider_registry import (
            ProviderEntry, ProviderRegistry,
        )
        reg = ProviderRegistry()
        reg.register(ProviderEntry(
            provider_id=EXPECTED_PROVIDER_ID,
            capability=ProviderCapability(provider_id=EXPECTED_PROVIDER_ID),
            status=ProviderStatus.ACTIVE, reason="test",
        ))
        with pytest.raises(ProductionWiringError, match="OPT_IN"):
            build_provider_registry_with_opt_in(registry=reg)

    def test_dry_run_only_rejected(self):
        from crypto_trading_bot.execution.provider_capability import (
            ProviderCapability, ProviderStatus,
        )
        from crypto_trading_bot.execution.provider_registry import (
            ProviderEntry, ProviderRegistry,
        )
        reg = ProviderRegistry()
        reg.register(ProviderEntry(
            provider_id=EXPECTED_PROVIDER_ID,
            capability=ProviderCapability(provider_id=EXPECTED_PROVIDER_ID),
            status=ProviderStatus.DRY_RUN_ONLY, reason="test",
        ))
        with pytest.raises(ProductionWiringError, match="OPT_IN"):
            build_provider_registry_with_opt_in(registry=reg)

    def test_restricted_rejected(self):
        from crypto_trading_bot.execution.provider_capability import (
            ProviderCapability, ProviderStatus,
        )
        from crypto_trading_bot.execution.provider_registry import (
            ProviderEntry, ProviderRegistry,
        )
        reg = ProviderRegistry()
        reg.register(ProviderEntry(
            provider_id=EXPECTED_PROVIDER_ID,
            capability=ProviderCapability(provider_id=EXPECTED_PROVIDER_ID),
            status=ProviderStatus.RESTRICTED, reason="test",
        ))
        with pytest.raises(ProductionWiringError, match="OPT_IN"):
            build_provider_registry_with_opt_in(registry=reg)

    def test_unconfirmed_rejected(self):
        from crypto_trading_bot.execution.provider_capability import (
            ProviderCapability, ProviderStatus,
        )
        from crypto_trading_bot.execution.provider_registry import (
            ProviderEntry, ProviderRegistry,
        )
        reg = ProviderRegistry()
        reg.register(ProviderEntry(
            provider_id=EXPECTED_PROVIDER_ID,
            capability=ProviderCapability(provider_id=EXPECTED_PROVIDER_ID),
            status=ProviderStatus.UNCONFIRMED, reason="test",
        ))
        with pytest.raises(ProductionWiringError, match="OPT_IN"):
            build_provider_registry_with_opt_in(registry=reg)

    def test_provider_missing_rejected(self):
        from crypto_trading_bot.execution.provider_registry import (
            ProviderRegistry,
        )
        reg = ProviderRegistry()  # vazio
        with pytest.raises(ProductionWiringError, match="not registered"):
            build_provider_registry_with_opt_in(registry=reg)


# ---------------------------------------------------------------------------
# build_session_plan_factory
# ---------------------------------------------------------------------------

class TestBuildSessionPlanFactoryInjectable:

    def test_factory_uses_injected_plan_builder(self):
        captured = {}

        def fake_plan_builder(**kw):
            captured.update(kw)
            return MagicMock(plan_id=kw.get("plan_id", "FAKE"))

        factory = build_session_plan_factory(
            plan_builder=fake_plan_builder,
        )
        snap = MagicMock(blueprint=MagicMock(
            side="buy", entry_price=65000.0, stop_loss=64000.0,
            take_profit=66000.0, qty=0.003, notional_usd=195.0,
        ))
        result = factory(
            plan_id="TEST", live_snapshot=snap,
            trading_signal=MagicMock(),
            runner_plan=MagicMock(symbol="BTCUSDT",
                                   strategy_name="trend_pullback"),
            profile=MagicMock(),
            effective_risk_config=MagicMock(),
            now=None,
        )
        assert captured["plan_id"] == "TEST"


# ---------------------------------------------------------------------------
# Module-level guarantees
# ---------------------------------------------------------------------------

class TestModuleHasNoNetworkAtImport:

    def test_imports_lazy_no_bybit_at_module_load(self):
        """Importar production_wiring nao deve puxar BybitClient."""
        # Patcheia BybitClient.__init__ para falhar.
        import crypto_trading_bot.exchange.bybit_client as bcm
        original = bcm.BybitClient.__init__

        def _fail(*a, **kw):
            raise RuntimeError("BybitClient instantiated at import!")

        with patch.object(bcm.BybitClient, "__init__", _fail):
            # Re-import nao deve instanciar.
            import importlib
            import crypto_trading_bot.demo_endurance.production_wiring \
                as pwm
            importlib.reload(pwm)
            assert pwm.EXPECTED_DEMO_ENDPOINT == \
                "https://api-demo.bybit.com"

    def test_module_no_top_level_imports_of_bybit_classes(self):
        from pathlib import Path
        p = Path(__file__).parent.parent / "src" / "crypto_trading_bot" / \
            "demo_endurance" / "production_wiring.py"
        src = p.read_text(encoding="utf-8")
        # Top-level imports - strip docs+comments+function bodies eh
        # complexo; aqui simplesmente checamos que as classes nao
        # aparecem em linha "from X import Y" no nivel do modulo.
        for line in src.split("\n"):
            stripped = line.strip()
            if stripped.startswith("from ") and "import" in stripped:
                # Top-level imports nao devem trazer BybitClient direto.
                # Note: imports dentro de funcoes nao estao no nivel zero.
                # Heuristica simples: lines que nao tem indent.
                if not line.startswith(" ") and not line.startswith("\t"):
                    assert "BybitClient" not in line, (
                        f"BybitClient top-level import: {line}"
                    )
                    assert "BybitDemoExecutor" not in line, (
                        f"BybitDemoExecutor top-level import: {line}"
                    )
                    assert "BybitDemoPreflight" not in line, (
                        f"BybitDemoPreflight top-level import: {line}"
                    )
