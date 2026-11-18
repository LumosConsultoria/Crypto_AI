"""
Effective Risk Config (FASE 47) — config soberana a partir dos operator inputs
================================================================================
Constroi um **RiskConfig EFETIVO** a partir dos operator inputs (perfil
HyroTrader One-Step 5.000 USDT), em vez de usar os defaults do RiskConfig
silenciosamente. Registra, por campo, VALOR APLICADO + ORIGEM
(operator_input | hyrotrader_external | fase47_spec | derived | default) e os
ITENS NAO SUPORTADOS pelo RiskEngine (tratados no overlay hyrotrader_eval).

Pontos travados (revisao do operador, FASE 47):
- **max_risk_per_trade = 0,5% (US$25) e SOBERANO** no RiskConfig efetivo
  (o RiskEngine enforce 0,5%). O **3%/US$150 e SO teto externo HyroTrader**,
  reportado, NUNCA o valor do RiskConfig.
- **Sizing DINAMICO por risco**: notional = risco_base / stop_dist_pct,
  limitado por leverage 1x (notional <= capital), min_stop e o teto externo
  3%/150 (guarda — 0,5% ja e menor). Nao ha notional fixo em 150.
- leverage 1x; 1 posicao; piso min_stop 0.005 INTACTO.

NAO altera RiskEngine/ModeGuard/piso; apenas PARAMETRIZA o RiskConfig.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from crypto_trading_bot.config.risk_config import RiskConfig

# IDs dos operator inputs (FASE 36 schema; percentuais em numeros inteiros:
# max_risk_per_trade_pct=0.5 => 0,5%; max_daily_loss_pct=4 => 4%).
_OID = {
    "capital": "session_capital_usd",
    "risk_per_trade": "max_risk_per_trade_pct",
    "daily_loss": "max_daily_loss_pct",
    "session_loss": "max_session_loss_pct",
    "total_loss": "max_total_loss_pct",
    "drawdown": "max_drawdown_pct",
    "leverage": "max_leverage",
    "open_positions": "max_open_positions",
    "consecutive_losses": "max_consecutive_losses",
    "cooldown_minutes": "cooldown_after_loss_minutes",
    "kill_switch_usd": "kill_switch_loss_limit_usd",
}

# Valores-alvo declarados pelo operador (FASE 47) — usados como fallback
# DOCUMENTADO (origin=fase47_spec) quando o store nao informa o campo.
# NUNCA defaults silenciosos do RiskConfig.
FASE47_SPEC = {
    "capital": 5000.0,
    "risk_per_trade_pct": 0.005,          # 0,5% SOBERANO
    "daily_loss_pct": 0.04,               # 4% / 200 trailing
    "total_loss_pct": 0.06,               # 6% / 300 (eq min 4700)
    "leverage": 1.0,
    "open_positions": 1,
    "session_loss_pct": 0.01,             # 1% (controle interno)
    "consecutive_losses": 2,              # 2 perdas => cooldown
    "cooldown_minutes": 15,
    "kill_switch_usd": 50.0,
}

# Teto externo HyroTrader — REPORTADO, nunca o valor do RiskConfig efetivo.
HYROTRADER_EXTERNAL = {
    "max_risk_per_trade_pct": 0.03,       # 3% / US$150 (teto oficial)
    "profit_target_pct": 0.10,            # meta 10% / 500 (KPI)
    "daily_drawdown_pct": 0.04,           # 4% / 200 trailing intraday
    "total_loss_pct": 0.06,               # 6% / 300, equity min 4700
    "concentration_max_pct": 0.40,        # <=40% do lucro em 1 dia
    "min_days": 5,
    "mandatory_stop": True,
}


@dataclass(frozen=True)
class EffectiveConfig:
    """Config efetiva + proveniencia. `risk_config` e o RiskConfig soberano
    que o RiskEngine deve consumir na pesquisa (em vez dos defaults)."""
    risk_config: RiskConfig
    applied: Mapping[str, Any]            # campo -> {value, origin}
    external_ceilings: Mapping[str, Any]  # HyroTrader (reported-only)
    internal_controls: Mapping[str, Any]  # cooldown/sessao/kill-switch
    sizing_policy: Mapping[str, Any]
    not_supported_by_riskengine: List[str]

    def to_dict(self) -> dict:
        return {
            "schema": "effective_config_v1",
            "risk_config": {
                "account_size_usd": float(self.risk_config.account_size_usd),
                "max_risk_per_trade_pct":
                    float(self.risk_config.max_risk_per_trade_pct),
                "max_daily_loss_pct":
                    float(self.risk_config.max_daily_loss_pct),
                "max_total_loss_pct":
                    float(self.risk_config.max_total_loss_pct),
                "max_leverage": float(self.risk_config.max_leverage),
                "max_open_positions":
                    int(self.risk_config.max_open_positions),
                "max_position_size_pct":
                    float(self.risk_config.max_position_size_pct),
                "max_exposure_per_asset_pct":
                    float(self.risk_config.max_exposure_per_asset_pct),
                "min_stop_loss_pct":
                    float(self.risk_config.min_stop_loss_pct),
            },
            "applied": dict(self.applied),
            "external_ceilings_hyrotrader": dict(self.external_ceilings),
            "internal_controls": dict(self.internal_controls),
            "sizing_policy": dict(self.sizing_policy),
            "not_supported_by_riskengine":
                list(self.not_supported_by_riskengine),
            "note": (
                "RiskConfig efetivo SOBERANO = 0,5%/US$25; 3%/US$150 e SO "
                "teto externo HyroTrader (reportado). Controles internos "
                "(2 perdas=>cooldown 15min, perda sessao 1%, kill switch "
                "US$50) e regras HyroTrader trailing/concentracao/min-dias "
                "nao sao enforce do RiskEngine: simulados/reportados no "
                "hyrotrader_eval ou marcados not_supported."
            ),
        }


def _read_operator_inputs(store) -> Dict[str, Any]:
    """Le valores brutos do OperatorInputStore (ou {}). Nao inventa."""
    if store is None:
        return {}
    out: Dict[str, Any] = {}
    for key, oid in _OID.items():
        try:
            val = store.get(oid)
        except Exception:  # noqa: BLE001
            val = None
        if val is not None and val.value is not None:
            out[key] = val.value
    return out


def _pct_from_operator(value: Any) -> Optional[float]:
    """Operator inputs guardam percentuais como numeros inteiros
    (0.5 => 0,5%; 4 => 4%). Converte p/ fracao do RiskConfig."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value) / 100.0
    except (TypeError, ValueError):
        return None


