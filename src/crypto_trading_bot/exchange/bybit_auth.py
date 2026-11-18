"""
Bybit V5 HMAC Authentication — FASE 5
========================================
Função pura para gerar a assinatura HMAC-SHA256 exigida pelos endpoints
privados da Bybit V5 (incluindo testnet).

⚠️  Função pura: sem I/O, sem rede, sem efeitos colaterais.
⚠️  Apenas usa stdlib (hmac, hashlib, json). Sem dependência nova.
⚠️  NUNCA loga api_key, api_secret, signature ou headers sensíveis.

Spec Bybit V5 (oficial):
    https://bybit-exchange.github.io/docs/v5/intro#authentication

Algoritmo (resumido):
    payload = timestamp + api_key + recv_window + (query_string OR body_string)
    signature = hmac_sha256(api_secret, payload).hexdigest()

    Headers obrigatórios:
        X-BAPI-API-KEY:    <api_key>
        X-BAPI-TIMESTAMP:  <timestamp_ms>
        X-BAPI-RECV-WINDOW: <recv_window_ms>
        X-BAPI-SIGN:       <signature_hex>
        X-BAPI-SIGN-TYPE:  2          (HMAC-SHA256)

Convenções:
    - query_string: parâmetros ordenados ALFABETICAMENTE por chave, separados
      por '&', no formato "k1=v1&k2=v2..." (mesma serialização da URL).
    - body_string: JSON compacto (sem espaços), determinístico
      (json.dumps(payload, separators=(',', ':'), sort_keys=False)).
    - Para chamadas GET: usa query_string. Para POST: usa body_string.

API:
    sign_request(
        api_key: str,
        api_secret: str,
        timestamp_ms: int,
        recv_window_ms: int,
        method: str,                   # "GET" | "POST"
        query_or_body: str,            # already serialized
    ) → Dict[str, str]                  # headers obrigatórios

    build_query_string(params: Dict[str, Any]) → str
    build_body_string(payload: Dict[str, Any]) → str
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Dict, Mapping

# Janela mínima/máxima razoável em ms (Bybit aceita 0-60000; recomendado 5000)
_MIN_RECV_WINDOW_MS = 100
_MAX_RECV_WINDOW_MS = 60000


def build_query_string(params: Mapping[str, Any]) -> str:
    """
    Constrói a query string ordenada alfabeticamente por chave.

    Bybit V5 exige que a assinatura seja calculada sobre os params
    SERIALIZADOS NA MESMA ORDEM que serão enviados. Garantimos ordem
    determinística via sort_keys.

    Args:
        params: Dict de parâmetros (chaves str, valores Any).

    Returns:
        String "k1=v1&k2=v2..." ordenada por chave.
        Para params vazio, retorna "".

    ⚠️  Esta função NÃO faz URL-encoding. Bybit V5 aceita string crua
        para a assinatura (o cliente HTTP fará URL-encoding ao enviar).
    """
    if not params:
        return ""
    sorted_keys = sorted(params.keys())
    parts = [f"{k}={params[k]}" for k in sorted_keys]
    return "&".join(parts)


def build_body_string(payload: Mapping[str, Any]) -> str:
    """
    Serializa o body em JSON compacto e determinístico para POST.

    Bybit V5 exige que a assinatura seja calculada sobre o EXATO body
    enviado. JSON compacto (separators=(',', ':')) sem espaços extras.

    Mantemos a ordem fornecida pelo caller (sort_keys=False) — a Bybit
    aceita qualquer ordem desde que body e assinatura concordem.

    Args:
        payload: Dict do body (chaves str).

    Returns:
        String JSON compacta (sem espaços/newlines).
        Para payload vazio, retorna "{}".
    """
    if not payload:
        return "{}"
    return json.dumps(payload, separators=(",", ":"), sort_keys=False)


def sign_request(
    api_key: str,
    api_secret: str,
    timestamp_ms: int,
    recv_window_ms: int,
    method: str,
    query_or_body: str,
) -> Dict[str, str]:
    """
    Gera os headers de autenticação Bybit V5 para uma requisição.

    Algoritmo:
        payload = str(timestamp_ms) + api_key + str(recv_window_ms) + query_or_body
        signature = HMAC-SHA256(api_secret, payload).hexdigest() (lowercase)

    Args:
        api_key:        Chave pública da API (str não-vazia).
        api_secret:     Segredo da API (str não-vazia).
        timestamp_ms:   Timestamp em milissegundos (>= 0).
        recv_window_ms: Janela de validade em ms (entre _MIN_ e _MAX_).
        method:         "GET" ou "POST" (apenas para auditoria/log; não entra
                        no payload da assinatura V5).
        query_or_body:  String já serializada (query string para GET ou body
                        JSON compacto para POST).

    Returns:
        Dict com os 5 headers obrigatórios:
            X-BAPI-API-KEY, X-BAPI-TIMESTAMP, X-BAPI-RECV-WINDOW,
            X-BAPI-SIGN, X-BAPI-SIGN-TYPE.

    Raises:
        ValueError: Se api_key/api_secret vazios, timestamp negativo,
                    recv_window fora da faixa razoável, ou method inválido.

    ⚠️  Esta função NUNCA loga api_key, api_secret ou signature.
    """
    # Validações de entrada (mensagens NÃO contêm os valores reais)
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("api_key deve ser string não-vazia")
    if not isinstance(api_secret, str) or not api_secret.strip():
        raise ValueError("api_secret deve ser string não-vazia")
    if not isinstance(timestamp_ms, int) or timestamp_ms < 0:
        raise ValueError(
            f"timestamp_ms deve ser int >= 0: {timestamp_ms}"
        )
    if (
        not isinstance(recv_window_ms, int)
        or recv_window_ms < _MIN_RECV_WINDOW_MS
        or recv_window_ms > _MAX_RECV_WINDOW_MS
    ):
        raise ValueError(
            f"recv_window_ms deve estar em [{_MIN_RECV_WINDOW_MS}, "
            f"{_MAX_RECV_WINDOW_MS}] ms: {recv_window_ms}"
        )
    if method not in ("GET", "POST"):
        raise ValueError(f"method deve ser 'GET' ou 'POST': {method!r}")

    # Spec V5: payload = timestamp + api_key + recv_window + query_or_body
    payload = f"{timestamp_ms}{api_key}{recv_window_ms}{query_or_body}"

    signature = hmac.new(
        key=api_secret.encode("utf-8"),
        msg=payload.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()  # hex lowercase por padrão

    return {
        "X-BAPI-API-KEY": api_key,
        "X-BAPI-TIMESTAMP": str(timestamp_ms),
        "X-BAPI-RECV-WINDOW": str(recv_window_ms),
        "X-BAPI-SIGN": signature,
        "X-BAPI-SIGN-TYPE": "2",   # 2 = HMAC-SHA256
    }
