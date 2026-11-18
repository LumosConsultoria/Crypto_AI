"""
AI candidate builder (FASE 47, correcao do shadow) — RiskEngine ANTES da IA.
=============================================================================
Gera contextos de candidato p/ a IA APENAS para setups que:
  1) passam o piso (stop_dist_pct >= min_stop_loss_pct) E
  2) sao APROVADOS pelo RiskEngine (effective config).
=> candidato com stop < 0,5% (ou bloqueado pelo RiskEngine) NAO consome
chamada de IA (P1).

O contexto enviado a IA e COMPLETO e CAUSAL (P3): funding + percentil, OI +
variacao, ATR + ATR%, volume, entry/stop/alvo/R:R, stop_dist, risco Hyro
disponivel, custos (bps) e stance Polymarket quando aplicavel. Nenhum campo
inventado (ex.: sem liquidation_price => a IA nao pode falar de liquidacao).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from crypto_trading_bot.research.effective_config import (
    EffectiveConfig,
    dynamic_position_size,
)
from crypto_trading_bot.research.perp_signals import build_perp_features

_REALISTIC_BPS = {"fees_bps": 6.0, "slippage_bps": 5.0, "spread_bps": 2.0}


def _rr(entry: float, stop: float, target: float) -> Optional[float]:
    risk = abs(entry - stop)
    rew = abs(target - entry)
    return round(rew / risk, 3) if risk > 0 else None


def build_candidate_contexts(
    candles: Sequence, *, funding_points: Sequence = (),
    oi_points: Sequence = (), effective_config: EffectiveConfig,
    polymarket_history=None, symbol: str = "BTCUSDT",
    interval_minutes: int = 15, max_candidates: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Retorna (contextos_aprovados, contagens). contagens inclui
    total_setups, rejected_by_floor, rejected_by_riskengine, approved."""
    from crypto_trading_bot.data.feature_engine import FeatureEngine
    from crypto_trading_bot.research.mtf_strategy import _emit
    from crypto_trading_bot.research.perp_families import (
        detect_f1_funding_fade, detect_f2_oi_momentum)
    from crypto_trading_bot.risk.risk_engine import RiskEngine

    feats = build_perp_features(candles, interval_minutes=interval_minutes,
                               funding_points=list(funding_points),
                               oi_points=list(oi_points))
    f1 = detect_f1_funding_fade(candles, feats.funding_pctile)
    f2 = detect_f2_oi_momentum(candles, feats.oi_change)
    setups = sorted(f1 + f2, key=lambda s: s.open_ts)

    fe = FeatureEngine().compute(list(candles))
    atr = [float(x) for x in fe["atr_14"]]
    closes = [float(x) for x in fe["closes"]]

    rc = effective_config.risk_config
    capital = float(rc.account_size_usd)
    risk_base_pct = float(rc.max_risk_per_trade_pct)
    risk_base_usd = round(risk_base_pct * capital, 2)
    ext = effective_config.external_ceilings
    engine = RiskEngine(initial_capital=capital, config=rc)

    counts = {"total_setups": len(setups), "rejected_by_floor": 0,
              "rejected_by_riskengine": 0, "approved": 0}
    out: List[Dict[str, Any]] = []
    for s in setups:
        sized = dynamic_position_size(
            capital=capital, stop_dist_pct=s.stop_dist_pct,
            risk_base_pct=risk_base_pct,
            external_risk_ceiling_pct=ext["max_risk_per_trade_pct"])
        size = sized["position_size_usd"]
        # ----- RiskEngine ANTES da IA (P1) -----
        sig = _emit(symbol, f"perp_{s.setup_id.split('_')[0]}", s.direction,
                    s.entry_ref, s.stop, s.target, size)
        if sig.action.value not in ("buy", "sell"):
            counts["rejected_by_floor"] += 1
            continue
        try:
            res = engine.validate_signal(sig.to_trading_signal())
        except Exception:  # noqa: BLE001
            counts["rejected_by_riskengine"] += 1
            continue
        if not res.approved:
            br = (res.block_reason or "").lower()
            if "stop" in br and ("min" in br or "small" in br
                                 or "0.5" in br or "pequeno" in br):
                counts["rejected_by_floor"] += 1
            else:
                counts["rejected_by_riskengine"] += 1
            continue
        # ----- contexto causal COMPLETO (P3) -----
        i = s.idx
        a = atr[i] if 0 <= i < len(atr) else None
        px = closes[i] if 0 <= i < len(closes) else s.entry_ref
        vol = float(candles[i].volume) if 0 <= i < len(candles) else None
        poly = "not_applicable"
        if polymarket_history is not None:
            from datetime import timedelta
            ct = s.open_ts + timedelta(minutes=interval_minutes)
            poly = polymarket_history.stance_at(ct)
        ctx = {
            "symbol": symbol,
            "timestamp": s.open_ts.isoformat()
            if hasattr(s.open_ts, "isoformat") else str(s.open_ts),
            "family": s.setup_id.split("_")[0],
            "direction": s.direction,
            "entry": s.entry_ref, "stop": s.stop, "target": s.target,
            "risk_reward": _rr(s.entry_ref, s.stop, s.target),
            "stop_dist_pct": round(s.stop_dist_pct, 5),
            "atr": round(a, 2) if a is not None else None,
            "atr_pct": round(a / px, 5) if (a is not None and px) else None,
            "volume": round(vol, 2) if vol is not None else None,
            "funding_rate": (round(feats.funding[i], 8)
                             if i < len(feats.funding)
                             and feats.funding[i] is not None else None),
            "funding_pctile": (round(feats.funding_pctile[i], 4)
                               if i < len(feats.funding_pctile)
                               and feats.funding_pctile[i] is not None
                               else None),
            "open_interest": (round(feats.oi[i], 2) if i < len(feats.oi)
                              and feats.oi[i] is not None else None),
            "oi_change": (round(feats.oi_change[i], 5)
                          if i < len(feats.oi_change)
                          and feats.oi_change[i] is not None else None),
            "position_size_usd": size,
            "target_risk_usd": risk_base_usd,
            "hyro_per_trade_ceiling_usd": round(
                ext["max_risk_per_trade_pct"] * capital, 2),
            "hyro_daily_dd_limit_usd": round(
                ext["daily_drawdown_pct"] * capital, 2),
            "costs_bps": dict(_REALISTIC_BPS),
            "polymarket_stance": poly,
            "data_note": "sem liquidation_price/orderbook fornecidos => "
                         "nao inferir liquidacao/profundidade",
        }
        out.append(ctx)
        counts["approved"] += 1
        if max_candidates is not None and len(out) >= max_candidates:
            break
    return out, counts


__all__ = ["build_candidate_contexts"]
