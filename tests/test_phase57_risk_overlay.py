"""
FASE 57 — Risk & Exposure Overlay (alternativa C, NAO-preditivo, advisory).
100% OFFLINE, deterministico. Verifica cada regra de alerta, agregados de
exposicao, status e invariantes (sem ordem; demo/live bloqueados). Sem rede.
"""

from __future__ import annotations

from crypto_trading_bot.risk_overlay import (
    AccountState, Position, RiskLimits, evaluate_risk_overlay)

_LIM = RiskLimits(capital_usd=5000.0, max_risk_per_trade_pct=0.005,
                  max_daily_loss_pct=0.04, max_total_loss_pct=0.06,
                  max_exposure_pct=1.0, max_leverage=1.0, max_open_positions=1,
                  min_stop_loss_pct=0.005)


def _codes(rep):
    return {a["code"] for a in rep["alerts"]}


def test_flat_account_ok():
    rep = evaluate_risk_overlay(
        AccountState(equity_usd=5000, balance_usd=5000), [], _LIM)
    assert rep["overall_status"] == "flat_ok"
    assert rep["alerts"] == []
    assert rep["orders_emitted"] == 0
    assert rep["real_execution_allowed"] is False
    assert rep["demo_blocked"] and rep["live_blocked"]


def test_position_without_stop_loss():
    p = Position("BTCUSDT", "long", notional_usd=1000, entry_price=60000,
                 mark_price=60000, stop_loss_price=None)
    rep = evaluate_risk_overlay(
        AccountState(equity_usd=5000, balance_usd=5000), [p], _LIM)
    assert "position_no_stop_loss" in _codes(rep)
    assert rep["overall_status"] in ("action_required", "action_required_critical")


def test_stop_below_floor():
    # SL a 0,2% < piso 0,5%
    p = Position("BTCUSDT", "long", 1000, 60000, 60000,
                 stop_loss_price=60000 * (1 - 0.002))
    rep = evaluate_risk_overlay(
        AccountState(equity_usd=5000, balance_usd=5000), [p], _LIM)
    assert "position_stop_below_floor" in _codes(rep)


def test_risk_per_trade_exceeded_and_target_notional():
    # SL 2% e notional 5000 => risco US$100 > cap US$25
    p = Position("BTCUSDT", "long", 5000, 60000, 60000,
                 stop_loss_price=60000 * (1 - 0.02))
    rep = evaluate_risk_overlay(
        AccountState(equity_usd=5000, balance_usd=5000), [p], _LIM)
    al = next(a for a in rep["alerts"]
              if a["code"] == "position_risk_per_trade_exceeded")
    assert al["evidence"]["risk_to_stop_usd"] == 100.0
    # alvo: risco 25 / 2% = notional 1250
    assert al["evidence"]["target_notional_usd"] == 1250.0


def test_exposure_and_leverage_over_cap():
    # notional 6000 > capital 5000 (exposure>100%) e equity 5000 => lev 1,2x
    p = Position("BTCUSDT", "long", 6000, 60000, 60000,
                 stop_loss_price=60000 * (1 - 0.01))
    rep = evaluate_risk_overlay(
        AccountState(equity_usd=5000, balance_usd=5000), [p], _LIM)
    assert "exposure_over_cap" in _codes(rep)
    assert "leverage_over_cap" in _codes(rep)
    ex = next(a for a in rep["alerts"] if a["code"] == "exposure_over_cap")
    assert ex["evidence"]["reduce_notional_usd"] == 1000.0


def test_too_many_positions():
    ps = [Position(f"S{i}", "long", 100, 100, 100,
                   stop_loss_price=99.5) for i in range(2)]
    rep = evaluate_risk_overlay(
        AccountState(equity_usd=5000, balance_usd=5000), ps, _LIM)
    assert "too_many_positions" in _codes(rep)


def test_daily_loss_warning_and_breach():
    # warning: perda do dia = 80% de 200 = 160
    rep_w = evaluate_risk_overlay(
        AccountState(equity_usd=4840, balance_usd=5000,
                     realized_pnl_today_usd=-160), [], _LIM)
    assert "daily_loss_warning" in _codes(rep_w)
    # breach: perda do dia 250 >= 200
    rep_b = evaluate_risk_overlay(
        AccountState(equity_usd=4750, balance_usd=5000,
                     realized_pnl_today_usd=-250), [], _LIM)
    assert "daily_loss_breached" in _codes(rep_b)
    assert rep_b["overall_status"] == "action_required_critical"


def test_equity_floor_breached():
    # equity 4700 <= floor 4700 (6% de 5000)
    rep = evaluate_risk_overlay(
        AccountState(equity_usd=4700, balance_usd=4700), [], _LIM)
    assert "equity_floor_breached" in _codes(rep)


def test_funding_bleed_advisory():
    # long pagando funding>0 notavel
    p = Position("BTCUSDT", "long", 10000, 60000, 60000,
                 stop_loss_price=60000 * (1 - 0.01), funding_rate=0.0005)
    rep = evaluate_risk_overlay(
        AccountState(equity_usd=5000, balance_usd=5000), [p], _LIM)
    fb = next(a for a in rep["alerts"] if a["code"] == "position_funding_bleed")
    assert fb["severity"] == "low"
    assert fb["evidence"]["funding_cost_per_event_usd"] == 5.0


def test_exposure_summary_numbers():
    p = Position("BTCUSDT", "long", 1000, 60000, 60000,
                 stop_loss_price=60000 * (1 - 0.01))
    rep = evaluate_risk_overlay(
        AccountState(equity_usd=5000, balance_usd=5000), [p], _LIM)
    es = rep["exposure_summary"]
    assert es["total_notional_usd"] == 1000.0
    assert es["exposure_pct"] == 0.2
    assert es["total_risk_to_stop_usd"] == 10.0     # 1% de 1000
