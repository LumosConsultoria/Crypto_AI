"""
Tests - Demo30MinRealRunner (FASE 27)
==========================================
100% offline. ZERO network. ZERO BybitClient real. ZERO ordem.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from crypto_trading_bot.demo_endurance import (
    Demo30MinPlan,
    Demo30MinRealRunner,
    Demo30MinVerdict,
    LiveDemoBlueprintProvider,
    PlannedDemoBlueprint,
    build_default_planned_blueprint,
    build_demo_30_min_plan,
)
from crypto_trading_bot.demo_session_execution.outcome import (
    RecommendedNextAction,
)


NOW = datetime(2026, 6, 4, 12, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def _fake_preflight():
    pf = MagicMock()
    pf.ok = True
    pf.manual_confirmations_needed = ()
    pf.abort_reason = None
    pf.abort_details = ""
    pf.market_info = MagicMock(
        symbol="BTCUSDT", tick_size=0.5, qty_step=0.001,
        min_notional_value=5.0, reference_price=65000.0,
    )
    pf.account_state = MagicMock(
        wallet_balance_usdt=5000.0, available_balance_usdt=5000.0,
        open_positions_count=0, open_orders_count=0,
        leverage_confirmable=True, leverage_value=1.0,
    )
    pf.proposal = MagicMock(
        symbol="BTCUSDT", side="buy", reference_price=65000.0,
        qty=0.003, position_size_usd=195.0,
        stop_loss=64025.0, take_profit=66950.0,
        leverage=1.0, risk_usd=2.925, capital=5000.0,
    )
    return pf


def _build_plan(*, live_blueprint_id=None):
    bp = build_default_planned_blueprint(now=NOW)
    return build_demo_30_min_plan(
        symbol="BTCUSDT", strategy_name="trend_pullback",
        max_orders=1, max_session_minutes=30,
        risk_thresholds_snapshot={"max_daily_loss_pct": 0.05},
        planned_blueprint=bp,
        operator_token="OPTOK1234567",
        now=NOW, live_blueprint_id=live_blueprint_id,
    )


def _make_runner(*, signal_action="hold", risk_approved=True,
                 gate_outcome=None, gate_callable_counter=None,
                 apply_demo_real=False, market_data_callable=None,
                 cycles_to_first_signal=1):
    """Builder de runner com fakes determinISTIcos."""
    provider = LiveDemoBlueprintProvider(
        preflight_factory=_fake_preflight, clock=lambda: NOW,
    )
    plan = _build_plan()

    risk_engine = MagicMock()
    risk_engine.validate_signal.return_value = MagicMock(
        approved=risk_approved, reason="ok"
    )

    safety = MagicMock(requires_operator_ack=False)
    mode_guard = MagicMock()
    registry = MagicMock()
    rcfg = MagicMock()
    prof = MagicMock()

    # Strategy fake: retorna signal de acordo com signal_action.
    state = {"calls": 0}
    fake_signal_actionable = MagicMock(
        is_actionable=True,
        to_trading_signal=lambda: MagicMock(
            symbol="BTCUSDT", side=MagicMock(value="buy"),
            entry_price=65000.0, stop_loss_price=64025.0,
            take_profit_price=66950.0, position_size_usd=195.0,
        ),
    )
    fake_signal_hold = MagicMock(is_actionable=False)

    def fake_strategy_factory():
        s = MagicMock()
        def eval_fn(features):
            state["calls"] += 1
            if signal_action == "hold":
                return fake_signal_hold
            if state["calls"] >= cycles_to_first_signal:
                return fake_signal_actionable
            return fake_signal_hold
        s.evaluate = eval_fn
        s.set_running = MagicMock()
        return s

    # Feature engine fake (apenas dict).
    def fake_feature_factory():
        fe = MagicMock()
        fe.compute = lambda candles: {"closes": [], "has_sufficient_data": True}
        return fe

    # Default market data devolve 1 candle (nao-vazio).
    def default_market(**kw):
        return [MagicMock(symbol="BTCUSDT", close=65000.0)]
    md_callable = market_data_callable or default_market

    # Gate callable counter
    def default_gate(*args, **kwargs):
        if gate_callable_counter is not None:
            gate_callable_counter["n"] = gate_callable_counter.get("n", 0) + 1
        if gate_outcome is not None:
            return gate_outcome
        # default: canonical filled
        return MagicMock(
            executor_called=True, executor_success=True,
            is_filled_canonical=True, requires_manual_review=False,
            safety_halt_recommended=False, final_safety_state="normal",
            outcome_reason="canonical fill",
            to_dict=lambda: {"is_filled_canonical": True},
        )

    # Session plan factory mock: evita instanciar
    # DemoSessionReadinessCheck / build_demo_session_plan reais
    # (que exigem OperationalProfile / RiskConfig validos).
    def fake_session_plan_factory(**kwargs):
        return MagicMock(name="fake_session_plan",
                         plan_id=kwargs.get("plan_id", "TEST"))

    runner = Demo30MinRealRunner(
        plan=plan, provider=provider,
        risk_engine=risk_engine, safety_machine=safety,
        mode_guard=mode_guard, provider_registry=registry,
        effective_risk_config=rcfg, profile=prof,
        operator_token="OPTOK1234567",
        market_data_callable=md_callable,
        feature_engine_factory=fake_feature_factory,
        strategy_factory=fake_strategy_factory,
        demo_executor_factory=lambda: MagicMock(),
        gate_callable=default_gate,
        post_session_check_callable=lambda ex, stage: {
            "operation": "post_session_check", "stage": stage,
            "success": True, "requires_manual_review": False,
            "sl_attached": True, "tp_attached": True,
        },
        session_plan_factory=fake_session_plan_factory,
        clock=lambda: NOW, sleep=lambda s: None,
        cycle_interval_seconds=60.0,
        apply_demo_real=apply_demo_real,
    )
    return runner, plan, provider


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRunRealHappyPath:

    def test_no_signal_yields_passed_zero_trades(self):
        runner, plan, prov = _make_runner(signal_action="hold")
        out = runner.run_real()
        assert out.verdict == Demo30MinVerdict.PASSED_ZERO_TRADES
        assert out.orders_submitted == 0
        assert out.mode == "real_endurance"
        assert out.apply_demo_real_invoked is False
        assert out.live_blueprint_id is not None
        # Recommended seguro:
        assert out.recommended_next_action == RecommendedNextAction.RETURN_TO_PAPER

    def test_signal_approved_one_canonical_fill_yields_passed_one_trade(self):
        counter = {}
        runner, plan, prov = _make_runner(
            signal_action="buy", risk_approved=True,
            gate_callable_counter=counter,
        )
        out = runner.run_real()
        assert out.verdict == Demo30MinVerdict.PASSED_ONE_TRADE
        assert out.orders_submitted == 1
        assert out.orders_filled == 1
        assert counter.get("n", 0) == 1, "gate must be called exactly 1x"

    def test_max_orders_eq_1_strict(self):
        counter = {}
        runner, plan, prov = _make_runner(
            signal_action="buy", risk_approved=True,
            gate_callable_counter=counter,
        )
        runner.run_real()
        assert counter["n"] == 1

    def test_apply_demo_real_false_means_dry_run_true_in_gate(self):
        """Quando apply_demo_real=False, gate eh chamado com dry_run=True."""
        captured = {}
        def capture_gate(plan, **kwargs):
            captured["dry_run"] = kwargs.get("dry_run")
            return MagicMock(
                executor_called=True, executor_success=True,
                is_filled_canonical=True, requires_manual_review=False,
                safety_halt_recommended=False, final_safety_state="normal",
                outcome_reason="ok",
                to_dict=lambda: {},
            )
        runner, _, _ = _make_runner(
            signal_action="buy",
            apply_demo_real=False,
        )
        runner._gate_callable = capture_gate
        runner.run_real()
        assert captured["dry_run"] is True

    def test_apply_demo_real_true_means_dry_run_false_in_gate(self):
        captured = {}
        def capture_gate(plan, **kwargs):
            captured["dry_run"] = kwargs.get("dry_run")
            return MagicMock(
                executor_called=True, executor_success=True,
                is_filled_canonical=True, requires_manual_review=False,
                safety_halt_recommended=False, final_safety_state="normal",
                outcome_reason="ok",
                to_dict=lambda: {},
            )
        runner, _, _ = _make_runner(
            signal_action="buy", apply_demo_real=True,
        )
        runner._gate_callable = capture_gate
        runner.run_real()
        assert captured["dry_run"] is False


class TestSafetyAndAbort:

    def test_safety_halt_mid_session_yields_safety_halt_ack(self):
        runner, _, _ = _make_runner(signal_action="hold")
        # Override safety state
        runner._safety_machine.requires_operator_ack = True
        out = runner.run_real()
        assert out.verdict == Demo30MinVerdict.SAFETY_HALT_ACK_NEEDED

    def test_gate_exception_yields_failed(self):
        def raising_gate(plan, **kwargs):
            raise RuntimeError("simulated gate error")
        runner, _, _ = _make_runner(signal_action="buy")
        runner._gate_callable = raising_gate
        out = runner.run_real()
        assert out.verdict == Demo30MinVerdict.FAILED

    def test_api_failures_three_strikes_manual_review(self):
        def bad_market(**kw):
            raise RuntimeError("api fail")
        runner, _, _ = _make_runner(
            signal_action="hold", market_data_callable=bad_market,
        )
        out = runner.run_real()
        assert out.verdict == Demo30MinVerdict.MANUAL_REVIEW_REQUIRED

    def test_preflight_failure_yields_not_executable(self):
        plan = _build_plan()
        prov = LiveDemoBlueprintProvider(
            preflight_factory=lambda: None, clock=lambda: NOW,
        )
        runner = Demo30MinRealRunner(
            plan=plan, provider=prov, risk_engine=MagicMock(),
            safety_machine=MagicMock(requires_operator_ack=False),
            mode_guard=MagicMock(), provider_registry=MagicMock(),
            effective_risk_config=MagicMock(), profile=MagicMock(),
            operator_token="OPTOK", market_data_callable=lambda **k: [],
            clock=lambda: NOW, sleep=lambda s: None,
            cycle_interval_seconds=60.0,
        )
        out = runner.run_real()
        assert out.verdict == Demo30MinVerdict.NOT_EXECUTABLE


class TestPosicaoAbertaNoFim:
    """Ajuste obrigatorio 3: posicao aberta no fim NAO permite
    READY_FOR_NEXT_DEMO_SESSION."""

    def test_manual_review_required_when_open_position(self):
        # Gate returns canonical mas manual_review por triangulation
        custom_outcome = MagicMock(
            executor_called=True, executor_success=True,
            is_filled_canonical=True,
            requires_manual_review=True,
            safety_halt_recommended=False, final_safety_state="normal",
            outcome_reason="triangulated",
            to_dict=lambda: {},
        )
        runner, _, _ = _make_runner(
            signal_action="buy", gate_outcome=custom_outcome,
        )
        out = runner.run_real()
        assert out.verdict == Demo30MinVerdict.MANUAL_REVIEW_REQUIRED
        # Mesmo se outcome for "passed", se posicao aberta, rec eh review:
        assert out.recommended_next_action != \
            RecommendedNextAction.READY_FOR_NEXT_DEMO_SESSION


class TestTypeChecks:

    def test_rejects_non_plan(self):
        with pytest.raises(TypeError):
            Demo30MinRealRunner(
                plan="not a plan",
                provider=LiveDemoBlueprintProvider(
                    preflight_factory=_fake_preflight, clock=lambda: NOW,
                ),
                risk_engine=MagicMock(), safety_machine=MagicMock(),
                mode_guard=MagicMock(), provider_registry=MagicMock(),
                effective_risk_config=MagicMock(), profile=MagicMock(),
                operator_token="OPTOK",
                market_data_callable=lambda **k: [],
            )

    def test_rejects_non_provider(self):
        plan = _build_plan()
        with pytest.raises(TypeError):
            Demo30MinRealRunner(
                plan=plan, provider="not a provider",
                risk_engine=MagicMock(), safety_machine=MagicMock(),
                mode_guard=MagicMock(), provider_registry=MagicMock(),
                effective_risk_config=MagicMock(), profile=MagicMock(),
                operator_token="OPTOK",
                market_data_callable=lambda **k: [],
            )

    def test_rejects_empty_operator_token(self):
        plan = _build_plan()
        prov = LiveDemoBlueprintProvider(
            preflight_factory=_fake_preflight, clock=lambda: NOW,
        )
        with pytest.raises(ValueError, match="operator_token"):
            Demo30MinRealRunner(
                plan=plan, provider=prov,
                risk_engine=MagicMock(), safety_machine=MagicMock(),
                mode_guard=MagicMock(), provider_registry=MagicMock(),
                effective_risk_config=MagicMock(), profile=MagicMock(),
                operator_token="",
                market_data_callable=lambda **k: [],
            )


class TestNeverInstantiatesNetworkClients:

    def test_runner_does_not_instantiate_bybit_client(self):
        import crypto_trading_bot.exchange.bybit_client as bcm

        def _fail(*a, **kw):
            raise RuntimeError("BybitClient should NOT be instantiated")

        with patch.object(bcm.BybitClient, "__init__", _fail):
            runner, _, _ = _make_runner(signal_action="hold")
            out = runner.run_real()
            assert out.verdict == Demo30MinVerdict.PASSED_ZERO_TRADES

    def test_runner_does_not_instantiate_bybit_demo_executor(self):
        import crypto_trading_bot.execution.bybit_demo_executor as em

        def _fail(*a, **kw):
            raise RuntimeError("BybitDemoExecutor should NOT be instantiated")

        with patch.object(em.BybitDemoExecutor, "__init__", _fail):
            runner, _, _ = _make_runner(signal_action="hold")
            out = runner.run_real()
            assert out.verdict == Demo30MinVerdict.PASSED_ZERO_TRADES

    def test_runner_does_not_instantiate_bybit_demo_preflight(self):
        import crypto_trading_bot.execution.bybit_demo_preflight as pm

        def _fail(*a, **kw):
            raise RuntimeError("BybitDemoPreflight should NOT be instantiated")

        with patch.object(pm.BybitDemoPreflight, "__init__", _fail):
            runner, _, _ = _make_runner(signal_action="hold")
            out = runner.run_real()
            # Provider usa fake; nao instancia real
            assert out.verdict == Demo30MinVerdict.PASSED_ZERO_TRADES


class TestOutcomeShape:

    def test_outcome_has_apply_demo_real_invoked(self):
        runner, _, _ = _make_runner(signal_action="hold")
        out = runner.run_real()
        assert hasattr(out, "apply_demo_real_invoked")
        assert out.apply_demo_real_invoked is False

    def test_outcome_has_live_blueprint_id(self):
        runner, _, _ = _make_runner(signal_action="hold")
        out = runner.run_real()
        assert out.live_blueprint_id is not None
        assert out.live_blueprint_id.startswith("BP-")

    def test_outcome_to_dict_no_secrets(self):
        runner, _, _ = _make_runner(signal_action="hold")
        out = runner.run_real()
        text = str(out.to_dict()).lower()
        for tok in ("api_key", "api_secret", "bearer", "x-bapi",
                    "sign=", "authorization", "origin_string"):
            assert tok not in text


class TestModuleHasNoNetworkInExecutable:

    def test_real_runner_source_clean(self):
        from pathlib import Path
        p = Path(__file__).parent.parent / "src" / "crypto_trading_bot" / \
            "demo_endurance" / "real_runner.py"
        src = p.read_text(encoding="utf-8")
        in_doc = False
        out_lines = []
        for line in src.splitlines():
            s = line.strip()
            if in_doc:
                if s.endswith('"""') or s.endswith("'''"):
                    in_doc = False
                continue
            if s.startswith('"""') or s.startswith("'''"):
                if not (s.endswith('"""') and len(s) > 3):
                    in_doc = True
                continue
            if s.startswith("#"):
                continue
            out_lines.append(line)
        exe = "\n".join(out_lines)
        # Runner pode importar PROTOCOLS / types (lazy imports
        # internos), mas nao deve instanciar classes de rede.
        for tok in (
            "import httpx", "from httpx", "import requests",
            "from requests", "load_dotenv",
            "BybitClient(", "BybitDemoExecutor(",
            "BybitDemoPreflight(",
        ):
            assert tok not in exe, f"forbidden in real_runner.py: {tok}"
