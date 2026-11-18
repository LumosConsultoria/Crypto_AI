"""
Context Risk Composition (FASE 47, secao 7.3) — multiplicadores IA/Polymarket
==============================================================================
Influencia QUANTITATIVA do contexto sobre o risco. So REDUZ (<=1,0); nunca
aumenta (consistente com does_not_override + RiskEngine soberano).

- IA: favoravel=1,00; neutra/incerta=0,50; contraria=0,00 (veto).
- Polymarket: favoravel=1,00; risco_elevado=0,75; contrario=0,00 (veto).
- risco_final = risco_base × mult_IA × mult_Polymarket (risco_base max 0,5%).

Falha de contexto (modo E):
- IA indisponivel/erro tecnico: NUNCA 1,00 (favoravel silencioso) — reduz
  (0,50) ou veta (0,00) conforme `failure_policy`.
- Polymarket erro tecnico: idem.
- Ausencia LEGITIMA de mercado Polymarket relevante: `not_applicable` =>
  mult=1,00 (sem efeito), marcado distinto de falha.
Tudo registravel no Decision Trace (stance + multiplicador + estado).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from crypto_trading_bot.ai_assistant.advisor_protocol import (
    AIAdvice,
    AIAdviceStatus,
    AISuggestedAction,
)

# Multiplicadores TRAVADOS (FASE 47, revisao do operador).
AI_FAVORABLE, AI_NEUTRAL, AI_CONTRARY = 1.00, 0.50, 0.00
POLY_FAVORABLE, POLY_ELEVATED, POLY_CONTRARY = 1.00, 0.75, 0.00

# Estados de contexto registrados no trace.
AI_STATES = ("favorable", "neutral", "contrary", "unavailable", "error")
POLY_STATES = ("favorable", "elevated_risk", "contrary",
               "not_applicable", "unavailable", "error")


def ai_multiplier(advice: Optional[AIAdvice], *,
                  available: bool = True, error: bool = False,
                  failure_policy: str = "reduce") -> Tuple[str, float]:
    """(estado, multiplicador) da IA.

    favoravel(1,00) = sem objecao (NEUTRAL + PROCEED). contraria(0,00) = VETO.
    neutra/incerta(0,50) = CAUTION / MANUAL_REVIEW / acao != PROCEED.
    Indisponivel/erro => reduce(0,50) ou veto(0,00) — NUNCA 1,00.
    """
    if error:
        return "error", (AI_CONTRARY if failure_policy == "veto"
                         else AI_NEUTRAL)
    if not available or advice is None:
        return "unavailable", (AI_CONTRARY if failure_policy == "veto"
                               else AI_NEUTRAL)
    if advice.status == AIAdviceStatus.VETO:
        return "contrary", AI_CONTRARY
    if (advice.status == AIAdviceStatus.NEUTRAL
            and advice.suggested_action == AISuggestedAction.PROCEED):
        return "favorable", AI_FAVORABLE
    # CAUTION, MANUAL_REVIEW, ou acao WAIT/RESEARCH_REQUIRED
    return "neutral", AI_NEUTRAL


def polymarket_multiplier(stance: str, *,
                          failure_policy: str = "reduce") -> Tuple[str, float]:
    """(estado, multiplicador) do Polymarket.

    favoravel=1,00; risco_elevado=0,75; contrario=0,00; not_applicable=1,00
    (sem efeito, distinto de falha); unavailable/error => reduce/veto.
    """
    s = (stance or "not_applicable").lower()
    if s == "favorable":
        return "favorable", POLY_FAVORABLE
    if s in ("elevated_risk", "elevated", "risk_elevated"):
        return "elevated_risk", POLY_ELEVATED
    if s == "contrary":
        return "contrary", POLY_CONTRARY
    if s == "not_applicable":
        return "not_applicable", 1.00          # sem efeito (nao e falha)
    # unavailable / error
    state = "error" if s == "error" else "unavailable"
    return state, (POLY_CONTRARY if failure_policy == "veto" else AI_NEUTRAL)


@dataclass(frozen=True)
class ContextDecision:
    risk_base_usd: float
    ai_state: str
    ai_multiplier: float
    poly_state: str
    poly_multiplier: float
    risk_final_usd: float
    decision: str            # kept | reduced | vetoed

    def to_dict(self) -> dict:
        return {
            "risk_base_usd": round(self.risk_base_usd, 4),
            "ai_state": self.ai_state,
            "ai_multiplier": self.ai_multiplier,
            "polymarket_state": self.poly_state,
            "polymarket_multiplier": self.poly_multiplier,
            "risk_final_usd": round(self.risk_final_usd, 4),
            "decision": self.decision,
            "note": "risco_final = risco_base × mult_IA × mult_Polymarket; "
                    "so reduz (<=1,0); RiskEngine soberano nunca excedido.",
        }


def compose_risk(
    risk_base_usd: float, *,
    advice: Optional[AIAdvice] = None,
    ai_available: bool = True, ai_error: bool = False,
    poly_stance: str = "not_applicable", poly_error: bool = False,
    failure_policy: str = "reduce",
    use_ai: bool = True, use_polymarket: bool = True,
) -> ContextDecision:
    """Compoe o risco final aplicando os multiplicadores de IA e Polymarket.

    `use_ai`/`use_polymarket`: False => multiplicador neutro 1,00 (config da
    ablacao: A/B sem contexto; C so Polymarket; D so IA; E completo).
    """
    if use_ai:
        ai_state, ai_mult = ai_multiplier(
            advice, available=ai_available, error=ai_error,
            failure_policy=failure_policy)
    else:
        ai_state, ai_mult = "disabled", 1.00
    if use_polymarket:
        ps = "error" if poly_error else poly_stance
        poly_state, poly_mult = polymarket_multiplier(
            ps, failure_policy=failure_policy)
    else:
        poly_state, poly_mult = "disabled", 1.00

    risk_final = risk_base_usd * ai_mult * poly_mult
    if risk_final <= 0:
        decision = "vetoed"
    elif risk_final < risk_base_usd - 1e-9:
        decision = "reduced"
    else:
        decision = "kept"
    return ContextDecision(
        risk_base_usd=risk_base_usd, ai_state=ai_state, ai_multiplier=ai_mult,
        poly_state=poly_state, poly_multiplier=poly_mult,
        risk_final_usd=risk_final, decision=decision)


# ----------------------------- metricas de impacto -------------------------

def impact_metrics(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Agrega o impacto do contexto vs baseline (sem contexto).

    Cada record: {decision: kept|reduced|vetoed, baseline_pnl_usd: float,
    scale: float in [0,1]}. scale = risk_final/risk_base (1 p/ kept, 0 p/
    vetoed). PnL evitado = perda que NAO ocorreu (corte de risco em trade
    perdedor); PnL perdido = ganho que NAO ocorreu (corte em trade vencedor).
    """
    kept = reduced = vetoed = 0
    pnl_avoided = 0.0      # >0: bom (perdas evitadas)
    pnl_lost = 0.0         # >0: ruim (ganhos cortados)
    for r in records:
        dec = r.get("decision")
        base = float(r.get("baseline_pnl_usd", 0.0) or 0.0)
        scale = float(r.get("scale", 1.0) or 0.0)
        if dec == "kept":
            kept += 1
            continue
        if dec == "reduced":
            reduced += 1
        elif dec == "vetoed":
            vetoed += 1
            scale = 0.0
        # fracao do PnL que deixou de ocorrer
        removed = base * (1.0 - scale)
        if base < 0:
            pnl_avoided += -removed      # removeu parte de uma perda => bom
        elif base > 0:
            pnl_lost += removed          # removeu parte de um ganho => ruim
    return {
        "trades_total": len(records),
        "trades_kept": kept,
        "trades_reduced": reduced,
        "trades_vetoed": vetoed,
        "pnl_avoided_usd": round(pnl_avoided, 4),
        "pnl_lost_usd": round(pnl_lost, 4),
        "net_context_benefit_usd": round(pnl_avoided - pnl_lost, 4),
    }


__all__ = [
    "AI_FAVORABLE", "AI_NEUTRAL", "AI_CONTRARY",
    "POLY_FAVORABLE", "POLY_ELEVATED", "POLY_CONTRARY",
    "ContextDecision", "ai_multiplier", "polymarket_multiplier",
    "compose_risk", "impact_metrics",
]
