"""
FASE 47 — effective_config: RiskConfig efetivo a partir dos operator inputs.
100% OFFLINE. Travas: max_risk_per_trade=0,5% SOBERANO (nunca 3%); 3%/150 so
teto externo reportado; sizing dinamico por risco respeita leverage 1x +
min_stop; controles internos registrados (overlay/not_supported). Piso 0.005
inalterado. Sem rede/ordem/secret.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import pytest

from crypto_trading_bot.research.effective_config import (
    HYROTRADER_EXTERNAL,
    build_effective_config,
    dynamic_position_size,
)


@dataclass
class _Val:
    value: Any


class _FakeStore:
    """Imita OperatorInputStore.get -> objeto com .value (ou None)."""

    def __init__(self, mapping: dict):
        self._m = mapping

    def get(self, input_id: str) -> Optional[_Val]:
        if input_id in self._m:
            return _Val(self._m[input_id])
        return None


# --------------------------- sem store (fase47_spec) ----------------------

class TestSpecFallback:

    def test_risk_sovereign_is_half_pct_not_three(self):
        ec = build_effective_config(store=None)
        assert ec.risk_config.max_risk_per_trade_pct == pytest.approx(0.005)
        # 3% NUNCA vira o valor do RiskConfig
        assert ec.risk_config.max_risk_per_trade_pct != 0.03
        # 3% aparece SO como teto externo reportado
        assert ec.external_ceilings["max_risk_per_trade_pct"] == 0.03
        assert HYROTRADER_EXTERNAL["max_risk_per_trade_pct"] == 0.03

    def test_core_fields_from_spec(self):
        ec = build_effective_config(store=None)
        rc = ec.risk_config
        assert rc.account_size_usd == pytest.approx(5000.0)
        assert rc.max_daily_loss_pct == pytest.approx(0.04)
        assert rc.max_total_loss_pct == pytest.approx(0.06)
        assert rc.max_leverage == pytest.approx(1.0)
        assert rc.max_open_positions == 1
        assert rc.min_stop_loss_pct == pytest.approx(0.005)  # piso intacto
        # leverage 1x => notional ate o capital (nao default 10%/20%)
        assert rc.max_position_size_pct == pytest.approx(1.0)
        assert rc.max_exposure_per_asset_pct == pytest.approx(1.0)

    def test_internal_controls_and_not_supported_registered(self):
        ec = build_effective_config(store=None)
        ic = ec.internal_controls
        assert ic["consecutive_losses"]["value"] == 2
        assert ic["cooldown_minutes"]["value"] == 15
        assert ic["kill_switch_usd"]["value"] == 50.0
        assert ic["session_loss_pct"]["value"] == pytest.approx(0.01)
        # regras nao suportadas pelo RiskEngine listadas explicitamente
        joined = " ".join(ec.not_supported_by_riskengine)
        assert "trailing" in joined and "concentration" in joined
        assert "min_5_days" in joined and "kill_switch" in joined

    def test_origins_marked_fase47_spec(self):
        ec = build_effective_config(store=None)
        assert ec.applied["max_risk_per_trade_pct"]["origin"] == "fase47_spec"


# --------------------------- com operator inputs --------------------------

class TestOperatorInputs:

    def test_reads_operator_inputs_with_origin(self):
        store = _FakeStore({
            "session_capital_usd": 5000,
            "max_risk_per_trade_pct": 0.5,     # 0,5%
            "max_daily_loss_pct": 4,           # 4%
            "max_total_loss_pct": 6,
            "max_drawdown_pct": 6,
            "max_leverage": 1,
            "max_open_positions": 1,
            "max_consecutive_losses": 2,
            "cooldown_after_loss_minutes": 15,
            "kill_switch_loss_limit_usd": 50,
            "max_session_loss_pct": 1,
        })
        ec = build_effective_config(store=store)
        assert ec.risk_config.max_risk_per_trade_pct == pytest.approx(0.005)
        assert ec.risk_config.max_daily_loss_pct == pytest.approx(0.04)
        assert ec.applied["max_risk_per_trade_pct"]["origin"] == \
            "operator_input"
        assert ec.applied["max_daily_loss_pct"]["origin"] == "operator_input"
        assert ec.internal_controls["session_loss_pct"]["origin"] == \
            "operator_input"

    def test_capital_override(self):
        ec = build_effective_config(store=None, capital_override=10000.0)
        assert ec.risk_config.account_size_usd == pytest.approx(10000.0)
        assert ec.applied["account_size_usd"]["origin"] == "override"


# --------------------------- sizing dinamico ------------------------------

class TestDynamicSizing:

    def test_risk_base_binding_normal_stop(self):
        # stop 1% => notional = 25 / 0.01 = 2500; risco = 25 (0,5%)
        s = dynamic_position_size(capital=5000.0, stop_dist_pct=0.01)
        assert s["position_size_usd"] == pytest.approx(2500.0)
        assert s["risk_usd"] == pytest.approx(25.0)
        assert s["binding"] == "risk_base"

    def test_exposure_cap_for_tiny_stop(self):
        # stop 0,5% (piso) => raw notional = 25/0.005 = 5000 = capital;
        # ainda dentro do cap (leverage 1x). stop menor => piso aplica.
        s = dynamic_position_size(capital=5000.0, stop_dist_pct=0.002)
        assert s["stop_dist_pct"] == pytest.approx(0.005)  # piso
        assert s["position_size_usd"] <= 5000.0            # cap leverage 1x

    def test_notional_never_exceeds_capital_at_1x(self):
        # stop minusculo => piso 0.005 aplica; com risco_base 0,5% o notional
        # maximo = 25/0.005 = 5000 = capital (invariante a leverage 1x).
        s = dynamic_position_size(capital=5000.0, stop_dist_pct=0.0001,
                                  max_notional_pct=1.0)
        assert s["position_size_usd"] <= 5000.0 + 1e-6
        assert s["stop_dist_pct"] == pytest.approx(0.005)

    def test_exposure_cap_binds_when_risk_base_higher(self):
        # com risco_base 3% (so p/ exercitar o cap), notional bruto
        # 150/0.005=30000 > capital => cap em 5000 (leverage 1x).
        s = dynamic_position_size(capital=5000.0, stop_dist_pct=0.002,
                                  risk_base_pct=0.03, max_notional_pct=1.0)
        assert s["position_size_usd"] == pytest.approx(5000.0)
        assert s["binding"] == "exposure_cap_leverage_1x"

    def test_hyro_notional_cap_modeled_separately(self):
        # P4: teto de NOTIONAL HyroTrader (separado do risco). stop 1% =>
        # notional 2500; com teto de notional 1000 => limita em 1000.
        s = dynamic_position_size(capital=5000.0, stop_dist_pct=0.01,
                                  hyro_max_notional_usd=1000.0)
        assert s["position_size_usd"] == pytest.approx(1000.0)
        assert s["binding"] == "hyro_max_notional_cap"

    def test_no_hyro_notional_cap_by_default(self):
        # sem teto de notional (regras atuais) => so risco/leverage limitam
        s = dynamic_position_size(capital=5000.0, stop_dist_pct=0.01)
        assert s["position_size_usd"] == pytest.approx(2500.0)
        assert s["binding"] == "risk_base"

    def test_sizing_policy_exposes_separate_notional_field(self):
        ec = build_effective_config(store=None)
        caps = ec.sizing_policy["caps"]
        assert "hyro_max_notional_usd" in caps          # separado do risco
        assert caps["hyro_max_notional_usd"] is None     # nao fornecido
        assert caps["notional_bound_source"] == "leverage_1x_only"

    def test_risk_never_above_half_pct_for_normal_stops(self):
        # com risco_base 0,5%, o risco fica em 25 enquanto o cap nao morde
        for stop in (0.008, 0.01, 0.02, 0.05):
            s = dynamic_position_size(capital=5000.0, stop_dist_pct=stop)
            assert s["risk_usd"] <= 25.0 + 1e-6
