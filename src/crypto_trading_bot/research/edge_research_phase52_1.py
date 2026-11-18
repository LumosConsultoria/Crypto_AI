"""
Edge Research FASE 52.1 — Funding Signal-to-Strategy Reconciliation.
====================================================================
Reconcilia POR QUE o sinal bruto funding_rate 3d sobrevive (DEV e VAL) mas a
estrategia F5 falhou na VAL. NAO monta estrategia nova; NAO otimiza; NAO
consulta OOS. Apenas DECOMPOE o sinal bruto vs trades executaveis, numa ESCADA
de configuracoes PRE-especificadas (cada degrau adiciona UMA mecanica da F5),
medindo onde o edge da VAL desaparece.

Sinal bruto (FASE 49/50/52): funding_rate, 1h, EXTREMO por tercil do proprio
sample, retorno FIXO 3d close-a-close, SEM stop/target/path, SEM funding no PnL,
peso igual. F5 (FASE 51): 4h, funding_pctile>=0,85/<=0,15, stop [1,5%,5%],
alvo 1,5R, saida por tempo ~7d, funding REAL no PnL, sizing por risco USD.

A escada (tudo 1h, DEV e VAL separados, custo 26bps, direcao FIXA MR):
  C1 fixed-3d  + tercil      (executavel: threshold CAUSAL, sequencial)
  C2 fixed-3d  + tercil      + funding
  C3 fixed-3d  + extremo F5  (0,85/0,15)
  C4 fixed-7d  + extremo F5             (horizonte da F5)
  C5 stop/alvo + extremo F5  + funding  (≈ mecanicas F5 no 1h, 7d)
  C6 stop/alvo + extremo F5  + funding  (3d)
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from crypto_trading_bot.research.perp_signals import funding_pnl_adjustment

REALISTIC_COST = 0.0026
STOP_PCT = 0.05          # cap estrutural da F5 (FIXO, pre-especificado)
RR = 1.5                 # alvo 1,5R da F5
H3D = 72                 # 3d em barras 1h
H7D = 168                # 7d em barras 1h


def _parse(d: str) -> datetime:
    return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _utc(ts):
    return ts.replace(tzinfo=timezone.utc) if getattr(ts, "tzinfo", None) \
        is None else ts


def _month(ts) -> str:
    t = _utc(ts)
    return f"{t.year}-{t.month:02d}"


def simulate_trades(
    candles: Sequence, funding_pctile: Sequence[Optional[float]],
    funding_events: Sequence, *, hi: float, lo: float, exit_kind: str,
    horizon_bars: int, stop_pct: float = STOP_PCT, rr: float = RR,
    cost_pct: float = REALISTIC_COST, apply_funding: bool = False,
) -> List[Dict[str, Any]]:
    """Trades SEQUENCIAIS nao-sobrepostos (flat->entrada no extremo causal->
    saida). exit_kind: 'fixed' (close no horizonte) ou 'stop_target' (stop/alvo/
    tempo, PATH-aware pelas barras 1h). Retornos em FRACAO do notional."""
    n = len(candles)
    closes = [float(c.close) for c in candles]
    highs = [float(c.high) for c in candles]
    lows = [float(c.low) for c in candles]
    trades: List[Dict[str, Any]] = []
    i = 0
    while i < n - 1:
        p = funding_pctile[i] if i < len(funding_pctile) else None
        direction = None
        if p is not None and p >= hi:
            direction = "short"
        elif p is not None and p <= lo:
            direction = "long"
        if direction is None:
            i += 1
            continue
        entry = closes[i]
        sign = 1.0 if direction == "long" else -1.0
        end = min(i + horizon_bars, n - 1)
        exit_idx = end
        exit_price = closes[end]
        if exit_kind == "stop_target":
            stop_lv = entry * (1 - stop_pct) if direction == "long" \
                else entry * (1 + stop_pct)
            tgt_lv = entry * (1 + rr * stop_pct) if direction == "long" \
                else entry * (1 - rr * stop_pct)
            for j in range(i + 1, end + 1):
                hit_stop = (lows[j] <= stop_lv) if direction == "long" \
                    else (highs[j] >= stop_lv)
                hit_tgt = (highs[j] >= tgt_lv) if direction == "long" \
                    else (lows[j] <= tgt_lv)
                if hit_stop:                       # conservador: stop antes
                    exit_idx, exit_price = j, stop_lv
                    break
                if hit_tgt:
                    exit_idx, exit_price = j, tgt_lv
                    break
        gross = sign * (exit_price / entry - 1.0)
        net = gross - cost_pct
        fund = 0.0
        if apply_funding:
            fund = funding_pnl_adjustment(
                candles[i].timestamp, candles[exit_idx].timestamp,
                notional_usd=1.0, side=direction,
                funding_events=funding_events)
            net += fund
        trades.append({"entry_idx": i, "exit_idx": exit_idx,
                       "direction": direction, "gross": gross, "net": net,
                       "funding": fund, "month": _month(candles[i].timestamp),
                       "ts": candles[i].timestamp})
        i = exit_idx + 1                            # nao-sobreposto
    return trades


def _seg(trades, seg) -> List[Dict[str, Any]]:
    lo, hi = _parse(seg[0]), _parse(seg[1])
    return [t for t in trades if lo <= _utc(t["ts"]) < hi]


def summarize(trades: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    if not trades:
        return {"n_trades": 0, "mean_net_pct": None, "total_net_pct": None,
                "hit_rate": None, "sign_consistency": None}
    nets = [t["net"] for t in trades]
    by_m: Dict[str, List[float]] = {}
    for t in trades:
        by_m.setdefault(t["month"], []).append(t["net"])
    m_means = {m: statistics.mean(v) for m, v in by_m.items()}
    months_pos = sum(1 for v in m_means.values() if v > 0)
    return {
        "n_trades": len(trades),
        "mean_net_pct": round(statistics.mean(nets) * 100, 4),
        "total_net_pct": round(sum(nets) * 100, 4),
        "hit_rate": round(sum(1 for x in nets if x > 0) / len(nets), 4),
        "sign_consistency": round(months_pos / len(m_means), 4)
        if m_means else None,
        "n_months": len(m_means),
        "mean_funding_pct": round(
            statistics.mean([t["funding"] for t in trades]) * 100, 4),
    }


# ----- escada de configuracoes (PRE-especificada; NAO otimizada) -----------
LADDER = [
    {"id": "C1_fixed3d_tercile", "hi": 0.667, "lo": 0.333,
     "exit_kind": "fixed", "horizon_bars": H3D, "apply_funding": False,
     "label": "executavel: 3d close, threshold causal tercil, SEM funding"},
    {"id": "C2_fixed3d_tercile_funding", "hi": 0.667, "lo": 0.333,
     "exit_kind": "fixed", "horizon_bars": H3D, "apply_funding": True,
     "label": "+ funding no PnL"},
    {"id": "C3_fixed3d_extreme", "hi": 0.85, "lo": 0.15,
     "exit_kind": "fixed", "horizon_bars": H3D, "apply_funding": True,
     "label": "+ threshold extremo F5 (0,85/0,15)"},
    {"id": "C4_fixed7d_extreme", "hi": 0.85, "lo": 0.15,
     "exit_kind": "fixed", "horizon_bars": H7D, "apply_funding": True,
     "label": "+ horizonte 7d (da F5)"},
    {"id": "C5_stoptarget7d_extreme", "hi": 0.85, "lo": 0.15,
     "exit_kind": "stop_target", "horizon_bars": H7D, "apply_funding": True,
     "label": "+ stop 5% / alvo 1,5R (≈ mecanicas F5)"},
    {"id": "C6_stoptarget3d_extreme", "hi": 0.85, "lo": 0.15,
     "exit_kind": "stop_target", "horizon_bars": H3D, "apply_funding": True,
     "label": "stop/alvo com horizonte 3d"},
]


@dataclass(frozen=True)
class Reconciliation521Report:
    schema: str
    symbol: str
    generated_at: str
    window: Mapping[str, Any]
    ladder: Tuple[Mapping[str, Any], ...]
    raw_signal_reference: Mapping[str, Any]
    f5_reference: Mapping[str, Any]
    attribution: Mapping[str, Any]
    answers: Mapping[str, Any]
    decision: str
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {"schema": self.schema, "symbol": self.symbol,
                "generated_at": self.generated_at, "window": dict(self.window),
                "ladder": [dict(x) for x in self.ladder],
                "raw_signal_reference": dict(self.raw_signal_reference),
                "f5_reference": dict(self.f5_reference),
                "attribution": dict(self.attribution),
                "answers": dict(self.answers), "decision": self.decision,
                "real_execution_allowed": False, "demo_blocked": True,
                "live_blocked": True, "strategy_promoted": False,
                "notes": list(self.notes)}


def _val_positive(row) -> bool:
    v = row["val"]["mean_net_pct"]
    return v is not None and v > 0


def run_reconciliation(
    candles_dev_val: Sequence, *, symbol: str = "BTCUSDT",
    funding_points: Sequence = (), oi_points: Sequence = (),
    dev: Tuple[str, str] = ("2025-01-01", "2025-10-01"),
    val: Tuple[str, str] = ("2025-10-01", "2026-02-01"),
    cost_pct: float = REALISTIC_COST, progress=None) -> Reconciliation521Report:
    from crypto_trading_bot.research.perp_signals import build_perp_features

    def _cb(m):
        if progress:
            progress(m)

    _cb("perp features (funding_pctile causal, 1h)")
    pf = build_perp_features(candles_dev_val, interval_minutes=60,
                             funding_points=list(funding_points),
                             oi_points=list(oi_points))
    fpct, fevents = pf.funding_pctile, pf.funding_events

    ladder_rows: List[Dict[str, Any]] = []
    for cfg in LADDER:
        _cb(f"escada: {cfg['id']}")
        trades = simulate_trades(
            candles_dev_val, fpct, fevents, hi=cfg["hi"], lo=cfg["lo"],
            exit_kind=cfg["exit_kind"], horizon_bars=cfg["horizon_bars"],
            cost_pct=cost_pct, apply_funding=cfg["apply_funding"])
        ladder_rows.append({
            "id": cfg["id"], "label": cfg["label"],
            "params": {k: cfg[k] for k in ("hi", "lo", "exit_kind",
                                           "horizon_bars", "apply_funding")},
            "dev": summarize(_seg(trades, dev)),
            "val": summarize(_seg(trades, val)),
        })

    # ---- atribuicao: onde a VAL deixa de ser positiva ----
    first_neg = next((r["id"] for r in ladder_rows if not _val_positive(r)),
                     None)
    c1 = ladder_rows[0]
    raw_ref = {
        "source": "FASE 52 reports/edge_research_phase52_btcusdt.json",
        "funding_rate_3d_overall": {
            "dev": {"survival": "survived", "mean_net_after_cost": 0.003974,
                    "sign_consistency": 0.7778, "fired": 180},
            "val": {"survival": "survived", "mean_net_after_cost": 0.003589,
                    "sign_consistency": 1.0, "fired": 78}},
        "note": ("net por trade do sinal BRUTO usa tercil do PROPRIO sample + "
                 "janelas sobrepostas no pool + retorno FIXO close-a-close SEM "
                 "path; nao e diretamente executavel."),
    }
    f5_ref = {
        "source": "FASE 51 reports/edge_research_phase51_btcusdt.json",
        "dev": {"trades": 67, "net_pnl_usd": 516, "profit_factor_net": 1.77,
                "sign_consistency": 0.78, "classification": "candidata_paper"},
        "val": {"trades": 28, "net_pnl_usd": 27.9, "profit_factor_net": 1.08,
                "sign_consistency": 0.25, "classification": "sem_edge_operacional"},
    }

    def _row(cid):
        return next(r for r in ladder_rows if r["id"] == cid)

    def _net(cid, seg):
        return _row(cid)[seg]["mean_net_pct"]
    # evidencias estruturais (data-driven):
    exec_3d = ["C1_fixed3d_tercile", "C2_fixed3d_tercile_funding",
               "C3_fixed3d_extreme"]
    h7 = ["C4_fixed7d_extreme", "C5_stoptarget7d_extreme"]
    exec3d_dev_no_edge = all((_net(c, "dev") or 0) <= 0 for c in exec_3d)
    h7_dev_positive = all((_net(c, "dev") or 0) > 0 for c in h7)
    h7_val_inverts = all((_net(c, "val") or 0) < 0 for c in h7)

    c1_val_ok = _val_positive(c1) and (c1["val"]["sign_consistency"] or 0) >= 0.6
    if c1_val_ok:
        decision = "ENCERRAR_APENAS_F5_E_REGIME_FILTER"
        conclusion = (
            "O sinal funding_rate/percentil SOBREVIVE como estrategia "
            "EXECUTAVEL minima (entrada por percentil causal + saida FIXA 3d + "
            "custo) no DEV e na VAL. Logo o edge bruto e real e executavel; a "
            "F5 perdeu o edge nas MECANICAS adicionadas, nao no sinal. "
            f"Primeiro degrau que zera a VAL: {first_neg}.")
        next_test = (
            "FASE 53 (teste MINIMO, sem otimizar): swing MR por funding com "
            "saida FIXA por tempo (~3d), SEM stop/alvo apertados, threshold "
            "causal pre-fixado; validar DEV->VAL nao-sobreposto; OOS so depois.")
    else:
        decision = "ENCERRAR_FUNDING_COMPLETAMENTE"
        conclusion = (
            "Mesmo a versao EXECUTAVEL minima (percentil causal + saida fixa 3d "
            "+ custo, sequencial) NAO sustenta net>0 estavel na VAL. O 'edge' do "
            "sinal bruto vinha do MODO DE MEDIR (tercil do proprio sample + "
            "janelas sobrepostas + retorno fixo sem path/sequencia), nao de algo "
            "executavel. Funding direcional em BTCUSDT nao gera estrategia.")
        next_test = ("Nenhum. Encerrar a linha funding direcional; IA/Polymarket "
                     "shadow; FASE 53 = dados prospectivos (liquidacoes/orderbook).")

    answers = {
        "q1_signal_execution_compatible": (
            "NAO totalmente. O net do sinal bruto usa tercil do proprio sample "
            "(nao causal), pool sobreposto e retorno FIXO close-a-close sem "
            "path. A versao executavel (C1) usa percentil CAUSAL, sequencial, "
            "com custo => e a medida honesta de executabilidade."),
        "q2_where_f5_lost_edge": {
            "threshold_tercile_vs_extreme": "C1 vs C3",
            "horizon_3d_vs_7d": "C3 vs C4",
            "stop_target_path_dependence": "C4 vs C5",
            "funding_in_pnl": "C1 vs C2 (funding AJUDA o MR: short recebe "
                              "funding alto, long recebe funding baixo)",
            "first_step_that_kills_val": first_neg,
            "direction": "igual nos dois (MR); NAO e causa",
            "sizing": "peso igual aqui; sizing escala magnitude, NAO o SINAL "
                      "por trade => nao explica a queda de sign_consistency "
                      "0,78->0,25 (sizing-invariante)",
            "sample": f"F5 VAL=28 trades vs C1 VAL={c1['val']['n_trades']} "
                      "(extremo 0,85/0,15 reduz MUITO a amostra vs tercil)",
        },
        "q3_simple_strategy_without_val_tuning": (
            "SIM" if c1_val_ok else "NAO") + " — ver C1 (saida fixa 3d, "
            "threshold causal, custo; nenhum parametro ajustado na VAL).",
        "q4_where_raw_edge_disappears": conclusion,
        "next_minimal_test": next_test,
    }
    interpretation = (
        "Executavel 3d (C1-C3) SEM edge ate no DEV (net<=0); o LUCRO de DEV da "
        "F5 vem do horizonte 7d + stop/alvo (C4/C5 DEV+), que INVERTE na VAL "
        "(C4/C5 VAL-). Logo: (a) a 'sobrevivencia' do sinal 3d na FASE 52 foi "
        "ARTEFATO de medicao (tercil in-sample + overlap + retorno fixo sem "
        "path/sequencia); (b) o edge de DEV da F5 foi um efeito de horizonte 7d "
        "NAO-robusto. C5 reproduz a F5 (DEV+/VAL-, VALsc baixo)."
    ) if (exec3d_dev_no_edge and h7_dev_positive and h7_val_inverts) else (
        "Ver escada: localizar o degrau onde DEV e VAL divergem.")
    attribution = {
        "first_step_val_negative": first_neg,
        "c1_executable_val_ok": c1_val_ok,
        "c1_dev_net_pct": _net("C1_fixed3d_tercile", "dev"),
        "c1_val_net_pct": _net("C1_fixed3d_tercile", "val"),
        "exec3d_dev_no_edge": exec3d_dev_no_edge,
        "h7_dev_positive": h7_dev_positive,
        "h7_val_inverts": h7_val_inverts,
        "f5_reproduced_by_C5": {
            "C5_dev_net_pct": _net("C5_stoptarget7d_extreme", "dev"),
            "C5_val_net_pct": _net("C5_stoptarget7d_extreme", "val")},
        "interpretation": interpretation,
        "conclusion": conclusion}

    return Reconciliation521Report(
        schema="funding_signal_strategy_reconciliation_v1", symbol=symbol,
        generated_at=datetime.now(timezone.utc).isoformat(),
        window={"dev": dev, "val": val, "n_candles": len(candles_dev_val),
                "timeframe": "1h", "cost_pct": cost_pct, "stop_pct": STOP_PCT,
                "rr": RR, "perpetual_only": True, "oos_consulted": False},
        ladder=tuple(ladder_rows), raw_signal_reference=raw_ref,
        f5_reference=f5_ref, attribution=attribution, answers=answers,
        decision=decision,
        notes=("Decomposicao sinal-bruto vs trades-F5; sem otimizar; sem OOS; "
               "sem estrategia nova. Path-aware pelas barras 1h (stop/alvo). "
               "Funding direcional AJUDA o MR (sinal correto). OOS intocado.",
               "Se C1 (executavel minimo) sobrevive a VAL => so a F5/regime "
               "esta rejeitada; senao => funding direcional encerrado.",))


__all__ = ["simulate_trades", "summarize", "run_reconciliation", "LADDER",
           "Reconciliation521Report"]
