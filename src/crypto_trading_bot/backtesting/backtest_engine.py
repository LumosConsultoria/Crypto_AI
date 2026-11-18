"""
BacktestEngine — Motor de Backtesting Candle a Candle
======================================================
Simula estratégias sobre dados históricos sem lookahead bias.

⚠️  AVISOS OBRIGATÓRIOS:
    1. Resultados de backtest NÃO garantem performance futura.
    2. Este módulo é EXCLUSIVO para backtesting — ZERO ordens reais.
    3. Não usa API keys. Não conecta internet. Não usa exchanges reais.
    4. Meta de challenge NÃO encerra o backtest.

GARANTIA ANTI-LOOKAHEAD BIAS:
    Em cada candle i, a estratégia recebe APENAS candles[:i+1].
    Candles futuros (i+1, i+2, ...) são INVISÍVEIS para a estratégia.
    Entrada ocorre no preço de fechamento do candle atual.
    Stop/TP são verificados apenas nos candles posteriores ao de entrada.

FLUXO DO BACKTEST:
    Para cada candle i (a partir do min_candles):
    1. Verifica posições abertas (stop/TP no candle i)
    2. Estratégia recebe candles[:i+1] → FeatureEngine → StrategySignal
    3. Se BUY/SELL: RiskEngine.validate_signal() → soberano
    4. Se aprovado: abre BacktestTrade
    5. Atualiza equity curve
    Ao final: fecha posições abertas ao preço do último candle

REGRA DE AMBIGUIDADE (stop e TP no mesmo candle):
    ⚠️  Se candle tiver low <= stop_loss E high >= take_profit,
    o STOP LOSS é considerado atingido primeiro (abordagem conservadora).
    Documenta em docs/backtesting.md.

INTEGRAÇÃO COM RiskEngine:
    O mesmo RiskEngine de produção é usado, sem modificações.
    record_trade_opened() → registra abertura
    record_trade_closed() → atualiza capital e exposição
    Meta de challenge (challenge_profit_target_usd) NÃO bloqueia trades.

Uso:
    from crypto_trading_bot.backtesting.backtest_engine import BacktestEngine
    from crypto_trading_bot.backtesting.backtest_data import generate_trending_candles
    from crypto_trading_bot.strategies.ema_rsi_strategy import EmaRsiStrategy
    from crypto_trading_bot.risk.risk_engine import RiskEngine
    from crypto_trading_bot.data.feature_engine import FeatureEngine

    candles = generate_trending_candles(200)
    strategy = EmaRsiStrategy()
    strategy.set_running()
    risk_engine = RiskEngine(initial_capital=5000.0)
    feature_engine = FeatureEngine()

    engine = BacktestEngine(
        strategy=strategy,
        risk_engine=risk_engine,
        feature_engine=feature_engine,
        initial_capital=5000.0,
    )
    report = engine.run(candles)
    print(report.summary())
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from crypto_trading_bot.backtesting.backtest_report import BacktestReport
from crypto_trading_bot.backtesting.backtest_trade import BacktestTrade, CloseReason
from crypto_trading_bot.backtesting.execution_costs import (
    ExecutionCostConfig,
    apply_entry_costs,
    apply_exit_costs,
)
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.logging_system.logger import get_audit_logger, get_logger
from crypto_trading_bot.risk.risk_engine import RiskEngine, TradingSignal
from crypto_trading_bot.strategies.signal_model import StrategyAction, StrategySignal

_logger = get_logger(__name__)
_audit = get_audit_logger(__name__)

# Mínimo de candles para o FeatureEngine ter dados suficientes
_DEFAULT_MIN_CANDLES = 50


# ---------------------------------------------------------------------------
# FASE 3E.4B — Pending signal interno (não exportado)
# ---------------------------------------------------------------------------

@dataclass
class _PendingSignal:
    """
    Sinal aprovado pelo RiskEngine aguardando execução por latência.

    Interno ao BacktestEngine — não exportado.
    Carregado apenas dentro de `run()`; nunca atributo de instância.

    Atributos:
        trading_signal:    TradingSignal aprovado na geração.
        generated_at_idx:  índice do candle onde foi gerado.
        executes_at_idx:   generated_at_idx + entry_latency_candles.
    """
    trading_signal: TradingSignal
    generated_at_idx: int
    executes_at_idx: int


class BacktestEngine:
    """
    Motor de backtesting candle a candle com garantia anti-lookahead bias.

    ⚠️  Resultados de backtest NÃO garantem performance futura.
    ⚠️  ZERO ordens reais enviadas.
    ⚠️  Meta de challenge NÃO encerra o backtest.

    Parâmetros:
        strategy:              Estratégia a testar. Deve implementar evaluate().
        risk_engine:           Motor de risco. Soberano sobre a estratégia.
        feature_engine:        Motor de features. Calcula indicadores.
        initial_capital:       Capital inicial da simulação.
        min_candles:           Mínimo de candles antes de iniciar estratégia.
        symbol:                Símbolo negociado (para metadados).
        challenge_profit_target_usd: Meta de challenge em USD (APENAS KPI).

    Garantias de segurança:
        - A estratégia nunca vê candles futuros.
        - Toda posição passa pelo RiskEngine antes de abrir.
        - O backtest roda até o fim dos dados, independente de PnL.
        - Meta de challenge não bloqueia trades.
    """

    def __init__(
        self,
        strategy: Any,                        # BaseStrategy ou compatível
        risk_engine: RiskEngine,
        feature_engine: Optional[FeatureEngine] = None,
        initial_capital: float = 5000.0,
        min_candles: int = _DEFAULT_MIN_CANDLES,
        symbol: str = "BTCUSDT",
        challenge_profit_target_usd: Optional[float] = None,
        execution_cost_config: Optional[ExecutionCostConfig] = None,
        # FASE 12 — Integração ExitPolicy opt-in.
        # Default False preserva 100% do comportamento legado byte-a-byte.
        exit_policy: Optional[Any] = None,
        use_exit_policy: bool = False,
        # FASE 48 — saida por TEMPO (max barras em trade). Default None
        # preserva 100% do comportamento legado. Quando setado, fecha a
        # posicao por TIME_LIMIT (preco de close) se nem SL nem TP dispararem
        # apos `max_holding_candles` barras — compativel com 1 posicao.
        max_holding_candles: Optional[int] = None,
    ) -> None:
        if initial_capital <= 0:
            raise ValueError(f"initial_capital deve ser positivo: {initial_capital}")
        if min_candles < 1:
            raise ValueError(f"min_candles deve ser >= 1: {min_candles}")

        # FASE 12 — gate: flag obrigatória + policy só ativa quando flag True
        if use_exit_policy and exit_policy is None:
            raise ValueError(
                "use_exit_policy=True exige exit_policy: ExitPolicy. "
                "Passe a instância ou desligue a flag."
            )
        if use_exit_policy:
            # Import local para evitar acoplamento quando flag está desligada
            from crypto_trading_bot.exit_policy import ExitPolicy as _ExitPolicy
            if not isinstance(exit_policy, _ExitPolicy):
                raise TypeError(
                    "exit_policy deve ser ExitPolicy quando "
                    "use_exit_policy=True."
                )

        self._strategy = strategy
        self._risk_engine = risk_engine
        self._feature_engine = feature_engine or FeatureEngine()
        self._initial_capital = initial_capital
        self._min_candles = min_candles
        self._symbol = symbol
        self._challenge_profit_target_usd = challenge_profit_target_usd
        # FASE 48 — limite de barras em trade (None = sem time-exit; legado)
        if max_holding_candles is not None and max_holding_candles < 1:
            raise ValueError("max_holding_candles deve ser >= 1 ou None")
        self._max_holding_candles: Optional[int] = max_holding_candles
        # FASE 3E.1 — modelo de custos (default zero preserva FASE 3D.5)
        self._execution_cost_config = execution_cost_config or ExecutionCostConfig()
        # FASE 12 — ExitPolicy opt-in (None quando flag desligada)
        self._use_exit_policy: bool = bool(use_exit_policy)
        self._exit_policy = exit_policy if use_exit_policy else None
        # FASE 37.1 — estado de execucao (progresso/parcial/interrupt).
        self._last_run_interrupted: bool = False
        self._run_trades: List[BacktestTrade] = []
        self._run_equity: List[float] = []
        self._run_progress: Dict[str, Any] = {"i": 0, "n": 0, "blocked": 0}
        self._run_blocked_reasons: Dict[str, int] = {}

        _logger.info(
            f"BacktestEngine inicializado | "
            f"strategy={strategy.name} | "
            f"capital={initial_capital:.2f} | "
            f"min_candles={min_candles} | "
            f"symbol={symbol} | "
            f"costs={'OFF' if self._execution_cost_config.is_zero else 'ON'} | "
            f"latency={self._execution_cost_config.entry_latency_candles} | "
            f"exit_policy={'ON' if self._use_exit_policy else 'OFF'}"
        )

    def run(
        self,
        candles: List[Candle],
        *,
        progress_callback: Optional[Callable[[dict], None]] = None,
        progress_every: int = 0,
        precompute_features: bool = False,
    ) -> BacktestReport:
        """
        Executa o backtest sobre a lista de candles fornecida.

        GARANTIA ANTI-LOOKAHEAD: a estratégia em cada candle i recebe
        APENAS candles[:i+1] — nunca candles futuros.
        Entrada ocorre no close do candle atual.
        Stop/TP são verificados nos candles seguintes.

        ⚠️  Meta de challenge NÃO encerra o backtest.
            O loop sempre roda até o último candle.

        Args:
            candles: Lista de Candle em ordem cronológica (mais antigo → mais recente).
            progress_callback: (FASE 37.1) callback OPCIONAL chamado a cada
                `progress_every` candles com um dict
                {i, n, trades, blocked, timestamp}. Apenas observacional —
                NAO altera a logica de trade. Default None = sem efeito.
            progress_every: intervalo (em candles) entre chamadas do
                callback. 0 (default) = nunca chama.
            precompute_features: (FASE 37.1) se True, calcula a serie de
                features UMA vez (O(n)) e fatia por candle, em vez de
                recomputar por janela (O(n^2)). Resultado matematicamente
                IDENTICO (sem look-ahead). Default False = caminho legado.

        Returns:
            BacktestReport com todas as métricas de performance.

        Raises:
            ValueError: Se a lista de candles estiver vazia.
        """
        if not candles:
            raise ValueError(
                "Lista de candles vazia. Forneça dados históricos para o backtest."
            )

        n = len(candles)
        self._last_run_interrupted = False
        # FASE 37.1: precompute O(n) (identico, sem look-ahead) opt-in.
        _indexed = (
            self._feature_engine.compute_indexed(candles)
            if precompute_features else None
        )

        def _feats(idx: int) -> Dict[str, Any]:
            if _indexed is not None:
                try:
                    return _indexed.at(idx)
                except Exception as e:  # noqa: BLE001
                    _logger.warning(f"compute_indexed.at erro: {e}")
                    return {"has_sufficient_data": False,
                            "n_candles": idx + 1}
            return self._compute_features_safe(candles[:idx + 1])

        def _emit_progress(idx: int, n_trades: int, n_blocked: int,
                           ts) -> None:
            if progress_callback is None or progress_every <= 0:
                return
            if idx % progress_every != 0 and idx != n - 1:
                return
            try:
                progress_callback({
                    "i": idx, "n": n, "trades": n_trades,
                    "blocked": n_blocked, "timestamp": ts,
                })
            except Exception as e:  # noqa: BLE001
                _logger.debug(f"progress_callback erro (ignorado): {e}")
        _logger.info(
            f"BacktestEngine.run iniciado | "
            f"candles={n} | strategy={self._strategy.name} | "
            f"capital_inicial={self._initial_capital:.2f}"
        )
        _audit.info(
            f"BACKTEST_START | strategy={self._strategy.name} | "
            f"symbol={self._symbol} | n_candles={n} | capital={self._initial_capital:.2f}"
        )

        # Estado interno do backtest
        trades: List[BacktestTrade] = []
        open_trade: Optional[BacktestTrade] = None
        equity_curve: List[float] = []
        current_capital = self._initial_capital
        risk_blocked_count = 0
        # FASE 37.3: contagem de bloqueios por categoria (report).
        risk_blocked_reasons: Dict[str, int] = {}

        def _record_block(reason: Any) -> None:
            key = getattr(reason, "value", None) or str(reason or "unknown")
            risk_blocked_reasons[key] = risk_blocked_reasons.get(key, 0) + 1
        signals_generated = 0
        # FASE 3E.4B — Pending signal aguardando execução por latência.
        # Sempre None quando entry_latency_candles == 0 (regressão preservada).
        pending_signal: Optional[_PendingSignal] = None
        entry_latency = self._execution_cost_config.entry_latency_candles
        # FASE 12 — cache do último StrategySignal acionável (BUY/SELL) para
        # alimentar a ExitPolicy quando opposite-signal estiver habilitado.
        # Sempre None quando use_exit_policy=False (regressão preservada).
        latest_actionable_signal = None

        # FASE 37.1: estado parcial VIVO p/ o caller construir relatorio
        # parcial em caso de KeyboardInterrupt (referencia a lista de
        # trades; contadores atualizados O(1) por candle).
        self._run_trades = trades
        self._run_equity = equity_curve
        self._run_progress = {"i": 0, "n": n, "blocked": 0}
        self._run_blocked_reasons = risk_blocked_reasons

        # -----------------------------------------------------------------------
        # LOOP PRINCIPAL: candle a candle, sem lookahead
        # -----------------------------------------------------------------------
        for i in range(n):
            candle = candles[i]
            # FASE 37.3: informa a DATA SIMULADA do candle ao RiskEngine
            # para que o limite diario (max_trades_per_day) e o PnL diario
            # resetem por dia simulado (e nao acumulem como sessao unica no
            # backtest inteiro). Em prod/paper/live isto nunca eh chamado.
            if hasattr(self._risk_engine, "set_simulation_date"):
                ts = getattr(candle, "timestamp", None)
                if ts is not None:
                    self._risk_engine.set_simulation_date(ts.date())
            self._run_progress = {
                "i": i, "n": n, "blocked": risk_blocked_count,
            }
            _emit_progress(i, len(trades), risk_blocked_count,
                           candle.timestamp)

            # --- PASSO 1: Verificar posições abertas ANTES da nova avaliação ---
            # Stop/TP são verificados no candle atual (para posições abertas no ciclo anterior)
            if open_trade is not None and not open_trade.is_open:
                open_trade = None  # limpeza defensiva

            if open_trade is not None:
                # FASE 12 — Quando opposite-signal está habilitado, avalia a
                # estratégia AGORA (com posição aberta) para alimentar a
                # ExitPolicy com o sinal atual. Não abre nova posição —
                # apenas atualiza latest_actionable_signal.
                # Caminho desligado quando use_exit_policy=False (legado).
                if (self._use_exit_policy
                        and self._exit_policy is not None
                        and self._exit_policy.allow_opposite_signal
                        and i >= self._min_candles - 1):
                    feats_opp = _feats(i)
                    if feats_opp.get("has_sufficient_data", False):
                        feats_opp["symbol"] = self._symbol
                        try:
                            sig_opp = self._strategy.evaluate(feats_opp)
                            if sig_opp is not None and sig_opp.is_actionable:
                                latest_actionable_signal = sig_opp
                        except Exception as e:
                            _logger.warning(
                                f"[{i}] Falha ao avaliar estratégia para "
                                f"opposite-signal: {e}"
                            )

                # Verifica stop/TP no candle atual para posições abertas.
                # Quando use_exit_policy=True, a ExitPolicy é consultada e
                # pode também disparar TIME_LIMIT ou OPPOSITE_SIGNAL.
                closed_trade = self._check_exit_conditions(
                    trade=open_trade,
                    candle=candle,
                    candle_idx=i,
                    latest_signal=latest_actionable_signal,
                )
                if closed_trade is not None:
                    # Posição foi fechada → atualiza RiskEngine e capital
                    self._risk_engine.record_trade_closed(
                        symbol=closed_trade.symbol,
                        pnl=closed_trade.pnl_usd,
                        size_usd=closed_trade.position_size_usd,
                    )
                    current_capital = self._risk_engine.get_status_summary()["current_capital"]
                    open_trade = None

                    # Lifecycle: notifica a estrategia do fechamento para que
                    # ela libere a reentrada (reseta _has_open_position).
                    # Sem isto, estrategias que rastreiam posicao internamente
                    # ficam presas em "posicao aberta" e nunca mais geram
                    # sinal -> apenas 1 trade por backtest. Mesma notificacao
                    # que paper/live ja fazem; NAO altera logica de trade.
                    if hasattr(self._strategy, "on_trade_closed"):
                        self._strategy.on_trade_closed(
                            closed_trade.symbol, closed_trade.pnl_usd,
                        )

                    _logger.debug(
                        f"[{i}] Trade fechado: {closed_trade.close_reason.value} | "
                        f"PnL={closed_trade.pnl_usd:+.2f} | capital={current_capital:.2f}"
                    )

                    # FASE 12 — Anti-flip: se a saída foi por OPPOSITE_SIGNAL no
                    # candle atual, NÃO abre nova posição no mesmo candle.
                    # A nova entrada só pode ocorrer em ciclo posterior. Esta
                    # invariante só é necessária no caminho ExitPolicy; legado
                    # nunca fecha por OPPOSITE_SIGNAL.
                    if (self._use_exit_policy
                            and closed_trade.close_reason == CloseReason.OPPOSITE_SIGNAL):
                        # Atualiza equity e pula para o próximo candle.
                        equity_curve.append(round(current_capital, 4))
                        continue

            # --- FASE 3E.4B PASSO 1.5: Processa pending signal se hora de executar ---
            # Pending só executa exatamente em i == executes_at_idx.
            # Revalida RiskEngine; em caso de falha, descarta e conta como bloqueado.
            # Em caso de aprovação, executa no OPEN do candle atual.
            if pending_signal is not None and i == pending_signal.executes_at_idx:
                revalidation = self._risk_engine.validate_signal(
                    pending_signal.trading_signal
                )
                if not revalidation.approved:
                    risk_blocked_count += 1
                    _record_block(revalidation.block_reason)
                    _logger.debug(
                        f"[{i}] RiskEngine bloqueou pending (revalidação): "
                        f"{revalidation.reason[:60]}"
                    )
                    if hasattr(self._strategy, "on_signal_rejected"):
                        self._strategy.on_signal_rejected(
                            pending_signal.trading_signal, revalidation.reason
                        )
                    pending_signal = None
                else:
                    # Executa no OPEN do candle atual (i == executes_at_idx).
                    pts = pending_signal.trading_signal
                    entry_exec = apply_entry_costs(
                        side=pts.side.value,
                        price_theoretical=candle.open,   # ← OPEN, não close
                        position_size_usd=pts.position_size_usd,
                        config=self._execution_cost_config,
                    )
                    # FASE 25 - guard defensiva: movimento adverso durante
                    # entry_latency_candles pode levar o entry executado a
                    # cruzar o stop original. Nesse caso, descarta o pending
                    # (trade nasceria invalido pela invariante de
                    # BacktestTrade: BUY -> stop < entry; SELL -> stop > entry).
                    # Conta como risk_blocked para auditoria.
                    _exec_price = entry_exec.price_executed
                    _stop = pts.stop_loss_price
                    side_lower = pts.side.value.lower()
                    adverse = (
                        (side_lower == "buy" and _exec_price <= _stop)
                        or (side_lower == "sell" and _exec_price >= _stop)
                    )
                    if adverse:
                        risk_blocked_count += 1
                        _record_block("adverse_movement_during_latency")
                        _logger.debug(
                            f"[{i}] Pending descartado por movimento adverso "
                            f"durante latency: side={side_lower} "
                            f"exec={_exec_price:.2f} stop={_stop:.2f} "
                            f"(invariante violada se aberto)"
                        )
                        if hasattr(self._strategy, "on_signal_rejected"):
                            self._strategy.on_signal_rejected(
                                pts, "adverse_movement_during_latency"
                            )
                        pending_signal = None
                        equity_curve.append(round(current_capital, 4))
                        continue
                    open_trade = BacktestTrade(
                        symbol=self._symbol,
                        strategy_name=self._strategy.name,
                        entry_candle_idx=i,                     # candle de EXECUÇÃO
                        entry_time=candle.timestamp,
                        entry_price=entry_exec.price_executed,
                        stop_loss_price=pts.stop_loss_price,    # ORIGINAL do sinal
                        take_profit_price=pts.take_profit_price,  # ORIGINAL do sinal
                        position_size_usd=pts.position_size_usd,
                        side=pts.side.value,
                        entry_price_theoretical=entry_exec.price_theoretical,
                        entry_fee_usd=entry_exec.fee_usd,
                        entry_slippage_cost_usd=entry_exec.slippage_cost_usd,
                    )
                    trades.append(open_trade)
                    self._risk_engine.record_trade_opened(pts)
                    if hasattr(self._strategy, "on_signal_approved"):
                        self._strategy.on_signal_approved(pts)
                    _logger.debug(
                        f"[{i}] Pending executado: {pts.side.value.upper()} "
                        f"@ open={candle.open:.2f} | latency={entry_latency} | "
                        f"gerado@{pending_signal.generated_at_idx}"
                    )
                    pending_signal = None

            # Atualiza equity curve com capital atual
            equity_curve.append(round(current_capital, 4))

            # --- PASSO 2: Estratégia avalia apenas candles até o índice atual ---
            # ⚠️  ANTI-LOOKAHEAD: passa exatamente candles[:i+1]
            # A estratégia nunca pode ver candles[i+1:]
            if i < self._min_candles - 1:
                # Dados insuficientes — não avalia estratégia ainda
                continue

            # ← SOMENTE passado + atual (sem futuro). _feats usa precompute
            # O(n) quando habilitado; senao recomputa a janela (legado).
            features = _feats(i)

            if not features.get("has_sufficient_data", False):
                continue

            # Adiciona símbolo para a estratégia
            features["symbol"] = self._symbol

            # Se já há posição aberta, a estratégia não gera novo sinal
            # (compatível com estratégias que não rastreiam posição internamente)
            if open_trade is not None:
                continue

            # FASE 3E.4B: enquanto há pending signal aguardando execução,
            # a estratégia também não é chamada (regra simétrica ao open_trade).
            if pending_signal is not None:
                continue

            # --- PASSO 3: Avalia estratégia ---
            strategy_signal: StrategySignal = self._strategy.evaluate(features)

            # FASE 12 — cache do último sinal acionável para a ExitPolicy.
            # Inerte quando use_exit_policy=False.
            if strategy_signal.is_actionable:
                latest_actionable_signal = strategy_signal

            if not strategy_signal.is_actionable:
                # HOLD — ciclo seguro sem execução
                continue

            signals_generated += 1

            # --- PASSO 4: RiskEngine valida o sinal (soberano) ---
            try:
                trading_signal = strategy_signal.to_trading_signal()
            except ValueError as e:
                _logger.warning(f"[{i}] Sinal inválido para conversão: {e}")
                continue

            risk_result = self._risk_engine.validate_signal(trading_signal)

            if not risk_result.approved:
                risk_blocked_count += 1
                _record_block(risk_result.block_reason)
                _logger.debug(
                    f"[{i}] RiskEngine bloqueou: {risk_result.reason[:60]}"
                )
                # Notifica estratégia sobre rejeição (não obrigatório, mas correto)
                if hasattr(self._strategy, "on_signal_rejected"):
                    self._strategy.on_signal_rejected(trading_signal, risk_result.reason)
                continue

            # --- PASSO 5: Abre BacktestTrade OU cria pending signal (FASE 3E.4B) ---
            if entry_latency == 0:
                # Caminho da FASE 3E.4A (regressão perfeita byte-a-byte):
                # entrada IMEDIATA no close do candle atual.
                entry_exec = apply_entry_costs(
                    side=trading_signal.side.value,
                    price_theoretical=candle.close,
                    position_size_usd=trading_signal.position_size_usd,
                    config=self._execution_cost_config,
                )
                open_trade = BacktestTrade(
                    symbol=self._symbol,
                    strategy_name=self._strategy.name,
                    entry_candle_idx=i,
                    entry_time=candle.timestamp,
                    entry_price=entry_exec.price_executed,
                    stop_loss_price=trading_signal.stop_loss_price,
                    take_profit_price=trading_signal.take_profit_price,
                    position_size_usd=trading_signal.position_size_usd,
                    side=trading_signal.side.value,
                    entry_price_theoretical=entry_exec.price_theoretical,
                    entry_fee_usd=entry_exec.fee_usd,
                    entry_slippage_cost_usd=entry_exec.slippage_cost_usd,
                )
                trades.append(open_trade)

                # Registra abertura no RiskEngine (atualiza exposição e trades_today)
                self._risk_engine.record_trade_opened(trading_signal)

                # Notifica estratégia sobre aprovação
                if hasattr(self._strategy, "on_signal_approved"):
                    self._strategy.on_signal_approved(trading_signal)

                _logger.debug(
                    f"[{i}] Trade aberto: {trading_signal.side.value.upper()} "
                    f"@ {candle.close:.2f} | "
                    f"stop={trading_signal.stop_loss_price:.2f} | "
                    f"size={trading_signal.position_size_usd:.2f}USD"
                )
            else:
                # FASE 3E.4B: cria pending signal; executa em candle i+entry_latency.
                # on_signal_approved e record_trade_opened são chamados na EXECUÇÃO,
                # não na geração (simula "ordem submetida, aguardando preenchimento").
                pending_signal = _PendingSignal(
                    trading_signal=trading_signal,
                    generated_at_idx=i,
                    executes_at_idx=i + entry_latency,
                )
                _logger.debug(
                    f"[{i}] Pending criado: {trading_signal.side.value.upper()} "
                    f"executa@{pending_signal.executes_at_idx} (latency={entry_latency})"
                )

        # -----------------------------------------------------------------------
        # FIM DO LOOP: Fecha posições abertas + expira pending (FASE 3E.4B)
        # -----------------------------------------------------------------------
        # FASE 3E.4B: se pending signal ainda existe, o candle de execução
        # nunca chegou (latência > candles restantes). Expira silenciosamente.
        # NÃO incrementa risk_blocked_count (não foi RiskEngine que bloqueou).
        if pending_signal is not None:
            _logger.info(
                f"Pending signal expirou sem execução | "
                f"gerado@{pending_signal.generated_at_idx} | "
                f"esperava executar@{pending_signal.executes_at_idx} | "
                f"último candle disponível = {n - 1}"
            )
            pending_signal = None

        if open_trade is not None and open_trade.is_open:
            last_candle = candles[-1]
            # FASE 3E.1: aplica custos de saída no fim dos dados (mesmo modelo).
            exit_exec = apply_exit_costs(
                side=open_trade.side,
                price_theoretical=last_candle.close,
                position_size_usd=open_trade.position_size_usd,
                config=self._execution_cost_config,
            )
            open_trade.close(
                exit_candle_idx=n - 1,
                exit_time=last_candle.timestamp,
                exit_price=exit_exec.price_executed,
                close_reason=CloseReason.END_OF_DATA,
                exit_price_theoretical=exit_exec.price_theoretical,
                exit_fee_usd=exit_exec.fee_usd,
                exit_slippage_cost_usd=exit_exec.slippage_cost_usd,
            )
            self._risk_engine.record_trade_closed(
                symbol=open_trade.symbol,
                pnl=open_trade.pnl_usd,
                size_usd=open_trade.position_size_usd,
            )
            # Lifecycle: notifica a estrategia (consistencia de estado;
            # loop ja terminou, sem reentrada). NAO altera resultado.
            if hasattr(self._strategy, "on_trade_closed"):
                self._strategy.on_trade_closed(
                    open_trade.symbol, open_trade.pnl_usd,
                )
            current_capital = self._risk_engine.get_status_summary()["current_capital"]
            equity_curve.append(round(current_capital, 4))

            _logger.debug(
                f"Trade fechado por fim dos dados: "
                f"PnL={open_trade.pnl_usd:+.2f} | capital_final={current_capital:.2f}"
            )

        closed_trades = [t for t in trades if not t.is_open]

        _logger.info(
            f"BacktestEngine.run concluído | "
            f"candles={n} | trades={len(closed_trades)} | "
            f"risk_blocked={risk_blocked_count} | "
            f"capital_final={current_capital:.2f}"
        )
        _audit.info(
            f"BACKTEST_END | strategy={self._strategy.name} | "
            f"trades={len(closed_trades)} | capital_final={current_capital:.2f}"
        )

        # -----------------------------------------------------------------------
        # Gera relatório
        # -----------------------------------------------------------------------
        report = BacktestReport.from_trades(
            trades=closed_trades,
            initial_capital=self._initial_capital,
            equity_curve=equity_curve,
            strategy_name=self._strategy.name,
            symbol=self._symbol,
            n_candles_total=n,
            risk_blocked_count=risk_blocked_count,
            risk_blocked_reasons=dict(risk_blocked_reasons),
            challenge_profit_target_usd=self._challenge_profit_target_usd,
        )

        return report

    # -----------------------------------------------------------------------
    # Métodos Privados
    # -----------------------------------------------------------------------

    def _check_exit_conditions(
        self,
        trade: BacktestTrade,
        candle: Candle,
        candle_idx: int,
        latest_signal: Optional["StrategySignal"] = None,
    ) -> Optional[BacktestTrade]:
        """
        Verifica condições de saída no candle atual.

        Quando `use_exit_policy=False` (default), executa o caminho legado:
        SL/TP por candle, regra conservadora SL-vence-TP.

        Quando `use_exit_policy=True`, delega à ExitPolicy. Mantém os
        mesmos invariantes: detecção por preço teórico, aplicação de
        custos via apply_exit_costs(), fechamento por trade.close().

        Args:
            trade:         Trade aberto a verificar.
            candle:        Candle atual (posterior ao de entrada).
            candle_idx:    Índice do candle atual.
            latest_signal: Último sinal acionável visto (para opposite).

        Returns:
            O trade fechado (com PnL) se a saída disparou; None caso contrário.
        """
        if not trade.is_open:
            return None

        # Não verifica stop/TP no mesmo candle de entrada (evita ruído intracandle)
        if candle_idx <= trade.entry_candle_idx:
            return None

        # FASE 12 — caminho ExitPolicy opt-in
        if self._use_exit_policy and self._exit_policy is not None:
            return self._check_exit_via_policy(
                trade=trade,
                candle=candle,
                candle_idx=candle_idx,
                latest_signal=latest_signal,
            )

        stop_hit = False
        tp_hit = False

        if trade.side == "buy":
            stop_hit = candle.low <= trade.stop_loss_price
            tp_hit = (
                trade.take_profit_price is not None
                and candle.high >= trade.take_profit_price
            )
        else:  # sell
            stop_hit = candle.high >= trade.stop_loss_price
            tp_hit = (
                trade.take_profit_price is not None
                and candle.low <= trade.take_profit_price
            )

        # ⚠️  REGRA DE AMBIGUIDADE: stop loss tem prioridade sobre take profit
        # FASE 3E.1: detecção de hit usa preço TEÓRICO (stop_loss_price / take_profit_price).
        # Slippage/spread ajustam APENAS o preço executado APÓS o hit ser detectado.
        if stop_hit:
            exit_exec = apply_exit_costs(
                side=trade.side,
                price_theoretical=trade.stop_loss_price,
                position_size_usd=trade.position_size_usd,
                config=self._execution_cost_config,
            )
            trade.close(
                exit_candle_idx=candle_idx,
                exit_time=candle.timestamp,
                exit_price=exit_exec.price_executed,
                close_reason=CloseReason.STOP_LOSS,
                exit_price_theoretical=exit_exec.price_theoretical,
                exit_fee_usd=exit_exec.fee_usd,
                exit_slippage_cost_usd=exit_exec.slippage_cost_usd,
            )
            return trade

        if tp_hit and trade.take_profit_price is not None:
            exit_exec = apply_exit_costs(
                side=trade.side,
                price_theoretical=trade.take_profit_price,
                position_size_usd=trade.position_size_usd,
                config=self._execution_cost_config,
            )
            trade.close(
                exit_candle_idx=candle_idx,
                exit_time=candle.timestamp,
                exit_price=exit_exec.price_executed,
                close_reason=CloseReason.TAKE_PROFIT,
                exit_price_theoretical=exit_exec.price_theoretical,
                exit_fee_usd=exit_exec.fee_usd,
                exit_slippage_cost_usd=exit_exec.slippage_cost_usd,
            )
            return trade

        # FASE 48 — saida por TEMPO (fallback): nem SL nem TP dispararam e a
        # posicao excedeu max_holding_candles barras => fecha no close atual.
        if (self._max_holding_candles is not None
                and (candle_idx - trade.entry_candle_idx)
                >= self._max_holding_candles):
            exit_exec = apply_exit_costs(
                side=trade.side,
                price_theoretical=float(candle.close),
                position_size_usd=trade.position_size_usd,
                config=self._execution_cost_config,
            )
            trade.close(
                exit_candle_idx=candle_idx,
                exit_time=candle.timestamp,
                exit_price=exit_exec.price_executed,
                close_reason=CloseReason.TIME_LIMIT,
                exit_price_theoretical=exit_exec.price_theoretical,
                exit_fee_usd=exit_exec.fee_usd,
                exit_slippage_cost_usd=exit_exec.slippage_cost_usd,
            )
            return trade

        return None

    def _check_exit_via_policy(
        self,
        *,
        trade: BacktestTrade,
        candle: Candle,
        candle_idx: int,
        latest_signal: Optional["StrategySignal"],
    ) -> Optional[BacktestTrade]:
        """
        FASE 12 — Caminho ExitPolicy (opt-in).

        Converte trade → OpenPositionState, consulta ExitPolicy, aplica
        custos via apply_exit_costs() e fecha o trade com o snapshot
        auditável da ExitDecision.

        Preserva regra conservadora (SL vence TP) porque a ExitPolicy
        replica essa regra internamente.
        """
        # Import locais para isolar dependência quando flag está desligada.
        from crypto_trading_bot.backtesting.exit_policy_adapter import (
            backtest_trade_to_open_position,
            decision_to_snapshot,
            map_decision_to_close,
        )

        position = backtest_trade_to_open_position(trade)
        decision = self._exit_policy.evaluate(
            position=position,
            candle=candle,
            candle_idx=candle_idx,
            now=candle.timestamp,
            latest_signal=latest_signal,
        )
        if not decision.should_close:
            return None

        close_reason, trigger_price = map_decision_to_close(
            decision, trade, candle
        )

        exit_exec = apply_exit_costs(
            side=trade.side,
            price_theoretical=trigger_price,
            position_size_usd=trade.position_size_usd,
            config=self._execution_cost_config,
        )
        snapshot = decision_to_snapshot(decision)
        trade.close(
            exit_candle_idx=candle_idx,
            exit_time=candle.timestamp,
            exit_price=exit_exec.price_executed,
            close_reason=close_reason,
            exit_price_theoretical=exit_exec.price_theoretical,
            exit_fee_usd=exit_exec.fee_usd,
            exit_slippage_cost_usd=exit_exec.slippage_cost_usd,
            exit_decision_snapshot=snapshot,
        )
        return trade

    def _compute_features_safe(
        self,
        candles: List[Candle],
    ) -> Dict[str, Any]:
        """
        Calcula features com tratamento seguro de erros.

        Args:
            candles: Lista de candles (somente passado + atual).

        Returns:
            Dicionário de features. `has_sufficient_data=False` se erro.
        """
        try:
            features = self._feature_engine.compute(candles)
            return features
        except Exception as e:
            _logger.warning(f"FeatureEngine erro: {e}")
            return {"has_sufficient_data": False, "n_candles": len(candles)}

    @property
    def last_run_interrupted(self) -> bool:
        """FASE 37.1 — True se o ultimo run foi marcado como interrompido."""
        return self._last_run_interrupted

    def build_partial_report(self) -> BacktestReport:
        """FASE 37.1 — Relatorio PARCIAL a partir do estado vivo do run.

        Usado pelo caller apos capturar KeyboardInterrupt. Inclui apenas
        os trades JA fechados ate o ponto da interrupcao (posicao aberta
        nao eh fechada). NAO altera logica de trade; nada e inventado.
        """
        self._last_run_interrupted = True
        closed = [t for t in self._run_trades if not t.is_open]
        n_total = int(self._run_progress.get("n", 0) or 0)
        return BacktestReport.from_trades(
            trades=closed,
            initial_capital=self._initial_capital,
            equity_curve=list(self._run_equity),
            strategy_name=self._strategy.name,
            symbol=self._symbol,
            n_candles_total=n_total,
            risk_blocked_count=int(self._run_progress.get("blocked", 0) or 0),
            risk_blocked_reasons=dict(self._run_blocked_reasons),
            challenge_profit_target_usd=self._challenge_profit_target_usd,
        )

    @property
    def strategy_name(self) -> str:
        """Nome da estratégia configurada."""
        return self._strategy.name

    @property
    def initial_capital(self) -> float:
        """Capital inicial configurado."""
        return self._initial_capital

    def __repr__(self) -> str:
        return (
            f"BacktestEngine("
            f"strategy={self._strategy.name} | "
            f"capital={self._initial_capital:.2f} | "
            f"symbol={self._symbol})"
        )
