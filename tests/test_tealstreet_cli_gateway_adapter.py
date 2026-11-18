"""
Testes do TealstreetCliGatewayAdapter — FASE 9B
==================================================
⚠️  100% offline. ZERO secrets reais. ZERO rede. ZERO subprocess. ZERO HTTP.

Cobertura:
    - dry_run obrigatório no construtor; dry_run=False → NotImplementedError.
    - config.simulation_mode obrigatoriamente True.
    - Capability declara supports_webhook=True + supports_cli=True, confirmed=False.
    - Satisfaz ExecutorProtocol estruturalmente.
    - execute() rejeita risk_result.approved=False.
    - build_market_command BUY monta args corretos com cli_path e account_id.
    - build_market_command SELL monta args corretos.
    - build_market_command retorna None quando cli_path ausente.
    - build_hook_payload monta dict com signal data + hook_secret_present flag.
    - build_hook_payload retorna None quando hook_url+hook_id ausentes.
    - Token (SecretStr) NUNCA aparece em config.to_dict(), repr(), payload,
      result.to_dict(), get_summary(), audit/log capturado.
    - Mensagem segura quando faltam configurações.
    - Adapter NÃO importa subprocess/httpx/requests no módulo.
"""

from __future__ import annotations

import io
import sys

import pytest
from pydantic import SecretStr

from crypto_trading_bot.execution import ExecutorProtocol
from crypto_trading_bot.execution.providers import (
    TealstreetCliGatewayAdapter,
    TealstreetDryRunResult,
    TealstreetGatewayConfig,
)
from crypto_trading_bot.risk.risk_engine import (
    OrderSide,
    RiskResult,
    TradingSignal,
)

# Marker estável usado em todos os testes; NUNCA deve aparecer em outputs.
_FAKE_TOKEN_MARKER = "TEALSTREET_TOKEN_SHOULD_NEVER_APPEAR_ANYWHERE_XYZ"


def _signal(side: OrderSide = OrderSide.BUY) -> TradingSignal:
    return TradingSignal(
        symbol="BTCUSDT",
        side=side,
        entry_price=65000.0,
        stop_loss_price=64000.0,
        take_profit_price=67000.0,
        position_size_usd=100.0,
        leverage=1.0,
        strategy_name="test",
    )


def _approved(side: OrderSide = OrderSide.BUY) -> RiskResult:
    return RiskResult(approved=True, reason="ok", signal=_signal(side))


def _blocked() -> RiskResult:
    return RiskResult(approved=False, reason="blocked", signal=_signal())


def _full_config(with_secret: bool = False) -> TealstreetGatewayConfig:
    kwargs = dict(
        cli_path="/opt/tealstreet/bin/tealstreet",
        account_id="demo_account_001",
        hook_url="https://hook.example/abc",
        hook_id="abc",
        simulation_mode=True,
    )
    if with_secret:
        kwargs["hook_secret"] = SecretStr(_FAKE_TOKEN_MARKER)
    return TealstreetGatewayConfig(**kwargs)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class TestTealstreetGatewayConfig:

    def test_defaults_are_all_none_and_simulation_true(self):
        c = TealstreetGatewayConfig()
        assert c.cli_path is None
        assert c.account_id is None
        assert c.hook_url is None
        assert c.hook_id is None
        assert c.hook_secret is None
        assert c.simulation_mode is True

    def test_simulation_mode_false_rejected(self):
        with pytest.raises(ValueError, match="simulation_mode"):
            TealstreetGatewayConfig(simulation_mode=False)

    def test_cli_path_must_be_string(self):
        with pytest.raises(ValueError, match="cli_path"):
            TealstreetGatewayConfig(cli_path=42)  # type: ignore[arg-type]

    def test_hook_secret_must_be_secretstr(self):
        with pytest.raises(ValueError, match="SecretStr"):
            TealstreetGatewayConfig(hook_secret="raw-string")  # type: ignore[arg-type]

    def test_to_dict_never_exposes_secret(self):
        c = TealstreetGatewayConfig(hook_secret=SecretStr(_FAKE_TOKEN_MARKER))
        import json
        blob = json.dumps(c.to_dict())
        assert _FAKE_TOKEN_MARKER not in blob
        assert c.to_dict()["hook_secret_present"] is True

    def test_repr_never_exposes_secret(self):
        c = TealstreetGatewayConfig(hook_secret=SecretStr(_FAKE_TOKEN_MARKER))
        assert _FAKE_TOKEN_MARKER not in repr(c)


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------

