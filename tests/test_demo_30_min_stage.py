"""
Tests - DemoEnduranceStage (FASE 26 Bloco 1)
==============================================
100% offline. ZERO network. ZERO secrets.
"""

from __future__ import annotations

from crypto_trading_bot.demo_endurance import DemoEnduranceStage, is_valid_stage


class TestDemoEnduranceStage:

    def test_demo_30_min_exists(self):
        assert DemoEnduranceStage.DEMO_30_MIN.value == "demo_30_min"

    def test_is_string_enum(self):
        assert isinstance(DemoEnduranceStage.DEMO_30_MIN, str)
        assert DemoEnduranceStage.DEMO_30_MIN == "demo_30_min"

    def test_only_one_stage_in_this_phase(self):
        # Nesta fase, apenas DEMO_30_MIN. DEMO_60_MIN/DEMO_1_DAY ficam
        # para FASE 28+.
        stages = list(DemoEnduranceStage)
        assert stages == [DemoEnduranceStage.DEMO_30_MIN]

    def test_is_valid_stage_accepts_enum(self):
        assert is_valid_stage(DemoEnduranceStage.DEMO_30_MIN) is True

    def test_is_valid_stage_accepts_string(self):
        assert is_valid_stage("demo_30_min") is True

    def test_is_valid_stage_rejects_unknown(self):
        assert is_valid_stage("demo_60_min") is False
        assert is_valid_stage("paper_30_min") is False
        assert is_valid_stage(None) is False
        assert is_valid_stage(42) is False
