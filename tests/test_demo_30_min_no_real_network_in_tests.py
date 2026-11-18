"""
Tests - FASE 27 regression: no real network nas FASES 26+27
=================================================================
Garantia estrutural: nenhum modulo de demo_endurance/ chama rede;
testes nao instanciam BybitClient real; CLI FASE 27 nao auto-invoca
gate real.
"""

from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).parent.parent
_DEMO_ENDURANCE_DIR = (
    _REPO_ROOT / "src" / "crypto_trading_bot" / "demo_endurance"
)


def _strip_doc_and_comments(src: str) -> str:
    in_doc = False
    out = []
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
        out.append(line)
    return "\n".join(out)


# Tokens proibidos em codigo executavel.
# Nota: real_runner.py usa LAZY imports de execute_demo_session_gated /
# DemoSessionReadinessCheck APENAS dentro de _invoke_gate (com gate
# callable injetavel), o que eh aceitavel. Os testes verificam que
# nenhuma INSTANCIACAO DE CLASSES DE REDE acontece em codigo executavel
# de modulos FASE 27. Provider/runner sao testados separadamente para
# nao instanciar BybitClient/BybitDemoExecutor/BybitDemoPreflight.
_FORBIDDEN_PER_FILE = {
    "stage.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    "safety_thresholds.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    "plan.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    "readiness.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    "outcome.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    "dry_run.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    "ui_snapshot.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    "prompt_io.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    "live_blueprint_provider.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    # real_runner.py: pode importar gate/readiness_check via LAZY
    # dentro de _invoke_gate (factory injetavel substitui em testes).
    # Mas NAO pode instanciar classes de rede no codigo executavel.
    "real_runner.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "load_dotenv",
    ),
    "__init__.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    # FASE 28 - production_wiring.py: pode importar via LAZY dentro de
    # cada factory (factory injetavel substitui em testes). Mas NAO
    # pode instanciar classes de rede no codigo executavel top-level.
    "production_wiring.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "load_dotenv",
    ),
    # FASE 28 - session_telemetry.py: zero dependencia de rede.
    "session_telemetry.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    # FASE 29 - flat_check_validator.py: funcao pura.
    "flat_check_validator.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    # FASE 29 - pnl_tracker.py: callables injetaveis para fetches.
    "pnl_tracker.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    # FASE 29 - exit_resolver.py: wraps ExitPolicy FASE 11.
    "exit_resolver.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    # FASE 29 - position_monitor.py: callables injetaveis.
    "position_monitor.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    # FASE 29 - close_executor_wrapper.py: delega para executor.
    "close_executor_wrapper.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    # FASE 29 - gates_phase29.py: funcoes puras de validacao.
    "gates_phase29.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    # FASE 30 - endurance_duration.py: dataclass puro de prazo.
    "endurance_duration.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    # FASE 30 - endurance_limits.py: tetos operacionais puros.
    "endurance_limits.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    # FASE 30 - endurance_outcome.py: outcome frozen puro.
    "endurance_outcome.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    # FASE 30 - endurance_preflight.py: probes injetaveis; sem rede.
    "endurance_preflight.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    # FASE 30 - cycle_context.py: contexto frozen + sanitizacao p/ IA.
    "cycle_context.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    # FASE 30 - endurance_runner.py: tudo injetavel (market data,
    # strategy, risk, gate, prediction, IA); gate dry_run=True.
    "endurance_runner.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    # FASE 30.2 - gates_phase30.py: validacao pura.
    "gates_phase30.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "execute_demo_session_gated(", "build_demo_api_blueprint(",
        "load_dotenv",
    ),
    # FASE 30.2 - endurance_real_execution.py: lifecycle injetavel;
    # a factory de PRODUCAO invoca o gate FASE 22 (lazy) — como
    # real_runner.py. Testes nunca usam a factory (injetam fakes).
    "endurance_real_execution.py": (
        "import httpx", "from httpx", "import requests", "from requests",
        "BybitClient(", "BybitDemoExecutor(", "BybitDemoPreflight(",
        "load_dotenv",
    ),
}


