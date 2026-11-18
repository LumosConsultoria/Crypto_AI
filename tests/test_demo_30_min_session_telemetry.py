"""
Tests - SessionTelemetryRecorder (FASE 28)
==============================================
100% offline. ZERO network. ZERO secret persistido.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from crypto_trading_bot.demo_endurance import (
    SessionTelemetryEvent,
    SessionTelemetryRecorder,
)


NOW = datetime(2026, 6, 4, 12, tzinfo=timezone.utc)


class TestSessionTelemetryEvent:

    def test_valid_event(self):
        ev = SessionTelemetryEvent(
            event_type="session_start",
            cycle_idx=None,
            timestamp=NOW,
            snapshot={"foo": "bar"},
        )
        assert ev.event_type == "session_start"
        assert ev.cycle_idx is None
        d = ev.to_dict()
        assert d["event_type"] == "session_start"
        assert d["snapshot"]["foo"] == "bar"

    def test_invalid_event_type_rejected(self):
        with pytest.raises(ValueError, match="event_type"):
            SessionTelemetryEvent(
                event_type="bogus", cycle_idx=None,
                timestamp=NOW, snapshot={},
            )

    def test_negative_cycle_idx_rejected(self):
        with pytest.raises(ValueError, match="cycle_idx"):
            SessionTelemetryEvent(
                event_type="cycle_start", cycle_idx=-1,
                timestamp=NOW, snapshot={},
            )

    def test_naive_timestamp_made_aware(self):
        naive = datetime(2026, 6, 4, 12)
        ev = SessionTelemetryEvent(
            event_type="cycle_start", cycle_idx=0,
            timestamp=naive, snapshot={},
        )
        assert ev.timestamp.tzinfo is not None

    def test_snapshot_is_mappingproxy(self):
        from types import MappingProxyType
        ev = SessionTelemetryEvent(
            event_type="cycle_start", cycle_idx=0,
            timestamp=NOW, snapshot={"x": 1},
        )
        assert isinstance(ev.snapshot, MappingProxyType)

    def test_string_truncated(self):
        long = "x" * 500
        ev = SessionTelemetryEvent(
            event_type="cycle_start", cycle_idx=0,
            timestamp=NOW, snapshot={"k": long},
        )
        assert len(ev.snapshot["k"]) <= 203

    def test_suspicious_string_redacted(self):
        ev = SessionTelemetryEvent(
            event_type="cycle_start", cycle_idx=0,
            timestamp=NOW,
            snapshot={"k": "the api_key=ABC123"},
        )
        assert ev.snapshot["k"] == "<redacted>"


class TestSessionTelemetryRecorder:

    def test_append_only(self):
        rec = SessionTelemetryRecorder(
            clock=lambda: NOW, operator_token="TOK",
        )
        rec.record("session_start")
        rec.record("cycle_start", cycle_idx=0)
        rec.record("session_end")
        assert len(rec.events) == 3
        # events is tuple (imutavel)
        import builtins
        assert isinstance(rec.events, tuple)

    def test_operator_token_sanitized_in_snapshot(self):
        rec = SessionTelemetryRecorder(
            clock=lambda: NOW, operator_token="VERYLONGSECRETOP",
        )
        rec.record("session_start")
        ev = rec.events[0]
        assert "operator_token_sanitized" in ev.snapshot
        # Token completo nunca aparece
        assert "VERYLONGSECRETOP" not in str(ev.snapshot)
        assert ev.snapshot["operator_token_sanitized"].endswith("...")

    def test_to_json_sanitized(self):
        rec = SessionTelemetryRecorder(
            clock=lambda: NOW, operator_token="OPSECRET123",
        )
        rec.record("session_start", snapshot={"data": "ok"})
        rec.record("api_failure", cycle_idx=0,
                   snapshot={"error_message": "the api_key=XYZ"})
        text = rec.to_json()
        # JSON sanitized
        assert "OPSECRET123" not in text
        assert "api_key=XYZ" not in text or "<redacted>" in text
        for tok in ("api_key", "api_secret", "bearer", "x-bapi",
                    "sign=", "authorization", "origin_string"):
            assert tok not in text.lower()

    def test_to_jsonl_one_line_per_event(self):
        rec = SessionTelemetryRecorder(
            clock=lambda: NOW, operator_token="TOK",
        )
        rec.record("session_start")
        rec.record("cycle_start", cycle_idx=0)
        rec.record("session_end")
        text = rec.to_jsonl()
        lines = [ln for ln in text.split("\n") if ln.strip()]
        assert len(lines) == 3
        # cada linha eh JSON valido
        for ln in lines:
            d = json.loads(ln)
            assert "event_type" in d

    def test_to_jsonl_file_rejects_dotdot(self, tmp_path):
        rec = SessionTelemetryRecorder(
            clock=lambda: NOW, operator_token="TOK",
        )
        rec.record("session_start")
        bad = str(tmp_path / ".." / "out.jsonl")
        with pytest.raises(ValueError, match="'\\.\\.'"):
            rec.to_jsonl_file(bad)

    def test_to_jsonl_file_writes_sanitized(self, tmp_path):
        # Token > 8 chars: deve aparecer apenas como primeiros 8 + "..."
        full_token = "OPSECRETVERYLONGTOKEN"
        rec = SessionTelemetryRecorder(
            clock=lambda: NOW, operator_token=full_token,
        )
        rec.record("session_start", snapshot={"strategy": "trend_pullback"})
        rec.record("cycle_start", cycle_idx=0)
        rec.record("session_end", snapshot={
            "verdict": "passed_zero_trades",
        })
        out_path = tmp_path / "telemetry.jsonl"
        rec.to_jsonl_file(str(out_path))
        assert out_path.exists()
        text = out_path.read_text(encoding="utf-8")
        for tok in ("api_key", "api_secret", "bearer", "x-bapi",
                    "sign=", "authorization", "origin_string"):
            assert tok not in text.lower()
        # Token completo NUNCA aparece (apenas forma sanitizada "OPSECRET...").
        assert full_token not in text
        assert "VERYLONGTOKEN" not in text

    def test_record_invalid_event_type_fallback_safe(self):
        rec = SessionTelemetryRecorder(
            clock=lambda: NOW, operator_token="TOK",
        )
        # Invalid event_type -> nao explode, registra fallback.
        rec.record("BOGUS_TYPE")
        assert len(rec.events) == 1
        assert rec.events[0].event_type == "api_failure"

    def test_overflow_protection(self):
        rec = SessionTelemetryRecorder(
            clock=lambda: NOW, operator_token="TOK", max_events=3,
        )
        for i in range(10):
            rec.record("cycle_start", cycle_idx=i)
        assert len(rec.events) == 3
        assert rec.overflow_count == 7

    def test_max_events_must_be_positive(self):
        with pytest.raises(ValueError):
            SessionTelemetryRecorder(
                clock=lambda: NOW, operator_token="TOK", max_events=0,
            )

    def test_short_token_padded_with_dots(self):
        rec = SessionTelemetryRecorder(
            clock=lambda: NOW, operator_token="ABC",
        )
        assert rec.operator_token_sanitized == "ABC..."

    def test_empty_token_marked(self):
        rec = SessionTelemetryRecorder(
            clock=lambda: NOW, operator_token="",
        )
        assert rec.operator_token_sanitized == "<empty>"


class TestModuleHasNoNetwork:

    def test_session_telemetry_module_no_network_imports(self):
        from pathlib import Path
        p = Path(__file__).parent.parent / "src" / "crypto_trading_bot" / \
            "demo_endurance" / "session_telemetry.py"
        src = p.read_text(encoding="utf-8")
        for tok in (
            "import httpx", "from httpx",
            "import requests", "from requests",
            "BybitClient(", "BybitDemoExecutor(",
            "BybitDemoPreflight(", "load_dotenv",
            "execute_demo_session_gated(",
        ):
            assert tok not in src, f"forbidden in session_telemetry: {tok}"
