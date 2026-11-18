"""
SessionRunner — Supervisor paper-only com gates safety/profile (FASE 17)
==========================================================================
⚠️  AVISOS OBRIGATÓRIOS:
    - PAPER-ONLY. NÃO importa BybitClient, BybitDemoExecutor,
      BybitTestnetExecutor, DemoExecutionResult, httpx, requests, providers.
    - NÃO chama record_trade_opened diretamente. Esse fluxo continua
      via BotEngine → PaperTrader → RiskEngine (intocados).
    - NÃO envia ordem real/demo/testnet. NÃO promove provider.
    - NÃO aplica risk_config_overrides do OperationalProfile no RiskEngine.
      O profile é consultado APENAS para regras de sessão.

PRESERVAÇÃO DE ESTADO ENTRE CICLOS — DESIGN INTENCIONAL:
    PaperTradingOrchestrator.run_session() cria instâncias frescas a cada
    chamada. Para preservar estado entre ciclos (open_trades,
    execution_count, consecutive_losses, etc.), o SessionRunner constrói
    o pipeline UMA vez no __init__ e roda o loop interno chamando
    bot_engine.run_once() diretamente. PaperTradingOrchestrator
    permanece intocado byte-a-byte.

GATES APLICADOS A CADA CICLO (ordem determinística):
    Pre-flight (uma vez, antes do loop):
        1. profile.allowed_symbols inclui o symbol.

    Por ciclo:
        2. Manual stop (operador chamou .stop()).
        3. SAFETY: kill_switch_enabled + safety_state crítico → STOP.
        4. PROFILE: max_session_minutes ultrapassado → STOP.
        5. PROFILE: pause_after_consecutive_losses atingido → STOP.
        6. PROFILE: max_trades_per_session atingido → STOP.
        7. SAFETY: can_open_new_position=False → BLOCK (ciclo segue,
           mas estratégia internamente continua executando — gate apenas
           registra; abertura efetiva é controlada por PaperTrader e
           consumidores futuros).
        8. PROFILE: allowed_hours_utc → BLOCK ciclo (continue).
        9. PROFILE: max_concurrent_positions atingido → BLOCK abertura
           (bot_engine.run_once é chamado mesmo assim para permitir
           gestão da posição existente, mas registra block).

Notas:
    - "BLOCK" ≠ "STOP". BLOCK registra evento e segue; STOP encerra sessão.
    - Esta camada é supervisora; ela NÃO modifica a estratégia.
      Bloqueios de abertura efetiva continuam sob responsabilidade do
      RiskEngine (sovereign) — SessionRunner apenas registra contagem
      auditável e produz métricas.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, List, Optional

from crypto_trading_bot.logging_system.logger import get_audit_logger, get_logger
from crypto_trading_bot.operational_profile import OperationalProfile
from crypto_trading_bot.operational_safety import (
    SafetyState,
    SafetyStateMachine,
)
from crypto_trading_bot.session_runner.config import SessionRunnerConfig
from crypto_trading_bot.session_runner.result import (
    BLOCK_PROFILE_CONCURRENT,
    BLOCK_PROFILE_HOURS,
    BLOCK_PROFILE_CONSECUTIVE_LOSSES,
    BLOCK_PROFILE_TIME_LIMIT,
    BLOCK_PROFILE_TRADES_PER_SESSION,
    BLOCK_RISK_ENGINE,
    BLOCK_SAFETY_STATE,
    SessionBlockEvent,
    SessionRunResult,
    SessionStopReason,
)

_logger = get_logger(__name__)
_audit = get_audit_logger(__name__)


class SessionRunner:
    """
    Supervisor de sessão paper-only com gates de safety + profile.

    Construído UMA vez por sessão. Pipeline interno (BotEngine, PaperTrader,
    RiskEngine, MockExchange, MarketDataService, FeatureEngine, strategy)
    construído UMA vez no __init__ — preserva estado entre ciclos.
    """

    def __init__(self, config: SessionRunnerConfig) -> None:
        if not isinstance(config, SessionRunnerConfig):
            raise TypeError(
                "config deve ser SessionRunnerConfig; "
                f"recebido {type(config).__name__}"
            )
        self._config = config
        self._stop_requested = False
        self._blocks: List[SessionBlockEvent] = []
        self._safety: SafetyStateMachine = (
            config.safety_state_machine or SafetyStateMachine()
        )

        # === Constrói o pipeline UMA vez (preserva estado entre ciclos) ===
        # Imports LAZY para evitar import circular (execution → bot_engine).
        # Inline aqui (não delega ao PaperTradingOrchestrator) para garantir
        # que pipeline seja construído UMA vez por SessionRunner.
        from crypto_trading_bot.core.bot_engine import BotEngine
        from crypto_trading_bot.data.feature_engine import FeatureEngine
        from crypto_trading_bot.data.market_data import MarketDataService
        from crypto_trading_bot.exchange.mock_exchange import MockExchange
        from crypto_trading_bot.execution.paper_trader import PaperTrader
        from crypto_trading_bot.risk.risk_engine import RiskEngine

        # Strategy via spec.factory — UMA vez por SessionRunner
        strategy_config = dict(config.spec.default_config)
        if config.spec_config_override:
            strategy_config.update(config.spec_config_override)
        strategy_factory_call = lambda: config.spec.factory(
            dict(strategy_config)
        )
        if config.dry_run:
            # Wrapper que força HOLD em todos os ciclos (zero execuções).
            # Reusa o wrapper do PaperTradingOrchestrator (interno mas estável).
            from crypto_trading_bot.execution.paper_orchestrator import (
                _hold_signal_factory_wrapper,
            )
            wrapper_cls = _hold_signal_factory_wrapper(
                strategy_factory_call, symbol=config.symbol
            )
            self._strategy = wrapper_cls()
        else:
            self._strategy = strategy_factory_call()

        # FASE 25 — feed paper opcional. Se feed_adapter for fornecido,
        # FeedBackedMockExchange substitui o random walk pelos candles
        # deterministicos. Sem feed: comportamento legado preservado.
        if config.feed_adapter is not None:
            from crypto_trading_bot.paper_feed.exchange import (
                FeedBackedMockExchange,
            )
            self._mock_exchange = FeedBackedMockExchange(
                feed_adapter=config.feed_adapter,
                initial_balance_usdt=float(config.capital),
                simulated_fee_pct=float(config.simulated_fee_pct),
            )
        else:
            self._mock_exchange = MockExchange(
                initial_balance_usdt=float(config.capital),
                simulated_fee_pct=float(config.simulated_fee_pct),
            )
        self._risk_engine = RiskEngine(initial_capital=float(config.capital))
        self._market_data = MarketDataService(
            exchange=self._mock_exchange,
            default_symbol=config.symbol,
            default_timeframe=config.timeframe,
        )
        # FASE 25 Bloco 1 — alinhamento estrito de features com a spec:
        # FeatureEngine.from_strategy_spec extrai ema_fast/slow/direction
        # do default_config e injeta como ema_periods. Resolve o root cause
        # do "0 trades" perpetuo causado por ema_20/ema_50 ausentes quando
        # FeatureEngine usava apenas defaults [9, 21].
        self._feature_engine = FeatureEngine.from_strategy_spec(config.spec)
        self._paper_trader = PaperTrader(
            risk_engine=self._risk_engine,
            exchange=self._mock_exchange,
        )
        # BotEngine: NÃO setamos cycle_interval — o SessionRunner controla
        # o sleep externamente via self._config.sleep para garantir clock
        # injetável e testes determinísticos.
        self._bot_engine = BotEngine(
            market_data_service=self._market_data,
            feature_engine=self._feature_engine,
            strategy=self._strategy,
            risk_engine=self._risk_engine,
            paper_trader=self._paper_trader,
            cycle_interval_seconds=0.0,
        )

        # FASE 25 — Signal exercise opt-in: instancia PaperExitOrchestrator
        # com ExitPolicy default (SL+TP). Avalia fechamento por ciclo.
        # NUNCA abre posicao. Sem isto, trades paper ficam abertos ate o
        # fim da sessao (open_positions_end > 0).
        self._paper_exit_orchestrator = None  # type: ignore[var-annotated]
        if config.signal_exercise:
            from crypto_trading_bot.execution.provider_capability import (
                ProviderCapability,
            )
            from crypto_trading_bot.exit_policy.exit_policy import ExitPolicy
            from crypto_trading_bot.exit_policy.paper_session import (
                PaperExitOrchestrator,
            )
            # Capability minima e auditavel: provider mock paper, suporta
            # SL/TP. NAO eh provider real, NAO autoriza execucao externa.
            paper_capability = ProviderCapability(
                provider_id="mock_paper",
                supports_market_order=True,
                supports_stop_loss=True,
                supports_take_profit=True,
                supports_positions_query=True,
                supports_balance_query=True,
                supports_cancel_order=True,
                is_demo_environment=False,
                is_live_environment=False,
                documented_assets=(config.symbol,),
                confirmed=False,
                confirmation_source="",
                notes=(
                    "ProviderCapability declarativa para signal exercise "
                    "paper. NAO autoriza execucao externa. ModeGuard e "
                    "RiskEngine permanecem soberanos."
                ),
            )
            exit_policy = ExitPolicy(
                provider_capability=paper_capability,
                allow_close_on_opposite_signal=False,
                require_reduce_only_for_auto_close=True,
                emergency_close_enabled=False,
            )
            self._paper_exit_orchestrator = PaperExitOrchestrator(
                paper_trader=self._paper_trader,
                exit_policy=exit_policy,
            )

        # Estado de sessão (acumulado entre ciclos)
        self._consecutive_losses = 0
        self._last_closed_count = 0  # tracking para detectar new closed trades
        self._max_equity = float(config.capital)  # para drawdown
        self._max_drawdown = 0.0

        _audit.info(
            f"SessionRunner.init | profile={config.profile.name} | "
            f"symbol={config.symbol} | capital={config.capital:.2f} | "
            f"max_cycles={config.max_cycles} | dry_run={config.dry_run} | "
            f"safety_initial={self._safety.state.value}"
        )

    # ----------------------------------------------------------------------
    # API pública
    # ----------------------------------------------------------------------

    def stop(self) -> None:
        """Sinaliza stop manual; próximo ciclo encerra a sessão."""
        self._stop_requested = True

    @property
    def is_stop_requested(self) -> bool:
        return self._stop_requested

    @property
    def paper_trader(self):
        """Acesso somente-leitura ao PaperTrader (para testes/diagnóstico)."""
        return self._paper_trader

    @property
    def safety_state_machine(self) -> SafetyStateMachine:
        return self._safety

    def feed_safety_flags(self, flags: Any) -> None:
        """
        Helper duck-typed: delega para SafetyStateMachine.from_safety_flags.

        Aceita qualquer objeto com manual_review_required /
        safety_halt_recommended / etc. Nesta fase, runner em paper-only
        não tem fonte automática — método existe para integradores
        futuros (FASE 18+).
        """
        self._safety.from_safety_flags(flags)

    # ----------------------------------------------------------------------
    # Loop principal
    # ----------------------------------------------------------------------

    def run(self) -> SessionRunResult:
        """Executa a sessão. Retorna SessionRunResult imutável.

        ⚠️  Contadores **de sessão** (blocks, consecutive_losses, drawdown)
            zeram no início de cada chamada. O estado **físico** do pipeline
            (paper_trader.open_trades, execution_count, closed_trades,
            RiskEngine counters) **permanece** entre chamadas de run() —
            é a invariante de preservação de estado.
        """
        cfg = self._config

        # Reset contadores de SESSÃO (não de pipeline)
        self._blocks = []
        self._consecutive_losses = 0
        # Recalcula baseline de equity a partir do RiskEngine atual
        try:
            cur = float(
                self._risk_engine.get_status_summary().get(
                    "current_capital", cfg.capital
                )
            )
        except Exception:
            cur = float(cfg.capital)
        self._max_equity = cur
        self._max_drawdown = 0.0
        # last_closed_count: alinha com o estado atual do PaperTrader
        # (assim, novos closes em ciclos da run atual avançam losses streak)
        self._last_closed_count = len(self._paper_trader.closed_trades)

        started_at = cfg.clock()
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)

        cycles_completed = 0
        stopped_reason = SessionStopReason.MAX_CYCLES

        # --- Pre-flight: allowed_symbols ---
        if (cfg.profile.allowed_symbols
                and cfg.symbol not in cfg.profile.allowed_symbols):
            self._record_block(
                cycle_index=-1,
                source=BLOCK_PROFILE_CONCURRENT,  # placeholder; ver abaixo
                reason=(
                    f"symbol {cfg.symbol!r} não está em "
                    f"profile.allowed_symbols={list(cfg.profile.allowed_symbols)}"
                ),
                metadata={"symbol": cfg.symbol},
                now=started_at,
                # FASE 17 — corrigir source para pre-flight de symbol
                _override_source_for_symbol=True,
            )
            ended_at = cfg.clock()
            if ended_at.tzinfo is None:
                ended_at = ended_at.replace(tzinfo=timezone.utc)
            return self._build_result(
                cycles_completed=0,
                stopped_reason=SessionStopReason.PROFILE_SYMBOL_NOT_ALLOWED,
                started_at=started_at,
                ended_at=ended_at,
            )

        # --- Loop de ciclos ---
        virtual_now = started_at
        for cycle_idx in range(cfg.max_cycles):
            # 1. Manual stop
            if self._stop_requested:
                stopped_reason = SessionStopReason.MANUAL_STOP
                break

            # 2. Kill switch + safety state crítico → STOP
            if (cfg.profile.kill_switch_enabled
                    and self._safety.requires_operator_ack):
                self._record_block(
                    cycle_index=cycle_idx,
                    source=BLOCK_SAFETY_STATE,
                    reason=(
                        f"kill_switch_enabled + safety_state="
                        f"{self._safety.state.value}"
                    ),
                    metadata={
                        "safety_state": self._safety.state.value,
                        "kill_switch": True,
                    },
                    now=virtual_now,
                )
                stopped_reason = SessionStopReason.KILL_SWITCH
                break

            # 3. Time limit
            if cfg.profile.max_session_minutes is not None:
                elapsed_min = (virtual_now - started_at).total_seconds() / 60.0
                if elapsed_min >= cfg.profile.max_session_minutes:
                    self._record_block(
                        cycle_index=cycle_idx,
                        source=BLOCK_PROFILE_TIME_LIMIT,
                        reason=(
                            f"max_session_minutes={cfg.profile.max_session_minutes}"
                            f" atingido (elapsed={elapsed_min:.2f} min)"
                        ),
                        metadata={"elapsed_minutes": elapsed_min},
                        now=virtual_now,
                    )
                    stopped_reason = SessionStopReason.TIME_LIMIT
                    break

            # 4. Consecutive losses
            if (cfg.profile.pause_after_consecutive_losses is not None
                    and self._consecutive_losses
                    >= cfg.profile.pause_after_consecutive_losses):
                self._record_block(
                    cycle_index=cycle_idx,
                    source=BLOCK_PROFILE_CONSECUTIVE_LOSSES,
                    reason=(
                        f"pause_after_consecutive_losses="
                        f"{cfg.profile.pause_after_consecutive_losses}"
                        f" atingido ({self._consecutive_losses} losses)"
                    ),
                    metadata={
                        "consecutive_losses": self._consecutive_losses,
                    },
                    now=virtual_now,
                )
                stopped_reason = SessionStopReason.PROFILE_CONSECUTIVE_LOSSES
                break

            # 5. Max trades per session
            if (cfg.profile.max_trades_per_session is not None
                    and self._paper_trader.execution_count
                    >= cfg.profile.max_trades_per_session):
                self._record_block(
                    cycle_index=cycle_idx,
                    source=BLOCK_PROFILE_TRADES_PER_SESSION,
                    reason=(
                        f"max_trades_per_session="
                        f"{cfg.profile.max_trades_per_session}"
                        f" atingido (executados={self._paper_trader.execution_count})"
                    ),
                    metadata={
                        "execution_count": self._paper_trader.execution_count,
                    },
                    now=virtual_now,
                )
                stopped_reason = SessionStopReason.PROFILE_TRADES_LIMIT
                break

            # 6. Safety: can_open_new_position (BLOCK, não STOP)
            if not self._safety.can_open_new_position:
                self._record_block(
                    cycle_index=cycle_idx,
                    source=BLOCK_SAFETY_STATE,
                    reason=(
                        f"safety_state={self._safety.state.value} bloqueia "
                        f"nova abertura"
                    ),
                    metadata={"safety_state": self._safety.state.value},
                    now=virtual_now,
                )

            # 7. Profile: allowed_hours_utc (BLOCK ciclo, continue)
            if cfg.profile.allowed_hours_utc:
                hour_now = virtual_now.hour
                if not _hour_in_allowed_windows(
                    hour_now, cfg.profile.allowed_hours_utc
                ):
                    self._record_block(
                        cycle_index=cycle_idx,
                        source=BLOCK_PROFILE_HOURS,
                        reason=(
                            f"hora UTC={hour_now} fora de "
                            f"allowed_hours_utc={list(cfg.profile.allowed_hours_utc)}"
                        ),
                        metadata={"hour_utc": hour_now},
                        now=virtual_now,
                    )
                    # Pula o ciclo (não chama bot_engine.run_once)
                    cycles_completed += 1
                    virtual_now = _advance_clock(
                        virtual_now, cfg.virtual_cycle_seconds
                    )
                    if cfg.cycle_interval_seconds > 0:
                        cfg.sleep(cfg.cycle_interval_seconds)
                    continue

            # 8. Profile: max_concurrent_positions (BLOCK abertura)
            n_open = len(self._paper_trader.open_trades)
            limit_concurrent = cfg.profile.max_concurrent_positions
            if isinstance(limit_concurrent, int) and n_open >= limit_concurrent:
                self._record_block(
                    cycle_index=cycle_idx,
                    source=BLOCK_PROFILE_CONCURRENT,
                    reason=(
                        f"max_concurrent_positions={limit_concurrent}"
                        f" atingido (open={n_open})"
                    ),
                    metadata={
                        "open_positions": n_open,
                        "limit": limit_concurrent,
                    },
                    now=virtual_now,
                )

            # === Executa 1 ciclo do BotEngine ===
            try:
                cycle_result = self._bot_engine.run_once()
            except Exception as e:
                _logger.error(
                    f"SessionRunner: erro no ciclo {cycle_idx}: "
                    f"{type(e).__name__}",
                    exc_info=True,
                )
                stopped_reason = SessionStopReason.ERROR
                break

            cycles_completed += 1

            # 9. Pós-ciclo: bloqueios do RiskEngine vindo do BotCycleResult
            if _cycle_was_risk_blocked(cycle_result):
                self._record_block(
                    cycle_index=cycle_idx,
                    source=BLOCK_RISK_ENGINE,
                    reason="RiskEngine bloqueou sinal do ciclo",
                    metadata={"cycle_action": _cycle_action(cycle_result)},
                    now=virtual_now,
                )

            # FASE 25 — Signal exercise: avalia fechamento de posicoes
            # abertas contra ExitPolicy (SL/TP via candle.high/low).
            # NUNCA abre posicao. Chama paper_trader.close_trade ->
            # record_trade_closed no RiskEngine.
            if self._paper_exit_orchestrator is not None:
                current_candle = self._get_current_candle()
                latest_signal = getattr(
                    cycle_result, "strategy_signal", None
                )
                self._paper_exit_orchestrator.on_candle(
                    candle=current_candle,
                    candle_idx=cycle_idx,
                    now=virtual_now,
                    latest_signal=latest_signal,
                )

            # FASE 25 — Avanca cursor do feed determinISTIco apos cada ciclo.
            # Sem feed (MockExchange random walk), nao tem efeito.
            from crypto_trading_bot.paper_feed.exchange import (
                FeedBackedMockExchange as _FBME,
            )
            if isinstance(self._mock_exchange, _FBME):
                self._mock_exchange.advance_cursor()

            # Atualiza contadores de consecutive losses e drawdown
            self._update_post_cycle_metrics()

            # Avança relógio virtual + sleep real (injetável)
            virtual_now = _advance_clock(
                virtual_now, cfg.virtual_cycle_seconds
            )
            if cfg.cycle_interval_seconds > 0:
                cfg.sleep(cfg.cycle_interval_seconds)

        # --- Encerramento ---
        ended_at = cfg.clock()
        if ended_at.tzinfo is None:
            ended_at = ended_at.replace(tzinfo=timezone.utc)

        # Reset de stop para reutilização (mesma semântica do orchestrator)
        self._stop_requested = False

        result = self._build_result(
            cycles_completed=cycles_completed,
            stopped_reason=stopped_reason,
            started_at=started_at,
            ended_at=ended_at,
        )
        _audit.info(
            f"SessionRunner.end | reason={result.stopped_reason.value} | "
            f"cycles={result.total_cycles_completed}/{result.total_cycles_requested} | "
            f"opened={result.trades_opened} closed={result.trades_closed} | "
            f"pnl={result.pnl_paper:+.2f} | blocks={result.total_blocks}"
        )
        return result

    # ----------------------------------------------------------------------
    # Internos
    # ----------------------------------------------------------------------

    def _record_block(
        self,
        *,
        cycle_index: int,
        source: str,
        reason: str,
        metadata: dict,
        now: datetime,
        _override_source_for_symbol: bool = False,
    ) -> None:
        # Pre-flight de symbol não tem block_source dedicado ainda; usamos
        # PROFILE_TRADES_PER_SESSION como agregador "profile" para que
        # consistência total_blocks == soma_por_origem permaneça válida.
        # O stopped_reason específico (PROFILE_SYMBOL_NOT_ALLOWED) cobre
        # a diferenciação humana. Para auditoria a origem permanece profile.
        if _override_source_for_symbol:
            source = BLOCK_PROFILE_TRADES_PER_SESSION
            metadata = dict(metadata)
            metadata["pre_flight"] = True
            metadata["pre_flight_kind"] = "symbol_not_allowed"
        event = SessionBlockEvent(
            cycle_index=cycle_index,
            block_source=source,
            reason=reason,
            triggered_at=now if now.tzinfo else now.replace(tzinfo=timezone.utc),
            metadata=metadata,
        )
        self._blocks.append(event)
        _audit.info(
            f"SESSION_BLOCK | cycle={event.cycle_index} | "
            f"source={event.block_source} | reason='{event.reason}'"
        )

    def _get_current_candle(self):
        """FASE 25 - candle atual para signal exercise.

        Em FeedBackedMockExchange, retorna o candle exato sob o cursor.
        Em MockExchange random walk, retorna None (signal_exercise nao
        eh usado nesta combinacao em fluxos suportados; o orchestrator
        chamado com candle=None usa entry_price como fallback para
        TIME_LIMIT/MANUAL/EMERGENCY mas NAO dispara SL/TP - garantia
        defensiva).
        """
        from crypto_trading_bot.paper_feed.exchange import (
            FeedBackedMockExchange,
        )
        if isinstance(self._mock_exchange, FeedBackedMockExchange):
            return self._mock_exchange.current_candle
        return None

    def _update_post_cycle_metrics(self) -> None:
        """Atualiza consecutive_losses e drawdown a partir do PaperTrader."""
        closed = self._paper_trader.closed_trades
        # Detecta novos trades fechados desde a última checagem
        new_closes = closed[self._last_closed_count:]
        for trade in new_closes:
            pnl = float(getattr(trade, "pnl", 0.0) or 0.0)
            if pnl < 0:
                self._consecutive_losses += 1
            else:
                # Qualquer trade não-loss zera o streak
                self._consecutive_losses = 0
        self._last_closed_count = len(closed)

        # Drawdown a partir do capital atual do RiskEngine
        try:
            summary = self._risk_engine.get_status_summary()
            current_capital = float(summary.get("current_capital", 0.0))
        except Exception:
            current_capital = float(self._config.capital)
        if current_capital > self._max_equity:
            self._max_equity = current_capital
        dd = current_capital - self._max_equity
        if dd < self._max_drawdown:
            self._max_drawdown = dd

    def _build_result(
        self,
        *,
        cycles_completed: int,
        stopped_reason: SessionStopReason,
        started_at: datetime,
        ended_at: datetime,
    ) -> SessionRunResult:
        closed = list(self._paper_trader.closed_trades)
        pnl_paper = sum(
            float(getattr(t, "pnl", 0.0) or 0.0) for t in closed
        )
        # Determine final safety state
        final_safety = self._safety.state.value
        return SessionRunResult.from_blocks(
            total_cycles_requested=self._config.max_cycles,
            total_cycles_completed=cycles_completed,
            trades_opened=self._paper_trader.execution_count,
            trades_closed=len(closed),
            pnl_paper=round(pnl_paper, 4),
            drawdown_paper=round(self._max_drawdown, 4),
            consecutive_losses_final=self._consecutive_losses,
            blocks=tuple(self._blocks),
            final_safety_state=final_safety,
            stopped_reason=stopped_reason,
            started_at=started_at,
            ended_at=ended_at,
        )


# ---------------------------------------------------------------------------
# Helpers puros
# ---------------------------------------------------------------------------

def _hour_in_allowed_windows(hour: int, windows) -> bool:
    """True se `hour` está em qualquer janela [start, end) de `windows`."""
    for entry in windows:
        if len(entry) != 2:
            continue
        start, end = entry
        if start <= hour < end:
            return True
    return False


def _advance_clock(now: datetime, virtual_seconds: float) -> datetime:
    """Avança o relógio virtual (não real)."""
    return now + timedelta(seconds=float(virtual_seconds))


def _cycle_was_risk_blocked(cycle_result) -> bool:
    """Inspeção defensiva do BotCycleResult — `risk_blocked` é estado público."""
    action = getattr(cycle_result, "action", "")
    if isinstance(action, str) and action == "risk_blocked":
        return True
    # Alguns Enums têm .value
    val = getattr(action, "value", None)
    return val == "risk_blocked"


def _cycle_action(cycle_result) -> str:
    action = getattr(cycle_result, "action", "")
    if isinstance(action, str):
        return action
    val = getattr(action, "value", None)
    return val or str(action)
