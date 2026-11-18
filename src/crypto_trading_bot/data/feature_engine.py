"""
FeatureEngine — Motor de Features para Estratégias
====================================================
Transforma uma lista de candles em um dataset enriquecido com indicadores
técnicos, pronto para ser consumido por estratégias.

⚠️  RESPONSABILIDADES:
    1. Receber List[Candle] → retornar dict de features enriquecido.
    2. Calcular todos os indicadores de forma padronizada.
    3. Tratar dados insuficientes, candles fora de ordem e NaN.
    4. Preservar ordem temporal (sem lookahead bias).
    5. NÃO gerar sinais de compra/venda.
    6. NÃO tomar decisões de trading.
    7. NÃO conectar a APIs ou exchanges.

⚠️  SEPARAÇÃO DE RESPONSABILIDADES:
    BybitClient → dados brutos
    MarketDataService → abstração da exchange
    FeatureEngine → calcula indicadores sobre os dados
    Strategy → usa features para gerar sinais determinísticos
    RiskEngine → valida os sinais → soberano

Uso:
    from crypto_trading_bot.data.feature_engine import FeatureEngine
    from crypto_trading_bot.exchange.base_exchange import Candle

    engine = FeatureEngine()
    features = engine.compute(candles)

    # Features disponíveis no resultado:
    print(features["sma_20"])       # pd.Series com SMA de 20 períodos
    print(features["ema_9"])        # EMA de 9 períodos
    print(features["rsi_14"])       # RSI de 14 períodos
    print(features["atr_14"])       # ATR de 14 períodos
    print(features["bb_upper"])     # Banda superior de Bollinger
    print(features["bb_lower"])     # Banda inferior
    print(features["vwap"])         # VWAP
    print(features["obv"])          # On-Balance Volume
    print(features["closes"])       # pd.Series de fechamentos
    print(features["last_close"])   # Último fechamento como float
    print(features["last_rsi"])     # Último RSI como float
"""

from __future__ import annotations

import warnings
from typing import Any, List

import pandas as pd
import numpy as np

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.indicators import (
    atr,
    bollinger_bands,
    ema,
    obv,
    rsi,
    sma,
    vwap,
)
from crypto_trading_bot.logging_system.logger import get_logger

_logger = get_logger(__name__)

# Mínimo de candles recomendado para calcular todos os indicadores principais
# (RSI 14 + buffer)
_MIN_CANDLES_RECOMMENDED = 50


