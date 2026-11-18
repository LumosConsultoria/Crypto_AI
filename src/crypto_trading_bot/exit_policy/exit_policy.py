"""
ExitPolicy — Camada determinística de decisão de saída (FASE 11)
=================================================================
⚠️  AVISOS OBRIGATÓRIOS:
    - ExitPolicy NÃO chama executor, NÃO chama rede, NÃO envia ordem.
    - ExitPolicy NÃO conhece BybitClient/BybitDemoExecutor/qualquer
      provider real. Apenas consome ProviderCapability (frozen dataclass).
    - ExitPolicy NÃO chama RiskEngine. O RiskEngine continua soberano
      como SEGUNDA camada de proteção (anti-flip + invariantes).
    - auto_execute_blocked é decisão de CAPABILITY. Mesmo False, execução
      real depende de gates futuros (ProviderStatus, ModeGuard, ambiente,
      integração com executor). Capability ≠ autorização.
    - require_reduce_only_for_auto_close=False NÃO libera fechamento
      automático externo. O override só afeta o campo requires_reduce_only
      reportado; auto_execute_blocked CONTINUA refletindo a capability.

ORDEM DE PRECEDÊNCIA (hard-coded, determinística):
    1. emergency_active        → EMERGENCY
    2. manual_close_requested  → MANUAL
    3. SL hit no candle        → STOP_LOSS
    4. TP hit no candle        → TAKE_PROFIT  (SL vence TP no mesmo candle)
    5. Sinal contrário         → OPPOSITE_SIGNAL  (se habilitado)
    6. Tempo excedido          → TIME_LIMIT  (por candles ou por segundos)
    7. Default                 → should_close=False

REGRA DE AMBIGUIDADE SL/TP:
    Mantém a regra conservadora do BacktestEngine: quando o mesmo candle
    apresenta low <= stop_loss E high >= take_profit, o STOP LOSS vence.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.execution.provider_capability import ProviderCapability
from crypto_trading_bot.exit_policy.exit_decision import (
    ExitDecision,
    ExitReason,
    ExitSource,
    OpenPositionState,
    PositionSide,
    make_hold_decision,
)
from crypto_trading_bot.logging_system.logger import get_audit_logger, get_logger
from crypto_trading_bot.strategies.signal_model import (
    StrategyAction,
    StrategySignal,
)

_logger = get_logger(__name__)
_audit = get_audit_logger(__name__)


class ExitPolicy:
    """
    Política de saída determinística e auditável.

    Parâmetros:
        provider_capability:                ProviderCapability do destino
                                            futuro (sem chamada de rede).
        max_time_in_position_candles:       Limite por candles em modo
                                            backtest. None desativa.
        max_time_in_position_seconds:       Limite por tempo de relógio em
                                            modo live/paper. None desativa.
        allow_close_on_opposite_signal:     Se True, sinal contrário fecha.
        require_reduce_only_for_auto_close: Se True (default), o campo
                                            requires_reduce_only=True em
                                            toda decisão de fechamento.
                                            Se False, requires_reduce_only=False
                                            é reportado — MAS isso não
                                            libera providers sem reduceOnly.
                                            auto_execute_blocked permanece
                                            refletindo a capability.
        emergency_close_enabled:            Se True, emergency_active=True
                                            no evaluate() dispara EMERGENCY.

    Garantias:
        - Determinística: mesma entrada → mesma decisão.
        - 100% offline. Não chama rede. Não chama executor.
        - Audita exatamente 1 linha EXIT_DECISION por should_close=True.
        - Sem secrets, sem PII, sem credenciais nos logs.
    """

    def __init__(
        self,
        provider_capability: ProviderCapability,
        *,
        max_time_in_position_candles: Optional[int] = None,
        max_time_in_position_seconds: Optional[int] = None,
        allow_close_on_opposite_signal: bool = False,
        require_reduce_only_for_auto_close: bool = True,
        emergency_close_enabled: bool = False,
    ) -> None:
        if not isinstance(provider_capability, ProviderCapability):
            raise TypeError(
                "provider_capability deve ser ProviderCapability"
            )
        if (max_time_in_position_candles is not None
                and max_time_in_position_candles <= 0):
            raise ValueError(
                f"max_time_in_position_candles deve ser > 0: "
                f"{max_time_in_position_candles}"
            )
        if (max_time_in_position_seconds is not None
                and max_time_in_position_seconds <= 0):
            raise ValueError(
                f"max_time_in_position_seconds deve ser > 0: "
                f"{max_time_in_position_seconds}"
            )

        self._capability = provider_capability
        self._max_candles = max_time_in_position_candles
        self._max_seconds = max_time_in_position_seconds
        self._allow_opposite = allow_close_on_opposite_signal
        self._require_reduce_only = require_reduce_only_for_auto_close
        self._emergency_enabled = emergency_close_enabled

        if not require_reduce_only_for_auto_close:
            # Aviso explícito: override seguro apenas para paper/backtest/manual.
            # NUNCA pode liberar provider externo sem reduceOnly.
            _logger.warning(
                "[ExitPolicy] require_reduce_only_for_auto_close=False — "
                "permitido apenas para paper/backtest/manual. Providers sem "
                "supports_reduce_only continuam com auto_execute_blocked=True."
            )

        _logger.info(
            f"[ExitPolicy] inicializada | provider={provider_capability.provider_id} | "
            f"reduce_only={provider_capability.supports_reduce_only} | "
            f"max_candles={max_time_in_position_candles} | "
            f"max_seconds={max_time_in_position_seconds} | "
            f"opposite={allow_close_on_opposite_signal} | "
            f"require_ro={require_reduce_only_for_auto_close} | "
            f"emergency={emergency_close_enabled}"
        )

    # -----------------------------------------------------------------------
    # Properties públicas (FASE 12 — leitura por integradores)
    # -----------------------------------------------------------------------

    @property
    def allow_opposite_signal(self) -> bool:
        """Indica se a política consume sinais contrários como gatilho."""
        return self._allow_opposite

    @property
    def has_time_limit(self) -> bool:
        """Indica se algum limite temporal está configurado."""
        return self._max_candles is not None or self._max_seconds is not None

    @property
    def provider_capability(self) -> ProviderCapability:
        """Acesso somente-leitura à capability associada à política."""
        return self._capability

    # -----------------------------------------------------------------------
    # API principal
    # -----------------------------------------------------------------------

    def evaluate(
        self,
        position: OpenPositionState,
        *,
        candle: Optional[Candle] = None,
        now: Optional[datetime] = None,
        candle_idx: Optional[int] = None,
        latest_signal: Optional[StrategySignal] = None,
        manual_close_requested: bool = False,
        emergency_active: bool = False,
    ) -> ExitDecision:
        """
        Avalia se a posição deve ser fechada agora.

        Args:
            position:               Estado da posição aberta.
            candle:                 Candle atual (None permitido em modo
                                    live sem grade).
            now:                    Timestamp atual UTC (None → utcnow).
            candle_idx:             Índice do candle atual (backtest) ou None.
            latest_signal:          Sinal mais recente da estratégia (para
                                    regra de opposite_signal). Pode ser None.
            manual_close_requested: Operador humano pediu fechamento.
            emergency_active:       Kill switch ativo.

        Returns:
            ExitDecision (imutável). Quando should_close=True, uma linha
            de audit EXIT_DECISION é emitida exatamente uma vez.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # 1. EMERGENCY (precedência máxima)
        if emergency_active and self._emergency_enabled:
            return self._build_close_decision(
                position=position,
                reason=ExitReason.EMERGENCY,
                source=ExitSource.RULE_EMERGENCY,
                now=now,
                candle_idx=candle_idx,
                trigger_price=candle.close if candle is not None else None,
                extra_metadata={"emergency_active": True},
            )

        # 2. MANUAL
        if manual_close_requested:
            return self._build_close_decision(
                position=position,
                reason=ExitReason.MANUAL,
                source=ExitSource.RULE_MANUAL,
                now=now,
                candle_idx=candle_idx,
                trigger_price=candle.close if candle is not None else None,
                extra_metadata={"manual": True},
            )

        # 3 e 4. SL e TP (regra conservadora: SL vence TP no mesmo candle)
        if candle is not None:
            sl_hit, tp_hit = self._sl_tp_hits(position, candle)
            if sl_hit:
                return self._build_close_decision(
                    position=position,
                    reason=ExitReason.STOP_LOSS,
                    source=ExitSource.RULE_SL_TP,
                    now=now,
                    candle_idx=candle_idx,
                    trigger_price=position.stop_loss_price,
                    extra_metadata={
                        "candle_low": candle.low,
                        "candle_high": candle.high,
                        "tp_also_hit": tp_hit,  # auditabilidade ambiguidade
                    },
                )
            if tp_hit:
                return self._build_close_decision(
                    position=position,
                    reason=ExitReason.TAKE_PROFIT,
                    source=ExitSource.RULE_SL_TP,
                    now=now,
                    candle_idx=candle_idx,
                    trigger_price=position.take_profit_price,
                    extra_metadata={
                        "candle_low": candle.low,
                        "candle_high": candle.high,
                    },
                )

        # 5. OPPOSITE SIGNAL (se habilitado)
        if (self._allow_opposite
                and latest_signal is not None
                and self._is_opposite_signal(position, latest_signal)):
            return self._build_close_decision(
                position=position,
                reason=ExitReason.OPPOSITE_SIGNAL,
                source=ExitSource.RULE_OPPOSITE,
                now=now,
                candle_idx=candle_idx,
                trigger_price=(
                    latest_signal.entry_price if latest_signal else None
                ),
                extra_metadata={
                    "opposite_action": latest_signal.action.value,
                    "opposite_strategy": latest_signal.strategy_name,
                },
            )

        # 6. TIME LIMIT
        time_decision = self._time_limit_check(
            position=position, now=now, candle_idx=candle_idx, candle=candle
        )
        if time_decision is not None:
            return time_decision

        # 7. Default
        return make_hold_decision(now)

    # -----------------------------------------------------------------------
    # Regras internas
    # -----------------------------------------------------------------------

    def _sl_tp_hits(
        self, position: OpenPositionState, candle: Candle
    ) -> tuple[bool, bool]:
        """
        Detecta hit de SL/TP no candle dado.

        BUY:  stop hit ↔ low <= stop_loss; tp hit ↔ high >= take_profit.
        SELL: stop hit ↔ high >= stop_loss; tp hit ↔ low <= take_profit.

        Regra de ambiguidade resolvida em evaluate() (SL vence).
        """
        if position.side == PositionSide.BUY:
            sl_hit = candle.low <= position.stop_loss_price
            tp_hit = (
                position.take_profit_price is not None
                and candle.high >= position.take_profit_price
            )
        else:  # SELL
            sl_hit = candle.high >= position.stop_loss_price
            tp_hit = (
                position.take_profit_price is not None
                and candle.low <= position.take_profit_price
            )
        return sl_hit, tp_hit

    def _is_opposite_signal(
        self, position: OpenPositionState, signal: StrategySignal
    ) -> bool:
        """True se o sinal aponta em direção oposta à posição aberta."""
        if not signal.is_actionable:
            return False
        if position.side == PositionSide.BUY:
            return signal.action == StrategyAction.SELL
        return signal.action == StrategyAction.BUY

    def _time_limit_check(
        self,
        *,
        position: OpenPositionState,
        now: datetime,
        candle_idx: Optional[int],
        candle: Optional[Candle],
    ) -> Optional[ExitDecision]:
        """
        Verifica limites de tempo (por candles e por segundos).

        Por candles (backtest): exige candle_idx + position.entry_candle_idx.
        Por segundos (live):    usa now - position.entry_time.
        """
        if self._max_candles is not None:
            if (candle_idx is not None
                    and position.entry_candle_idx is not None):
                elapsed_candles = candle_idx - position.entry_candle_idx
                if elapsed_candles >= self._max_candles:
                    return self._build_close_decision(
                        position=position,
                        reason=ExitReason.TIME_LIMIT,
                        source=ExitSource.RULE_TIME,
                        now=now,
                        candle_idx=candle_idx,
                        trigger_price=(
                            candle.close if candle is not None else None
                        ),
                        extra_metadata={
                            "limit_kind": "candles",
                            "limit_value": self._max_candles,
                            "elapsed_candles": elapsed_candles,
                        },
                    )

        if self._max_seconds is not None:
            entry_time = position.entry_time
            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=timezone.utc)
            elapsed_seconds = (now - entry_time).total_seconds()
            if elapsed_seconds >= self._max_seconds:
                return self._build_close_decision(
                    position=position,
                    reason=ExitReason.TIME_LIMIT,
                    source=ExitSource.RULE_TIME,
                    now=now,
                    candle_idx=candle_idx,
                    trigger_price=(
                        candle.close if candle is not None else None
                    ),
                    extra_metadata={
                        "limit_kind": "seconds",
                        "limit_value": self._max_seconds,
                        "elapsed_seconds": round(elapsed_seconds, 3),
                    },
                )

        return None

    # -----------------------------------------------------------------------
    # Construção de decisão + audit
    # -----------------------------------------------------------------------

    def _build_close_decision(
        self,
        *,
        position: OpenPositionState,
        reason: ExitReason,
        source: ExitSource,
        now: datetime,
        candle_idx: Optional[int],
        trigger_price: Optional[float],
        extra_metadata: Optional[Mapping[str, Any]] = None,
    ) -> ExitDecision:
        """
        Constrói ExitDecision para should_close=True e emite 1 linha de audit.

        auto_execute_blocked SEMPRE reflete a capability (NÃO o override).
        requires_reduce_only respeita o override, mas o override NÃO libera
        execução automática para providers sem supports_reduce_only.

        MANUAL e EMERGENCY: humano pode fechar manualmente fora do bot;
        a decisão ainda reporta auto_execute_blocked da capability para
        o caso de algum integrador futuro tentar auto-executar.
        """
        capability_allows_auto_close = self._capability.supports_reduce_only
        auto_execute_blocked = not capability_allows_auto_close
        requires_reduce_only = bool(self._require_reduce_only)

        elapsed_candles: Optional[int] = None
        if (candle_idx is not None
                and position.entry_candle_idx is not None):
            elapsed_candles = candle_idx - position.entry_candle_idx

        elapsed_seconds: Optional[float] = None
        entry_time = position.entry_time
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(tzinfo=timezone.utc)
        try:
            elapsed_seconds = round((now - entry_time).total_seconds(), 3)
        except (TypeError, ValueError):
            elapsed_seconds = None

        # Metadata: capability_allows_auto_close inclui o gate técnico;
        # NÃO incluímos "execution_allowed" — capability ≠ autorização.
        metadata: dict[str, Any] = {
            "capability_allows_auto_close": capability_allows_auto_close,
            "provider_id": self._capability.provider_id,
            "side": position.side.value,
            "entry_price": position.entry_price,
            "stop_loss_price": position.stop_loss_price,
            "take_profit_price": position.take_profit_price,
            "position_size_usd": position.position_size_usd,
            "trigger_price": trigger_price,
            "elapsed_candles": elapsed_candles,
            "elapsed_seconds": elapsed_seconds,
        }
        if extra_metadata:
            metadata.update(extra_metadata)

        decision = ExitDecision(
            should_close=True,
            reason=reason,
            source=source,
            triggered_at_time=now,
            requires_reduce_only=requires_reduce_only,
            auto_execute_blocked=auto_execute_blocked,
            triggered_at_idx=candle_idx,
            metadata=MappingProxyType(metadata),
        )

        # Audit determinístico — exatamente 1 linha por should_close=True.
        _audit.info(self._format_audit_line(position, decision))
        return decision

    @staticmethod
    def _format_audit_line(
        position: OpenPositionState, decision: ExitDecision
    ) -> str:
        """
        Formata a linha de audit. Determinística e sem secrets.

        Campos: reason, source, symbol, side, reduce_only_required,
        auto_blocked, entry, trigger, elapsed.
        """
        md = decision.metadata
        trigger_price = md.get("trigger_price")
        trigger_str = (
            f"{trigger_price:.4f}" if isinstance(trigger_price, (int, float))
            else "n/a"
        )
        elapsed_c = md.get("elapsed_candles")
        elapsed_s = md.get("elapsed_seconds")
        elapsed_parts = []
        if elapsed_c is not None:
            elapsed_parts.append(f"candles={elapsed_c}")
        if elapsed_s is not None:
            elapsed_parts.append(f"seconds={elapsed_s}")
        elapsed_str = ",".join(elapsed_parts) if elapsed_parts else "n/a"

        return (
            f"EXIT_DECISION | "
            f"reason={decision.reason.value} | "
            f"source={decision.source.value} | "
            f"symbol={position.symbol} | "
            f"side={position.side.value} | "
            f"reduce_only_required={decision.requires_reduce_only} | "
            f"auto_blocked={decision.auto_execute_blocked} | "
            f"entry={position.entry_price:.4f} | "
            f"trigger={trigger_str} | "
            f"elapsed={elapsed_str} | "
            f"provider_cap={md.get('provider_id', 'unknown')}"
        )
