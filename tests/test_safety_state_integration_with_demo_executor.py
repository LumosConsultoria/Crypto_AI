"""
Integração SafetyStateMachine ↔ DemoExecutionResult (FASE 16)
==============================================================
⚠️  100% offline. ZERO rede. ZERO secrets. ZERO ordens.

Estratégia: o operational_safety NÃO importa BybitDemoExecutor nem
DemoExecutionResult. A integração é via duck-typing. Aqui validamos
que:
    1. Um DemoExecutionResult REAL (importado nos testes apenas para
       garantir compatibilidade) pode ser consumido pelo helper genérico.
    2. operational_safety/* não importa BybitDemoExecutor/BybitClient/etc.
    3. record_trade_opened NÃO é chamado pela máquina de estado.
"""

from __future__ import annotations

import pytest

from crypto_trading_bot.execution.bybit_demo_executor import (
    DemoExecutionResult,
)
from crypto_trading_bot.operational_safety import (
    SafetyState,
    SafetyStateMachine,
)


# ---------------------------------------------------------------------------
# DemoExecutionResult REAL alimenta a máquina via duck-typing
# ---------------------------------------------------------------------------

class TestRealDemoResultDuckTyped:

    def test_filled_by_triangulation_result_moves_to_safety_halt(self):
        result = DemoExecutionResult(
            success=True,
            operation="place_order",
            reason="triangulated",
            manual_review_required=True,
            safety_halt_recommended=True,
            reconciliation_confidence="triangulated",
        )
        m = SafetyStateMachine()
        evt = m.from_safety_flags(result)
        # Como ambos flags estão True, vai para SAFETY_HALT_RECOMMENDED.
        assert m.state is SafetyState.SAFETY_HALT_RECOMMENDED
        assert evt is not None
        assert evt.metadata["reconciliation_confidence"] == "triangulated"

    def test_only_manual_review_moves_to_manual_review(self):
        result = DemoExecutionResult(
            success=True,
            operation="place_order",
            reason="triangulated",
            manual_review_required=True,
            safety_halt_recommended=False,
            reconciliation_confidence="triangulated",
        )
        m = SafetyStateMachine()
        m.from_safety_flags(result)
        assert m.state is SafetyState.MANUAL_REVIEW_REQUIRED

    def test_canonical_filled_result_keeps_normal(self):
        result = DemoExecutionResult(
            success=True,
            operation="place_order",
            reason="filled",
            manual_review_required=False,
            safety_halt_recommended=False,
            reconciliation_confidence="canonical",
        )
        m = SafetyStateMachine()
        evt = m.from_safety_flags(result)
        assert evt is None
        assert m.state is SafetyState.NORMAL


# ---------------------------------------------------------------------------
# operational_safety NÃO importa nada de execução/exchange
# ---------------------------------------------------------------------------

class TestNoExecutorImports:

    def _src(self, dotted: str) -> str:
        import importlib
        mod = importlib.import_module(dotted)
        return open(mod.__file__, "r", encoding="utf-8").read()

    def test_safety_state_module_isolated(self):
        src = self._src("crypto_trading_bot.operational_safety.safety_state")
        # Verifica apenas imports reais (não menções textuais em docstrings)
        forbidden_imports = [
            "from crypto_trading_bot.execution.bybit_demo_executor",
            "from crypto_trading_bot.exchange.bybit_client",
            "from crypto_trading_bot.execution.bybit_testnet_executor",
            "import DemoExecutionResult",
        ]
        for tok in forbidden_imports:
            assert tok not in src

    def test_safety_state_machine_module_isolated(self):
        src = self._src(
            "crypto_trading_bot.operational_safety.safety_state_machine"
        )
        # Verifica apenas imports reais (não menções textuais em docstrings)
        forbidden_imports = [
            "from crypto_trading_bot.execution.bybit_demo_executor",
            "from crypto_trading_bot.exchange.bybit_client",
            "from crypto_trading_bot.execution.bybit_testnet_executor",
            "from crypto_trading_bot.risk.risk_engine",
            "import DemoExecutionResult",
        ]
        for tok in forbidden_imports:
            assert tok not in src

    def test_state_machine_does_not_call_record_trade_opened(self):
        """A máquina NÃO chama RiskEngine.record_trade_opened em nenhuma
        transição (defesa estrutural)."""
        src = self._src(
            "crypto_trading_bot.operational_safety.safety_state_machine"
        )
        assert "record_trade_opened" not in src
