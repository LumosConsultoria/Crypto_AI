"""
Testes do scripts/run_bybit_demo_diagnostic.py — FASE 9 Fatia 3
==================================================================
⚠️  100% offline. ZERO secrets reais. ZERO rede. ZERO ordens.

Cobertura:
    - main(argv) é testável e idempotente.
    - Default (sem flags) e --dry-run: exit 0, NÃO chama get_balance.
    - --safe-check sem --confirm-demo-execution: exit 1 (ModeGuard).
    - --safe-check em TRADING_MODE=paper: exit 1.
    - --safe-check com ENABLE_DEMO_EXECUTION=false: exit 1.
    - --safe-check com endpoint resolvido != api-demo.bybit.com: exit 1.
    - --safe-check sem credentials: exit 1.
    - --safe-check com triple-lock OK + endpoint=demo + creds:
        → chama BybitClient.get_balance() EXATAMENTE 1 vez.
        → NUNCA chama place_market_order/cancel_order/get_order_status.
        → retorna exit 0 e relatório sanitizado.
    - --execute-demo-order envia ordem real demo após as 7 travas (Fatia 4B):
      triple-flag-lock + sizing > 0 + ModeGuard + endpoint + credentials +
      provider gate + RiskEngine. Falha em qualquer trava aborta sem rede.
    - Stream de log capturado NÃO contém valor real de api_key/secret.
"""

from __future__ import annotations

import importlib
import io
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Garante src/ no path para importar o script via runpy/importlib.
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT / "src"))


# Carregamento estável do script (não está em src/, está em scripts/).
_SCRIPT_PATH = _ROOT / "scripts" / "run_bybit_demo_diagnostic.py"


