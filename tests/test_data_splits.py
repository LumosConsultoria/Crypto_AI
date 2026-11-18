"""
Testes de data_splits — FASE 3E.4A
====================================
⚠️  ZERO chamadas à internet.
⚠️  ZERO API keys.
⚠️  ZERO ordens reais.

Cobertura:
    - split_in_sample_out_of_sample: defaults, validações, edge cases,
      preservação de ordem, ausência de sobreposição.
    - walk_forward_split: número de folds, adjacência, train_pct respeitado,
      validações, política explícita de sobra descartada (n % n_folds != 0).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from crypto_trading_bot.backtesting.backtest_data import BacktestDataError
from crypto_trading_bot.backtesting.data_splits import (
    split_in_sample_out_of_sample,
    walk_forward_split,
)
from crypto_trading_bot.exchange.base_exchange import Candle


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
_INTERVAL = timedelta(minutes=15)


def _make_candles(n: int, symbol: str = "BTCUSDT") -> List[Candle]:
    """Cria n candles determinísticos com timestamps crescentes (15min)."""
    return [
        Candle(
            symbol=symbol,
            timeframe="15",
            timestamp=_TS0 + _INTERVAL * i,
            open=65000.0,
            high=65100.0,
            low=64900.0,
            close=65000.0,
            volume=1000.0,
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# split_in_sample_out_of_sample
# ---------------------------------------------------------------------------

class TestSplitInSampleOutOfSample:

    def test_default_split_70_30_lengths(self):
        candles = _make_candles(100)
        in_sample, out_of_sample = split_in_sample_out_of_sample(candles)
        assert len(in_sample) == 70
        assert len(out_of_sample) == 30

    def test_split_preserves_chronological_order(self):
        candles = _make_candles(100)
        in_sample, out_of_sample = split_in_sample_out_of_sample(candles)
        assert in_sample[-1].timestamp < out_of_sample[0].timestamp

    def test_split_lengths_sum_to_total(self):
        candles = _make_candles(83)
        in_sample, out_of_sample = split_in_sample_out_of_sample(candles, in_sample_pct=0.6)
        assert len(in_sample) + len(out_of_sample) == 83

    def test_no_overlap_between_in_and_out(self):
        """Nenhum timestamp aparece nas duas janelas."""
        candles = _make_candles(100)
        in_sample, out_of_sample = split_in_sample_out_of_sample(candles)
        in_ts = {c.timestamp for c in in_sample}
        out_ts = {c.timestamp for c in out_of_sample}
        assert in_ts.isdisjoint(out_ts)

    def test_split_with_custom_pct_50_50(self):
        candles = _make_candles(200)
        in_sample, out_of_sample = split_in_sample_out_of_sample(
            candles, in_sample_pct=0.5
        )
        assert len(in_sample) == 100
        assert len(out_of_sample) == 100

    @pytest.mark.parametrize("pct", [0.0, 1.0, -0.1, 1.1, 2.0])
    def test_invalid_pct_raises(self, pct):
        candles = _make_candles(100)
        with pytest.raises(ValueError, match="in_sample_pct"):
            split_in_sample_out_of_sample(candles, in_sample_pct=pct)

    def test_empty_candles_raises(self):
        with pytest.raises(BacktestDataError):
            split_in_sample_out_of_sample([])

    def test_split_too_small_dataset_raises(self):
        """pct=0.001 com n=10 → split_idx=0 → in_sample vazio → erro."""
        candles = _make_candles(10)
        with pytest.raises(ValueError, match="janela vazia"):
            split_in_sample_out_of_sample(candles, in_sample_pct=0.001)


# ---------------------------------------------------------------------------
# walk_forward_split
# ---------------------------------------------------------------------------

class TestWalkForwardSplit:

    def test_returns_correct_number_of_folds(self):
        candles = _make_candles(100)
        folds = walk_forward_split(candles, n_folds=5, train_pct=0.7)
        assert len(folds) == 5

    def test_each_fold_has_train_and_test(self):
        candles = _make_candles(100)
        folds = walk_forward_split(candles, n_folds=5, train_pct=0.7)
        for k, (train, test) in enumerate(folds):
            assert len(train) > 0, f"fold {k} train vazio"
            assert len(test) > 0, f"fold {k} test vazio"

    def test_folds_are_adjacent_and_non_overlapping(self):
        """
        Última timestamp do fold k < primeira do fold k+1.
        Nenhum candle (timestamp) aparece em dois folds.
        """
        candles = _make_candles(100)
        folds = walk_forward_split(candles, n_folds=5, train_pct=0.7)
        all_timestamps_per_fold = [
            [c.timestamp for c in train] + [c.timestamp for c in test]
            for train, test in folds
        ]
        # Adjacência: último de fold k < primeiro de fold k+1
        for k in range(len(all_timestamps_per_fold) - 1):
            last_k = all_timestamps_per_fold[k][-1]
            first_k1 = all_timestamps_per_fold[k + 1][0]
            assert last_k < first_k1, (
                f"Fold {k} sobrepõe fold {k+1}: {last_k} >= {first_k1}"
            )
        # Sem duplicatas globais
        flat = [ts for fold in all_timestamps_per_fold for ts in fold]
        assert len(flat) == len(set(flat)), "Folds compartilham candles!"

    def test_train_test_split_within_fold_respects_train_pct(self):
        """fold_size=20, train_pct=0.7 → train=14, test=6 em cada fold."""
        candles = _make_candles(100)
        folds = walk_forward_split(candles, n_folds=5, train_pct=0.7)
        for train, test in folds:
            assert len(train) == 14
            assert len(test) == 6

    def test_train_test_inside_fold_are_chronologically_ordered(self):
        candles = _make_candles(100)
        folds = walk_forward_split(candles, n_folds=5, train_pct=0.7)
        for train, test in folds:
            assert train[-1].timestamp < test[0].timestamp

    @pytest.mark.parametrize("n_folds", [0, 1, -1])
    def test_invalid_n_folds_raises(self, n_folds):
        candles = _make_candles(100)
        with pytest.raises(ValueError, match="n_folds"):
            walk_forward_split(candles, n_folds=n_folds)

    @pytest.mark.parametrize("train_pct", [0.0, 1.0, -0.5, 2.0])
    def test_invalid_train_pct_raises(self, train_pct):
        candles = _make_candles(100)
        with pytest.raises(ValueError, match="train_pct"):
            walk_forward_split(candles, n_folds=5, train_pct=train_pct)

    def test_empty_candles_raises(self):
        with pytest.raises(BacktestDataError):
            walk_forward_split([], n_folds=5)

    def test_n_folds_greater_than_candles_raises(self):
        candles = _make_candles(3)
        with pytest.raises(ValueError, match="menor que n_folds"):
            walk_forward_split(candles, n_folds=5)

    def test_train_pct_too_small_raises(self):
        """fold_size=2, train_pct=0.1 → train_size=0 → erro."""
        candles = _make_candles(10)
        with pytest.raises(ValueError, match="particionamento inválido"):
            walk_forward_split(candles, n_folds=5, train_pct=0.1)

    def test_remainder_is_discarded_when_not_evenly_divisible(self):
        """
        AJUSTE OBRIGATÓRIO: política explícita e testada de sobra descartada.

        11 candles, n_folds=5 → fold_size=2, total_usado=10, descartado=1.
        """
        candles = _make_candles(11)
        folds = walk_forward_split(candles, n_folds=5, train_pct=0.5)
        total_used = sum(len(train) + len(test) for train, test in folds)
        assert total_used == 10, (
            f"Esperado 10 candles usados (5 folds × 2), obtido {total_used}"
        )
        assert total_used < len(candles)
        # Sobra descartada do FINAL — último candle não aparece em nenhum fold.
        used_timestamps = {
            c.timestamp
            for train, test in folds
            for c in (train + test)
        }
        assert candles[-1].timestamp not in used_timestamps

    def test_no_remainder_when_evenly_divisible(self):
        """100 candles, n_folds=5 → fold_size=20, sem sobra."""
        candles = _make_candles(100)
        folds = walk_forward_split(candles, n_folds=5, train_pct=0.7)
        total_used = sum(len(train) + len(test) for train, test in folds)
        assert total_used == 100
