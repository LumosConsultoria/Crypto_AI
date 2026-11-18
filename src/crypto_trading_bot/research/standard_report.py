"""
Standard Backtest Report (FASE 47.1) — conceito PADRONIZADO de "ganho".
========================================================================
Todo backtest produz um relatorio com TRES secoes + verdict de QUATRO eixos
+ TABELA MENSAL (sempre presente, mesmo quando a estrategia morre no DEV por
edge negativo — registramos o resumo temporal p/ diagnosticar se o problema
e estrutural, concentrado em poucos meses ou custo/funding).

1) strategy_metrics: gross PnL; net PnL (apos fees/spread/slippage/funding);
   PF liquido; expectancy liquida; max drawdown; win rate; nº de trades;
   media/mediana de ganho e perda.
2) temporal_breakdown: PnL diario/semanal/mensal; meses +/-; melhor/pior mes;
   maior sequencia de perdas; concentracao de lucro por dia/trade; TABELA
   MENSAL.
3) hyro_simulation: simulacao operacional HyroTrader 5k (reusa
   hyrotrader_eval) — capital 5000, risco base 0,5%/US$25, daily DD, max loss,
   session loss 1%, kill switch US$50, cooldown apos 2 perdas, leverage 1x,
   1 posicao, profit target, dias minimos, profit concentration.

Verdict (5 eixos SEPARADOS; NUNCA "aprovado" so porque PF>1):
   - edge_estatistico: aprovado | rejeitado
   - robustez_temporal: aprovado | rejeitado
   - hyro_challenge: passaria | falharia | pendente   (perfil HyroTrader 5k)
   - standard_trader: aprovado | rejeitado            (conta propria/padrao)
   - bot_completo_E: validado | pendente | rejeitado
+ classification: candidata_paper | edge_possivel_incompativel_com_challenge |
  sem_edge_operacional. Perfil Trader Padrao NAO libera demo/live.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence

from crypto_trading_bot.research.hyro_attempts import simulate_hyro_attempts
from crypto_trading_bot.research.hyrotrader_eval import (
    evaluate_hyrotrader_challenge,
)
from crypto_trading_bot.research.monthly_close import (
    standard_trader_monthly_close,
)
from crypto_trading_bot.research.perp_signals import funding_pnl_adjustment

# limiares (travados; reuso FASE 44). pf default conservador.
PF_THRESHOLD = 1.15
SIGN_CONSISTENCY_MIN = 0.60
CONCENTRATION_TOP_MAX = 0.50


def _utc(ts):
    if ts is None:
        return None
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    return ts.replace(tzinfo=timezone.utc) if getattr(ts, "tzinfo", None) \
        is None else ts


def _trade_rows(rep, funding_events):
    """Lista de (exit_time, net_pnl_incl_funding, gross_pnl, fees+slip)."""
    rows = []
    for t in (rep.trades or []):
        net = float(getattr(t, "pnl_usd", 0.0) or 0.0)
        fnd = funding_pnl_adjustment(
            getattr(t, "entry_time", None), getattr(t, "exit_time", None),
            notional_usd=float(getattr(t, "position_size_usd", 0.0) or 0.0),
            side=getattr(t, "side", "buy"), funding_events=funding_events or [])
        exo = _utc(getattr(t, "exit_time", None)) or _utc(
            getattr(t, "entry_time", None))
        rows.append({
            "exit_time": exo,
            "gross": float(getattr(t, "gross_pnl_usd", 0.0) or 0.0),
            "net_pre_funding": net,
            "funding": fnd,
            "net": net + fnd,
        })
    return rows


def _strategy_metrics(rep, rows) -> Dict[str, Any]:
    nets = [r["net"] for r in rows]
    gross = sum(r["gross"] for r in rows)
    funding = sum(r["funding"] for r in rows)
    net_pre = sum(r["net_pre_funding"] for r in rows)
    net = sum(nets)
    fees = float(getattr(rep, "total_fees_usd", 0.0) or 0.0)
    slip = float(getattr(rep, "total_slippage_usd", 0.0) or 0.0)
    wins = [p for p in nets if p > 0]
    losses = [p for p in nets if p < 0]
    n = len(nets)
    pf = (round(sum(wins) / -sum(losses), 4) if losses
          else (None if not wins else float("inf")))
    return {
        "gross_pnl_usd": round(gross, 4),
        "fees_usd": round(fees, 4),
        "slippage_spread_usd": round(slip, 4),
        "funding_usd": round(funding, 4),
        "net_pnl_usd_pre_funding": round(net_pre, 4),
        "net_pnl_usd": round(net, 4),
        "profit_factor_net": pf,
        "expectancy_net_usd": round(net / n, 4) if n else None,
        "max_drawdown_pct": getattr(rep, "max_drawdown_pct", None),
        "win_rate": round(len(wins) / n, 4) if n else None,
        "num_trades": n,
        "avg_win_usd": round(statistics.mean(wins), 4) if wins else None,
        "avg_loss_usd": round(statistics.mean(losses), 4) if losses else None,
        "median_win_usd": round(statistics.median(wins), 4) if wins else None,
        "median_loss_usd": round(statistics.median(losses), 4)
        if losses else None,
    }


def _period_key(dt, kind):
    if dt is None:
        return None
    if kind == "daily":
        return dt.date().isoformat()
    if kind == "weekly":
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return f"{dt.year}-{dt.month:02d}"


def _group(rows, kind):
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        k = _period_key(r["exit_time"], kind)
        if k is None:
            continue
        a = out.setdefault(k, {"pnl": 0.0, "trades": 0, "wins": 0})
        a["pnl"] += r["net"]
        a["trades"] += 1
        if r["net"] > 0:
            a["wins"] += 1
    return {k: {"pnl": round(v["pnl"], 4), "trades": v["trades"],
                "win_rate": round(v["wins"] / v["trades"], 4)
                if v["trades"] else None}
            for k, v in sorted(out.items())}


def _longest_losing_streak(rows) -> int:
    streak = best = 0
    for r in sorted(rows, key=lambda x: (x["exit_time"] or datetime.max
                                         .replace(tzinfo=timezone.utc))):
        if r["net"] < 0:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return best


def _concentration(rows) -> Dict[str, Any]:
    nets = [r["net"] for r in rows]
    wins = sorted([p for p in nets if p > 0], reverse=True)
    gross_win = sum(wins)
    top_trade = (round(wins[0] / gross_win, 4)
                 if wins and gross_win > 0 else None)
    daily = _group(rows, "daily")
    pos_days = {k: v["pnl"] for k, v in daily.items() if v["pnl"] > 0}
    total_pos = sum(pos_days.values())
    top_day = (round(max(pos_days.values()) / total_pos, 4)
               if pos_days and total_pos > 0 else None)
    return {"top_trade_share_of_gross_profit": top_trade,
            "top_day_share_of_positive_days": top_day}


def _temporal_breakdown(rows) -> Dict[str, Any]:
    monthly = _group(rows, "monthly")
    months = list(monthly.items())
    pos = [m for m, v in months if v["pnl"] > 0]
    neg = [m for m, v in months if v["pnl"] < 0]
    best = max(months, key=lambda kv: kv[1]["pnl"]) if months else None
    worst = min(months, key=lambda kv: kv[1]["pnl"]) if months else None
    sign_consistency = (round(len(pos) / len(months), 4) if months else None)
    total = sum(v["pnl"] for _, v in months)
    net_excl_best = round(total - (best[1]["pnl"] if best else 0.0), 4)
    return {
        "daily": _group(rows, "daily"),
        "weekly": _group(rows, "weekly"),
        "monthly_table": [{"month": m, **v} for m, v in months],
        "months_total": len(months),
        "months_positive": len(pos),
        "months_negative": len(neg),
        "sign_consistency": sign_consistency,
        "best_month": ({"month": best[0], **best[1]} if best else None),
        "worst_month": ({"month": worst[0], **worst[1]} if worst else None),
        "net_excluding_best_month_usd": net_excl_best,
        "longest_losing_streak_trades": _longest_losing_streak(rows),
        "profit_concentration": _concentration(rows),
    }


# gates do perfil TRADER PADRAO / CONTA PROPRIA (sem regras de challenge)
TRADER_PF_MIN = 1.15
TRADER_MAXDD_LIMIT = 25.0          # gate de aceite (maxDD tb e so metrica)
TRADER_SIGN_CONSISTENCY_MIN = 0.60


def _standard_trader_evaluation(strat, temporal, *, capital,
                                pf_min=TRADER_PF_MIN,
                                maxdd_limit=TRADER_MAXDD_LIMIT) -> Dict[str, Any]:
    """Perfil Trader Padrao / Conta Propria: SEM meta de 10%, SEM daily DD de
    challenge, SEM concentracao obrigatoria, SEM dias minimos. maxDD apenas
    como METRICA (+ gate de aceite). Foco: net PnL, PF, expectancy, maxDD,
    retorno/DD, estabilidade mensal, baixa concentracao (informativa)."""
    net = strat.get("net_pnl_usd") or 0.0
    pf = strat.get("profit_factor_net")
    exp = strat.get("expectancy_net_usd")
    maxdd = abs(strat.get("max_drawdown_pct") or 0.0)
    ret_pct = (net / capital * 100.0) if capital else 0.0
    if maxdd > 0:
        ret_over_dd = round(ret_pct / maxdd, 4)
        rod_ok = ret_over_dd > 0
    else:
        # sem drawdown: lucrativo => otimo (sem divisao por zero)
        ret_over_dd = None
        rod_ok = net > 0
    sc = temporal.get("sign_consistency")
    conc = (temporal.get("profit_concentration") or {}).get(
        "top_trade_share_of_gross_profit")
    gates = {
        "net_positive": net > 0,
        "pf_ok": pf is not None and pf >= pf_min,
        "expectancy_positive": exp is not None and exp > 0,
        "maxdd_acceptable": maxdd <= maxdd_limit,
        "return_over_dd_positive": rod_ok,
        "monthly_stability": sc is not None and sc >= TRADER_SIGN_CONSISTENCY_MIN,
    }
    verdict = "aprovado" if all(gates.values()) else "rejeitado"
    return {
        "profile": "standard_trader_own_account",
        "risk_base_pct": 0.005,
        "net_pnl_usd": round(net, 4),
        "profit_factor_net": pf,
        "expectancy_net_usd": exp,
        "max_drawdown_pct": strat.get("max_drawdown_pct"),
        "return_pct": round(ret_pct, 4),
        "return_over_dd": ret_over_dd,
        "monthly_sign_consistency": sc,
        "top_trade_concentration": conc,
        "gates": gates,
        "verdict": verdict,
        "note": ("Conta propria: maxDD so como metrica (+gate de aceite); SEM "
                 "meta 10%/daily-DD-challenge/concentracao-obrigatoria/dias-"
                 "minimos. NAO libera demo/live."),
    }


def _classification(hyro_axis: str, trader_axis: str) -> str:
    """Cruza Hyro Challenge x Trader Padrao (decisao do operador)."""
    if trader_axis != "aprovado":
        return "sem_edge_operacional"
    if hyro_axis == "passaria":
        return "candidata_paper"
    return "edge_possivel_incompativel_com_challenge"


def _verdicts(strat, temporal, hyro_verdict, *, pf_threshold,
              expectancy_ci, prospective_pending,
              standard_trader_verdict="rejeitado",
              hyro_attempts_verdict=None) -> Dict[str, str]:
    pf = strat.get("profit_factor_net")
    exp = strat.get("expectancy_net_usd")
    net = strat.get("net_pnl_usd") or 0.0
    ci_ok = True
    if expectancy_ci is not None:
        lo = expectancy_ci.get("ci_low")
        ci_ok = lo is not None and lo >= 0
    edge = ("aprovado" if (net > 0 and pf is not None and pf >= pf_threshold
                           and exp is not None and exp > 0 and ci_ok)
            else "rejeitado")
    sc = temporal.get("sign_consistency")
    conc = (temporal.get("profit_concentration") or {}).get(
        "top_trade_share_of_gross_profit")
    robust = ("aprovado" if (sc is not None and sc >= SIGN_CONSISTENCY_MIN
                             and (temporal.get("net_excluding_best_month_usd")
                                  or 0) >= 0
                             and (conc is None
                                  or conc < CONCENTRATION_TOP_MAX))
              else "rejeitado")
    hv = {"passaria_no_desafio": "passaria",
          "reprovaria_no_desafio": "falharia",
          "reprovaria_no_desafio_meta_nao_atingida": "falharia",
          "incompleto_controles_internos_ausentes": "pendente",
          "sem_trades": "pendente"}.get(hyro_verdict, "pendente")
    # leitura PRINCIPAL do Hyro = tentativas sequenciais (pass_rate), nao so o
    # segmento inteiro. Fallback ao mapeamento de segmento se nao houver.
    hyro_challenge = hyro_attempts_verdict or hv
    if edge == "rejeitado":
        bot_e = "rejeitado"
    elif prospective_pending:
        bot_e = "pendente"
    else:
        bot_e = "validado"
    # 5 eixos SEPARADOS (desafio_hyro renomeado p/ hyro_challenge; standard_
    # trader novo). Sem alias.
    return {"edge_estatistico": edge, "robustez_temporal": robust,
            "hyro_challenge": hyro_challenge,
            "standard_trader": standard_trader_verdict,
            "bot_completo_E": bot_e}


def build_standard_report(
    rep, *, capital: float = 5000.0, funding_events: Sequence = (),
    segment_label: str = "DEV",
    hyro_internal_controls: Optional[Mapping[str, Any]] = None,
    hyro_daily_drawdown_pct: float = 0.04, hyro_total_loss_pct: float = 0.06,
    hyro_max_duration_days: Optional[int] = None,
    pf_threshold: float = PF_THRESHOLD,
    expectancy_ci: Optional[Mapping[str, Any]] = None,
    prospective_pending: bool = True,
    risk_base_pct: float = 0.005,
    trader_pf_min: float = TRADER_PF_MIN,
    trader_maxdd_limit: float = TRADER_MAXDD_LIMIT,
) -> Dict[str, Any]:
    """Relatorio padronizado. Produz as 3 secoes + 4 verdicts + tabela mensal
    SEMPRE (mesmo sem edge / poucos trades)."""
    rows = _trade_rows(rep, funding_events)
    strat = _strategy_metrics(rep, rows)
    temporal = _temporal_breakdown(rows)
    # P6: o desafio HyroTrader usa net APOS fees+spread+slippage+FUNDING.
    # rep.trades.pnl_usd ja inclui fees+slippage; somamos o funding por trade.
    funded_trades = []
    for t in (rep.trades or []):
        fnd = funding_pnl_adjustment(
            getattr(t, "entry_time", None), getattr(t, "exit_time", None),
            notional_usd=float(getattr(t, "position_size_usd", 0.0) or 0.0),
            side=getattr(t, "side", "buy"), funding_events=funding_events or [])
        funded_trades.append({
            "entry_time": getattr(t, "entry_time", None),
            "exit_time": getattr(t, "exit_time", None),
            "pnl_usd": float(getattr(t, "pnl_usd", 0.0) or 0.0) + fnd,
            "stop_loss": getattr(t, "stop_loss_price",
                                 getattr(t, "stop_loss", None)),
        })
    hyro = evaluate_hyrotrader_challenge(
        funded_trades, capital=capital,
        daily_drawdown_pct=hyro_daily_drawdown_pct,
        total_loss_pct=hyro_total_loss_pct,
        internal_controls=hyro_internal_controls)
    hyro_d = hyro.to_dict()
    # profit target (KPI) + progresso
    target_usd = round(0.10 * capital, 2)
    hyro_d["profit_target_usd"] = target_usd
    hyro_d["profit_target_progress_pct"] = (
        round((strat["net_pnl_usd"] / target_usd) * 100, 2)
        if target_usd else None)
    # leitura PRINCIPAL do Hyro: MULTIPLAS tentativas sequenciais (FASE 54).
    hyro_attempts = simulate_hyro_attempts(
        funded_trades, capital=capital,
        daily_drawdown_pct=hyro_daily_drawdown_pct,
        total_loss_pct=hyro_total_loss_pct,
        internal_controls=hyro_internal_controls,
        max_duration_days=hyro_max_duration_days)
    # leitura PRINCIPAL do Trader Padrao: fechamento MENSAL (FASE 54).
    monthly_close = standard_trader_monthly_close(rows, capital=capital)
    # Perfil 2 — Trader Padrao / Conta Propria (MESMOS trades; sem regras de
    # challenge). risco 0,5% primario (1% e analise separada no orquestrador).
    trader_eval = _standard_trader_evaluation(
        strat, temporal, capital=capital, pf_min=trader_pf_min,
        maxdd_limit=trader_maxdd_limit)
    trader_eval["risk_base_pct"] = round(risk_base_pct, 6)
    verdicts = _verdicts(strat, temporal, hyro_d.get("challenge_verdict"),
                         pf_threshold=pf_threshold, expectancy_ci=expectancy_ci,
                         prospective_pending=prospective_pending,
                         standard_trader_verdict=trader_eval["verdict"],
                         hyro_attempts_verdict=hyro_attempts.get(
                             "hyro_attempts_verdict"))
    classification = _classification(verdicts["hyro_challenge"],
                                     verdicts["standard_trader"])
    return {
        "schema": "standard_backtest_report_v2",
        "segment": segment_label,
        "capital_usd": capital,
        "risk_base_pct": round(risk_base_pct, 6),
        "risk_base_usd": round(risk_base_pct * capital, 2),
        "strategy_metrics": strat,
        "temporal_breakdown": temporal,
        "hyro_simulation": hyro_d,
        "hyro_challenge_attempts": hyro_attempts,
        "standard_trader_evaluation": trader_eval,
        "standard_trader_monthly_close": monthly_close,
        "verdict": verdicts,
        "classification": classification,
        "standard_trader_unlocks_execution": False,
        "note": ("'ganho' padronizado: net inclui fees+spread+slippage+funding;"
                 " avaliacao em DOIS perfis (hyro_challenge + standard_trader);"
                 " 5 verdicts separados (NUNCA aprovado so por PF>1); tabela"
                 " mensal sempre; HyroTrader=perfil principal; Trader Padrao"
                 " NAO libera demo/live."),
    }


__all__ = ["build_standard_report", "PF_THRESHOLD", "TRADER_PF_MIN",
           "TRADER_MAXDD_LIMIT"]
