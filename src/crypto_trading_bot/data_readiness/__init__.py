"""
data_readiness - Historical Data Readiness (FASE 36.x)
=======================================================
Validacao OFFLINE de dataset historico de candles (BTCUSDT 15m e
outros) para backtest / walk-forward / calibracao. Reaproveita o
formato canonico do BacktestData. ZERO rede / API / credencial.
"""

from crypto_trading_bot.data_readiness.readiness import (
    CANONICAL_COLUMNS,
    DEFAULT_MAX_GAP_FRACTION,
    DEFAULT_MIN_ROWS_BACKTEST,
    DEFAULT_MIN_ROWS_WALK_FORWARD,
    DataReadinessReport,
    ReadinessStatus,
    SUPPORTED_FUTURE_SOURCES,
    canonical_dataset_path,
    check_readiness_at_canonical_path,
    describe_source_contract,
    import_candle_dataset,
    validate_candle_dataset,
)

__all__ = [
    "CANONICAL_COLUMNS",
    "DEFAULT_MAX_GAP_FRACTION",
    "DEFAULT_MIN_ROWS_BACKTEST",
    "DEFAULT_MIN_ROWS_WALK_FORWARD",
    "DataReadinessReport",
    "ReadinessStatus",
    "SUPPORTED_FUTURE_SOURCES",
    "canonical_dataset_path",
    "check_readiness_at_canonical_path",
    "describe_source_contract",
    "import_candle_dataset",
    "validate_candle_dataset",
]
