"""
Redaction / secret scanner (infra reutilizavel; FASE 43 — realocado da
antiga UI). Garante que NENHUM secret vaze em respostas, reports, logs ou
telemetry. Offline/puro (so stdlib). Sem rede. Sem dependencia de FastAPI.
"""

from __future__ import annotations

import json
from typing import Any

# Scanner ESTRITO (REPORTS/LOGS): reports nunca devem conter material de
# credencial; aqui ate os NOMES api_key/api_secret sao suspeitos.
SECRET_TOKENS = (
    "api_key", "api_secret", "apikey", "apisecret",
    "bearer ", "x-bapi", "sign=", "signature", "authorization:",
    "secret_value", "get_secret_value", "-----begin",
)

# Scanner de VALOR (RESPOSTAS): consumidores podem expor legitimamente
# campos de PRESENCA (api_key_configured etc.). Aqui flagamos apenas
# markers de VALOR de secret — nunca nomes de campo.
OUTBOUND_VALUE_MARKERS = (
    "get_secret_value", "secret_value=", "-----begin",
    "bearer ", "x-bapi-sign", "authorization:", "sign=",
)


class SecretLeakError(Exception):
    """Detectado possivel secret num payload que seria exposto."""


def contains_secret_token(text: str) -> bool:
    """Estrito (reports/logs): flag de nomes/markers de credencial."""
    low = str(text).lower()
    return any(tok in low for tok in SECRET_TOKENS)


def contains_secret_value(text: str) -> bool:
    """Conservador (respostas): flag de VALOR de secret, nunca de nomes de
    campo de presenca (api_key_configured etc.)."""
    low = str(text).lower()
    return any(tok in low for tok in OUTBOUND_VALUE_MARKERS)


def assert_no_secret(payload: Any) -> None:
    """Levanta SecretLeakError se o payload serializado contiver um VALOR
    suspeito de secret. NAO flaga nomes de campo de presenca."""
    try:
        text = json.dumps(payload, default=str)
    except (TypeError, ValueError):
        text = str(payload)
    if contains_secret_value(text):
        raise SecretLeakError("payload contem valor suspeito de secret")


def redact(text: str) -> str:
    """Redige linhas que contenham tokens suspeitos (para logs/erros)."""
    out = []
    for line in str(text).splitlines():
        out.append("[REDACTED]" if contains_secret_token(line) else line)
    return "\n".join(out)


def safe_error_message(exc: Exception) -> str:
    """Mensagem de erro SANITIZADA (sem stacktrace, sem secret)."""
    msg = f"{type(exc).__name__}"
    detail = str(exc)
    if detail and not contains_secret_token(detail):
        msg = f"{msg}: {detail[:160]}"
    return msg


__all__ = [
    "OUTBOUND_VALUE_MARKERS",
    "SECRET_TOKENS",
    "SecretLeakError",
    "assert_no_secret",
    "contains_secret_token",
    "contains_secret_value",
    "redact",
    "safe_error_message",
]
