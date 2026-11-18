"""
EmaRsiStrategy — Estratégia Placeholder para Validação do Fluxo Completo
=========================================================================
⚠️  AVISO OBRIGATÓRIO:
    Este arquivo é um PLACEHOLDER DE INTEGRAÇÃO.
    NÃO FOI VALIDADO POR BACKTESTING.
    NÃO REPRESENTA UMA ESTRATÉGIA PROFISSIONAL.
    NÃO DEVE SER USADA PARA TRADING REAL.
    Propósito único: validar a integração entre FeatureEngine,
    BotEngine, RiskEngine e PaperTrader.

Lógica simplificada (apenas para teste de fluxo):
    COMPRA quando:
      - EMA(ema_short_period) > EMA(ema_long_period)  [tendência de alta]
      - RSI(rsi_period) < rsi_overbought               [não sobrecomprado]
      - has_sufficient_data == True                    [dados válidos]
      - Sem posição aberta no momento

    Stop loss:
      - entry_price - (stop_atr_multiplier × ATR)
      - Fallback: entry_price × (1 - stop_fallback_pct) se ATR indisponível

Todos os parâmetros são explícitos e configuráveis.
Nenhum parâmetro escondido ou hardcoded.

HOLD é retornado explicitamente quando as condições não são atendidas.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from crypto_trading_bot.logging_system.logger import get_logger
from crypto_trading_bot.risk.risk_engine import OrderSide, TradingSignal
from crypto_trading_bot.strategies.base_strategy import BaseStrategy, StrategyState
from crypto_trading_bot.strategies.signal_model import StrategyAction, StrategySignal

_logger = get_logger(__name__)

# Parâmetros padrão — todos documentados, sem magia
_DEFAULT_EMA_SHORT = 9
_DEFAULT_EMA_LONG = 21
_DEFAULT_RSI_PERIOD = 14
_DEFAULT_RSI_OVERBOUGHT = 65.0       # acima disso = sobrecomprado = não entra
_DEFAULT_STOP_ATR_MULTIPLIER = 2.0   # stop = entry - 2×ATR
_DEFAULT_STOP_FALLBACK_PCT = 0.015   # 1.5% — usado se ATR for NaN
_DEFAULT_POSITION_SIZE_USD = 200.0   # tamanho da posição em USD
_MIN_CANDLES = 50                    # mínimo de candles para operar com segurança


class EmaRsiStrategy(BaseStrategy):
    """
    Estratégia placeholder baseada em EMA cruzada + RSI.

    ⚠️  PLACEHOLDER DE INTEGRAÇÃO — NÃO PARA TRADING REAL.

    Consume diretamente o dicionário de features do FeatureEngine.
    Usa o método evaluate() como ponto de entrada principal (via BotEngine).

    Parâmetros (todos explícitos):
        ema_short_period:    EMA rápida (default: 9)
        ema_long_period:     EMA lenta (default: 21)
        rsi_period:          Período do RSI (default: 14)
        rsi_overbought:      RSI acima disso = zona de sobrecompra (default: 65.0)
        stop_atr_multiplier: Multiplicador do ATR para calcular stop (default: 2.0)
        stop_fallback_pct:   % de stop quando ATR não disponível (default: 0.015)
        position_size_usd:   Tamanho da posição em USD (default: 200.0)

    Lógica de entrada:
        BUY quando EMA9 > EMA21 E RSI < 65 E sem posição aberta E dados suficientes.

    Lógica de saída:
        Gerenciada externamente (PaperTrader/BotEngine).
        O stop loss é definido na criação do sinal.
    """

    def __init__(
        self,
        ema_short_period: int = _DEFAULT_EMA_SHORT,
        ema_long_period: int = _DEFAULT_EMA_LONG,
        rsi_period: int = _DEFAULT_RSI_PERIOD,
        rsi_overbought: float = _DEFAULT_RSI_OVERBOUGHT,
        stop_atr_multiplier: float = _DEFAULT_STOP_ATR_MULTIPLIER,
        stop_fallback_pct: float = _DEFAULT_STOP_FALLBACK_PCT,
        position_size_usd: float = _DEFAULT_POSITION_SIZE_USD,
    ) -> None:
        if ema_short_period >= ema_long_period:
            raise ValueError(
                f"ema_short_period ({ema_short_period}) deve ser menor que "
                f"ema_long_period ({ema_long_period})"
            )
        if not (0 < rsi_overbought <= 100):
            raise ValueError(f"rsi_overbought deve estar em (0, 100]: {rsi_overbought}")
        if stop_fallback_pct <= 0:
            raise ValueError(f"stop_fallback_pct deve ser positivo: {stop_fallback_pct}")
        if position_size_usd <= 0:
            raise ValueError(f"position_size_usd deve ser positivo: {position_size_usd}")

        self._ema_short_period = ema_short_period
        self._ema_long_period = ema_long_period
        self._rsi_period = rsi_period
        self._rsi_overbought = rsi_overbought
        self._stop_atr_multiplier = stop_atr_multiplier
        self._stop_fallback_pct = stop_fallback_pct
        self._position_size_usd = position_size_usd
        self._has_open_position: bool = False

        super().__init__()

        _logger.info(
            f"[{self.name}] Parâmetros | "
            f"ema={ema_short_period}/{ema_long_period} | "
            f"rsi_period={rsi_period} | "
            f"rsi_overbought={rsi_overbought} | "
            f"stop_mult={stop_atr_multiplier}×ATR | "
            f"stop_fallback={stop_fallback_pct:.1%} | "
            f"size_usd={position_size_usd}"
        )

    # -----------------------------------------------------------------------
    # Interface obrigatória da BaseStrategy
    # -----------------------------------------------------------------------

    @property
    def name(self) -> str:
        return (
            f"ema_rsi_placeholder"
            f"_e{self._ema_short_period}/{self._ema_long_period}"
            f"_r{self._rsi_period}"
        )

    def generate_signal(
        self,
        market_data: Dict[str, Any],
    ) -> Optional[TradingSignal]:
        """
        Implementação de compatibilidade com a interface BaseStrategy.

        ⚠️  Para EmaRsiStrategy, use evaluate(features) diretamente.
        Este método é fornecido apenas para satisfazer o contrato da classe base.
        O BotEngine sempre chama evaluate(), nunca generate_signal() diretamente.
        """
        # Delega para evaluate() e converte o resultado
        signal = self.evaluate(market_data)
        if signal.is_actionable:
            return signal.to_trading_signal()
        return None

    def reset(self) -> None:
        """Reseta o estado interno da estratégia."""
        self._has_open_position = False
        self._state = StrategyState.WARMING_UP
        _logger.info(f"[{self.name}] Estado resetado")

    # -----------------------------------------------------------------------
    # Método principal — evaluate() com FeatureEngine output
    # -----------------------------------------------------------------------

    def evaluate(self, features: Dict[str, Any]) -> StrategySignal:
        """
        Avalia os dados do FeatureEngine e retorna StrategySignal padronizado.

        Este é o método usado pelo BotEngine. Sempre retorna um StrategySignal
        (nunca None) — HOLD quando não há condições de entrada, BUY/SELL quando há.

        Args:
            features: Dicionário retornado por FeatureEngine.compute(candles).
                Campos utilizados:
                    - has_sufficient_data: bool
                    - symbol: str (ou None se vazio)
                    - last_close: float
                    - last_ema_9: float (ou chave dinâmica por período)
                    - ema_21: pd.Series (usa último valor)
                    - last_rsi: float
                    - last_atr: float

        Returns:
            StrategySignal com action=BUY (se condições atendidas) ou action=HOLD.
        """
        symbol = features.get("symbol") or "UNKNOWN"

        # --- Verificação de estado ---
        if self._state != StrategyState.RUNNING:
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=self.name,
                reason=f"Estratégia inativa: {self._state.value}",
            )

        # --- Verificação de dados suficientes ---
        if not features.get("has_sufficient_data", False):
            n = features.get("n_candles", 0)
            _logger.debug(
                f"[{self.name}] HOLD — dados insuficientes: "
                f"{n} candles (mínimo: {_MIN_CANDLES})"
            )
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=self.name,
                reason=f"Dados insuficientes: {n}/{_MIN_CANDLES} candles",
            )

        # --- Extração de features ---
        last_close = features.get("last_close", 0.0)
        last_rsi = features.get("last_rsi", float("nan"))
        last_atr = features.get("last_atr", float("nan"))

        # EMA curta: usa last_ema_{period} se disponível, senão pega da série
        ema_short_key = f"last_ema_{self._ema_short_period}"
        ema_short = features.get(ema_short_key, float("nan"))
        if math.isnan(ema_short):
            ema_short = self._get_last_from_series(features, f"ema_{self._ema_short_period}")

        # EMA longa: pega da série (pode não ter last_*)
        ema_long_key = f"last_ema_{self._ema_long_period}"
        ema_long = features.get(ema_long_key, float("nan"))
        if math.isnan(ema_long):
            ema_long = self._get_last_from_series(features, f"ema_{self._ema_long_period}")

        # --- Validação de valores obrigatórios ---
        if last_close <= 0:
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=self.name,
                reason=f"Preço inválido: last_close={last_close}",
            )
        if math.isnan(ema_short) or math.isnan(ema_long):
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=self.name,
        reason=(
            f"EMA indisponível: "
            f"ema{self._ema_short_period}={'NaN' if math.isnan(ema_short) else f'{ema_short:.2f}'}, "
            f"ema{self._ema_long_period}={'NaN' if math.isnan(ema_long) else f'{ema_long:.2f}'}"
        ),
            )

        # --- Regras de entrada (determinísticas, sem IA) ---
        ema_crossover = ema_short > ema_long          # EMA rápida acima da lenta
        rsi_valid = math.isnan(last_rsi) or (last_rsi < self._rsi_overbought)  # não sobrecomprado
        no_position = not self._has_open_position

        _logger.debug(
            f"[{self.name}] Avaliação | "
            f"close={last_close:.2f} | "
            f"ema{self._ema_short_period}={ema_short:.2f} | "
            f"ema{self._ema_long_period}={ema_long:.2f} | "
            f"ema_cross={ema_crossover} | "
            f"rsi={'NaN' if math.isnan(last_rsi) else f'{last_rsi:.1f}'} | "
            f"rsi_valid={rsi_valid} | "
            f"open_pos={self._has_open_position}"
        )

        # --- HOLD se condições não atendidas ---
        if not (ema_crossover and rsi_valid and no_position):
            reasons = []
            if not ema_crossover:
                reasons.append(
                    f"EMA{self._ema_short_period}({ema_short:.2f}) "
                    f"≤ EMA{self._ema_long_period}({ema_long:.2f})"
                )
            if not rsi_valid:
                reasons.append(f"RSI={last_rsi:.1f} ≥ {self._rsi_overbought}")
            if not no_position:
                reasons.append("posição já aberta")
            return StrategySignal.hold(
                symbol=symbol,
                strategy_name=self.name,
                reason="; ".join(reasons),
            )

        # --- Calcular stop loss ---
        stop_loss_price = self._calculate_stop_loss(last_close, last_atr)

        # --- Calcular take profit (2:1 R:R como placeholder) ---
        risk = last_close - stop_loss_price
        take_profit_price = round(last_close + (2.0 * risk), 2)

        _logger.info(
            f"[{self.name}] SINAL BUY | "
            f"symbol={symbol} | "
            f"entry={last_close:.2f} | "
            f"stop={stop_loss_price:.2f} | "
            f"tp={take_profit_price:.2f} | "
            f"ema{self._ema_short_period}={ema_short:.2f} | "
            f"ema{self._ema_long_period}={ema_long:.2f} | "
            f"rsi={'NaN' if math.isnan(last_rsi) else f'{last_rsi:.1f}'} | "
            f"atr={'NaN' if math.isnan(last_atr) else f'{last_atr:.2f}'}"
        )

        signal = StrategySignal.buy(
            symbol=symbol,
            strategy_name=self.name,
            entry_price=last_close,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            position_size_usd=self._position_size_usd,
            leverage=1.0,
            metadata={
                f"ema_{self._ema_short_period}": round(ema_short, 2),
                f"ema_{self._ema_long_period}": round(ema_long, 2),
                "rsi": round(last_rsi, 2) if not math.isnan(last_rsi) else None,
                "atr": round(last_atr, 4) if not math.isnan(last_atr) else None,
                "note": "⚠️ PLACEHOLDER — NÃO PARA TRADING REAL",
            },
        )

        self._signal_count += 1
        self._last_signal = signal
        return signal

    # -----------------------------------------------------------------------
    # Callbacks de ciclo de vida
    # -----------------------------------------------------------------------

    def on_signal_approved(self, signal: TradingSignal) -> None:
        """Marca posição como aberta quando sinal é aprovado pelo RiskEngine."""
        super().on_signal_approved(signal)
        self._has_open_position = True

    def on_trade_closed(self, symbol: str, pnl: float) -> None:
        """Marca posição como fechada."""
        super().on_trade_closed(symbol, pnl)
        self._has_open_position = False

    # -----------------------------------------------------------------------
    # Métodos privados
    # -----------------------------------------------------------------------

    def _calculate_stop_loss(self, entry_price: float, atr: float) -> float:
        """
        Calcula o preço de stop loss.

        Usa ATR quando disponível (stop = entry - multiplier × ATR).
        Fallback para percentual fixo quando ATR for NaN.

        Args:
            entry_price: Preço de entrada.
            atr: ATR atual. float('nan') se indisponível.

        Returns:
            Preço de stop loss (sempre abaixo do entry_price).
        """
        if not math.isnan(atr) and atr > 0:
            stop = entry_price - (self._stop_atr_multiplier * atr)
            _logger.debug(
                f"[{self.name}] Stop por ATR: "
                f"{entry_price:.2f} - {self._stop_atr_multiplier}×{atr:.4f} = {stop:.2f}"
            )
        else:
            stop = entry_price * (1.0 - self._stop_fallback_pct)
            _logger.debug(
                f"[{self.name}] Stop fallback ({self._stop_fallback_pct:.1%}): "
                f"{entry_price:.2f} × {1 - self._stop_fallback_pct:.4f} = {stop:.2f}"
            )

        return round(stop, 2)

    @staticmethod
    def _get_last_from_series(features: Dict[str, Any], key: str) -> float:
        """
        Extrai o último valor de uma pd.Series no dicionário de features.

        Args:
            features: Dicionário de features.
            key: Chave da série (ex: "ema_21").

        Returns:
            Último valor válido ou float('nan') se série ausente/vazia/NaN.
        """
        import math as _math
        series = features.get(key)
        if series is None:
            return float("nan")
        try:
            val = float(series.iloc[-1])
            return val if not _math.isnan(val) else float("nan")
        except (IndexError, TypeError, AttributeError):
            return float("nan")

    def __repr__(self) -> str:
        return (
            f"EmaRsiStrategy("
            f"ema={self._ema_short_period}/{self._ema_long_period} | "
            f"rsi<{self._rsi_overbought} | "
            f"stop={self._stop_atr_multiplier}×ATR | "
            f"size={self._position_size_usd}USD | "
            f"state={self._state.value})"
        )
