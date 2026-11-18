"""
PaperTradingOrchestrator — FASE 4
====================================
Orquestrador de sessões contínuas de paper trading usando o BotEngine existente
como caixa-preta.

⚠️  Sem ordens reais. Sem API key. Sem endpoint privado.
⚠️  Toda execução passa por BotEngine → RiskEngine → PaperTrader → MockExchange.
⚠️  Paper trading NÃO garante performance futura.

DESIGN:
    - BotEngine, PaperTrader, RiskEngine, MockExchange, MarketDataService,
      FeatureEngine, ModeGuard, BybitClient: NUNCA modificados.
    - Cada sessão constrói INSTÂNCIAS FRESCAS (sem state leak entre sessões).
    - Strategy é criada UMA VEZ por sessão via spec.factory(config_final).
    - capital é OBRIGATÓRIO em PaperSessionConfig — sem default 5000.
    - Source de candles: MOCK_EXCHANGE (random walk) | CACHE (FASE 3G) | INMEMORY.
    - CACHE/INMEMORY: closes extraídos e injetados em mock_exchange._price_history
      (helper interno; documentado como replay simplificado — para precisão OHLCV
      total, use BacktestEngine).

EXEMPLO DE USO:
    from crypto_trading_bot.execution import (
        PaperTradingOrchestrator, PaperSessionConfig, CandlesSource,
    )
    from crypto_trading_bot.research import StrategySpec

    spec = StrategySpec(name="demo", factory=my_factory)
    config = PaperSessionConfig(
        spec=spec,
        capital=5000.0,             # OBRIGATÓRIO — sem default
        symbol="BTCUSDT",
        timeframe="15",
        candles_source=CandlesSource.MOCK_EXCHANGE,
        max_cycles=20,
        cycle_interval_seconds=0.0,
        dry_run=False,
    )

    orch = PaperTradingOrchestrator()
    result = orch.run_session(config)
    print(result.summary_text())
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, List, Mapping, Optional, Tuple

from crypto_trading_bot.core.cycle_result import BotCycleResult
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.logging_system.logger import get_audit_logger, get_logger
from crypto_trading_bot.research.strategy_research import StrategySpec

# NOTA: BotEngine, MockExchange, MarketDataService, FeatureEngine, PaperTrader e
# RiskEngine são importados LAZY dentro de run_session() para evitar import
# circular (execution → bot_engine → execution).

_logger = get_logger(__name__)
_audit = get_audit_logger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class CandlesSource(str, Enum):
    """
    Fonte de candles para alimentar o MockExchange durante a sessão.

    MOCK_EXCHANGE:
        MockExchange gera preços via random walk (não-determinístico). Default
        para casos exploratórios e testes de pipeline.

    CACHE:
        Carrega candles do DataCache (FASE 3G) — replay determinístico.
        Requer cached_symbol e cached_timeframe na config.

    INMEMORY:
        Usa lista de candles fornecida diretamente em PaperSessionConfig.
        Requer inmemory_candles na config.

    ⚠️  CACHE e INMEMORY extraem APENAS os closes para popular
        mock_exchange._price_history. OHLCV completo NÃO é preservado por aqui.
        Para precisão OHLCV total, use BacktestEngine.
    """
    MOCK_EXCHANGE = "mock_exchange"
    CACHE = "cache"
    INMEMORY = "inmemory"


# ---------------------------------------------------------------------------
# PaperSessionConfig
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PaperSessionConfig:
    """
    Configuração imutável de uma sessão de paper trading.

    ⚠️  capital é OBRIGATÓRIO — sem default. O orquestrador NUNCA assume
        capital fixo (5000 ou outro). Usuário deve fornecer explicitamente.

    Atributos:
        spec:                  StrategySpec (FASE 3F) — define a estratégia.
        spec_config_override:  Override de config para a factory da strategy.
        symbol:                Símbolo a operar (ex: "BTCUSDT").
        timeframe:             Timeframe (ex: "15").
        capital:               Capital inicial da sessão (USD). OBRIGATÓRIO, > 0.
        candles_source:        Fonte de candles para o MockExchange.
        cached_symbol:         Symbol do cache (obrigatório se source=CACHE).
        cached_timeframe:      Timeframe do cache (obrigatório se source=CACHE).
        inmemory_candles:      Tupla de Candle (obrigatório se source=INMEMORY).
        max_cycles:            Número máximo de ciclos da sessão (> 0).
        cycle_interval_seconds:Sleep entre ciclos (>= 0). 0 = replay rápido.
        dry_run:               Se True, sessão evita execuções simuladas
                               (força HOLD; resultado deixa isso explícito).
        simulated_fee_pct:     Fee simulada do MockExchange (>= 0).
    """

    # Estratégia (FASE 3F)
    spec: StrategySpec
    spec_config_override: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )

    # Conta
    symbol: str = "BTCUSDT"
    timeframe: str = "15"

    # ⚠️  CAPITAL OBRIGATÓRIO — sem default. Por design, o usuário precisa
    # decidir conscientemente. Sentinel para detectar omissão.
    capital: Optional[float] = None

    # Source de candles
    candles_source: CandlesSource = CandlesSource.MOCK_EXCHANGE
    cached_symbol: Optional[str] = None
    cached_timeframe: Optional[str] = None
    inmemory_candles: Optional[Tuple[Candle, ...]] = None

    # Controle do loop
    max_cycles: int = 100
    cycle_interval_seconds: float = 0.0
    dry_run: bool = False

    # Custos simulados (MockExchange.simulated_fee_pct)
    simulated_fee_pct: float = 0.001

    def __post_init__(self) -> None:
        # capital é OBRIGATÓRIO
        if self.capital is None:
            raise ValueError(
                "PaperSessionConfig.capital é OBRIGATÓRIO. "
                "Forneça explicitamente (ex: capital=1000.0). "
                "Nenhum default fixo é assumido pelo orquestrador."
            )
        if self.capital <= 0:
            raise ValueError(
                f"PaperSessionConfig.capital deve ser > 0: {self.capital}"
            )
        if self.max_cycles <= 0:
            raise ValueError(
                f"PaperSessionConfig.max_cycles deve ser > 0: {self.max_cycles}"
            )
        if self.cycle_interval_seconds < 0:
            raise ValueError(
                f"cycle_interval_seconds deve ser >= 0: "
                f"{self.cycle_interval_seconds}"
            )
        if self.simulated_fee_pct < 0:
            raise ValueError(
                f"simulated_fee_pct deve ser >= 0: {self.simulated_fee_pct}"
            )
        if not isinstance(self.candles_source, CandlesSource):
            raise ValueError(
                f"candles_source deve ser CandlesSource enum: "
                f"{self.candles_source!r}"
            )

        # Validações por source
        if self.candles_source is CandlesSource.CACHE:
            if not self.cached_symbol or not self.cached_timeframe:
                raise ValueError(
                    "CandlesSource.CACHE requer cached_symbol e cached_timeframe."
                )
        elif self.candles_source is CandlesSource.INMEMORY:
            if not self.inmemory_candles:
                raise ValueError(
                    "CandlesSource.INMEMORY requer inmemory_candles não-vazio."
                )

        # Snapshot read-only de spec_config_override
        if not isinstance(self.spec_config_override, MappingProxyType):
            object.__setattr__(
                self,
                "spec_config_override",
                MappingProxyType(dict(self.spec_config_override)),
            )
        # tupla imutável para inmemory_candles
        if self.inmemory_candles is not None and not isinstance(
            self.inmemory_candles, tuple
        ):
            object.__setattr__(
                self, "inmemory_candles", tuple(self.inmemory_candles)
            )


# ---------------------------------------------------------------------------
# PaperSessionResult
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PaperSessionResult:
    """
    Resultado imutável de uma sessão de paper trading.

    ⚠️  summary_text() SEMPRE contém aviso de não-garantia.

    Atributos:
        config:               PaperSessionConfig usada.
        n_cycles_completed:   Número de ciclos efetivamente executados.
        cycle_results:        Tupla de BotCycleResult (1 por ciclo).
        paper_summary:        Snapshot de PaperTrader.get_summary().
        risk_summary:         Snapshot de RiskEngine.get_status_summary().
        started_at:           Timestamp de início.
        ended_at:             Timestamp de término.
        stopped_reason:       "max_cycles" | "manual_stop" | "error" |
                              "out_of_candles" | "safety_blocked_repeatedly"
        dry_run_active:       Se True, a sessão foi dry_run (sem execuções).
    """

    config: PaperSessionConfig
    n_cycles_completed: int
    cycle_results: Tuple[BotCycleResult, ...]
    paper_summary: Mapping[str, Any]
    risk_summary: Mapping[str, Any]
    started_at: datetime
    ended_at: datetime
    stopped_reason: str
    dry_run_active: bool = False

    @property
    def total_executions(self) -> int:
        """Número de ciclos com trade executado."""
        return sum(1 for r in self.cycle_results if r.executed)

    @property
    def total_holds(self) -> int:
        """Número de ciclos que terminaram em HOLD."""
        return sum(1 for r in self.cycle_results if r.action == "hold")

    @property
    def total_risk_blocked(self) -> int:
        """Número de ciclos bloqueados pelo RiskEngine."""
        return sum(
            1 for r in self.cycle_results if r.action == "risk_blocked"
        )

    @property
    def total_safety_blocked(self) -> int:
        """Número de ciclos bloqueados pelo ModeGuard."""
        return sum(
            1 for r in self.cycle_results if r.action == "safety_blocked"
        )

    @property
    def total_pnl_usd(self) -> float:
        """PnL realizado dos trades fechados (do paper_summary)."""
        return float(self.paper_summary.get("total_pnl", 0.0))

    def summary_text(self) -> str:
        """
        Sumário textual da sessão. SEMPRE inclui aviso de não-garantia.
        """
        duration = (self.ended_at - self.started_at).total_seconds()
        lines = [
            "=" * 70,
            "  📋 PAPER TRADING SESSION RESULT",
            "  ⚠️  PAPER TRADING NÃO GARANTE PERFORMANCE FUTURA.",
            "  ⚠️  Nenhuma ordem real foi enviada. ZERO API key.",
            "=" * 70,
            f"  Strategy:        {self.config.spec.name}",
            f"  Symbol:          {self.config.symbol} ({self.config.timeframe})",
            f"  Capital inicial: ${self.config.capital:,.2f}",
            f"  Candles source:  {self.config.candles_source.value}",
            f"  Stopped reason:  {self.stopped_reason}",
            f"  Duration:        {duration:.2f}s",
            "",
            "─" * 70,
            "  CICLOS",
            "─" * 70,
            f"  Cycles completed:  {self.n_cycles_completed}/{self.config.max_cycles}",
            f"  Trades executed:   {self.total_executions}",
            f"  Holds:             {self.total_holds}",
            f"  Risk blocked:      {self.total_risk_blocked}",
            f"  Safety blocked:    {self.total_safety_blocked}",
        ]
        if self.dry_run_active:
            lines.append("")
            lines.append(
                "  🔍 DRY-RUN ATIVO: nenhuma execução simulada foi realizada."
            )
            lines.append(
                "     Todos os sinais BUY/SELL foram tratados como HOLD."
            )

        lines += [
            "",
            "─" * 70,
            "  PAPER TRADER SUMMARY",
            "─" * 70,
            f"  Total PnL:         ${self.total_pnl_usd:+,.2f}",
            f"  Open trades:       {self.paper_summary.get('open_trades', 0)}",
            f"  Closed trades:     {self.paper_summary.get('closed_trades', 0)}",
        ]
        win_rate = self.paper_summary.get("win_rate")
        if win_rate is not None:
            lines.append(f"  Win rate:          {win_rate:.1f}%")

        lines += [
            "",
            "=" * 70,
            "  ⚠️  REFORÇO: Paper trading com dados simulados ou históricos NÃO",
            "      garante performance em condições reais. Custos, latência,",
            "      slippage e regimes de mercado podem variar drasticamente.",
            "=" * 70,
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Serializa para dict (JSON-friendly)."""
        return {
            "strategy_name": self.config.spec.name,
            "symbol": self.config.symbol,
            "timeframe": self.config.timeframe,
            "capital": self.config.capital,
            "candles_source": self.config.candles_source.value,
            "max_cycles": self.config.max_cycles,
            "n_cycles_completed": self.n_cycles_completed,
            "stopped_reason": self.stopped_reason,
            "dry_run_active": self.dry_run_active,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "total_executions": self.total_executions,
            "total_holds": self.total_holds,
            "total_risk_blocked": self.total_risk_blocked,
            "total_safety_blocked": self.total_safety_blocked,
            "total_pnl_usd": self.total_pnl_usd,
            "paper_summary": dict(self.paper_summary),
            "risk_summary": dict(self.risk_summary),
        }