class FeatureEngine:
    """
    Motor de features técnicas.

    Recebe uma lista de Candle e retorna um dicionário de features enriquecidas
    com indicadores calculados usando pandas/numpy.

    Parâmetros configuráveis:
        sma_periods: Períodos para SMAs (padrão: [9, 20, 50])
        ema_periods: Períodos para EMAs (padrão: [9, 21])
        rsi_period: Período para RSI (padrão: 14)
        atr_period: Período para ATR (padrão: 14)
        bb_period: Período para Bollinger Bands (padrão: 20)
        bb_num_std: Número de desvios padrão para BB (padrão: 2.0)

    Garantias:
        - Preserva ordem temporal dos candles
        - Candles fora de ordem são reordenados por timestamp
        - Lista vazia retorna features vazias (sem exceção)
        - Candles insuficientes retornam features parciais com NaN
        - NaN é tratado explicitamente (não silenciosamente ignorado)
    """

    def __init__(
        self,
        sma_periods: list[int] | None = None,
        ema_periods: list[int] | None = None,
        rsi_period: int = 14,
        atr_period: int = 14,
        bb_period: int = 20,
        bb_num_std: float = 2.0,
    ) -> None:
        self._sma_periods = sma_periods or [9, 20, 50]
        # FASE 25 Bloco 1 — Defesa em profundidade: defaults cobrem os EMAs
        # requeridos por TrendPullbackStrategy (20/50), VolatilityBreakoutStrategy
        # (50) e BotEngine legado (9/21). NENHUMA estrategia suportada fica em
        # HOLD perpetuo por feature ausente ao usar defaults.
        # Para alinhamento ESTRITO baseado em StrategySpec, use
        # FeatureEngine.from_strategy_spec(spec).
        self._ema_periods = ema_periods or [9, 20, 21, 50]
        self._rsi_period = rsi_period
        self._atr_period = atr_period
        self._bb_period = bb_period
        self._bb_num_std = bb_num_std

    @classmethod
    def from_strategy_spec(cls, spec) -> "FeatureEngine":
        """FASE 25 Bloco 1 - construtor alinhado a StrategySpec.

        Le `spec.default_config` (read-only mapping) e extrai os periods
        requeridos pela estrategia. Garante que o dict de features sempre
        contera as chaves que a strategy.evaluate() consulta.

        Periods extraidos (quando presentes em default_config):
            - ema_fast_period, ema_slow_period (trend_pullback)
            - direction_filter_period          (volatility_breakout)
            - rsi_period, atr_period
            - bb_period

        Os defaults atuais (9, 20, 21, 50 para EMA; 9, 20, 50 para SMA)
        permanecem como base e os periods da spec sao MERGED. Nunca remove
        periods default.

        Args:
            spec: StrategySpec ou objeto com atributo `default_config` Mapping.

        Returns:
            Nova instancia de FeatureEngine com periods alinhados.
        """
        default_config = getattr(spec, "default_config", None) or {}

        ema_periods = list({9, 20, 21, 50})  # defaults defensivos
        for key in ("ema_fast_period", "ema_slow_period",
                    "direction_filter_period"):
            val = default_config.get(key)
            if isinstance(val, int) and val > 0:
                ema_periods.append(val)
        ema_periods = sorted(set(ema_periods))

        sma_periods = sorted({9, 20, 50})

        rsi_period = default_config.get("rsi_period", 14)
        if not isinstance(rsi_period, int) or rsi_period <= 0:
            rsi_period = 14

        atr_period = default_config.get("atr_period", 14)
        if not isinstance(atr_period, int) or atr_period <= 0:
            atr_period = 14

        bb_period = default_config.get("bb_period", 20)
        if not isinstance(bb_period, int) or bb_period <= 0:
            bb_period = 20

        return cls(
            sma_periods=sma_periods,
            ema_periods=ema_periods,
            rsi_period=rsi_period,
            atr_period=atr_period,
            bb_period=bb_period,
        )

    def compute(self, candles: List[Candle]) -> dict[str, Any]:
        """
        Calcula todas as features a partir de uma lista de candles.

        O método trata os seguintes casos especiais:
            - Lista vazia: retorna estrutura vazia
            - 1 candle: retorna estrutura mínima (indicadores = NaN)
            - Candles fora de ordem: reordena por timestamp antes de calcular
            - NaN nos dados de entrada: propaga para o indicador afetado
            - Volumes zero: tratados pelo VWAP (substitui por NaN)

        Args:
            candles: Lista de Candle, preferencialmente em ordem cronológica.

        Returns:
            Dicionário com todas as features calculadas. Estrutura:

            {
                # Series completas (pd.Series, índice 0..N-1)
                "closes": pd.Series,
                "opens": pd.Series,
                "highs": pd.Series,
                "lows": pd.Series,
                "volumes": pd.Series,
                "timestamps": pd.Series,

                # Indicadores (pd.Series, mesmo índice)
                "sma_9": pd.Series,
                "sma_20": pd.Series,
                "sma_50": pd.Series,
                "ema_9": pd.Series,
                "ema_21": pd.Series,
                "rsi_14": pd.Series,
                "atr_14": pd.Series,
                "bb_upper": pd.Series,
                "bb_middle": pd.Series,
                "bb_lower": pd.Series,
                "bb_bandwidth": pd.Series,
                "bb_percent_b": pd.Series,
                "vwap": pd.Series,
                "obv": pd.Series,

                # Valores do último candle (floats) — NaN se insuficiente
                "last_close": float,
                "last_volume": float,
                "last_high": float,
                "last_low": float,
                "last_rsi": float,
                "last_atr": float,
                "last_sma_20": float,
                "last_ema_9": float,
                "last_bb_upper": float,
                "last_bb_lower": float,
                "last_vwap": float,
                "last_obv": float,

                # Metadados
                "n_candles": int,
                "has_sufficient_data": bool,
                "symbol": str | None,
            }

        Notas:
            - Indicadores com NaN no último valor precisam de mais candles.
            - `has_sufficient_data` é True se n_candles >= {_MIN_CANDLES_RECOMMENDED}.
        """
        # --- Caso: lista vazia ---
        if not candles:
            _logger.debug("FeatureEngine.compute: lista de candles vazia")
            return self._empty_features()

        # --- Ordenar por timestamp (preserva ordem temporal) ---
        sorted_candles = sorted(candles, key=lambda c: c.timestamp)

        # Detectar e logar candles fora de ordem
        if sorted_candles != candles:
            _logger.warning(
                f"FeatureEngine.compute: {len(candles)} candles estavam fora de ordem. "
                f"Reordenados por timestamp."
            )

        n = len(sorted_candles)

        # --- Extrair séries OHLCV ---
        closes = pd.Series([c.close for c in sorted_candles], dtype=float)
        opens = pd.Series([c.open for c in sorted_candles], dtype=float)
        highs = pd.Series([c.high for c in sorted_candles], dtype=float)
        lows = pd.Series([c.low for c in sorted_candles], dtype=float)
        volumes = pd.Series([c.volume for c in sorted_candles], dtype=float)
        timestamps = pd.Series([c.timestamp for c in sorted_candles])

        # Verificar NaN nos dados brutos
        if closes.isna().any():
            n_nan = closes.isna().sum()
            _logger.warning(f"FeatureEngine: {n_nan} valores NaN nos fechamentos.")

        # --- Calcular indicadores ---
        features: dict[str, Any] = {
            # Séries OHLCV
            "closes": closes,
            "opens": opens,
            "highs": highs,
            "lows": lows,
            "volumes": volumes,
            "timestamps": timestamps,
        }

        # SMAs
        for period in self._sma_periods:
            features[f"sma_{period}"] = sma(closes, period)

        # EMAs
        for period in self._ema_periods:
            features[f"ema_{period}"] = ema(closes, period)

        # RSI
        features[f"rsi_{self._rsi_period}"] = rsi(closes, self._rsi_period)

        # ATR (requer high, low, close)
        features[f"atr_{self._atr_period}"] = atr(highs, lows, closes, self._atr_period)

        # Bollinger Bands
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            bb = bollinger_bands(closes, period=self._bb_period, num_std=self._bb_num_std)
        features["bb_upper"] = bb.upper
        features["bb_middle"] = bb.middle
        features["bb_lower"] = bb.lower
        features["bb_bandwidth"] = bb.bandwidth
        features["bb_percent_b"] = bb.percent_b

        # VWAP (cumulativo da sessão)
        features["vwap"] = vwap(highs, lows, closes, volumes)

        # OBV
        features["obv"] = obv(closes, volumes)

        # --- Valores do último candle + metadados ---
        # Centralizado em _finalize_last_values para que compute_indexed
        # (FASE 37.1) reuse EXATAMENTE o mesmo mapeamento serie->last_*.
        symbol = sorted_candles[0].symbol if sorted_candles else None
        self._finalize_last_values(features, n, symbol)

        if not features["has_sufficient_data"]:
            _logger.debug(
                f"FeatureEngine: {n} candles (recomendado: {_MIN_CANDLES_RECOMMENDED}). "
                f"Alguns indicadores podem ser NaN."
            )

        return features

    def _finalize_last_values(
        self, features: dict[str, Any], n: int, symbol: Any,
    ) -> None:
        """Preenche os campos last_* e metadados a partir das SERIES ja
        presentes em `features` (le sempre o ULTIMO valor de cada serie).

        ⚠️  Fonte unica de verdade do mapeamento serie->last_*: usado por
        `compute` (serie completa) e por `compute_indexed.at(i)` (serie
        fatiada ate i). Garante identidade entre os dois caminhos.
        """
        empty = pd.Series(dtype=float)
        features["last_close"] = self._last_float(features["closes"])
        features["last_volume"] = self._last_float(features["volumes"])
        features["last_high"] = self._last_float(features["highs"])
        features["last_low"] = self._last_float(features["lows"])
        features["last_rsi"] = self._last_float(
            features[f"rsi_{self._rsi_period}"])
        features["last_atr"] = self._last_float(
            features[f"atr_{self._atr_period}"])
        features["last_sma_20"] = self._last_float(
            features.get("sma_20", empty))
        features["last_ema_9"] = self._last_float(
            features.get("ema_9", empty))
        features["last_bb_upper"] = self._last_float(features["bb_upper"])
        features["last_bb_lower"] = self._last_float(features["bb_lower"])
        features["last_vwap"] = self._last_float(features["vwap"])
        features["last_obv"] = self._last_float(features["obv"])

        features["n_candles"] = n
        features["has_sufficient_data"] = n >= _MIN_CANDLES_RECOMMENDED
        features["symbol"] = symbol

    def compute_indexed(self, candles: List[Candle]) -> "_IndexedFeatures":
        """FASE 37.1 — Calcula a serie completa UMA vez (O(n)) e devolve
        um acessor `at(i)` que entrega o dict de features equivalente a
        `compute(candles[:i+1])`, em O(1) amortizado por candle.

        Identidade (sem look-ahead): indicadores rolling/ewm/cumulativos
        no indice i dependem APENAS de candles[:i+1]; logo
        full_series.iloc[:i+1] == serie de compute(candles[:i+1]). As
        estrategias leem cada serie via .iloc[-1] -> valor em i. Nao
        altera resultado de trade (provado por teste de equivalencia).
        """
        full = self.compute(list(candles))
        return _IndexedFeatures(self, full)

    def _empty_features(self) -> dict[str, Any]:
        """Retorna estrutura de features vazia (lista de candles vazia)."""
        empty = pd.Series(dtype=float)
        features = {
            "closes": empty,
            "opens": empty,
            "highs": empty,
            "lows": empty,
            "volumes": empty,
            "timestamps": pd.Series(dtype=object),
        }

        for period in self._sma_periods:
            features[f"sma_{period}"] = empty
        for period in self._ema_periods:
            features[f"ema_{period}"] = empty

        features[f"rsi_{self._rsi_period}"] = empty
        features[f"atr_{self._atr_period}"] = empty
        features["bb_upper"] = empty
        features["bb_middle"] = empty
        features["bb_lower"] = empty
        features["bb_bandwidth"] = empty
        features["bb_percent_b"] = empty
        features["vwap"] = empty
        features["obv"] = empty

        # Últimos valores = NaN
        for key in ["last_close", "last_volume", "last_high", "last_low",
                    "last_rsi", "last_atr", "last_sma_20", "last_ema_9",
                    "last_bb_upper", "last_bb_lower", "last_vwap", "last_obv"]:
            features[key] = float("nan")

        features["n_candles"] = 0
        features["has_sufficient_data"] = False
        features["symbol"] = None

        return features

    @staticmethod
    def _last_float(series: pd.Series) -> float:
        """Retorna o último valor de uma série como float, ou NaN se vazia/inválida."""
        if series is None or len(series) == 0:
            return float("nan")
        last = series.iloc[-1]
        if pd.isna(last):
            return float("nan")
        return float(last)

    def __repr__(self) -> str:
        return (
            f"FeatureEngine("
            f"sma={self._sma_periods}, "
            f"ema={self._ema_periods}, "
            f"rsi={self._rsi_period}, "
            f"atr={self._atr_period}, "
            f"bb={self._bb_period})"
        )


