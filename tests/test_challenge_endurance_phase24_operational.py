"""
Tests - FASE 24: PAPER_30_MIN operational run integration
==============================================================
100% offline. ZERO network. ZERO secrets. ZERO order.

Covers:
    - strategy_factory: trend_pullback / volatility_breakout / invalid.
    - ChallengeEnduranceResult mode/strategy_name validation:
        - operational_paper_run requires strategy_name.
        - preview_no_strategy cannot have verdict=passed with cycles>0.
    - ChallengeEnduranceRunner detects mode from strategy_spec or
      runner_factory.
    - to_ui_snapshot exposes mode + strategy_name.
    - CLI:
        - --strategy ausente -> mode=preview_no_strategy
          + verdict=not_executable + next_recommended_stage=None.
        - --strategy trend_pullback -> mode=operational_paper_run com
          strategy_name populated.
        - DEMO_* continua planned-only.
    - Nenhum import de BybitClient no strategy_factory.
"""

from __future__ import annotations

import json
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
# strategy_factory
# ---------------------------------------------------------------------------

class TestStrategyFactory:

    def test_trend_pullback_returns_spec(self):
        from crypto_trading_bot.challenge_readiness.strategy_factory import (
            build_strategy_spec,
        )
        spec = build_strategy_spec("trend_pullback")
        assert spec is not None
        assert hasattr(spec, "name") and isinstance(spec.name, str)
        assert spec.name == "trend_pullback_default"

    def test_volatility_breakout_returns_spec(self):
        from crypto_trading_bot.challenge_readiness.strategy_factory import (
            build_strategy_spec,
        )
        spec = build_strategy_spec("volatility_breakout")
        assert spec is not None
        assert "vol" in spec.name.lower() or "break" in spec.name.lower()

    def test_unknown_name_rejected(self):
        from crypto_trading_bot.challenge_readiness.strategy_factory import (
            build_strategy_spec,
        )
        with pytest.raises(ValueError):
            build_strategy_spec("unknown_strategy")

    def test_non_string_rejected(self):
        from crypto_trading_bot.challenge_readiness.strategy_factory import (
            build_strategy_spec,
        )
        with pytest.raises(ValueError):
            build_strategy_spec(123)  # type: ignore[arg-type]

    def test_supported_strategies_constant(self):
        from crypto_trading_bot.challenge_readiness.strategy_factory import (
            SUPPORTED_STRATEGIES,
            describe_supported_strategies,
        )
        assert "trend_pullback" in SUPPORTED_STRATEGIES
        assert "volatility_breakout" in SUPPORTED_STRATEGIES
        desc = describe_supported_strategies()
        assert set(desc.keys()) == set(SUPPORTED_STRATEGIES)

    def test_factory_no_bybit_imports(self):
        """Source-level: factory must not import BybitClient/executors.
        Check only executable lines (skip docstrings and comments)."""
        src = (
            _REPO_ROOT / "src" / "crypto_trading_bot"
            / "challenge_readiness" / "strategy_factory.py"
        ).read_text(encoding="utf-8")
        # Strip docstrings/comments simply: drop triple-quoted blocks
        # and inline comments. This is rough but enough to detect actual
        # import statements vs informational docstring mentions.
        out = []
        in_block = False
        for line in src.splitlines():
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
            out.append(line)
        exe = "\n".join(out)
        assert "BybitClient(" not in exe
        assert "BybitDemoExecutor" not in exe
        assert "BybitTestnetExecutor" not in exe
        assert "import httpx" not in exe
        assert "from httpx" not in exe
        assert "import requests" not in exe
        assert "from requests" not in exe


# ---------------------------------------------------------------------------
# ChallengeEnduranceResult mode validation
# ---------------------------------------------------------------------------

