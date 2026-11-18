"""
Módulo de Indicadores Técnicos
================================
Calcula indicadores técnicos e quantitativos sobre dados de mercado.

⚠️  REGRAS FUNDAMENTAIS:
    1. Indicadores são funções PURAS — recebem dados, retornam valores.
    2. SEM efeitos colaterais, sem acesso a APIs.
    3. SEM geração de sinais de compra/venda.
    4. SEM lógica de estratégia.
    5. Dados insuficientes retornam NaN (sem exceção).
    6. A estratégia é responsável por interpretar os valores.

Categorias implementadas (FASE 3B):
    Tendência:   SMA, EMA, VWAP
    Momentum:    RSI (Wilder)
    Volatilidade: ATR (Wilder), Bollinger Bands
    Volume:      OBV, OBV+EMA

Categorias futuras (FASE 4+):
    - Ichimoku Cloud
    - MACD
    - Stochastic
    - CVD (Cumulative Volume Delta)
    - VPVR (Volume Profile Visible Range)
    - Funding Rate / Open Interest

Uso:
    from crypto_trading_bot.indicators import sma, ema, rsi, atr, bollinger_bands, obv, vwap

    closes = pd.Series([...])
    sma_20 = sma(closes, 20)
    rsi_14 = rsi(closes, 14)
"""

# Tendência
from crypto_trading_bot.indicators.trend import (
    sma,
    ema,
    vwap,
    sma_series_to_dict,
    ema_series_to_dict,
)

# Momentum
from crypto_trading_bot.indicators.momentum import (
    rsi,
    rsi_last,
)

# Volatilidade
from crypto_trading_bot.indicators.volatility_indicators import (
    true_range,
    atr,
    atr_last,
    bollinger_bands,
    BollingerBands,
)

# Volume
from crypto_trading_bot.indicators.volume import (
    obv,
    obv_with_ema,
)

__all__ = [
    # Tendência
    "sma",
    "ema",
    "vwap",
    "sma_series_to_dict",
    "ema_series_to_dict",
    # Momentum
    "rsi",
    "rsi_last",
    # Volatilidade
    "true_range",
    "atr",
    "atr_last",
    "bollinger_bands",
    "BollingerBands",
    # Volume
    "obv",
    "obv_with_ema",
]
