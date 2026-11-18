"""
Log Redaction — FASE 5
========================
Funções puras para mascarar dados sensíveis em mensagens textuais antes
de enviá-las a logs.

⚠️  Funções puras: sem I/O, sem rede.
⚠️  NÃO aplica filtro global ao logger nesta fase (mudança maior em logger.py
    foi marcada como "parar e reportar"). O caller usa `redact_sensitive()`
    explicitamente antes de chamar `logger.info(...)`.

Padrões mascarados:
    - api_key=... / "api_key": "..."
    - api_secret=... / "api_secret": "..."
    - secret=... / "secret": "..."
    - Headers Bybit V5: X-BAPI-API-KEY, X-BAPI-SIGN, X-BAPI-SIGN-TYPE
    - Authorization: Bearer ... / Basic ...

Tudo que case com esses padrões é substituído por `***REDACTED***`.

Uso típico:
    from crypto_trading_bot.logging_system.log_redaction import redact_sensitive

    msg = f"Headers enviados: api_key={key}, X-BAPI-SIGN={sig}"
    logger.info(redact_sensitive(msg))
"""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping

# ---------------------------------------------------------------------------
# Token de substituição
# ---------------------------------------------------------------------------

REDACTED_PLACEHOLDER = "***REDACTED***"

# ---------------------------------------------------------------------------
# Padrões de chaves sensíveis em mensagens textuais
# ---------------------------------------------------------------------------
# Cada padrão captura: nome do campo + separador (=, :) + valor (até espaço,
# ',', '}', '"' ou newline). O valor é substituído.
#
# As keys ficam EM CASE-INSENSITIVE; valores podem estar entre aspas ou não.

_SENSITIVE_KEYS = (
    # Chaves comuns
    "api_key",
    "api[_-]?secret",
    "secret",
    # Cabeçalhos Bybit V5
    "X-BAPI-API-KEY",
    "X-BAPI-SIGN",
    "X-BAPI-SIGN-TYPE",
    # Authorization
    "Authorization",
)


def _build_pattern() -> re.Pattern[str]:
    """
    Constrói um regex unificado que casa qualquer chave sensível seguida
    de '=', ':' ou ': ' (com ou sem aspas) e captura o valor até o próximo
    delimitador.

    Formato suportado (todos case-insensitive):
        api_key=VAL
        api_key="VAL"
        "api_key": "VAL"        ← JSON-style com aspas antes do ':'
        X-BAPI-SIGN: VAL
        X-BAPI-API-KEY: VAL

    Returns:
        re.Pattern compilado.
    """
    # Filtra "Authorization" do conjunto genérico — esse vai num regex separado
    # (precisa capturar "Bearer XXXX" ou "Basic XXXX" como UM valor único).
    keys_for_generic = [
        k for k in _SENSITIVE_KEYS
        if k.lower() != "authorization"
    ]
    keys_alt = "|".join(keys_for_generic)
    # Captura: chave + aspa opcional + separador + aspa opcional + valor.
    # JSON: "api_key": "val" → "api_key" + : + "val"
    #   key="api_key", quote_after_key='"', sep=': ', quote_open='"',
    #   val="val", quote_close (mesmo)
    pattern = (
        rf"(?P<key>(?i:{keys_alt}))"
        r'(?P<quote_after_key>"?)'           # aspa após a chave (JSON: "key" : "val")
        r"(?P<sep>\s*[:=]\s*)"               # separador : ou =
        r'(?P<quote_open>"?)'                 # aspa de abertura do valor
        r'(?P<val>[^\s,"}\]\n]+)'             # valor (sem espaços/aspas)
        r'(?P<quote_close>"?)'                # aspa de fechamento do valor
    )
    return re.compile(pattern)


_REDACTION_RE = _build_pattern()

# Regex especial para "Authorization: <esquema> <token>" — substitui TUDO
# que vier após o separador até fim de linha (cobre Bearer, Basic, etc.).
_AUTH_RE = re.compile(
    r"(?P<key>(?i:Authorization))"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<val>[^\n,}\]]+)"
)


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def redact_sensitive(text: str) -> str:
    """
    Substitui valores de campos sensíveis em uma string por `***REDACTED***`.

    Args:
        text: Texto contendo possivelmente chaves/secrets.

    Returns:
        Texto com valores sensíveis substituídos. Estrutura preservada.

    Exemplos:
        >>> redact_sensitive("api_key=abc123 user=john")
        'api_key=***REDACTED*** user=john'

        >>> redact_sensitive('"api_secret": "topsecret"')
        '"api_secret": "***REDACTED***"'

        >>> redact_sensitive("X-BAPI-SIGN: 6c7d8e9...")
        'X-BAPI-SIGN: ***REDACTED***'

    ⚠️  Função pura. NÃO altera input. NÃO chama logger.
    """
    if not isinstance(text, str) or not text:
        return text

    def _replace_generic(match: re.Match[str]) -> str:
        key = match.group("key")
        q_after_key = match.group("quote_after_key")
        sep = match.group("sep")
        q_open = match.group("quote_open")
        q_close = match.group("quote_close")
        return (
            f"{key}{q_after_key}{sep}{q_open}{REDACTED_PLACEHOLDER}{q_close}"
        )

    def _replace_auth(match: re.Match[str]) -> str:
        key = match.group("key")
        sep = match.group("sep")
        return f"{key}{sep}{REDACTED_PLACEHOLDER}"

    # Aplica padrão genérico (api_key/api_secret/sign/X-BAPI-*).
    out = _REDACTION_RE.sub(_replace_generic, text)
    # Aplica padrão Authorization (substitui esquema + token).
    out = _AUTH_RE.sub(_replace_auth, out)
    return out


def redact_dict(data: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Versão dict-aware: para dicts, mascara valores cujas chaves são sensíveis.

    Não recursivo — apenas o nível superior. Para nested dicts, chamar
    `redact_dict` em cada nível conforme necessário.

    Args:
        data: Dict de chave→valor.

    Returns:
        Cópia rasa do dict com valores sensíveis substituídos.
    """
    if not isinstance(data, Mapping):
        return dict(data) if data else {}

    sensitive_keys_lower = {
        "api_key", "api_secret", "apisecret", "api-secret",
        "secret",
        "x-bapi-api-key", "x-bapi-sign", "x-bapi-sign-type",
        "authorization",
    }
    out: Dict[str, Any] = {}
    for k, v in data.items():
        key_lower = str(k).lower()
        if key_lower in sensitive_keys_lower:
            out[k] = REDACTED_PLACEHOLDER
        else:
            out[k] = v
    return out
