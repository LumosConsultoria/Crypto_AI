"""
Tests - FASE 24 microfix: no hardcoded default capital
============================================================
100% offline. ZERO network. ZERO secrets. ZERO order.

Closes microfix: removes hidden default capital of 5000.0 from:
  1. scripts/run_challenge_endurance.py (--capital was default=5000.0).
  2. ChallengeEnduranceRunner._run_session (account_size or 5000.0).

After fix:
  - CLI rejects invocation without --capital.
  - Runner raises ValueError when profile/risk_config have no account_size.
  - Both 5000 and 10000 capitals work explicitly.
  - No code path depends on capital == 5000 specifically.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


_REPO_ROOT = Path(__file__).parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "run_challenge_endurance.py"


def _run(*args: str, timeout: int = 120):
    cmd = [sys.executable, str(_SCRIPT), *args]
    return subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=str(_REPO_ROOT), timeout=timeout, check=False,
    )


# ---------------------------------------------------------------------------
# CLI: --capital is required
# ---------------------------------------------------------------------------

class TestCliRequiresCapital:

    def test_cli_without_capital_rejected_by_argparse(self):
        r = _run("--profile", "personal", "--stage", "PAPER_30_MIN")
        # argparse failure -> non-zero exit
        assert r.returncode != 0
        # Message names the missing argument (sanitized).
        assert "--capital" in (r.stdout + r.stderr)

    def test_cli_with_capital_5000_works(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--stage", "PAPER_30_MIN",
        )
        assert r.returncode == 0

    def test_cli_with_capital_10000_works(self):
        r = _run(
            "--profile", "personal", "--capital", "10000",
            "--stage", "PAPER_30_MIN",
        )
        assert r.returncode == 0

    def test_cli_with_capital_zero_rejected_by_business_rule(self):
        r = _run(
            "--profile", "personal", "--capital", "0",
            "--stage", "PAPER_30_MIN",
        )
        assert r.returncode == 1
        assert "--capital must be > 0" in r.stdout


# ---------------------------------------------------------------------------
# Source: no hidden 5000 default in CLI argument
# ---------------------------------------------------------------------------

class TestSourceHasNoHiddenDefault:

    def test_cli_capital_argument_has_no_default_5000(self):
        src = _SCRIPT.read_text(encoding="utf-8")
        # Argument declaration must not pair --capital with default=5000.0
        # (regression guard). Multi-line add_argument calls are common, so
        # search for blocks where --capital appears anywhere within a window.
        lines = src.splitlines()
        found_capital_arg = False
        for i, line in enumerate(lines):
            if "add_argument(" in line:
                # Capture a small window starting at this line.
                window = "\n".join(lines[i:i + 7])
                if '"--capital"' in window:
                    found_capital_arg = True
                    assert "default=5000" not in window, (
                        "FASE 24 microfix violated: --capital has hidden "
                        "default=5000.0"
                    )
                    assert "required=True" in window, (
                        "--capital must be required=True"
                    )
        assert found_capital_arg, "--capital argument not found in CLI"

    def test_runner_has_no_fallback_5000(self):
        runner_src = (
            _REPO_ROOT / "src" / "crypto_trading_bot"
            / "challenge_readiness" / "endurance_runner.py"
        ).read_text(encoding="utf-8")
        # Strip comments and docstrings naively.
        out_lines = []
        in_block = False
        for line in runner_src.splitlines():
            stripped = line.strip()
            if in_block:
                if stripped.endswith('"""') or stripped.endswith("'''"):
                    in_block = False
                continue
            if stripped.startswith('"""') or stripped.startswith("'''"):
                if not (stripped.endswith('"""') and len(stripped) > 3):
                    in_block = True
                continue
            if stripped.startswith("#"):
                continue
            out_lines.append(line)
        exe = "\n".join(out_lines)
        # No "or 5000" fallback in executable code.
        assert "or 5000" not in exe
        # Defensive: no literal 5000.0 in executable code path.
        assert "5000.0" not in exe


# ---------------------------------------------------------------------------
# Runner raises clear error when no capital is set
# ---------------------------------------------------------------------------

