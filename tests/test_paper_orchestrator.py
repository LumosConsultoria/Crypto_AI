"""
Testes do PaperTradingOrchestrator — FASE 4
==============================================
⚠️  ZERO chamadas à internet.
⚠️  ZERO API keys.
⚠️  ZERO ordens reais.
⚠️  BybitClient NUNCA é instanciado pelo orquestrador.

Cobertura:
    - PaperSessionConfig: criação, frozen, capital OBRIGATÓRIO (sem default 5000),
      validações de campos, validações por source (CACHE/INMEMORY).
    - PaperSessionResult: frozen, properties, summary_text com aviso obrigatório.
    - run_session: MOCK_EXCHANGE / CACHE / INMEMORY, HOLD strategy, BUY strategy,
      dry_run, max_cycles, manual stop.
    - Factory chamada 1× por sessão; sessões independentes.
    - Funciona com capitais variados (1000, 5000, 10000, 25000) — nenhuma
      lógica depende de capital == 5000.
    - ModeGuard preservado.
    - BybitClient NUNCA usado.
    - Invariante: todo trade executado tem risk_approved=True.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tests.helpers import StubStrategy, make_default_buy_signal

from crypto_trading_bot.backtesting.backtest_data import generate_trending_candles
from crypto_trading_bot.data.data_cache import DataCache
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.execution import (
    CandlesSource,
    PaperSessionConfig,
    PaperSessionResult,
    PaperTradingOrchestrator,
)
from crypto_trading_bot.research import StrategySpec
from crypto_trading_bot.strategies.signal_model import StrategySignal


# ---------------------------------------------------------------------------
# Helpers locais
# ---------------------------------------------------------------------------

_TS0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
_15MIN = timedelta(minutes=15)


def _hold_factory(config: Dict[str, Any]) -> StubStrategy:
    s = StubStrategy(
        signal=StrategySignal.hold("BTCUSDT", "stub"),
        block_after_trade=True,
    )
    s.set_running()
    return s


def _buy_factory(config: Dict[str, Any]) -> StubStrategy:
    s = StubStrategy(signal=make_default_buy_signal(), block_after_trade=True)
    s.set_running()
    return s


def _hold_spec(name: str = "hold_demo") -> StrategySpec:
    return StrategySpec(name=name, factory=_hold_factory)


def _buy_spec(name: str = "buy_demo") -> StrategySpec:
    return StrategySpec(name=name, factory=_buy_factory)


def _inmemory_candles(n: int = 100) -> tuple:
    return tuple(generate_trending_candles(n, trend_pct_per_candle=0.0))


# ---------------------------------------------------------------------------
# PaperSessionConfig — validações
# ---------------------------------------------------------------------------

class TestPaperSessionConfigValidation:

    def test_valid_minimal_config(self):
        cfg = PaperSessionConfig(spec=_hold_spec(), capital=1000.0)
        assert cfg.capital == 1000.0
        assert cfg.max_cycles == 100
        assert cfg.candles_source is CandlesSource.MOCK_EXCHANGE
        assert cfg.dry_run is False

    def test_config_is_frozen(self):
        cfg = PaperSessionConfig(spec=_hold_spec(), capital=1000.0)
        with pytest.raises((AttributeError, Exception)):
            cfg.capital = 9999.0  # type: ignore[misc]

    def test_capital_omitted_raises(self):
        """
        ⚠️ AJUSTE OBRIGATÓRIO: capital deve ser EXPLÍCITO, sem default 5000.
        Omitir capital deve levantar ValueError claro.
        """
        with pytest.raises(ValueError, match="capital"):
            PaperSessionConfig(spec=_hold_spec())  # type: ignore[call-arg]

    def test_capital_none_raises(self):
        with pytest.raises(ValueError, match="OBRIGAT"):
            PaperSessionConfig(spec=_hold_spec(), capital=None)

    def test_capital_zero_raises(self):
        with pytest.raises(ValueError, match="capital"):
            PaperSessionConfig(spec=_hold_spec(), capital=0.0)

    def test_capital_negative_raises(self):
        with pytest.raises(ValueError, match="capital"):
            PaperSessionConfig(spec=_hold_spec(), capital=-100.0)

    def test_max_cycles_zero_raises(self):
        with pytest.raises(ValueError, match="max_cycles"):
            PaperSessionConfig(spec=_hold_spec(), capital=1000.0, max_cycles=0)

    def test_max_cycles_negative_raises(self):
        with pytest.raises(ValueError, match="max_cycles"):
            PaperSessionConfig(spec=_hold_spec(), capital=1000.0, max_cycles=-1)

    def test_cycle_interval_negative_raises(self):
        with pytest.raises(ValueError, match="cycle_interval"):
            PaperSessionConfig(
                spec=_hold_spec(), capital=1000.0, cycle_interval_seconds=-0.1
            )

    def test_simulated_fee_pct_negative_raises(self):
        with pytest.raises(ValueError, match="simulated_fee_pct"):
            PaperSessionConfig(
                spec=_hold_spec(), capital=1000.0, simulated_fee_pct=-0.001
            )

    def test_cache_source_without_symbol_raises(self):
        with pytest.raises(ValueError, match="CACHE"):
            PaperSessionConfig(
                spec=_hold_spec(),
                capital=1000.0,
                candles_source=CandlesSource.CACHE,
                # cached_symbol/cached_timeframe ausentes
            )

    def test_inmemory_source_empty_raises(self):
        with pytest.raises(ValueError, match="INMEMORY"):
            PaperSessionConfig(
                spec=_hold_spec(),
                capital=1000.0,
                candles_source=CandlesSource.INMEMORY,
                inmemory_candles=(),
            )

    def test_inmemory_source_none_raises(self):
        with pytest.raises(ValueError, match="INMEMORY"):
            PaperSessionConfig(
                spec=_hold_spec(),
                capital=1000.0,
                candles_source=CandlesSource.INMEMORY,
                inmemory_candles=None,
            )

    def test_spec_config_override_is_read_only(self):
        cfg = PaperSessionConfig(
            spec=_hold_spec(),
            capital=1000.0,
            spec_config_override={"x": 1},
        )
        with pytest.raises(TypeError):
            cfg.spec_config_override["x"] = 999  # type: ignore[index]


# ---------------------------------------------------------------------------
# PaperSessionResult
# ---------------------------------------------------------------------------

class TestPaperSessionResult:

    def _run_minimal(self, capital: float = 1000.0, max_cycles: int = 3):
        cfg = PaperSessionConfig(
            spec=_hold_spec(),
            capital=capital,
            max_cycles=max_cycles,
        )
        return PaperTradingOrchestrator().run_session(cfg)

    def test_result_is_frozen(self):
        result = self._run_minimal()
        with pytest.raises((AttributeError, Exception)):
            result.n_cycles_completed = 9999  # type: ignore[misc]

    def test_summary_text_contains_no_guarantee_warning(self):
        result = self._run_minimal()
        text = result.summary_text()
        assert "NÃO GARANTE PERFORMANCE FUTURA" in text

    def test_summary_text_mentions_no_real_orders(self):
        result = self._run_minimal()
        text = result.summary_text()
        assert "ordem real" in text.lower() or "api key" in text.lower()

    def test_to_dict_is_serializable(self):
        import json
        result = self._run_minimal()
        d = result.to_dict()
        json.dumps(d)  # não pode lançar


# ---------------------------------------------------------------------------
# run_session — MOCK_EXCHANGE source
# ---------------------------------------------------------------------------

class TestRunSessionMockExchange:

    def test_session_executes_max_cycles(self):
        cfg = PaperSessionConfig(
            spec=_hold_spec(), capital=1000.0, max_cycles=5,
        )
        result = PaperTradingOrchestrator().run_session(cfg)
        assert result.n_cycles_completed == 5
        assert result.stopped_reason == "max_cycles"
        assert len(result.cycle_results) == 5

    def test_hold_strategy_produces_zero_executions(self):
        cfg = PaperSessionConfig(
            spec=_hold_spec(), capital=1000.0, max_cycles=10,
        )
        result = PaperTradingOrchestrator().run_session(cfg)
        assert result.total_executions == 0
        assert result.total_holds > 0

    def test_buy_strategy_produces_at_least_one_execution(self):
        """
        BUY strategy + capital suficiente para position_size_usd=200 +
        suficientes candles para FeatureEngine + cenário válido.
        Esperado: pelo menos 1 execução.
        """
        cfg = PaperSessionConfig(
            spec=_buy_spec(),
            capital=5000.0,        # capital >> position_size para RiskEngine aprovar
            max_cycles=80,         # cycles suficientes (MockExchange tem 250 candles em history)
        )
        result = PaperTradingOrchestrator().run_session(cfg)
        assert result.total_executions >= 1, (
            f"BUY strategy deveria executar pelo menos 1 trade. "
            f"executions={result.total_executions} "
            f"risk_blocked={result.total_risk_blocked} "
            f"holds={result.total_holds}"
        )


# ---------------------------------------------------------------------------
# dry_run mode
# ---------------------------------------------------------------------------

class TestDryRunMode:

    def test_dry_run_produces_zero_executions(self):
        cfg = PaperSessionConfig(
            spec=_buy_spec(),       # mesmo BUY strategy
            capital=5000.0,
            max_cycles=80,
            dry_run=True,           # dry-run ATIVO
        )
        result = PaperTradingOrchestrator().run_session(cfg)
        assert result.total_executions == 0, (
            "dry_run=True deveria forçar zero execuções, "
            f"mas foram {result.total_executions}."
        )

    def test_dry_run_marked_explicitly_in_result(self):
        """AJUSTE OBRIGATÓRIO: dry_run não pode ser mascarado como HOLD comum."""
        cfg = PaperSessionConfig(
            spec=_buy_spec(),
            capital=5000.0,
            max_cycles=5,
            dry_run=True,
        )
        result = PaperTradingOrchestrator().run_session(cfg)
        assert result.dry_run_active is True
        # E o summary_text torna explícito
        text = result.summary_text()
        assert "DRY-RUN" in text or "dry-run" in text.lower()

    def test_non_dry_run_marked_false_in_result(self):
        cfg = PaperSessionConfig(
            spec=_hold_spec(), capital=1000.0, max_cycles=3, dry_run=False,
        )
        result = PaperTradingOrchestrator().run_session(cfg)
        assert result.dry_run_active is False


# ---------------------------------------------------------------------------
# CACHE source — usa tmp_path (NUNCA toca cache real)
# ---------------------------------------------------------------------------

class TestRunSessionCacheSource:

    def test_session_loads_from_data_cache(self, tmp_path: Path):
        # Pre-popula cache em tmp_path
        cache = DataCache(base_dir=tmp_path)
        candles = generate_trending_candles(100, trend_pct_per_candle=0.0)
        cache.save(candles)

        # Patch DataCache no módulo data_cache para que toda instanciação
        # use base_dir=tmp_path (o orquestrador chama DataCache() default).
        original_init = DataCache.__init__

        def _patched_init(self, base_dir=None):
            return original_init(self, base_dir=tmp_path)

        with patch.object(DataCache, "__init__", _patched_init):
            cfg = PaperSessionConfig(
                spec=_hold_spec(),
                capital=1000.0,
                max_cycles=5,
                candles_source=CandlesSource.CACHE,
                cached_symbol="BTCUSDT",
                cached_timeframe="15",
            )
            result = PaperTradingOrchestrator().run_session(cfg)

        assert result.n_cycles_completed == 5
        assert result.stopped_reason == "max_cycles"


# ---------------------------------------------------------------------------
# INMEMORY source
# ---------------------------------------------------------------------------

class TestRunSessionInMemorySource:

    def test_session_uses_inmemory_candles(self):
        candles = _inmemory_candles(100)
        cfg = PaperSessionConfig(
            spec=_hold_spec(),
            capital=1000.0,
            max_cycles=5,
            candles_source=CandlesSource.INMEMORY,
            inmemory_candles=candles,
        )
        result = PaperTradingOrchestrator().run_session(cfg)
        assert result.n_cycles_completed == 5


# ---------------------------------------------------------------------------
# Strategy factory: chamada 1× por sessão, sessões independentes
# ---------------------------------------------------------------------------

class TestStrategyFactoryIntegration:

    def test_factory_called_once_per_session(self):
        call_count = {"n": 0}

        def counting_factory(config):
            call_count["n"] += 1
            return _hold_factory(config)

        spec = StrategySpec(name="counter", factory=counting_factory)
        cfg = PaperSessionConfig(spec=spec, capital=1000.0, max_cycles=10)
        PaperTradingOrchestrator().run_session(cfg)

        assert call_count["n"] == 1, (
            f"Factory deveria ser chamada UMA vez por sessão, "
            f"obtido {call_count['n']}"
        )

    def test_config_override_passed_to_factory(self):
        captured: List[Dict[str, Any]] = []

        def capturing_factory(config):
            captured.append(dict(config))
            return _hold_factory(config)

        spec = StrategySpec(
            name="cap",
            factory=capturing_factory,
            default_config={"a": 1, "b": 2},
        )
        cfg = PaperSessionConfig(
            spec=spec,
            capital=1000.0,
            spec_config_override={"a": 99, "c": "new"},
            max_cycles=3,
        )
        PaperTradingOrchestrator().run_session(cfg)
        # Recebeu config final = default + override
        assert captured[0] == {"a": 99, "b": 2, "c": "new"}

    def test_two_sessions_create_independent_strategies(self):
        created: List[Any] = []

        def tracking_factory(config):
            s = _hold_factory(config)
            created.append(s)
            return s

        spec = StrategySpec(name="track", factory=tracking_factory)
        cfg = PaperSessionConfig(spec=spec, capital=1000.0, max_cycles=3)

        orch = PaperTradingOrchestrator()
        orch.run_session(cfg)
        orch.run_session(cfg)

        assert len(created) == 2
        assert created[0] is not created[1]


# ---------------------------------------------------------------------------
# Capitais variados — NENHUMA lógica depende de capital == 5000
# ---------------------------------------------------------------------------

class TestVariousCapitals:

    @pytest.mark.parametrize("capital", [1000.0, 3500.0, 5000.0, 10000.0, 25000.0])
    def test_session_works_with_capital(self, capital: float):
        """
        ⚠️ AJUSTE OBRIGATÓRIO: orquestrador funciona com QUALQUER capital > 0,
        não apenas 5000.
        """
        cfg = PaperSessionConfig(
            spec=_hold_spec(), capital=capital, max_cycles=3,
        )
        result = PaperTradingOrchestrator().run_session(cfg)
        assert result.n_cycles_completed == 3
        # PaperTrader inicial: balance bate com capital
        assert result.config.capital == capital

    def test_no_logic_depends_specifically_on_capital_5000(self):
        """
        ⚠️ AJUSTE OBRIGATÓRIO: prova que sessão com capital diferente de 5000
        produz resultado equivalente em estrutura (mesmo número de ciclos, etc.).
        """
        spec = _hold_spec()
        r_1k = PaperTradingOrchestrator().run_session(
            PaperSessionConfig(spec=spec, capital=1000.0, max_cycles=5)
        )
        r_5k = PaperTradingOrchestrator().run_session(
            PaperSessionConfig(spec=spec, capital=5000.0, max_cycles=5)
        )
        r_10k = PaperTradingOrchestrator().run_session(
            PaperSessionConfig(spec=spec, capital=10000.0, max_cycles=5)
        )

        # Todas produzem o MESMO número de ciclos com HOLD strategy
        assert r_1k.n_cycles_completed == 5
        assert r_5k.n_cycles_completed == 5
        assert r_10k.n_cycles_completed == 5
        # Todas terminam por max_cycles
        assert r_1k.stopped_reason == "max_cycles"
        assert r_5k.stopped_reason == "max_cycles"
        assert r_10k.stopped_reason == "max_cycles"


# ---------------------------------------------------------------------------
# RiskEngine soberano + capital muito baixo
# ---------------------------------------------------------------------------

class TestRiskEngineSovereign:

    def test_low_capital_triggers_risk_blocked(self):
        """
        Capital ínfimo + BUY com position_size=200 → RiskEngine bloqueia.
        """
        cfg = PaperSessionConfig(
            spec=_buy_spec(),
            capital=1.0,           # capital ínfimo
            max_cycles=80,
        )
        result = PaperTradingOrchestrator().run_session(cfg)
        assert result.total_executions == 0
        assert result.total_risk_blocked > 0, (
            "Capital ínfimo deveria ter sido bloqueado pelo RiskEngine."
        )

    def test_every_executed_trade_has_risk_approved_true(self):
        """
        INVARIANTE: todo trade executado deve ter risk_approved=True
        (garantia herdada do BotEngine/PaperTrader).
        """
        cfg = PaperSessionConfig(
            spec=_buy_spec(), capital=5000.0, max_cycles=80,
        )
        result = PaperTradingOrchestrator().run_session(cfg)
        for r in result.cycle_results:
            if r.executed:
                assert r.risk_approved is True, (
                    f"Trade executado SEM risk_approved=True: "
                    f"cycle={r.cycle} action={r.action}"
                )


# ---------------------------------------------------------------------------
# Stop manual
# ---------------------------------------------------------------------------

class TestStopReasons:

    def test_max_cycles_stop_reason(self):
        cfg = PaperSessionConfig(spec=_hold_spec(), capital=1000.0, max_cycles=5)
        result = PaperTradingOrchestrator().run_session(cfg)
        assert result.stopped_reason == "max_cycles"

    def test_manual_stop_via_flag_before_run(self):
        """
        stop() pré-set sinaliza para parar antes do primeiro ciclo.
        """
        orch = PaperTradingOrchestrator()
        orch.stop()  # flag pré-setada
        cfg = PaperSessionConfig(spec=_hold_spec(), capital=1000.0, max_cycles=5)
        result = orch.run_session(cfg)
        assert result.stopped_reason == "manual_stop"
        assert result.n_cycles_completed == 0


# ---------------------------------------------------------------------------
# Segurança: BybitClient nunca instanciado, sem internet
# ---------------------------------------------------------------------------

class TestSafetyGuarantees:

    def test_orchestrator_does_not_use_bybit_client(self):
        """
        Patch o módulo BybitClient para falhar se for instanciado.
        Sessão MOCK_EXCHANGE deve completar sem tocar nele.
        """
        with patch(
            "crypto_trading_bot.exchange.bybit_client.BybitClient.__init__",
            side_effect=AssertionError("BybitClient não deve ser instanciado!"),
        ):
            cfg = PaperSessionConfig(
                spec=_hold_spec(), capital=1000.0, max_cycles=3,
            )
            result = PaperTradingOrchestrator().run_session(cfg)
            assert result.n_cycles_completed == 3

    def test_no_paper_trade_without_risk_approval(self):
        """
        Em CADA cycle_result, se executed=True → risk_approved=True.
        Invariante já testada em TestRiskEngineSovereign, replicada aqui
        com cenário mais rico.
        """
        cfg = PaperSessionConfig(
            spec=_buy_spec(), capital=10000.0, max_cycles=50,
        )
        result = PaperTradingOrchestrator().run_session(cfg)
        executed = [r for r in result.cycle_results if r.executed]
        # Pode ter 0 ou mais; o critério é a invariante
        for r in executed:
            assert r.risk_approved is True
            # E a tradução não tem 'risk_blocked'
            assert r.action == "executed"

    def test_paper_summary_present_in_result(self):
        cfg = PaperSessionConfig(spec=_hold_spec(), capital=1000.0, max_cycles=3)
        result = PaperTradingOrchestrator().run_session(cfg)
        # paper_summary é um Mapping com chaves do PaperTrader.get_summary()
        assert "open_trades" in result.paper_summary
        assert "closed_trades" in result.paper_summary
        assert "total_pnl" in result.paper_summary

    def test_risk_summary_present_in_result(self):
        cfg = PaperSessionConfig(spec=_hold_spec(), capital=1000.0, max_cycles=3)
        result = PaperTradingOrchestrator().run_session(cfg)
        # risk_summary tem campos do RiskEngine.get_status_summary()
        assert "current_capital" in result.risk_summary
