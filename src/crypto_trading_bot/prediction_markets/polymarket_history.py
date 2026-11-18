"""
Polymarket history (FASE 47) — descoberta causal + price history + storage +
alinhamento causal + stance p/ a composicao de risco (context_risk).
==============================================================================
- Descoberta CAUSAL de mercados BTC ELEGIVEIS (lista PRE-DEFINIDA de termos;
  sem cherry-pick por desfecho); um mercado so e elegivel em t se EXISTIA
  (created_at <= t) e ainda NAO resolveu (resolved_at None ou > t).
- Historico de preco/probabilidade por timestamp (nunca resultado resolvido,
  nunca selecao por desfecho futuro).
- Storage canonico VERSIONADO + cobertura/readiness.
- Alinhamento CAUSAL a candles (asof por close_time) -> stance por candle.
- Stance -> multiplicador via context_risk (favorable=1,00/elevated_risk=0,75/
  contrary=0,00/not_applicable=1,00).

Transporte HTTP real e INJETAVEL (gated; usado so no CLI de fetch). Aqui,
offline: consome snapshots ja coletados/fixtures. Nunca aposta/ordem.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

# Categorias/termos BTC ELEGIVEIS pre-definidos (sem cherry-pick por desfecho).
BTC_ELIGIBLE_TERMS = ("bitcoin", "btc")
# Prob "incerta" (perto de 0,5) em mercado BTC vigente => risco elevado.
_UNCERTAIN_LOW, _UNCERTAIN_HIGH = 0.40, 0.60


def _as_utc(ts) -> Optional[datetime]:
    if ts is None:
        return None
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
    return None


@dataclass(frozen=True)
class PolymarketSnapshot:
    market_id: str
    question: str
    category: str
    created_at: Optional[datetime]
    resolved_at: Optional[datetime]
    timestamp: datetime          # instante do snapshot de preco
    prob_yes: float              # probabilidade implicada [0,1] NAQUELE ts

    def to_dict(self) -> dict:
        return {"market_id": self.market_id, "question": self.question,
                "category": self.category,
                "created_at": self.created_at.isoformat()
                if self.created_at else None,
                "resolved_at": self.resolved_at.isoformat()
                if self.resolved_at else None,
                "timestamp": self.timestamp.isoformat(),
                "prob_yes": self.prob_yes}


def is_btc_eligible(question: str, category: str = "", *,
                    terms: Sequence[str] = BTC_ELIGIBLE_TERMS) -> bool:
    text = f"{question} {category}".lower()
    return any(t in text for t in terms)


def load_snapshots(rows: Sequence[Mapping[str, Any]]) -> List[PolymarketSnapshot]:
    out: List[PolymarketSnapshot] = []
    for r in rows or []:
        ts = _as_utc(r.get("timestamp"))
        if ts is None:
            continue
        try:
            prob = float(r.get("prob_yes"))
        except (TypeError, ValueError):
            continue
        out.append(PolymarketSnapshot(
            market_id=str(r.get("market_id", "")),
            question=str(r.get("question", "")),
            category=str(r.get("category", "")),
            created_at=_as_utc(r.get("created_at")),
            resolved_at=_as_utc(r.get("resolved_at")),
            timestamp=ts, prob_yes=max(0.0, min(1.0, prob))))
    out.sort(key=lambda s: s.timestamp)
    return out


class PolymarketHistory:
    """Historico causal de snapshots de mercados BTC elegiveis."""

    def __init__(self, snapshots: Sequence[PolymarketSnapshot], *,
                 terms: Sequence[str] = BTC_ELIGIBLE_TERMS) -> None:
        self._terms = tuple(terms)
        # so mantem snapshots BTC elegiveis (filtro por termo, nao desfecho)
        self._snaps = [s for s in snapshots
                       if is_btc_eligible(s.question, s.category,
                                          terms=self._terms)]
        self._snaps.sort(key=lambda s: s.timestamp)

    def eligible_at(self, t: datetime) -> List[PolymarketSnapshot]:
        """Snapshots com timestamp <= t de mercados que EXISTIAM (created<=t)
        e NAO resolveram em t (resolved None ou > t). Causal, sem lookahead."""
        t = _as_utc(t)
        out = []
        for s in self._snaps:
            if s.timestamp > t:
                continue
            if s.created_at is not None and s.created_at > t:
                continue
            if s.resolved_at is not None and s.resolved_at <= t:
                continue
            out.append(s)
        return out

    def stance_at(self, t: datetime) -> str:
        """Stance causal em t (ultimo snapshot por mercado elegivel).

        Heuristica conservadora (so REDUZ risco): sem mercado elegivel =>
        not_applicable; prob incerta (perto de 0,5) em mercado vigente =>
        elevated_risk; senao favorable. (contrary fica p/ config explicita
        de evento adverso — nao inferido por desfecho futuro.)
        """
        elig = self.eligible_at(t)
        if not elig:
            return "not_applicable"
        # ultimo snapshot por mercado
        latest: Dict[str, PolymarketSnapshot] = {}
        for s in elig:
            cur = latest.get(s.market_id)
            if cur is None or s.timestamp >= cur.timestamp:
                latest[s.market_id] = s
        probs = [s.prob_yes for s in latest.values()]
        if any(_UNCERTAIN_LOW <= p <= _UNCERTAIN_HIGH for p in probs):
            return "elevated_risk"
        return "favorable"

    def align_to_candles(self, candles: Sequence, *,
                         interval_minutes: int) -> List[str]:
        """Stance por candle (causal por close_time)."""
        out = []
        for c in candles:
            ts = c.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            close_time = ts + timedelta(minutes=interval_minutes)
            out.append(self.stance_at(close_time))
        return out

    def coverage(self, start: Optional[datetime] = None,
                 end: Optional[datetime] = None,
                 *, min_markets: int = 3,
                 min_snapshots: int = 200) -> Dict[str, Any]:
        """Cobertura/readiness do historico p/ a ablacao C.

        insufficient_history se poucos mercados/snapshots BTC => Polymarket
        vai p/ shadow (C nao roda historico).
        """
        start = _as_utc(start)
        end = _as_utc(end)
        snaps = [s for s in self._snaps
                 if (start is None or s.timestamp >= start)
                 and (end is None or s.timestamp < end)]
        markets = {s.market_id for s in snaps}
        first = snaps[0].timestamp.isoformat() if snaps else None
        last = snaps[-1].timestamp.isoformat() if snaps else None
        sufficient = (len(markets) >= min_markets
                      and len(snaps) >= min_snapshots)
        return {
            "btc_markets": len(markets),
            "snapshots": len(snaps),
            "first": first, "last": last,
            "min_markets": min_markets, "min_snapshots": min_snapshots,
            "verdict": "sufficient" if sufficient else "insufficient_history",
            "note": "insufficient_history => Polymarket vai p/ shadow; "
                    "C nao roda historico (sem inventar dados retroativos).",
        }


# ----------------------------- storage canonico ---------------------------

def save_canonical(path: str, snapshots: Sequence[PolymarketSnapshot], *,
                   meta: Optional[Mapping[str, Any]] = None) -> None:
    p = Path(path)
    if any(part == ".." for part in p.parts):
        raise ValueError("path contem '..' (rejeitado)")
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "polymarket_history_v1",
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "provenance": dict(meta or {}),
        "snapshots": [s.to_dict() for s in snapshots],
    }
    p.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def load_canonical(path: str) -> List[PolymarketSnapshot]:
    p = Path(path)
    if not p.is_file():
        return []
    data = json.loads(p.read_text(encoding="utf-8-sig"))
    return load_snapshots(data.get("snapshots") or [])


def default_polymarket_transport():
    """Transporte HTTP read-only REAL (gamma-api.polymarket.com). Import
    tardio; usado SO no CLI de fetch (gated por --allow-network). Nunca
    aposta/ordem; sem auth/secret."""
    def _fetch(url: str) -> Any:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent":
                                                   "crypto-ai-research"})
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    return _fetch


__all__ = [
    "BTC_ELIGIBLE_TERMS", "PolymarketSnapshot", "PolymarketHistory",
    "is_btc_eligible", "load_snapshots", "save_canonical", "load_canonical",
    "default_polymarket_transport",
]
