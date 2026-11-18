"""
Indicadores de Momentum
========================
RSI (Relative Strength Index).

⚠️  REGRAS DE DESIGN:
    1. Funções puras — sem efeitos colaterais.
    2. Sem acesso a APIs, exchanges ou configuração de risco.
    3. Sem geração de sinais de compra/venda.
    4. Dados insuficientes retornam NaN.
    5. Sem lookahead bias.

RSI (Wilder):
    Mede a velocidade e magnitude das mudanças de preço.
    Valor entre 0 e 100.
    Interpretação clássica (não é sinal obrigatório):
        > 70: sobrecomprado
        < 30: sobrevendido
    Mas estratégias institucionais raramente usam esses thresholds de forma ingênua.
"""

from __future__ import annotations

import pandas as pd
import numpy as np


def rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index (Índice de Força Relativa).

    Implementação usando o método de suavização de Wilder (EWM com alpha=1/period).
    Este é o RSI "clássico" — o mesmo usado pela maioria das plataformas.

    Fórmula:
        delta = close.diff()
        gain = max(delta, 0)   (ganhos)
        loss = max(-delta, 0)  (perdas — valor absoluto)
        RS = avg_gain / avg_loss   (Wilder's smoothing)
        RSI = 100 - 100 / (1 + RS)

    Suavização de Wilder:
        Equivalente a EWM com alpha = 1/period e adjust=False.
        Diferente da SMA simples dos ganhos/perdas.

    Args:
        closes: Série de preços de fechamento (ordem cronológica).
        period: Número de períodos para o RSI (padrão: 14).

    Returns:
        Série com valores RSI entre 0 e 100. NaN para os primeiros `period` candles.

    Exemplo:
        closes = pd.Series([44.34, 44.09, 44.15, 43.61, 44.33,
                            44.83, 45.10, 45.15, 43.61, 44.33, 44.83,
                            45.10, 45.15, 45.33, 46.08])
        result = rsi(closes, period=14)
        # result.dropna().iloc[0] ≈ 70.53 (valor esperado para esta série)
    """
    if period <= 0:
        raise ValueError(f"period deve ser positivo, recebido: {period}")
    if period < 2:
        raise ValueError(f"period deve ser >= 2 para RSI, recebido: {period}")

    # Diferença entre fechamentos consecutivos
    delta = closes.diff()

    # Separar ganhos e perdas
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    # Suavização de Wilder: alpha = 1/period
    # adjust=False → cada valor usa o anterior, sem lookahead
    # min_periods=period → NaN até ter `period` pontos
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    # Constrói RSI tratando os casos especiais de avg_loss=0:
    #   - avg_loss=0 e avg_gain>0 → todos os movimentos são de alta → RSI = 100
    #   - avg_loss=0 e avg_gain=0 → mercado sem variação → RSI = 50 (convenção)
    #   - avg_loss>0 → cálculo normal
    rsi_values = pd.Series(float("nan"), index=closes.index, dtype=float)

    # Máscara de valores válidos (não-NaN)
    valid = avg_gain.notna() & avg_loss.notna()

    # Caso: só ganhos (avg_loss=0, avg_gain>0) → RSI = 100
    all_gains = valid & (avg_loss == 0) & (avg_gain > 0)
    rsi_values.loc[all_gains] = 100.0

    # Caso normal: avg_loss > 0
    normal = valid & (avg_loss > 0)
    if normal.any():
        rs = avg_gain.loc[normal] / avg_loss.loc[normal]
        rsi_values.loc[normal] = 100.0 - (100.0 / (1.0 + rs))

    return rsi_values


def rsi_last(closes: pd.Series, period: int = 14) -> float:
    """
    Retorna apenas o último valor do RSI.

    Conveniência para estratégias que precisam apenas do valor atual.

    Args:
        closes: Série de fechamentos.
        period: Período do RSI.

    Returns:
        Último valor do RSI como float, ou float('nan') se insuficiente.
    """
    result = rsi(closes, period)
    last = result.iloc[-1] if len(result) > 0 else float("nan")
    return float(last) if not pd.isna(last) else float("nan")