def build_effective_config(
    *, store=None, capital_override: Optional[float] = None,
) -> EffectiveConfig:
    """Constroi o RiskConfig efetivo + proveniencia.

    Fonte por campo: operator input (se presente) > FASE47_SPEC
    (fallback DOCUMENTADO) — NUNCA defaults silenciosos do RiskConfig.
    """
    raw = _read_operator_inputs(store)
    applied: Dict[str, Any] = {}

    def _take_pct(key: str, spec_key: str, label: str) -> float:
        op = _pct_from_operator(raw.get(key))
        if op is not None:
            applied[label] = {"value": op, "origin": "operator_input"}
            return op
        v = FASE47_SPEC[spec_key]
        applied[label] = {"value": v, "origin": "fase47_spec"}
        return v

    # capital
    if capital_override is not None:
        capital = float(capital_override)
        applied["account_size_usd"] = {"value": capital,
                                       "origin": "override"}
    elif raw.get("capital") is not None:
        capital = float(raw["capital"])
        applied["account_size_usd"] = {"value": capital,
                                       "origin": "operator_input"}
    else:
        capital = FASE47_SPEC["capital"]
        applied["account_size_usd"] = {"value": capital,
                                       "origin": "fase47_spec"}

    # risco por trade SOBERANO = 0,5% (operator) — nunca 3%
    risk_pct = _take_pct("risk_per_trade", "risk_per_trade_pct",
                         "max_risk_per_trade_pct")
    daily_pct = _take_pct("daily_loss", "daily_loss_pct",
                          "max_daily_loss_pct")
    # total loss = max(total, drawdown) e >= daily (validator do RiskConfig)
    total_op = _pct_from_operator(raw.get("total_loss"))
    dd_op = _pct_from_operator(raw.get("drawdown"))
    if total_op is not None or dd_op is not None:
        total_pct = max(x for x in (total_op, dd_op) if x is not None)
        applied["max_total_loss_pct"] = {"value": total_pct,
                                         "origin": "operator_input"}
    else:
        total_pct = FASE47_SPEC["total_loss_pct"]
        applied["max_total_loss_pct"] = {"value": total_pct,
                                        "origin": "fase47_spec"}
    total_pct = max(total_pct, daily_pct)

    # leverage 1x
    lev_op = raw.get("leverage")
    if lev_op is not None and not isinstance(lev_op, bool):
        leverage = float(lev_op)
        applied["max_leverage"] = {"value": leverage,
                                   "origin": "operator_input"}
    else:
        leverage = FASE47_SPEC["leverage"]
        applied["max_leverage"] = {"value": leverage, "origin": "fase47_spec"}

    # posicoes simultaneas
    pos_op = raw.get("open_positions")
    if isinstance(pos_op, int) and not isinstance(pos_op, bool):
        open_positions = pos_op
        applied["max_open_positions"] = {"value": open_positions,
                                         "origin": "operator_input"}
    else:
        open_positions = FASE47_SPEC["open_positions"]
        applied["max_open_positions"] = {"value": open_positions,
                                         "origin": "fase47_spec"}

    # exposicao/position caps DERIVADOS de leverage 1x: notional <= capital.
    # (default 10%/20% do RiskConfig seria silencioso => NAO usar.)
    pos_cap_pct = min(1.0, leverage)            # 1x => 100% do capital
    applied["max_position_size_pct"] = {"value": pos_cap_pct,
                                        "origin": "derived(leverage_1x)"}
    applied["max_exposure_per_asset_pct"] = {"value": pos_cap_pct,
                                             "origin": "derived(leverage_1x)"}
    # piso intacto
    applied["min_stop_loss_pct"] = {"value": 0.005, "origin": "default(piso)"}

    rc = RiskConfig(
        account_profile_name="hyrotrader_5k_effective",
        provider_name="HyroTrader",
        provider_type="prop_challenge",
        is_prop_firm=True, is_challenge_account=True,
        account_size_usd=capital,
        max_risk_per_trade_pct=risk_pct,
        max_daily_loss_pct=daily_pct,
        max_total_loss_pct=total_pct,
        max_leverage=leverage,
        max_open_positions=int(open_positions),
        max_position_size_pct=pos_cap_pct,
        max_exposure_per_asset_pct=pos_cap_pct,
        min_stop_loss_pct=0.005,
        max_stop_loss_pct=0.05,
    )

    # controles internos (RiskEngine NAO suporta => overlay/registro)
    def _num(key, spec_key):
        v = raw.get(key)
        if v is not None and not isinstance(v, bool):
            return v, "operator_input"
        return FASE47_SPEC[spec_key], "fase47_spec"

    sess_loss = _pct_from_operator(raw.get("session_loss"))
    sess_origin = "operator_input"
    if sess_loss is None:
        sess_loss = FASE47_SPEC["session_loss_pct"]
        sess_origin = "fase47_spec"
    cons, cons_o = _num("consecutive_losses", "consecutive_losses")
    cd, cd_o = _num("cooldown_minutes", "cooldown_minutes")
    ks, ks_o = _num("kill_switch_usd", "kill_switch_usd")

    internal = {
        "session_loss_pct": {"value": sess_loss, "origin": sess_origin,
                             "enforced": "overlay"},
        "consecutive_losses": {"value": cons, "origin": cons_o,
                               "enforced": "overlay"},
        "cooldown_minutes": {"value": cd, "origin": cd_o,
                             "enforced": "overlay"},
        "kill_switch_usd": {"value": ks, "origin": ks_o,
                            "enforced": "overlay"},
    }

    risk_base_usd = round(risk_pct * capital, 2)
    sizing = {
        "mode": "dynamic_risk_based",
        "risk_base_pct": risk_pct,
        "risk_base_usd": risk_base_usd,
        "formula": "notional = risk_base_usd / stop_dist_pct",
        "caps": {
            "leverage": leverage,
            "max_notional_usd_from_leverage": round(pos_cap_pct * capital, 2),
            "external_risk_ceiling_pct":
                HYROTRADER_EXTERNAL["max_risk_per_trade_pct"],
            "external_risk_ceiling_usd": round(
                HYROTRADER_EXTERNAL["max_risk_per_trade_pct"] * capital, 2),
            "min_stop_loss_pct": 0.005,
            # P4: teto de NOTIONAL real da HyroTrader (separado do risco). Nas
            # regras fornecidas NAO ha teto de notional explicito alem da
            # leverage 1x (notional <= capital). Se a HyroTrader publicar um
            # cap de notional/lote, preencher aqui e o sizing o respeita.
            "hyro_max_notional_usd": None,
            "notional_bound_source": "leverage_1x_only",
        },
        "note": "notional dinamico por risco (notional=risco_base/stop_dist); "
                "150=US$ do teto de RISCO 3% (NAO de notional). Unico limite "
                "de notional = leverage 1x (<= capital). Teto de notional "
                "HyroTrader, se existir, e modelado SEPARADAMENTE em "
                "hyro_max_notional_usd.",
    }

    not_supported = [
        "daily_drawdown_trailing_intraday(incl_unrealized+fees+funding)",
        "concentration_max_40pct_per_day",
        "min_5_days",
        "consecutive_losses_cooldown",
        "session_loss_limit",
        "kill_switch_usd",
    ]

    return EffectiveConfig(
        risk_config=rc, applied=applied,
        external_ceilings=dict(HYROTRADER_EXTERNAL),
        internal_controls=internal, sizing_policy=sizing,
        not_supported_by_riskengine=not_supported,
    )