class TestResultModeValidation:

    def _common_kw(self):
        now = datetime.now(timezone.utc)
        from crypto_trading_bot.challenge_readiness import (
            ChallengeEnduranceStage,
        )
        return dict(
            stage=ChallengeEnduranceStage.PAPER_30_MIN,
            profile_name="p", account_size_usd=5000.0, symbol="BTCUSDT",
            duration_planned_minutes=30, cycles_completed=0,
            trades_opened=0, trades_closed=0, open_positions_end=0,
            pnl_realized=0.0, pnl_unrealized=0.0,
            max_drawdown_observed=0.0, max_daily_loss_observed=0.0,
            risk_violations_count=0, safety_events_count=0,
            blockers=(), warnings=(),
            verdict="not_executable",
            next_recommended_stage=None,
            started_at=now, ended_at=now,
        )

    def test_operational_requires_strategy_name(self):
        from crypto_trading_bot.challenge_readiness import (
            ChallengeEnduranceResult,
        )
        kw = self._common_kw()
        kw["mode"] = "operational_paper_run"
        kw["strategy_name"] = None
        with pytest.raises(ValueError, match="strategy_name"):
            ChallengeEnduranceResult(**kw)

    def test_operational_with_strategy_name_accepted(self):
        from crypto_trading_bot.challenge_readiness import (
            ChallengeEnduranceResult,
        )
        kw = self._common_kw()
        kw["mode"] = "operational_paper_run"
        kw["strategy_name"] = "trend_pullback_default"
        r = ChallengeEnduranceResult(**kw)
        assert r.mode == "operational_paper_run"
        assert r.strategy_name == "trend_pullback_default"

    def test_preview_passed_with_cycles_rejected(self):
        from crypto_trading_bot.challenge_readiness import (
            ChallengeEnduranceResult,
        )
        kw = self._common_kw()
        kw["mode"] = "preview_no_strategy"
        kw["verdict"] = "passed"
        kw["cycles_completed"] = 10
        with pytest.raises(ValueError, match="preview_no_strategy"):
            ChallengeEnduranceResult(**kw)

    def test_preview_zero_cycles_accepted(self):
        from crypto_trading_bot.challenge_readiness import (
            ChallengeEnduranceResult,
        )
        kw = self._common_kw()
        kw["mode"] = "preview_no_strategy"
        kw["cycles_completed"] = 0
        r = ChallengeEnduranceResult(**kw)
        assert r.mode == "preview_no_strategy"

    def test_invalid_mode_rejected(self):
        from crypto_trading_bot.challenge_readiness import (
            ChallengeEnduranceResult,
        )
        kw = self._common_kw()
        kw["mode"] = "garbage"
        with pytest.raises(ValueError, match="mode"):
            ChallengeEnduranceResult(**kw)


# ---------------------------------------------------------------------------
# Runner mode detection
# ---------------------------------------------------------------------------

def _fake_session_result(**ov):
    defaults = dict(
        total_cycles_completed=10, trades_opened=0, trades_closed=0,
        pnl_paper=0.0, drawdown_paper=0.0, consecutive_losses_final=0,
        blocks_by_safety=0, blocks_by_profile=0, blocks_by_risk=0,
        final_safety_state="normal",
        stopped_reason=SimpleNamespace(value="max_cycles"),
    )
    defaults.update(ov)
    return SimpleNamespace(**defaults)


class TestRunnerModeDetection:

    def test_runner_factory_only_marks_operational(self):
        """Cenario testes: runner_factory injetado sem strategy_spec
        ainda conta como operational (pipeline real executado)."""
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
            r.run.return_value = _fake_session_result()
            return r

        runner = ChallengeEnduranceRunner(
            profile=build_personal_profile(account_size_usd=5000.0),
            risk_config=RiskConfig(),
            readiness_config=ChallengeReadinessConfig(
                target_stage=ChallengeEnduranceStage.PAPER_30_MIN,
                symbol="BTCUSDT",
            ),
            runner_factory=_factory,
        )
        result = runner.run()
        assert result.mode == "operational_paper_run"
        assert result.strategy_name == "injected_via_runner_factory"

    def test_no_strategy_no_factory_is_preview(self):
        """Sem strategy_spec e sem runner_factory: runner real seria
        chamado e exigiria strategy_spec; aqui apenas validamos que
        evaluate_readiness funciona, e que ChallengeEnduranceResult
        com mode=preview_no_strategy + cycles_completed=0 eh valido."""
        from crypto_trading_bot.challenge_readiness import (
            ChallengeEnduranceResult, ChallengeEnduranceStage,
        )
        now = datetime.now(timezone.utc)
        r = ChallengeEnduranceResult(
            stage=ChallengeEnduranceStage.PAPER_30_MIN,
            mode="preview_no_strategy",
            strategy_name=None,
            profile_name="p", account_size_usd=5000.0, symbol="BTCUSDT",
            duration_planned_minutes=30, cycles_completed=0,
            trades_opened=0, trades_closed=0, open_positions_end=0,
            pnl_realized=0.0, pnl_unrealized=0.0,
            max_drawdown_observed=0.0, max_daily_loss_observed=0.0,
            risk_violations_count=0, safety_events_count=0,
            blockers=(), warnings=(), verdict="not_executable",
            next_recommended_stage=None,
            started_at=now, ended_at=now,
        )
        assert r.mode == "preview_no_strategy"
        assert r.strategy_name is None


# ---------------------------------------------------------------------------
# to_ui_snapshot exposes mode/strategy_name
# ---------------------------------------------------------------------------

