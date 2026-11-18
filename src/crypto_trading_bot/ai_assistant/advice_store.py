"""
AI Advice Store (FASE 47) — storage VERSIONADO + cache/replay deterministico
=============================================================================
Por chamada de IA grava: timestamp, modelo, model_version, prompt_hash,
inputs (SANITIZADOS), resposta (AIAdvice dict), latencia. Permite REPLAY
deterministico no backtest/shadow (consome do cache, sem re-chamar o provider)
e garante que NENHUM secret vai ao store (redaction + scan).

Arquivo JSON local; nunca secrets. Reusa redact_text (provider_adapter).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from crypto_trading_bot.ai_assistant.advisor_protocol import (
    AIAdvice,
    AIAdviceStatus,
    AISuggestedAction,
)
from crypto_trading_bot.ai_assistant.provider_adapter import redact_text

# Scan defensivo de secret (alem do redact): recusa gravar se sobrar padrao.
_SECRET_PAT = re.compile(r"(?i)(sk-[A-Za-z0-9_\-]{8,}|api[_-]?key\s*[:=]|"
                         r"bearer\s+[A-Za-z0-9._\-]{8,})")


def prompt_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:32]


def _sanitize_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, Mapping):
        return {k: _sanitize_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_obj(v) for v in obj]
    return obj


def assert_no_secret(text: str) -> None:
    if text and _SECRET_PAT.search(text):
        raise ValueError("possivel secret detectado; gravacao recusada")


@dataclass(frozen=True)
class AdviceRecord:
    ts: str
    model: str
    model_version: str
    prompt_hash: str
    inputs: Mapping[str, Any]
    response: Mapping[str, Any]
    latency_ms: Optional[float] = None
    source: str = "real"        # real | mock | replay

    def to_dict(self) -> dict:
        return {
            "ts": self.ts, "model": self.model,
            "model_version": self.model_version,
            "prompt_hash": self.prompt_hash,
            "inputs": dict(self.inputs), "response": dict(self.response),
            "latency_ms": self.latency_ms, "source": self.source,
        }


def advice_from_response(resp: Mapping[str, Any]) -> AIAdvice:
    """Reconstroi AIAdvice a partir do dict salvo (replay)."""
    status = AIAdviceStatus(resp.get("status", "neutral"))
    action = AISuggestedAction(resp.get("suggested_action", "proceed"))
    return AIAdvice(
        status=status, confidence=float(resp.get("confidence", 0.0) or 0.0),
        reason=str(resp.get("reason", "")),
        warnings=tuple(resp.get("warnings", ()) or ()),
        suggested_action=action)


class AdviceStore:
    """Store JSON versionado + indice por prompt_hash p/ replay."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        if any(p == ".." for p in self._path.parts):
            raise ValueError("store path contem '..' (rejeitado)")
        self._records: List[Dict[str, Any]] = []
        self._by_hash: Dict[str, Dict[str, Any]] = {}
        if self._path.is_file():
            try:
                loaded = json.loads(self._path.read_text(encoding="utf-8"))
                self._records = list(loaded.get("records") or [])
                for r in self._records:
                    self._by_hash[r.get("prompt_hash")] = r
            except Exception:  # noqa: BLE001
                self._records = []

    def record(self, rec: AdviceRecord) -> None:
        d = rec.to_dict()
        # sanitiza + recusa secret
        d["inputs"] = _sanitize_obj(d["inputs"])
        d["response"] = _sanitize_obj(d["response"])
        assert_no_secret(json.dumps(d, default=str))
        self._records.append(d)
        self._by_hash[d["prompt_hash"]] = d
        self._persist()

    def cached(self, ph: str) -> Optional[AIAdvice]:
        r = self._by_hash.get(ph)
        if r is None:
            return None
        try:
            return advice_from_response(r.get("response") or {})
        except Exception:  # noqa: BLE001
            return None

    def has(self, ph: str) -> bool:
        return ph in self._by_hash

    @property
    def records(self) -> List[Dict[str, Any]]:
        return list(self._records)

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema": "ai_advice_store_v1",
                   "updated_at": datetime.now(timezone.utc).isoformat(),
                   "records": self._records}
        self._path.write_text(json.dumps(payload, indent=2, default=str),
                              encoding="utf-8")


__all__ = [
    "AdviceRecord", "AdviceStore", "advice_from_response",
    "assert_no_secret", "prompt_hash",
]
