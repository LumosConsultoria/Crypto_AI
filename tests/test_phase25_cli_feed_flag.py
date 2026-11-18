"""
Tests - FASE 25 Bloco 5: CLI --feed e --signal-exercise
==========================================================
100% offline. ZERO network. ZERO secret printed.

Cobre as validacoes cruzadas e mensagens prescritas.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "run_challenge_endurance.py"


def _run(*args: str, timeout: int = 180):
    cmd = [sys.executable, str(_SCRIPT), *args]
    return subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=str(_REPO_ROOT), timeout=timeout, check=False,
    )


class TestCrossValidation:

    def test_feed_synthetic_without_signal_exercise_rejected(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--stage", "PAPER_30_MIN",
            "--strategy", "trend_pullback",
            "--feed", "synthetic_trending",
        )
        assert r.returncode == 1
        assert "signal-exercise" in (r.stdout + r.stderr)

    def test_signal_exercise_without_explicit_feed_rejected(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--stage", "PAPER_30_MIN",
            "--strategy", "trend_pullback",
            "--signal-exercise",  # sem --feed
        )
        assert r.returncode == 1
        assert "--feed" in (r.stdout + r.stderr)

    def test_legacy_feed_works_without_signal_exercise(self):
        # --feed mock_random_walk continua valido sem signal_exercise: a CLI
        # ACEITA e EXECUTA o run. mock_random_walk e NAO-DETERMINISTICO (random
        # walk sem seed) => o verdict (passed/failed) varia; exit 0=passed,
        # 2=failed mas EXECUTOU, 1=rejeicao de validacao de flag. Aqui validamos
        # que NAO foi rejeitado (executou), nao o verdict — mesmo criterio de
        # TestSignalExerciseExecution (exit in (0,2)).
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--stage", "PAPER_30_MIN",
            "--strategy", "trend_pullback",
            "--feed", "mock_random_walk",
        )
        assert r.returncode in (0, 2), (
            f"unexpected exit={r.returncode} stdout={r.stdout[:500]}"
        )
        # executou de fato (snapshot do run presente, sem ser rejeitado=exit 1)
        assert "feed_type:" in r.stdout and "mock_random_walk" in r.stdout
        assert "cycles_completed:" in r.stdout


class TestSignalExerciseExecution:

    def test_synthetic_trending_with_signal_exercise_succeeds(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--stage", "PAPER_30_MIN",
            "--strategy", "trend_pullback",
            "--feed", "synthetic_trending",
            "--signal-exercise",
        )
        # Exit 0 = passed; exit 2 = failed mas executou. Ambos valem
        # como "executou signal exercise corretamente".
        assert r.returncode in (0, 2), (
            f"unexpected exit={r.returncode} stdout={r.stdout[:500]}"
        )
        assert "feed_type:" in r.stdout
        assert "synthetic_trending" in r.stdout
        assert "signal_exercise:" in r.stdout
        assert "True" in r.stdout

    def test_prescribed_signal_exercise_notice_appears(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--stage", "PAPER_30_MIN",
            "--strategy", "trend_pullback",
            "--feed", "synthetic_trending",
            "--signal-exercise",
        )
        assert "NOT performance evidence" in r.stdout


class TestCacheMissFailsClearly:

    def test_cache_with_no_local_file_fails_no_network(self):
        # cache para symbol nao-existente: deve falhar com mensagem clara.
        # Garantia: sem download.
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--stage", "PAPER_30_MIN",
            "--symbol", "ZZZNONEXISTENT",
            "--strategy", "trend_pullback",
            "--feed", "cache",
            "--signal-exercise",
        )
        assert r.returncode == 1
        # Mensagem deve mencionar feed
        assert "feed build failed" in r.stdout


class TestNoSecretsInOutput:

    def test_signal_exercise_run_no_secrets_printed(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--stage", "PAPER_30_MIN",
            "--strategy", "trend_pullback",
            "--feed", "synthetic_trending",
            "--signal-exercise",
        )
        full = (r.stdout + r.stderr).lower()
        for tok in ("api_key", "api_secret", "bearer ", "x-bapi",
                    "sign=", "authorization:", "origin_string"):
            assert tok not in full


class TestSourceGuardsForCLI:

    def test_no_bybit_client_import_in_cli(self):
        src = _SCRIPT.read_text(encoding="utf-8")
        assert "from crypto_trading_bot.exchange.bybit_client" not in src
        assert "BybitClient(" not in src

    def test_no_httpx_or_requests_in_cli(self):
        src = _SCRIPT.read_text(encoding="utf-8")
        for tok in ("import httpx", "from httpx",
                    "import requests", "from requests"):
            assert tok not in src

    def test_no_dotenv_in_cli(self):
        src = _SCRIPT.read_text(encoding="utf-8")
        assert "load_dotenv" not in src
        assert ".env" not in src
