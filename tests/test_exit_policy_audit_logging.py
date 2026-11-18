"""
Testes de auditoria da ExitPolicy (FASE 11)
============================================
⚠️  100% offline. ZERO rede.

Cobertura:
    - should_close=True emite EXATAMENTE 1 linha EXIT_DECISION.
    - should_close=False NÃO emite linha de audit.
    - A linha contém: reason, source, symbol, side, reduce_only_required,
      auto_blocked, entry, trigger, elapsed, provider_cap.
    - A linha NÃO contém secrets, API keys, headers, signatures, PII.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.execution.provider_capability import ProviderCapability
from crypto_trading_bot.exit_policy import (
    ExitPolicy,
    OpenPositionState,
    PositionSide,
)


_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _cap(supports_ro: bool = True, provider_id: str = "mock") -> ProviderCapability:
    return ProviderCapability(
        provider_id=provider_id,
        supports_market_order=True,
        supports_reduce_only=supports_ro,
    )


def _pos() -> OpenPositionState:
    return OpenPositionState(
        symbol="BTCUSDT", side=PositionSide.BUY,
        entry_price=65000.0, entry_time=_NOW,
        stop_loss_price=64000.0, take_profit_price=67000.0,
        position_size_usd=200.0, entry_candle_idx=10,
    )


def _sl_candle() -> Candle:
    return Candle(
        symbol="BTCUSDT", timeframe="15", timestamp=_NOW,
        open=64500.0, high=65000.0, low=63500.0, close=64000.0,
        volume=1000.0,
    )


def _patch_audit(monkeypatch) -> MagicMock:
    """Substitui o _audit do módulo por um MagicMock e o retorna."""
    import crypto_trading_bot.exit_policy.exit_policy as ep_mod
    fake_audit = MagicMock()
    monkeypatch.setattr(ep_mod, "_audit", fake_audit)
    return fake_audit


# ---------------------------------------------------------------------------
# Quantidade de linhas
# ---------------------------------------------------------------------------

class TestAuditEmission:

    def test_should_close_true_emits_exactly_one_audit_line(self, monkeypatch):
        fake_audit = _patch_audit(monkeypatch)
        policy = ExitPolicy(provider_capability=_cap())
        policy.evaluate(
            position=_pos(), candle=_sl_candle(),
            now=_NOW, candle_idx=11,
        )
        # Exatamente uma chamada de _audit.info
        assert fake_audit.info.call_count == 1

    def test_should_close_false_emits_zero_audit_lines(self, monkeypatch):
        fake_audit = _patch_audit(monkeypatch)
        policy = ExitPolicy(provider_capability=_cap())
        # Candle não bate em SL nem TP
        neutral_candle = Candle(
            symbol="BTCUSDT", timeframe="15", timestamp=_NOW,
            open=65000.0, high=65500.0, low=64500.0, close=65000.0,
            volume=1000.0,
        )
        policy.evaluate(
            position=_pos(), candle=neutral_candle,
            now=_NOW, candle_idx=11,
        )
        assert fake_audit.info.call_count == 0

    def test_multiple_close_decisions_emit_multiple_lines(self, monkeypatch):
        fake_audit = _patch_audit(monkeypatch)
        policy = ExitPolicy(provider_capability=_cap())
        for _ in range(3):
            policy.evaluate(
                position=_pos(), candle=_sl_candle(),
                now=_NOW, candle_idx=11,
            )
        assert fake_audit.info.call_count == 3


# ---------------------------------------------------------------------------
# Conteúdo da linha
# ---------------------------------------------------------------------------

class TestAuditLineContent:

    def _captured_line(self, monkeypatch, **policy_kwargs) -> str:
        fake_audit = _patch_audit(monkeypatch)
        policy = ExitPolicy(provider_capability=_cap(), **policy_kwargs)
        policy.evaluate(
            position=_pos(), candle=_sl_candle(),
            now=_NOW, candle_idx=11,
        )
        assert fake_audit.info.call_count == 1
        args, kwargs = fake_audit.info.call_args
        return args[0] if args else kwargs.get("msg", "")

    def test_line_starts_with_exit_decision(self, monkeypatch):
        line = self._captured_line(monkeypatch)
        assert line.startswith("EXIT_DECISION |")

    def test_line_contains_all_required_fields(self, monkeypatch):
        line = self._captured_line(monkeypatch)
        required = [
            "reason=",
            "source=",
            "symbol=BTCUSDT",
            "side=buy",
            "reduce_only_required=",
            "auto_blocked=",
            "entry=",
            "trigger=",
            "elapsed=",
            "provider_cap=",
        ]
        for piece in required:
            assert piece in line, f"linha de audit deve conter '{piece}': {line}"

    def test_line_does_not_contain_secrets(self, monkeypatch):
        line = self._captured_line(monkeypatch)
        forbidden = [
            "api_key", "api_secret", "apiKey", "apiSecret",
            "X-BAPI-API-KEY", "X-BAPI-SIGN", "signature=",
            "Authorization:", "Bearer ", "password",
        ]
        for tok in forbidden:
            assert tok not in line, (
                f"linha de audit não pode conter '{tok}': {line}"
            )

    def test_line_does_not_contain_pii(self, monkeypatch):
        line = self._captured_line(monkeypatch)
        forbidden = [
            "consultorialumos",  # email do operador
            "@",                  # qualquer email
        ]
        for tok in forbidden:
            assert tok not in line, (
                f"linha de audit não pode conter PII '{tok}': {line}"
            )

    def test_line_reflects_capability_blocked_value(self, monkeypatch):
        fake_audit = _patch_audit(monkeypatch)
        policy = ExitPolicy(provider_capability=_cap(supports_ro=False))
        policy.evaluate(
            position=_pos(), candle=_sl_candle(),
            now=_NOW, candle_idx=11,
        )
        line = fake_audit.info.call_args.args[0]
        assert "auto_blocked=True" in line

    def test_line_reflects_capability_unblocked_value(self, monkeypatch):
        fake_audit = _patch_audit(monkeypatch)
        policy = ExitPolicy(provider_capability=_cap(supports_ro=True))
        policy.evaluate(
            position=_pos(), candle=_sl_candle(),
            now=_NOW, candle_idx=11,
        )
        line = fake_audit.info.call_args.args[0]
        assert "auto_blocked=False" in line