class _FastSeries:
    """View leve sobre um array numpy, com a API MINIMA que as estrategias
    e `_finalize_last_values` usam nas series de feature: iteracao (`list(s)`,
    `for x in s`), `len(s)`, `s.iloc[k]` e `s[k]`. Evita construir pd.Series
    por candle (FASE 44: precompute O(1)/candle, sem overhead pandas).
    Valores identicos a `pd.Series.iloc[:upper]` (mesma origem numerica)."""

    __slots__ = ("_a",)

    def __init__(self, a) -> None:
        self._a = a   # numpy.ndarray (view ate upper)

    def __len__(self) -> int:
        return int(self._a.shape[0])

    def __iter__(self):
        return iter(self._a)

    def __getitem__(self, k):
        r = self._a[k]
        return _FastSeries(r) if isinstance(k, slice) else r

    @property
    def iloc(self):
        # numpy suporta indexacao negativa/posicional => s.iloc[-1] == a[-1].
        return self._a


class _IndexedFeatures:
    """Acessor O(1)/candle sobre uma serie de features ja computada uma
    vez (FASE 37.1; FASE 44 acelerado p/ numpy). `at(i)` devolve o dict
    equivalente a `FeatureEngine.compute(candles[:i+1])` sem recomputar
    indicadores e sem construir pd.Series por candle.

    Cada serie vira um array numpy precomputado UMA vez; `at(i)` entrega
    um `_FastSeries` sobre a fatia `[:i+1]` (view numpy O(1)); os campos
    last_* e metadados sao recalculados pelo MESMO `_finalize_last_values`
    usado por `compute`, garantindo identidade numerica.
    """

    __slots__ = ("_engine", "_full", "_arrays", "_series_keys", "_symbol",
                 "_n")

    def __init__(self, engine: "FeatureEngine", full: dict[str, Any]) -> None:
        self._engine = engine
        self._full = full
        self._symbol = full.get("symbol")
        self._n = int(full.get("n_candles", 0) or 0)
        # Apenas as chaves que sao pd.Series (as demais sao escalares).
        self._series_keys = [
            k for k, v in full.items() if isinstance(v, pd.Series)
        ]
        # Precompute numpy UMA vez (O(n) memoria; O(1) por candle no at()).
        self._arrays = {k: full[k].to_numpy() for k in self._series_keys}

    @property
    def n_candles(self) -> int:
        return self._n

    def at(self, i: int) -> dict[str, Any]:
        """Dict de features no candle i (== compute(candles[:i+1]))."""
        if self._n == 0 or i < 0:
            return self._engine._empty_features()
        if i >= self._n:
            i = self._n - 1
        out: dict[str, Any] = {}
        upper = i + 1
        for key in self._series_keys:
            out[key] = _FastSeries(self._arrays[key][:upper])
        # last_* + metadados via fonte unica de verdade.
        self._engine._finalize_last_values(out, upper, self._symbol)
        return out
