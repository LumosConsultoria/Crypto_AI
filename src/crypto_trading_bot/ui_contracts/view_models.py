"""
UI ViewModels - Field Metadata Contract (FASE 37 Complemento)
=============================================================
Contrato de CAMPOS (metadados) para a UI FUTURA dos fluxos novos da
FASE 37: entrada do operador, execucao de backtest e dados historicos.
A UI visual NAO eh implementada agora; este contrato JA descreve cada
campo (nome/label/tipo/origem/obrigatorio/default/validacao/editavel/
sensivel/mascarado/campo_de_relatorio/campo_de_decision_trace).

⚠️  NENHUM secret aparece no ViewModel. Campos `sensitive=True` NUNCA
    carregam valor: `value=None`, `masked=True`. O ViewModel descreve a
    EXISTENCIA do campo, jamais o segredo.

Cada FieldSpec eh JSON-ready (to_dict). O builder so popula `value` para
campos NAO sensiveis e quando um valor seguro foi explicitamente passado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional, Tuple


@dataclass(frozen=True)
class FieldSpec:
    """Metadado de UM campo de UI (sem secret)."""
    name: str
    label: str
    type: str                       # string|int|float|bool|enum|date|secret
    source: str                     # operator|config|api_derived|calculated
    required: bool = False
    default: Any = None
    validation: str = ""
    editable: bool = True
    sensitive: bool = False
    masked: bool = False
    report_field: bool = False
    decision_trace_field: bool = False
    options: Tuple[str, ...] = field(default_factory=tuple)
    value: Any = None               # nunca preenchido p/ sensitive

    def __post_init__(self) -> None:
        if self.sensitive:
            # Garante que nenhum valor sensivel vaze pelo ViewModel.
            object.__setattr__(self, "value", None)
            object.__setattr__(self, "masked", True)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "source": self.source,
            "required": self.required,
            "default": self.default,
            "validation": self.validation,
            "editable": self.editable,
            "sensitive": self.sensitive,
            "masked": self.masked,
            "report_field": self.report_field,
            "decision_trace_field": self.decision_trace_field,
            "options": list(self.options),
            "value": self.value,
        }


def _vm(schema: str, title: str, fields: List[FieldSpec],
        notes: Tuple[str, ...] = ()) -> dict:
    return {
        "schema": schema,
        "title": title,
        "no_secret_guarantee": True,
        "fields": [f.to_dict() for f in fields],
        "notes": list(notes),
    }


def build_historical_data_view_model(
    *, values: Optional[Mapping[str, Any]] = None,
) -> dict:
    """ViewModel dos inputs do Historical Data Fetcher (Parte A)."""
    v = dict(values or {})
    fields = [
        FieldSpec("provider", "Provider", "enum", "operator",
                  required=True, validation="fake|binance",
                  options=("fake", "binance"), report_field=True,
                  value=v.get("provider")),
        FieldSpec("symbol", "Symbol", "string", "operator", required=True,
                  validation="ex.: BTCUSDT", report_field=True,
                  value=v.get("symbol")),
        FieldSpec("timeframe", "Timeframe", "enum", "operator",
                  required=True, validation="1m..1d", report_field=True,
                  value=v.get("timeframe")),
        FieldSpec("start_date", "Start date (UTC)", "date", "operator",
                  required=True, validation="YYYY-MM-DD",
                  report_field=True, value=v.get("start_date")),
        FieldSpec("end_date", "End date (UTC)", "date", "operator",
                  required=True, validation="> start_date",
                  report_field=True, value=v.get("end_date")),
        FieldSpec("allow_network", "Allow network (provider real)",
                  "bool", "operator", default=False,
                  validation="obrigatorio p/ provider real",
                  value=v.get("allow_network")),
        FieldSpec("force", "Overwrite existing", "bool", "operator",
                  default=False, value=v.get("force")),
        FieldSpec("dry_run", "Dry-run", "bool", "operator",
                  default=False, value=v.get("dry_run")),
        FieldSpec("run_readiness", "Run Data Readiness", "bool",
                  "operator", default=False, value=v.get("run_readiness")),
        FieldSpec("checksum_sha256", "Dataset checksum", "string",
                  "calculated", editable=False, report_field=True,
                  value=v.get("checksum_sha256")),
    ]
    return _vm("historical_data_view_model_v1",
               "Historical Data Fetcher", fields,
               notes=(
                   "Provider real usa endpoint PUBLICO read-only; nunca "
                   "execucao. Sem API key neste fluxo.",
               ))


def build_backtest_run_view_model(
    *, context: Optional[Mapping[str, Any]] = None,
) -> dict:
    """ViewModel da execucao de backtest operacional (Parte C/D)."""
    c = dict(context or {})
    enabled_kinds = set(c.get("enabled_context_kinds") or ())

    def _ctx_on(kind: str):
        return True if kind in enabled_kinds else (
            None if not c else False)

    fields = [
        FieldSpec("strategy", "Strategy", "enum", "operator",
                  required=True, validation="registry + perfil",
                  report_field=True, decision_trace_field=True,
                  value=c.get("strategy")),
        FieldSpec("profile", "Profile", "enum", "operator",
                  validation="allowed_strategies", report_field=True,
                  decision_trace_field=True, value=c.get("profile")),
        FieldSpec("capital_usd", "Capital (USD, simulado)", "float",
                  "operator", required=True, validation="> 0",
                  report_field=True, value=c.get("capital_usd")),
        FieldSpec("fees_bps", "Fees (bps)", "float", "operator",
                  default=0.0, validation=">= 0", report_field=True,
                  value=c.get("fees_bps")),
        FieldSpec("slippage_bps", "Slippage (bps)", "float", "operator",
                  default=0.0, validation=">= 0", report_field=True,
                  value=c.get("slippage_bps")),
        FieldSpec("min_stop_loss_pct", "Min stop-loss (piso RiskEngine)",
                  "float", "config", editable=False,
                  validation="travado >= 0.005", report_field=True,
                  decision_trace_field=True,
                  value=c.get("min_stop_loss_pct")),
        FieldSpec("leverage", "Leverage", "float", "operator",
                  default=1.0, validation=">= 1.0", report_field=True,
                  value=c.get("leverage")),
        FieldSpec("enable_ai_context", "Enable AI context", "bool",
                  "operator", default=False, decision_trace_field=True,
                  value=_ctx_on("ai")),
        FieldSpec("enable_market_intelligence", "Enable MI context",
                  "bool", "operator", default=False,
                  decision_trace_field=True,
                  value=_ctx_on("market_intelligence")),
        FieldSpec("enable_polymarket_context", "Enable Polymarket context",
                  "bool", "operator", default=False,
                  decision_trace_field=True,
                  value=_ctx_on("polymarket")),
        FieldSpec("allow_missing_context", "Allow missing context",
                  "bool", "operator", default=True),
        FieldSpec("simulate_execution_only", "Simulated execution only",
                  "bool", "config", default=True, editable=False,
                  validation="travado True (nunca ordem real)",
                  report_field=True),
    ]
    return _vm("backtest_run_view_model_v1",
               "Backtest Operational Run", fields,
               notes=(
                   "Execucao SEMPRE simulada. RiskEngine soberano "
                   "(piso travado). Contextos so usam dado REAL, anti "
                   "look-ahead; decision_impact nunca inventado.",
               ))


def build_operator_input_view_model(
    *, requirements: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> dict:
    """ViewModel dos Operator Inputs (V1-V12) p/ a UI futura.

    requirements: opcional, mapa name -> {status,last_updated_at,...}
    (NUNCA valores sensiveis). Campos sensiveis (ex.: credenciais) sao
    marcados sensitive/masked e jamais carregam valor.
    """
    r = dict(requirements or {})

    def _status(n: str) -> Optional[str]:
        item = r.get(n) or {}
        return item.get("status")

    fields = [
        FieldSpec("capital_usd", "Operational capital (USD)", "float",
                  "operator", required=True, validation="> 0",
                  report_field=True, value=None),
        FieldSpec("account_type", "Account type", "enum", "operator",
                  required=True, options=("paper", "demo", "live"),
                  validation="paper|demo|live"),
        FieldSpec("account_currency", "Account currency", "string",
                  "operator", required=True),
        FieldSpec("operational_timezone", "Timezone", "string",
                  "operator", required=True),
        FieldSpec("max_risk_per_trade_usd", "Max risk per trade (USD)",
                  "float", "operator", required=True, validation="> 0",
                  report_field=True, decision_trace_field=True),
        FieldSpec("max_daily_loss_usd", "Max daily loss (USD)", "float",
                  "operator", required=True, validation="> 0",
                  report_field=True),
        FieldSpec("max_position_notional_usd", "Max position notional",
                  "float", "operator", required=True, validation="> 0",
                  report_field=True, decision_trace_field=True),
        FieldSpec("max_leverage", "Max leverage", "float", "operator",
                  required=True, validation=">= 1.0", report_field=True),
        FieldSpec("max_open_positions", "Max open positions", "int",
                  "operator", required=True, validation=">= 1"),
        # Credenciais: descritas, NUNCA com valor (sensitive => masked).
        FieldSpec("exchange_api_key", "Exchange API key", "secret",
                  "operator", required=False, sensitive=True,
                  editable=True,
                  validation="presence-only; nunca exibido/logado"),
        FieldSpec("exchange_api_secret", "Exchange API secret", "secret",
                  "operator", required=False, sensitive=True,
                  editable=True,
                  validation="presence-only; nunca exibido/logado"),
        FieldSpec("ai_api_key", "AI provider API key", "secret",
                  "operator", required=False, sensitive=True,
                  editable=True,
                  validation="presence-only; nunca exibido/logado"),
    ]
    # Anexa status (nao-sensivel) por campo, quando fornecido.
    enriched = []
    for f in fields:
        d = f.to_dict()
        st = _status(f.name)
        if st is not None:
            d["status"] = st
        enriched.append(d)
    return {
        "schema": "operator_input_view_model_v1",
        "title": "Operator Required Inputs (V1-V12)",
        "no_secret_guarantee": True,
        "fields": enriched,
        "notes": [
            "Campos secret NUNCA carregam valor (presence-only). Sem "
            "V1-V4 nenhuma execucao real eh liberada.",
        ],
    }


__all__ = [
    "FieldSpec",
    "build_backtest_run_view_model",
    "build_historical_data_view_model",
    "build_operator_input_view_model",
]