class TestDemoEnduranceModulesClean:

    def test_each_module_has_no_forbidden_tokens(self):
        py_files = sorted(_DEMO_ENDURANCE_DIR.glob("*.py"))
        names_seen = []
        for f in py_files:
            names_seen.append(f.name)
            exe = _strip_doc_and_comments(f.read_text(encoding="utf-8"))
            forbidden = _FORBIDDEN_PER_FILE.get(f.name)
            assert forbidden is not None, (
                f"file {f.name} not in _FORBIDDEN_PER_FILE; add mapping."
            )
            for tok in forbidden:
                assert tok not in exe, (
                    f"forbidden token {tok!r} in {f.name}"
                )
        # Garantia que todos os arquivos esperados sao cobertos.
        for expected in _FORBIDDEN_PER_FILE.keys():
            assert expected in names_seen, f"missing: {expected}"


class TestCLIClean:

    def test_cli_endurance_clean(self):
        cli = _REPO_ROOT / "scripts" / "run_demo_30_min_endurance.py"
        src = cli.read_text(encoding="utf-8")
        exe = _strip_doc_and_comments(src)
        # FASE 28 closeout: load_dotenv aceitavel SE override=False
        # (sem sobrescrever env operacional do usuario) e valores nunca
        # impressos. Os demais tokens permanecem proibidos no top-level.
        for tok in (
            "import httpx", "from httpx",
            "import requests", "from requests",
            "BybitClient(", "BybitDemoExecutor(",
            "BybitDemoPreflight(",
            "execute_demo_session_gated(",
            "build_demo_api_blueprint(",
        ):
            assert tok not in exe, (
                f"forbidden in scripts/run_demo_30_min_endurance.py: {tok}"
            )
        # load_dotenv eh permitido apenas via _safe_load_dotenv helper
        # com override=False; valores nunca impressos.
        if "load_dotenv" in exe:
            assert "_safe_load_dotenv" in exe
            assert "override=False" in exe
            assert "values never printed" in src


class TestFase22PreservedSmoke:

    def test_run_bybit_demo_session_gated_unchanged_shape(self):
        p = _REPO_ROOT / "scripts" / "run_bybit_demo_session_gated.py"
        assert p.is_file()
        src = p.read_text(encoding="utf-8")
        # Nao deve depender do demo_endurance/real_runner.
        assert "from crypto_trading_bot.demo_endurance.real_runner" \
            not in src
        assert "Demo30MinRealRunner" not in src

    def test_demo_session_execution_intact(self):
        from crypto_trading_bot.demo_session_execution.gate import (
            execute_demo_session_gated, DemoSessionRejected,
        )
        from crypto_trading_bot.demo_session_execution.outcome import (
            RecommendedNextAction, DemoSessionOutcome,
        )
        assert callable(execute_demo_session_gated)
        assert RecommendedNextAction.READY_FOR_NEXT_DEMO_SESSION


class TestFase26PreservedSmoke:

    def test_run_demo_30_min_planned_unchanged_shape(self):
        p = _REPO_ROOT / "scripts" / "run_demo_30_min_planned.py"
        assert p.is_file()
        src = p.read_text(encoding="utf-8")
        # Nao depende do real_runner / live provider.
        assert "Demo30MinRealRunner" not in src
        assert "LiveDemoBlueprintProvider" not in src

    def test_demo_30_min_dry_run_simulator_intact(self):
        from crypto_trading_bot.demo_endurance import (
            Demo30MinDryRunSimulator, build_default_planned_blueprint,
            build_demo_30_min_plan, Demo30MinVerdict,
        )
        from datetime import datetime, timezone
        now = datetime(2026, 6, 4, tzinfo=timezone.utc)
        bp = build_default_planned_blueprint(now=now)
        plan = build_demo_30_min_plan(
            symbol="BTCUSDT", strategy_name="trend_pullback",
            max_orders=1, max_session_minutes=30,
            risk_thresholds_snapshot={},
            planned_blueprint=bp,
            operator_token="OPTOK", now=now,
        )
        sim = Demo30MinDryRunSimulator(
            plan, clock=lambda: now, sleep=lambda s: None,
        )
        out = sim.simulate()
        assert out.verdict == Demo30MinVerdict.PLANNED_DRY_RUN_OK
        assert out.mode == "dry_run_planned"
