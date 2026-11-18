"""
FeedBackedMockExchange - MockExchange alimentado por PaperFeedAdapter
======================================================================
FASE 25 Bloco 2. Subclasse de MockExchange que substitui o random walk
por uma lista determinISTIca de Candle vinda do PaperFeedAdapter.

Mantem balance/positions/orders/place_market_order do MockExchange
INTOCADOS. Apenas sobrescreve:
    - get_candles(): retorna janela do feed ate cursor atual.
    - _get_simulated_price(): retorna close do candle no cursor.
    - get_ticker(): usa o close do candle atual.

API extra:
    - advance_cursor(): avanca o cursor em 1 candle (chamado pelo
      SessionRunner apos cada bot_engine.run_once).
    - current_candle: candle atual sob o cursor.

SEGURANCA:
    - NAO importa BybitClient/httpx/requests.
    - NAO chama rede.
    - NAO altera assert_safe_mode / ModeGuard / RiskEngine.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Tuple

from crypto_trading_bot.exchange.base_exchange import Candle, Ticker
from crypto_trading_bot.exchange.mock_exchange import MockExchange
from crypto_trading_bot.logging_system.logger import get_logger
from crypto_trading_bot.paper_feed.adapter import PaperFeedAdapter

_logger = get_logger(__name__)


# Warm-up minimo de candles para FeatureEngine produzir indicadores nao-NaN.
# Aligned with _MIN_CANDLES_RECOMMENDED (50) + buffer para ema_50.
_DEFAULT_WARMUP_CANDLES = 60


class FeedBackedMockExchange(MockExchange):
    """MockExchange cujo feed vem de um PaperFeedAdapter determinISTIco.

    Construido pelo SessionRunner quando feed_adapter eh fornecido.
    Mantem comportamento idêntico de execucao de ordens; apenas a
    serie de candles/precos eh substituida.
    """

    def __init__(
        self,
        feed_adapter: PaperFeedAdapter,
        *,
        initial_balance_usdt: float = 5000.0,
        simulated_fee_pct: float = 0.001,
        warmup_candles: int = _DEFAULT_WARMUP_CANDLES,
    ) -> None:
        if not isinstance(feed_adapter, PaperFeedAdapter):
            raise TypeError(
                "feed_adapter deve ser PaperFeedAdapter; "
                f"recebido {type(feed_adapter).__name__}"
            )
        if feed_adapter.n_candles < warmup_candles + 1:
            raise ValueError(
                f"feed_adapter tem {feed_adapter.n_candles} candles; "
                f"minimo eh warmup_candles+1 = {warmup_candles + 1}. "
                "Aumente n na fixture ou reduza warmup_candles."
            )
        self._feed_candles: Tuple[Candle, ...] = feed_adapter.candles
        self._feed_adapter = feed_adapter
        # Cursor aponta para a posicao atual (ultimo candle visivel).
        # Comeca em warmup_candles - 1 para garantir que get_candles entregue
        # janela suficiente para indicadores no PRIMEIRO ciclo.
        self._feed_cursor = warmup_candles - 1

        # Super init: comportamento do MockExchange preservado (balance,
        # positions, fee). initial_price = close do candle no cursor inicial.
        initial_price = float(self._feed_candles[self._feed_cursor].close)
        super().__init__(
            initial_price=initial_price,
            initial_balance_usdt=initial_balance_usdt,
            price_volatility=0.0,  # nao usado
            simulated_fee_pct=simulated_fee_pct,
        )
        # Sobrescreve _price_history para refletir os closes do feed
        # ate o cursor atual. Mantem coerencia com qualquer codigo que
        # ainda leia self._price_history.
        self._price_history = [
            float(c.close) for c in self._feed_candles[: self._feed_cursor + 1]
        ]
        _logger.info(
            "FeedBackedMockExchange inicializada | "
            f"feed={feed_adapter.feed_type.value} | "
            f"n_total={feed_adapter.n_candles} | "
            f"cursor_inicial={self._feed_cursor} | "
            f"warmup_candles={warmup_candles} | "
            f"price={initial_price:.2f}"
        )

    @property
    def feed_adapter(self) -> PaperFeedAdapter:
        return self._feed_adapter

    @property
    def feed_cursor(self) -> int:
        return self._feed_cursor

    @property
    def current_candle(self) -> Candle:
        """Candle sob o cursor atual."""
        return self._feed_candles[self._feed_cursor]

    @property
    def has_more_candles(self) -> bool:
        """True se o cursor ainda pode avancar."""
        return self._feed_cursor < len(self._feed_candles) - 1

    def advance_cursor(self) -> bool:
        """Avanca o cursor em 1 candle.

        Returns:
            True se avancou; False se ja estava no fim do feed.
        """
        if self._feed_cursor >= len(self._feed_candles) - 1:
            return False
        self._feed_cursor += 1
        new_close = float(self._feed_candles[self._feed_cursor].close)
        self._current_price = new_close
        self._price_history.append(new_close)
        return True

    # -----------------------------------------------------------------------
    # Override get_candles: retorna janela do feed ate o cursor atual
    # -----------------------------------------------------------------------

    def get_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
    ) -> List[Candle]:
        """Retorna ate `limit` candles ate o cursor atual (inclusivo).

        Diferente do MockExchange: NAO gera candles aleatorios. Devolve
        exatamente os candles do feed (preservando OHLCV/timestamp).
        """
        end = self._feed_cursor + 1
        start = max(0, end - limit)
        return list(self._feed_candles[start:end])

    # -----------------------------------------------------------------------
    # Override _get_simulated_price: usa close do candle atual
    # -----------------------------------------------------------------------

    def _get_simulated_price(self) -> float:
        """Preco atual = close do candle no cursor."""
        return float(self._feed_candles[self._feed_cursor].close)

    # -----------------------------------------------------------------------
    # Override get_ticker para refletir candle atual (timestamp coerente)
    # -----------------------------------------------------------------------

    def get_ticker(self, symbol: str) -> Ticker:
        candle = self._feed_candles[self._feed_cursor]
        price = float(candle.close)
        spread = price * 0.0001
        ts = candle.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return Ticker(
            symbol=symbol,
            last_price=price,
            bid=round(price - spread / 2, 2),
            ask=round(price + spread / 2, 2),
            volume_24h=float(candle.volume),
            timestamp=ts,
        )