def _approve_session_result():
    return SimpleNamespace(
        total_cycles_completed=10, trades_opened=0, trades_closed=0,
        pnl_paper=0.0, drawdown_paper=0.0, consecutive_losses_final=0,
        blocks_by_safety=0, blocks_by_profile=0, blocks_by_risk=0,
        final_safety_state="normal",
        stopped_reason=SimpleNamespace(value="max_cycles"),
    )


class TestRunnerRaisesWhenNoCapital:

    def test_runner_real_path_requires_capital(self):
        """When runner is invoked WITHOUT runner_factory and the
        profile/risk_config provide no account_size_usd > 0,
        ChallengeEnduranceRunner.run() should fail with a clear error
        (not silently default to 5000.0).

        We test the helper directly to avoid needing a real
        SessionRunner setup.
        """
        from crypto_trading_bot.challenge_readiness import (
            ChallengeEnduranceRunner, ChallengeReadinessConfig,
            ChallengeEnduranceStage,
        )
        from crypto_trading_bot.config.risk_config import RiskConfig
        from crypto_trading_bot.operational_profile.profile import (
            OperationalProfile,
        )

        # Profile com account_size_usd=None
        prof = OperationalProfile(
            name="no_capital", description="no capital",
            provider_type="custom", account_size_usd=None,
        )
        # RiskConfig default has account_size_usd > 0 (pydantic enforces);
        # operator cannot easily build a RiskConfig with 0 via API.
        # Here we monkey-patch the runner to consult only profile, to
        # simulate fallback to the previous "or 5000" path.
        # Approach: simulate via a custom RiskConfig instance whose
        # account_size_usd is 0 via direct __dict__ injection (test
        # double; not used in production).
        rc = RiskConfig()
        object.__setattr__(rc, "account_size_usd", 0)

        runner = ChallengeEnduranceRunner(
            profile=prof, risk_config=rc,
            readiness_config=ChallengeReadinessConfig(
                target_stage=ChallengeEnduranceStage.PAPER_30_MIN,
                symbol="BTCUSDT",
            ),
            strategy_spec=SimpleNamespace(name="fake_strategy"),
        )
        # Readiness will fail too (account_size error blocker), but
        # the readiness gate raises EnduranceReadinessRejected. The
        # capital fallback removal is in _run_session, called only after
        # readiness OK. So we verify the readiness path first, which
        # also tells the operator there is no capital.
        from crypto_trading_bot.challenge_readiness import (
            EnduranceReadinessRejected,
        )
        with pytest.raises(EnduranceReadinessRejected):
            runner.run()


# ---------------------------------------------------------------------------
# No code path depends on capital == 5000 specifically
# ---------------------------------------------------------------------------

class TestNoLogicDependsOn5000:

    def test_cli_runs_with_arbitrary_capital_values(self):
        # Variety: 100, 2500, 7777, 12345. None should special-case 5000.
        for cap in ("100", "2500", "7777", "12345"):
            r = _run(
                "--profile", "personal", "--capital", cap,
                "--stage", "PAPER_30_MIN",
            )
            assert r.returncode == 0, f"capital={cap} failed: {r.stdout}"

    def test_runner_factory_works_with_arbitrary_capital(self):
        from crypto_trading_bot.challenge_readiness import (
            ChallengeEnduranceRunner, ChallengeReadinessConfig,
            ChallengeEnduranceStage,
        )
        from crypto_trading_bot.config.risk_config import RiskConfig
        from crypto_trading_bot.operational_profile import (
            build_personal_profile,
        )

        def _factory(**kw):
            r = MagicMock()
            r.run.return_value = _approve_session_result()
            return r

        for capital in (250.0, 1500.0, 12345.0):
            prof = build_personal_profile(account_size_usd=capital)
            runner = ChallengeEnduranceRunner(
                profile=prof, risk_config=RiskConfig(),
                readiness_config=ChallengeReadinessConfig(
                    target_stage=ChallengeEnduranceStage.PAPER_30_MIN,
                    symbol="BTCUSDT",
                ),
                runner_factory=_factory,
            )
            result = runner.run()
            assert result.account_size_usd == capital
            # Operational since runner_factory was provided.
            assert result.mode == "operational_paper_run"
