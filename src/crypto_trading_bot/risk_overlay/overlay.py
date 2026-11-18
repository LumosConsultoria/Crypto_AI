"""
Risk & Exposure Overlay (FASE 57) — motor de avaliacao ADVISORY.
=================================================================
Avalia conta + posicoes contra RiskLimits e emite Alertas + recomendacoes de
reducao de exposicao/risco. NAO-preditivo; read-only; NUNCA ordem. Determinis-
tico/offline. Regras (severidade): sem-SL, SL<piso, risco/trade>cap,
exposicao>cap, leverage>cap, posicoes>cap, daily-DD (aviso/estouro),
equity-floor (aviso/estouro), funding-bleed, drawdown nao-realizado.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from crypto_trading_bot.risk_overlay.models import (
    AccountState, Alert, Position, RiskLimits, SEVERITY_ORDER)

# fracao do limite diario a partir da qual avisamos (antes de estourar)
_DAILY_WARN_FRAC = 0.75
_FLOOR_WARN_PCT = 0.015          # 1,5% acima do equity floor => aviso
_FUNDING_NOTABLE = 0.0001        # 0,01% por evento => custo notavel


def _pos_alerts(p: Position, lim: RiskLimits) -> List[Alert]:
    out: List[Alert] = []
    scope = f"position:{p.symbol}"
    sd = p.stop_dist_pct()
    if p.stop_loss_price is None:
        out.append(Alert(
            "position_no_stop_loss", "high", scope,
            f"{p.symbol}: posicao SEM stop-loss.",
            "Definir SL (>= piso 0,5%); posicao sem SL viola disciplina e o "
            "challenge (stop obrigatorio).",
            {"notional_usd": p.notional_usd}))
    elif sd is not None and sd < lim.min_stop_loss_pct:
        out.append(Alert(
            "position_stop_below_floor", "medium", scope,
            f"{p.symbol}: SL muito apertado ({sd*100:.2f}% < piso "
            f"{lim.min_stop_loss_pct*100:.2f}%).",
            "Alargar o SL ao piso ou reduzir notional; SL abaixo do piso e "
            "bloqueado pelo RiskEngine.",
            {"stop_dist_pct": round(sd, 6)}))
    risk = p.risk_to_stop_usd()
    if risk is not None and risk > lim.max_risk_per_trade_usd:
        # notional alvo p/ risco <= cap
        tgt = (round(lim.max_risk_per_trade_usd / sd, 2)
               if sd and sd > 0 else None)
        out.append(Alert(
            "position_risk_per_trade_exceeded", "high", scope,
            f"{p.symbol}: risco ao stop US${risk} > cap "
            f"US${lim.max_risk_per_trade_usd}.",
            (f"Reduzir notional para <= US${tgt} (risco <= "
             f"US${lim.max_risk_per_trade_usd})." if tgt
             else "Reduzir notional para enquadrar o risco no cap."),
            {"risk_to_stop_usd": risk,
             "max_risk_per_trade_usd": lim.max_risk_per_trade_usd,
             "target_notional_usd": tgt}))
    # drawdown nao-realizado relevante (perda > cap de risco por trade)
    u = p.unrealized()
    if u < 0 and abs(u) > lim.max_risk_per_trade_usd:
        out.append(Alert(
            "position_unrealized_drawdown", "medium", scope,
            f"{p.symbol}: perda nao-realizada US${u} (> cap de risco "
            f"US${lim.max_risk_per_trade_usd}).",
            "Revisar tese/!SL; considerar reduzir exposicao se sem catalisador.",
            {"unrealized_pnl_usd": u}))
    # custo de funding (advisory) — long paga funding>0; short paga funding<0
    if p.funding_rate is not None:
        sign = 1.0 if p.side.lower() in ("long", "buy") else -1.0
        cost = sign * p.funding_rate * p.notional_usd      # >0 = custo p/ a pos
        if cost > 0 and abs(p.funding_rate) >= _FUNDING_NOTABLE:
            out.append(Alert(
                "position_funding_bleed", "low", scope,
                f"{p.symbol}: pagando ~US${round(cost,2)}/evento de funding "
                f"(rate {p.funding_rate*100:.4f}%).",
                "Funding sangra posicoes paradas; avaliar reduzir/encerrar se "
                "sem tese de curto prazo.",
                {"funding_rate": p.funding_rate,
                 "funding_cost_per_event_usd": round(cost, 2)}))
    return out


def _account_alerts(acc: AccountState, positions: Sequence[Position],
                    lim: RiskLimits, total_notional: float,
                    total_unrealized: float) -> List[Alert]:
    out: List[Alert] = []
    exposure_pct = total_notional / lim.capital_usd if lim.capital_usd else 0.0
    eff_lev = total_notional / acc.equity_usd if acc.equity_usd else 0.0
    # exposicao
    if exposure_pct > lim.max_exposure_pct + 1e-9:
        cut = round(total_notional - lim.max_exposure_pct * lim.capital_usd, 2)
        out.append(Alert(
            "exposure_over_cap", "high", "account",
            f"Exposicao {exposure_pct*100:.1f}% > cap "
            f"{lim.max_exposure_pct*100:.0f}%.",
            f"Reduzir notional total em ~US${cut} para enquadrar no cap.",
            {"exposure_pct": round(exposure_pct, 4),
             "reduce_notional_usd": cut}))
    if eff_lev > lim.max_leverage + 1e-9:
        out.append(Alert(
            "leverage_over_cap", "high", "account",
            f"Alavancagem efetiva {eff_lev:.2f}x > cap {lim.max_leverage:.0f}x.",
            "Reduzir notional total ou aportar; manter <= leverage do perfil.",
            {"effective_leverage": round(eff_lev, 3)}))
    n = len([p for p in positions])
    if n > lim.max_open_positions:
        out.append(Alert(
            "too_many_positions", "medium", "account",
            f"{n} posicoes abertas > cap {lim.max_open_positions}.",
            "Encerrar/consolidar posicoes ate o limite do perfil.",
            {"open_positions": n, "max_open_positions": lim.max_open_positions}))
    # daily drawdown (realizado hoje + nao-realizado)
    day_pnl = acc.realized_pnl_today_usd + total_unrealized
    if day_pnl < 0:
        loss = -day_pnl
        frac = loss / lim.max_daily_loss_usd if lim.max_daily_loss_usd else 0.0
        if frac >= 1.0:
            out.append(Alert(
                "daily_loss_breached", "critical", "account",
                f"Perda do dia US${round(loss,2)} >= limite diario "
                f"US${lim.max_daily_loss_usd}.",
                "PARAR de operar hoje; daily drawdown estourado (regra de "
                "challenge). Sem novas entradas.",
                {"day_loss_usd": round(loss, 2),
                 "max_daily_loss_usd": lim.max_daily_loss_usd}))
        elif frac >= _DAILY_WARN_FRAC:
            out.append(Alert(
                "daily_loss_warning", "high", "account",
                f"Perda do dia US${round(loss,2)} = {frac*100:.0f}% do limite "
                f"diario.",
                "Aproximando do daily DD; reduzir risco/tamanho, evitar nova "
                "entrada.",
                {"day_loss_usd": round(loss, 2), "fraction_of_limit": round(frac, 3)}))
    # equity floor (perda total)
    if acc.equity_usd <= lim.equity_floor_usd:
        out.append(Alert(
            "equity_floor_breached", "critical", "account",
            f"Equity US${acc.equity_usd} <= piso US${lim.equity_floor_usd} "
            f"(max loss {lim.max_total_loss_pct*100:.0f}%).",
            "Max loss atingido; encerrar exposicao. Challenge reprovado.",
            {"equity_usd": acc.equity_usd, "equity_floor_usd": lim.equity_floor_usd}))
    elif acc.equity_usd <= lim.equity_floor_usd * (1.0 + _FLOOR_WARN_PCT):
        out.append(Alert(
            "equity_floor_warning", "high", "account",
            f"Equity US${acc.equity_usd} proximo do piso "
            f"US${lim.equity_floor_usd}.",
            "Reduzir exposicao agressivamente; pouco espaco ate o max loss.",
            {"equity_usd": acc.equity_usd}))
    return out


def _status(alerts: Sequence[Alert], n_positions: int) -> str:
    if not alerts:
        return "flat_ok" if n_positions == 0 else "ok_monitor"
    top = max(SEVERITY_ORDER[a.severity] for a in alerts)
    return {4: "action_required_critical", 3: "action_required",
            2: "warning", 1: "ok_monitor", 0: "ok_monitor"}[top]


def evaluate_risk_overlay(account: AccountState, positions: Sequence[Position],
                          limits: Optional[RiskLimits] = None) -> Dict[str, Any]:
    """Avalia conta+posicoes e retorna o relatorio ADVISORY (sem ordem)."""
    lim = limits or RiskLimits()
    positions = list(positions)
    total_notional = round(sum(p.notional_usd for p in positions), 2)
    total_unrealized = round(sum(p.unrealized() for p in positions), 2)
    total_risk = round(sum(p.risk_to_stop_usd() or 0.0 for p in positions), 2)

    alerts: List[Alert] = []
    for p in positions:
        alerts.extend(_pos_alerts(p, lim))
    alerts.extend(_account_alerts(account, positions, lim, total_notional,
                                  total_unrealized))
    alerts.sort(key=lambda a: -SEVERITY_ORDER[a.severity])

    sev_counts: Dict[str, int] = {}
    for a in alerts:
        sev_counts[a.severity] = sev_counts.get(a.severity, 0) + 1
    status = _status(alerts, len(positions))

    return {
        "schema": "risk_overlay_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "advisory_read_only_non_predictive",
        "limits": lim.to_dict(),
        "account": account.to_dict(),
        "positions": [p.to_dict() for p in positions],
        "exposure_summary": {
            "open_positions": len(positions),
            "total_notional_usd": total_notional,
            "exposure_pct": round(total_notional / lim.capital_usd, 4)
            if lim.capital_usd else None,
            "effective_leverage": round(total_notional / account.equity_usd, 3)
            if account.equity_usd else None,
            "total_risk_to_stop_usd": total_risk,
            "total_unrealized_pnl_usd": total_unrealized,
            "day_pnl_usd": round(account.realized_pnl_today_usd
                                 + total_unrealized, 2)},
        "alerts": [a.to_dict() for a in alerts],
        "severity_counts": sev_counts,
        "overall_status": status,
        "recommendations": [a.recommendation for a in alerts],
        "real_execution_allowed": False, "orders_emitted": 0,
        "demo_blocked": True, "live_blocked": True,
        "note": ("Overlay ADVISORY read-only, NAO-preditivo: avalia risco/"
                 "exposicao e recomenda; NUNCA envia ordem. RiskEngine/ModeGuard/"
                 "piso 0.005 intactos; demo/live bloqueados."),
    }


__all__ = ["evaluate_risk_overlay"]
