"""
Testes dos Indicadores Técnicos
=================================
⚠️  ZERO chamadas à internet — todos os testes usam dados determinísticos.

Cobertura:
    - SMA: cálculo correto, dados insuficientes, period inválido
    - EMA: cálculo correto, mais peso em recentes, dados insuficientes
    - VWAP: cálculo correto, volume zero, tamanhos inconsistentes
    - RSI: cálculo correto, todos os ganhos, todas as perdas, market neutro
    - ATR: true range, ATR final, dados insuficientes
    - Bollinger Bands: upper/lower/middle, bandwidth, %B, dados insuficientes
    - OBV: cálculo correto, sem variação, dados vazios
    - Todos retornam NaN para dados insuficientes (sem exceção)
"""

import math
import pandas as pd
import numpy as np
import pytest

from crypto_trading_bot.indicators import (
    sma, ema, vwap,
    rsi, rsi_last,
    atr, atr_last, true_range, bollinger_bands, BollingerBands,
    obv, obv_with_ema,
    sma_series_to_dict, ema_series_to_dict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _series(*values: float) -> pd.Series:
    """Cria uma pd.Series com os valores fornecidos."""
    return pd.Series(list(values), dtype=float)


def _isnan(val) -> bool:
    """Verifica se um valor é NaN (float ou pd.NA)."""
    try:
        return math.isnan(float(val))
    except (TypeError, ValueError):
        return True


# ---------------------------------------------------------------------------
# Testes de SMA
# ---------------------------------------------------------------------------

class TestSMA:
    """Testa a Simple Moving Average."""

    def test_sma_basic_calculation(self):
        """SMA(3) de [1,2,3,4,5] → [NaN, NaN, 2.0, 3.0, 4.0]."""
        closes = _series(1, 2, 3, 4, 5)
        result = sma(closes, 3)
        assert _isnan(result.iloc[0])
        assert _isnan(result.iloc[1])
        assert result.iloc[2] == pytest.approx(2.0)  # (1+2+3)/3
        assert result.iloc[3] == pytest.approx(3.0)  # (2+3+4)/3
        assert result.iloc[4] == pytest.approx(4.0)  # (3+4+5)/3

    def test_sma_single_period(self):
        """SMA(1) é igual ao próprio preço."""
        closes = _series(10, 20, 30)
        result = sma(closes, 1)
        assert result.iloc[0] == pytest.approx(10.0)
        assert result.iloc[1] == pytest.approx(20.0)
        assert result.iloc[2] == pytest.approx(30.0)

    def test_sma_all_same_values(self):
        """SMA de valores constantes equals o próprio valor."""
        closes = _series(100, 100, 100, 100, 100)
        result = sma(closes, 3)
        for i in range(2, 5):
            assert result.iloc[i] == pytest.approx(100.0)

    def test_sma_insufficient_data_returns_nan(self):
        """Série com menos de `period` candles retorna apenas NaN."""
        closes = _series(10, 20)
        result = sma(closes, 5)
        assert result.isna().all()

    def test_sma_period_invalid_raises(self):
        with pytest.raises(ValueError):
            sma(_series(1, 2, 3), period=0)
        with pytest.raises(ValueError):
            sma(_series(1, 2, 3), period=-1)

    def test_sma_series_to_dict(self):
        closes = _series(1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
        result = sma_series_to_dict(closes, [3, 5])
        assert "sma_3" in result
        assert "sma_5" in result
        assert result["sma_3"].iloc[-1] == pytest.approx(9.0)   # (8+9+10)/3
        assert result["sma_5"].iloc[-1] == pytest.approx(8.0)   # (6+7+8+9+10)/5


# ---------------------------------------------------------------------------
# Testes de EMA
# ---------------------------------------------------------------------------

class TestEMA:
    """Testa a Exponential Moving Average."""

    def test_ema_gives_more_weight_to_recent(self):
        """EMA deve dar mais peso ao mais recente que SMA."""
        # Série crescente: EMA deve ser > SMA por dar mais peso ao final
        closes = _series(1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
        ema_result = ema(closes, 5)
        sma_result = sma(closes, 5)
        last_valid_ema = ema_result.dropna().iloc[-1]
        last_valid_sma = sma_result.dropna().iloc[-1]
        assert last_valid_ema > last_valid_sma

    def test_ema_insufficient_data_returns_nan(self):
        closes = _series(1, 2)
        result = ema(closes, 5)
        assert result.isna().all()

    def test_ema_constant_series(self):
        """EMA de série constante é o próprio valor."""
        closes = _series(50.0, 50.0, 50.0, 50.0, 50.0, 50.0)
        result = ema(closes, 3)
        valid = result.dropna()
        assert len(valid) > 0
        for v in valid:
            assert v == pytest.approx(50.0, abs=0.001)

    def test_ema_period_invalid_raises(self):
        with pytest.raises(ValueError):
            ema(_series(1, 2, 3), period=0)

    def test_ema_series_to_dict(self):
        closes = pd.Series(range(1, 25), dtype=float)
        result = ema_series_to_dict(closes, [9, 21])
        assert "ema_9" in result
        assert "ema_21" in result
        assert not result["ema_9"].dropna().empty


# ---------------------------------------------------------------------------
# Testes de VWAP
# ---------------------------------------------------------------------------

class TestVWAP:
    """Testa o Volume Weighted Average Price."""

    def test_vwap_basic_calculation(self):
        """VWAP com volume uniforme = típica ajustada."""
        # typical_price = (high+low+close)/3
        # Com volume uniforme: VWAP = média simples de typical prices
        high = _series(12, 14, 16)
        low = _series(8, 6, 4)
        close = _series(10, 12, 14)
        volume = _series(100, 100, 100)

        result = vwap(high, low, close, volume)

        # TP1 = (12+8+10)/3 = 10, TP2 = (14+6+12)/3 = 10.67, TP3 = (16+4+14)/3 = 11.33
        # VWAP[2] = (10×100 + 10.67×100 + 11.33×100) / 300 = 32/3 ≈ 10.666...
        assert not _isnan(result.iloc[-1])
        assert result.iloc[-1] == pytest.approx(10.666, abs=0.01)

    def test_vwap_higher_volume_weights_more(self):
        """Candle com volume maior deve puxar o VWAP para seu preço."""
        high = _series(100, 200)
        low = _series(90, 190)
        close = _series(95, 195)
        # Volume muito maior no segundo candle
        volume = _series(1, 1000)

        result = vwap(high, low, close, volume)
        # VWAP deve estar próximo do preço do segundo candle
        tp2 = (200 + 190 + 195) / 3  # ≈ 195
        assert abs(result.iloc[-1] - tp2) < 5

    def test_vwap_zero_volume_returns_nan(self):
        """Volume zero deve resultar em NaN para o VWAP daquele ponto."""
        high = _series(100, 100)
        low = _series(90, 90)
        close = _series(95, 95)
        volume = _series(0, 0)  # volume zero

        result = vwap(high, low, close, volume)
        assert result.isna().all()

    def test_vwap_inconsistent_sizes_raises(self):
        with pytest.raises(ValueError):
            vwap(_series(1, 2, 3), _series(1, 2), _series(1, 2), _series(1, 2))


# ---------------------------------------------------------------------------
# Testes de RSI
# ---------------------------------------------------------------------------

class TestRSI:
    """Testa o RSI (Wilder's method)."""

    def test_rsi_all_gains_is_100(self):
        """Se todos os movimentos são positivos, RSI deve ser próximo de 100."""
        closes = _series(*[float(i) for i in range(1, 20)])  # 1, 2, 3, ..., 19
        result = rsi(closes, 14)
        last_valid = result.dropna().iloc[-1]
        assert last_valid > 90.0  # quase 100

    def test_rsi_all_losses_near_zero(self):
        """Se todos os movimentos são negativos, RSI deve ser próximo de 0."""
        closes = _series(*[float(20 - i) for i in range(20)])  # 20, 19, ..., 1
        result = rsi(closes, 14)
        last_valid = result.dropna().iloc[-1]
        assert last_valid < 10.0  # quase 0

    def test_rsi_midpoint_series_near_50(self):
        """Série alternando ganhos e perdas similares deve ter RSI próximo de 50."""
        np.random.seed(42)
        # Série aleatória de pequenas variações
        closes = pd.Series(100.0 + np.cumsum(np.random.uniform(-1, 1, 100)), dtype=float)
        result = rsi(closes, 14)
        last_valid = result.dropna().iloc[-1]
        # Muito frouxo, só verifica que está num intervalo razoável
        assert 20 <= last_valid <= 80

    def test_rsi_insufficient_data_returns_nan(self):
        """Menos de `period` candles → apenas NaN."""
        closes = _series(1, 2, 3, 4, 5)
        result = rsi(closes, 14)
        assert result.isna().all()

    def test_rsi_between_0_and_100(self):
        """RSI deve sempre estar entre 0 e 100."""
        np.random.seed(123)
        closes = pd.Series(100.0 + np.cumsum(np.random.uniform(-5, 5, 200)), dtype=float)
        result = rsi(closes, 14).dropna()
        assert (result >= 0).all() and (result <= 100).all()

    def test_rsi_last_returns_float(self):
        closes = pd.Series(range(1, 30), dtype=float)
        val = rsi_last(closes, 14)
        assert isinstance(val, float)
        assert not math.isnan(val)

    def test_rsi_last_insufficient_returns_nan(self):
        closes = _series(1, 2, 3)
        val = rsi_last(closes, 14)
        assert math.isnan(val)

    def test_rsi_period_invalid_raises(self):
        with pytest.raises(ValueError):
            rsi(_series(1, 2, 3), period=0)
        with pytest.raises(ValueError):
            rsi(_series(1, 2, 3), period=1)


# ---------------------------------------------------------------------------
# Testes de ATR
# ---------------------------------------------------------------------------

class TestATR:
    """Testa o Average True Range."""

    def test_true_range_basic(self):
        """True Range deve ser o maior entre high-low, |high-prev_close|, |low-prev_close|."""
        high = _series(15, 16, 14)
        low = _series(10, 12, 9)
        close = _series(12, 14, 11)

        tr = true_range(high, low, close)

        # tr[0] = NaN (sem prev_close)
        assert _isnan(tr.iloc[0])

        # tr[1] = max(16-12=4, |16-12|=4, |12-12|=0) = 4
        assert tr.iloc[1] == pytest.approx(4.0)

        # tr[2] = max(14-9=5, |14-14|=0, |9-14|=5) = 5
        assert tr.iloc[2] == pytest.approx(5.0)

    def test_atr_insufficient_data_returns_nan(self):
        high = _series(10, 11, 12)
        low = _series(8, 9, 10)
        close = _series(9, 10, 11)
        result = atr(high, low, close, period=14)
        assert result.isna().all()

    def test_atr_positive_values(self):
        """ATR deve sempre ser positivo."""
        n = 30
        np.random.seed(42)
        base = np.cumsum(np.random.uniform(-5, 5, n)) + 100
        high = pd.Series(base + np.random.uniform(0, 5, n))
        low = pd.Series(base - np.random.uniform(0, 5, n))
        close = pd.Series(base)

        result = atr(high, low, close, period=14).dropna()
        assert (result > 0).all()

    def test_atr_last_returns_float(self):
        n = 30
        base = pd.Series(range(n), dtype=float) + 100
        high = base + 2
        low = base - 2
        close = base

        val = atr_last(high, low, close, period=14)
        assert isinstance(val, float)
        assert not math.isnan(val)

    def test_atr_inconsistent_sizes_raises(self):
        with pytest.raises(ValueError):
            atr(_series(1, 2, 3), _series(1, 2), _series(1, 2), period=3)


# ---------------------------------------------------------------------------
# Testes de Bollinger Bands
# ---------------------------------------------------------------------------

class TestBollingerBands:
    """Testa as Bollinger Bands."""

    def test_bb_returns_namedtuple(self):
        closes = pd.Series(range(1, 25), dtype=float)
        result = bollinger_bands(closes, period=5)
        assert isinstance(result, BollingerBands)
        assert hasattr(result, "upper")
        assert hasattr(result, "middle")
        assert hasattr(result, "lower")
        assert hasattr(result, "bandwidth")
        assert hasattr(result, "percent_b")

    def test_bb_upper_always_above_lower(self):
        """Banda superior deve sempre estar acima da inferior."""
        closes = pd.Series(range(1, 30), dtype=float)
        bb = bollinger_bands(closes, period=5, num_std=2.0)
        valid_upper = bb.upper.dropna()
        valid_lower = bb.lower.dropna()
        assert (valid_upper.values >= valid_lower.values).all()

    def test_bb_middle_equals_sma(self):
        """Banda do meio deve ser igual à SMA."""
        closes = pd.Series(range(1, 30), dtype=float)
        bb = bollinger_bands(closes, period=10)
        sma_result = sma(closes, 10)
        # Compara apenas onde ambos têm valores
        mask = ~(bb.middle.isna() | sma_result.isna())
        pd.testing.assert_series_equal(
            bb.middle[mask].reset_index(drop=True),
            sma_result[mask].reset_index(drop=True),
            check_names=False,
        )

    def test_bb_constant_series_zero_bandwidth(self):
        """Série constante → desvio padrão zero → bandwidth zero."""
        closes = pd.Series([100.0] * 25, dtype=float)
        bb = bollinger_bands(closes, period=20)
        valid_bw = bb.bandwidth.dropna()
        if len(valid_bw) > 0:
            assert (valid_bw.abs() < 1e-10).all()

    def test_bb_insufficient_data_returns_nan(self):
        """Menos de `period` candles → NaN."""
        closes = _series(1, 2, 3)
        bb = bollinger_bands(closes, period=20)
        assert bb.upper.isna().all()
        assert bb.lower.isna().all()

    def test_bb_period_invalid_raises(self):
        with pytest.raises(ValueError):
            bollinger_bands(_series(1, 2, 3), period=0)

    def test_bb_num_std_invalid_raises(self):
        with pytest.raises(ValueError):
            bollinger_bands(_series(1, 2, 3), period=3, num_std=0)


# ---------------------------------------------------------------------------
# Testes de OBV
# ---------------------------------------------------------------------------

class TestOBV:
    """Testa o On-Balance Volume."""

    def test_obv_up_day_adds_volume(self):
        """Dia de alta (close > prev_close) adiciona volume ao OBV."""
        close = _series(100, 105, 110)
        volume = _series(1000, 1000, 1000)
        result = obv(close, volume)
        # OBV[0] = 0 (base, sem prev_close)
        # OBV[1] = 0 + 1000 = 1000 (alta)
        # OBV[2] = 1000 + 1000 = 2000 (alta)
        assert result.iloc[0] == pytest.approx(0.0)
        assert result.iloc[1] == pytest.approx(1000.0)
        assert result.iloc[2] == pytest.approx(2000.0)

    def test_obv_down_day_subtracts_volume(self):
        """Dia de baixa (close < prev_close) subtrai volume do OBV."""
        close = _series(100, 90, 80)
        volume = _series(1000, 1000, 1000)
        result = obv(close, volume)
        assert result.iloc[0] == pytest.approx(0.0)
        assert result.iloc[1] == pytest.approx(-1000.0)
        assert result.iloc[2] == pytest.approx(-2000.0)

    def test_obv_unchanged_day_no_change(self):
        """Dia neutro (close == prev_close) não altera OBV."""
        close = _series(100, 100, 100)
        volume = _series(1000, 1000, 1000)
        result = obv(close, volume)
        assert result.iloc[0] == pytest.approx(0.0)
        assert result.iloc[1] == pytest.approx(0.0)
        assert result.iloc[2] == pytest.approx(0.0)

    def test_obv_mixed_days(self):
        """Testa sequência variada."""
        close = _series(100, 105, 103, 108)
        volume = _series(1000, 2000, 1500, 3000)
        result = obv(close, volume)
        # OBV[0] = 0
        # OBV[1] = 0 + 2000 = 2000 (alta)
        # OBV[2] = 2000 - 1500 = 500 (baixa)
        # OBV[3] = 500 + 3000 = 3500 (alta)
        assert result.iloc[0] == pytest.approx(0.0)
        assert result.iloc[1] == pytest.approx(2000.0)
        assert result.iloc[2] == pytest.approx(500.0)
        assert result.iloc[3] == pytest.approx(3500.0)

    def test_obv_empty_series(self):
        """Série vazia → retorna série vazia sem exceção."""
        result = obv(pd.Series(dtype=float), pd.Series(dtype=float))
        assert len(result) == 0

    def test_obv_inconsistent_size_raises(self):
        with pytest.raises(ValueError):
            obv(_series(100, 105), _series(1000))

    def test_obv_with_ema_returns_both_series(self):
        close = pd.Series(range(1, 30), dtype=float)
        volume = pd.Series([100.0] * 29)
        raw, signal = obv_with_ema(close, volume, ema_period=10)
        assert len(raw) == len(close)
        assert len(signal) == len(close)
