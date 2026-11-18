"""
Testes do script check_operational_profile.py (FASE 18)
==========================================================
⚠️  100% offline. ZERO rede.

Cobertura:
    - Script roda sem rede.
    - Output contém preview/diff tabular sanitizado.
    - Output não contém secrets (api_key, api_secret, Bearer, X-BAPI-SIGN).
    - Exit 0 para profile válido.
    - Exit 1 para issue 'error'.
    - Script NÃO importa BybitClient/executores/httpx.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).parent.parent
_SCRIPT = _ROOT / "scripts" / "check_operational_profile.py"


def _run(*args: str, env_extra=None) -> tuple[int, str]:
    cmd = [sys.executable, str(_SCRIPT), *args]
    import os
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        cmd,
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=30,
    )
    return result.returncode, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Modos válidos
# ---------------------------------------------------------------------------

class TestValidProfilesExitZero:

    def test_personal_default(self):
        code, out = _run("--profile", "personal", "--capital", "5000")
        assert code == 0, out
        assert "PREVIEW ONLY" in out
        assert "personal" in out

    def test_prop_challenge(self):
        code, out = _run("--profile", "prop_challenge", "--capital", "5000")
        # prop_challenge pode gerar warnings (cross-config), mas não errors
        # com defaults atuais — exit 0
        assert code == 0, out

    def test_hyrotrader_template(self):
        code, out = _run(
            "--profile", "hyrotrader_demo_template", "--capital", "5000",
        )
        assert code == 0, out

    def test_custom_default(self):
        code, out = _run("--profile", "custom")
        assert code == 0, out


# ---------------------------------------------------------------------------
# Output tabular contém os campos esperados
# ---------------------------------------------------------------------------

class TestOutputContent:

    def test_output_contains_diff_header(self):
        code, out = _run("--profile", "personal", "--capital", "5000")
        assert code == 0
        assert "DIFF" in out
        assert "ISSUES" in out
        assert "is_apply_safe" in out
        assert "requires_confirmation" in out

    def test_output_contains_preview_only_marker(self):
        code, out = _run("--profile", "personal", "--capital", "5000")
        assert "PREVIEW ONLY" in out
        assert "nenhum override foi aplicado" in out


# ---------------------------------------------------------------------------
# Sem secrets no output
# ---------------------------------------------------------------------------

class TestNoSecretsInOutput:

    def test_no_api_key_or_secret_strings_in_output(self):
        code, out = _run("--profile", "personal", "--capital", "5000")
        lower = out.lower()
        forbidden = (
            "api_key=", "api_secret=", "x-bapi-sign", "bearer ",
            "authorization:",
        )
        for tok in forbidden:
            assert tok not in lower, f"output contém token suspeito: {tok}"

    def test_no_dotenv_content_in_output(self):
        """Script NÃO deve abrir/cat o .env. Output não tem trecho típico."""
        code, out = _run("--profile", "personal", "--capital", "5000")
        # Tokens típicos de uma linha de .env (BYBIT_API_KEY=)
        assert "BYBIT_API_KEY=" not in out
        assert "BYBIT_API_SECRET=" not in out


# ---------------------------------------------------------------------------
# Capital inválido falha
# ---------------------------------------------------------------------------

class TestInvalidCapital:

    def test_zero_capital_exits_nonzero(self):
        code, out = _run("--profile", "personal", "--capital", "0")
        assert code == 1

    def test_negative_capital_exits_nonzero(self):
        code, out = _run("--profile", "personal", "--capital", "-100")
        assert code == 1


# ---------------------------------------------------------------------------
# Inspeção estrutural: script não importa rede/executores
# ---------------------------------------------------------------------------

class TestScriptNoForbiddenImports:

    def test_script_does_not_import_bybit_client(self):
        src = _SCRIPT.read_text(encoding="utf-8")
        assert "from crypto_trading_bot.exchange.bybit_client" not in src
        assert "import crypto_trading_bot.exchange.bybit_client" not in src

    def test_script_does_not_import_executors(self):
        src = _SCRIPT.read_text(encoding="utf-8")
        forbidden = [
            "from crypto_trading_bot.execution.bybit_demo_executor",
            "from crypto_trading_bot.execution.bybit_testnet_executor",
        ]
        for tok in forbidden:
            assert tok not in src

    def test_script_does_not_import_httpx(self):
        src = _SCRIPT.read_text(encoding="utf-8")
        assert "import httpx" not in src
        assert "from httpx" not in src

    def test_script_does_not_open_dotenv(self):
        src = _SCRIPT.read_text(encoding="utf-8")
        # Script confia no pydantic-settings para ler .env;
        # NUNCA deve open()/Path()/read_text do .env diretamente
        assert 'open(".env"' not in src
        assert "open('.env'" not in src
        assert "'.env').read" not in src.replace(' ', '')
