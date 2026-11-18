"""
AI ContextBuilder (FASE 32)
============================
Constroi o payload sanitizado entregue a IA.

⚠️  A IA NUNCA recebe: secrets, headers, API key/secret, payloads
    sensiveis, objetos mutaveis de execucao (client/executor/
    risk_engine/mode_guard). Apenas valores tecnicos/decisao.
⚠️  Sanitizacao por DENYLIST de tokens + allowlist estrutural:
    qualquer chave suspeita eh descartada; valores string sao
    truncados.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


# Tokens que NUNCA podem aparecer em chaves entregues a IA.
_SECRET_KEY_TOKENS = (
    "api_key", "api_secret", "secret", "token", "password", "credential",
    "authorization", "bearer", "x-bapi", "sign", "header", "cookie",
)
_MAX_STR_LEN = 200
_MAX_DEPTH = 4


def _is_suspect_key(key: str) -> bool:
    low = str(key).lower()
    return any(tok in low for tok in _SECRET_KEY_TOKENS)


def sanitize_for_ai(value: Any, *, _depth: int = 0) -> Any:
    """Sanitiza recursivamente um valor para consumo da IA.

    - Chaves suspeitas sao DESCARTADAS (nao redigidas: nem chegam).
    - Strings truncadas em 200 chars.
    - Objetos nao-primitivos viram repr truncado (nunca o objeto).
    """
    if _depth > _MAX_DEPTH:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:_MAX_STR_LEN]
    if isinstance(value, Mapping):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            if _is_suspect_key(str(k)):
                continue
            out[str(k)] = sanitize_for_ai(v, _depth=_depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [
            sanitize_for_ai(v, _depth=_depth + 1) for v in value[:50]
        ]
    # Objeto arbitrario: NUNCA passa adiante; apenas tipo.
    return f"<{type(value).__name__}>"


def build_ai_context(
    *,
    symbol: str,
    profile_name: str,
    cycle_idx: int,
    signal_snapshot: Optional[Mapping[str, Any]] = None,
    risk_summary: Optional[Mapping[str, Any]] = None,
    prediction_context: Optional[Mapping[str, Any]] = None,
    market_meta: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Monta o contexto sanitizado para AIAdvisorProtocol.

    Todos os blocos passam por sanitize_for_ai. prediction_context
    (FASE 34) ja chega sanitizado do adapter, mas re-sanitizamos por
    defesa em profundidade.
    """
    return {
        "schema": "trade_cycle_context_for_ai_v1",
        "symbol": str(symbol)[:32],
        "profile_name": str(profile_name)[:64],
        "cycle_idx": int(cycle_idx),
        "signal_snapshot": sanitize_for_ai(signal_snapshot or {}),
        "risk_summary": sanitize_for_ai(risk_summary or {}),
        "prediction_context": (
            sanitize_for_ai(prediction_context)
            if prediction_context is not None else None
        ),
        "market_meta": sanitize_for_ai(market_meta or {}),
    }


__all__ = ["build_ai_context", "sanitize_for_ai"]
