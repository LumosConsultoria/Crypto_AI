"""
Public market-data adapter (infra; FASE 43 realocado) — READ-ONLY, sem auth.
==========================================================================
Klines/instrument PUBLICOS reusando os providers da FASE 37
(BinancePublicProvider etc.). SEM secret. Usado via NetComms (gated por
acao). Em teste: provider_obj=Fake. FastAPI-free.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class PublicMarketDataAdapter:
    """Adapter read-only de dados publicos. Nao salva nada (so busca)."""

    def __init__(self, provider: str = "binance", provider_obj=None) -> None:
        self._provider = provider
        self._provider_obj = provider_obj   # injetado em teste (Fake)

    def supported_timeframes(self) -> Dict[str, int]:
        from crypto_trading_bot.historical_data import SUPPORTED_TIMEFRAMES
        return dict(SUPPORTED_TIMEFRAMES)

    def fetch_to_canonical(
        self, *, symbol: str, timeframe: str, start_date: str,
        end_date: str, base_dir: str, force: bool = False,
        run_readiness: bool = True,
    ) -> Dict[str, Any]:
        """Busca candles PUBLICOS read-only e salva no caminho canonico.
        Retorna metadados (sem secret). Rede real so quando chamado via
        run_network_op aprovado (ou provider_obj fake em teste)."""
        from crypto_trading_bot.historical_data import fetch_historical
        result = fetch_historical(
            provider=self._provider, symbol=symbol, timeframe=timeframe,
            start_date=start_date, end_date=end_date, base_dir=base_dir,
            force=force, run_readiness=run_readiness,
            provider_obj=self._provider_obj)
        d = result.to_dict()
        return {
            "provider": d["provider"], "symbol": d["symbol"],
            "timeframe": d["timeframe"], "rows_saved": d["rows_saved"],
            "first_timestamp": d["first_timestamp"],
            "last_timestamp": d["last_timestamp"],
            "checksum": d["checksum"], "dataset_path": d["dataset_path"],
            "readiness_status": d["readiness_status"],
            "overwrite_blocked": d["overwrite_blocked"],
            "errors": d["errors"], "warnings": d["warnings"],
        }


__all__ = ["PublicMarketDataAdapter"]
