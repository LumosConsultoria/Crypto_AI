"""
BybitDemoExecutor — Qty Normalization Hardening (FASE 14 microfase)
=====================================================================
⚠️  100% offline. ZERO secrets. ZERO rede. ZERO ordens.

Cobertura:
    - normalize_qty_to_step() resolve o bug 71.518350 / 71518.35 →
      0.0009999999999999998 → enviado como 0.001 ao step.
    - Múltiplos exatos do step são preservados.
    - qty_raw abaixo do step retorna 0 (executor recusa).
    - Float repr quebrado (0.0009999999999999998) → Decimal('0.001').
    - BybitDemoExecutor envia qty normalizado ao step (0.001 BTCUSDT).
    - qty_step inválido (<= 0) rejeitado no construtor.
    - dry_run não chama place_market_order.
    - Nenhum teste chama internet; nenhum usa API key real.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from crypto_trading_bot.execution.bybit_demo_executor import (
    BybitDemoExecutor,
    normalize_qty_to_step,
)

from tests.test_bybit_demo_executor import (
    _approved,
    _make_demo_mock_client,
    _make_executor,
    _make_signal,
    _settings_demo_ready,
)


# ---------------------------------------------------------------------------
# normalize_qty_to_step — helper puro
# ---------------------------------------------------------------------------

class TestNormalizeQtyToStep:

    def test_float_precision_bug_71518_case(self):
        """O caso real que rejeitou a Demo v2 com retCode=10001."""
        # 71.518350 / 71518.35 em float = 0.0009999999999999998
        qty_raw = 71.518350 / 71518.35
        result = normalize_qty_to_step(qty_raw, Decimal("0.001"))
        assert result == Decimal("0.001"), (
            f"Esperado Decimal('0.001'), obtido {result!r} (qty_raw={qty_raw!r})"
        )

    def test_exact_multiple_preserved(self):
        result = normalize_qty_to_step(Decimal("0.005"), Decimal("0.001"))
        assert result == Decimal("0.005")

    def test_string_input_accepted(self):
        result = normalize_qty_to_step("0.0029999", Decimal("0.001"))
        # 0.0029999 / 0.001 = 2.9999 → ROUND_DOWN → 2 → * 0.001 → 0.002
        assert result == Decimal("0.002")

    def test_round_down_conservative(self):
        # 0.00307692... ROUND_DOWN ao step 0.001 → 0.003
        result = normalize_qty_to_step(200.0 / 65000.0, Decimal("0.001"))
        assert result == Decimal("0.003")

    def test_below_step_returns_zero(self):
        result = normalize_qty_to_step(0.0005, Decimal("0.001"))
        assert result == Decimal("0")

    def test_zero_qty_returns_zero(self):
        result = normalize_qty_to_step(0.0, Decimal("0.001"))
        assert result == Decimal("0")

    def test_negative_qty_returns_zero(self):
        result = normalize_qty_to_step(-1.0, Decimal("0.001"))
        assert result == Decimal("0")

    def test_step_zero_raises(self):
        with pytest.raises(ValueError, match="qty_step"):
            normalize_qty_to_step(0.001, Decimal("0"))

    def test_step_negative_raises(self):
        with pytest.raises(ValueError, match="qty_step"):
            normalize_qty_to_step(0.001, Decimal("-0.001"))

    def test_step_accepts_str_input(self):
        result = normalize_qty_to_step(0.005, "0.001")
        assert result == Decimal("0.005")

    def test_step_accepts_float_input(self):
        # Decimal(str(0.001)) preserva exatidão
        result = normalize_qty_to_step(0.005, 0.001)
        assert result == Decimal("0.005")

    def test_different_step_works(self):
        # qty_step 0.01 (algumas alts)
        result = normalize_qty_to_step(1.237, Decimal("0.01"))
        assert result == Decimal("1.23")

    def test_returns_decimal_type(self):
        result = normalize_qty_to_step(0.001, Decimal("0.001"))
        assert isinstance(result, Decimal)


# ---------------------------------------------------------------------------
# BybitDemoExecutor — usa o helper no place_market_order
# ---------------------------------------------------------------------------

class TestExecutorUsesNormalizedQty:

    def test_qty_normalized_to_step_in_place_order(self):
        """Cenário real que falhou: position=71.518350, entry=71518.35."""
        sig = _make_signal(
            position_size_usd=71.518350,
            entry_price=71518.35,
        )
        executor, client = _make_executor()
        r = executor.execute(_approved(sig), dry_run=False)
        # qty enviado ao client deve ser 0.001 — NÃO 0.0009999999999999998
        qty_sent = client.place_market_order.call_args.kwargs["qty"]
        assert qty_sent == pytest.approx(0.001), (
            f"qty enviado: {qty_sent!r} — deveria ser 0.001"
        )
        # Garantia adicional: a string que seria serializada não tem
        # representação float quebrada.
        assert "999999" not in repr(qty_sent)
        assert r.success is True  # mock por padrão retorna sucesso

    def test_qty_normalized_for_position_200_entry_65000(self):
        # 200/65000 = 0.00307692... → ROUND_DOWN ao step 0.001 → 0.003
        sig = _make_signal(position_size_usd=200.0, entry_price=65000.0)
        executor, client = _make_executor()
        executor.execute(_approved(sig), dry_run=False)
        qty_sent = client.place_market_order.call_args.kwargs["qty"]
        assert qty_sent == pytest.approx(0.003)

    def test_qty_below_step_aborts_without_calling_place_order(self):
        # position 0.5 / entry 65000 = 0.0000076 → < step 0.001 → 0 → abort
        sig = _make_signal(position_size_usd=0.5, entry_price=65000.0)
        executor, client = _make_executor()
        r = executor.execute(_approved(sig), dry_run=False)
        assert r.success is False
        assert "qty normalizado é 0" in r.reason
        client.place_market_order.assert_not_called()

    def test_custom_qty_step_step01_aborts_when_qty_below_step(self):
        """qty_step=0.01 com qty_raw=0.00307 → abort (qty < step)."""
        from crypto_trading_bot.core.mode_guard import ModeGuard
        from crypto_trading_bot.risk.risk_engine import RiskEngine
        client = _make_demo_mock_client()
        executor = BybitDemoExecutor(
            client=client,
            mode_guard=ModeGuard(settings=_settings_demo_ready()),
            risk_engine=RiskEngine(initial_capital=5000.0),
            confirm_demo_execution=True,
            reconciliation_attempts=2,
            reconciliation_delay_seconds=0.0,
            qty_step=Decimal("0.01"),  # step maior que qty_raw
        )
        sig = _make_signal(position_size_usd=200.0, entry_price=65000.0)
        r = executor.execute(_approved(sig), dry_run=False)
        # 200/65000 = 0.00307... < step 0.01 → abort sem chamar place_order
        assert r.success is False
        assert "qty normalizado é 0" in r.reason
        client.place_market_order.assert_not_called()

    def test_custom_qty_step_step001_normalizes(self):
        from crypto_trading_bot.core.mode_guard import ModeGuard
        from crypto_trading_bot.risk.risk_engine import RiskEngine
        client = _make_demo_mock_client()
        executor = BybitDemoExecutor(
            client=client,
            mode_guard=ModeGuard(settings=_settings_demo_ready()),
            risk_engine=RiskEngine(initial_capital=5000.0),
            confirm_demo_execution=True,
            reconciliation_attempts=2,
            reconciliation_delay_seconds=0.0,
            qty_step=Decimal("0.01"),
        )
        # Position grande o suficiente para qty > step
        sig = _make_signal(position_size_usd=1000.0, entry_price=65000.0)
        executor.execute(_approved(sig), dry_run=False)
        qty_sent = client.place_market_order.call_args.kwargs["qty"]
        # 1000/65000 = 0.01538... → step 0.01 ROUND_DOWN → 0.01
        assert qty_sent == pytest.approx(0.01)


# ---------------------------------------------------------------------------
# Construtor: qty_step inválido
# ---------------------------------------------------------------------------

class TestConstructorRejectsInvalidStep:

    def test_step_zero_raises(self):
        from crypto_trading_bot.core.mode_guard import ModeGuard
        from crypto_trading_bot.risk.risk_engine import RiskEngine
        with pytest.raises(ValueError, match="qty_step"):
            BybitDemoExecutor(
                client=_make_demo_mock_client(),
                mode_guard=ModeGuard(settings=_settings_demo_ready()),
                risk_engine=RiskEngine(initial_capital=5000.0),
                qty_step=Decimal("0"),
            )

    def test_step_negative_raises(self):
        from crypto_trading_bot.core.mode_guard import ModeGuard
        from crypto_trading_bot.risk.risk_engine import RiskEngine
        with pytest.raises(ValueError, match="qty_step"):
            BybitDemoExecutor(
                client=_make_demo_mock_client(),
                mode_guard=ModeGuard(settings=_settings_demo_ready()),
                risk_engine=RiskEngine(initial_capital=5000.0),
                qty_step="-0.001",
            )

    def test_step_string_accepted(self):
        from crypto_trading_bot.core.mode_guard import ModeGuard
        from crypto_trading_bot.risk.risk_engine import RiskEngine
        # Não deve levantar
        BybitDemoExecutor(
            client=_make_demo_mock_client(),
            mode_guard=ModeGuard(settings=_settings_demo_ready()),
            risk_engine=RiskEngine(initial_capital=5000.0),
            qty_step="0.001",
        )

    def test_default_step_is_0001(self):
        executor, _ = _make_executor()
        assert executor._qty_step == Decimal("0.001")


# ---------------------------------------------------------------------------
# Dry-run NÃO chama place_market_order (preservado)
# ---------------------------------------------------------------------------

class TestDryRunStillBypassesPlaceOrder:

    def test_dry_run_no_place_market_order_call(self):
        executor, client = _make_executor()
        sig = _make_signal(position_size_usd=71.518350, entry_price=71518.35)
        r = executor.execute(_approved(sig), dry_run=True)
        assert r.dry_run is True
        client.place_market_order.assert_not_called()


# ---------------------------------------------------------------------------
# Isolamento estrutural — nenhum import novo de rede
# ---------------------------------------------------------------------------

class TestStructuralIsolation:

    def test_no_httpx_in_executor(self):
        import crypto_trading_bot.execution.bybit_demo_executor as mod
        src = open(mod.__file__, "r", encoding="utf-8").read()
        assert "import httpx" not in src.split("\n")
        assert "from httpx" not in src

    def test_decimal_imported_correctly(self):
        import crypto_trading_bot.execution.bybit_demo_executor as mod
        src = open(mod.__file__, "r", encoding="utf-8").read()
        assert "from decimal import" in src

    def test_no_api_key_or_secret_in_normalized_qty_path(self):
        """Garante que o helper de normalização não toca em credentials."""
        from crypto_trading_bot.execution.bybit_demo_executor import (
            normalize_qty_to_step,
        )
        # Helper é puro: só números entram/saem
        import inspect
        src = inspect.getsource(normalize_qty_to_step)
        forbidden = ("api_key", "api_secret", "X-BAPI", "Bearer",
                     "authorization", ".env", "Settings")
        for tok in forbidden:
            assert tok.lower() not in src.lower(), (
                f"Helper deve ser puro; menciona {tok}"
            )