class TestAdapterConstructor:

    def test_dry_run_required(self):
        with pytest.raises(TypeError):
            TealstreetCliGatewayAdapter(config=TealstreetGatewayConfig())  # type: ignore[call-arg]

    def test_dry_run_must_be_bool(self):
        with pytest.raises(ValueError, match="dry_run"):
            TealstreetCliGatewayAdapter(
                dry_run=None, config=TealstreetGatewayConfig()  # type: ignore[arg-type]
            )

    def test_dry_run_false_raises_not_implemented(self):
        with pytest.raises(NotImplementedError, match="BLOQUEADO"):
            TealstreetCliGatewayAdapter(
                dry_run=False, config=TealstreetGatewayConfig()
            )

    def test_config_must_be_tealstreet_config(self):
        with pytest.raises(TypeError, match="TealstreetGatewayConfig"):
            TealstreetCliGatewayAdapter(dry_run=True, config={})  # type: ignore[arg-type]

    def test_construction_succeeds_with_minimum(self):
        a = TealstreetCliGatewayAdapter(
            dry_run=True, config=TealstreetGatewayConfig()
        )
        assert a.is_dry_run is True
        assert a.provider_id == "tealstreet_cli_gateway"


# ---------------------------------------------------------------------------
# Capability
# ---------------------------------------------------------------------------

class TestAdapterCapability:

    def test_capability_declares_webhook_and_cli(self):
        a = TealstreetCliGatewayAdapter(
            dry_run=True, config=TealstreetGatewayConfig()
        )
        cap = a.capability
        assert cap.supports_webhook is True
        assert cap.supports_cli is True

    def test_capability_is_demo_not_live(self):
        a = TealstreetCliGatewayAdapter(
            dry_run=True, config=TealstreetGatewayConfig()
        )
        cap = a.capability
        assert cap.is_demo_environment is True
        assert cap.is_live_environment is False
        assert cap.confirmed is False


# ---------------------------------------------------------------------------
# ExecutorProtocol + invariantes
# ---------------------------------------------------------------------------

class TestAdapterContract:

    def test_satisfies_executor_protocol(self):
        a = TealstreetCliGatewayAdapter(
            dry_run=True, config=TealstreetGatewayConfig()
        )
        assert isinstance(a, ExecutorProtocol)

    def test_execute_rejects_unapproved(self):
        a = TealstreetCliGatewayAdapter(
            dry_run=True, config=TealstreetGatewayConfig()
        )
        with pytest.raises(ValueError, match="REJEITA"):
            a.execute(_blocked())

    def test_execute_returns_dry_run_result(self):
        a = TealstreetCliGatewayAdapter(dry_run=True, config=_full_config())
        r = a.execute(_approved())
        assert isinstance(r, TealstreetDryRunResult)
        assert r.success is True
        assert r.dry_run is True
        assert r.provider_id == "tealstreet_cli_gateway"
        assert r.command is not None
        assert r.hook_payload is not None


# ---------------------------------------------------------------------------
# build_market_command
# ---------------------------------------------------------------------------

class TestBuildMarketCommand:

    def test_buy_command_args_with_full_config(self):
        a = TealstreetCliGatewayAdapter(dry_run=True, config=_full_config())
        cmd = a.build_market_command(_signal(OrderSide.BUY))
        assert cmd is not None
        assert "/opt/tealstreet/bin/tealstreet" in cmd[0]
        assert "--simulation" in cmd
        assert "--account" in cmd and "demo_account_001" in cmd
        assert "--symbol" in cmd and "BTCUSDT" in cmd
        assert "--side" in cmd and "buy" in cmd
        assert "--type" in cmd and "market" in cmd

    def test_sell_command_args_with_full_config(self):
        a = TealstreetCliGatewayAdapter(dry_run=True, config=_full_config())
        cmd = a.build_market_command(_signal(OrderSide.SELL))
        assert cmd is not None
        assert "sell" in cmd
        assert "--simulation" in cmd

    def test_no_cli_path_returns_none(self):
        a = TealstreetCliGatewayAdapter(
            dry_run=True,
            config=TealstreetGatewayConfig(account_id="demo"),
        )
        assert a.build_market_command(_signal()) is None

    def test_no_account_id_uses_marker_not_crash(self):
        a = TealstreetCliGatewayAdapter(
            dry_run=True,
            config=TealstreetGatewayConfig(cli_path="/x/cli"),
        )
        cmd = a.build_market_command(_signal())
        assert cmd is not None
        assert "__account_unset__" in cmd


