"""
PaperTrader — Executor Simulado de Paper Trading
==================================================
Executa ordens simuladas sem qualquer conexão com API real.

Responsabilidades:
    1. Receber sinais APROVADOS pelo RiskEngine (nunca bypassa o risco).
    2. Simular execução de ordens via MockExchange.
    3. Notificar o RiskEngine sobre trades abertos/fechados.
    4. Registrar todas as operações em log de auditoria.
    5. Manter histórico completo de trades simulados.
    6. Publicar eventos via EventBus.

⚠️  REGRAS INVIOLÁVEIS:
    - O PaperTrader NUNCA aceita um sinal não validado pelo RiskEngine.
    - O PaperTrader NUNCA se conecta à Bybit real.
    - Toda operação é registrada em log de auditoria.

Uso:
    paper_trader = PaperTrader(risk_engine, mock_exchange)
    result = paper_trader.execute(risk_result)  # risk_result.approved DEVE ser True
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from crypto_trading_bot.config.settings import Settings, get_settings
from crypto_trading_bot.core.mode_guard import ModeGuard
from crypto_trading_bot.exchange.base_exchange import BaseExchange, OrderResult
from crypto_trading_bot.exchange.mock_exchange import MockExchange
from crypto_trading_bot.logging_system.logger import get_audit_logger, get_logger
from crypto_trading_bot.risk.risk_engine import (
    OrderSide,
    RiskEngine,
    RiskResult,
    TradingSignal,
)

_logger = get_logger(__name__)
_audit = get_audit_logger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class PaperTradeStatus(str, Enum):
    """Status de um paper trade."""
    OPEN = "open"
    CLOSED_STOP_LOSS = "closed_stop_loss"
    CLOSED_TAKE_PROFIT = "closed_take_profit"
    CLOSED_MANUAL = "closed_manual"
    FAILED = "failed"
    # FASE 13 — valores adicionais usados pelo PaperExitOrchestrator (opt-in).
    # Não removem nem reordenam valores anteriores (compat. serialização).
    CLOSED_TIME_LIMIT = "closed_time_limit"
    CLOSED_OPPOSITE_SIGNAL = "closed_opposite_signal"
    CLOSED_EMERGENCY = "closed_emergency"


@dataclass
class PaperTrade:
    """
    Representa um trade simulado completo.

    Contém todas as informações de um trade desde a abertura até o fechamento.

    Atributos:
        trade_id: ID único do trade.
        signal: Sinal original que originou o trade.
        order_result: Resultado da ordem simulada.
        status: Estado atual do trade.
        opened_at: Timestamp de abertura.
        closed_at: Timestamp de fechamento (None se ainda aberto).
        close_price: Preço de fechamento (None se ainda aberto).
        pnl: PnL realizado após fechamento.
        pnl_pct: PnL percentual.
    """
    trade_id: str
    signal: TradingSignal
    order_result: OrderResult
    status: PaperTradeStatus = PaperTradeStatus.OPEN
    opened_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: Optional[datetime] = None
    close_price: Optional[float] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    # FASE 13 — Snapshot opcional da ExitDecision quando fechado via
    # PaperExitOrchestrator. Default None preserva retrocompat.
    exit_decision_snapshot: Optional[dict] = None

    @property
    def is_open(self) -> bool:
        return self.status == PaperTradeStatus.OPEN

    @property
    def is_closed(self) -> bool:
        return self.status != PaperTradeStatus.OPEN

    @property
    def position_size_usd(self) -> float:
        return self.signal.position_size_usd

    def __repr__(self) -> str:
        pnl_str = f"PnL={self.pnl:+.2f}" if self.is_closed else "ABERTO"
        return (
            f"PaperTrade("
            f"id={self.trade_id[:6]} | "
            f"{self.signal.symbol} {self.signal.side.value} | "
            f"entry={self.order_result.avg_fill_price} | "
            f"{pnl_str})"
        )


@dataclass
class PaperExecutionResult:
    """Resultado da execução pelo PaperTrader."""
    success: bool
    trade: Optional[PaperTrade]
    reason: str = ""

    def __repr__(self) -> str:
        status = "✅" if self.success else "❌"
        return f"PaperExecutionResult({status} | {self.reason or 'OK'})"


# ---------------------------------------------------------------------------
# PaperTrader
# ---------------------------------------------------------------------------

class PaperTrader:
    """
    Executor de paper trading — simula ordens sem API real.

    Recebe sinais APROVADOS pelo RiskEngine e os executa na MockExchange.
    Mantém estado de posições abertas e histórico completo de trades.

    Uso completo:
        exchange = MockExchange(initial_balance_usdt=5000.0)
        risk_engine = RiskEngine(initial_capital=5000.0)
        paper_trader = PaperTrader(risk_engine=risk_engine, exchange=exchange)

        # Gerar sinal da estratégia
        signal = strategy.generate_signal(market_data)

        # Validar com RiskEngine (OBRIGATÓRIO)
        risk_result = risk_engine.validate_signal(signal)

        # Executar apenas se aprovado
        if risk_result.approved:
            result = paper_trader.execute(risk_result)
    """

    def __init__(
        self,
        risk_engine: RiskEngine,
        exchange: Optional[BaseExchange] = None,
        mode_guard: Optional[ModeGuard] = None,
    ) -> None:
        """
        Inicializa o PaperTrader.

        Args:
            risk_engine: Instância do RiskEngine. OBRIGATÓRIO — não aceita None.
            exchange: Exchange a usar. Padrão: MockExchange(5000.0).
            mode_guard: ModeGuard para verificação de modo. Criado automaticamente se None.
        """
        if risk_engine is None:
            raise ValueError("PaperTrader requer uma instância de RiskEngine. Nunca passe None.")

        self._risk_engine = risk_engine

        # O saldo inicial do MockExchange é lido de settings.paper_trading_initial_balance
        # — não é hardcoded em 5000. Pode ser configurado via PAPER_TRADING_INITIAL_BALANCE no .env.
        if exchange is None:
            _settings = get_settings()
            exchange = MockExchange(
                initial_balance_usdt=_settings.paper_trading_initial_balance
            )

        self._exchange = exchange
        self._mode_guard = mode_guard or ModeGuard()

        # FASE 12 — preparação para ativação da ExitPolicy (sem consumo).
        # Setter armazena a policy mas nenhum método do PaperTrader a consulta
        # nesta fase. Ativação real fica para fase futura (Paper Activation).
        self._exit_policy = None  # type: ignore[var-annotated]

        # Verifica que estamos em modo seguro
        self._mode_guard.assert_safe_mode("PaperTrader.__init__")

        # Histórico de trades
        self._open_trades: Dict[str, PaperTrade] = {}
        self._closed_trades: List[PaperTrade] = []
        self._execution_count: int = 0

        _logger.info(
            f"PaperTrader inicializado | "
            f"exchange={self._exchange.name} | "
            f"mode={self._mode_guard.mode.value}"
        )

    # -----------------------------------------------------------------------
    # FASE 12 — Preparação para ExitPolicy (setter sem consumo)
    # -----------------------------------------------------------------------

    def set_exit_policy(self, policy) -> None:
        """
        Armazena uma ExitPolicy opcional. Setter de preparação.

        ⚠️  FASE 12: setter ARMAZENA mas NENHUM método do PaperTrader
            consulta esta policy. Ativação real é trabalho de fase futura
            (Paper Activation + Demo SL/TP Readiness).

        Args:
            policy: instância de ExitPolicy ou None para limpar.
        """
        if policy is not None:
            from crypto_trading_bot.exit_policy import ExitPolicy as _ExitPolicy
            if not isinstance(policy, _ExitPolicy):
                raise TypeError(
                    "set_exit_policy exige ExitPolicy ou None. "
                    f"Recebido: {type(policy).__name__}"
                )
        self._exit_policy = policy

    @property
    def exit_policy(self):
        """Acesso somente-leitura à ExitPolicy armazenada (FASE 12)."""
        return self._exit_policy

    # -----------------------------------------------------------------------
    # Execução Principal
    # -----------------------------------------------------------------------

    def execute(self, risk_result: RiskResult) -> PaperExecutionResult:
        """
        Executa um sinal aprovado pelo RiskEngine.

        ⚠️  REGRA INVIOLÁVEL: Só aceita RiskResult.approved=True.
        Se o RiskResult não for aprovado, lança ValueError imediatamente.

        Args:
            risk_result: Resultado da validação do RiskEngine.
                         DEVE ter approved=True.

        Returns:
            PaperExecutionResult com sucesso ou falha da execução.

        Raises:
            ValueError: Se risk_result.approved=False (violação de protocolo).
        """
        # Verificação de segurança: nunca aceita sinal não aprovado
        if not risk_result.approved:
            msg = (
                f"PaperTrader.execute() chamado com sinal NÃO APROVADO pelo RiskEngine. "
                f"Motivo do bloqueio: {risk_result.reason}. "
                f"NUNCA chame execute() sem verificar risk_result.approved antes."
            )
            _logger.error(msg)
            raise ValueError(msg)

        # Verificação de modo seguro
        self._mode_guard.assert_safe_mode("PaperTrader.execute")

        signal = risk_result.signal
        self._execution_count += 1

        _logger.info(
            f"PaperTrader.execute | "
            f"#{self._execution_count} | "
            f"symbol={signal.symbol} | "
            f"side={signal.side.value} | "
            f"strategy={signal.strategy_name}"
        )

        try:
            # Calcula quantidade a partir do tamanho em USD
            # Em paper trading, usa o preço atual do mock exchange
            # qty = position_size_usd / entry_price
            entry_price = signal.entry_price
            qty = round(signal.position_size_usd / entry_price, 8)

            if qty <= 0:
                raise ValueError(f"Quantidade calculada inválida: {qty}")

            # Executa ordem na exchange simulada
            order_result = self._exchange.place_market_order(
                symbol=signal.symbol,
                side=signal.side.value,
                qty=qty,
                stop_loss=signal.stop_loss_price,
                take_profit=signal.take_profit_price,
            )

            # Cria o registro do paper trade
            trade_id = str(uuid.uuid4())[:12].upper()
            trade = PaperTrade(
                trade_id=trade_id,
                signal=signal,
                order_result=order_result,
                status=PaperTradeStatus.OPEN,
                opened_at=datetime.now(timezone.utc),
            )

            # Registra o trade aberto
            self._open_trades[trade_id] = trade

            # Notifica o RiskEngine sobre o trade aberto
            self._risk_engine.record_trade_opened(signal)

            # Log de auditoria
            _audit.info(
                f"PaperTrader.TRADE_ABERTO | "
                f"id={trade_id} | "
                f"symbol={signal.symbol} | "
                f"side={signal.side.value} | "
                f"qty={qty} | "
                f"entry={order_result.avg_fill_price} | "
                f"stop={signal.stop_loss_price} | "
                f"tp={signal.take_profit_price} | "
                f"size_usd={signal.position_size_usd} | "
                f"strategy={signal.strategy_name} | "
                f"[SIMULADO]"
            )

            return PaperExecutionResult(
                success=True,
                trade=trade,
                reason=f"Trade aberto com sucesso | id={trade_id}",
            )

        except Exception as e:
            _logger.error(f"PaperTrader.execute: erro ao executar trade: {e}")
            _audit.error(
                f"PaperTrader.TRADE_FALHOU | "
                f"symbol={signal.symbol} | "
                f"side={signal.side.value} | "
                f"error={e}"
            )
            return PaperExecutionResult(
                success=False,
                trade=None,
                reason=str(e),
            )

    def close_trade(
        self,
        trade_id: str,
        close_price: float,
        reason: str = "manual",
        exit_decision_snapshot: Optional[dict] = None,
    ) -> PaperExecutionResult:
        """
        Fecha um paper trade aberto.

        Calcula o PnL, notifica o RiskEngine e move o trade para o histórico.

        Args:
            trade_id: ID do trade a fechar.
            close_price: Preço de fechamento.
            reason: Motivo do fechamento (ex: "stop_loss", "take_profit", "manual").

        Returns:
            PaperExecutionResult com o trade fechado.
        """
        trade = self._open_trades.get(trade_id)

        if trade is None:
            return PaperExecutionResult(
                success=False,
                trade=None,
                reason=f"Trade {trade_id} não encontrado nas posições abertas",
            )

        signal = trade.signal
        entry_price = trade.order_result.avg_fill_price or signal.entry_price
        qty = trade.order_result.filled_qty

        # Calcula PnL
        if signal.side == OrderSide.BUY:
            pnl = (close_price - entry_price) * qty
        else:
            pnl = (entry_price - close_price) * qty

        pnl_pct = pnl / signal.position_size_usd if signal.position_size_usd > 0 else 0.0

        # Determina o status
        status_map = {
            "stop_loss": PaperTradeStatus.CLOSED_STOP_LOSS,
            "take_profit": PaperTradeStatus.CLOSED_TAKE_PROFIT,
            # FASE 13 — motivos adicionais (opt-in via PaperExitOrchestrator)
            "time_limit": PaperTradeStatus.CLOSED_TIME_LIMIT,
            "opposite_signal": PaperTradeStatus.CLOSED_OPPOSITE_SIGNAL,
            "emergency": PaperTradeStatus.CLOSED_EMERGENCY,
        }
        status = status_map.get(reason.lower(), PaperTradeStatus.CLOSED_MANUAL)

        # Atualiza o trade
        trade.status = status
        trade.closed_at = datetime.now(timezone.utc)
        trade.close_price = close_price
        trade.pnl = round(pnl, 4)
        trade.pnl_pct = round(pnl_pct, 6)
        # FASE 13 — armazena snapshot apenas se fornecido (cópia defensiva).
        if exit_decision_snapshot is not None:
            trade.exit_decision_snapshot = dict(exit_decision_snapshot)

        # Move para fechados
        del self._open_trades[trade_id]
        self._closed_trades.append(trade)

        # Notifica o RiskEngine
        self._risk_engine.record_trade_closed(
            symbol=signal.symbol,
            pnl=pnl,
            size_usd=signal.position_size_usd,
        )

        # Log de auditoria
        emoji = "💚" if pnl >= 0 else "🔴"
        _audit.info(
            f"PaperTrader.TRADE_FECHADO | "
            f"id={trade_id} | "
            f"symbol={signal.symbol} | "
            f"side={signal.side.value} | "
            f"reason={reason} | "
            f"entry={entry_price} | "
            f"close={close_price} | "
            f"pnl={pnl:+.4f} ({pnl_pct:+.2%}) {emoji} | "
            f"strategy={signal.strategy_name} | "
            f"[SIMULADO]"
        )

        return PaperExecutionResult(
            success=True,
            trade=trade,
            reason=f"Trade fechado | pnl={pnl:+.4f}",
        )

    # -----------------------------------------------------------------------
    # Consultas de Estado
    # -----------------------------------------------------------------------

    @property
    def open_trades(self) -> Dict[str, PaperTrade]:
        """Trades atualmente abertos."""
        return dict(self._open_trades)

    @property
    def closed_trades(self) -> List[PaperTrade]:
        """Histórico de trades fechados."""
        return list(self._closed_trades)

    @property
    def execution_count(self) -> int:
        """Total de execuções realizadas."""
        return self._execution_count

    @property
    def total_pnl(self) -> float:
        """PnL total de todos os trades fechados."""
        return sum(t.pnl for t in self._closed_trades)

    @property
    def win_rate(self) -> Optional[float]:
        """Taxa de acerto. None se nenhum trade fechado ainda."""
        if not self._closed_trades:
            return None
        winning = sum(1 for t in self._closed_trades if t.pnl > 0)
        return winning / len(self._closed_trades)

    def get_summary(self) -> dict:
        """
        Retorna um resumo da performance do paper trader.

        Returns:
            Dicionário com métricas de performance.
        """
        closed = self._closed_trades
        winning = [t for t in closed if t.pnl > 0]
        losing = [t for t in closed if t.pnl <= 0]

        return {
            "total_executions": self._execution_count,
            "open_trades": len(self._open_trades),
            "closed_trades": len(closed),
            "total_pnl": round(self.total_pnl, 4),
            "win_rate": round(self.win_rate, 4) if self.win_rate is not None else None,
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "avg_win": round(sum(t.pnl for t in winning) / len(winning), 4) if winning else 0.0,
            "avg_loss": round(sum(t.pnl for t in losing) / len(losing), 4) if losing else 0.0,
            "balance": self._exchange.get_balance(),
            "mode": "paper_simulation",
        }

    def __repr__(self) -> str:
        return (
            f"PaperTrader("
            f"open={len(self._open_trades)} | "
            f"closed={len(self._closed_trades)} | "
            f"pnl={self.total_pnl:+.2f})"
        )
