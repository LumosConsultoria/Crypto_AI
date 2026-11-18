"""
PaperTrader.set_exit_policy — readiness (FASE 12)
==================================================
⚠️  100% offline. ZERO rede.

Cobertura:
    - set_exit_policy(policy) aceita e armazena.
    - set_exit_policy(None) zera.
    - Tipo inválido → TypeError.
    - Comportamento dos métodos existentes do PaperTrader NÃO mudou:
      nenhum método consulta self._exit_policy nesta fase.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from crypto_trading_bot.execution.paper_trader import PaperTrader
from crypto_trading_bot.execution.provider_capability import ProviderCapability
from crypto_trading_bot.exit_policy import ExitPolicy
from crypto_trading_bot.risk.risk_engine import RiskEngine


def _make_trader() -> PaperTrader:
    return PaperTrader(risk_engine=RiskEngine(initial_capital=5000.0))


def _policy() -> ExitPolicy:
    return ExitPolicy(
        provider_capability=ProviderCapability(
            provider_id="mock", supports_market_order=True,
            supports_reduce_only=True,
        ),
    )


class TestSetterStores:

    def test_default_exit_policy_is_none(self):
        t = _make_trader()
        assert t.exit_policy is None

    def test_set_policy_stores(self):
        t = _make_trader()
        p = _policy()
        t.set_exit_policy(p)
        assert t.exit_policy is p

    def test_set_none_clears(self):
        t = _make_trader()
        p = _policy()
        t.set_exit_policy(p)
        assert t.exit_policy is p
        t.set_exit_policy(None)
        assert t.exit_policy is None

    def test_invalid_type_raises(self):
        t = _make_trader()
        with pytest.raises(TypeError, match="ExitPolicy"):
            t.set_exit_policy("not_a_policy")  # type: ignore[arg-type]


class TestPaperTraderDoesNotConsumePolicyYet:

    def test_source_does_not_reference_exit_policy_in_execute_flow(self):
        """
        Garantia estrutural: nenhum método do PaperTrader consulta
        self._exit_policy (apenas o setter o atribui). Ativação real
        é trabalho de fase futura.
        """
        path = Path(PaperTrader.__module__.replace(".", "/") + ".py")
        # Mais robusto: usa __file__ via inspect
        import crypto_trading_bot.execution.paper_trader as pt_mod
        src = open(pt_mod.__file__, "r", encoding="utf-8").read()
        # Contagens permitidas: definição, atribuição inicial, setter, property.
        # Tudo o que NÃO seja setter ou property é "consumo" (proibido).
        occurrences = re.findall(r"self\._exit_policy", src)
        # Esperado: 1 atribuição em __init__, 1 atribuição em set_exit_policy,
        # 1 leitura em property exit_policy. Total = 3.
        assert len(occurrences) == 3, (
            f"Esperado 3 referências a self._exit_policy (init + setter + "
            f"property). Encontrado {len(occurrences)}. "
            f"Possivelmente algum método novo está consumindo a policy. "
            f"Ativação deve ficar para fase futura."
        )
