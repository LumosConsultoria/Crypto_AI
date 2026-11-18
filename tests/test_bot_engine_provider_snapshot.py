"""
Testes do BotCycleResult.provider_snapshot via BotEngine — FASE 8
====================================================================
⚠️  100% offline. ZERO secrets. ZERO rede.

Cobertura:
    - cycle_result tem provider_snapshot populado quando settings.provider_id
      está no registry (default paper).
    - provider_snapshot é um dict sanitizado (sem secrets).
    - PaperTrader path continua executando normalmente (FASE 6+7 invariantes).
    - cycle_result.executor_result e trade legado seguem preservados.
"""

from __future__ import annotations

from crypto_trading_bot.strategies.signal_model import StrategySignal

from tests.helpers import make_stub_engine


class TestProviderSnapshotPopulatedOnCycle:

    def test_provider_snapshot_present_on_paper_default(self):
        buy = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, *_ = make_stub_engine(buy, capital=5000.0, n_candles=60)
        result = engine.run_once()
        assert result.provider_snapshot is not None
        # Provider default das settings paper isoladas (helpers FASE 7) é "paper".
        assert result.provider_snapshot["provider_id"] == "paper"
        assert result.provider_snapshot["status"] == "active"

    def test_provider_snapshot_has_no_secrets(self):
        buy = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, *_ = make_stub_engine(buy, capital=5000.0, n_candles=60)
        result = engine.run_once()
        snap = result.provider_snapshot
        assert snap is not None
        import json
        blob = json.dumps(snap).lower()
        for bad in ("api_key", "api_secret", "x-bapi-sign", "authorization",
                    "bearer ", "your_testnet_api_key"):
            assert bad not in blob

    def test_paper_path_invariants_preserved(self):
        """Garantia: FASE 8 NÃO alterou o fluxo paper (FASE 6 + bugfix preservados)."""
        buy = StrategySignal.buy("BTCUSDT", "stub", 65000.0, 64000.0, 200.0)
        engine, _strat, risk, _paper = make_stub_engine(buy, capital=5000.0, n_candles=60)
        result = engine.run_once()
        # FASE 6: executor_result + trade legado
        assert result.action == "executed"
        assert result.executed is True
        assert result.executor_result is not None
        assert result.trade is not None
        assert result.executor_result is result.trade
        # bugfix pós-FASE 6: record_trade_opened uma única vez
        assert risk.get_status_summary()["trades_today"] == 1
        # FASE 8: provider_snapshot
        assert result.provider_snapshot is not None
