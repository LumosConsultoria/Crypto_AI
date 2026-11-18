"""
NetComms — executor de operacoes de rede (infra; FASE 43 realocado da
antiga UI).
====================================================================
Toda comunicacao de rede passa por aqui: adapter/client ALLOWLISTED,
timeout, erro SANITIZADO, status visivel, last_success/last_failure.
NUNCA expoe secret/header/signature; NUNCA shell. Operacao GATED por
padrao: sem permissao explicita => `blocked`/`not_configured`, sem tocar a
rede. FastAPI-free; usavel por qualquer CLI.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FTimeout
from typing import Any, Callable, Optional

from crypto_trading_bot.netcomms.redaction import (
    contains_secret_token,
    safe_error_message,
)
from crypto_trading_bot.netcomms.status import ConnectionStatus, now_iso

_EXECUTOR = ThreadPoolExecutor(max_workers=2)


def run_network_op(
    operation: str,
    adapter_callable: Optional[Callable[[], Any]] = None,
    *,
    timeout: float = 10.0,
    gated: bool = True,
    approved: bool = False,
    not_configured: bool = False,
    registry=None,
) -> ConnectionStatus:
    """Executa UMA operacao de rede allowlisted, devolvendo ConnectionStatus.

    - not_configured=True (ex.: sem credencial) => 'not_configured'.
    - gated e nao approved (ou adapter None) => 'blocked' (NAO toca rede).
    - approved + adapter => executa com timeout; erro sanitizado.
    O adapter DEVE ser read-only e devolver um dict ja sanitizado.
    """
    prev = registry.get(operation) if registry is not None else None

    def _status(**kw) -> ConnectionStatus:
        base = {
            "last_success": prev.last_success if prev else None,
            "last_failure": prev.last_failure if prev else None,
        }
        base.update(kw)   # kw tem precedencia (ex.: novo last_failure)
        st = ConnectionStatus(operation=operation, gated=gated, **base)
        if registry is not None:
            registry.update(st)
        return st

    if not_configured:
        return _status(state="not_configured",
                       detail="credenciais/config ausentes")
    if gated and (not approved or adapter_callable is None):
        return _status(state="blocked",
                       detail="comunicacao gated: nao aprovada")

    t0 = time.monotonic()
    try:
        fut = _EXECUTOR.submit(adapter_callable)
        result = fut.result(timeout=timeout)
    except _FTimeout:
        return _status(state="failed", last_failure=now_iso(),
                       last_error_sanitized="timeout",
                       detail=f"timeout apos {timeout}s")
    except Exception as e:  # noqa: BLE001
        return _status(state="failed", last_failure=now_iso(),
                       last_error_sanitized=safe_error_message(e),
                       detail="falha na operacao (sanitizada)")
    latency = round((time.monotonic() - t0) * 1000.0, 2)
    # Defesa: resultado do adapter NUNCA pode conter secret.
    detail = ""
    if isinstance(result, dict):
        detail = str({k: result[k] for k in list(result)[:6]})
        if contains_secret_token(detail):
            detail = "[REDACTED]"
    return _status(state="connected", last_success=now_iso(),
                   latency_ms=latency, detail=detail[:200])


__all__ = ["run_network_op"]
