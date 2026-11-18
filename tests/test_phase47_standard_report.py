"""
FASE 47.1 — standard_report: conceito PADRONIZADO de "ganho". 100% OFFLINE.
3 secoes (estrategia/temporal/hyro) + verdict 4 eixos + TABELA MENSAL sempre
presente (inclusive DEV sem edge). net inclui fees/spread/slippage/funding.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from crypto_trading_bot.research.standard_report import build_standard_report

_D0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _trade(day, pnl, *, gross=None, size=2500.0, side="buy"):
    ein = _D0 + timedelta(days=day, hours=1)
    return SimpleNamespace(
        entry_time=ein, exit_time=ein + timedelta(minutes=30),
        pnl_usd=float(pnl), gross_pnl_usd=float(gross if gross is not None
                                                else pnl + 1.0),
        position_size_usd=size, side=side, stop_loss_price=100.0)


def _rep(trades, *, fees=10.0, slippage=5.0, dd=-3.0):
    return SimpleNamespace(
        trades=trades, total_fees_usd=fees, total_slippage_usd=slippage,
        max_drawdown_pct=dd, total_trades=len(trades),
        win_rate=None, profit_factor=None, expectancy_usd=None,
        avg_win_usd=None, avg_loss_usd=None, final_capital=5000.0,
        total_pnl_usd=sum(t.pnl_usd for t in trades))


class TestStrategyMetrics:

    def test_sections_present(self):
        trades = [_trade(d, 10.0) for d in range(5)] + \
                 [_trade(d, -6.0) for d in range(40, 45)]
        r = build_standard_report(_rep(trades), capital=5000.0)
        for sec in ("strategy_metrics", "temporal_breakdown",
                    "hyro_simulation", "verdict"):
            assert sec in r
        sm = r["strategy_metrics"]
        for k in ("gross_pnl_usd", "net_pnl_usd", "funding_usd",
                  "profit_factor_net", "expectancy_net_usd",
                  "max_drawdown_pct", "win_rate", "num_trades",
                  "avg_win_usd", "avg_loss_usd", "median_win_usd",
                  "median_loss_usd"):
            assert k in sm

    def test_net_includes_costs_and_funding(self):
        # sem funding events => funding_usd 0; net == soma pnl_usd
        trades = [_trade(0, 10.0), _trade(1, -4.0)]
        r = build_standard_report(_rep(trades), capital=5000.0)
        sm = r["strategy_metrics"]
        assert sm["funding_usd"] == 0.0
        assert sm["net_pnl_usd"] == 6.0
        assert sm["num_trades"] == 2


class TestTemporalBreakdown:

    def test_monthly_table_always_present(self):
        trades = [_trade(d, 5.0) for d in range(0, 90, 10)]
        r = build_standard_report(_rep(trades), capital=5000.0)
        tb = r["temporal_breakdown"]
        assert isinstance(tb["monthly_table"], list)
        assert tb["months_total"] >= 1
        assert tb["best_month"] is not None and tb["worst_month"] is not None
        assert "daily" in tb and "weekly" in tb

    def test_longest_losing_streak(self):
        trades = [_trade(0, 5.0), _trade(1, -1.0), _trade(2, -1.0),
                  _trade(3, -1.0), _trade(4, 2.0)]
        r = build_standard_report(_rep(trades), capital=5000.0)
        assert r["temporal_breakdown"]["longest_losing_streak_trades"] == 3

    def test_concentration_fields(self):
        trades = [_trade(0, 100.0)] + [_trade(d, 2.0) for d in range(1, 6)]
        c = build_standard_report(_rep(trades), capital=5000.0)[
            "temporal_breakdown"]["profit_concentration"]
        assert c["top_trade_share_of_gross_profit"] is not None


class TestDevDeadStillReportsTemporal:

    def test_negative_edge_dev_keeps_temporal_summary(self):
        # estrategia MORRE no DEV (so perdas) -> ainda assim tabela mensal +
        # resumo temporal presentes (diagnostico estrutural/concentracao/custo)
        trades = [_trade(d, -3.0) for d in range(0, 120, 5)]  # ~4 meses
        r = build_standard_report(_rep(trades), capital=5000.0,
                                  segment_label="DEV")
        tb = r["temporal_breakdown"]
        assert len(tb["monthly_table"]) >= 3        # varios meses registrados
        assert tb["months_negative"] >= 3
        assert r["verdict"]["edge_estatistico"] == "rejeitado"
        # resumo temporal util mesmo sem edge
        assert tb["worst_month"] is not None


class TestHyroUsesFunding:

    def test_funding_changes_hyro_daily_drawdown(self):
        # net (-150) sozinho NAO estoura daily DD (200); com funding (-100)
        # o net total (-250) ESTOURA => desafio_hyro deve refletir funding.
        from crypto_trading_bot.research.perp_signals import TimePoint
        ev = [TimePoint(_D0 + timedelta(days=0, hours=2), 0.001)]  # rate 0,1%
        t = SimpleNamespace(
            entry_time=_D0 + timedelta(hours=1),
            exit_time=_D0 + timedelta(hours=3),
            pnl_usd=-150.0, gross_pnl_usd=-150.0,
            position_size_usd=100000.0, side="buy")
        # sem funding
        r0 = build_standard_report(_rep([t]), capital=5000.0,
                                   funding_events=[])
        dd0 = r0["hyro_simulation"]["external_rules"][
            "daily_drawdown_trailing"]["breached"]
        # com funding (long paga 0,1%*100000 = -100 => net -250)
        r1 = build_standard_report(_rep([t]), capital=5000.0,
                                   funding_events=ev)
        dd1 = r1["hyro_simulation"]["external_rules"][
            "daily_drawdown_trailing"]["breached"]
        assert dd0 is False and dd1 is True   # funding entra no desafio_hyro
        assert r1["hyro_simulation"]["enforcement_map"][
            "daily_drawdown_trailing_intraday"] == "simulated_overlay"


class TestVerdictFiveAxes:

    def test_five_axes_present_and_valid(self):
        trades = [_trade(d, 5.0) for d in range(6)]
        r = build_standard_report(_rep(trades), capital=5000.0)
        v = r["verdict"]
        assert set(v) == {"edge_estatistico", "robustez_temporal",
                          "hyro_challenge", "standard_trader",
                          "bot_completo_E"}
        assert v["edge_estatistico"] in ("aprovado", "rejeitado")
        assert v["hyro_challenge"] in ("passaria", "falharia", "pendente",
                                       "fraco_instavel")
        assert v["standard_trader"] in ("aprovado", "rejeitado")
        assert v["bot_completo_E"] in ("validado", "pendente", "rejeitado")
        # dual-profile presente + classification + Trader Padrao nao libera exec
        assert "standard_trader_evaluation" in r
        assert r["classification"] in (
            "candidata_paper", "edge_possivel_incompativel_com_challenge",
            "sem_edge_operacional")
        assert r["standard_trader_unlocks_execution"] is False

    def test_not_approved_just_because_pf_gt_1(self):
        # PF>1 mas concentrado/poucos meses => robustez pode reprovar; e
        # bot_completo_E nunca 'validado' se prospective_pending=True
        trades = [_trade(0, 100.0)] + [_trade(1, 1.0)]
        v = build_standard_report(_rep(trades), capital=5000.0,
                                  prospective_pending=True)["verdict"]
        assert v["bot_completo_E"] in ("pendente", "rejeitado")


class TestDualProfileClassification:

    def test_sem_edge_operacional_when_losing(self):
        # perdedora => reprova no Trader Padrao (perfil mais frouxo)
        trades = [_trade(d, -5.0) for d in range(6)]
        r = build_standard_report(_rep(trades), capital=5000.0)
        assert r["verdict"]["standard_trader"] == "rejeitado"
        assert r["classification"] == "sem_edge_operacional"

    def test_edge_possivel_incompativel_quando_lucra_mas_nao_bate_meta(self):
        # lucrativa e robusta, MAS net +60 < meta 10% (500) => hyro falha,
        # Trader Padrao aprova => edge_possivel_incompativel_com_challenge
        trades = [_trade(d, 10.0) for d in range(6)]   # +60 < 500
        r = build_standard_report(_rep(trades), capital=5000.0)
        assert r["verdict"]["hyro_challenge"] == "falharia"
        assert r["verdict"]["standard_trader"] == "aprovado"
        assert r["classification"] == \
            "edge_possivel_incompativel_com_challenge"

    def test_candidata_paper_quando_passa_nos_dois(self):
        # +600 >= meta 500, sobrevive regras Hyro E gates Trader Padrao
        trades = [_trade(d, 100.0) for d in range(6)]
        r = build_standard_report(_rep(trades), capital=5000.0)
        assert r["verdict"]["hyro_challenge"] == "passaria"
        assert r["verdict"]["standard_trader"] == "aprovado"
        assert r["classification"] == "candidata_paper"

    def test_standard_trader_uses_own_gates_no_target(self):
        ste = build_standard_report(
            _rep([_trade(d, 10.0) for d in range(6)]),
            capital=5000.0)["standard_trader_evaluation"]
        # SEM meta de 10% nos gates do Trader Padrao
        assert "profit_target" not in str(ste["gates"])
        assert ste["verdict"] == "aprovado"
        assert ste["max_drawdown_pct"] is not None   # maxDD como metrica
