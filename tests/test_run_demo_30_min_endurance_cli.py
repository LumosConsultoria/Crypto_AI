"""
Tests - scripts/run_demo_30_min_endurance.py (FASE 27)
==========================================================
100% offline. ZERO network. ZERO secret. ZERO ordem.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "run_demo_30_min_endurance.py"


def _run(*args: str, env_extra=None, timeout: int = 60):
    cmd = [sys.executable, str(_SCRIPT), *args]
    import os
    env = os.environ.copy()
    # Sanitize ENV to default-safe for tests.
    # FASE 28 closeout: CLI agora autoloads .env (override=False). Para
    # bloquear o autoload de injetar valores nos testes, setamos as
    # variaveis criticas como string vazia (presente). load_dotenv
    # override=False respeita presence, mesmo vazia.
    for k in ("ENABLE_LIVE_TRADING", "ENABLE_DEMO_EXECUTION",
              "TRADING_MODE", "BYBIT_DEMO_API_KEY",
              "BYBIT_DEMO_API_SECRET",
              "DEMO_30_MIN_REAL_RUNNER_DEPLOYED"):
        env[k] = ""
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=str(_REPO_ROOT), timeout=timeout, check=False, env=env,
    )


def _read_src() -> str:
    return _SCRIPT.read_text(encoding="utf-8")


class TestSourceGuards:

    def test_source_is_ascii(self):
        src = _read_src()
        for i, ch in enumerate(src):
            assert ord(ch) <= 127, f"non-ASCII at {i}"

    def test_no_bybit_client_in_cli(self):
        src = _read_src()
        assert "BybitClient(" not in src
        assert "from crypto_trading_bot.exchange.bybit_client" not in src

    def test_no_bybit_executor_or_preflight_in_cli(self):
        src = _read_src()
        assert "BybitDemoExecutor" not in src
        assert "BybitDemoPreflight" not in src

    def test_no_gate_or_blueprint_builder_in_cli(self):
        src = _read_src()
        assert "execute_demo_session_gated" not in src
        assert "build_demo_api_blueprint" not in src

    def test_no_network_imports(self):
        src = _read_src()
        for tok in ("import httpx", "from httpx",
                    "import requests", "from requests"):
            assert tok not in src

    def test_dotenv_autoload_present_with_safety_guards(self):
        """FASE 28 closeout: load_dotenv eh permitido no CLI, mas exige
        garantias de seguranca:
            - override=False (nao sobrescreve env existente)
            - lazy import (dentro da funcao)
            - count-only no banner (nunca imprime valores)
        """
        src = _read_src()
        # load_dotenv eh agora aceitavel apenas dentro de _safe_load_dotenv.
        assert "_safe_load_dotenv" in src
        assert "override=False" in src
        # Nenhum print de valor da env eh feito (apenas count).
        assert "values never printed" in src


class TestArgparseRequired:

    def test_missing_profile_fails(self):
        r = _run("--capital", "5000", "--strategy", "trend_pullback",
                 "--operator-token", "TOK")
        assert r.returncode != 0

    def test_missing_capital_fails(self):
        r = _run("--profile", "personal",
                 "--strategy", "trend_pullback",
                 "--operator-token", "TOK")
        assert r.returncode != 0

    def test_missing_operator_token_fails(self):
        r = _run("--profile", "personal", "--capital", "5000",
                 "--strategy", "trend_pullback")
        assert r.returncode != 0

    def test_max_orders_not_1_rejected(self):
        r = _run("--profile", "personal", "--capital", "5000",
                 "--strategy", "trend_pullback",
                 "--operator-token", "TOK",
                 "--max-orders", "2",
                 "--readiness-only")
        assert r.returncode == 1
        assert "--max-orders must be exactly 1" in r.stdout

    def test_max_minutes_above_30_rejected(self):
        r = _run("--profile", "personal", "--capital", "5000",
                 "--strategy", "trend_pullback",
                 "--operator-token", "TOK",
                 "--max-minutes", "31",
                 "--readiness-only")
        assert r.returncode == 1
        assert "--max-minutes" in r.stdout


class TestReadinessOnly:

    def test_readiness_only_ok(self):
        r = _run("--profile", "personal", "--capital", "5000",
                 "--strategy", "trend_pullback",
                 "--operator-token", "TOK1234",
                 "--readiness-only")
        assert r.returncode == 0
        assert "Readiness:" in r.stdout
        assert "ready" in r.stdout


class TestPartialFlagsRejected:

    def test_only_apply_demo_real_rejected(self):
        r = _run("--profile", "personal", "--capital", "5000",
                 "--strategy", "trend_pullback",
                 "--operator-token", "TOK1234",
                 "--apply-demo-real")
        assert r.returncode == 1
        assert "ALL four redundant flags" in r.stdout

    def test_three_of_four_flags_rejected(self):
        r = _run("--profile", "personal", "--capital", "5000",
                 "--strategy", "trend_pullback",
                 "--operator-token", "TOK1234",
                 "--apply-demo-real",
                 "--confirm-demo-endurance",
                 "--i-understand-this-is-demo-endurance")
        assert r.returncode == 1
        assert "--execute-real" in r.stdout


class TestRealPathEnvGates:

    def test_all_four_flags_without_env_demo_rejected(self):
        r = _run("--profile", "personal", "--capital", "5000",
                 "--strategy", "trend_pullback",
                 "--operator-token", "TOK1234",
                 "--apply-demo-real",
                 "--confirm-demo-endurance",
                 "--i-understand-this-is-demo-endurance",
                 "--execute-real",
                 "--non-interactive-assume-no")
        # readiness pode passar; mas extra_blockers env vai bloquear
        assert r.returncode == 1
        assert ("TRADING_MODE" in r.stdout) or \
               ("ENABLE_DEMO_EXECUTION" in r.stdout)

    def test_live_trading_true_rejected(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "TOK1234",
            "--apply-demo-real",
            "--confirm-demo-endurance",
            "--i-understand-this-is-demo-endurance",
            "--execute-real",
            "--non-interactive-assume-no",
            env_extra={
                "ENABLE_LIVE_TRADING": "true",
                "ENABLE_DEMO_EXECUTION": "true",
                "TRADING_MODE": "demo",
                "BYBIT_DEMO_API_KEY": "x",
                "BYBIT_DEMO_API_SECRET": "y",
            },
        )
        assert r.returncode == 1
        assert "ENABLE_LIVE_TRADING" in r.stdout

    def test_non_interactive_assume_no_blocks_real_path(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--strategy", "trend_pullback",
            "--operator-token", "TOK1234",
            "--apply-demo-real",
            "--confirm-demo-endurance",
            "--i-understand-this-is-demo-endurance",
            "--execute-real",
            "--non-interactive-assume-no",
            env_extra={
                "ENABLE_DEMO_EXECUTION": "true",
                "TRADING_MODE": "demo",
                "BYBIT_DEMO_API_KEY": "x",
                "BYBIT_DEMO_API_SECRET": "y",
            },
        )
        assert r.returncode == 1
        # Mensagem clara que execucao foi declinada por nao-interativo
        assert "non-interactive" in r.stdout.lower() or \
               "declined" in r.stdout.lower()


class TestSafeDefaults:

    def test_no_real_flags_just_runs_readiness_safely(self):
        r = _run("--profile", "personal", "--capital", "5000",
                 "--strategy", "trend_pullback",
                 "--operator-token", "TOK1234")
        # Sem --readiness-only nem flags reais: readiness OK e mensagem
        # encaminhando para FASE 26 dry-run.
        assert r.returncode == 0
        assert "FASE 26" in r.stdout or "dry-run" in r.stdout.lower()


class TestOutputSanitization:

    def test_no_secrets_in_stdout(self):
        r = _run("--profile", "personal", "--capital", "5000",
                 "--strategy", "trend_pullback",
                 "--operator-token", "OPSECRETXYZ1234",
                 "--readiness-only")
        full = (r.stdout + r.stderr).lower()
        for tok in ("api_key", "api_secret", "bearer ", "x-bapi",
                    "sign=", "authorization:", "origin_string"):
            assert tok not in full
        # Token completo nunca aparece
        assert "OPSECRETXYZ1234" not in r.stdout

    def test_output_json_no_secrets(self, tmp_path):
        out = tmp_path / "endur.json"
        r = _run("--profile", "personal", "--capital", "5000",
                 "--strategy", "trend_pullback",
                 "--operator-token", "OPSECRETXYZ1234",
                 "--readiness-only",
                 "--output", str(out))
        assert r.returncode == 0
        if out.exists():
            text = out.read_text(encoding="utf-8")
            for tok in ("api_key", "api_secret", "bearer ", "x-bapi",
                        "sign=", "authorization:", "origin_string"):
                assert tok not in text.lower()
            assert "OPSECRETXYZ1234" not in text

    def test_output_path_with_dotdot_rejected(self):
        r = _run("--profile", "personal", "--capital", "5000",
                 "--strategy", "trend_pullback",
                 "--operator-token", "TOK1234",
                 "--readiness-only",
                 "--output", "../endur.json")
        assert "'..'" in r.stdout or "contains '..'" in r.stdout


class TestBannerAndMessages:

    def test_banner_mentions_real_endurance(self):
        r = _run("--profile", "personal", "--capital", "5000",
                 "--strategy", "trend_pullback",
                 "--operator-token", "TOK1234",
                 "--readiness-only")
        assert "REAL ENDURANCE GATE" in r.stdout
        assert "FASE 22 runbook" in r.stdout
        assert "Max 1 order" in r.stdout
