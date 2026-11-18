"""
Profile → RiskConfig adapter — gate explícito e auditável (FASE 18)
======================================================================
⚠️  AVISOS OBRIGATÓRIOS:
    - NÃO muta o RiskConfig base. SEMPRE retorna nova instância.
    - NÃO toca RiskEngine em runtime — esta camada apenas constrói um
      RiskConfig efetivo. Caller decide instanciar novo RiskEngine.
    - NÃO importa RiskEngine, BotEngine, BybitClient, executores, providers,
      httpx, requests.
    - Funções puras: sem I/O, sem rede, sem mutação de globals.
    - apply só ocorre com confirm=True + operator_token não-vazio + plan
      is_apply_safe=True. Caso contrário levanta ProfileOverrideRejected.
    - HyroTrader é tratado como qualquer outro profile via flags
      estruturados; nenhum branch consulta provider_name.

ARQUITETURA:
    1. build_risk_override_plan(profile, base) → ProfileRiskOverridePlan
       - Compara overrides do profile contra base.
       - Coleta issues: error (apply bloqueia) / warning / info.
       - Reutiliza validate_profile_against_risk_config (FASE 16).

    2. preview_profile_risk_config(profile, base) → AppliedRiskConfigSnapshot
       - Dry-run: monta snapshot SEM aplicar, SEM emitir audit "APPLIED".

    3. apply_profile_overrides_with_gate(profile, base, *, confirm,
       operator_token, notes) → RiskConfig (NOVA instância)
       - Levanta ProfileOverrideRejected em qualquer falha de gate.
       - Emite audit estruturado sanitizado.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, List, Mapping, Tuple

from pydantic import ValidationError

from crypto_trading_bot.config.risk_config import RiskConfig
from crypto_trading_bot.logging_system.logger import get_audit_logger, get_logger
from crypto_trading_bot.operational_profile.profile import OperationalProfile
from crypto_trading_bot.operational_profile.validation import (
    validate_profile_against_risk_config,
)

_logger = get_logger(__name__)
_audit = get_audit_logger(__name__)


# ---------------------------------------------------------------------------
# Sanitização (mesma defesa em profundidade da FASE 16)
# ---------------------------------------------------------------------------

def _sanitize_token(token: str) -> str:
    """Trunca + redacta substrings suspeitas. Token NÃO é credencial,
    mas tratamos defensivamente."""
    if not isinstance(token, str) or not token.strip():
        return "<empty>"
    lower = token.lower()
    suspicious = ("api_key", "api_secret", "bearer ", "x-bapi", "sign=")
    if any(s in lower for s in suspicious):
        return "<redacted_suspicious_token>"
    return token[:8] + ("..." if len(token) > 8 else "")


def _sanitize_notes(notes: str) -> str:
    """Trunca em 200 chars + redacta substrings suspeitas."""
    if not isinstance(notes, str):
        return ""
    truncated = notes[:200]
    lower = truncated.lower()
    suspicious = (
        "api_key", "api_secret", "bearer ", "x-bapi-sign", "authorization:",
    )
    if any(s in lower for s in suspicious):
        return "<redacted_suspicious_notes>"
    return truncated


# ---------------------------------------------------------------------------
# Exceção
# ---------------------------------------------------------------------------

class ProfileOverrideRejected(RuntimeError):
    """
    apply_profile_overrides_with_gate rejeitou aplicação.

    Causas: confirm=False, token vazio, plan com issue 'error'.
    Não silencia — caller deve tratar.
    """


# ---------------------------------------------------------------------------
# Tipos imutáveis
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProfileRiskOverrideIssue:
    """Issue do plano de override — não levanta; é coletada."""
    severity: str          # "error" | "warning" | "info"
    key: str | None        # campo afetado (None se issue geral)
    message: str

    def __post_init__(self) -> None:
        if self.severity not in ("error", "warning", "info"):
            raise ValueError(
                f"severity inválida: {self.severity!r}; "
                f"aceitas: error/warning/info"
            )
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message deve ser string não-vazia")

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "key": self.key,
            "message": self.message,
        }


@dataclass(frozen=True)
class FieldDiff:
    """Diff de um campo do RiskConfig (base vs proposed)."""
    field: str
    base_value: Any
    proposed_value: Any
    changed: bool

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "base_value": self.base_value,
            "proposed_value": self.proposed_value,
            "changed": self.changed,
        }


@dataclass(frozen=True)
class ProfileRiskOverridePlan:
    """Plano de override imutável; preview-friendly e auditável."""
    profile_name: str
    base_config: Mapping[str, Any]
    proposed_config: Mapping[str, Any]
    diffs: Tuple[FieldDiff, ...]
    issues: Tuple[ProfileRiskOverrideIssue, ...]
    is_apply_safe: bool
    requires_confirmation: bool

    def __post_init__(self) -> None:
        # MappingProxyType para snapshots
        if not isinstance(self.base_config, MappingProxyType):
            object.__setattr__(
                self, "base_config",
                MappingProxyType(dict(self.base_config)),
            )
        if not isinstance(self.proposed_config, MappingProxyType):
            object.__setattr__(
                self, "proposed_config",
                MappingProxyType(dict(self.proposed_config)),
            )
        # tuplas defensivas
        if not isinstance(self.diffs, tuple):
            object.__setattr__(self, "diffs", tuple(self.diffs))
        if not isinstance(self.issues, tuple):
            object.__setattr__(self, "issues", tuple(self.issues))

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == "warning" for i in self.issues)

    def to_dict(self) -> dict:
        return {
            "profile_name": self.profile_name,
            "base_config": dict(self.base_config),
            "proposed_config": dict(self.proposed_config),
            "diffs": [d.to_dict() for d in self.diffs],
            "issues": [i.to_dict() for i in self.issues],
            "is_apply_safe": self.is_apply_safe,
            "requires_confirmation": self.requires_confirmation,
        }


@dataclass(frozen=True)
class AppliedRiskConfigSnapshot:
    """Snapshot do resultado de preview/apply. operator_token SEMPRE
    sanitizado antes de armazenar."""
    profile_name: str
    applied_at: datetime
    operator_token_sanitized: str
    final_config: Mapping[str, Any]
    diff_summary: Tuple[FieldDiff, ...]
    issues_at_apply: Tuple[ProfileRiskOverrideIssue, ...]
    was_applied: bool   # False em preview, True em apply real

    def __post_init__(self) -> None:
        if self.applied_at.tzinfo is None:
            object.__setattr__(
                self, "applied_at",
                self.applied_at.replace(tzinfo=timezone.utc),
            )
        if not isinstance(self.final_config, MappingProxyType):
            object.__setattr__(
                self, "final_config",
                MappingProxyType(dict(self.final_config)),
            )
        if not isinstance(self.diff_summary, tuple):
            object.__setattr__(self, "diff_summary", tuple(self.diff_summary))
        if not isinstance(self.issues_at_apply, tuple):
            object.__setattr__(
                self, "issues_at_apply", tuple(self.issues_at_apply),
            )

    def to_dict(self) -> dict:
        return {
            "profile_name": self.profile_name,
            "applied_at": self.applied_at.isoformat(),
            "operator_token_sanitized": self.operator_token_sanitized,
            "final_config": dict(self.final_config),
            "diff_summary": [d.to_dict() for d in self.diff_summary],
            "issues_at_apply": [i.to_dict() for i in self.issues_at_apply],
            "was_applied": self.was_applied,
        }


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _snapshot_risk_config(rc: RiskConfig) -> dict[str, Any]:
    """
    Snapshot dos campos relevantes (numéricos/identidade) do RiskConfig
    em ordem determinística. Exclui properties calculadas (max_daily_loss_usd
    etc.). Usado para base/proposed config.
    """
    keys = [
        "account_profile_name", "provider_name", "provider_type",
        "is_prop_firm", "is_challenge_account", "is_funded_account",
        "account_size_usd",
        "max_daily_loss_pct", "max_total_loss_pct",
        "max_trades_per_day", "max_open_positions",
        "max_risk_per_trade_pct", "max_exposure_per_asset_pct",
        "max_leverage",
        "min_stop_loss_pct", "max_stop_loss_pct",
        "max_position_size_pct",
        "challenge_profit_target_usd", "enforce_profit_target",
    ]
    snap: dict[str, Any] = {}
    for k in keys:
        if hasattr(rc, k):
            snap[k] = getattr(rc, k)
    return snap


def _build_proposed_config(
    base_rc: RiskConfig, overrides: Mapping[str, Any],
) -> Tuple[RiskConfig | None, List[ProfileRiskOverrideIssue]]:
    """
    Constrói nova instância de RiskConfig aplicando overrides via
    pydantic.model_copy(update=...). Retorna (new_rc, issues).

    new_rc é None quando overrides causam ValidationError ou keys inválidas.
    Issues coletadas para qualquer key desconhecida ou valor inválido.
    """
    issues: List[ProfileRiskOverrideIssue] = []
    if not overrides:
        # No-op: retorna NOVA instância equivalente ao base.
        return base_rc.model_copy(), issues

    # Detecta keys desconhecidas ANTES de tentar model_copy
    valid_fields = set(RiskConfig.model_fields.keys())
    safe_overrides: dict[str, Any] = {}
    for k, v in overrides.items():
        if k not in valid_fields:
            issues.append(ProfileRiskOverrideIssue(
                severity="error",
                key=k,
                message=(
                    f"chave {k!r} não existe em RiskConfig "
                    f"(campos válidos: {sorted(valid_fields)[:6]}…)"
                ),
            ))
            continue
        safe_overrides[k] = v

    if not safe_overrides:
        # Tudo era key inválida — não há como gerar proposed válido.
        # Mas ainda retornamos new_rc = copy do base para que o caller
        # possa exibir o estado atual sem propagar None.
        return base_rc.model_copy(), issues

    try:
        new_rc = base_rc.model_copy(update=safe_overrides)
        # Pydantic v2 model_copy NÃO revalida por default. Forçamos via
        # nova validação: cria nova instância a partir do dump.
        dumped = new_rc.model_dump()
        # model_validate revalida todos os ranges
        new_rc = RiskConfig.model_validate(dumped)
        return new_rc, issues
    except ValidationError as e:
        # Coleta cada erro do pydantic como issue sanitizada
        for err in e.errors():
            loc = err.get("loc") or ()
            key = ".".join(str(p) for p in loc) if loc else None
            # Mensagem do pydantic é segura (não contém secrets)
            msg = str(err.get("msg", "validation error"))
            issues.append(ProfileRiskOverrideIssue(
                severity="error",
                key=key,
                message=f"ValidationError em {key!r}: {msg}",
            ))
        return None, issues


def _compute_diffs(
    base_snap: dict[str, Any], proposed_snap: dict[str, Any],
) -> List[FieldDiff]:
    """Diff determinístico ordenado por nome de campo."""
    all_keys = sorted(set(base_snap.keys()) | set(proposed_snap.keys()))
    diffs: List[FieldDiff] = []
    for k in all_keys:
        bv = base_snap.get(k)
        pv = proposed_snap.get(k)
        diffs.append(FieldDiff(
            field=k, base_value=bv, proposed_value=pv,
            changed=(bv != pv),
        ))
    return diffs


def _detect_redundant_overrides(
    overrides: Mapping[str, Any], base_snap: dict[str, Any],
) -> List[ProfileRiskOverrideIssue]:
    """Override redundante = mesmo valor que o base. severity=info."""
    issues: List[ProfileRiskOverrideIssue] = []
    for k, v in overrides.items():
        if k in base_snap and base_snap[k] == v:
            issues.append(ProfileRiskOverrideIssue(
                severity="info",
                key=k,
                message=(
                    f"override {k!r}={v!r} é redundante "
                    f"(mesmo valor do base)"
                ),
            ))
    return issues


def _detect_account_size_divergence(
    profile: OperationalProfile, base_snap: dict[str, Any],
) -> List[ProfileRiskOverrideIssue]:
    """profile.account_size_usd vs base.account_size_usd."""
    issues: List[ProfileRiskOverrideIssue] = []
    p_cap = profile.account_size_usd
    b_cap = base_snap.get("account_size_usd")
    if p_cap is None or b_cap is None:
        return issues
    try:
        diff_pct = abs(float(p_cap) - float(b_cap)) / max(abs(float(b_cap)), 1.0)
    except (TypeError, ValueError, ZeroDivisionError):
        return issues
    # Tolerância 0.5% para arredondamento
    if diff_pct > 0.005:
        issues.append(ProfileRiskOverrideIssue(
            severity="warning",
            key="account_size_usd",
            message=(
                f"profile.account_size_usd={p_cap} diverge de "
                f"base.account_size_usd={b_cap}; aplique override "
                f"explícito ou alinhe via .env"
            ),
        ))
    return issues


# ---------------------------------------------------------------------------
# build_risk_override_plan
# ---------------------------------------------------------------------------

def build_risk_override_plan(
    profile: OperationalProfile,
    base_risk_config: RiskConfig,
) -> ProfileRiskOverridePlan:
    """
    Constrói o plano comparando profile.risk_config_overrides contra base.

    NÃO aplica. NÃO muta nada. Sempre retorna plano (mesmo com errors).

    Args:
        profile: OperationalProfile (frozen).
        base_risk_config: RiskConfig base (não é mutado).

    Returns:
        ProfileRiskOverridePlan imutável.
    """
    if not isinstance(profile, OperationalProfile):
        raise TypeError(
            f"profile deve ser OperationalProfile; "
            f"recebido {type(profile).__name__}"
        )
    if not isinstance(base_risk_config, RiskConfig):
        raise TypeError(
            f"base_risk_config deve ser RiskConfig; "
            f"recebido {type(base_risk_config).__name__}"
        )

    base_snap = _snapshot_risk_config(base_risk_config)
    overrides = dict(profile.risk_config_overrides)

    new_rc, override_issues = _build_proposed_config(base_risk_config, overrides)
    if new_rc is None:
        # Construção falhou — proposed_snap fica igual ao base (defensivo)
        proposed_snap = dict(base_snap)
    else:
        proposed_snap = _snapshot_risk_config(new_rc)

    # Redundância: apenas se temos new_rc válido E overrides não-vazios
    redundancy_issues: List[ProfileRiskOverrideIssue] = []
    if overrides:
        redundancy_issues = _detect_redundant_overrides(overrides, base_snap)

    # Divergência de account_size_usd (warning)
    capital_issues = _detect_account_size_divergence(profile, base_snap)

    # Cross-config issues da FASE 16 (warnings)
    cross_issues_raw = validate_profile_against_risk_config(
        profile, base_risk_config,
    )
    cross_issues = [
        ProfileRiskOverrideIssue(
            severity="warning", key=None, message=msg,
        )
        for msg in cross_issues_raw
    ]

    diffs = _compute_diffs(base_snap, proposed_snap)
    has_real_diff = any(d.changed for d in diffs)

    all_issues = tuple(
        override_issues + capital_issues + redundancy_issues + cross_issues
    )
    has_errors = any(i.severity == "error" for i in all_issues)

    plan = ProfileRiskOverridePlan(
        profile_name=profile.name,
        base_config=base_snap,
        proposed_config=proposed_snap,
        diffs=tuple(diffs),
        issues=all_issues,
        is_apply_safe=(not has_errors),
        requires_confirmation=has_real_diff,
    )

    # Audit estruturado (sem secrets)
    _audit.info(
        f"PROFILE_OVERRIDE_PLAN | profile={profile.name} | "
        f"diffs={sum(1 for d in diffs if d.changed)} | "
        f"issues_error={sum(1 for i in all_issues if i.severity == 'error')} | "
        f"issues_warning={sum(1 for i in all_issues if i.severity == 'warning')} | "
        f"issues_info={sum(1 for i in all_issues if i.severity == 'info')} | "
        f"apply_safe={plan.is_apply_safe}"
    )
    return plan


# ---------------------------------------------------------------------------
# preview_profile_risk_config
# ---------------------------------------------------------------------------

def preview_profile_risk_config(
    profile: OperationalProfile,
    base_risk_config: RiskConfig,
) -> AppliedRiskConfigSnapshot:
    """
    Dry-run: monta snapshot do resultado SEM aplicar.

    NÃO muta base_risk_config. NÃO emite PROFILE_OVERRIDE_APPLIED.
    Retorna AppliedRiskConfigSnapshot com was_applied=False.
    """
    plan = build_risk_override_plan(profile, base_risk_config)

    new_rc, _ = _build_proposed_config(
        base_risk_config, dict(profile.risk_config_overrides),
    )
    if new_rc is None:
        final_snap = dict(plan.base_config)
    else:
        final_snap = _snapshot_risk_config(new_rc)

    snapshot = AppliedRiskConfigSnapshot(
        profile_name=profile.name,
        applied_at=datetime.now(timezone.utc),
        operator_token_sanitized="<preview>",
        final_config=final_snap,
        diff_summary=plan.diffs,
        issues_at_apply=plan.issues,
        was_applied=False,
    )
    return snapshot


# ---------------------------------------------------------------------------
# apply_profile_overrides_with_gate
# ---------------------------------------------------------------------------

def apply_profile_overrides_with_gate(
    profile: OperationalProfile,
    base_risk_config: RiskConfig,
    *,
    confirm: bool,
    operator_token: str,
    notes: str = "",
) -> RiskConfig:
    """
    Aplica overrides retornando NOVA instância de RiskConfig.

    Gate humano explícito:
        - confirm=False                         → ProfileOverrideRejected.
        - operator_token vazio/não-string       → ProfileOverrideRejected.
        - plan.is_apply_safe=False              → ProfileOverrideRejected.

    No-op seguro: profile sem risk_config_overrides retorna NOVA instância
    equivalente ao base. base_risk_config NÃO é mutado.

    Audit:
        - PROFILE_OVERRIDE_APPLIED  (sucesso, token/notes sanitizados).
        - PROFILE_OVERRIDE_REJECTED (falha de gate, reason sanitizada).
    """
    # Gate 1: confirm
    if not isinstance(confirm, bool) or confirm is not True:
        reason = "confirm deve ser True para aplicar overrides"
        _audit.warning(
            f"PROFILE_OVERRIDE_REJECTED | profile={profile.name} | "
            f"reason='{reason}'"
        )
        raise ProfileOverrideRejected(reason)

    # Gate 2: operator_token não-vazio
    if not isinstance(operator_token, str) or not operator_token.strip():
        reason = "operator_token deve ser string não-vazia"
        _audit.warning(
            f"PROFILE_OVERRIDE_REJECTED | profile={profile.name} | "
            f"reason='{reason}'"
        )
        raise ProfileOverrideRejected(reason)

    plan = build_risk_override_plan(profile, base_risk_config)

    # Gate 3: plan seguro
    if not plan.is_apply_safe:
        error_msgs = [
            i.message for i in plan.issues if i.severity == "error"
        ]
        reason = (
            f"apply rejeitado: plano não-seguro ({len(error_msgs)} erro(s))"
        )
        _audit.warning(
            f"PROFILE_OVERRIDE_REJECTED | profile={profile.name} | "
            f"reason='{reason}'"
        )
        raise ProfileOverrideRejected(
            f"{reason}: {'; '.join(error_msgs[:3])}"
        )

    # Aplica: nova instância
    new_rc, _ = _build_proposed_config(
        base_risk_config, dict(profile.risk_config_overrides),
    )
    if new_rc is None:
        # Defensivo: não esperado quando plan.is_apply_safe=True
        reason = "construção do RiskConfig efetivo falhou inesperadamente"
        _audit.warning(
            f"PROFILE_OVERRIDE_REJECTED | profile={profile.name} | "
            f"reason='{reason}'"
        )
        raise ProfileOverrideRejected(reason)

    # Garante NOVA instância mesmo no caso no-op
    sanitized_token = _sanitize_token(operator_token)
    sanitized_notes = _sanitize_notes(notes)

    _audit.info(
        f"PROFILE_OVERRIDE_APPLIED | profile={profile.name} | "
        f"operator_token={sanitized_token} | "
        f"diffs={sum(1 for d in plan.diffs if d.changed)} | "
        f"notes='{sanitized_notes}'"
    )
    return new_rc