# ---------------------------------------------------------------------------
# Helpers internos (replay por closes)
# ---------------------------------------------------------------------------

def _candles_to_closes(candles: Tuple[Candle, ...]) -> List[float]:
    """
    Extrai apenas os closes dos candles para popular MockExchange._price_history.

    ⚠️  LIMITAÇÃO DOCUMENTADA: OHLCV completo NÃO é preservado por aqui.
        Apenas closes alimentam o random-walk reverso do MockExchange.
        Para precisão OHLCV total, use BacktestEngine.
    """
    return [float(c.close) for c in candles]


def _hold_signal_factory_wrapper(real_factory, symbol: str):
    """
    Cria um wrapper de factory para modo dry_run: a estratégia retornada
    SEMPRE produz HOLD em evaluate() (sobrescreve para garantir zero execução).

    Implementa via classe wrapper que delega `is_running`, `set_running` e
    callbacks ao objeto subjacente, mas força HOLD em `evaluate()`.
    """
    from crypto_trading_bot.strategies.signal_model import StrategySignal

    class _DryRunStrategyWrapper:
        """Strategy wrapper que força HOLD em todos os ciclos (dry_run)."""

        def __init__(self) -> None:
            self._inner = real_factory()
            self.name = getattr(self._inner, "name", "dry_run_wrapper")

        @property
        def is_running(self) -> bool:
            return getattr(self._inner, "is_running", False)

        def set_running(self) -> None:
            if hasattr(self._inner, "set_running"):
                self._inner.set_running()

        def evaluate(self, features):
            # DRY-RUN: sempre HOLD (independente do que a estratégia real diria).
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=getattr(self._inner, "name", "dry_run"),
                reason="dry_run: paper session dry_run ativo",
            )

        def on_signal_approved(self, signal) -> None:
            if hasattr(self._inner, "on_signal_approved"):
                self._inner.on_signal_approved(signal)

        def on_signal_rejected(self, signal, reason: str) -> None:
            if hasattr(self._inner, "on_signal_rejected"):
                self._inner.on_signal_rejected(signal, reason)

        def on_trade_closed(self, symbol, pnl: float) -> None:
            if hasattr(self._inner, "on_trade_closed"):
                self._inner.on_trade_closed(symbol, pnl)

    return _DryRunStrategyWrapper


