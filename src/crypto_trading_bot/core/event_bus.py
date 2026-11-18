"""
Event Bus — Barramento de Eventos Interno
==========================================
Sistema simples de publicação/assinatura de eventos para comunicação
desacoplada entre módulos do sistema.

Eventos típicos:
- SignalGenerated: nova estratégia gerou um sinal
- RiskApproved: risco aprovou execução
- RiskBlocked: risco bloqueou execução
- OrderSimulated: ordem simulada pelo paper trader
- OrderPlaced: ordem enviada à exchange (live/testnet)
- OrderFilled: ordem executada
- DailyLimitReached: limite diário atingido

Uso:
    bus = EventBus()
    bus.subscribe("signal_generated", my_handler)
    bus.publish("signal_generated", {"symbol": "BTCUSDT", "side": "buy"})
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Callable, Dict, List

from crypto_trading_bot.logging_system.logger import get_logger

_logger = get_logger(__name__)

# Eventos válidos do sistema
VALID_EVENTS = {
    "signal_generated",
    "risk_approved",
    "risk_blocked",
    "order_simulated",
    "order_placed",
    "order_filled",
    "order_cancelled",
    "trade_executed",          # trade simulado ou real executado com sucesso
    "daily_limit_reached",
    "total_loss_limit_reached",
    "system_started",
    "system_stopped",
    "error_occurred",
}

# Tipo de handler de evento
EventHandler = Callable[[Dict[str, Any]], None]


class EventBus:
    """
    Barramento de eventos simples e síncrono.

    Permite comunicação desacoplada entre módulos sem importações circulares.
    Futuramente pode ser evoluído para async com asyncio.Queue.

    Exemplo:
        bus = EventBus()

        def on_signal(data):
            print(f"Sinal recebido: {data}")

        bus.subscribe("signal_generated", on_signal)
        bus.publish("signal_generated", {"symbol": "BTCUSDT", "side": "buy"})
    """

    def __init__(self) -> None:
        """Inicializa o EventBus com dicionário vazio de subscribers."""
        self._subscribers: Dict[str, List[EventHandler]] = defaultdict(list)
        self._event_history: List[Dict[str, Any]] = []
        self._max_history: int = 1000

        _logger.info("EventBus inicializado")

    def subscribe(self, event_name: str, handler: EventHandler) -> None:
        """
        Registra um handler para um tipo de evento.

        Args:
            event_name: Nome do evento (use as constantes VALID_EVENTS).
            handler: Função chamada quando o evento é publicado.
                     Recebe um dict com os dados do evento.

        Raises:
            ValueError: Se o event_name não for válido.
        """
        if event_name not in VALID_EVENTS:
            raise ValueError(
                f"Evento inválido: '{event_name}'. "
                f"Eventos válidos: {sorted(VALID_EVENTS)}"
            )

        self._subscribers[event_name].append(handler)
        _logger.debug(
            f"EventBus.subscribe | event={event_name} | "
            f"handler={handler.__name__} | "
            f"total_subscribers={len(self._subscribers[event_name])}"
        )

    def unsubscribe(self, event_name: str, handler: EventHandler) -> None:
        """
        Remove um handler de um tipo de evento.

        Args:
            event_name: Nome do evento.
            handler: Handler a remover.
        """
        if event_name in self._subscribers:
            try:
                self._subscribers[event_name].remove(handler)
                _logger.debug(f"EventBus.unsubscribe | event={event_name} | handler={handler.__name__}")
            except ValueError:
                _logger.warning(f"Handler não encontrado para remoção: {event_name}/{handler.__name__}")

    def publish(self, event_name: str, data: Dict[str, Any] | None = None) -> int:
        """
        Publica um evento para todos os subscribers registrados.

        Args:
            event_name: Nome do evento a publicar.
            data: Dados do evento (dict). Pode ser None.

        Returns:
            Número de handlers notificados.

        Raises:
            ValueError: Se o event_name não for válido.
        """
        if event_name not in VALID_EVENTS:
            raise ValueError(
                f"Evento inválido: '{event_name}'. "
                f"Eventos válidos: {sorted(VALID_EVENTS)}"
            )

        payload = data or {}
        handlers = self._subscribers.get(event_name, [])

        # Armazenar no histórico (limitado)
        if len(self._event_history) >= self._max_history:
            self._event_history.pop(0)
        self._event_history.append({"event": event_name, "data": payload})

        _logger.debug(
            f"EventBus.publish | event={event_name} | "
            f"subscribers={len(handlers)} | data={payload}"
        )

        errors = []
        for handler in handlers:
            try:
                handler(payload)
            except Exception as e:
                _logger.error(
                    f"Erro no handler '{handler.__name__}' para evento '{event_name}': {e}"
                )
                errors.append(e)

        if errors:
            _logger.warning(
                f"EventBus: {len(errors)} handler(s) falharam para evento '{event_name}'"
            )

        return len(handlers)

    def get_subscriber_count(self, event_name: str) -> int:
        """Retorna o número de subscribers de um evento."""
        return len(self._subscribers.get(event_name, []))

    def get_event_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Retorna os últimos N eventos publicados.

        Args:
            limit: Quantidade máxima de eventos a retornar.

        Returns:
            Lista de eventos (mais recentes por último).
        """
        return self._event_history[-limit:]

    def clear_history(self) -> None:
        """Limpa o histórico de eventos."""
        self._event_history.clear()

    def __repr__(self) -> str:
        total_subs = sum(len(v) for v in self._subscribers.values())
        return f"EventBus(events={len(self._subscribers)}, total_subscribers={total_subs})"
