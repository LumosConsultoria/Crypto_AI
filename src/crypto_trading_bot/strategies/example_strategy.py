"""
ExampleStrategy — Estratégia Exemplo para Validação Estrutural
================================================================
⚠️  AVISO IMPORTANTE:
    Esta estratégia É APENAS um exemplo para validar o fluxo do sistema.
    NÃO deve ser usada para trading real.
    NÃO representa uma estratégia rentável ou validada.
    A lógica aqui é intencialmente simplista para fins de teste.

Lógica simplificada (apenas para teste de fluxo):
    - Gera sinal de compra quando o preço atual está acima da média móvel simples
      de 20 períodos (SMA20), com volume acima da média.
    - Stop loss colocado 2% abaixo do preço de entrada.
    - Take profit colocado 4% acima do preço de entrada (R:R de 2:1).
    - Não abre nova posição se já tiver uma posição aberta.

Esta estratégia serve para:
    1. Validar que o fluxo estratégia → risco → executor funciona.
    2. Servir como template para novas estratégias.
    3. Gerar sinais em testes unitários.

TODO (FASE 3): Substituir pela primeira estratégia real após backtesting.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from crypto_trading_bot.logging_system.logger import get_logger
from crypto_trading_bot.risk.risk_engine import OrderSide, TradingSignal
from crypto_trading_bot.strategies.base_strategy import BaseStrategy, StrategyState

_logger = get_logger(__name__)

# Parâmetros da estratégia exemplo
_DEFAULT_SMA_PERIOD = 20
_DEFAULT_STOP_LOSS_PCT = 0.02      # 2% abaixo da entrada
_DEFAULT_TAKE_PROFIT_PCT = 0.04    # 4% acima da entrada (R:R 2:1)
_DEFAULT_POSITION_SIZE_USD = 200.0  # USD por trade (conservador para testes)
_MIN_CANDLES_REQUIRED = _DEFAULT_SMA_PERIOD + 1


class ExampleStrategy(BaseStrategy):
    """
    Estratégia exemplo baseada em cruzamento de preço sobre SMA20 + volume.

    ⚠️  NÃO USE PARA TRADING REAL — apenas para validar o fluxo do sistema.

    Regras de entrada (determinísticas, sem IA):
        COMPRA quando:
            - Preço atual > SMA(20)
            - Volume atual > volume médio dos últimos 20 períodos
            - Não há posição aberta

        VENDA/SHORT: não implementado nesta versão exemplo.

    Saída:
        - Stop loss: 2% abaixo do preço de entrada
        - Take profit: 4% acima do preço de entrada

    Parâmetros:
        sma_period: Período da média móvel simples (default: 20)
        stop_loss_pct: Percentual de stop loss (default: 0.02 = 2%)
        take_profit_pct: Percentual de take profit (default: 0.04 = 4%)
        position_size_usd: Tamanho da posição em USD (default: 200.0)
    """

    def __init__(
        self,
        sma_period: int = _DEFAULT_SMA_PERIOD,
        stop_loss_pct: float = _DEFAULT_STOP_LOSS_PCT,
        take_profit_pct: float = _DEFAULT_TAKE_PROFIT_PCT,
        position_size_usd: float = _DEFAULT_POSITION_SIZE_USD,
    ) -> None:
        self._sma_period = sma_period
        self._stop_loss_pct = stop_loss_pct
        self._take_profit_pct = take_profit_pct
        self._position_size_usd = position_size_usd
        self._has_open_position: bool = False

        # Chama __init__ da classe base (registra nome e estado)
        super().__init__()

        _logger.info(
            f"[{self.name}] Parâmetros | "
            f"sma_period={sma_period} | "
            f"sl={stop_loss_pct:.1%} | "
            f"tp={take_profit_pct:.1%} | "
            f"size_usd={position_size_usd}"
        )

    # -----------------------------------------------------------------------
    # Interface obrigatória da BaseStrategy
    # -----------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "example_sma20_strategy"

    def generate_signal(
        self,
        market_data: Dict[str, Any],
    ) -> Optional[TradingSignal]:
        """
        Gera sinal baseado em SMA20 + volume.

        Args:
            market_data: Dicionário com dados de mercado.
                Campos obrigatórios:
                    - symbol: str
                    - close: float (preço atual)
                    - closes: list[float] (histórico de N fechamentos)
                    - volume: float (volume atual)
                    - volumes: list[float] (histórico de volumes)

        Returns:
            TradingSignal se condições de entrada forem atendidas, None caso contrário.
        """
        # --- Validação dos dados de entrada ---
        symbol = market_data.get("symbol", "")
        close = market_data.get("close", 0.0)
        closes: List[float] = market_data.get("closes", [])
        volume = market_data.get("volume", 0.0)
        volumes: List[float] = market_data.get("volumes", [])

        if not symbol or close <= 0:
            _logger.debug(f"[{self.name}] Dados inválidos: symbol={symbol}, close={close}")
            return None

        # --- Verificação de dados suficientes ---
        if len(closes) < _MIN_CANDLES_REQUIRED:
            _logger.debug(
                f"[{self.name}] Aguardando dados: {len(closes)}/{_MIN_CANDLES_REQUIRED} candles"
            )
            return None

        # --- Cálculo da SMA20 ---
        sma = self._calculate_sma(closes, self._sma_period)
        if sma is None:
            return None

        # --- Cálculo do volume médio ---
        avg_volume = self._calculate_avg_volume(volumes, self._sma_period)

        # --- Regra de entrada (determinística) ---
        price_above_sma = close > sma
        volume_above_avg = (avg_volume is None) or (volume > avg_volume)
        no_open_position = not self._has_open_position

        _logger.debug(
            f"[{self.name}] Avaliação | "
            f"close={close:.2f} | "
            f"sma{self._sma_period}={sma:.2f} | "
            f"above_sma={price_above_sma} | "
            f"vol_above_avg={volume_above_avg} | "
            f"open_pos={self._has_open_position}"
        )

        # Sem sinal se condições não atendidas
        if not (price_above_sma and volume_above_avg and no_open_position):
            return None

        # --- Construção do Sinal ---
        entry_price = close
        stop_loss_price = round(entry_price * (1 - self._stop_loss_pct), 2)
        take_profit_price = round(entry_price * (1 + self._take_profit_pct), 2)

        signal = TradingSignal(
            symbol=symbol,
            side=OrderSide.BUY,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            position_size_usd=self._position_size_usd,
            leverage=1.0,
            strategy_name=self.name,
            metadata={
                "sma": round(sma, 2),
                "volume": volume,
                "avg_volume": round(avg_volume, 2) if avg_volume else None,
                "sma_period": self._sma_period,
                "note": "EXEMPLO — não usar para trading real",
            },
        )

        return signal

    def reset(self) -> None:
        """Reseta o estado interno da estratégia."""
        self._has_open_position = False
        self._state = StrategyState.WARMING_UP
        _logger.info(f"[{self.name}] Estado resetado")

    # -----------------------------------------------------------------------
    # Callbacks de ciclo de vida
    # -----------------------------------------------------------------------

    def on_signal_approved(self, signal: TradingSignal) -> None:
        """Marca posição como aberta quando sinal é aprovado."""
        super().on_signal_approved(signal)
        self._has_open_position = True

    def on_trade_closed(self, symbol: str, pnl: float) -> None:
        """Marca posição como fechada."""
        super().on_trade_closed(symbol, pnl)
        self._has_open_position = False

    # -----------------------------------------------------------------------
    # Métodos auxiliares privados
    # -----------------------------------------------------------------------

    @staticmethod
    def _calculate_sma(closes: List[float], period: int) -> Optional[float]:
        """
        Calcula a média móvel simples dos últimos N fechamentos.

        Args:
            closes: Lista de preços de fechamento.
            period: Número de períodos.

        Returns:
            Valor da SMA ou None se dados insuficientes.
        """
        if len(closes) < period:
            return None
        window = closes[-period:]
        return sum(window) / len(window)

    @staticmethod
    def _calculate_avg_volume(volumes: List[float], period: int) -> Optional[float]:
        """
        Calcula o volume médio dos últimos N períodos.

        Args:
            volumes: Lista de volumes.
            period: Número de períodos.

        Returns:
            Volume médio ou None se dados insuficientes.
        """
        if not volumes or len(volumes) < period:
            return None
        window = volumes[-period:]
        return sum(window) / len(window)
