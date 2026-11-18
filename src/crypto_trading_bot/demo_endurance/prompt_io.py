"""
Prompt IO + TTY detection for demo endurance real (FASE 27)
================================================================
Helpers para confirmacao interativa do operador antes de demo real.

⚠️  ZERO importacao de:
    - BybitClient / BybitDemoExecutor / BybitDemoPreflight
    - execute_demo_session_gated / build_demo_api_blueprint
    - httpx / requests / load_dotenv

Politica:
    - TTY ausente sem --non-interactive-assume-no -> TTYRequired raise.
    - --non-interactive-assume-no -> retorna False sem prompt.
    - Timeout -> retorna False.
    - Resposta != "Y" (case-sensitive) -> retorna False.
    - Apenas "Y" exato (uppercase) -> retorna True.
"""

from __future__ import annotations

import os
import sys
from typing import Callable, Optional


class TTYRequired(RuntimeError):
    """Levantado quando prompt interativo eh requerido mas TTY ausente."""


def is_tty(stream=None) -> bool:
    """True se o stream eh TTY interativo.

    Default: sys.stdin. Aceita injecao para testes.
    """
    target = stream if stream is not None else sys.stdin
    isatty = getattr(target, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except Exception:
        return False


def prompt_yes_or_abort(
    message: str,
    *,
    timeout_seconds: float = 60.0,
    assume_no: bool = False,
    tty_check: Callable[[], bool] = is_tty,
    input_fn: Optional[Callable[[str], str]] = None,
) -> bool:
    """Pergunta confirmacao Y; retorna True apenas se resposta == "Y".

    Args:
        message:         Prompt a exibir.
        timeout_seconds: Timeout aplicado quando o input bloqueia (informativo;
                         input() padrao do Python nao tem timeout cross-platform
                         sem dependencia adicional - aceitamos isso e
                         documentamos: caller pode injetar input_fn com timeout
                         nativo onde fizer sentido).
        assume_no:       Se True, retorna False sem prompt (CI/no-TTY safe).
        tty_check:       Callable que retorna True se TTY presente (injetavel).
        input_fn:        Callable(message) -> str. Default input().

    Returns:
        True apenas se assume_no=False AND tty presente AND ans == "Y".

    Raises:
        TTYRequired: se TTY ausente e assume_no=False.
    """
    if assume_no:
        return False
    if not tty_check():
        raise TTYRequired(
            "TTY required for confirmation prompt. Use "
            "--non-interactive-assume-no in CI/non-TTY environment "
            "(execution will be safely declined)."
        )
    fn = input_fn or input
    try:
        ans = fn(message)
    except (EOFError, KeyboardInterrupt):
        return False
    if not isinstance(ans, str):
        return False
    return ans.strip() == "Y"


def envvar_present(name: str) -> bool:
    """True se variavel de ambiente eh nao-vazia.

    ⚠️  NUNCA imprime nem retorna o valor; apenas presence boolean.
    """
    if not isinstance(name, str) or not name.strip():
        return False
    val = os.environ.get(name, "")
    return bool(val.strip())