# ---------------------------------------------------------------------------
# build_hook_payload
# ---------------------------------------------------------------------------

class TestBuildHookPayload:

    def test_payload_includes_signal_data(self):
        a = TealstreetCliGatewayAdapter(dry_run=True, config=_full_config())
        p = a.build_hook_payload(_signal())
        assert p is not None
        assert p["symbol"] == "BTCUSDT"
        assert p["side"] == "buy"
        assert p["size_usd"] == 100.0
        assert p["simulation"] is True
        assert p["hook_id"] == "abc"

    def test_payload_marks_hook_secret_present_without_exposing_value(self):
        a = TealstreetCliGatewayAdapter(
            dry_run=True, config=_full_config(with_secret=True)
        )
        p = a.build_hook_payload(_signal())
        assert p is not None
        assert p["hook_secret_present"] is True
        # token NUNCA no payload
        import json
        assert _FAKE_TOKEN_MARKER not in json.dumps(p)

    def test_no_hook_config_returns_none(self):
        a = TealstreetCliGatewayAdapter(
            dry_run=True,
            config=TealstreetGatewayConfig(cli_path="/x"),  # sem hook_*
        )
        assert a.build_hook_payload(_signal()) is None


# ---------------------------------------------------------------------------
# Mensagens seguras quando falta config
# ---------------------------------------------------------------------------

class TestSafeMessages:

    def test_missing_cli_message_in_reason(self):
        a = TealstreetCliGatewayAdapter(
            dry_run=True,
            config=TealstreetGatewayConfig(hook_id="x"),
        )
        r = a.execute(_approved())
        assert r.command is None
        assert "cli_path" in r.reason

    def test_missing_hook_message_in_reason(self):
        a = TealstreetCliGatewayAdapter(
            dry_run=True,
            config=TealstreetGatewayConfig(cli_path="/x"),
        )
        r = a.execute(_approved())
        assert r.hook_payload is None
        assert "hook_url" in r.reason or "hook_id" in r.reason

    def test_missing_both_safe_reason(self):
        a = TealstreetCliGatewayAdapter(
            dry_run=True, config=TealstreetGatewayConfig()
        )
        r = a.execute(_approved())
        assert r.command is None
        assert r.hook_payload is None
        assert r.success is True   # dry-run sempre "sucesso" — só monta o que pode
        assert "config ausente" in r.reason


# ---------------------------------------------------------------------------
# Defesa contra leak de secret
# ---------------------------------------------------------------------------

class TestSecretMasking:

    def test_get_summary_never_exposes_secret(self):
        import json
        a = TealstreetCliGatewayAdapter(
            dry_run=True, config=_full_config(with_secret=True)
        )
        blob = json.dumps(a.get_summary())
        assert _FAKE_TOKEN_MARKER not in blob

    def test_result_to_dict_never_exposes_secret(self):
        import json
        a = TealstreetCliGatewayAdapter(
            dry_run=True, config=_full_config(with_secret=True)
        )
        r = a.execute(_approved())
        blob = json.dumps(r.to_dict())
        assert _FAKE_TOKEN_MARKER not in blob

    def test_repr_never_exposes_secret(self):
        a = TealstreetCliGatewayAdapter(
            dry_run=True, config=_full_config(with_secret=True)
        )
        assert _FAKE_TOKEN_MARKER not in repr(a)

    def test_log_stream_does_not_leak_secret(self):
        """Captura o stream loguru durante init+execute e checa por leak."""
        from loguru import logger as loguru_logger
        buf = io.StringIO()
        sink_id = loguru_logger.add(buf, level="DEBUG")
        try:
            a = TealstreetCliGatewayAdapter(
                dry_run=True, config=_full_config(with_secret=True)
            )
            a.execute(_approved())
        finally:
            loguru_logger.remove(sink_id)
        captured = buf.getvalue()
        assert _FAKE_TOKEN_MARKER not in captured
        # Marcador de presença pode aparecer (booleano "True"), mas nunca o valor.


# ---------------------------------------------------------------------------
# Garantias de ambiente offline
# ---------------------------------------------------------------------------

class TestNoNetworkOrSubprocessAtImport:

    def test_module_does_not_import_subprocess_or_httpx_or_requests(self):
        mod = sys.modules[TealstreetCliGatewayAdapter.__module__]
        for forbidden in ("subprocess", "httpx", "requests", "urllib3"):
            assert not hasattr(mod, forbidden), (
                f"módulo expõe '{forbidden}' — adapter não deve carregar rede/IO real nesta fase"
            )
