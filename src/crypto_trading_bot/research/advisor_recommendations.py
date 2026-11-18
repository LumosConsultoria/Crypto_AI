"""
Advisor Recommendations (FASE 36 Bloco E)
==========================================
Recomendacoes de parametros em 3 perfis (conservador/moderado/
arrojado) com regime de mercado, lifecycle de aceite AUDITAVEL e
regras invioalveis:

⚠️  NUNCA roda automaticamente (operador aciona via CLI).
⚠️  NUNCA aplica mudanca: aceite apenas REGISTRA; runtime continua
    usando configuracao explicitamente informada.
⚠️  Aceite exige: cap de alteracao percentual INFORMADO pelo operador
    (Q9 sem default — ausente => bloqueia), evidencia de backtest
    (needs_backtest) e walk-forward quando exigido, operator_token e
    audit trail old/new.
⚠️  Anti-overfitting: reusa in/out-of-sample + detect_overfitting da
    FASE 33; recomendacao com overfitting NUNCA e elegivel a aceite.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Regime de mercado (deterministico)
# ---------------------------------------------------------------------------

def detect_market_regime(candles: Sequence) -> dict:
    """Classifica regime: trending_up|trending_down|ranging|
    high_volatility, com evidencias (ATR%, retorno, ruido)."""
    closes = [float(getattr(c, "close", 0.0)) for c in candles]
    highs = [float(getattr(c, "high", 0.0)) for c in candles]
    lows = [float(getattr(c, "low", 0.0)) for c in candles]
    n = len(closes)
    if n < 20:
        return {"regime": "unknown", "evidence": {"n_candles": n}}

    total_return_pct = (closes[-1] / closes[0] - 1.0) * 100.0
    # ATR% aproximado (media de ranges relativos).
    ranges = [
        (h - l) / c for h, l, c in zip(highs, lows, closes) if c > 0
    ]
    atr_pct = (sum(ranges) / len(ranges)) * 100.0 if ranges else 0.0
    # Ruido: reversoes de direcao candle-a-candle.
    flips = sum(
        1 for i in range(2, n)
        if (closes[i] - closes[i - 1]) * (
            closes[i - 1] - closes[i - 2]
        ) < 0
    )
    noise_ratio = flips / max(1, n - 2)

    if atr_pct >= 3.0:
        regime = "high_volatility"
    elif total_return_pct >= 3.0 and noise_ratio < 0.6:
        regime = "trending_up"
    elif total_return_pct <= -3.0 and noise_ratio < 0.6:
        regime = "trending_down"
    else:
        regime = "ranging"
    return {
        "regime": regime,
        "evidence": {
            "n_candles": n,
            "total_return_pct": round(total_return_pct, 4),
            "atr_pct": round(atr_pct, 4),
            "noise_ratio": round(noise_ratio, 4),
        },
    }


# ---------------------------------------------------------------------------
# Recomendacao
# ---------------------------------------------------------------------------

_SUGGESTION_PROFILES = ("conservador", "moderado", "arrojado")
_STATUSES = ("suggested", "accepted", "rejected", "expired")


@dataclass(frozen=True)
class ParameterRecommendation:
    """UMA recomendacao de parametro, em um perfil de sugestao."""

    recommendation_id: str
    strategy: str
    suggestion_profile: str       # conservador|moderado|arrojado
    current_config: Mapping[str, Any]
    suggested_config: Mapping[str, Any]
    reason: str
    evidence: Mapping[str, Any]
    risk_note: str
    expected_impact: str
    regime: str
    needs_backtest: bool = True
    needs_walk_forward: bool = True
    needs_human_approval: bool = True
    overfitting_flag: bool = False
    status: str = "suggested"
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    def __post_init__(self) -> None:
        if self.suggestion_profile not in _SUGGESTION_PROFILES:
            raise ValueError(
                f"suggestion_profile invalido: "
                f"{self.suggestion_profile!r}"
            )
        if self.status not in _STATUSES:
            raise ValueError(f"status invalido: {self.status!r}")
        if self.created_at.tzinfo is None:
            object.__setattr__(
                self, "created_at",
                self.created_at.replace(tzinfo=timezone.utc),
            )

    def to_dict(self) -> dict:
        return {
            "recommendation_id": self.recommendation_id,
            "strategy": self.strategy,
            "suggestion_profile": self.suggestion_profile,
            "current_config": dict(self.current_config),
            "suggested_config": dict(self.suggested_config),
            "reason": self.reason[:300],
            "evidence": dict(self.evidence),
            "risk_note": self.risk_note[:200],
            "expected_impact": self.expected_impact[:200],
            "regime": self.regime,
            "needs_backtest": bool(self.needs_backtest),
            "needs_walk_forward": bool(self.needs_walk_forward),
            "needs_human_approval": True,
            "overfitting_flag": bool(self.overfitting_flag),
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }


def _blend(current: float, suggested: float, factor: float) -> float:
    """Interpola current->suggested pelo fator do perfil."""
    return round(current + (suggested - current) * factor, 6)


_PROFILE_FACTORS = {
    "conservador": 0.33,
    "moderado": 0.66,
    "arrojado": 1.0,
}

_NUMERIC_PARAMS = (
    "rsi_long_overbought", "rsi_short_oversold",
    "pullback_atr_tolerance_k", "stop_atr_multiplier",
    "risk_reward_ratio",
)
_INT_PARAMS = ("ema_fast_period", "ema_slow_period", "rsi_period")


def build_recommendations(
    *,
    advisor_report: Mapping[str, Any],
    regime: Mapping[str, Any],
    current_config: Mapping[str, Any],
    now: Optional[datetime] = None,
) -> List[ParameterRecommendation]:
    """Deriva recomendacoes nos 3 perfis a partir do AdvisorReport.

    conservador: 1/3 do caminho ate a config sugerida pelo ranking;
    moderado: 2/3; arrojado: config sugerida integral. EMAs (inteiros)
    so mudam no arrojado (mudanca estrutural).
    """
    now = now or datetime.now(timezone.utc)
    recs: List[ParameterRecommendation] = []
    strategy = str(advisor_report.get(
        "candidate_strategy", "trend_pullback_bidirectional",
    ))
    regime_name = str(regime.get("regime", "unknown"))

    for side in ("long", "short"):
        block = dict(advisor_report.get(side) or {})
        best_cfg = block.get("recommended_config")
        perf = dict(block.get("performance") or {})
        if not best_cfg:
            continue
        overfit = bool(perf.get("overfitting_warning", False))
        for profile_name, factor in _PROFILE_FACTORS.items():
            suggested: Dict[str, Any] = dict(current_config)
            changed = []
            for param, value in dict(best_cfg).items():
                cur = current_config.get(param)
                if param in _INT_PARAMS:
                    if profile_name == "arrojado" and cur != value:
                        suggested[param] = value
                        changed.append(param)
                elif param in _NUMERIC_PARAMS and isinstance(
                    value, (int, float),
                ) and isinstance(cur, (int, float)):
                    blended = _blend(float(cur), float(value), factor)
                    if blended != cur:
                        suggested[param] = blended
                        changed.append(param)
                elif param in ("enable_long", "enable_short"):
                    suggested[param] = value
            if not changed:
                continue
            recs.append(ParameterRecommendation(
                recommendation_id=(
                    f"rec-{uuid.uuid4().hex[:10]}"
                ),
                strategy=strategy,
                suggestion_profile=profile_name,
                current_config=dict(current_config),
                suggested_config=suggested,
                reason=(
                    f"lado {side}: ranking robusto sugere ajustes em "
                    f"{changed} (PF="
                    f"{perf.get('profit_factor')}, trades="
                    f"{perf.get('total_trades')})"
                ),
                evidence={
                    "side": side,
                    "performance": perf,
                    "changed_params": changed,
                    "blend_factor": factor,
                },
                risk_note=(
                    "Backtest NAO garante performance futura; "
                    "exige validacao adicional."
                ),
                expected_impact=(
                    f"aproximar config do melhor ranking {side} "
                    f"({int(factor * 100)}% do caminho)"
                ),
                regime=regime_name,
                overfitting_flag=overfit,
                created_at=now,
            ))
    return recs


# ---------------------------------------------------------------------------
# Store com lifecycle auditavel
# ---------------------------------------------------------------------------

class RecommendationStore:
    """Persistencia JSON do lifecycle suggested->accepted/rejected/
    expired. Aceite NUNCA aplica config — apenas registra."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        if any(p == ".." for p in self._path.parts):
            raise ValueError("store path contem '..'")
        self._data: Dict[str, Any] = {"recommendations": {},
                                      "audit": []}
        if self._path.is_file():
            try:
                loaded = json.loads(
                    self._path.read_text(encoding="utf-8"),
                )
                if isinstance(loaded, dict):
                    self._data = {
                        "recommendations": dict(
                            loaded.get("recommendations") or {},
                        ),
                        "audit": list(loaded.get("audit") or []),
                    }
            except Exception:  # noqa: BLE001
                pass

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2, default=str),
            encoding="utf-8",
        )

    def save(self, recs: Sequence[ParameterRecommendation]) -> None:
        for rec in recs:
            self._data["recommendations"][
                rec.recommendation_id
            ] = rec.to_dict()
        self._persist()

    def get(self, rec_id: str) -> Optional[dict]:
        return self._data["recommendations"].get(rec_id)

    def list_all(self) -> List[dict]:
        return list(self._data["recommendations"].values())

    def accept(
        self,
        rec_id: str,
        *,
        operator_token: str,
        max_change_pct: Optional[float],
        backtest_validated: bool,
        walk_forward_validated: bool,
        now: Optional[datetime] = None,
    ) -> Tuple[bool, str]:
        """Aceite manual auditado. (ok, motivo).

        Regras (Q9/Q10 — SEM defaults inventados):
            - max_change_pct OBRIGATORIO (cap por parametro);
            - backtest_validated obrigatorio se needs_backtest;
            - walk_forward_validated obrigatorio se needs_walk_forward;
            - overfitting_flag => INELEGIVEL;
            - registra old/new + operador + timestamp.
        """
        now = now or datetime.now(timezone.utc)
        rec = self._data["recommendations"].get(rec_id)
        if rec is None:
            return False, "recommendation_id desconhecido"
        if rec["status"] != "suggested":
            return False, f"status atual: {rec['status']}"
        if not operator_token.strip():
            return False, "operator_token obrigatorio"
        if rec.get("overfitting_flag"):
            return False, (
                "INELEGIVEL: overfitting_flag=True (in-sample bom, "
                "out-of-sample degrada)"
            )
        if max_change_pct is None:
            return False, (
                "blocked_missing_limits: max_change_pct (Q9) "
                "obrigatorio — sem default"
            )
        if rec.get("needs_backtest") and not backtest_validated:
            return False, "backtest adicional nao validado (Q10)"
        if rec.get("needs_walk_forward") and \
                not walk_forward_validated:
            return False, "walk-forward nao validado (Q10)"
        # Cap por parametro numerico.
        cur = rec["current_config"]
        new = rec["suggested_config"]
        for param, new_val in new.items():
            old_val = cur.get(param)
            if isinstance(old_val, (int, float)) and isinstance(
                new_val, (int, float),
            ) and old_val:
                change_pct = abs(new_val - old_val) / abs(
                    old_val,
                ) * 100.0
                if change_pct > max_change_pct:
                    return False, (
                        f"param {param}: alteracao "
                        f"{change_pct:.2f}% > cap "
                        f"{max_change_pct}%"
                    )
        rec["status"] = "accepted"
        rec["accepted_at"] = now.isoformat()
        rec["accepted_by"] = operator_token
        self._data["audit"].append({
            "action": "accept",
            "recommendation_id": rec_id,
            "operator_token": operator_token,
            "timestamp": now.isoformat(),
            "old_config": cur,
            "new_config": new,
            "max_change_pct": max_change_pct,
        })
        self._persist()
        return True, "accepted (NAO aplicado automaticamente)"

    def reject(
        self, rec_id: str, *, operator_token: str,
        reason: str = "", now: Optional[datetime] = None,
    ) -> bool:
        now = now or datetime.now(timezone.utc)
        rec = self._data["recommendations"].get(rec_id)
        if rec is None or rec["status"] != "suggested":
            return False
        rec["status"] = "rejected"
        rec["rejected_at"] = now.isoformat()
        rec["rejected_by"] = operator_token
        self._data["audit"].append({
            "action": "reject", "recommendation_id": rec_id,
            "operator_token": operator_token,
            "timestamp": now.isoformat(), "reason": reason[:160],
        })
        self._persist()
        return True

    def expire_old(
        self, *, max_age_days: int,
        now: Optional[datetime] = None,
    ) -> int:
        now = now or datetime.now(timezone.utc)
        expired = 0
        for rec in self._data["recommendations"].values():
            if rec["status"] != "suggested":
                continue
            created = datetime.fromisoformat(rec["created_at"])
            if now - created > timedelta(days=max_age_days):
                rec["status"] = "expired"
                expired += 1
        if expired:
            self._persist()
        return expired

    @property
    def audit_trail(self) -> List[dict]:
        return list(self._data["audit"])


