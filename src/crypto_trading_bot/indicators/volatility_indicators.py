"""
Indicadores de Volatilidade
=============================
ATR (Average True Range) e Bollinger Bands.

⚠️  REGRAS DE DESIGN:
    1. Funções puras — sem efeitos colaterais.
    2. Sem acesso a APIs ou configuração de risco.
    3. Sem geração de sinais de compra/venda.
    4. Dados insuficientes retornam NaN.
    5. Sem lookahead bias.

ATR:
    Mede a volatilidade de mercado independente da direção.
    Muito usado para dimensionar stops e posições.
    "Quanto o mercado se move em média por período."

Bollinger Bands:
    Bandas ao redor de uma SMA proporcionais ao desvio padrão.
    Quanto mais largas as bandas, maior a volatilidade.
    Muito usado para identificar squeeze (baixa volatilidade → explosão iminente).
"""

from __future__ import annotations

from typing import NamedTuple

import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------

def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """
    True Range (Amplitude Real) — componente do ATR.

    O True Range é o maior dos três valores:
        1. high - low (amplitude da vela atual)
        2. |high - previous_close| (gap de alta)
        3. |low - previous_close| (gap de baixa)

    Args:
        high: Série de máximas.
        low: Série de mínimas.
        close: Série de fechamentos.

    Returns:
        Série com o True Range. NaN para o primeiro elemento (sem previous_close).
    """
    if not (len(high) == len(low) == len(close)):
        raise ValueError(
            f"Todas as séries devem ter o mesmo tamanho. "
            f"high={len(high)}, low={len(low)}, close={len(close)}"
        )

    prev_close = close.shift(1)

    # skipna=False: se prev_close é NaN (primeiro candle), o TR inteiro é NaN.
    # Isso preserva a semântica correta: o primeiro candle não tem True Range
    # porque não existe fechamento anterior de referência.
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1, skipna=False)

    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Average True Range (Amplitude Média Real) de Wilder.

    Média suavizada do True Range. Usa a suavização de Wilder (EWM).
    Muito usado para:
        - Dimensionar stops (ex: stop = entry ± 2 × ATR)
        - Dimensionar posições pelo risco
        - Medir volatilidade atual vs histórica

    Fórmula:
        TR = max(high-low, |high-prev_close|, |low-prev_close|)
        ATR[t] = tr[t] × (1/period) + ATR[t-1] × (1 - 1/period)  [Wilder]

    Args:
        high: Série de máximas.
        low: Série de mínimas.
        close: Série de fechamentos.
        period: Número de períodos (padrão: 14, Wilder).

    Returns:
        Série com valores ATR. NaN para os primeiros `period` candles.

    Exemplo:
        # ATR de 14 períodos para dimensionar stop:
        stop_distance = 2.0 * atr(high, low, close, 14).iloc[-1]
        stop_loss = entry_price - stop_distance  # para compra
    """
    if period <= 0:
        raise ValueError(f"period deve ser positivo, recebido: {period}")

    tr = true_range(high, low, close)

    # Suavização de Wilder: alpha = 1/period
    atr_values = tr.ewm(
        alpha=1.0 / period,
        min_periods=period,
        adjust=False,
    ).mean()

    return atr_values


def atr_last(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> float:
    """
    Retorna apenas o último valor do ATR.

    Conveniência para uso em estratégias.

    Returns:
        Último valor do ATR como float, ou float('nan') se insuficiente.
    """
    result = atr(high, low, close, period)
    last = result.iloc[-1] if len(result) > 0 else float("nan")
    return float(last) if not pd.isna(last) else float("nan")


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------

class BollingerBands(NamedTuple):
    """Resultado das Bollinger Bands."""
    upper: pd.Series    # Banda superior (SMA + k × std)
    middle: pd.Series   # Banda do meio (SMA)
    lower: pd.Series    # Banda inferior (SMA - k × std)
    bandwidth: pd.Series  # Largura das bandas (upper - lower) / middle
    percent_b: pd.Series  # %B: posição do preço dentro das bandas


def bollinger_bands(
    closes: pd.Series,
    period: int = 20,
    num_std: float = 2.0,
) -> BollingerBands:
    """
    Bollinger Bands (Bandas de Bollinger).

    Bandas dinâmicas ao redor de uma SMA, a ±num_std desvios padrão.
    Quanto mais largas as bandas, maior a volatilidade recente.

    Fórmula:
        middle = SMA(closes, period)
        std = rolling_std(closes, period)
        upper = middle + num_std × std
        lower = middle - num_std × std
        bandwidth = (upper - lower) / middle
        %B = (close - lower) / (upper - lower)

    Parâmetros comuns:
        Standard: period=20, num_std=2.0
        Para crypto (mais volátil): period=20, num_std=2.5

    Args:
        closes: Série de preços de fechamento (ordem cronológica).
        period: Número de períodos para SMA e desvio padrão (padrão: 20).
        num_std: Número de desvios padrão para as bandas (padrão: 2.0).

    Returns:
        BollingerBands namedtuple com: upper, middle, lower, bandwidth, percent_b.
        Todos os valores são NaN para os primeiros `period-1` candles.

    Exemplo:
        bb = bollinger_bands(closes, period=20, num_std=2.0)
        if not pd.isna(bb.upper.iloc[-1]):
            print(f"Banda superior: {bb.upper.iloc[-1]:.2f}")
            print(f"Banda inferior: {bb.lower.iloc[-1]:.2f}")
    """
    if period <= 0:
        raise ValueError(f"period deve ser positivo, recebido: {period}")
    if num_std <= 0:
        raise ValueError(f"num_std deve ser positivo, recebido: {num_std}")

    # SMA (banda do meio)
    middle = closes.rolling(window=period, min_periods=period).mean()

    # Desvio padrão da população (ddof=0 como maioria das plataformas usa)
    std = closes.rolling(window=period, min_periods=period).std(ddof=0)

    # Bandas
    upper = middle + num_std * std
    lower = middle - num_std * std

    # Bandwidth: mede a "abertura" das bandas relativa ao meio
    # Alto bandwidth = alta volatilidade; baixo = squeeze
    bandwidth = (upper - lower) / middle.where(middle != 0, other=float("nan"))

    # %B: onde o preço está dentro das bandas
    # %B = 0 → no lower; %B = 1 → no upper; %B = 0.5 → no meio
    band_range = (upper - lower).where(upper != lower, other=float("nan"))
    percent_b = (closes - lower) / band_range

    return BollingerBands(
        upper=upper,
        middle=middle,
        lower=lower,
        bandwidth=bandwidth,
        percent_b=percent_b,
    )
