"""
ExitPolicy ↔ BacktestEngine — Adapter Puro (FASE 12)
======================================================
⚠️  AVISOS OBRIGATÓRIOS:
    - Este módulo NÃO chama executor, NÃO chama rede, NÃO envia ordem.
    - NÃO chama RiskEngine. NÃO conhece provider real.
    - Funções puras: convertem BacktestTrade ↔ OpenPositionState e
      mapeiam ExitDecision → (CloseReason, trigger_price) para o
      BacktestEngine aplicar custos e fechar o trade.

USO ESPERADO (apenas quando BacktestEngine.use_exit_policy=True):
    pos = backtest_trade_to_open_position(trade)
    decision = exit_policy.evaluate(pos, candle=c, candle_idx=i, ...)
    if decision.should_close:
        reason, trigger_price = map_decision_to_close(decision, trade, candle)
        # BacktestEngine aplica apply_exit_costs(...) e chama trade.close(...)
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from crypto_trading_bot.backtesting.backtest_trade import BacktestTrade, CloseReason
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.exit_policy import (
    ExitDecision,
    ExitReason,
    OpenPositionState,
    PositionSide,
)


# ---------------------------------------------------------------------------
# BacktestTrade → OpenPositionState
# ---------------------------------------------------------------------------

def backtest_trade_to_open_position(trade: BacktestTrade) -> OpenPositionState:
    """
    Converte um BacktestTrade aberto em OpenPositionState (tipo neutro
    consumido pela ExitPolicy).

    Não muta o trade. Não faz I/O.

    Raises:
        ValueError: se o trade já estiver fechado ou tiver dados inválidos.
    """
    if not trade.is_open:
        raise ValueError(
            f"Trade {trade.trade_id} já fechado — não pode ser convertido."
        )
    side = (
        PositionSide.BUY if trade.side == "buy" else PositionSide.SELL
    )
    return OpenPositionState(
        symbol=trade.symbol,
        side=side,
        entry_price=trade.entry_price,
        entry_time=trade.entry_time,
        stop_loss_price=trade.stop_loss_price,
        take_profit_price=trade.take_profit_price,
        position_size_usd=trade.position_size_usd,
        entry_candle_idx=trade.entry_candle_idx,
    )


# ---------------------------------------------------------------------------
# ExitReason → CloseReason  (somente subset válido em backtest puro)
# ---------------------------------------------------------------------------

# FASE 12 — MANUAL/EMERGENCY/END_OF_DATA propositalmente fora deste mapeamento:
# - MANUAL/EMERGENCY não existem em backtest determinístico (sem humano vivo).
# - END_OF_DATA é decidido pelo próprio BacktestEngine no encerramento do loop.
_EXIT_REASON_TO_CLOSE_REASON: Dict[ExitReason, CloseReason] = {
    ExitReason.STOP_LOSS: CloseReason.STOP_LOSS,
    ExitReason.TAKE_PROFIT: CloseReason.TAKE_PROFIT,
    ExitReason.TIME_LIMIT: CloseReason.TIME_LIMIT,
    ExitReason.OPPOSITE_SIGNAL: CloseReason.OPPOSITE_SIGNAL,
}


class UnsupportedExitReasonError(ValueError):
    """ExitReason fora do escopo do backtest (ex.: MANUAL/EMERGENCY)."""


def map_decision_to_close(
    decision: ExitDecision,
    trade: BacktestTrade,
    candle: Candle,
) -> Tuple[CloseReason, float]:
    """
    Mapeia ExitDecision → (CloseReason, trigger_price_teorico) para o
    BacktestEngine aplicar custos e fechar o trade.

    trigger_price_teorico:
        - STOP_LOSS       → trade.stop_loss_price (preço teórico)
        - TAKE_PROFIT     → trade.take_profit_price (preço teórico)
        - TIME_LIMIT      → candle.close (saída na vela atual)
        - OPPOSITE_SIGNAL → candle.close (saída na vela atual)

    Returns:
        (CloseReason, trigger_price_teorico)

    Raises:
        AssertionError:           se decision.should_close == False.
        UnsupportedExitReasonError: ExitReason fora do escopo do backtest.
        ValueError:               TAKE_PROFIT sem take_profit_price definido.
    """
    assert decision.should_close, (
        "map_decision_to_close exige should_close=True"
    )
    if decision.reason not in _EXIT_REASON_TO_CLOSE_REASON:
        raise UnsupportedExitReasonError(
            f"ExitReason {decision.reason.value} fora do escopo de "
            f"backtest puro (MANUAL/EMERGENCY/END_OF_DATA não suportados aqui)."
        )

    close_reason = _EXIT_REASON_TO_CLOSE_REASON[decision.reason]

    if close_reason == CloseReason.STOP_LOSS:
        return close_reason, trade.stop_loss_price
    if close_reason == CloseReason.TAKE_PROFIT:
        if trade.take_profit_price is None:
            raise ValueError(
                "TAKE_PROFIT exige trade.take_profit_price não-None."
            )
        return close_reason, trade.take_profit_price
    # TIME_LIMIT e OPPOSITE_SIGNAL → fecha no preço corrente (close)
    return close_reason, candle.close


# ---------------------------------------------------------------------------
# ExitDecision → snapshot serializável
# ---------------------------------------------------------------------------

def decision_to_snapshot(decision: ExitDecision) -> Dict[str, Any]:
    """
    Converte ExitDecision para dict puro e serializável.

    Achata MappingProxyType, normaliza tipos para JSON-friendly,
    omite Mappings aninhadas (planifica em chaves simples quando
    possível). NÃO inclui execution_allowed nem qualquer flag de
    autorização — apenas a camada de capability é exposta.
    """
    md = dict(decision.metadata) if decision.metadata else {}
    snapshot: Dict[str, Any] = {
        "reason": decision.reason.value,
        "source": decision.source.value,
        "triggered_at_time": decision.triggered_at_time.isoformat(),
        "triggered_at_idx": decision.triggered_at_idx,
        "requires_reduce_only": bool(decision.requires_reduce_only),
        "auto_execute_blocked": bool(decision.auto_execute_blocked),
    }
    # Campos auditáveis do metadata (apenas escalares simples)
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
# Helper: latest signal cache (FASE 12 — usado em backtest para opposite-signal)
# ---------------------------------------------------------------------------
# Mantido fora do BacktestEngine para preservar a regressão byte-a-byte da
# legacy path. O BacktestEngine só consulta este cache quando use_exit_policy
# e allow_close_on_opposite_signal estão ativos.
