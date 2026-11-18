"""
FASE 54 — ajuste metodologico do standard_report:
- hyro_challenge_attempts: simulacao de MULTIPLAS tentativas sequenciais (Hyro).
- standard_trader_monthly_close: fechamento MENSAL (Trader Padrao).
100% OFFLINE, deterministico. Thresholds do verdict EXPLICITOS e testados.
Sem rede/ordem.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from crypto_trading_bot.research.hyro_attempts import simulate_hyro_attempts
from crypto_trading_bot.research.monthly_close import (
    standard_trader_monthly_close)
from crypto_trading_bot.research.standard_report import build_standard_report

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _ft(day, pnl, hours=1):
    ein = _D0 + timedelta(days=day, hours=hours)
    return {"entry_time": ein, "exit_time": ein + timedelta(minutes=30),
            "pnl_usd": float(pnl), "stop_loss": 100.0}


class TestHyroAttempts:

    def test_no_trades_pendente(self):
        r = simulate_hyro_attempts([])
        assert r["total_attempts"] == 0
        assert r["hyro_attempts_verdict"] == "pendente"

    def test_losing_all_attempts_fail(self):
        # so perdas => nenhuma tentativa passa => falharia
        trades = [_ft(d, -20.0) for d in range(30)]
        r = simulate_hyro_attempts(trades)
        assert r["passed_attempts"] == 0
        assert r["hyro_attempts_verdict"] == "falharia"
        assert r["failure_reasons"]                      # algum motivo contado

    def test_winning_attempt_passes_target_and_min_days(self):
        # +120/dia por 6 dias => +720 cruza meta 500 com >=5 dias distintos
        trades = [_ft(d, 120.0) for d in range(6)]
        r = simulate_hyro_attempts(trades)
        assert r["passed_attempts"] >= 1
        a0 = r["attempts"][0]
        assert a0["status"] == "passed"
        assert a0["days_traded"] >= 5
        assert a0["failure_or_success_reason"] == "profit_target_reached"
        assert r["hyro_attempts_verdict"] in ("passaria", "fraco_instavel")

    def test_daily_drawdown_terminates_attempt(self):
        # grande perda num dia estoura daily DD (4% de 5000 = 200)
        trades = [_ft(0, 50.0), _ft(1, -250.0), _ft(2, 50.0)]
        r = simulate_hyro_attempts(trades)
        assert any(a["failure_or_success_reason"] == "daily_drawdown"
                   for a in r["attempts"])

    def test_pass_rate_threshold_explicit(self):
        from crypto_trading_bot.research.hyro_attempts import PASS_RATE_STRONG
        assert PASS_RATE_STRONG == 0.50


class TestMonthlyClose:

    def _rows(self, items):
        # rows no formato de _trade_rows: exit_time, gross, net_pre_funding,
        # funding, net
        out = []
        for day, net in items:
            out.append({"exit_time": _D0 + timedelta(days=day),
                        "gross": net + 1.0, "net_pre_funding": net,
                        "funding": 0.0, "net": float(net)})
        return out

    def test_monthly_rows_and_consolidated(self):
        # jan: +100 ; fev: -40 ; mar: +60
        rows = self._rows([(1, 100.0), (35, -40.0), (65, 60.0)])
        mc = standard_trader_monthly_close(rows, capital=5000.0)
        assert mc["total_months"] == 3
        assert mc["positive_months"] == 2 and mc["negative_months"] == 1
        assert mc["positive_month_rate"] == round(2 / 3, 4)
        first = mc["monthly"][0]
        for k in ("month", "start_equity", "end_equity", "net_pnl_usd",
                  "net_return_pct", "gross_pnl_usd", "fees_slippage_spread_usd",
                  "funding_usd", "number_of_trades", "win_rate",
                  "max_drawdown_month_pct", "positive_month"):
            assert k in first
        assert first["start_equity"] == 5000.0
        assert mc["cumulative_net_pnl"] == 120.0
        assert mc["longest_negative_month_streak"] == 1

    def test_equity_chains_across_months(self):
        rows = self._rows([(1, 100.0), (35, 100.0)])
        mc = standard_trader_monthly_close(rows, capital=5000.0)
        assert mc["monthly"][0]["end_equity"] == 5100.0
        assert mc["monthly"][1]["start_equity"] == 5100.0


class TestIntegratedInStandardReport:

    def test_new_sections_present_and_verdict_uses_attempts(self):
        trades = [SimpleNamespace(
            entry_time=_D0 + timedelta(days=d, hours=1),
            exit_time=_D0 + timedelta(days=d, hours=1, minutes=30),
            pnl_usd=120.0, gross_pnl_usd=121.0, position_size_usd=2500.0,
            side="buy", stop_loss_price=100.0) for d in range(6)]
        rep = SimpleNamespace(
            trades=trades, total_fees_usd=6.0, total_slippage_usd=3.0,
            max_drawdown_pct=-2.0, total_trades=6)
        r = build_standard_report(rep, capital=5000.0)
        assert "hyro_challenge_attempts" in r
        assert "standard_trader_monthly_close" in r
        att = r["hyro_challenge_attempts"]
        # verdict hyro_challenge == verdict das tentativas (leitura principal)
        assert r["verdict"]["hyro_challenge"] == att["hyro_attempts_verdict"]
        assert att["total_attempts"] >= 1