def _load_script_module():
    """Carrega o script como módulo Python para importar `main`."""
    spec = importlib.util.spec_from_file_location(
        "run_bybit_demo_diagnostic", _SCRIPT_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_FAKE_KEY_MARKER = "TEALDEMO_FAKE_KEY_SHOULD_NEVER_APPEAR_IN_OUTPUT_XYZ"
_FAKE_SECRET_MARKER = "TEALDEMO_FAKE_SECRET_SHOULD_NEVER_APPEAR_IN_OUTPUT_XYZ"


def _setup_demo_env(monkeypatch, *, mode="demo", enable_demo=True, use_demo=True,
                    api_key=_FAKE_KEY_MARKER, api_secret=_FAKE_SECRET_MARKER):
    """Configura env vars que fazem Settings/ExchangeConfig resolverem para demo."""
    monkeypatch.setenv("TRADING_MODE", mode)
    monkeypatch.setenv("ENABLE_LIVE_TRADING", "false")
    monkeypatch.setenv("ENABLE_TESTNET_EXECUTION", "false")
    monkeypatch.setenv("ENABLE_DEMO_EXECUTION", "true" if enable_demo else "false")
    monkeypatch.setenv("EXECUTOR_TYPE", "paper")
    monkeypatch.setenv("PROVIDER_ID", "paper")
    monkeypatch.setenv("BYBIT_USE_TESTNET", "false")
    monkeypatch.setenv("BYBIT_USE_DEMO", "true" if use_demo else "false")
    monkeypatch.setenv("BYBIT_ENVIRONMENT", "demo" if use_demo else "")
    if api_key is not None:
        monkeypatch.setenv("BYBIT_API_KEY", api_key)
    if api_secret is not None:
        monkeypatch.setenv("BYBIT_API_SECRET", api_secret)

    # IMPORTANTE: get_settings tem lru_cache; limpar para que reabra env vars.
    from crypto_trading_bot.config.settings import get_settings
    get_settings.cache_clear()


def _setup_paper_env(monkeypatch):
    """Env vars de modo paper (default) — não autoriza demo."""
    _setup_demo_env(monkeypatch, mode="paper", enable_demo=False, use_demo=False)


def _patch_bybit_client(monkeypatch, *, balance_response=None,
                        raise_exception=None):
    """
    Patch da classe BybitClient para evitar qualquer chamada httpx real.

    Retorna o MagicMock instance que será devolvido por BybitClient(...).
    """
    instance = MagicMock(name="BybitClient_demo_mock")
    # Atributos lidos pelo script
    instance.environment = "demo"
    instance._base_url = "https://api-demo.bybit.com"
    instance.is_demo = True

    if raise_exception is not None:
        instance.get_balance.side_effect = raise_exception
    else:
        instance.get_balance.return_value = balance_response or {"list": []}

    # Patch construtor para retornar o mock e RAStreaR chamadas
    import crypto_trading_bot.exchange.bybit_client as bc_mod
    monkeypatch.setattr(bc_mod, "BybitClient", MagicMock(return_value=instance))
    return instance


# ===========================================================================
# Cenários: dry-run e --dry-run flag
# ===========================================================================

class TestDryRunDoesNothing:

    def test_default_no_flags_exits_zero(self, monkeypatch):
        _setup_paper_env(monkeypatch)
        mod = _load_script_module()
        # Mesmo em paper, dry-run não chama nada
        client_mock = _patch_bybit_client(monkeypatch)
        rc = mod.main([])
        assert rc == 0
        client_mock.get_balance.assert_not_called()

    def test_explicit_dry_run_flag_exits_zero(self, monkeypatch):
        _setup_paper_env(monkeypatch)
        mod = _load_script_module()
        client_mock = _patch_bybit_client(monkeypatch)
        rc = mod.main(["--dry-run"])
        assert rc == 0
        client_mock.get_balance.assert_not_called()


# ===========================================================================
# Cenários: --safe-check sem prereqs corretos
# ===========================================================================

class TestSafeCheckBlockedByPreconditions:

    def test_blocked_without_confirm_demo_execution(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        mod = _load_script_module()
        client_mock = _patch_bybit_client(monkeypatch)
        rc = mod.main(["--safe-check"])  # sem --confirm-demo-execution
        assert rc == 1
        client_mock.get_balance.assert_not_called()

    def test_blocked_in_paper_mode(self, monkeypatch):
        _setup_paper_env(monkeypatch)
        mod = _load_script_module()
        client_mock = _patch_bybit_client(monkeypatch)
        rc = mod.main(["--safe-check", "--confirm-demo-execution"])
        assert rc == 1
        client_mock.get_balance.assert_not_called()

    def test_blocked_when_enable_demo_execution_false(self, monkeypatch):
        _setup_demo_env(monkeypatch, enable_demo=False)
        mod = _load_script_module()
        client_mock = _patch_bybit_client(monkeypatch)
        rc = mod.main(["--safe-check", "--confirm-demo-execution"])
        assert rc == 1
        client_mock.get_balance.assert_not_called()

    def test_blocked_when_endpoint_not_api_demo(self, monkeypatch):
        # TRADING_MODE=demo + ENABLE_DEMO_EXECUTION=true MAS BYBIT_USE_DEMO=false
        # → exchange.rest_url cai em testnet (BYBIT_USE_TESTNET=true por default)
        _setup_demo_env(monkeypatch, use_demo=False)
        monkeypatch.setenv("BYBIT_USE_TESTNET", "true")
        mod = _load_script_module()
        client_mock = _patch_bybit_client(monkeypatch)
        rc = mod.main(["--safe-check", "--confirm-demo-execution"])
        assert rc == 1
        client_mock.get_balance.assert_not_called()

    def test_blocked_without_credentials(self, monkeypatch):
        # Strings vazias fazem ExchangeConfig.has_credentials retornar False
        # (env vars têm precedência sobre o .env real, então isso "apaga" qualquer
        # credencial presente no arquivo).
        _setup_demo_env(monkeypatch, api_key="", api_secret="")
        mod = _load_script_module()
        client_mock = _patch_bybit_client(monkeypatch)
        rc = mod.main(["--safe-check", "--confirm-demo-execution"])
        assert rc == 1
        client_mock.get_balance.assert_not_called()


# ===========================================================================
# Cenário: --safe-check com tudo OK
# ===========================================================================

class TestSafeCheckSuccessPath:

    def test_safe_check_calls_get_balance_exactly_once(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        client_mock = _patch_bybit_client(monkeypatch)
        mod = _load_script_module()
        rc = mod.main(["--safe-check", "--confirm-demo-execution"])
        assert rc == 0
        assert client_mock.get_balance.call_count == 1

    def test_safe_check_never_calls_place_or_cancel(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        client_mock = _patch_bybit_client(monkeypatch)
        mod = _load_script_module()
        mod.main(["--safe-check", "--confirm-demo-execution"])
        client_mock.place_market_order.assert_not_called()
        client_mock.cancel_order.assert_not_called()
        client_mock.get_order_status.assert_not_called()

    def test_safe_check_failure_returns_exit_1(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        client_mock = _patch_bybit_client(
            monkeypatch, raise_exception=ConnectionError("simulated demo network fail")
        )
        mod = _load_script_module()
        rc = mod.main(["--safe-check", "--confirm-demo-execution"])
        assert rc == 1
        client_mock.get_balance.assert_called_once()


# ===========================================================================
# Cenário: --execute-demo-order — FATIA 4B (envio real gated)
# ===========================================================================

def _patch_bybit_client_for_order(
    monkeypatch,
    *,
    order_id: str = "DEMO_ORDER_001",
    order_status_response: dict | None = None,
    positions_response: list | None = None,
    order_history_response: list | None = None,
    place_raise: Exception | None = None,
):
    """Patch BybitClient para testar o caminho --execute-demo-order."""
    from datetime import datetime, timezone

    from crypto_trading_bot.exchange.base_exchange import OrderResult

    instance = MagicMock(name="BybitClient_demo_order_mock")
    instance.environment = "demo"
    instance._base_url = "https://api-demo.bybit.com"
    instance.is_demo = True
    instance.has_credentials = True

    # safe-check ainda usa get_balance — mockar para os outros testes
    instance.get_balance.return_value = {"list": []}

    if place_raise is not None:
        instance.place_market_order.side_effect = place_raise
    else:
        instance.place_market_order.return_value = OrderResult(
            order_id=order_id,
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            qty=0.003,
            price=None,
            status="submitted",
            fee=0.0,
            timestamp=datetime.now(timezone.utc),
        )
    instance.get_order_status.return_value = (
        order_status_response if order_status_response is not None
        else {"orderStatus": "Filled"}
    )
    # FASE 9 hardening: fallback de reconciliação
    instance.get_order_history.return_value = (
        order_history_response if order_history_response is not None
        else []
    )
    instance.get_positions.return_value = (
        positions_response if positions_response is not None
        else [{"symbol": "BTCUSDT", "side": "buy", "size": "0.003"}]
    )

    import crypto_trading_bot.exchange.bybit_client as bc_mod
    monkeypatch.setattr(bc_mod, "BybitClient", MagicMock(return_value=instance))
    return instance


def _minimum_order_args() -> list[str]:
    """Args mínimos para o caminho --execute-demo-order.

    Nota FASE 14 (qty hardening): position-size escolhido para garantir
    qty >= qty_step=0.001 do BTCUSDT linear demo. 200 USD / 65000 USD/BTC
    = 0.003... → normalizado a 0.003 (acima do step).
    """
    return [
        "--execute-demo-order",
        "--confirm-demo-execution",
        "--i-understand-this-is-demo",
        "--symbol", "BTCUSDT",
        "--side", "buy",
        "--capital", "1000",
        "--position-size", "200",
        "--entry-price", "65000",
        "--stop-loss", "64000",
        "--leverage", "1.0",
    ]


class TestExecuteDemoOrderTripleFlagLock:
    """Triple-flag-lock: todas as 3 flags exigidas."""

    def test_blocked_without_confirm_demo_execution(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        client = _patch_bybit_client_for_order(monkeypatch)
        mod = _load_script_module()
        # Remove --confirm-demo-execution
        args = [a for a in _minimum_order_args() if a != "--confirm-demo-execution"]
        rc = mod.main(args)
        assert rc == 1
        client.place_market_order.assert_not_called()

    def test_blocked_without_i_understand_this_is_demo(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        client = _patch_bybit_client_for_order(monkeypatch)
        mod = _load_script_module()
        args = [a for a in _minimum_order_args() if a != "--i-understand-this-is-demo"]
        rc = mod.main(args)
        assert rc == 1
        client.place_market_order.assert_not_called()


class TestExecuteDemoOrderSizingValidation:
    """Sizing > 0 obrigatório para cada flag."""

    @pytest.mark.parametrize("flag_to_remove,flag_value", [
        ("--capital", "1000"),
        ("--position-size", "5"),
        ("--entry-price", "65000"),
        ("--stop-loss", "64000"),
        ("--leverage", "1.0"),
    ])
    def test_blocked_when_sizing_param_missing(self, monkeypatch, flag_to_remove, flag_value):
        _setup_demo_env(monkeypatch)
        client = _patch_bybit_client_for_order(monkeypatch)
        mod = _load_script_module()
        args = _minimum_order_args()
        idx = args.index(flag_to_remove)
        # Remove a flag e seu valor (pares consecutivos)
        del args[idx:idx + 2]
        rc = mod.main(args)
        assert rc == 1
        client.place_market_order.assert_not_called()

    @pytest.mark.parametrize("flag", [
        "--capital", "--position-size", "--entry-price",
        "--stop-loss", "--leverage",
    ])
    def test_blocked_when_sizing_param_zero(self, monkeypatch, flag):
        _setup_demo_env(monkeypatch)
        client = _patch_bybit_client_for_order(monkeypatch)
        mod = _load_script_module()
        args = _minimum_order_args()
        idx = args.index(flag)
        args[idx + 1] = "0"  # zera o valor
        rc = mod.main(args)
        assert rc == 1
        client.place_market_order.assert_not_called()


class TestExecuteDemoOrderModeGuardGates:

    def test_blocked_in_paper_mode(self, monkeypatch):
        _setup_paper_env(monkeypatch)
        client = _patch_bybit_client_for_order(monkeypatch)
        mod = _load_script_module()
        rc = mod.main(_minimum_order_args())
        assert rc == 1
        client.place_market_order.assert_not_called()

    def test_blocked_when_enable_demo_execution_false(self, monkeypatch):
        _setup_demo_env(monkeypatch, enable_demo=False)
        client = _patch_bybit_client_for_order(monkeypatch)
        mod = _load_script_module()
        rc = mod.main(_minimum_order_args())
        assert rc == 1
        client.place_market_order.assert_not_called()

    def test_blocked_when_endpoint_not_api_demo(self, monkeypatch):
        # BYBIT_USE_DEMO=false → endpoint cai em testnet (BYBIT_USE_TESTNET=true)
        _setup_demo_env(monkeypatch, use_demo=False)
        monkeypatch.setenv("BYBIT_USE_TESTNET", "true")
        client = _patch_bybit_client_for_order(monkeypatch)
        mod = _load_script_module()
        rc = mod.main(_minimum_order_args())
        assert rc == 1
        client.place_market_order.assert_not_called()


class TestExecuteDemoOrderRiskEngineGate:

    def test_blocked_when_riskengine_rejects(self, monkeypatch):
        """RiskEngine rejeita: stop_loss exatamente igual a entry → SL pct=0."""
        _setup_demo_env(monkeypatch)
        client = _patch_bybit_client_for_order(monkeypatch)
        mod = _load_script_module()
        args = _minimum_order_args()
        # Força stop_loss == entry_price → distância 0 → RiskEngine rejeita
        idx_sl = args.index("--stop-loss")
        idx_entry = args.index("--entry-price")
        args[idx_sl + 1] = args[idx_entry + 1]  # stop_loss = entry_price
        rc = mod.main(args)
        assert rc == 1
        # Falhou ANTES de tentar enviar ordem
        client.place_market_order.assert_not_called()


class TestExecuteDemoOrderHappyPath:

    def test_calls_executor_execute_dry_run_false_when_all_gates_pass(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        client = _patch_bybit_client_for_order(monkeypatch)
        mod = _load_script_module()
        rc = mod.main(_minimum_order_args())
        assert rc == 0
        client.place_market_order.assert_called_once()

    def test_payload_uses_qty_from_position_size_div_entry_price(self, monkeypatch):
        # FASE 14 (qty hardening): qty é normalizado ao qty_step=0.001
        # com ROUND_DOWN. 200/65000 = 0.00307692... → 0.003 (BTCUSDT linear).
        _setup_demo_env(monkeypatch)
        client = _patch_bybit_client_for_order(monkeypatch)
        mod = _load_script_module()
        mod.main(_minimum_order_args())
        kwargs = client.place_market_order.call_args.kwargs
        assert kwargs["qty"] == pytest.approx(0.003)

    def test_payload_does_not_include_reduce_only(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        client = _patch_bybit_client_for_order(monkeypatch)
        mod = _load_script_module()
        mod.main(_minimum_order_args())
        kwargs = client.place_market_order.call_args.kwargs
        assert "reduceOnly" not in kwargs and "reduce_only" not in kwargs

    def test_calls_reconciliation_endpoints(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        client = _patch_bybit_client_for_order(monkeypatch)
        mod = _load_script_module()
        mod.main(_minimum_order_args())
        client.get_order_status.assert_called_once()
        client.get_positions.assert_called_once()


class TestExecuteDemoOrderLogSanitization:

    def test_log_during_real_execute_does_not_leak_markers(self, monkeypatch, capsys):
        from loguru import logger as loguru_logger
        _setup_demo_env(monkeypatch)
        # Cliente que falha com mensagem contendo markers
        client = _patch_bybit_client_for_order(
            monkeypatch,
            place_raise=RuntimeError(
                f"X-BAPI-SIGN: sig api_key={_FAKE_KEY_MARKER}"
            ),
        )
        mod = _load_script_module()
        buf = io.StringIO()
        sink_id = loguru_logger.add(buf, level="DEBUG")
        try:
            rc = mod.main(_minimum_order_args())
        finally:
            loguru_logger.remove(sink_id)
        assert rc == 1
        stdout = capsys.readouterr().out
        log = buf.getvalue()
        assert _FAKE_KEY_MARKER not in stdout
        assert _FAKE_KEY_MARKER not in log
        assert _FAKE_SECRET_MARKER not in stdout
        assert _FAKE_SECRET_MARKER not in log


class TestSafeCheckStillWorksAfterFatia4B:
    """Regressão: safe-check da Fatia 3 continua funcionando após mudanças."""

    def test_safe_check_still_calls_get_balance(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        client = _patch_bybit_client_for_order(monkeypatch)
        mod = _load_script_module()
        rc = mod.main(["--safe-check", "--confirm-demo-execution"])
        assert rc == 0
        client.get_balance.assert_called()
        # Safe-check NÃO chama place_market_order
        client.place_market_order.assert_not_called()


# ===========================================================================
# Cenário: --prepare-demo-order — preflight automático (Fatia 4B+)
# ===========================================================================

def _patch_bybit_client_for_preflight(monkeypatch):
    """Patch BybitClient para preflight: mock de TODOS os endpoints read-only."""
    from crypto_trading_bot.exchange.base_exchange import OrderBook, Ticker

    instance = MagicMock(name="BybitClient_preflight_mock")
    instance.environment = "demo"
    instance._base_url = "https://api-demo.bybit.com"
    instance.is_demo = True
    instance.has_credentials = True

    instance.get_instruments_info.return_value = {
        "symbol": "BTCUSDT",
        "lotSizeFilter": {
            "minOrderQty": "0.001", "maxOrderQty": "1190.000",
            "qtyStep": "0.001", "minNotionalValue": "5",
        },
        "priceFilter": {"tickSize": "0.10"},
    }
    instance.get_order_book.return_value = OrderBook(
        symbol="BTCUSDT", bids=[(80000.0, 1.5)], asks=[(80010.0, 1.2)],
    )
    instance.get_ticker.return_value = Ticker(
        symbol="BTCUSDT", last_price=80005.0,
        bid=80000.0, ask=80010.0, volume_24h=1234.5,
    )
    instance.get_balance.return_value = {
        "list": [{"coin": [{
            "coin": "USDT",
            "walletBalance": "10000",
            "availableToWithdraw": "9800",
        }]}],
    }
    instance.get_positions.return_value = [
        {"symbol": "BTCUSDT", "size": "0", "leverage": "1"},
    ]
    instance.get_open_orders.return_value = []

    import crypto_trading_bot.exchange.bybit_client as bc_mod
    monkeypatch.setattr(bc_mod, "BybitClient", MagicMock(return_value=instance))
    return instance


class TestPrepareDemoOrderPreflight:

    def test_prepare_blocks_in_paper_mode(self, monkeypatch):
        _setup_paper_env(monkeypatch)
        client = _patch_bybit_client_for_preflight(monkeypatch)
        mod = _load_script_module()
        rc = mod.main(["--prepare-demo-order"])
        assert rc == 1
        # Aborta no ModeGuard ANTES de qualquer chamada read-only
        client.get_instruments_info.assert_not_called()

    def test_prepare_blocks_when_endpoint_not_api_demo(self, monkeypatch):
        # demo OFF + testnet ON
        _setup_demo_env(monkeypatch, use_demo=False)
        monkeypatch.setenv("BYBIT_USE_TESTNET", "true")
        client = _patch_bybit_client_for_preflight(monkeypatch)
        mod = _load_script_module()
        rc = mod.main(["--prepare-demo-order"])
        assert rc == 1
        client.get_instruments_info.assert_not_called()

    def test_prepare_blocks_without_credentials(self, monkeypatch):
        _setup_demo_env(monkeypatch, api_key="", api_secret="")
        client = _patch_bybit_client_for_preflight(monkeypatch)
        mod = _load_script_module()
        rc = mod.main(["--prepare-demo-order"])
        assert rc == 1
        client.get_instruments_info.assert_not_called()

    def test_prepare_calls_only_readonly_endpoints(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        client = _patch_bybit_client_for_preflight(monkeypatch)
        mod = _load_script_module()
        rc = mod.main(["--prepare-demo-order"])
        assert rc == 0
        # Read-only chamados
        client.get_instruments_info.assert_called()
        client.get_order_book.assert_called()
        client.get_balance.assert_called()
        client.get_positions.assert_called()
        client.get_open_orders.assert_called()
        # NÃO chamou place/cancel
        client.place_market_order.assert_not_called()
        client.cancel_order.assert_not_called()
        client.get_order_status.assert_not_called()

    def test_prepare_outputs_final_command_when_ok(self, monkeypatch, capsys):
        _setup_demo_env(monkeypatch)
        _patch_bybit_client_for_preflight(monkeypatch)
        mod = _load_script_module()
        rc = mod.main(["--prepare-demo-order"])
        assert rc == 0
        out = capsys.readouterr().out
        # Comando final sugerido aparece
        assert "--execute-demo-order" in out
        assert "--symbol BTCUSDT" in out
        assert "--side buy" in out
        assert "--leverage 1.0" in out

    def test_prepare_aborts_when_position_open(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        client = _patch_bybit_client_for_preflight(monkeypatch)
        client.get_positions.return_value = [
            {"symbol": "BTCUSDT", "size": "0.005", "leverage": "1"}
        ]
        mod = _load_script_module()
        rc = mod.main(["--prepare-demo-order"])
        assert rc == 1

    def test_prepare_aborts_when_leverage_not_target(self, monkeypatch):
        _setup_demo_env(monkeypatch)
        client = _patch_bybit_client_for_preflight(monkeypatch)
        client.get_positions.return_value = [
            {"symbol": "BTCUSDT", "size": "0", "leverage": "3"}
        ]
        mod = _load_script_module()
        rc = mod.main(["--prepare-demo-order"])
        assert rc == 1

    def test_prepare_does_not_leak_secrets(self, monkeypatch, capsys):
        from loguru import logger as loguru_logger
        _setup_demo_env(monkeypatch)
        _patch_bybit_client_for_preflight(monkeypatch)
        mod = _load_script_module()
        buf = io.StringIO()
        sink_id = loguru_logger.add(buf, level="DEBUG")
        try:
            mod.main(["--prepare-demo-order"])
        finally:
            loguru_logger.remove(sink_id)
        out = capsys.readouterr().out
        log = buf.getvalue()
        assert _FAKE_KEY_MARKER not in out
        assert _FAKE_KEY_MARKER not in log
        assert _FAKE_SECRET_MARKER not in out
        assert _FAKE_SECRET_MARKER not in log


# ===========================================================================
# Cenário: redaction de logs — secret NUNCA aparece em logs/output
# ===========================================================================

class TestNoSecretLeak:

    def test_log_stream_does_not_leak_credentials(self, monkeypatch, capsys):
        """
        Captura stdout (print) + loguru. Garante que valores reais de key/secret
        nunca aparecem.
        """
        from loguru import logger as loguru_logger

        _setup_demo_env(monkeypatch)
        client_mock = _patch_bybit_client(monkeypatch)
        mod = _load_script_module()

        buf = io.StringIO()
        sink_id = loguru_logger.add(buf, level="DEBUG")
        try:
            mod.main(["--safe-check", "--confirm-demo-execution"])
        finally:
            loguru_logger.remove(sink_id)

        log_captured = buf.getvalue()
        stdout_captured = capsys.readouterr().out

        for marker in (_FAKE_KEY_MARKER, _FAKE_SECRET_MARKER):
            assert marker not in log_captured, f"leaked in loguru: {marker}"
            assert marker not in stdout_captured, f"leaked in stdout: {marker}"

    def test_failure_message_is_sanitized(self, monkeypatch, capsys):
        """
        FASE 9 Fatias 4A+4B: defesa em camadas — o executor sanitiza a mensagem
        de erro (usa apenas type(e).__name__ em reason, nunca str(e)). Portanto
        nem o marker da key NEM o conteúdo sensível chegam ao stdout. Não há
        ***REDACTED*** porque não há nada sensível a redacionar — o que é a
        melhor defesa possível.
        """
        from loguru import logger as loguru_logger

        _setup_demo_env(monkeypatch)
        # Simula erro contendo padrão sensível
        bad_error_message = (
            f"Bybit auth failed: api_key={_FAKE_KEY_MARKER} "
            f"X-BAPI-SIGN: sig_value Authorization: Bearer xxx"
        )
        _patch_bybit_client(
            monkeypatch, raise_exception=RuntimeError(bad_error_message)
        )
        mod = _load_script_module()

        buf = io.StringIO()
        sink_id = loguru_logger.add(buf, level="DEBUG")
        try:
            rc = mod.main(["--safe-check", "--confirm-demo-execution"])
        finally:
            loguru_logger.remove(sink_id)

        assert rc == 1
        stdout_captured = capsys.readouterr().out
        log_captured = buf.getvalue()
        # Marker NUNCA aparece em stdout nem no log capturado
        assert _FAKE_KEY_MARKER not in stdout_captured
        assert _FAKE_KEY_MARKER not in log_captured
        # Tipo da exceção (seguro) DEVE aparecer para auditoria
        assert "RuntimeError" in stdout_captured