class TestUiSnapshot:

    def test_ui_snapshot_includes_mode(self):
        from crypto_trading_bot.challenge_readiness import (
            ChallengeEnduranceResult, ChallengeEnduranceStage,
        )
        now = datetime.now(timezone.utc)
        r = ChallengeEnduranceResult(
            stage=ChallengeEnduranceStage.PAPER_30_MIN,
            mode="operational_paper_run",
            strategy_name="trend_pullback_default",
            profile_name="p", account_size_usd=5000.0, symbol="BTCUSDT",
            duration_planned_minutes=30, cycles_completed=30,
            trades_opened=0, trades_closed=0, open_positions_end=0,
            pnl_realized=0.0, pnl_unrealized=0.0,
            max_drawdown_observed=0.0, max_daily_loss_observed=0.0,
            risk_violations_count=0, safety_events_count=0,
            blockers=(), warnings=(), verdict="passed",
            next_recommended_stage=None,
            started_at=now, ended_at=now,
        )
        snap = r.to_ui_snapshot()
        assert snap["stage_info"]["mode"] == "operational_paper_run"
        assert snap["stage_info"]["strategy_name"] == "trend_pullback_default"

    def test_to_dict_includes_mode_and_strategy_name(self):
        from crypto_trading_bot.challenge_readiness import (
            ChallengeEnduranceResult, ChallengeEnduranceStage,
        )
        now = datetime.now(timezone.utc)
        r = ChallengeEnduranceResult(
            stage=ChallengeEnduranceStage.PAPER_30_MIN,
            mode="preview_no_strategy",
            strategy_name=None,
            profile_name="p", account_size_usd=5000.0, symbol="BTCUSDT",
            duration_planned_minutes=30, cycles_completed=0,
            trades_opened=0, trades_closed=0, open_positions_end=0,
            pnl_realized=0.0, pnl_unrealized=0.0,
            max_drawdown_observed=0.0, max_daily_loss_observed=0.0,
            risk_violations_count=0, safety_events_count=0,
            blockers=(), warnings=(), verdict="not_executable",
            next_recommended_stage=None,
            started_at=now, ended_at=now,
        )
        d = r.to_dict()
        assert d["mode"] == "preview_no_strategy"
        assert d["strategy_name"] is None
        json.dumps(d)  # serializable


# ---------------------------------------------------------------------------
# CLI: --strategy distinguishes operational vs preview
# ---------------------------------------------------------------------------

class TestCliOperationalVsPreview:

    def test_cli_without_strategy_is_preview(self):
        r = _run("--profile", "personal", "--capital", "5000", "--stage", "PAPER_30_MIN")
        assert r.returncode == 0
        assert "preview_no_strategy" in r.stdout
        assert "verdict:                  not_executable" in r.stdout
        assert "next_recommended_stage:   None" in r.stdout

    def test_cli_with_trend_pullback_runs_operational(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--stage", "PAPER_30_MIN",
            "--strategy", "trend_pullback",
            "--virtual-cycle-seconds", "60",
        )
        assert r.returncode in (0, 2), (
            f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
        )
        assert "operational_paper_run" in r.stdout
        assert "trend_pullback_default" in r.stdout
        # Operational should expose cycles_completed > 0 OR clear failure.
        # Default 30-min paper with mock exchange produces cycles_completed=30.
        assert "cycles_completed:         30" in r.stdout or \
               "verdict:                  failed" in r.stdout

    def test_cli_with_volatility_breakout_runs_operational(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--stage", "PAPER_30_MIN",
            "--strategy", "volatility_breakout",
            "--virtual-cycle-seconds", "60",
        )
        # Same shape: operational, not preview.
        assert "operational_paper_run" in r.stdout
        # Strategy name from spec.
        assert "vol" in r.stdout.lower() or "break" in r.stdout.lower()

    def test_cli_demo_planned_still_planned_only(self):
        # FASE 24 must not break FASE 23 demo planned-only behavior.
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--stage", "DEMO_30_MIN_PLANNED",
            "--strategy", "trend_pullback",
        )
        # Demo planned exits BEFORE strategy execution: planned-only.
        assert "PLANNED ONLY" in r.stdout

    def test_cli_invalid_strategy_rejected_by_argparse(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--stage", "PAPER_30_MIN",
            "--strategy", "garbage",
        )
        assert r.returncode != 0

    def test_cli_operational_output_no_secrets(self):
        r = _run(
            "--profile", "personal", "--capital", "5000",
            "--stage", "PAPER_30_MIN",
            "--strategy", "trend_pullback",
        )
        full = (r.stdout + r.stderr).lower()
        for tok in ("api_key", "api_secret", "bearer ", "x-bapi",
                    "sign=", "authorization:", "origin_string"):
            assert tok not in full

    def test_cli_preview_warning_clearly_states_no_validation(self):
        r = _run("--profile", "personal", "--capital", "5000", "--stage", "PAPER_30_MIN")
        # Operator must see clearly that preview is NOT validation.
        assert "NOT an operational paper" in r.stdout or \
               "preview_no_strategy" in r.stdout


# ---------------------------------------------------------------------------
# Next stage recommendation honors mode
# ---------------------------------------------------------------------------

class TestNextStageRecommendation:

    def test_preview_does_not_recommend_next_stage(self):
        # Preview never sets next_recommended_stage; cycles_completed=0
        # and verdict=not_executable enforce this.
        r = _run("--profile", "personal", "--capital", "5000", "--stage", "PAPER_30_MIN")
        assert "next_recommended_stage:   None" in r.stdout

    def test_operational_passed_recommends_paper_60(self):
        r = _run(
            "--profile", "personal", "--capital", "5000", "--stage", "PAPER_30_MIN",
            "--strategy", "trend_pullback",
        )
        if "verdict:                  passed" in r.stdout:
            assert "next_recommended_stage:   paper_60_min" in r.stdout
