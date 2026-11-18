"""
ChallengeEnduranceStage + STAGE_DEFINITIONS (FASE 23)
=========================================================
Estagios explicitos de endurance. Paper executavel; demo planned-only
nesta fase. Cada estagio define:
    - duration_minutes (declarado);
    - mode_allowed ("paper" | "demo_planned");
    - provider_allowed ("paper" | "bybit_demo_linear");
    - can_call_external_api (False em paper);
    - can_send_external_order (False em paper);
    - required_previous_stage (ordem de progressao).

Provider-agnostic. Apenas dados imutaveis aqui — sem importar runner,
client, executor ou rede.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional, Tuple
from types import MappingProxyType


class ChallengeEnduranceStage(str, Enum):
    """Estagios do endurance progressivo.

    Valores sao contrato estavel — nao renomear sem nova fase de quebra.
    """
    PAPER_30_MIN = "paper_30_min"
    PAPER_60_MIN = "paper_60_min"
    PAPER_1_DAY = "paper_1_day"
    DEMO_30_MIN_PLANNED = "demo_30_min_planned"
    DEMO_60_MIN_PLANNED = "demo_60_min_planned"
    DEMO_1_DAY_PLANNED = "demo_1_day_planned"


@dataclass(frozen=True)
class _StageDef:
    duration_minutes: int
    mode_allowed: str            # "paper" | "demo_planned"
    provider_allowed: str        # "paper" | "bybit_demo_linear"
    can_call_external_api: bool
    can_send_external_order: bool
    required_previous_stage: Optional[ChallengeEnduranceStage] = None

    def to_dict(self) -> dict:
        return {
            "duration_minutes": self.duration_minutes,
            "mode_allowed": self.mode_allowed,
            "provider_allowed": self.provider_allowed,
            "can_call_external_api": self.can_call_external_api,
            "can_send_external_order": self.can_send_external_order,
            "required_previous_stage": (
                self.required_previous_stage.value
                if self.required_previous_stage is not None else None
            ),
        }


_STAGE_DEFINITIONS: Mapping[ChallengeEnduranceStage, _StageDef] = MappingProxyType({
    ChallengeEnduranceStage.PAPER_30_MIN: _StageDef(
        duration_minutes=30,
        mode_allowed="paper",
        provider_allowed="paper",
        can_call_external_api=False,
        can_send_external_order=False,
        required_previous_stage=None,
    ),
    ChallengeEnduranceStage.PAPER_60_MIN: _StageDef(
        duration_minutes=60,
        mode_allowed="paper",
        provider_allowed="paper",
        can_call_external_api=False,
        can_send_external_order=False,
        required_previous_stage=ChallengeEnduranceStage.PAPER_30_MIN,
    ),
    ChallengeEnduranceStage.PAPER_1_DAY: _StageDef(
        duration_minutes=24 * 60,
        mode_allowed="paper",
        provider_allowed="paper",
        can_call_external_api=False,
        can_send_external_order=False,
        required_previous_stage=ChallengeEnduranceStage.PAPER_60_MIN,
    ),
    ChallengeEnduranceStage.DEMO_30_MIN_PLANNED: _StageDef(
        duration_minutes=30,
        mode_allowed="demo_planned",
        provider_allowed="bybit_demo_linear",
        can_call_external_api=False,  # PLANNED-ONLY nesta fase
        can_send_external_order=False,
        required_previous_stage=ChallengeEnduranceStage.PAPER_1_DAY,
    ),
    ChallengeEnduranceStage.DEMO_60_MIN_PLANNED: _StageDef(
        duration_minutes=60,
        mode_allowed="demo_planned",
        provider_allowed="bybit_demo_linear",
        can_call_external_api=False,
        can_send_external_order=False,
        required_previous_stage=ChallengeEnduranceStage.DEMO_30_MIN_PLANNED,
    ),
    ChallengeEnduranceStage.DEMO_1_DAY_PLANNED: _StageDef(
        duration_minutes=24 * 60,
        mode_allowed="demo_planned",
        provider_allowed="bybit_demo_linear",
        can_call_external_api=False,
        can_send_external_order=False,
        required_previous_stage=ChallengeEnduranceStage.DEMO_60_MIN_PLANNED,
    ),
})


def get_stage_definition(stage: ChallengeEnduranceStage) -> _StageDef:
    """Retorna a definicao imutavel do estagio."""
    if not isinstance(stage, ChallengeEnduranceStage):
        raise TypeError(
            f"stage deve ser ChallengeEnduranceStage; "
            f"recebido {type(stage).__name__}"
        )
    return _STAGE_DEFINITIONS[stage]


def is_paper_stage(stage: ChallengeEnduranceStage) -> bool:
    """True se o estagio eh paper-only executavel nesta fase."""
    return get_stage_definition(stage).mode_allowed == "paper"


def is_demo_planned_stage(stage: ChallengeEnduranceStage) -> bool:
    """True se o estagio eh demo PLANNED-ONLY (nao executavel na FASE 23)."""
    return get_stage_definition(stage).mode_allowed == "demo_planned"


# Ordem cronologica para progressao.
STAGE_ORDER: Tuple[ChallengeEnduranceStage, ...] = (
    ChallengeEnduranceStage.PAPER_30_MIN,
    ChallengeEnduranceStage.PAPER_60_MIN,
    ChallengeEnduranceStage.PAPER_1_DAY,
    ChallengeEnduranceStage.DEMO_30_MIN_PLANNED,
    ChallengeEnduranceStage.DEMO_60_MIN_PLANNED,
    ChallengeEnduranceStage.DEMO_1_DAY_PLANNED,
)


def next_recommended_stage(
    current: ChallengeEnduranceStage,
) -> Optional[ChallengeEnduranceStage]:
    """Proximo estagio na ordem cronologica; None se ja for ultimo."""
    idx = STAGE_ORDER.index(current)
    if idx + 1 >= len(STAGE_ORDER):
        return None
    return STAGE_ORDER[idx + 1]
