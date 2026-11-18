"""
DemoEnduranceStage (FASE 26)
================================
Estagios de demo endurance. Nesta fase, APENAS DEMO_30_MIN existe.
DEMO_60_MIN e DEMO_1_DAY ficam para fases futuras (FASE 28+) e nao
sao planejados aqui.

⚠️  Este enum eh INDEPENDENTE de ChallengeEnduranceStage.
    O path challenge_endurance/ continua tratando DEMO_* como
    planned-only e segue exclusivamente o runbook FASE 22 para
    execucao real.
"""

from __future__ import annotations

from enum import Enum


class DemoEnduranceStage(str, Enum):
    """Stage de demo endurance suportado nesta fase.

    DEMO_30_MIN
        Sessao demo controlada de no maximo 30 minutos com max_orders=1.
        Nesta FASE 26 eh apenas planned/dry-run (sem execucao real demo,
        sem chamada de rede).
    """
    DEMO_30_MIN = "demo_30_min"


_VALID_STAGES = (DemoEnduranceStage.DEMO_30_MIN,)


def is_valid_stage(stage) -> bool:
    """True se `stage` for instancia ou valor valido."""
    if isinstance(stage, DemoEnduranceStage):
        return stage in _VALID_STAGES
    if isinstance(stage, str):
        return stage in {s.value for s in _VALID_STAGES}
    return False