def dynamic_position_size(
    *, capital: float, stop_dist_pct: float,
    risk_base_pct: float = 0.005,
    external_risk_ceiling_pct: float = 0.03,
    max_notional_pct: float = 1.0,
    min_stop_loss_pct: float = 0.005,
    hyro_max_notional_usd: Optional[float] = None,
) -> Dict[str, Any]:
    """Sizing DINAMICO por risco (FASE 47).

    notional = risk_base_usd / stop_dist_pct, com:
    - stop_dist_pct efetivo >= min_stop_loss_pct (piso);
    - notional limitado por max_notional_pct*capital (leverage 1x);
    - risco resultante limitado pelo teto externo 3% (guarda — 0,5% ja menor).
    Retorna o notional aplicado + qual limite prevaleceu (DETERMINISTICO).
    """
    if capital <= 0 or stop_dist_pct is None or stop_dist_pct <= 0:
        return {"position_size_usd": 0.0, "binding": "invalid_input",
                "risk_usd": 0.0, "stop_dist_pct": stop_dist_pct}
    eff_stop = max(float(stop_dist_pct), float(min_stop_loss_pct))
    risk_base_usd = risk_base_pct * capital
    raw_notional = risk_base_usd / eff_stop
    notional_cap = max_notional_pct * capital
    ceiling_notional = (external_risk_ceiling_pct * capital) / eff_stop
    binding = "risk_base"
    notional = raw_notional
    if ceiling_notional < notional:
        notional, binding = ceiling_notional, "external_risk_ceiling_3pct"
    if notional_cap < notional:
        notional, binding = notional_cap, "exposure_cap_leverage_1x"
    # P4: teto de NOTIONAL real da HyroTrader (separado), se fornecido.
    if hyro_max_notional_usd is not None and hyro_max_notional_usd < notional:
        notional, binding = float(hyro_max_notional_usd), \
            "hyro_max_notional_cap"
    notional = round(notional, 2)
    return {
        "position_size_usd": notional,
        "risk_usd": round(notional * eff_stop, 2),
        "stop_dist_pct": eff_stop,
        "binding": binding,
        "risk_base_usd": round(risk_base_usd, 2),
    }


__all__ = [
    "EffectiveConfig",
    "FASE47_SPEC",
    "HYROTRADER_EXTERNAL",
    "build_effective_config",
    "dynamic_position_size",
]
