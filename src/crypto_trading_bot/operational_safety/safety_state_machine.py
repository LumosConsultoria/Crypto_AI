"""
SafetyStateMachine — Orquestrador consultivo de safety (FASE 16)
==================================================================
⚠️  AVISOS OBRIGATÓRIOS:
    - Módulo PROVIDER-AGNOSTIC. NÃO importa BybitClient, BybitDemoExecutor,
      DemoExecutionResult, RiskEngine, BotEngine, httpx ou providers.
    - Esta máquina é CONSULTIVA: expõe propriedades read-only
      (can_open_new_position, can_modify_positions, can_read_state,
      requires_operator_ack) que CALLERS devem checar antes de operar.
      Nesta FASE 16 não há runner consumindo — apenas a estrutura.
    - Transições inválidas levantam InvalidSafetyTransition. Nada é
      "silenciado".
    - Audit emite linha estruturada por transição. Token de
      acknowledge passa por sanitização defensiva (truncado + redact)
      antes do log.

TRANSIÇÕES VÁLIDAS:
    NORMAL                      → MANUAL_REVIEW_REQUIRED   (mark_manual_review)
    NORMAL                      → SAFETY_HALT_RECOMMENDED  (recommend_safety_halt)
    SAFETY_HALT_RECOMMENDED     → SAFETY_HALT_ACTIVE       (activate_safety_halt)
    MANUAL_REVIEW_REQUIRED      → OPERATOR_ACKNOWLEDGED    (acknowledge)
    SAFETY_HALT_ACTIVE          → OPERATOR_ACKNOWLEDGED    (acknowledge)
    OPERATOR_ACKNOWLEDGED       → RESOLVED                 (resolve)
    RESOLVED                    → NORMAL                   (reset)

Qualquer outra transição → InvalidSafetyTransition.

INTEGRAÇÃO GENÉRICA (helper):
    from_safety_flags(flags) é um helper estático que ACEITA um objeto
    com os campos abaixo (duck-typing — qualquer dataclass/dict-like serve)
    e retorna a transição apropriada SEM acoplar a executores reais:
        - manual_review_required: bool
        - safety_halt_recommended: bool
        - reconciliation_confidence: str (opcional)
        - reason: str (opcional)
        - metadata: Mapping (opcional)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Mapping, Optional, Tuple

from crypto_trading_bot.logging_system.logger import get_audit_logger, get_logger
from crypto_trading_bot.operational_safety.safety_state import (
    InvalidSafetyTransition,
    SafetyEvent,
    SafetyState,
)

_logger = get_logger(__name__)
_audit = get_audit_logger(__name__)


# ---------------------------------------------------------------------------
# Transições válidas (declarativas para fácil auditoria)
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: dict[SafetyState, Tuple[SafetyState, ...]] = {
    SafetyState.NORMAL: (
        SafetyState.MANUAL_REVIEW_REQUIRED,
        SafetyState.SAFETY_HALT_RECOMMENDED,
    ),
    SafetyState.MANUAL_REVIEW_REQUIRED: (
        SafetyState.OPERATOR_ACKNOWLEDGED,
    ),
    SafetyState.SAFETY_HALT_RECOMMENDED: (
        SafetyState.SAFETY_HALT_ACTIVE,
    ),
    SafetyState.SAFETY_HALT_ACTIVE: (
        SafetyState.OPERATOR_ACKNOWLEDGED,
    ),
    SafetyState.OPERATOR_ACKNOWLEDGED: (
        SafetyState.RESOLVED,
    ),
    SafetyState.RESOLVED: (
        SafetyState.NORMAL,
    ),
}


# Estados que bloqueiam abertura de nova posição.
_BLOCKS_NEW_POSITION: frozenset = frozenset({
    SafetyState.MANUAL_REVIEW_REQUIRED,
    SafetyState.SAFETY_HALT_RECOMMENDED,
    SafetyState.SAFETY_HALT_ACTIVE,
    SafetyState.OPERATOR_ACKNOWLEDGED,   # ack não basta; precisa resolve+reset
})

# Estados que bloqueiam modificação de posição.
_BLOCKS_MODIFY_POSITION: frozenset = frozenset({
    SafetyState.SAFETY_HALT_ACTIVE,
})

# Estados que exigem ack humano para sair.
_REQUIRES_ACK: frozenset = frozenset({
    SafetyState.MANUAL_REVIEW_REQUIRED,
    SafetyState.SAFETY_HALT_ACTIVE,
})


# ---------------------------------------------------------------------------
# Sanitização defensiva de tokens/notes
# ---------------------------------------------------------------------------

def _sanitize_token(token: str) -> str:
    """
    Token de ack identificando o operador (ex.: e-mail).
    NÃO é credencial, mas tratamos defensivamente:
      - trunca para até 8 chars + "..."
      - rejeita tokens claramente parecidos com api_key/secret/bearer.
    """
    if not isinstance(token, str) or not token.strip():
        return "<empty>"
    lower = token.lower()
    suspicious = ("api_key", "api_secret", "bearer ", "x-bapi", "sign=")
    if any(s in lower for s in suspicious):
        return "<redacted_suspicious_token>"
    return token[:8] + ("..." if len(token) > 8 else "")


def _sanitize_notes(notes: str) -> str:
    """Notes de operator: trunca em 200 chars, remove possíveis secrets."""
    if not isinstance(notes, str):
        return ""
    truncated = notes[:200]
    lower = truncated.lower()
    suspicious = ("api_key", "api_secret", "bearer ", "x-bapi-sign", "authorization:")
    if any(s in lower for s in suspicious):
        return "<redacted_suspicious_notes>"
    return truncated


# ---------------------------------------------------------------------------
# SafetyStateMachine
# ---------------------------------------------------------------------------

class SafetyStateMachine:
    """
    Máquina de estado consultiva. Default inicia em NORMAL.

    Mantém histórico imutável de eventos (`history` → tuple).
    Emite linha de audit estruturada por transição.

    Read-only properties para futuros runners:
        can_open_new_position  — False em estados ambíguos.
        can_modify_positions   — False em SAFETY_HALT_ACTIVE.
        can_read_state         — sempre True.
        requires_operator_ack  — True em MANUAL_REVIEW_REQUIRED e
                                 SAFETY_HALT_ACTIVE.
    """

    def __init__(self, *, initial_state: SafetyState = SafetyState.NORMAL) -> None:
        if not isinstance(initial_state, SafetyState):
            raise TypeError(
                "initial_state deve ser SafetyState; "
                f"recebido {type(initial_state).__name__}"
            )
        self._state: SafetyState = initial_state
        self._history: List[SafetyEvent] = []

    # -----------------------------------------------------------------------
    # Properties read-only
    # -----------------------------------------------------------------------

    @property
    def state(self) -> SafetyState:
        return self._state

    @property
    def history(self) -> Tuple[SafetyEvent, ...]:
        return tuple(self._history)

    @property
    def can_open_new_position(self) -> bool:
        return self._state not in _BLOCKS_NEW_POSITION

    @property
    def can_modify_positions(self) -> bool:
        return self._state not in _BLOCKS_MODIFY_POSITION

    @property
    def can_read_state(self) -> bool:
        # Leitura/diagnóstico SEMPRE permitido.
        return True

    @property
    def requires_operator_ack(self) -> bool:
        return self._state in _REQUIRES_ACK

    # -----------------------------------------------------------------------
    # Transições explícitas
    # -----------------------------------------------------------------------

    def mark_manual_review_required(
        self, *, reason: str, metadata: Optional[Mapping[str, Any]] = None,
    ) -> SafetyEvent:
        """Marca incidente que exige revisão humana (ex.: triangulação)."""
        return self._transition(
            event_type="MANUAL_REVIEW_REQUIRED",
            target=SafetyState.MANUAL_REVIEW_REQUIRED,
            reason=reason,
            metadata=metadata,
        )

    def recommend_safety_halt(
        self, *, reason: str, metadata: Optional[Mapping[str, Any]] = None,
    ) -> SafetyEvent:
        """Sistema sugere parada; ainda não é ativa."""
        return self._transition(
            event_type="SAFETY_HALT_RECOMMENDED",
            target=SafetyState.SAFETY_HALT_RECOMMENDED,
            reason=reason,
            metadata=metadata,
        )

    def activate_safety_halt(
        self, *, reason: str, metadata: Optional[Mapping[str, Any]] = None,
    ) -> SafetyEvent:
        """Ativa halt explicitamente. Bloqueia abertura E modificação."""
        return self._transition(
            event_type="SAFETY_HALT_TRIGGERED",
            target=SafetyState.SAFETY_HALT_ACTIVE,
            reason=reason,
            metadata=metadata,
        )

    def acknowledge(
        self, *, operator_ack_token: str, notes: str = "",
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> SafetyEvent:
        """
        Operador confirma estar ciente. NÃO volta para NORMAL.

        Args:
            operator_ack_token: identificação do operador (não-vazio).
                                Não é credencial, mas é sanitizado no log.
            notes: notas livres do operador (truncadas/sanitizadas no log).
        """
        if not isinstance(operator_ack_token, str) or not operator_ack_token.strip():
            raise ValueError("operator_ack_token deve ser string não-vazia")
        sanitized_token = _sanitize_token(operator_ack_token)
        sanitized_notes = _sanitize_notes(notes)
        md = dict(metadata or {})
        md.setdefault("ack_token_sanitized", sanitized_token)
        md.setdefault("ack_notes_sanitized", sanitized_notes)
        return self._transition(
            event_type="OPERATOR_ACKNOWLEDGED",
            target=SafetyState.OPERATOR_ACKNOWLEDGED,
            reason=f"operator ack ({sanitized_token})",
            metadata=md,
        )

    def resolve(
        self, *, resolution_notes: str = "",
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> SafetyEvent:
        """Operador declara o incidente resolvido. Próximo passo: reset()."""
        sanitized_notes = _sanitize_notes(resolution_notes)
        md = dict(metadata or {})
        md.setdefault("resolution_notes_sanitized", sanitized_notes)
        return self._transition(
            event_type="SAFETY_STATE_RESOLVED",
            target=SafetyState.RESOLVED,
            reason="incidente resolvido pelo operador",
            metadata=md,
        )

    def reset(
        self, *, metadata: Optional[Mapping[str, Any]] = None,
    ) -> SafetyEvent:
        """Retorna ao estado NORMAL após RESOLVED."""
        return self._transition(
            event_type="SAFETY_STATE_RESET",
            target=SafetyState.NORMAL,
            reason="reset para NORMAL",
            metadata=metadata,
        )

    # -----------------------------------------------------------------------
    # Helper genérico — duck-typed (sem acoplar a executores)
    # -----------------------------------------------------------------------

    def from_safety_flags(self, flags: Any) -> Optional[SafetyEvent]:
        """
        Avalia um objeto com campos genéricos e transiciona para o estado
        seguro apropriado, se houver gatilho.

        NÃO importa nem depende de BybitDemoExecutor/DemoExecutionResult.
        Aceita QUALQUER objeto (duck-typed) com:
            - manual_review_required: bool (opcional, default False)
            - safety_halt_recommended: bool (opcional, default False)
            - reconciliation_confidence: str (opcional)
            - reason: str (opcional)
            - metadata: Mapping (opcional)

        Regras:
            - safety_halt_recommended=True → recommend_safety_halt (se NORMAL).
            - manual_review_required=True AND safety_halt_recommended=False →
              mark_manual_review_required.
            - manual_review_required=True AND safety_halt_recommended=True →
              recommend_safety_halt (gravidade maior); metadata registra
              que também havia manual_review pending.
            - Sem flags relevantes → retorna None (sem transição).

        Returns:
            SafetyEvent emitido, ou None se nada transicionou.
        """
        manual = bool(getattr(flags, "manual_review_required", False))
        halt = bool(getattr(flags, "safety_halt_recommended", False))
        if not manual and not halt:
            return None

        # Só transiciona se estado atual aceitar
        if self._state is not SafetyState.NORMAL:
            _logger.debug(
                f"from_safety_flags: estado atual {self._state.value} "
                f"não aceita transição automática"
            )
            return None

        reason = str(getattr(flags, "reason", "") or "").strip() or "safety flags"
        confidence = getattr(flags, "reconciliation_confidence", None)
        raw_metadata = getattr(flags, "metadata", None) or {}
        md: dict[str, Any] = {}
        if isinstance(raw_metadata, Mapping):
            md.update(dict(raw_metadata))
        if confidence is not None:
            md["reconciliation_confidence"] = str(confidence)
        md["manual_review_required"] = manual
        md["safety_halt_recommended"] = halt

        if halt:
            # Gravidade maior; metadata registra que manual também pendeu.
            return self.recommend_safety_halt(reason=reason, metadata=md)
        # Apenas manual review pendente
        return self.mark_manual_review_required(reason=reason, metadata=md)

    # -----------------------------------------------------------------------
    # Implementação interna
    # -----------------------------------------------------------------------

    def _transition(
        self,
        *,
        event_type: str,
        target: SafetyState,
        reason: str,
        metadata: Optional[Mapping[str, Any]],
    ) -> SafetyEvent:
        allowed = _VALID_TRANSITIONS.get(self._state, ())
        if target not in allowed:
            raise InvalidSafetyTransition(
                f"Transição inválida {self._state.value} → {target.value}. "
                f"Estado atual permite apenas: "
                f"{[s.value for s in allowed] or 'nada'}."
            )

        event = SafetyEvent(
            event_type=event_type,
            from_state=self._state,
            to_state=target,
            reason=reason or "",
            triggered_at=datetime.now(timezone.utc),
            metadata=metadata or {},
        )
        self._state = target
        self._history.append(event)
        self._audit_event(event)
        return event

    @staticmethod
    def _audit_event(event: SafetyEvent) -> None:
        """Emite linha estruturada de audit (sem secrets)."""
        _audit.info(
            f"SAFETY_STATE_TRANSITION | "
            f"event_type={event.event_type} | "
            f"from={event.from_state.value} | "
            f"to={event.to_state.value} | "
            f"reason='{event.reason}' | "
            f"triggered_at={event.triggered_at.isoformat()}"
        )