# ---------------------------------------------------------------------------
# PaperTradingOrchestrator
# ---------------------------------------------------------------------------

class PaperTradingOrchestrator:
    """
    Orquestrador de sessões de paper trading.

    Cada chamada a `run_session()` cria instâncias FRESCAS de:
        - Strategy (via spec.factory)
        - MockExchange
        - MarketDataService
        - FeatureEngine
        - RiskEngine
        - PaperTrader
        - BotEngine

    ⚠️  Nenhum estado é compartilhado entre sessões.
    ⚠️  BybitClient NUNCA é instanciado por este orquestrador.
    ⚠️  Toda execução passa por BotEngine → RiskEngine → PaperTrader → MockExchange.
    """

    def __init__(self) -> None:
        self._stop_requested = False

    def stop(self) -> None:
        """
        Sinaliza stop manual. O próximo ciclo encerra a sessão graciosamente.
        Flag simples — uso síncrono ou cross-thread.
        """
        self._stop_requested = True

    @property
    def is_stop_requested(self) -> bool:
        return self._stop_requested

    def run_session(self, config: PaperSessionConfig) -> PaperSessionResult:
        """
        Executa uma sessão completa de paper trading.

        Args:
            config: PaperSessionConfig imutável.

        Returns:
            PaperSessionResult imutável.
        """
        # Imports LAZY para evitar import circular
        # (execution → bot_engine → execution.paper_trader)
        from crypto_trading_bot.core.bot_engine import BotEngine
        from crypto_trading_bot.data.feature_engine import FeatureEngine
        from crypto_trading_bot.data.market_data import MarketDataService
        from crypto_trading_bot.exchange.mock_exchange import MockExchange
        from crypto_trading_bot.execution.paper_trader import PaperTrader
        from crypto_trading_bot.risk.risk_engine import RiskEngine

        # NÃO resetar self._stop_requested aqui — caller pode tê-lo pré-setado
        # via stop() ANTES de chamar run_session() (caso de uso "pare antes do
        # primeiro ciclo"). O reset acontece no fim da sessão.

        started_at = datetime.now(timezone.utc)
        _audit.info(
            f"PaperTradingOrchestrator.session_start | "
            f"strategy={config.spec.name} | symbol={config.symbol} | "
            f"capital={config.capital:.2f} | "
            f"source={config.candles_source.value} | "
            f"max_cycles={config.max_cycles} | dry_run={config.dry_run}"
        )

        # === 1. Constrói config final da estratégia (merge default + override) ===
        strategy_config = dict(config.spec.default_config)
        if config.spec_config_override:
            strategy_config.update(config.spec_config_override)

        # === 2. Constrói strategy via spec.factory — UMA vez por sessão ===
        real_factory_call = lambda: config.spec.factory(dict(strategy_config))
        if config.dry_run:
            # Wrapper que força HOLD em todos os ciclos (zero execuções)
            wrapper_cls = _hold_signal_factory_wrapper(
                real_factory_call, symbol=config.symbol
            )
            strategy = wrapper_cls()
        else:
            strategy = real_factory_call()

        # === 3. Constrói MockExchange (com fee customizada) ===
        mock_exchange = MockExchange(
            initial_balance_usdt=float(config.capital),
            simulated_fee_pct=float(config.simulated_fee_pct),
        )

        # Alimenta closes se CACHE/INMEMORY (replay por closes — documentado)
        injected_closes: Optional[List[float]] = None
        if config.candles_source is CandlesSource.CACHE:
            from crypto_trading_bot.data.data_cache import DataCache
            cache = DataCache()
            candles_from_cache = cache.load(
                symbol=config.cached_symbol,
                timeframe=config.cached_timeframe,
            )
            injected_closes = _candles_to_closes(tuple(candles_from_cache))
        elif config.candles_source is CandlesSource.INMEMORY:
            injected_closes = _candles_to_closes(config.inmemory_candles)

        if injected_closes is not None:
            if not injected_closes:
                raise ValueError(
                    "Closes extraídos do source são vazios — "
                    "verifique o cache/candles inmemory."
                )
            # Padrão já usado em scripts/run_paper_trading.py — atributo público
            # de fato (apesar do underscore por convenção interna).
            mock_exchange._price_history = list(injected_closes)

        # === 4. Constrói pipeline (instâncias FRESCAS por sessão) ===
        risk_engine = RiskEngine(initial_capital=float(config.capital))
        market_data = MarketDataService(
            exchange=mock_exchange,
            default_symbol=config.symbol,
            default_timeframe=config.timeframe,
        )
        feature_engine = FeatureEngine()
        paper_trader = PaperTrader(
            risk_engine=risk_engine, exchange=mock_exchange
        )

        # BotEngine não aceita symbol/timeframe diretamente — eles vão via
        # MarketDataService.default_symbol / default_timeframe acima.
        bot_engine = BotEngine(
            market_data_service=market_data,
            feature_engine=feature_engine,
            strategy=strategy,
            risk_engine=risk_engine,
            paper_trader=paper_trader,
            cycle_interval_seconds=config.cycle_interval_seconds,
        )

        # === 5. Loop de ciclos ===
        cycle_results: List[BotCycleResult] = []
        stopped_reason = "max_cycles"

        for cycle_idx in range(config.max_cycles):
            if self._stop_requested:
                stopped_reason = "manual_stop"
                _audit.info(
                    f"PaperTradingOrchestrator.manual_stop | "
                    f"after_cycle={cycle_idx}"
                )
                break

            try:
                cycle_result = bot_engine.run_once()
            except Exception as e:
                _logger.error(
                    f"PaperTradingOrchestrator: erro no ciclo {cycle_idx}: {e}",
                    exc_info=True,
                )
                stopped_reason = "error"
                break

            cycle_results.append(cycle_result)

            # Sleep entre ciclos (0 = replay rápido)
            if config.cycle_interval_seconds > 0:
                time.sleep(config.cycle_interval_seconds)

        # === 6. Agrega resultado ===
        ended_at = datetime.now(timezone.utc)
        paper_summary = MappingProxyType(dict(paper_trader.get_summary()))
        risk_summary = MappingProxyType(
            dict(risk_engine.get_status_summary())
        )

        result = PaperSessionResult(
            config=config,
            n_cycles_completed=len(cycle_results),
            cycle_results=tuple(cycle_results),
            paper_summary=paper_summary,
            risk_summary=risk_summary,
            started_at=started_at,
            ended_at=ended_at,
            stopped_reason=stopped_reason,
            dry_run_active=config.dry_run,
        )

        _audit.info(
            f"PaperTradingOrchestrator.session_end | "
            f"cycles={result.n_cycles_completed} | "
            f"executions={result.total_executions} | "
            f"risk_blocked={result.total_risk_blocked} | "
            f"stopped_reason={stopped_reason} | "
            f"pnl={result.total_pnl_usd:+.2f}"
        )

        # Reset stop flag para PRÓXIMA sessão (não para esta — esta já terminou).
        self._stop_requested = False
        return result
