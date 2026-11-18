"""
Indicadores de Tendência
=========================
SMA (Simple Moving Average), EMA (Exponential Moving Average), VWAP.

⚠️  REGRAS DE DESIGN:
    1. Funções puras: recebem dados, retornam valores.
    2. SEM efeitos colaterais.
    3. SEM acesso a APIs ou exchanges.
    4. SEM geração de sinais de compra/venda.
    5. SEM lógica de estratégia.
    6. Dados insuficientes retornam NaN (não lançam exceção).
    7. Preservam a ordem temporal dos dados.

Tipos:
    - Entrada: pd.Series (índice numérico ou datetime)
    - Saída: pd.Series (mesmo índice da entrada) ou float para valor único
    - NaN indica que o indicador ainda não tem dados suficientes

Sobre NaN vs exceção:
    Retornar NaN para dados insuficientes é preferível a lançar exceção
    porque permite que a FeatureEngine trate todos os casos de forma uniforme.
    A estratégia deve verificar se o valor é NaN antes de usá-lo.
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from typing import Optional


def sma(closes: pd.Series, period: int) -> pd.Series:
    """
    Simple Moving Average (Média Móvel Simples).

    Calcula a média aritmética dos últimos `period` fechamentos.
    Útil para identificar tendência de médio/longo prazo.

    Fórmula: SMA[t] = sum(close[t-period+1 : t+1]) / period

    Args:
        closes: Série de preços de fechamento (ordem cronológica).
        period: Número de períodos para a média.

    Returns:
        Série com os valores de SMA. NaN para os primeiros (period-1) candles.

    Exemplo:
        closes = pd.Series([100, 102, 104, 103, 105])
        result = sma(closes, 3)
        # result[-1] = (103 + 104 + 105) / 3 = 104.0
    """
    if period <= 0:
        raise ValueError(f"period deve ser positivo, recebido: {period}")
    return closes.rolling(window=period, min_periods=period).mean()


def ema(closes: pd.Series, period: int) -> pd.Series:
    """
    Exponential Moving Average (Média Móvel Exponencial).

    Dá mais peso aos preços recentes. Mais reativa que a SMA.
    Usa suavização standard: alpha = 2 / (period + 1).

    Fórmula: EMA[t] = close[t] × alpha + EMA[t-1] × (1 - alpha)
    Onde alpha = 2 / (period + 1)

    Implementação usa pandas.ewm com adjust=False para evitar lookahead bias.

    Args:
        closes: Série de preços de fechamento (ordem cronológica).
        period: Número de períodos (determina o fator de decaimento).

    Returns:
        Série com os valores de EMA. NaN para os primeiros (period-1) candles.

    Exemplo:
        closes = pd.Series([100, 102, 104, 103, 105])
        result = ema(closes, 3)
        # multiplier = 2/(3+1) = 0.5
    """
    if period <= 0:
        raise ValueError(f"period deve ser positivo, recebido: {period}")

    return closes.ewm(
        span=period,
        min_periods=period,
        adjust=False,
    ).mean()


def vwap(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
) -> pd.Series:
    """
    Volume Weighted Average Price (Preço Médio Ponderado por Volume).

    Amplamente usado como referência de preço "justo" intraday.
    Traders institucionais usam VWAP como benchmark de execução.

    Fórmula:
        TP = (high + low + close) / 3          (typical price)
        VWAP = cumsum(TP × volume) / cumsum(volume)

    ⚠️  IMPORTANTE — Sem lookahead bias:
        O cálculo é cumulativo dentro da série fornecida.
        Para uso correto, forneça apenas candles do dia atual.
        Ou use um VWAP "rolante" para períodos mais longos.

    ⚠️  Requer volume > 0:
        Se volume = 0, o denominador seria 0. Esses candles são ignorados.

    Args:
        high: Série de máximas.
        low: Série de mínimas.
        close: Série de fechamentos.
        volume: Série de volumes.

    Returns:
        Série com os valores de VWAP. NaN onde volume = 0 em todos os candles até o momento.
    """
    # Valida tamanho consistente
    if not (len(high) == len(low) == len(close) == len(volume)):
        raise ValueError(
            f"Todas as séries devem ter o mesmo tamanho. "
            f"Recebido: high={len(high)}, low={len(low)}, "
            f"close={len(close)}, volume={len(volume)}"
        )

    # Typical price
    typical_price = (high + low + close) / 3.0

    # Substitui volume 0 por NaN para evitar divisão por zero
    safe_volume = volume.where(volume > 0, other=float("nan"))

    # Cálculo cumulativo
    cum_tpv = (typical_price * safe_volume).cumsum()
    cum_vol = safe_volume.cumsum()

    return cum_tpv / cum_vol


def sma_series_to_dict(closes: pd.Series, periods: list[int]) -> dict[str, pd.Series]:
    """
    Calcula múltiplos períodos de SMA de uma vez.

    Conveniência para FeatureEngine.

    Args:
        closes: Série de fechamentos.
        periods: Lista de períodos (ex: [9, 20, 50, 200]).

    Returns:
        Dicionário {f"sma_{period}": pd.Series} para cada período.

    Exemplo:
        result = sma_series_to_dict(closes, [20, 50])
        result["sma_20"]  # SMA de 20 períodos
        result["sma_50"]  # SMA de 50 períodos
    """
    return {f"sma_{p}": sma(closes, p) for p in periods}


def ema_series_to_dict(closes: pd.Series, periods: list[int]) -> dict[str, pd.Series]:
    """
    Calcula múltiplos períodos de EMA de uma vez.

    Conveniência para FeatureEngine.

    Args:
        closes: Série de fechamentos.
        periods: Lista de períodos (ex: [9, 21, 55]).

    Returns:
        Dicionário {f"ema_{period}": pd.Series} para cada período.
    """
    return {f"ema_{p}": ema(closes, p) for p in periods}
