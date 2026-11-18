"""
PaperExitOrchestrator — Ativação opt-in da ExitPolicy no paper (FASE 13)
=========================================================================
⚠️  AVISOS OBRIGATÓRIOS:
    - NÃO chama executor real. NÃO chama rede. NÃO envia ordem.
    - NÃO importa BybitClient, BybitDemoExecutor, httpx.
    - NÃO usa API key/secret.
    - NÃO abre posição. Só fecha posições já abertas no PaperTrader.
    - RiskEngine continua soberano: cada close_trade chama
      paper_trader.close_trade(...) que invoca record_trade_closed().
    - PaperTrader NÃO é alterado por este módulo — apenas consumido.

USO TÍPICO:
    orchestrator = PaperExitOrchestrator(paper_trader, exit_policy)
    decisions = orchestrator.on_candle(candle, candle_idx, now,
                                       latest_signal=...)
    # decisions é a lista de ExitDecision EMITIDAS para fechamentos.

SEMÂNTICA DE PREÇO DE FECHAMENTO:
    STOP_LOSS       → signal.stop_loss_price
    TAKE_PROFIT     → signal.take_profit_price
    TIME_LIMIT      → candle.close
    OPPOSITE_SIGNAL → candle.close
    MANUAL          → candle.close (se candle != None) senão signal.entry_price
    EMERGENCY       → candle.close (idem)

⚠️  ExitPolicy.evaluate é chamada uma vez por posição aberta por candle.
    Cada decisão de fechamento dispara exatamente 1 chamada de close_trade.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Mapping, Optional

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.exit_policy.exit_decision import (
    ExitDecision,
    ExitReason,
    OpenPositionState,
    PositionSide,
)
from crypto_trading_bot.exit_policy.exit_policy import ExitPolicy
from crypto_trading_bot.logging_system.logger import get_logger
from crypto_trading_bot.risk.risk_engine import OrderSide

_logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helper: PaperTrade → OpenPositionState
# ---------------------------------------------------------------------------

def paper_trade_to_open_position(trade) -> OpenPositionState:
    """
    Converte um PaperTrade aberto em OpenPositionState consumido pela ExitPolicy.

    Não muta o trade. Não faz I/O. Recusa trades já fechados.

    Args:
        trade: PaperTrade aberto.

    Returns:
        OpenPositionState imutável.

    Raises:
        ValueError: trade já fechado ou dados inválidos.
    """
    # Import local para evitar dependência circular em load-time.
    from crypto_trading_bot.execution.paper_trader import PaperTrade  # noqa: F401

    if not getattr(trade, "is_open", False):
        raise ValueError(
            f"PaperTrade {getattr(trade, 'trade_id', '?')} já fechado."
        )

    signal = trade.signal
    side = (
        PositionSide.BUY if signal.side == OrderSide.BUY else PositionSide.SELL
    )
    entry_price = (
        trade.order_result.avg_fill_price
        if trade.order_result and trade.order_result.avg_fill_price
        else signal.entry_price
    )
    entry_time = trade.opened_at
    if entry_time is None:
        entry_time = datetime.now(timezone.utc)

    return OpenPositionState(
        symbol=signal.symbol,
        side=side,
        entry_price=float(entry_price),
        entry_time=entry_time,
        stop_loss_price=float(signal.stop_loss_price),
        take_profit_price=(
            float(signal.take_profit_price)
            if signal.take_profit_price is not None
            else None
        ),
        position_size_usd=float(signal.position_size_usd),
        entry_candle_idx=None,  # paper não tem grade de candles
    )


# ---------------------------------------------------------------------------
# Mapeamento ExitReason → (paper close reason str)
# ---------------------------------------------------------------------------

_REASON_TO_PAPER_STR = {
    ExitReason.STOP_LOSS: "stop_loss",
    ExitReason.TAKE_PROFIT: "take_profit",
    ExitReason.TIME_LIMIT: "time_limit",
    ExitReason.OPPOSITE_SIGNAL: "opposite_signal",
    ExitReason.MANUAL: "manual",
    ExitReason.EMERGENCY: "emergency",
}


def _close_price_for(
    decision: ExitDecision,
    position: OpenPositionState,
    candle: Optional[Candle],
) -> float:
    """Decide o preço de fechamento determinístico a partir da decisão."""
    if decision.reason == ExitReason.STOP_LOSS:
        return float(position.stop_loss_price)
    if decision.reason == ExitReason.TAKE_PROFIT:
        # ExitPolicy só dispara TP quando take_profit_price != None,
        # mas garantimos fallback defensivo.
        return (
            float(position.take_profit_price)
            if position.take_profit_price is not None
            else (float(candle.close) if candle is not None else float(position.entry_price))
        )
    # TIME_LIMIT, OPPOSITE_SIGNAL, MANUAL, EMERGENCY → candle.close se houver,
    # caso contrário entry_price (manual/emergency sem candle).
    if candle is not None:
        return float(candle.close)
    return float(position.entry_price)


def _decision_to_snapshot(decision: ExitDecision) -> dict:
    """
    Converte ExitDecision em dict puro auditável.

    Espelha a função existente em backtesting/exit_policy_adapter.py para
    manter consistência. Não expõe `execution_allowed` — apenas a camada
    de capability.
    """
    md = dict(decision.metadata) if decision.metadata else {}
    snapshot: dict = {
        "reason": decision.reason.value,
        "source": decision.source.value,
        "triggered_at_time": decision.triggered_at_time.isoformat(),
        "triggered_at_idx": decision.triggered_at_idx,
        "requires_reduce_only": bool(decision.requires_reduce_only),
        "auto_execute_blocked": bool(decision.auto_execute_blocked),
    }
    for k in (
        "capability_allows_auto_close",
        "provider_id",
        "trigger_price",
        "elapsed_candles",
        "elapsed_seconds",
        "limit_kind",
        "limit_value",
        "tp_also_hit",
        "opposite_action",
        "opposite_strategy",
        "candle_low",
        "candle_high",
    ):
        if k in md:
            snapshot[k] = md[k]
    return snapshot


# ---------------------------------------------------------------------------
# PaperExitOrchestrator
# ---------------------------------------------------------------------------

class PaperExitOrchestrator:
    """
    Orquestrador opt-in: avalia posições abertas do PaperTrader contra a
    ExitPolicy e fecha as que a política decidir, retornando a lista de
    ExitDecision emitidas para auditoria.

    ⚠️  NUNCA abre posição. Apenas fecha.
    ⚠️  Não chama RiskEngine diretamente — `PaperTrader.close_trade` já
        invoca `record_trade_closed`.
    ⚠️  Provider-agnostic: consome a ExitPolicy injetada (que tem sua
        própria ProviderCapability).
    """

    def __init__(self, paper_trader, exit_policy: ExitPolicy) -> None:
        # Import local para evitar dependência circular.
        from crypto_trading_bot.execution.paper_trader import PaperTrader

        if not isinstance(paper_trader, PaperTrader):
            raise TypeError(
                "paper_trader deve ser PaperTrader. "
                f"Recebido: {type(paper_trader).__name__}"
            )
        if not isinstance(exit_policy, ExitPolicy):
            raise TypeError(
                "exit_policy deve ser ExitPolicy. "
                f"Recebido: {type(exit_policy).__name__}"
            )
        self._paper_trader = paper_trader
        self._exit_policy = exit_policy
        _logger.info(
            "[PaperExitOrchestrator] inicializado | "
            f"opposite_enabled={exit_policy.allow_opposite_signal} | "
            f"has_time_limit={exit_policy.has_time_limit} | "
            f"provider_cap={exit_policy.provider_capability.provider_id}"
        )

    @property
    def paper_trader(self):
        """Acesso somente-leitura ao PaperTrader injetado."""
        return self._paper_trader

    @property
    def exit_policy(self) -> ExitPolicy:
        """Acesso somente-leitura à ExitPolicy injetada."""
        return self._exit_policy

    # -----------------------------------------------------------------------
    # API principal
    # -----------------------------------------------------------------------

    def on_candle(
        self,
        candle: Optional[Candle] = None,
        *,
        candle_idx: Optional[int] = None,
        now: Optional[datetime] = None,
        latest_signal=None,
        manual_close: Optional[Mapping[str, bool]] = None,
        emergency_active: bool = False,
    ) -> List[ExitDecision]:
        """
        Avalia todas as posições abertas e fecha as que a ExitPolicy
        decidir. Retorna a lista de ExitDecision emitidas (auditável).

        Args:
            candle:            Candle atual (None permitido em modo manual/
                               emergency).
            candle_idx:        Índice opcional do candle (None em paper live).
            now:               Timestamp atual UTC (None → utcnow).
            latest_signal:     Último StrategySignal acionável visto pelo
                               consumidor — usado para regra de opposite.
            manual_close:      Mapping {trade_id: True} para fechar manualmente
                               posições específicas. None = nenhuma manual.
            emergency_active:  Kill switch global; aplicado a TODAS as posições
                               abertas (se ExitPolicy tiver emergency habilitado).

        Returns:
            Lista de ExitDecision com should_close=True. Vazia se nada fechar.

        Garantias:
            - NUNCA abre posição.
            - close_trade é chamado exatamente 1× por decisão de fechamento.
            - Cada close_trade invoca record_trade_closed no RiskEngine.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        decisions: List[ExitDecision] = []
        manual_map = dict(manual_close or {})

        # Snapshot da lista para evitar mutação concorrente do dict subjacente
        # ao fechar via PaperTrader.close_trade.
        open_trades_snapshot = list(self._paper_trader.open_trades.values())

        for trade in open_trades_snapshot:
            if not trade.is_open:
                continue
            try:
                position = paper_trade_to_open_position(trade)
            except ValueError as e:
                _logger.warning(
                    f"[PaperExitOrchestrator] Pulando trade "
                    f"{getattr(trade, 'trade_id', '?')}: {e}"
                )
                continue

            decision = self._exit_policy.evaluate(
                position=position,
                candle=candle,
                candle_idx=candle_idx,
                now=now,
                latest_signal=latest_signal,
                manual_close_requested=manual_map.get(trade.trade_id, False),
                emergency_active=emergency_active,
            )

            if not decision.should_close:
                continue

            close_price = _close_price_for(decision, position, candle)
            reason_str = _REASON_TO_PAPER_STR.get(decision.reason, "manual")
            snapshot = _decision_to_snapshot(decision)

            result = self._paper_trader.close_trade(
                trade_id=trade.trade_id,
                close_price=close_price,
                reason=reason_str,
                exit_decision_snapshot=snapshot,
            )
            if not result.success:
                _logger.error(
                    f"[PaperExitOrchestrator] Falha ao fechar "
                    f"{trade.trade_id}: {result.reason}"
                )
                continue
            decisions.append(decision)

        return decisions
