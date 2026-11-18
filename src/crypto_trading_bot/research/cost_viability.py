"""
Cost Viability Diagnosis (FASE 48) — custo minimo p/ uma estrategia ser viavel.
================================================================================
Antes de testar familias novas, diagnostica o CUSTO de execucao em termos de
RISCO por trade (R), respondendo:
  - Qual custo round-trip (% do notional)?
  - Para um dado stop, qual o custo em R por trade (cost_in_r)?
  - Qual edge bruto MINIMO (em R) para superar custos?
  - Qual stop minimo p/ o custo cair abaixo de um alvo (ex.: 0,10R)?
  - Empirico: dado um conjunto de trades, gross/trade vs cost/trade vs edge.

Insight central (FASE 47): com sizing por risco (notional = risco/stop_dist),
o custo round-trip e % FIXO do NOTIONAL, entao:
    cost_in_R = round_trip_pct / stop_dist_pct
=> stop pequeno => notional grande => custo e fracao GRANDE do risco.
Stops maiores (horizonte maior) reduzem o custo em R e viabilizam o edge.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


def round_trip_cost_pct(*, taker_fee_pct: float, slippage_pct: float,
                        spread_pct: float, sides: int = 2) -> float:
    """Custo round-trip como fracao do notional (entrada+saida)."""
    return sides * (taker_fee_pct + slippage_pct + spread_pct)


def cost_in_r(stop_dist_pct: float, round_trip_pct: float) -> Optional[float]:
    """Custo por trade em multiplos de R (risco). cost_in_R =
    round_trip_pct / stop_dist_pct (independe do capital/risco_base)."""
    if stop_dist_pct is None or stop_dist_pct <= 0:
        return None
    return round(round_trip_pct / stop_dist_pct, 4)


def min_stop_for_cost_in_r(round_trip_pct: float,
                           target_cost_in_r: float) -> float:
    """Stop minimo (fracao) p/ o custo por trade <= target_cost_in_r."""
    if target_cost_in_r <= 0:
        return float("inf")
    return round(round_trip_pct / target_cost_in_r, 6)


def viability_table(*, round_trip_pct: float, risk_base_usd: float,
                    stops: Sequence[float] = (0.005, 0.01, 0.02, 0.03,
                                              0.05)) -> List[Dict[str, Any]]:
    """Por stop: notional, custo USD/trade, custo em R, edge bruto minimo."""
    out = []
    for s in stops:
        notional = risk_base_usd / s
        cost_usd = round_trip_pct * notional
        cir = cost_in_r(s, round_trip_pct)
        out.append({
            "stop_dist_pct": s,
            "notional_usd": round(notional, 2),
            "cost_usd_per_trade": round(cost_usd, 4),
            "cost_in_r": cir,
            "min_gross_edge_r_to_break_even": cir,
        })
    return out


def max_trades_for_budget(*, daily_loss_limit_usd: float,
                          cost_usd_per_trade: float) -> Optional[int]:
    """Nº maximo de trades perdedores de custo puro antes de bater o limite
    diario (ordem de grandeza p/ frequencia maxima sustentavel)."""
    if cost_usd_per_trade <= 0:
        return None
    return int(daily_loss_limit_usd // cost_usd_per_trade)


def diagnose_from_trades(trades: Sequence, *, round_trip_pct: float,
                         risk_base_usd: float = 25.0) -> Dict[str, Any]:
    """Diagnostico EMPIRICO a partir de trades reais (objetos com
    position_size_usd, gross_pnl_usd, pnl_usd)."""
    n = len(trades or [])
    if n == 0:
        return {"trades": 0, "note": "sem trades"}
    notionals, costs, gross, net = [], [], [], []
    for t in trades:
        notional = float(getattr(t, "position_size_usd", 0.0) or 0.0)
        g = float(getattr(t, "gross_pnl_usd", 0.0) or 0.0)
        p = float(getattr(t, "pnl_usd", 0.0) or 0.0)
        notionals.append(notional)
        costs.append(round_trip_pct * notional)
        gross.append(g)
        net.append(p)
    avg_notional = sum(notionals) / n
    avg_cost = sum(costs) / n
    avg_gross = sum(gross) / n
    avg_net = sum(net) / n
    gross_in_r = avg_gross / risk_base_usd if risk_base_usd else None
    cost_in_r_emp = avg_cost / risk_base_usd if risk_base_usd else None
    return {
        "trades": n,
        "avg_notional_usd": round(avg_notional, 2),
        "avg_cost_usd_per_trade": round(avg_cost, 4),
        "avg_gross_pnl_usd_per_trade": round(avg_gross, 4),
        "avg_net_pnl_usd_per_trade": round(avg_net, 4),
        "gross_edge_in_r": round(gross_in_r, 4) if gross_in_r is not None
        else None,
        "cost_in_r": round(cost_in_r_emp, 4) if cost_in_r_emp is not None
        else None,
        "viable": (avg_gross > avg_cost),
        "diagnosis": ("edge bruto > custo" if avg_gross > avg_cost
                      else "CUSTO destroi o edge: gross/trade < custo/trade"),
    }


def build_cost_diagnosis(*, taker_fee_pct: float, slippage_pct: float,
                         spread_pct: float, risk_base_usd: float = 25.0,
                         daily_loss_limit_usd: float = 200.0,
                         empirical_trades: Optional[Sequence] = None,
                         target_cost_in_r: float = 0.10) -> Dict[str, Any]:
    """Relatorio consolidado de diagnostico de custo (FASE 48)."""
    rt = round_trip_cost_pct(taker_fee_pct=taker_fee_pct,
                             slippage_pct=slippage_pct, spread_pct=spread_pct)
    table = viability_table(round_trip_pct=rt, risk_base_usd=risk_base_usd)
    out: Dict[str, Any] = {
        "schema": "cost_viability_v1",
        "round_trip_cost_pct": round(rt, 6),
        "round_trip_cost_bps": round(rt * 10000, 2),
        "risk_base_usd": risk_base_usd,
        "viability_table": table,
        "min_stop_for_target_cost_in_r": {
            "target_cost_in_r": target_cost_in_r,
            "min_stop_dist_pct": min_stop_for_cost_in_r(rt, target_cost_in_r),
        },
        "max_pure_cost_trades_per_day": max_trades_for_budget(
            daily_loss_limit_usd=daily_loss_limit_usd,
            cost_usd_per_trade=table[0]["cost_usd_per_trade"]),
        "note": ("cost_in_R = round_trip_pct/stop_dist_pct. Stops maiores "
                 "(horizonte maior) => menor custo em R => viabilidade. Funding"
                 " e 2a ordem (curto) mas soma em holds longos."),
    }
    if empirical_trades is not None:
        out["empirical"] = diagnose_from_trades(
            empirical_trades, round_trip_pct=rt, risk_base_usd=risk_base_usd)
    return out


__all__ = [
    "round_trip_cost_pct", "cost_in_r", "min_stop_for_cost_in_r",
    "viability_table", "max_trades_for_budget", "diagnose_from_trades",
    "build_cost_diagnosis",
]
