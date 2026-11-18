"""
BotEngine — Orquestrador Principal do Ciclo de Trading
========================================================
Coordena o fluxo completo: dados → features → estratégia → risco → execução.

⚠️  INVARIANTES DE SEGURANÇA (nunca podem ser violadas):
    1. ModeGuard verifica o modo antes de qualquer ciclo.
    2. HOLD/NO_TRADE NUNCA é enviado ao RiskEngine ou PaperTrader.
    3. PaperTrader NUNCA recebe sinal não aprovado pelo RiskEngine.
    4. Qualquer falha no ciclo resulta em estado seguro (sem execução).
    5. Todo ciclo produz um BotCycleResult auditável.

Fluxo de um ciclo (run_once):
    [1] ModeGuard.assert_safe_mode()
    [2] MarketDataService.get_candles(symbol, limit)
         └── vazio → BotCycleResult(action="no_candles")
    [3] FeatureEngine.compute(candles)
         └── has_sufficient_data=False → BotCycleResult(action="insufficient_data")
    [4] strategy.evaluate(features) → StrategySignal
         └── HOLD → BotCycleResult(action="hold")
         └── INACTIVE → BotCycleResult(action="strategy_inactive")
    [5] signal.to_trading_signal() → RiskEngine.validate_signal()
         └── blocked → on_signal_rejected() + BotCycleResult(action="risk_blocked")
    [6] PaperTrader.execute(risk_result)  ← SOMENTE aqui
         └── BotCycleResult(action="executed", risk_approved=True, executed=True)
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from crypto_trading_bot.config.settings import Settings, get_settings
from crypto_trading_bot.core.cycle_result import BotCycleResult
from crypto_trading_bot.core.event_bus import EventBus
from crypto_trading_bot.core.mode_guard import ModeGuard, TradingModeError
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.data.market_data import MarketDataService
from crypto_trading_bot.execution.paper_trader import PaperTrader
from crypto_trading_bot.logging_system.logger import get_audit_logger, get_logger
from crypto_trading_bot.risk.risk_engine import RiskEngine
from crypto_trading_bot.strategies.base_strategy import BaseStrategy
from crypto_trading_bot.strategies.signal_model import StrategyAction

if TYPE_CHECKING:
    # FASE 6 — apenas para type hints; evita qualquer surpresa de ordem de import.
    from crypto_trading_bot.execution.executor_protocol import ExecutorProtocol

_logger = get_logger(__name__)
_audit = get_audit_logger(__name__)


class BotEngine:
    """
    Orquestrador principal do bot de trading.

    Recebe todas as dependências por injeção (dependency injection).
    Isso garante:
    - Testabilidade: MockExchange pode ser injetado sem internet
    - Substituibilidade: qualquer BaseStrategy funciona sem mudar o engine
    - Auditabilidade: cada ciclo produz um BotCycleResult completo

    Uso:
        from crypto_trading_bot.exchange.mock_exchange import MockExchange
        from crypto_trading_bot.data.market_data import MarketDataService

        mock_exchange = MockExchange()
        market_data = MarketDataService(mock_exchange, symbol="BTCUSDT")
        feature_engine = FeatureEngine()
        strategy = EmaRsiStrategy()
        risk_engine = RiskEngine(initial_capital=5000.0)
        paper_trader = PaperTrader(risk_engine=risk_engine)

        engine = BotEngine(
            market_data_service=market_data,
            feature_engine=feature_engine,
            strategy=strategy,
            risk_engine=risk_engine,
            paper_trader=paper_trader,
        )
        strategy.set_running()
        result = engine.run_once()  # retorna BotCycleResult
    """

    def __init__(
        self,
        market_data_service: MarketDataService,
        feature_engine: FeatureEngine,
        strategy: BaseStrategy,
        risk_engine: RiskEngine,
        paper_trader: Optional[PaperTrader] = None,
        executor: Optional["ExecutorProtocol"] = None,
        settings: Optional[Settings] = None,
        mode_guard: Optional[ModeGuard] = None,
        event_bus: Optional[EventBus] = None,
        candles_limit: int = 100,
        cycle_interval_seconds: float = 60.0,
    ) -> None:
        """
        Inicializa o BotEngine com dependências injetadas.

        ⚠️  FASE 6 — Executor: forneça EXATAMENTE UM entre `paper_trader`
            (caminho legado/default) e `executor` (qualquer ExecutorProtocol,
            ex: TestnetExecutorBotAdapter). Fornecer ambos OU nenhum levanta
            ValueError. PaperTrader continua sendo o caminho recomendado/default.

        Args:
            market_data_service: Serviço de dados de mercado (real ou mock).
            feature_engine:      Calculador de indicadores técnicos.
            strategy:            Estratégia de trading (qualquer BaseStrategy).
            risk_engine:         Motor de risco — SEMPRE chamado antes do executor.
            paper_trader:        Executor simulado (legado/default) — NUNCA chamado
                                 sem aprovação do risco. Opcional se `executor` for dado.
            executor:            FASE 6 — executor alternativo que satisfaz
                                 ExecutorProtocol (ex: TestnetExecutorBotAdapter).
                                 Mutuamente exclusivo com paper_trader.
            settings:            Configurações gerais. Se None, carrega do .env.
            mode_guard:          Guarda de modo. Se None, cria a partir de settings.
            event_bus:           Barramento de eventos. Se None, cria novo.
            candles_limit:       Número de candles a buscar por ciclo (default: 100).
            cycle_interval_seconds: Intervalo entre ciclos em modo contínuo (default: 60s).

        Raises:
            ValueError: Se ambos paper_trader e executor forem fornecidos,
                        ou se nenhum for fornecido.
        """
        # FASE 6 — Resolução do executor ativo: exatamente UM caminho.
        if paper_trader is not None and executor is not None:
            raise ValueError(
                "BotEngine recebeu paper_trader E executor ao mesmo tempo. "
                "Forneça EXATAMENTE UM: paper_trader (default/legado) OU executor."
            )
        if paper_trader is None and executor is None:
            raise ValueError(
                "BotEngine requer um executor: forneça paper_trader "
                "(legado/default) OU executor (ExecutorProtocol). Nenhum foi dado."
            )

        self._market_data = market_data_service
        self._feature_engine = feature_engine
        self._strategy = strategy
        self._risk_engine = risk_engine
        self._paper_trader = paper_trader
        self._executor = executor
        # Executor ativo usado no ciclo. Satisfaz ExecutorProtocol.execute().
        self._active_executor = executor if executor is not None else paper_trader
        self._settings = settings or get_settings()
        self._mode_guard = mode_guard or ModeGuard(self._settings)
        self._event_bus = event_bus or EventBus()
        self._candles_limit = candles_limit
        self._cycle_interval_seconds = cycle_interval_seconds

        self._running: bool = False
        self._cycle_count: int = 0

        _executor_kind = (
            "paper_trader" if self._active_executor is paper_trader
            else type(self._active_executor).__name__
        )

        # FASE 8 — Snapshot opcional do provider configurado (read-only,
        # sanitizado). Lazy import para evitar acoplamento; falhas silenciadas
        # para NUNCA quebrar o ciclo por causa de auditoria.
        self._provider_snapshot: Optional[dict] = None
        try:
            from crypto_trading_bot.execution.provider_registry import get_registry
            pid = getattr(self._settings, "provider_id", None)
            if pid:
                self._provider_snapshot = get_registry().snapshot_one(pid)
        except Exception:
            self._provider_snapshot = None

        _logger.info(
            f"BotEngine inicializado | "
            f"mode={self._settings.trading_mode.value} | "
            f"symbol={self._settings.default_symbol} | "
            f"strategy={strategy.name} | "
            f"executor={_executor_kind} | "
            f"safe={self._mode_guard.is_safe}"
        )
        _audit.info(
            f"BotEngine.init | "
            f"mode={self._settings.trading_mode.value} | "
            f"strategy={strategy.name} | "
            f"executor={_executor_kind} | "
            f"capital={risk_engine.current_capital}"
        )

    # -----------------------------------------------------------------------
    # Loop principal
    # -----------------------------------------------------------------------

    def start(self) -> None:
        """
        Inicia o loop principal do bot (bloqueante).

        O loop continua até stop() ser chamado ou KeyboardInterrupt.
        Cada iteração chama run_once() e aguarda cycle_interval_seconds.

        ⚠️  Execute em thread separada em produção.
        """
        _audit.info(
            f"BotEngine.start | "
            f"mode={self._settings.trading_mode.value} | "
            f"symbol={self._settings.default_symbol}"
        )
        self._running = True
        self._event_bus.publish("system_started", {
            "mode": self._settings.trading_mode.value,
            "symbol": self._settings.default_symbol,
            "strategy": self._strategy.name,
        })

        _logger.info(
            f"🚀 Bot iniciado | "
            f"Modo: {self._settings.trading_mode.value.upper()} | "
            f"Símbolo: {self._settings.default_symbol} | "
            f"Estratégia: {self._strategy.name}"
        )

        try:
            while self._running:
                result = self.run_once()
                _logger.info(
                    f"Ciclo #{result.cycle} | "
                    f"action={result.action} | "
                    f"risk={result.risk_approved} | "
                    f"exec={result.executed}"
                )
                time.sleep(self._cycle_interval_seconds)
        except KeyboardInterrupt:
            _logger.info("Bot interrompido pelo usuário (Ctrl+C).")
        except Exception as e:
            _logger.critical(f"Erro crítico no BotEngine: {e}")
            self._event_bus.publish("error_occurred", {"error": str(e), "critical": True})
            raise
        finally:
            self.stop()

    def stop(self) -> None:
        """Para o loop principal graciosamente."""
        if self._running:
            self._running = False
            _audit.info(
                f"BotEngine.stop | cycles_completed={self._cycle_count}"
            )
            self._event_bus.publish("system_stopped", {
                "cycles_completed": self._cycle_count,
            })
            _logger.info(f"🛑 Bot parado | Ciclos executados: {self._cycle_count}")

    # -----------------------------------------------------------------------
    # Um ciclo de decisão
    # -----------------------------------------------------------------------

    def run_once(self) -> BotCycleResult:
        """
        Executa um único ciclo completo de decisão.

        Retorna sempre um BotCycleResult — nunca lança exceção ao caller.
        Útil para testes, backtesting e debugging.

        Returns:
            BotCycleResult com todo o rastreamento do ciclo.
        """
        return self._execute_cycle()

    def _execute_cycle(self) -> BotCycleResult:
        """
        Implementação do ciclo de decisão.

        Garante as invariantes de segurança:
        - HOLD nunca vai ao RiskEngine
        - RiskEngine é sempre chamado antes do PaperTrader
        - Qualquer exceção resulta em estado seguro

        Returns:
            BotCycleResult auditável com todo o rastreamento.
        """
        self._cycle_count += 1
        symbol = self._settings.default_symbol

        result = BotCycleResult(
            cycle=self._cycle_count,
            symbol=symbol,
            mode=self._settings.trading_mode.value,
            strategy_name=self._strategy.name,
            timestamp=datetime.now(timezone.utc),
            provider_snapshot=self._provider_snapshot,   # FASE 8 — read-only metadata
        )

        _logger.debug(
            f"Ciclo #{self._cycle_count} iniciado | "
            f"symbol={symbol} | "
            f"strategy={self._strategy.name}"
        )

        try:
            # ================================================================
            # PASSO 1: Verificar ModeGuard
            # Se não for modo seguro, bloqueia imediatamente.
            # ================================================================
            self._mode_guard.assert_safe_mode()

            # ================================================================
            # PASSO 2: Coletar Dados de Mercado
            # ================================================================
            candles = self._market_data.get_candles(
                symbol=symbol,
                limit=self._candles_limit,
            )
            result.n_candles = len(candles)

            if not candles:
                result.action = "no_candles"
                result.reason = "MarketData não retornou candles"
                _logger.debug(f"Ciclo #{self._cycle_count} | Sem candles disponíveis")
                return result

            _logger.debug(
                f"Ciclo #{self._cycle_count} | "
                f"{len(candles)} candles recebidos"
            )

            # ================================================================
            # PASSO 3: Calcular Features (FeatureEngine)
            # ================================================================
            features = self._feature_engine.compute(candles)

            if not features.get("has_sufficient_data", False):
                result.action = "insufficient_data"
                result.reason = (
                    f"FeatureEngine: dados insuficientes "
                    f"({features.get('n_candles', 0)} candles)"
                )
                _logger.debug(
                    f"Ciclo #{self._cycle_count} | "
                    f"Dados insuficientes para FeatureEngine"
                )
                return result

            # ================================================================
            # PASSO 4: Avaliar Estratégia → StrategySignal (BUY/SELL/HOLD)
            # ================================================================
            strategy_signal = self._strategy.evaluate(features)
            result.strategy_signal = strategy_signal

            _logger.debug(
                f"Ciclo #{self._cycle_count} | "
                f"Estratégia: {strategy_signal.action.value.upper()} | "
                f"{strategy_signal.reason if strategy_signal.reason else ''}"
            )

            # HOLD: estratégia avaliou e decidiu não operar → ciclo seguro
            if strategy_signal.action == StrategyAction.HOLD:
                result.action = "hold"
                result.reason = strategy_signal.reason or "Estratégia retornou HOLD"
                _logger.debug(
                    f"Ciclo #{self._cycle_count} | HOLD — {result.reason}"
                )
                return result

            # Estratégia inativa (não deveria chegar aqui, mas defesa em profundidade)
            if not strategy_signal.is_actionable:
                result.action = "strategy_inactive"
                result.reason = f"Sinal não executável: {strategy_signal.action.value}"
                return result

            # ================================================================
            # PASSO 5: Converter para TradingSignal → RiskEngine
            # INVARIANTE: RiskEngine é SEMPRE chamado antes do PaperTrader.
            # INVARIANTE: HOLD nunca chega aqui (verificado acima).
            # ================================================================
            trading_signal = strategy_signal.to_trading_signal()
            risk_result = self._risk_engine.validate_signal(trading_signal)
            result.risk_result = risk_result
            result.risk_approved = risk_result.approved

            if not risk_result.approved:
                result.action = "risk_blocked"
                result.reason = f"RiskEngine: {risk_result.reason}"

                # Notifica a estratégia sobre a rejeição
                self._strategy.on_signal_rejected(trading_signal, risk_result.reason)

                _logger.info(
                    f"Ciclo #{self._cycle_count} | "
                    f"⛔ RiskEngine bloqueou: {risk_result.block_reason} | "
                    f"{risk_result.reason[:80]}"
                )
                _audit.warning(
                    f"BotEngine.ciclo_bloqueado | "
                    f"cycle={self._cycle_count} | "
                    f"symbol={symbol} | "
                    f"strategy={self._strategy.name} | "
                    f"block_reason={risk_result.block_reason}"
                )
                return result

            # ================================================================
            # PASSO 6: Executar via executor ativo (PaperTrader OU executor injetado)
            # INVARIANTE: o executor SÓ é chamado após risk_result.approved=True.
            # FASE 6: self._active_executor satisfaz ExecutorProtocol.execute().
            #         No caminho legado (paper), é exatamente o PaperTrader —
            #         comportamento idêntico ao anterior.
            # ================================================================
            # ⚠️  record_trade_opened NÃO é chamado aqui: o executor é a ÚNICA
            #     fonte de verdade do registro de abertura. PaperTrader registra
            #     ao confirmar a ordem simulada; BybitTestnetExecutor registra
            #     após fill confirmado. Chamar aqui duplicava trades_today/exposição.
            exec_result = self._active_executor.execute(risk_result)
            self._strategy.on_signal_approved(trading_signal)

            result.action = "executed"
            result.executed = True
            # FASE 6: executor_result é o campo canônico; `trade` preserva o
            # legado (mesmo valor de retorno que o PaperTrader produzia antes).
            result.executor_result = exec_result
            result.trade = exec_result
            result.reason = (
                f"Trade simulado executado | "
                f"symbol={symbol} | "
                f"side={trading_signal.side.value} | "
                f"entry={trading_signal.entry_price} | "
                f"stop={trading_signal.stop_loss_price}"
            )

            _logger.info(
                f"Ciclo #{self._cycle_count} | "
                f"✅ Trade executado | "
                f"symbol={symbol} | "
                f"side={trading_signal.side.value.upper()} | "
                f"entry={trading_signal.entry_price} | "
                f"stop={trading_signal.stop_loss_price} | "
                f"size={trading_signal.position_size_usd} USD"
            )
            _audit.info(
                f"BotEngine.ciclo_executado | "
                f"cycle={self._cycle_count} | "
                f"symbol={symbol} | "
                f"side={trading_signal.side.value} | "
                f"entry={trading_signal.entry_price} | "
                f"stop={trading_signal.stop_loss_price} | "
                f"size_usd={trading_signal.position_size_usd} | "
                f"strategy={self._strategy.name}"
            )

            # Publica evento no barramento
            self._event_bus.publish("trade_executed", {
                "cycle": self._cycle_count,
                "symbol": symbol,
                "side": trading_signal.side.value,
                "entry": trading_signal.entry_price,
                "stop": trading_signal.stop_loss_price,
            })

        except TradingModeError as e:
            # ModeGuard bloqueou — estado mais seguro: sem execução
            result.action = "safety_blocked"
            result.reason = f"ModeGuard: {e}"
            result.risk_approved = False
            result.executed = False
            _logger.error(
                f"Ciclo #{self._cycle_count} | "
                f"🔒 SAFETY BLOCK: {e}"
            )
            _audit.critical(
                f"BotEngine.safety_blocked | "
                f"cycle={self._cycle_count} | "
                f"reason={e}"
            )

        except Exception as e:
            # Qualquer erro inesperado → estado seguro: sem execução
            result.action = "error"
            result.reason = str(e)
            result.risk_approved = False
            result.executed = False
            _logger.error(
                f"Ciclo #{self._cycle_count} | "
                f"❌ Erro inesperado: {type(e).__name__}: {e}"
            )
            self._event_bus.publish("error_occurred", {
                "cycle": self._cycle_count,
                "error": str(e),
                "critical": False,
            })

        # Invariante final: was_safe deve ser True
        assert result.was_safe, (
            f"VIOLAÇÃO DE SEGURANÇA: ciclo #{self._cycle_count} "
            f"não está em estado seguro! "
            f"executed={result.executed}, risk_approved={result.risk_approved}"
        )

        _logger.debug(
            f"Ciclo #{self._cycle_count} concluído | "
            f"action={result.action} | "
            f"risk={result.risk_approved} | "
            f"exec={result.executed}"
        )

        return result

    # -----------------------------------------------------------------------
    # Propriedades
    # -----------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """True se o bot está em loop ativo."""
        return self._running

    @property
    def cycle_count(self) -> int:
        """Total de ciclos executados."""
        return self._cycle_count

    @property
    def strategy(self) -> BaseStrategy:
        """Estratégia injetada."""
        return self._strategy

    @property
    def risk_engine(self) -> RiskEngine:
        """RiskEngine injetado."""
        return self._risk_engine

    @property
    def paper_trader(self) -> Optional[PaperTrader]:
        """PaperTrader injetado (None se um executor alternativo foi usado)."""
        return self._paper_trader

    @property
    def executor(self) -> Optional["ExecutorProtocol"]:
        """Executor alternativo injetado (None no caminho legado/paper)."""
        return self._executor

    @property
    def active_executor(self):
        """Executor efetivamente usado no ciclo (paper_trader OU executor)."""
        return self._active_executor

    def get_cycle_summary(self) -> dict:
        """Retorna resumo do estado atual do engine."""
        summary = {
            "cycle_count": self._cycle_count,
            "is_running": self._running,
            "mode": self._settings.trading_mode.value,
            "symbol": self._settings.default_symbol,
            "strategy": self._strategy.name,
            "strategy_state": self._strategy.state.value,
            "strategy_signals": self._strategy.signal_count,
            "risk_summary": self._risk_engine.get_status_summary(),
        }
        # Legado: mantém a chave paper_summary quando o executor é o PaperTrader.
        if self._paper_trader is not None:
            summary["paper_summary"] = self._paper_trader.get_summary()
        elif hasattr(self._active_executor, "get_summary"):
            summary["executor_summary"] = self._active_executor.get_summary()
        return summary

    def __repr__(self) -> str:
        return (
            f"BotEngine("
            f"mode={self._settings.trading_mode.value} | "
            f"strategy={self._strategy.name} | "
            f"running={self._running} | "
            f"cycles={self._cycle_count})"
        )
