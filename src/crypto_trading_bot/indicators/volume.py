"""
Indicadores de Volume
======================
OBV (On-Balance Volume).

⚠️  REGRAS DE DESIGN:
    1. Funções puras — sem efeitos colaterais.
    2. Sem acesso a APIs ou configuração de risco.
    3. Sem geração de sinais de compra/venda.
    4. Dados insuficientes retornam NaN ou séries com NaN.
    5. Sem lookahead bias.

OBV:
    Relaciona volume com variação de preço.
    Acumulação de volume em dias de alta → pressão compradora.
    Acumulação de volume em dias de baixa → pressão vendedora.
    Divergência OBV vs preço pode indicar reversão iminente.
"""

from __future__ import annotations

import pandas as pd
import numpy as np


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """
    On-Balance Volume (Volume no Balanço).

    Cumulativo de volume:
        - Se close > close_anterior: OBV += volume
        - Se close < close_anterior: OBV -= volume
        - Se close == close_anterior: OBV não muda

    Fórmula:
        OBV[t] = OBV[t-1] + volume[t] × sign(close[t] - close[t-1])
        Onde sign(0) = 0

    Interpretação:
        A tendência do OBV confirma (ou diverge de) a tendência de preço.
        Divergência: preço sobe mas OBV cai → possível fraqueza.

    Args:
        close: Série de preços de fechamento (ordem cronológica).
        volume: Série de volumes (ordem cronológica).

    Returns:
        Série com os valores de OBV. Primeiro valor = volume[0] (base de acumulação).

    Exemplo:
        obv_result = obv(closes, volumes)
        # Se OBV estiver subindo enquanto preço sobe → confirmação de tendência
    """
    if len(close) != len(volume):
        raise ValueError(
            f"close e volume devem ter o mesmo tamanho. "
            f"close={len(close)}, volume={len(volume)}"
        )

    if len(close) == 0:
        return pd.Series(dtype=float)

    # Variação de preço: positiva, negativa ou zero
    price_change = close.diff()

    # Sinal da variação: +1, -1 ou 0
    direction = price_change.apply(
        lambda x: 1 if x > 0 else (-1 if x < 0 else 0)
    )

    # Primeiro candle não tem variação — contribui com volume positivo como base
    direction.iloc[0] = 0

    # OBV é o acumulado do volume direcional
    directional_volume = direction * volume
    obv_series = directional_volume.cumsum()

    return obv_series


def obv_with_ema(
    close: pd.Series,
    volume: pd.Series,
    ema_period: int = 21,
) -> tuple[pd.Series, pd.Series]:
    """
    OBV com uma EMA suavizada para reduzir ruído.

    Retorna o OBV bruto e a EMA do OBV.
    A EMA do OBV é usada para filtrar sinais falsos.

    Args:
        close: Série de fechamentos.
        volume: Série de volumes.
        ema_period: Período da EMA aplicada ao OBV.

    Returns:
        Tupla (obv_series, obv_ema) — ambas são pd.Series.

    Exemplo:
        raw_obv, obv_signal = obv_with_ema(closes, volumes, ema_period=21)
        # Quando raw_obv > obv_signal: momentum de alta
        # Quando raw_obv < obv_signal: momentum de baixa
    """
    raw_obv = obv(close, volume)

    obv_ema = raw_obv.ewm(
        span=ema_period,
        min_periods=ema_period,
        adjust=False,
    ).mean()

    return raw_obv, obv_ema
