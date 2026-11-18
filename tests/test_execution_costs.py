"""
Testes do módulo ExecutionCostConfig — Funções puras de custos
================================================================
⚠️  ZERO chamadas à internet.
⚠️  ZERO API keys.
⚠️  ZERO ordens reais.

FASE 3E.1 — Cobertura unitária:
    - ExecutionCostConfig: defaults, validação, is_zero, active_fee_pct
    - apply_entry_costs: BUY/SELL com slippage, spread, fixed price, fees
    - apply_exit_costs: BUY/SELL com slippage, spread, fixed price, fees
    - Slippage e spread sempre pioram a execução
    - Direção adversa em cada combinação (side × leg)
    - Custo zero produz preço executado == preço teórico
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.backtesting.execution_costs import (
    ExecutionCostConfig,
    ExecutionResult,
    apply_entry_costs,
    apply_exit_costs,
)


# ---------------------------------------------------------------------------
# ExecutionCostConfig — defaults e validação
# ---------------------------------------------------------------------------

class TestExecutionCostConfigDefaults:

    def test_default_is_all_zero(self):
        cfg = ExecutionCostConfig()
        assert cfg.taker_fee_pct == 0.0
        assert cfg.maker_fee_pct == 0.0
        assert cfg.slippage_pct == 0.0
        assert cfg.slippage_fixed_price_usd == 0.0
        assert cfg.spread_pct == 0.0
        assert cfg.spread_fixed_price_usd == 0.0
        assert cfg.fee_side == "taker"

    def test_default_is_zero_property_true(self):
        cfg = ExecutionCostConfig()
        assert cfg.is_zero is True

    def test_is_zero_false_when_any_cost_nonzero(self):
        assert ExecutionCostConfig(taker_fee_pct=0.0001).is_zero is False
        assert ExecutionCostConfig(slippage_pct=0.0001).is_zero is False
        assert ExecutionCostConfig(spread_pct=0.0001).is_zero is False
        assert ExecutionCostConfig(slippage_fixed_price_usd=0.01).is_zero is False
        assert ExecutionCostConfig(spread_fixed_price_usd=0.01).is_zero is False
        assert ExecutionCostConfig(maker_fee_pct=0.0001).is_zero is False

    def test_active_fee_pct_uses_taker_by_default(self):
        cfg = ExecutionCostConfig(taker_fee_pct=0.0006, maker_fee_pct=0.0002)
        assert cfg.active_fee_pct == 0.0006

    def test_active_fee_pct_uses_maker_when_configured(self):
        cfg = ExecutionCostConfig(
            taker_fee_pct=0.0006, maker_fee_pct=0.0002, fee_side="maker"
        )
        assert cfg.active_fee_pct == 0.0002


class TestExecutionCostConfigValidation:

    @pytest.mark.parametrize("field", [
        "taker_fee_pct",
        "maker_fee_pct",
        "slippage_pct",
        "slippage_fixed_price_usd",
        "spread_pct",
        "spread_fixed_price_usd",
    ])
    def test_negative_cost_raises(self, field):
        with pytest.raises(ValueError, match=field):
            ExecutionCostConfig(**{field: -0.001})

    def test_invalid_fee_side_raises(self):
        with pytest.raises(ValueError, match="fee_side"):
            ExecutionCostConfig(fee_side="invalid")  # type: ignore[arg-type]

    def test_is_frozen(self):
        """Dataclass deve ser imutável (frozen=True)."""
        cfg = ExecutionCostConfig()
        with pytest.raises((AttributeError, Exception)):
            cfg.taker_fee_pct = 0.001  # type: ignore[misc]


# ---------------------------------------------------------------------------
# apply_entry_costs — zero
# ---------------------------------------------------------------------------

class TestApplyEntryCostsZero:

    def test_zero_config_preserves_price(self):
        cfg = ExecutionCostConfig()
        result = apply_entry_costs("buy", 65000.0, 200.0, cfg)
        assert result.price_executed == 65000.0
        assert result.price_theoretical == 65000.0
        assert result.fee_usd == 0.0
        assert result.slippage_cost_usd == 0.0

    def test_zero_config_returns_execution_result(self):
        cfg = ExecutionCostConfig()
        result = apply_entry_costs("sell", 65000.0, 200.0, cfg)
        assert isinstance(result, ExecutionResult)


# ---------------------------------------------------------------------------
# apply_entry_costs — fees
# ---------------------------------------------------------------------------

class TestApplyEntryCostsFees:

    def test_taker_fee_applied_on_notional(self):
        cfg = ExecutionCostConfig(taker_fee_pct=0.0006)
        result = apply_entry_costs("buy", 65000.0, 200.0, cfg)
        # fee = 200 * 0.0006 = 0.12
        assert result.fee_usd == pytest.approx(0.12, abs=1e-9)

    def test_maker_fee_applied_when_fee_side_maker(self):
        cfg = ExecutionCostConfig(
            taker_fee_pct=0.0006, maker_fee_pct=0.0002, fee_side="maker"
        )
        result = apply_entry_costs("buy", 65000.0, 1000.0, cfg)
        # fee = 1000 * 0.0002 = 0.20
        assert result.fee_usd == pytest.approx(0.20, abs=1e-9)


# ---------------------------------------------------------------------------
# Direção adversa: slippage SEMPRE piora a execução
# ---------------------------------------------------------------------------

class TestSlippageAdverseDirection:

    def test_buy_entry_slippage_increases_price(self):
        cfg = ExecutionCostConfig(slippage_pct=0.001)
        result = apply_entry_costs("buy", 65000.0, 200.0, cfg)
        assert result.price_executed > 65000.0
        # Esperado: 65000 * (1 + 0.001) = 65065
        assert result.price_executed == pytest.approx(65065.0, abs=1e-6)

    def test_sell_entry_slippage_decreases_price(self):
        cfg = ExecutionCostConfig(slippage_pct=0.001)
        result = apply_entry_costs("sell", 65000.0, 200.0, cfg)
        assert result.price_executed < 65000.0
        # Esperado: 65000 * (1 - 0.001) = 64935
        assert result.price_executed == pytest.approx(64935.0, abs=1e-6)

    def test_buy_exit_slippage_decreases_price(self):
        cfg = ExecutionCostConfig(slippage_pct=0.001)
        result = apply_exit_costs("buy", 65000.0, 200.0, cfg)
        assert result.price_executed < 65000.0
        assert result.price_executed == pytest.approx(64935.0, abs=1e-6)

    def test_sell_exit_slippage_increases_price(self):
        cfg = ExecutionCostConfig(slippage_pct=0.001)
        result = apply_exit_costs("sell", 65000.0, 200.0, cfg)
        assert result.price_executed > 65000.0
        assert result.price_executed == pytest.approx(65065.0, abs=1e-6)


# ---------------------------------------------------------------------------
# Spread: pioram a execução em ambos os lados
# ---------------------------------------------------------------------------

class TestSpreadAdverseDirection:

    def test_buy_entry_spread_increases_price(self):
        cfg = ExecutionCostConfig(spread_pct=0.0004)
        result = apply_entry_costs("buy", 65000.0, 200.0, cfg)
        # 65000 * 1.0004 = 65026
        assert result.price_executed == pytest.approx(65026.0, abs=1e-6)

    def test_sell_exit_spread_increases_price(self):
        cfg = ExecutionCostConfig(spread_pct=0.0004)
        result = apply_exit_costs("sell", 65000.0, 200.0, cfg)
        assert result.price_executed == pytest.approx(65026.0, abs=1e-6)

    def test_slippage_and_spread_combine(self):
        """Slippage e spread se somam no preço executado."""
        cfg = ExecutionCostConfig(slippage_pct=0.0005, spread_pct=0.0002)
        result = apply_entry_costs("buy", 65000.0, 200.0, cfg)
        # 65000 * (1 + 0.0007) = 65045.5
        assert result.price_executed == pytest.approx(65045.5, abs=1e-6)


# ---------------------------------------------------------------------------
# Slippage/spread FIXOS no preço (USD por unidade do preço do ativo)
# ---------------------------------------------------------------------------

class TestFixedPriceAdjustment:

    def test_slippage_fixed_price_increases_buy_entry(self):
        cfg = ExecutionCostConfig(slippage_fixed_price_usd=5.0)
        result = apply_entry_costs("buy", 65000.0, 200.0, cfg)
        assert result.price_executed == pytest.approx(65005.0, abs=1e-6)

    def test_slippage_fixed_price_decreases_buy_exit(self):
        cfg = ExecutionCostConfig(slippage_fixed_price_usd=5.0)
        result = apply_exit_costs("buy", 65000.0, 200.0, cfg)
        assert result.price_executed == pytest.approx(64995.0, abs=1e-6)

    def test_fixed_and_pct_combine(self):
        cfg = ExecutionCostConfig(
            slippage_pct=0.001, slippage_fixed_price_usd=5.0
        )
        result = apply_entry_costs("buy", 65000.0, 200.0, cfg)
        # 65000 * 1.001 + 5 = 65070
        assert result.price_executed == pytest.approx(65070.0, abs=1e-6)


# ---------------------------------------------------------------------------
# slippage_cost_usd: relação com o notional
# ---------------------------------------------------------------------------

class TestSlippageCostUsd:

    def test_slippage_cost_zero_when_config_zero(self):
        cfg = ExecutionCostConfig()
        result = apply_entry_costs("buy", 65000.0, 200.0, cfg)
        assert result.slippage_cost_usd == 0.0

    def test_slippage_cost_proportional_to_pct_and_size(self):
        cfg = ExecutionCostConfig(slippage_pct=0.001)
        result = apply_entry_costs("buy", 65000.0, 200.0, cfg)
        # 65 USD de drift / 65000 * 200 = 0.20 USD
        assert result.slippage_cost_usd == pytest.approx(0.20, abs=1e-6)

    def test_slippage_cost_always_nonneg(self):
        """Slippage cost é sempre o módulo do drift × notional/preço — nunca negativo."""
        cfg = ExecutionCostConfig(slippage_pct=0.001)
        for side in ("buy", "sell"):
            for leg_fn in (apply_entry_costs, apply_exit_costs):
                result = leg_fn(side, 65000.0, 200.0, cfg)
                assert result.slippage_cost_usd >= 0.0


# ---------------------------------------------------------------------------
# Validação de entrada das funções puras
# ---------------------------------------------------------------------------

class TestApplyCostsInputValidation:

    def test_apply_entry_negative_price_raises(self):
        with pytest.raises(ValueError, match="price_theoretical"):
            apply_entry_costs("buy", -1.0, 200.0, ExecutionCostConfig())

    def test_apply_entry_zero_price_raises(self):
        with pytest.raises(ValueError, match="price_theoretical"):
            apply_entry_costs("buy", 0.0, 200.0, ExecutionCostConfig())

    def test_apply_entry_negative_size_raises(self):
        with pytest.raises(ValueError, match="position_size_usd"):
            apply_entry_costs("buy", 65000.0, -1.0, ExecutionCostConfig())

    def test_apply_entry_invalid_side_raises(self):
        with pytest.raises(ValueError, match="side"):
            apply_entry_costs("long", 65000.0, 200.0, ExecutionCostConfig())

    def test_apply_exit_invalid_side_raises(self):
        with pytest.raises(ValueError, match="side"):
            apply_exit_costs("short", 65000.0, 200.0, ExecutionCostConfig())
