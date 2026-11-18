"""
BaseStrategy — Interface Base para Estratégias
================================================
Classe abstrata que define o contrato que toda estratégia deve seguir.

⚠️  REGRAS DE DESIGN:
    1. Toda estratégia DEVE herdar desta classe.
    2. O método generate_signal() é o único ponto de saída de sinais.
    3. Retorna Optional[TradingSignal] — None significa sem sinal.
    4. Stop loss é obrigatório em todo sinal retornado.
    5. A estratégia NÃO executa ordens — apenas gera sinais.
    6. A estratégia NÃO consulta IA/LLM para decisões de entrada/saída.
    7. Lógica deve ser determinística e testável com dados históricos.

Criando uma nova estratégia:
    class MinhaEstrategia(BaseStrategy):
        @property
        def name(self) -> str:
            return "minha_estrategia"

        def generate_signal(self, market_data: dict) -> Optional[TradingSignal]:
            # ... lógica determinística ...
            return TradingSignal(...)

        def reset(self) -> None:
            # ... resetar estado interno ...
            pass
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, Optional

from crypto_trading_bot.logging_system.logger import get_logger
from crypto_trading_bot.risk.risk_engine import OrderSide, TradingSignal

_logger = get_logger(__name__)


class StrategyState(str, Enum):
    """Estado da estratégia."""
    RUNNING = "running"         # Ativa e gerando sinais
    PAUSED = "paused"           # Pausada — não gera sinais
    ERROR = "error"             # Em estado de erro
    WARMING_UP = "warming_up"   # Aguardando dados suficientes para operar


class BaseStrategy(ABC):
    """
    Interface base para todas as estratégias de trading.

    Toda estratégia deve:
    - Implementar generate_signal()
    - Implementar a propriedade name
    - Implementar reset()
    - Garantir que sinais retornados sempre tenham stop_loss_price > 0
    - Nunca enviar ordens diretamente

    O método generate_signal() recebe um dicionário de dados de mercado
    e retorna um TradingSignal ou None.

    O formato esperado do market_data será definido na FASE 3 quando
    o módulo data/ for implementado.
    """

    def __init__(self) -> None:
        """Inicializa a estratégia em estado WARMING_UP."""
        self._state: StrategyState = StrategyState.WARMING_UP
        self._signal_count: int = 0
        self._error_count: int = 0
        self._last_signal: Optional[TradingSignal] = None

        _logger.info(f"Estratégia '{self.name}' inicializada | state={self._state.value}")

    # -----------------------------------------------------------------------
    # Métodos Abstratos — DEVEM ser implementados pela subclasse
    # -----------------------------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Nome único da estratégia (usado em logs e auditoria)."""
        ...

    @abstractmethod
    def generate_signal(
        self,
        market_data: Dict[str, Any],
    ) -> Optional[TradingSignal]:
        """
        Analisa os dados de mercado e gera um sinal de trading.

        Este é o método principal da estratégia. Deve conter toda a lógica
        de decisão de forma determinística e auditável.

        Args:
            market_data: Dicionário com dados de mercado. Estrutura mínima esperada:
                {
                    "symbol": str,            # Ex: "BTCUSDT"
                    "close": float,           # Preço de fechamento atual
                    "open": float,            # Preço de abertura
                    "high": float,            # Máxima do período
                    "low": float,             # Mínima do período
                    "volume": float,          # Volume
                    "timestamp": datetime,    # Timestamp da candle
                    "closes": list[float],    # Histórico de fechamentos
                    # ... outros indicadores conforme necessário
                }

        Returns:
            TradingSignal com stop_loss_price definido, ou None se não houver sinal.

        Notas:
            - SEMPRE defina stop_loss_price. Sinais sem stop loss são rejeitados.
            - NÃO acesse APIs externos aqui.
            - NÃO use IA/LLM para gerar sinais.
            - NÃO execute ordens aqui.
        """
        ...

    @abstractmethod
    def reset(self) -> None:
        """
        Reseta o estado interno da estratégia.

        Chamado ao iniciar uma nova sessão ou após um erro.
        Subclasses devem limpar quaisquer variáveis de estado internas.
        """
        ...

    # -----------------------------------------------------------------------
    # Métodos Concretos (podem ser sobrescritos se necessário)
    # -----------------------------------------------------------------------

    def on_signal_approved(self, signal: TradingSignal) -> None:
        """
        Callback chamado quando um sinal gerado é aprovado pelo RiskEngine.

        Usa para atualizar estado interno (ex: marcar posição como aberta).
        NÃO execute ordens aqui — apenas atualize estado.

        Args:
            signal: O sinal que foi aprovado.
        """
        _logger.debug(f"[{self.name}] Sinal aprovado: {signal.side.value} {signal.symbol}")

    def on_signal_rejected(self, signal: TradingSignal, reason: str) -> None:
        """
        Callback chamado quando um sinal gerado é rejeitado pelo RiskEngine.

        Args:
            signal: O sinal que foi rejeitado.
            reason: Motivo da rejeição.
        """
        _logger.info(f"[{self.name}] Sinal rejeitado: {reason}")

    def on_trade_closed(self, symbol: str, pnl: float) -> None:
        """
        Callback chamado quando uma posição originada por esta estratégia é fechada.

        Args:
            symbol: Símbolo do ativo.
            pnl: PnL realizado.
        """
        _logger.info(f"[{self.name}] Trade fechado: {symbol} PnL={pnl:+.2f}")

    def pause(self) -> None:
        """Pausa a estratégia. Enquanto pausada, generate_signal() sempre retorna None."""
        self._state = StrategyState.PAUSED
        _logger.info(f"Estratégia '{self.name}' pausada")

    def resume(self) -> None:
        """Retoma a estratégia pausada."""
        if self._state == StrategyState.PAUSED:
            self._state = StrategyState.RUNNING
            _logger.info(f"Estratégia '{self.name}' retomada")

    def set_running(self) -> None:
        """Marca a estratégia como pronta para operar."""
        self._state = StrategyState.RUNNING
        _logger.info(f"Estratégia '{self.name}' em execução")

    def evaluate(self, features: Dict[str, Any]) -> "StrategySignal":
        """
        Avalia os dados e retorna um StrategySignal com ação padronizada.

        Este é o método chamado pelo BotEngine a cada ciclo.
        Sempre retorna um StrategySignal — nunca None.
        Quando não há condições, retorna HOLD explicitamente.

        Implementação padrão:
            1. Se não estiver RUNNING → HOLD
            2. Chama generate_signal(features) para manter compatibilidade
            3. None → HOLD; TradingSignal → StrategySignal(BUY/SELL)
            4. Exceções são capturadas → HOLD + estado=ERROR

        Subclasses podem sobrescrever este método para lógica própria
        (ex: EmaRsiStrategy consome FeatureEngine dict diretamente).

        Args:
            features: Dicionário de dados/features de mercado.

        Returns:
            StrategySignal com action=BUY, SELL ou HOLD.
        """
        from crypto_trading_bot.strategies.signal_model import StrategyAction, StrategySignal

        symbol: str = str(features.get("symbol") or "")

        # --- Estado da estratégia ---
        if self._state != StrategyState.RUNNING:
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=self.name,
                reason=f"Estratégia inativa: {self._state.value}",
            )

        # --- Chama generate_signal() (interface de compatibilidade) ---
        try:
            trading_signal = self.generate_signal(features)
        except Exception as e:
            self._error_count += 1
            self._state = StrategyState.ERROR
            _logger.error(
                f"[{self.name}] Erro ao gerar sinal (#{self._error_count}): {e}"
            )
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=self.name,
                reason=f"Erro na estratégia: {e}",
            )

        # --- Sem sinal → HOLD ---
        if trading_signal is None:
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=self.name,
            )

        # --- Converte TradingSignal → StrategySignal ---
        action = (
            StrategyAction.BUY
            if trading_signal.side == OrderSide.BUY
            else StrategyAction.SELL
        )
        strategy_signal = StrategySignal(
            action=action,
            symbol=trading_signal.symbol,
            strategy_name=trading_signal.strategy_name,
            entry_price=trading_signal.entry_price,
            stop_loss_price=trading_signal.stop_loss_price,
            take_profit_price=trading_signal.take_profit_price,
            position_size_usd=trading_signal.position_size_usd,
            leverage=trading_signal.leverage,
            timestamp=trading_signal.timestamp,
            metadata=trading_signal.metadata,
        )

        self._signal_count += 1
        self._last_signal = strategy_signal

        _logger.info(
            f"[{self.name}] Sinal #{self._signal_count} | "
            f"action={action.value.upper()} | "
            f"symbol={strategy_signal.symbol} | "
            f"entry={strategy_signal.entry_price} | "
            f"stop={strategy_signal.stop_loss_price} | "
            f"sl_pct={strategy_signal.stop_loss_pct:.2%}"
        )

        return strategy_signal

    def _safe_generate_signal(
        self,
        market_data: Dict[str, Any],
    ) -> Optional[TradingSignal]:
        """
        Wrapper seguro em torno de generate_signal().

        ⚠️  Mantido para compatibilidade com testes existentes.
        Para novos fluxos, prefira evaluate() que retorna StrategySignal padronizado.

        Verifica o estado da estratégia antes de chamar generate_signal().
        Captura e registra exceções sem propagar para o BotEngine.

        Args:
            market_data: Dados de mercado.

        Returns:
            TradingSignal ou None.
        """
        if self._state != StrategyState.RUNNING:
            _logger.debug(
                f"[{self.name}] Sinal não gerado — state={self._state.value}"
            )
            return None

        try:
            signal = self.generate_signal(market_data)

            if signal is not None:
                self._signal_count += 1
                self._last_signal = signal
                _logger.info(
                    f"[{self.name}] Sinal gerado via _safe_generate_signal | "
                    f"symbol={signal.symbol} | "
                    f"side={signal.side.value} | "
                    f"entry={signal.entry_price} | "
                    f"stop={signal.stop_loss_price}"
                )

            return signal

        except Exception as e:
            self._error_count += 1
            self._state = StrategyState.ERROR
            _logger.error(
                f"[{self.name}] Erro ao gerar sinal (#{self._error_count}): {e}"
            )
            return None

    # -----------------------------------------------------------------------
    # Propriedades de Estado
    # -----------------------------------------------------------------------

    @property
    def state(self) -> StrategyState:
        """Estado atual da estratégia."""
        return self._state

    @property
    def is_running(self) -> bool:
        """Verdadeiro se a estratégia está em execução."""
        return self._state == StrategyState.RUNNING

    @property
    def signal_count(self) -> int:
        """Total de sinais gerados desde a última inicialização."""
        return self._signal_count

    @property
    def last_signal(self) -> Optional[TradingSignal]:
        """Último sinal gerado. None se nenhum sinal gerado ainda."""
        return self._last_signal

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, state={self._state.value})"
