"""
Demo Session Readiness — Check + Report (FASE 19)
====================================================
⚠️  AVISOS OBRIGATÓRIOS:
    - DOES NOT EXECUTE. Nenhum método inicia sessão, envia ordem, chama
      executor, instancia BybitClient ou chama rede.
    - PROVIDER-AGNOSTIC. NÃO importa BybitClient, BybitDemoExecutor,
      BybitTestnetExecutor, DemoExecutionResult, RiskEngine, BotEngine,
      SessionRunner, providers, httpx, requests.
    - PaperTrader continua o default absoluto. is_ready_for_gated_demo=True
      é APENAS SINAL — não autoriza ordem, não promove provider.
    - ProviderRegistry consultado SOMENTE em modo read-only (`get`).
      Nenhuma chamada de mutação (register/unregister/replace).
    - bybit_demo_linear continua OPT_IN. Esta camada NÃO promove para
      ACTIVE.
    - risk_config_overrides NÃO é aplicado aqui. Caller decide via
      apply_profile_overrides_with_gate (FASE 18) e passa o snapshot
      pronto. Este módulo apenas INSPECIONA.

ARQUITETURA:
    DemoSessionReadinessCheck(...).evaluate() → DemoSessionReadinessReport

    6 gates, executados em ordem determinística:
        1. SAFETY_STATE      — SafetyStateMachine.state == NORMAL
        2. PROFILE_CHECK     — validate_profile_self limpo
        3. PROVIDER_STATUS   — bybit_demo_linear == OPT_IN (exato)
        4. RISK_CONFIG_SNAPSHOT — AppliedRiskConfigSnapshot consistente
                                  com profile.risk_config_overrides
        5. LAST_FLAGS_CLEAN  — SafetyFlags sem manual/halt/triangulated
                               (respeitando require_manual_ack_on_triangulation)
        6. PREFLIGHT_LOCAL   — capital > 0, símbolo não-vazio, sem
                               posição aberta declarada, sem ordem
                               aberta declarada
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, List, Mapping, Optional, Tuple

from crypto_trading_bot.demo_session_readiness.flags_adapter import SafetyFlags
from crypto_trading_bot.execution.provider_capability import ProviderStatus
from crypto_trading_bot.execution.provider_registry import (
    ProviderRegistry,
    get_registry,
)
from crypto_trading_bot.logging_system.logger import (
    get_audit_logger,
    get_logger,
)
from crypto_trading_bot.operational_profile.profile import OperationalProfile
from crypto_trading_bot.operational_profile.risk_adapter import (
    AppliedRiskConfigSnapshot,
)
from crypto_trading_bot.operational_profile.validation import (
    validate_profile_self,
)
from crypto_trading_bot.operational_safety.safety_state import SafetyState
from crypto_trading_bot.operational_safety.safety_state_machine import (
    SafetyStateMachine,
)

_logger = get_logger(__name__)
_audit = get_audit_logger(__name__)


# Provider-id alvo da FASE 19. NÃO é configurável aqui — segue intencional
# para evitar uso acidental com outros providers neste check.
_DEMO_PROVIDER_ID = "bybit_demo_linear"


_VALID_SEVERITIES = ("error", "warning", "info")


# ---------------------------------------------------------------------------
# Sanitização defensiva (logs/output)
# ---------------------------------------------------------------------------

_SUSPICIOUS_LOG_SUBSTRINGS = (
    "api_key", "api_secret", "bearer ", "x-bapi", "sign=",
    "authorization:",
)


def _sanitize_for_log(text: str) -> str:
    """Trunca em 200 chars + redacta substrings suspeitas."""
    if not isinstance(text, str):
        return ""
    truncated = text[:200]
    lower = truncated.lower()
    if any(s in lower for s in _SUSPICIOUS_LOG_SUBSTRINGS):
        return "<redacted_suspicious>"
    return truncated


# ---------------------------------------------------------------------------
# Enums e tipos imutáveis
# ---------------------------------------------------------------------------

class ReadinessGate(str, Enum):
    """
    Gates avaliados pelo DemoSessionReadinessCheck.

    Valores são contrato estável — não renomear sem nova fase de quebra.
    """
    SAFETY_STATE = "safety_state"
    PROFILE_CHECK = "profile_check"
    PROVIDER_STATUS = "provider_status"
    RISK_CONFIG_SNAPSHOT = "risk_config_snapshot"
    LAST_FLAGS_CLEAN = "last_flags_clean"
    PREFLIGHT_LOCAL = "preflight_local"


@dataclass(frozen=True)
class ReadinessIssue:
    """Issue individual associada a um gate."""
    gate: ReadinessGate
    severity: str        # "error" | "warning" | "info"
    message: str
    detail: Optional[str] = None  # contexto extra (sanitizado)

    def __post_init__(self) -> None:
        if not isinstance(self.gate, ReadinessGate):
            raise TypeError(
                "gate deve ser ReadinessGate; "
                f"recebido {type(self.gate).__name__}"
            )
        if self.severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"severity inválida: {self.severity!r}; "
                f"aceitas: {list(_VALID_SEVERITIES)}"
            )
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message deve ser string não-vazia")
        if self.detail is not None and not isinstance(self.detail, str):
            raise TypeError("detail deve ser string ou None")

    @property
    def is_blocking(self) -> bool:
        return self.severity == "error"

    def to_dict(self) -> dict:
        return {
            "gate": self.gate.value,
            "severity": self.severity,
            "message": self.message,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class DemoSessionReadinessReport:
    """
    Resultado consolidado do DemoSessionReadinessCheck.

    Frozen. Tuplas para sequências. JSON-serializável via to_dict().
    is_ready_for_gated_demo=True NÃO autoriza ordem — é apenas sinal.

    Atributos:
        profile_name: nome do profile avaliado.
        symbol: símbolo declarado para a futura sessão demo.
        capital: capital declarado.
        provider_id: provider-id alvo (sempre bybit_demo_linear nesta fase).
        evaluated_at: UTC tz-aware.
        is_ready_for_gated_demo: True se zero issue 'error' em qualquer gate.
        gates_evaluated: tupla de ReadinessGate efetivamente checados.
        issues: tupla de ReadinessIssue (ordem determinística por gate).
        blocking_reasons: tupla de mensagens curtas das issues 'error'.
        notes: nota livre do operador (sanitizada).
    """
    profile_name: str
    symbol: str
    capital: float
    provider_id: str
    evaluated_at: datetime
    is_ready_for_gated_demo: bool
    gates_evaluated: Tuple[ReadinessGate, ...]
    issues: Tuple[ReadinessIssue, ...]
    blocking_reasons: Tuple[str, ...]
    notes: str = ""

    def __post_init__(self) -> None:
        # tz-aware
        if self.evaluated_at.tzinfo is None:
            object.__setattr__(
                self,
                "evaluated_at",
                self.evaluated_at.replace(tzinfo=timezone.utc),
            )
        # tuplas defensivas
        if not isinstance(self.gates_evaluated, tuple):
            object.__setattr__(
                self, "gates_evaluated", tuple(self.gates_evaluated)
            )
        if not isinstance(self.issues, tuple):
            object.__setattr__(self, "issues", tuple(self.issues))
        if not isinstance(self.blocking_reasons, tuple):
            object.__setattr__(
                self, "blocking_reasons", tuple(self.blocking_reasons)
            )
        # Consistência: se há issue 'error', is_ready_for_gated_demo deve
        # ser False. Se não há, deve refletir que NENHUM gate quebrou.
        has_error = any(i.severity == "error" for i in self.issues)
        if has_error and self.is_ready_for_gated_demo:
            raise ValueError(
                "DemoSessionReadinessReport inconsistente: "
                "is_ready_for_gated_demo=True com issues de severidade 'error'."
            )
        if not has_error and not self.is_ready_for_gated_demo and self.blocking_reasons:
            raise ValueError(
                "DemoSessionReadinessReport inconsistente: "
                "is_ready_for_gated_demo=False sem issues 'error' mas "
                "blocking_reasons preenchido."
            )
        # blocking_reasons deve bater com issues 'error'
        expected_count = sum(1 for i in self.issues if i.severity == "error")
        if len(self.blocking_reasons) != expected_count:
            raise ValueError(
                "DemoSessionReadinessReport inconsistente: "
                f"blocking_reasons ({len(self.blocking_reasons)}) != "
                f"count(severity='error') ({expected_count})."
            )

    @property
    def total_issues(self) -> int:
        return len(self.issues)

    @property
    def total_blocks(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def total_warnings(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    @property
    def total_info(self) -> int:
        return sum(1 for i in self.issues if i.severity == "info")

    def issues_by_gate(self, gate: ReadinessGate) -> Tuple[ReadinessIssue, ...]:
        return tuple(i for i in self.issues if i.gate is gate)

    def to_dict(self) -> dict:
        return {
            "profile_name": self.profile_name,
            "symbol": self.symbol,
            "capital": self.capital,
            "provider_id": self.provider_id,
            "evaluated_at": self.evaluated_at.isoformat(),
            "is_ready_for_gated_demo": self.is_ready_for_gated_demo,
            "gates_evaluated": [g.value for g in self.gates_evaluated],
            "issues": [i.to_dict() for i in self.issues],
            "blocking_reasons": list(self.blocking_reasons),
            "total_issues": self.total_issues,
            "total_blocks": self.total_blocks,
            "total_warnings": self.total_warnings,
            "total_info": self.total_info,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# DemoSessionReadinessCheck
# ---------------------------------------------------------------------------

class DemoSessionReadinessCheck:
    """
    Agregador de evidência local para preparação de futura sessão demo
    gated. **Não executa**. Não chama rede. Não envia ordem.

    USO:
        check = DemoSessionReadinessCheck(
            profile=profile,
            symbol="BTCUSDT",
            capital=5000.0,
            safety_machine=SafetyStateMachine(),
            risk_snapshot=optional_snapshot,
            last_safety_flags=optional_flags,
            has_open_position=False,
            has_open_orders=False,
            provider_registry=None,  # default: registry singleton (read-only)
            notes="",
        )
        report = check.evaluate()
        # report.is_ready_for_gated_demo é apenas SINAL.
    """

    def __init__(
        self,
        *,
        profile: OperationalProfile,
        symbol: str,
        capital: float,
        safety_machine: SafetyStateMachine,
        risk_snapshot: Optional[AppliedRiskConfigSnapshot] = None,
        last_safety_flags: Optional[SafetyFlags] = None,
        has_open_position: bool = False,
        has_open_orders: bool = False,
        provider_registry: Optional[ProviderRegistry] = None,
        notes: str = "",
    ) -> None:
        if not isinstance(profile, OperationalProfile):
            raise TypeError(
                "profile deve ser OperationalProfile; "
                f"recebido {type(profile).__name__}"
            )
        if not isinstance(safety_machine, SafetyStateMachine):
            raise TypeError(
                "safety_machine deve ser SafetyStateMachine; "
                f"recebido {type(safety_machine).__name__}"
            )
        if not isinstance(symbol, str):
            raise TypeError("symbol deve ser string")
        if not isinstance(capital, (int, float)):
            raise TypeError("capital deve ser numérico")
        if risk_snapshot is not None and not isinstance(
            risk_snapshot, AppliedRiskConfigSnapshot
        ):
            raise TypeError(
                "risk_snapshot deve ser AppliedRiskConfigSnapshot ou None"
            )
        if last_safety_flags is not None and not isinstance(
            last_safety_flags, SafetyFlags
        ):
            raise TypeError(
                "last_safety_flags deve ser SafetyFlags ou None"
            )

        self._profile = profile
        self._symbol = symbol
        self._capital = float(capital)
        self._safety_machine = safety_machine
        self._risk_snapshot = risk_snapshot
        self._last_safety_flags = last_safety_flags
        self._has_open_position = bool(has_open_position)
        self._has_open_orders = bool(has_open_orders)
        # Read-only: nunca chamamos métodos de mutação.
        self._registry = provider_registry or get_registry()
        self._notes = str(notes or "")

    # -----------------------------------------------------------------
    # Evaluate
    # -----------------------------------------------------------------

    def evaluate(self) -> DemoSessionReadinessReport:
        """
        Avalia os 6 gates em ordem determinística e produz o relatório.

        NÃO executa nada. NÃO promove provider. NÃO aplica overrides.
        Read-only sobre ProviderRegistry.
        """
        issues: List[ReadinessIssue] = []
        gates: List[ReadinessGate] = []

        # 1. SAFETY_STATE
        gates.append(ReadinessGate.SAFETY_STATE)
        self._check_safety_state(issues)

        # 2. PROFILE_CHECK
        gates.append(ReadinessGate.PROFILE_CHECK)
        self._check_profile_self(issues)

        # 3. PROVIDER_STATUS
        gates.append(ReadinessGate.PROVIDER_STATUS)
        self._check_provider_status(issues)

        # 4. RISK_CONFIG_SNAPSHOT
        gates.append(ReadinessGate.RISK_CONFIG_SNAPSHOT)
        self._check_risk_snapshot(issues)

        # 5. LAST_FLAGS_CLEAN
        gates.append(ReadinessGate.LAST_FLAGS_CLEAN)
        self._check_last_safety_flags(issues)

        # 6. PREFLIGHT_LOCAL
        gates.append(ReadinessGate.PREFLIGHT_LOCAL)
        self._check_preflight_local(issues)

        # Agregação
        blocking_msgs = tuple(
            i.message for i in issues if i.severity == "error"
        )
        is_ready = len(blocking_msgs) == 0

        report = DemoSessionReadinessReport(
            profile_name=self._profile.name,
            symbol=self._symbol,
            capital=self._capital,
            provider_id=_DEMO_PROVIDER_ID,
            evaluated_at=datetime.now(timezone.utc),
            is_ready_for_gated_demo=is_ready,
            gates_evaluated=tuple(gates),
            issues=tuple(issues),
            blocking_reasons=blocking_msgs,
            notes=_sanitize_for_log(self._notes),
        )
        self._audit_report(report)
        return report

    # -----------------------------------------------------------------
    # Gates individuais
    # -----------------------------------------------------------------

    def _check_safety_state(self, issues: List[ReadinessIssue]) -> None:
        state = self._safety_machine.state
        if state is not SafetyState.NORMAL:
            issues.append(ReadinessIssue(
                gate=ReadinessGate.SAFETY_STATE,
                severity="error",
                message=(
                    f"SafetyStateMachine não está em NORMAL "
                    f"(atual: {state.value})"
                ),
                detail=(
                    "Demo gated exige NORMAL. Conclua acknowledge → "
                    "resolve → reset antes de prosseguir."
                ),
            ))
            return
        if self._safety_machine.requires_operator_ack:
            issues.append(ReadinessIssue(
                gate=ReadinessGate.SAFETY_STATE,
                severity="error",
                message="SafetyStateMachine requer ack de operador",
                detail="Operador deve completar ack antes da sessão demo.",
            ))

    def _check_profile_self(self, issues: List[ReadinessIssue]) -> None:
        problems = validate_profile_self(self._profile)
        if not problems:
            return
        for msg in problems:
            issues.append(ReadinessIssue(
                gate=ReadinessGate.PROFILE_CHECK,
                severity="error",
                message=f"profile inválido: {msg}",
                detail=None,
            ))

    def _check_provider_status(self, issues: List[ReadinessIssue]) -> None:
        try:
            entry = self._registry.get(_DEMO_PROVIDER_ID)
        except KeyError:
            issues.append(ReadinessIssue(
                gate=ReadinessGate.PROVIDER_STATUS,
                severity="error",
                message=(
                    f"provider '{_DEMO_PROVIDER_ID}' não registrado "
                    f"no ProviderRegistry"
                ),
                detail=None,
            ))
            return
        # FASE 19: aceita EXATAMENTE OPT_IN. Sem "OPT_IN ou superior".
        if entry.status is not ProviderStatus.OPT_IN:
            issues.append(ReadinessIssue(
                gate=ReadinessGate.PROVIDER_STATUS,
                severity="error",
                message=(
                    f"provider '{_DEMO_PROVIDER_ID}' está em status "
                    f"'{entry.status.value}' — readiness exige "
                    f"exatamente OPT_IN"
                ),
                detail=_sanitize_for_log(entry.reason),
            ))

    def _check_risk_snapshot(self, issues: List[ReadinessIssue]) -> None:
        overrides = dict(self._profile.risk_config_overrides)
        has_overrides = bool(overrides)
        snapshot = self._risk_snapshot

        if snapshot is None:
            if has_overrides:
                issues.append(ReadinessIssue(
                    gate=ReadinessGate.RISK_CONFIG_SNAPSHOT,
                    severity="error",
                    message=(
                        "profile.risk_config_overrides não-vazio mas "
                        "AppliedRiskConfigSnapshot ausente"
                    ),
                    detail=(
                        "Caller deve produzir snapshot via "
                        "apply_profile_overrides_with_gate (FASE 18) "
                        "antes da readiness."
                    ),
                ))
            else:
                issues.append(ReadinessIssue(
                    gate=ReadinessGate.RISK_CONFIG_SNAPSHOT,
                    severity="info",
                    message=(
                        "sem AppliedRiskConfigSnapshot (overrides vazios) "
                        "— RiskConfig do .env será usado em runtime"
                    ),
                    detail=None,
                ))
            return

        # snapshot presente
        if has_overrides and not snapshot.was_applied:
            issues.append(ReadinessIssue(
                gate=ReadinessGate.RISK_CONFIG_SNAPSHOT,
                severity="error",
                message=(
                    "AppliedRiskConfigSnapshot é preview (was_applied=False) "
                    "mas profile possui risk_config_overrides não-vazios"
                ),
                detail=(
                    "Preview NÃO é configuração aplicada. Use "
                    "apply_profile_overrides_with_gate com gate humano "
                    "explícito antes da readiness."
                ),
            ))
        elif not has_overrides and not snapshot.was_applied:
            issues.append(ReadinessIssue(
                gate=ReadinessGate.RISK_CONFIG_SNAPSHOT,
                severity="info",
                message=(
                    "snapshot é preview (was_applied=False); sem overrides "
                    "no profile, runtime continua com RiskConfig do .env"
                ),
                detail=None,
            ))

        # issues do snapshot (apenas errors bloqueiam)
        snap_errors = [
            i for i in snapshot.issues_at_apply if i.severity == "error"
        ]
        for snap_err in snap_errors:
            key_part = f"[{snap_err.key}] " if snap_err.key else ""
            issues.append(ReadinessIssue(
                gate=ReadinessGate.RISK_CONFIG_SNAPSHOT,
                severity="error",
                message=(
                    f"AppliedRiskConfigSnapshot contém issue de error: "
                    f"{key_part}{snap_err.message}"
                ),
                detail=None,
            ))

    def _check_last_safety_flags(self, issues: List[ReadinessIssue]) -> None:
        flags = self._last_safety_flags
        if flags is None:
            # Ausência de flags anteriores é aceitável — não bloqueia.
            return

        if flags.safety_halt_recommended:
            issues.append(ReadinessIssue(
                gate=ReadinessGate.LAST_FLAGS_CLEAN,
                severity="error",
                message=(
                    "última safety flag indica safety_halt_recommended=True"
                ),
                detail=_sanitize_for_log(flags.reason),
            ))

        if flags.manual_review_required:
            issues.append(ReadinessIssue(
                gate=ReadinessGate.LAST_FLAGS_CLEAN,
                severity="error",
                message=(
                    "última safety flag indica manual_review_required=True"
                ),
                detail=_sanitize_for_log(flags.reason),
            ))

        confidence = flags.reconciliation_confidence
        if confidence == "triangulated":
            if self._profile.require_manual_ack_on_triangulation:
                issues.append(ReadinessIssue(
                    gate=ReadinessGate.LAST_FLAGS_CLEAN,
                    severity="error",
                    message=(
                        "última safety flag indica reconciliation_confidence="
                        "'triangulated' e profile exige ack manual em "
                        "triangulação"
                    ),
                    detail=(
                        "Triangulação NÃO é FILL canônico. Exige ack humano "
                        "antes da próxima sessão."
                    ),
                ))
            else:
                issues.append(ReadinessIssue(
                    gate=ReadinessGate.LAST_FLAGS_CLEAN,
                    severity="warning",
                    message=(
                        "reconciliation_confidence='triangulated' aceito "
                        "pelo profile (require_manual_ack_on_triangulation="
                        "False) — atenção: NÃO é fill canônico"
                    ),
                    detail=None,
                ))
        elif confidence == "none":
            issues.append(ReadinessIssue(
                gate=ReadinessGate.LAST_FLAGS_CLEAN,
                severity="error",
                message=(
                    "última safety flag indica reconciliation_confidence="
                    "'none' (reconciliação falhou ou ausente)"
                ),
                detail=_sanitize_for_log(flags.reason),
            ))

    def _check_preflight_local(self, issues: List[ReadinessIssue]) -> None:
        if not isinstance(self._symbol, str) or not self._symbol.strip():
            issues.append(ReadinessIssue(
                gate=ReadinessGate.PREFLIGHT_LOCAL,
                severity="error",
                message="symbol vazio ou inválido",
                detail=None,
            ))
        if self._capital <= 0:
            issues.append(ReadinessIssue(
                gate=ReadinessGate.PREFLIGHT_LOCAL,
                severity="error",
                message=f"capital inválido: {self._capital}",
                detail="capital deve ser > 0.",
            ))
        # Posição/ordem aberta declarada: bloqueia readiness.
        if self._has_open_position:
            issues.append(ReadinessIssue(
                gate=ReadinessGate.PREFLIGHT_LOCAL,
                severity="error",
                message="posição aberta declarada",
                detail=(
                    "Demo gated exige preflight com posição zerada. "
                    "Feche posições residuais antes."
                ),
            ))
        if self._has_open_orders:
            issues.append(ReadinessIssue(
                gate=ReadinessGate.PREFLIGHT_LOCAL,
                severity="error",
                message="ordem aberta declarada",
                detail=(
                    "Demo gated exige preflight sem ordens pendentes. "
                    "Cancele ordens residuais antes."
                ),
            ))
        # Cross-check com profile.allowed_symbols (se restrito)
        if (
            isinstance(self._symbol, str)
            and self._symbol.strip()
            and self._profile.allowed_symbols
            and self._symbol not in self._profile.allowed_symbols
        ):
            issues.append(ReadinessIssue(
                gate=ReadinessGate.PREFLIGHT_LOCAL,
                severity="error",
                message=(
                    f"symbol '{self._symbol}' não está em "
                    f"profile.allowed_symbols"
                ),
                detail=None,
            ))

    # -----------------------------------------------------------------
    # Audit
    # -----------------------------------------------------------------

    def _audit_report(self, report: DemoSessionReadinessReport) -> None:
        """Emite linha estruturada sanitizada."""
        _audit.info(
            "DEMO_SESSION_READINESS_CHECKED | "
            f"profile={_sanitize_for_log(report.profile_name)} | "
            f"symbol={_sanitize_for_log(report.symbol)} | "
            f"provider={report.provider_id} | "
            f"ready={report.is_ready_for_gated_demo} | "
            f"blocks={report.total_blocks} | "
            f"warnings={report.total_warnings} | "
            f"info={report.total_info}"
        )
