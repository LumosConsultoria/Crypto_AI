"""
DataCache — Cache local de candles em CSV
============================================
Persistência simples e auditável de séries de candles em CSV local.

⚠️  Sem compressão. Sem DB. Sem retry/lock.
⚠️  Um arquivo por par (symbol, timeframe).
⚠️  Política nesta fase: save() SOBRESCREVE (sem merge incremental).

Convenção de nomenclatura:
    {base_dir}/{symbol}_{timeframe}.csv

    Exemplo: data/historical/BTCUSDT_15.csv

DESIGN: symbol e timeframe NÃO são colunas do CSV. Eles são derivados do
filename e ATRIBUÍDOS a cada Candle durante o load — compatível com o
load_candles_from_csv() do backtest_data.py existente. Para preservar a
auditabilidade, save() valida que TODAS as candles têm o mesmo symbol e
timeframe (lança ValueError em caso de inconsistência).
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from crypto_trading_bot.backtesting.backtest_data import (
    candles_to_csv_string,
    load_candles_from_csv,
)
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.logging_system.logger import get_logger

_logger = get_logger(__name__)

# Diretório default de cache (pode ser sobrescrito no construtor)
_DEFAULT_BASE_DIR = Path("data/historical")


class DataCacheError(Exception):
    """Erro de operação no DataCache (load missing, save inconsistency, etc.)."""


class DataCache:
    """
    Cache local de candles em CSV (1 arquivo por symbol/timeframe).

    Atributos:
        base_dir: Diretório raiz do cache.

    Métodos:
        path_for(symbol, timeframe) → Path
        exists(symbol, timeframe)  → bool
        save(candles)               → Path (validação obrigatória)
        load(symbol, timeframe)    → List[Candle]
    """

    def __init__(self, base_dir: Path = _DEFAULT_BASE_DIR) -> None:
        self._base_dir = Path(base_dir)

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    def path_for(self, symbol: str, timeframe: str) -> Path:
        """
        Retorna o caminho convencional para um par (symbol, timeframe).

        Não cria diretórios nem verifica existência.
        """
        if not symbol or not isinstance(symbol, str):
            raise ValueError(f"symbol inválido: {symbol!r}")
        if not timeframe or not isinstance(timeframe, str):
            raise ValueError(f"timeframe inválido: {timeframe!r}")
        return self._base_dir / f"{symbol}_{timeframe}.csv"

    def exists(self, symbol: str, timeframe: str) -> bool:
        """True se o arquivo de cache existir para (symbol, timeframe)."""
        return self.path_for(symbol, timeframe).is_file()

    def save(self, candles: List[Candle]) -> Path:
        """
        Salva candles em CSV. SOBRESCREVE arquivo existente.

        Args:
            candles: Lista NÃO-VAZIA de Candle. Todas com mesmo symbol/timeframe.

        Returns:
            Path do arquivo CSV gravado.

        Raises:
            ValueError: se candles estiver vazia OU se houver inconsistência
                        de symbol/timeframe entre os candles.

        ⚠️  Validação obrigatória: garante que filename reflete os dados.
        """
        if not candles:
            raise ValueError("DataCache.save: lista de candles vazia.")

        symbol = candles[0].symbol
        timeframe = candles[0].timeframe

        # Auditabilidade: símbolo/timeframe consistentes em TODOS os candles
        for i, c in enumerate(candles):
            if c.symbol != symbol:
                raise ValueError(
                    f"DataCache.save: candle[{i}].symbol={c.symbol!r} "
                    f"!= candles[0].symbol={symbol!r}"
                )
            if c.timeframe != timeframe:
                raise ValueError(
                    f"DataCache.save: candle[{i}].timeframe={c.timeframe!r} "
                    f"!= candles[0].timeframe={timeframe!r}"
                )

        path = self.path_for(symbol, timeframe)
        # Garante que o diretório existe (cria recursivamente se necessário)
        path.parent.mkdir(parents=True, exist_ok=True)

        csv_text = candles_to_csv_string(candles, include_header=True)
        path.write_text(csv_text, encoding="utf-8")

        _logger.info(
            f"DataCache.save | {symbol}/{timeframe} | "
            f"{len(candles)} candles | {path}"
        )
        return path

    def load(self, symbol: str, timeframe: str) -> List[Candle]:
        """
        Carrega candles do CSV cacheado para (symbol, timeframe).

        Args:
            symbol:    Símbolo (ex: "BTCUSDT").
            timeframe: Timeframe (ex: "15").

        Returns:
            Lista de Candle em ordem cronológica (load_candles_from_csv
            já ordena internamente).

        Raises:
            DataCacheError: se o arquivo não existir.
        """
        path = self.path_for(symbol, timeframe)
        if not path.is_file():
            raise DataCacheError(
                f"DataCache: arquivo não encontrado para "
                f"{symbol}/{timeframe} em {path}"
            )

        candles = load_candles_from_csv(
            path=path,
            symbol=symbol,
            timeframe=timeframe,
        )
        _logger.info(
            f"DataCache.load | {symbol}/{timeframe} | "
            f"{len(candles)} candles | {path}"
        )
        return candles
