"""
FASE 47 — hyrotrader_eval: overlay de relatorio do desafio HyroTrader.
100% OFFLINE, deterministico. DD diario trailing (reset UTC), perda total/
equity min, concentracao <=40%/dia, min 5 dias, stop obrigatorio + controles
internos (2 perdas=>cooldown 15min, kill switch US$50, session loss
not_supported). Verdict "passaria" NUNCA ignora controles ausentes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from crypto_trading_bot.research.hyrotrader_eval import (
    evaluate_hyrotrader_challenge,
)

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _t(day, hour, pnl, *, minute=0, with_stop=True):
    ein = _D0 + timedelta(days=day, hours=hour, minutes=minute)
    exo = ein + timedelta(minutes=30)
    return {"entry_time": ein, "exit_time": exo, "pnl_usd": float(pnl),
            "stop_loss": 100.0 if with_stop else None}


class TestExternalRules:

    def test_daily_trailing_drawdown_breach(self):
        # dia 0: +100 (pico 5100), depois -250 => drop 250 do pico > 200
        trades = [_t(0, 1, 100.0), _t(0, 2, -250.0)]
        rep = evaluate_hyrotrader_challenge(trades, capital=5000.0)
        dd = rep.to_dict()["external_rules"]["daily_drawdown_trailing"]
        assert dd["breached"] is True
        assert dd["worst_daily_drawdown_usd"] >= 200.0

    def test_daily_drawdown_resets_per_utc_day(self):
        # -150 no dia 0 e -150 no dia 1: nenhum dia isolado cruza 200
        trades = [_t(0, 1, -150.0), _t(1, 1, -150.0)]
        rep = evaluate_hyrotrader_challenge(trades, capital=5000.0)
        dd = rep.to_dict()["external_rules"]["daily_drawdown_trailing"]
        assert dd["breached"] is False

    def test_total_loss_min_equity_breach(self):
        # perda acumulada leva equity <= 4700
        trades = [_t(d, 1, -120.0) for d in range(6)]   # -720 => 4280
        rep = evaluate_hyrotrader_challenge(trades, capital=5000.0)
        tl = rep.to_dict()["external_rules"]["total_loss"]
        assert tl["breached"] is True
        assert tl["min_equity_reached_usd"] <= 4700.0

    def test_concentration_breach(self):
        # dia 0 = +500; dias 1-4 = +10 cada => dia 0 domina (>40%)
        trades = [_t(0, 1, 500.0)] + [_t(d, 1, 10.0) for d in range(1, 5)]
        rep = evaluate_hyrotrader_challenge(trades, capital=5000.0)
        conc = rep.to_dict()["external_rules"]["concentration"]
        assert conc["breached"] is True
        assert conc["max_day_share"] > 0.40

    def test_min_days(self):
        trades = [_t(d, 1, 5.0) for d in range(3)]   # 3 dias < 5
        rep = evaluate_hyrotrader_challenge(trades, capital=5000.0)
        md = rep.to_dict()["external_rules"]["min_days"]
        assert md["ok"] is False and md["observed"] == 3

    def test_mandatory_stop_status(self):
        trades = [_t(d, 1, 5.0, with_stop=True) for d in range(5)]
        rep = evaluate_hyrotrader_challenge(trades, capital=5000.0)
        ms = rep.to_dict()["external_rules"]["mandatory_stop"]
        assert ms["status"] == "all_trades_have_stop"


class TestInternalControls:

    def test_consecutive_losses_cooldown_blocks(self):
        # 2 perdas seguidas no dia 0; 3a entrada 5min depois => bloqueada
        trades = [_t(0, 1, -10.0, minute=0), _t(0, 1, -10.0, minute=40),
                  _t(0, 1, 50.0, minute=75)]
        rep = evaluate_hyrotrader_challenge(
            trades, capital=5000.0,
            internal_controls={"consecutive_losses": 2,
                               "cooldown_minutes": 15})
        ic = rep.to_dict()["internal_controls"]
        assert ic["consecutive_losses_cooldown"]["status"] == "simulated"
        assert ic["consecutive_losses_cooldown"]["would_be_blocked_trades"] \
            >= 1

    def test_kill_switch_blocks_rest_of_day(self):
        # dia 0: -60 (>50) => kill; trade seguinte no dia bloqueado
        trades = [_t(0, 1, -60.0, minute=0), _t(0, 1, 20.0, minute=40)]
        rep = evaluate_hyrotrader_challenge(
            trades, capital=5000.0,
            internal_controls={"kill_switch_usd": 50.0})
        ks = rep.to_dict()["internal_controls"]["kill_switch"]
        assert ks["would_be_blocked_trades"] >= 1

    def test_session_loss_simulated(self):
        trades = [_t(d, 1, 5.0) for d in range(5)]
        rep = evaluate_hyrotrader_challenge(trades, capital=5000.0)
        ic = rep.to_dict()["internal_controls"]
        assert ic["session_loss"]["status"] == "simulated"
        assert ic["session_loss"]["pct"] == 0.01

    def test_session_loss_blocks_rest_of_day(self):
        # dia 0: -60 (>1% de 5000=50) => sessao bloqueada; trade seguinte
        # no mesmo dia e bloqueado
        trades = [_t(0, 1, -60.0, minute=0), _t(0, 1, 20.0, minute=40)]
        rep = evaluate_hyrotrader_challenge(trades, capital=5000.0)
        sl = rep.to_dict()["internal_controls"]["session_loss"]
        assert sl["would_be_blocked_trades"] >= 1


class TestVerdict:

    def test_passes_only_when_profit_target_reached(self):
        # sobrevive E ATINGE a meta (>=10%/500): 6 dias x +100 = +600.
        trades = [_t(d, 1, 100.0) for d in range(6)]
        d = evaluate_hyrotrader_challenge(trades, capital=5000.0).to_dict()
        assert d["challenge_verdict"] == "passaria_no_desafio"
        assert d["external_rules"]["profit_target"]["reached"] is True
        assert d["enforcement_map"]["session_loss_1pct"] == "simulated_overlay"

    def test_survives_but_below_target_is_meta_nao_atingida(self):
        # sobrevive (sem breach) mas net +60 < meta 500 => NAO passa o desafio
        trades = [_t(d, 1, 10.0) for d in range(6)]
        d = evaluate_hyrotrader_challenge(trades, capital=5000.0).to_dict()
        assert d["challenge_verdict"] == \
            "reprovaria_no_desafio_meta_nao_atingida"
        assert d["external_rules"]["profit_target"]["reached"] is False

    def test_breach_is_reprovaria_or_incompleto(self):
        # com breach de DD, nunca 'passaria'
        trades = [_t(0, 1, 100.0), _t(0, 2, -300.0)] + \
                 [_t(d, 1, 5.0) for d in range(1, 6)]
        rep = evaluate_hyrotrader_challenge(trades, capital=5000.0)
        assert rep.to_dict()["challenge_verdict"] != "passaria_no_desafio"

    def test_no_trades(self):
        rep = evaluate_hyrotrader_challenge([], capital=5000.0)
        assert rep.to_dict()["challenge_verdict"] == "sem_trades"