# ---------------------------------------------------------------------------
# Deteccao de desalinhamento SL x piso de risco (FASE 36 pos-demo 3)
# ---------------------------------------------------------------------------

def detect_sl_below_min_recurrence(
    decision_traces: Sequence[Mapping[str, Any]],
    *,
    min_occurrences: int = 3,
) -> dict:
    """Detecta sinais recorrentes bloqueados por SL abaixo do piso.

    Le os Decision Traces de uma sessao (campo risk_rejection_category
    == 'stop_loss_below_minimum') e, se a recorrencia atingir o limiar,
    produz recomendacoes CONSULTIVAS nos 3 perfis. Nunca aplica nada;
    aceite exige backtest/walk-forward.
    """
    hits = [
        t for t in (decision_traces or [])
        if isinstance(t, Mapping)
        and t.get("risk_rejection_category") == "stop_loss_below_minimum"
    ]
    count = len(hits)
    planned = [
        float(t["planned_sl_pct"]) for t in hits
        if t.get("planned_sl_pct") is not None
    ]
    mins = [
        float(t["min_sl_pct_required"]) for t in hits
        if t.get("min_sl_pct_required") is not None
    ]
    avg_planned = round(sum(planned) / len(planned), 4) if planned else None
    min_required = max(mins) if mins else None

    detected = count >= min_occurrences
    # Fator para a distancia do SL atingir o piso (ex.: 0.5/0.47).
    factor = None
    if detected and avg_planned and avg_planned > 0 and min_required:
        factor = round(min_required / avg_planned, 4)

    recommendations: list = []
    if detected:
        recommendations = [
            {
                "suggestion_profile": "conservador",
                "action": "wait_regime",
                "detail": (
                    "Nao operar neste regime de baixa volatilidade: "
                    "o SL ATR fica abaixo do piso de risco. Aguardar "
                    "ATR maior. Zero trade extra; zero risco novo."
                ),
                "needs_backtest": True,
                "needs_walk_forward": True,
                "needs_human_approval": True,
            },
            {
                "suggestion_profile": "moderado",
                "action": "set_strategy_min_stop_loss_pct",
                "detail": (
                    "Definir min_stop_loss_pct na estrategia (= piso do "
                    "RiskEngine) para rejeitar sinais doomed ANTES do "
                    "RiskEngine (HOLD risk-aware). Mantem o piso; nao "
                    "envia ordem invalida; trace fica explicito."
                ),
                "suggested_min_stop_loss_pct": (
                    round(min_required / 100.0, 6)
                    if min_required else None
                ),
                "needs_backtest": True,
                "needs_walk_forward": True,
                "needs_human_approval": True,
            },
            {
                "suggestion_profile": "arrojado",
                "action": "increase_stop_atr_multiplier",
                "detail": (
                    "Aumentar stop_atr_multiplier para que mult*ATR "
                    ">= piso (SL no piso, R:R preservado, risco_usd "
                    "ainda pequeno). Validar com backtest/walk-forward "
                    "que o stop mais largo nao degrada a expectancy."
                ),
                "suggested_multiplier_factor": factor,
                "needs_backtest": True,
                "needs_walk_forward": True,
                "needs_human_approval": True,
            },
        ]

    return {
        "schema": "sl_below_min_recurrence_v1",
        "detected": detected,
        "occurrences": count,
        "min_occurrences": min_occurrences,
        "avg_planned_sl_pct": avg_planned,
        "min_sl_pct_required": min_required,
        "recommendations": recommendations,
        "note": (
            "Consultivo. NAO baixa o piso do RiskEngine; NAO aplica "
            "mudanca; aceite exige backtest/walk-forward + operador."
        ),
    }


__all__ = [
    "ParameterRecommendation",
    "RecommendationStore",
    "build_recommendations",
    "detect_market_regime",
    "detect_sl_below_min_recurrence",
]
