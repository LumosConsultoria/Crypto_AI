"""
BybitTestnetExecutor — FASE 5
================================
Executor que envia ordens à Bybit TESTNET (apenas testnet, jamais mainnet),
usando o BybitClient autenticado (extensão mínima da FASE 5).

⚠️  ZERO ordens mainnet. ZERO ordens live. ZERO uso de API key real em testes.
⚠️  Toda invocação privada exige ModeGuard.assert_testnet_execution_allowed.
⚠️  PaperTrader continua sendo o default do BotEngine.
    Esta camada é uso MANUAL via scripts/run_testnet_diagnostic.py.
⚠️  Resultados em testnet NÃO garantem performance em conta real.

ARQUITETURA:
    BybitTestnetExecutor
        ├─ ModeGuard.assert_testnet_execution_allowed (triple-lock testnet)
        ├─ BybitClient (autenticado, com HMAC, testnet apenas)
        ├─ RiskEngine (recebe record_trade_opened após sucesso confirmado)
        └─ TestnetTrade + TestnetExecutionResult (auditoria local)

INVARIANTES:
    1. execute(risk_result) REJEITA se risk_result.approved=False (igual PaperTrader).
    2. ModeGuard é verificado ANTES de qualquer chamada privada.
    3. BybitClient.use_testnet=True é obrigatório (Defesa em profundidade).
    4. dry_run=True NUNCA chama BybitClient privado.
    5. safe_check_only=True chama APENAS get_balance (read após auth).
    6. record_trade_opened só é chamado APÓS confirmação de fill.
    7. Logs NUNCA contêm api_key/api_secret/sign — uso de log_redaction.
    8. position_size e leverage vêm de TradingSignal; nada hardcoded aqui.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Mapping, Optional

from crypto_trading_bot.core.mode_guard import ModeGuard
from crypto_trading_bot.exchange.bybit_client import (
    BybitClient,
    BybitExecutionBlockedError,
)
from crypto_trading_bot.logging_system.logger import get_audit_logger, get_logger
from crypto_trading_bot.risk.risk_engine import RiskEngine, RiskResult, TradingSignal

_logger = get_logger(__name__)
_audit = get_audit_logger(__name__)


class TestnetExecutionError(RuntimeError):
    """Erro genérico durante execução testnet (sem expor secrets)."""


class TestnetTradeStatus(str, Enum):
    SUBMITTED = "submitted"          # ordem aceita pela API; aguarda fill
    FILLED = "filled"                # confirmação de execução
    CANCELED = "canceled"             # cancelada por nós
    FAILED = "failed"                 # falha confirmada


@dataclass(frozen=True)
class TestnetTrade:
    """
    Registro imutável de um trade enviado à Bybit testnet.

    ⚠️  Este registro NUNCA contém api_key/secret/headers. Apenas dados do trade.
    """
    trade_id: str
    order_id: str
    symbol: str
    side: str                # "buy" | "sell"
    qty: float
    position_size_usd: float
    leverage: float
    entry_price_signal: float
    stop_loss_price: float
    take_profit_price: Optional[float]
    submitted_at: datetime
    status: TestnetTradeStatus
    raw_order_status: Mapping[str, Any] = field(default_factory=dict)
    position_snapshot: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TestnetExecutionResult:
    """
    Resultado imutável de uma chamada a execute()/cancel_pending()/safe_check_only().

    success=True indica que a Bybit aceitou e confirmou (quando aplicável);
    success=False indica bloqueio/erro.
    """
    success: bool
    operation: str           # "place_order" | "cancel_order" | "safe_check"
    trade: Optional[TestnetTrade] = None
    reason: str = ""
    dry_run: bool = False
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def to_dict(self) -> dict:
        """Serializa para dict (sem secrets — apenas metadados do trade)."""
        d = {
            "success": self.success,
            "operation": self.operation,
            "reason": self.reason,
            "dry_run": self.dry_run,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.trade is not None:
            d["trade"] = {
                "trade_id": self.trade.trade_id,
                "order_id": self.trade.order_id,
                "symbol": self.trade.symbol,
                "side": self.trade.side,
                "qty": self.trade.qty,
                "position_size_usd": self.trade.position_size_usd,
                "leverage": self.trade.leverage,
                "status": self.trade.status.value,
                "submitted_at": self.trade.submitted_at.isoformat(),
            }
        return d


class BybitTestnetExecutor:
    """
    Executor para Bybit testnet (manual, via scripts).

    Não é integrado ao BotEngine nesta fase. Uso típico:

        from crypto_trading_bot.execution import BybitTestnetExecutor
        from crypto_trading_bot.core.mode_guard import ModeGuard
        from crypto_trading_bot.risk.risk_engine import RiskEngine
        from crypto_trading_bot.exchange.bybit_client import BybitClient

        # Pré-condições: TRADING_MODE=testnet + ENABLE_TESTNET_EXECUTION=true no .env
        mode_guard = ModeGuard()
        client = BybitClient(
            use_testnet=True,
            api_key=settings.bybit_api_key,
            api_secret=settings.bybit_api_secret,
            recv_window=5000,
        )
        risk = RiskEngine(initial_capital=user_provided_capital)

        executor = BybitTestnetExecutor(
            client=client,
            mode_guard=mode_guard,
            risk_engine=risk,
            confirm_testnet_execution=True,   # ⚠️  exigido
        )

        # Sanity: testnet conectividade + auth (somente get_balance, NÃO ordem)
        check_result = executor.safe_check_only(dry_run=False)

        # Execução real (após risco aprovado externamente)
        approved = risk.validate_signal(signal)
        if approved.approved:
            result = executor.execute(approved, dry_run=False)
    """

    def __init__(
        self,
        client: BybitClient,
        mode_guard: ModeGuard,
        risk_engine: RiskEngine,
        confirm_testnet_execution: bool = False,
    ) -> None:
        """
        Args:
            client:                    BybitClient JÁ configurado com credentials testnet.
            mode_guard:                ModeGuard configurado pelas Settings.
            risk_engine:               RiskEngine soberano.
            confirm_testnet_execution: DEVE ser True para qualquer chamada
                                       que envie ordem. Default False — força
                                       o caller a tomar a decisão explícita.
        """
        # Defesa em profundidade: client DEVE ser testnet
        if not client.use_testnet:
            raise BybitExecutionBlockedError(
                "⛔ BybitTestnetExecutor recusa BybitClient com use_testnet=False. "
                "Mainnet está PERMANENTEMENTE bloqueado neste executor."
            )

        self._client = client
        self._mode_guard = mode_guard
        self._risk_engine = risk_engine
        self._confirm_testnet_execution = bool(confirm_testnet_execution)
        # Estado local (auditável; sem secrets)
        self._submitted_trades: Dict[str, TestnetTrade] = {}

        _audit.info(
            f"BybitTestnetExecutor inicializado | "
            f"client_testnet={client.use_testnet} | "
            f"client_has_credentials={client.has_credentials} | "
            f"confirm_testnet_execution={self._confirm_testnet_execution}"
        )

    # -----------------------------------------------------------------------
    # safe_check_only — apenas verifica auth (get_balance)
    # -----------------------------------------------------------------------

    def safe_check_only(self, dry_run: bool = True) -> TestnetExecutionResult:
        """
        Sanity check: chama get_balance() em testnet APENAS — não envia ordem.

        Útil para validar HMAC + conectividade testnet sem riscos.

        Args:
            dry_run: Se True (default), NÃO chama BybitClient. Apenas valida
                     configuração e retorna sucesso simulado.

        Returns:
            TestnetExecutionResult com operation="safe_check".
        """
        if dry_run:
            _logger.info("safe_check_only: DRY-RUN — nenhuma chamada feita.")
            return TestnetExecutionResult(
                success=True,
                operation="safe_check",
                reason="dry_run: configuração validada sem chamar API",
                dry_run=True,
            )

        # Verifica ModeGuard ANTES de qualquer chamada privada
        try:
            self._mode_guard.assert_testnet_execution_allowed(
                confirm_testnet_execution=self._confirm_testnet_execution,
                context="BybitTestnetExecutor.safe_check_only",
            )
        except Exception as e:
            return TestnetExecutionResult(
                success=False,
                operation="safe_check",
                reason=f"ModeGuard bloqueou: {e}",
            )

        try:
            _ = self._client.get_balance()
        except BybitExecutionBlockedError as e:
            return TestnetExecutionResult(
                success=False,
                operation="safe_check",
                reason=f"BybitClient bloqueou (sem credentials?): {e}",
            )
        except Exception as e:
            return TestnetExecutionResult(
                success=False,
                operation="safe_check",
                reason=f"Bybit API erro: {type(e).__name__}",
            )

        _audit.info("safe_check_only: get_balance() OK — auth validada.")
        return TestnetExecutionResult(
            success=True,
            operation="safe_check",
            reason="get_balance executado com sucesso",
        )

    # -----------------------------------------------------------------------
    # execute — envio de ordem após aprovação do RiskEngine
    # -----------------------------------------------------------------------

    def execute(
        self,
        risk_result: RiskResult,
        dry_run: bool = True,
    ) -> TestnetExecutionResult:
        """
        Envia uma ordem testnet, condicionado a:
            1. risk_result.approved=True (INVARIANTE igual ao PaperTrader)
            2. ModeGuard.assert_testnet_execution_allowed passa
            3. BybitClient.use_testnet=True (verificado no __init__)
            4. dry_run=False (caller pediu execução real)

        Args:
            risk_result: Resultado do RiskEngine. DEVE ter approved=True.
            dry_run:     Se True (default), simula sem chamar a API.

        Returns:
            TestnetExecutionResult.

        Raises:
            ValueError: se risk_result.approved=False (INVARIANTE).
        """
        # Invariante: NUNCA executa sem aprovação
        if not risk_result.approved:
            raise ValueError(
                "BybitTestnetExecutor.execute REJEITA risk_result não aprovado. "
                "Esta é uma INVARIANTE de segurança — fluxo deve passar pelo RiskEngine."
            )

        signal: TradingSignal = risk_result.signal

        if dry_run:
            _logger.info(
                f"execute: DRY-RUN | symbol={signal.symbol} | "
                f"side={signal.side.value} | size_usd={signal.position_size_usd}"
            )
            return TestnetExecutionResult(
                success=True,
                operation="place_order",
                reason=(
                    "dry_run: ordem não enviada à Bybit. "
                    f"Payload simulado: symbol={signal.symbol}, "
                    f"side={signal.side.value}, size_usd={signal.position_size_usd}."
                ),
                dry_run=True,
            )

        # Verifica ModeGuard ANTES de qualquer chamada privada
        try:
            self._mode_guard.assert_testnet_execution_allowed(
                confirm_testnet_execution=self._confirm_testnet_execution,
                context="BybitTestnetExecutor.execute",
            )
        except Exception as e:
            return TestnetExecutionResult(
                success=False,
                operation="place_order",
                reason=f"ModeGuard bloqueou: {e}",
            )

        # Calcula qty a partir do position_size_usd e entry_price do signal
        # ⚠️  position_size e leverage vêm DO SIGNAL; nada hardcoded aqui.
        if signal.entry_price <= 0:
            return TestnetExecutionResult(
                success=False,
                operation="place_order",
                reason="entry_price inválido no signal (<=0)",
            )
        qty = signal.position_size_usd / signal.entry_price

        # Envia ordem (BybitClient verifica credentials + use_testnet)
        try:
            order_result = self._client.place_market_order(
                symbol=signal.symbol,
                side=signal.side.value,           # "buy" ou "sell"
                qty=qty,
                stop_loss=signal.stop_loss_price,
                take_profit=signal.take_profit_price,
            )
        except BybitExecutionBlockedError as e:
            return TestnetExecutionResult(
                success=False,
                operation="place_order",
                reason=f"BybitClient bloqueou: {e}",
            )
        except Exception as e:
            return TestnetExecutionResult(
                success=False,
                operation="place_order",
                reason=f"Bybit API erro ao enviar ordem: {type(e).__name__}",
            )

        order_id = order_result.order_id
        _audit.info(
            f"execute: ordem submetida | order_id={order_id} | "
            f"symbol={signal.symbol} | side={signal.side.value} | qty={qty}"
        )

        # Reconciliação: status da ordem
        raw_order_status: Dict[str, Any] = {}
        try:
            raw_order_status = self._client.get_order_status(
                symbol=signal.symbol, order_id=order_id,
            )
        except Exception as e:
            _logger.warning(
                f"Não foi possível obter order_status (ordem submetida mas não reconciliada): "
                f"{type(e).__name__}"
            )

        # Reconciliação: snapshot de posições
        position_snapshot: Dict[str, Any] = {}
        try:
            positions = self._client.get_positions(symbol=signal.symbol)
            if positions:
                position_snapshot = dict(positions[0])
        except Exception as e:
            _logger.warning(
                f"Não foi possível obter position snapshot: {type(e).__name__}"
            )

        # Cria registro local imutável (sem secrets)
        trade_id = f"BT_TESTNET_{signal.symbol}_{order_id}"
        # Decide status com base no order_status (best-effort)
        raw_status = str(raw_order_status.get("orderStatus", "")).lower()
        if raw_status in ("filled", "partiallyfilled"):
            status = TestnetTradeStatus.FILLED
        elif raw_status in ("cancelled", "canceled"):
            status = TestnetTradeStatus.CANCELED
        elif raw_status == "":
            status = TestnetTradeStatus.SUBMITTED
        else:
            status = TestnetTradeStatus.SUBMITTED

        trade = TestnetTrade(
            trade_id=trade_id,
            order_id=order_id,
            symbol=signal.symbol,
            side=signal.side.value,
            qty=qty,
            position_size_usd=signal.position_size_usd,
            leverage=signal.leverage,
            entry_price_signal=signal.entry_price,
            stop_loss_price=signal.stop_loss_price,
            take_profit_price=signal.take_profit_price,
            submitted_at=datetime.now(timezone.utc),
            status=status,
            raw_order_status=raw_order_status,
            position_snapshot=position_snapshot,
        )
        self._submitted_trades[trade_id] = trade

        # Notifica RiskEngine APÓS sucesso confirmado (best-effort)
        # Política conservadora: notifica somente se status == FILLED.
        if status is TestnetTradeStatus.FILLED:
            try:
                self._risk_engine.record_trade_opened(signal)
            except Exception as e:
                _logger.warning(
                    f"RiskEngine.record_trade_opened falhou: {type(e).__name__}"
                )

        return TestnetExecutionResult(
            success=True,
            operation="place_order",
            trade=trade,
            reason="ordem submetida e reconciliada (best-effort)",
        )

    # -----------------------------------------------------------------------
    # cancel_pending — cancela uma ordem submetida
    # -----------------------------------------------------------------------

    def cancel_pending(
        self,
        symbol: str,
        order_id: str,
        dry_run: bool = True,
    ) -> TestnetExecutionResult:
        """
        Cancela uma ordem previamente submetida à testnet.

        Args:
            symbol:   Símbolo da ordem.
            order_id: Order ID retornado por execute().
            dry_run:  Se True (default), NÃO chama API.

        Returns:
            TestnetExecutionResult com operation="cancel_order".
        """
        if dry_run:
            return TestnetExecutionResult(
                success=True,
                operation="cancel_order",
                reason=f"dry_run: cancel simulado para order_id={order_id}",
                dry_run=True,
            )

        try:
            self._mode_guard.assert_testnet_execution_allowed(
                confirm_testnet_execution=self._confirm_testnet_execution,
                context="BybitTestnetExecutor.cancel_pending",
            )
        except Exception as e:
            return TestnetExecutionResult(
                success=False,
                operation="cancel_order",
                reason=f"ModeGuard bloqueou: {e}",
            )

        try:
            ok = self._client.cancel_order(symbol=symbol, order_id=order_id)
        except Exception as e:
            return TestnetExecutionResult(
                success=False,
                operation="cancel_order",
                reason=f"Bybit API erro ao cancelar: {type(e).__name__}",
            )

        _audit.info(f"cancel_pending: order_id={order_id} | ok={ok}")
        return TestnetExecutionResult(
            success=bool(ok),
            operation="cancel_order",
            reason=f"cancel executado para order_id={order_id}",
        )

    # -----------------------------------------------------------------------
    # Acessadores
    # -----------------------------------------------------------------------

    @property
    def submitted_trades(self) -> Mapping[str, TestnetTrade]:
        """Snapshot read-only de trades submetidos nesta sessão."""
        return dict(self._submitted_trades)

    def get_summary(self) -> dict:
        """
        Retorna um resumo dos trades submetidos (sem secrets).
        Útil para diagnóstico em scripts.
        """
        return {
            "n_submitted": len(self._submitted_trades),
            "n_filled": sum(
                1 for t in self._submitted_trades.values()
                if t.status is TestnetTradeStatus.FILLED
            ),
            "n_canceled": sum(
                1 for t in self._submitted_trades.values()
                if t.status is TestnetTradeStatus.CANCELED
            ),
            "trade_ids": list(self._submitted_trades.keys()),
        }
