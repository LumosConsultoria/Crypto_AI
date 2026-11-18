"""
Registry / TOMBSTONE de hipoteses REJEITADAS (FASE 56).
========================================================
Cataloga TODAS as hipoteses de edge testadas e rejeitadas nas FASES 38-55
(BTCUSDT Bybit Linear Perp, dados normais OHLCV/regime/vol/OI/funding/
calendario). Objetivo: registrar aprendizado E **impedir reexecucao acidental
da MESMA hipotese com tuning superficial**.

Uso: `check_before_test(name, family, structural_difference=...)` antes de
montar/rodar qualquer hipotese nova. Se o nome ja foi rejeitado => BLOQUEIA.
Se a FAMILIA ja foi rejeitada => exige justificativa de diferenca ESTRUTURAL
(nao apenas trocar parametros). NAO consulta VAL/OOS; nao promove nada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

# status possiveis
REJECTED = "rejected"                       # sem edge no DEV
REJECTED_DEFINITIVELY = "rejected_definitively"   # ruido confirmado multi-janela
NEAR_MISS = "near_miss_not_candidate"       # lucrativo mas falha robustez/signif
LINE_CLOSED = "line_closed"                 # linha inteira encerrada


@dataclass(frozen=True)
class RejectedHypothesis:
    name: str
    family: str
    phases: Tuple[str, ...]
    rejection_reason: str
    key_metrics: Mapping[str, Any]
    status: str
    superficial_tuning_blocked: bool = True

    def to_dict(self) -> dict:
        return {"name": self.name, "family": self.family,
                "phases": list(self.phases),
                "rejection_reason": self.rejection_reason,
                "key_metrics": dict(self.key_metrics), "status": self.status,
                "superficial_tuning_blocked": self.superficial_tuning_blocked}


# ------------------------------ TOMBSTONE ----------------------------------
REJECTED_HYPOTHESES: Tuple[RejectedHypothesis, ...] = (
    # --- FASES 37-40: prototipos research / familias atuais ---
    RejectedHypothesis(
        "mean_reversion_in_range", "mean_reversion", ("39", "40"),
        "RUIDO no CSV completo (17mo): sign_consistency mensal ~0 => "
        "rejeitar_definitivamente.",
        {"sign_consistency": 0.0}, REJECTED_DEFINITIVELY),
    RejectedHypothesis(
        "range_mean_reversion_vwap_bollinger", "mean_reversion", ("40",),
        "Multi-TF 15m/5m sem edge robusto; terminou em "
        "seguir_para_infra_operacional.",
        {}, REJECTED),
    RejectedHypothesis(
        "volatility_contraction_expansion", "vol_expansion", ("38",),
        "Sem edge robusto por regime; amostra/estabilidade insuficientes.",
        {}, REJECTED),
    RejectedHypothesis(
        "trend_pullback_bidirectional", "breakout_trend", ("37", "38"),
        "Expectancy negativa no periodo real (PF~0,96).",
        {"profit_factor": 0.96}, REJECTED),
    RejectedHypothesis(
        "volatility_breakout", "breakout_trend", ("37", "38"),
        "Expectancy negativa (PF~0,78).", {"profit_factor": 0.78}, REJECTED),
    # --- FASE 44 ---
    RejectedHypothesis(
        "vol_expansion_trend_44", "breakout_trend", ("44",),
        "no_edge_dev: PF<1; piso 0.005 bloqueia maioria no 5m.",
        {"verdict": "no_edge_dev"}, REJECTED),
    RejectedHypothesis(
        "range_mean_reversion_44", "mean_reversion", ("44",),
        "no_edge_dev: edge liquido negativo.", {"verdict": "no_edge_dev"},
        REJECTED),
    # --- FASE 45 ---
    RejectedHypothesis(
        "mtf_breakout_pullback", "breakout_trend", ("45",),
        "no_edge_dev (PF 0,68-0,74; A~=B); stop estrutural validado mas sem "
        "edge.", {"profit_factor": 0.71}, REJECTED),
    # --- FASE 46 ---
    RejectedHypothesis(
        "ema_slope_breakout_1h", "breakout_trend", ("46",),
        "REJEITAR (PF 0,75, exp -1,71); piso/amostra/sizing resolvidos, sem "
        "edge.", {"profit_factor": 0.75, "expectancy": -1.71}, REJECTED),
    # --- FASE 47 ---
    RejectedHypothesis(
        "funding_extreme_fade", "funding_directional", ("47",),
        "no_edge_dev (F1 PF 0,56-0,68).", {"profit_factor": 0.62}, REJECTED),
    RejectedHypothesis(
        "oi_confirmed_momentum", "oi_momentum", ("47",),
        "no_edge_dev (F2 PF 0,80-0,97); OI-gate PIORA.",
        {"profit_factor": 0.88}, REJECTED),
    # --- FASE 48 ---
    RejectedHypothesis(
        "trend_continuation_4h", "breakout_trend", ("48",),
        "gross NEGATIVO; cost-aware corrigiu custo mas gargalo=direcao/timing.",
        {"profit_factor": 0.26}, REJECTED),
    RejectedHypothesis(
        "vol_expansion_mtf_4h", "vol_expansion", ("48",),
        "gross NEGATIVO (F4 PF 0,60); alvo grande raramente atingido.",
        {"profit_factor": 0.60}, REJECTED),
    # --- FASE 51/52/52.1: linha FUNDING DIRECIONAL encerrada ---
    RejectedHypothesis(
        "funding_swing_mr", "funding_directional", ("51", "52", "52.1"),
        "DEV passa nos 2 perfis (PF1,77) mas VAL derruba (PF1,08 sc0,25); "
        "regime nao resgata (F52 NAO_SOBREVIVE); reconciliacao F52.1: edge 3d "
        "era ARTEFATO de medicao + horizonte 7d nao-robusto.",
        {"dev_pf": 1.77, "val_pf": 1.08, "val_sign_consistency": 0.25},
        LINE_CLOSED),
    # --- FASE 53 ---
    RejectedHypothesis(
        "seasonality_session_bias", "calendar", ("53",),
        "sem_edge_operacional no DEV (73tr net-311 PF0,43).",
        {"num_trades": 73, "net_pnl_usd": -311, "profit_factor": 0.43},
        REJECTED),
    RejectedHypothesis(
        "volume_climax_reversal", "volume", ("53",),
        "sem_edge_operacional no DEV (14tr net-310 PF0,12).",
        {"num_trades": 14, "net_pnl_usd": -310, "profit_factor": 0.12},
        REJECTED),
    RejectedHypothesis(
        "oi_divergence_exhaustion", "oi_momentum", ("53",),
        "sem_edge_operacional no DEV (35tr net-298 PF0,42); INVERSO do F2.",
        {"num_trades": 35, "net_pnl_usd": -298, "profit_factor": 0.42},
        REJECTED),
    # --- FASE 55 (condicionadas por regime) ---
    RejectedHypothesis(
        "trend_pullback_regime_gated", "regime_setup", ("55",),
        "perdedora (43tr net-313 PF0,53; 0/5 meses+); gate de regime nao "
        "resgatou.", {"num_trades": 43, "profit_factor": 0.53,
                      "sign_consistency": 0.0}, REJECTED),
    RejectedHypothesis(
        "range_reversion_regime_gated", "regime_reversal", ("55",),
        "perdedora + amostra insuficiente (23tr<30; net-259 PF0,54).",
        {"num_trades": 23, "profit_factor": 0.54}, REJECTED),
    # --- FASE 60 (multi-asset cross-sectional sprint; universo BTC/ETH/SOL/XRP,
    #     BNB excluido por dados incompletos 96,5%) ---
    RejectedHypothesis(
        "relative_strength_continuation_5m", "xs_relative_strength", ("60",),
        "REJEITAR DEV cross-sectional 5m: 3030 trades net-25421 PF0,52; sem "
        "edge relativo (custo+selecao adversa). 3/9 criterios.",
        {"num_trades": 3030, "net_pnl_usd": -25421, "profit_factor": 0.52},
        REJECTED),
    RejectedHypothesis(
        "relative_reversion_after_dispersion_5m", "xs_dispersion_reversion",
        ("60",),
        "REJEITAR DEV: 1777 trades net-14878 PF0,52; fade pos-dispersao sem "
        "edge. 3/9 criterios.",
        {"num_trades": 1777, "net_pnl_usd": -14878, "profit_factor": 0.52},
        REJECTED),
    RejectedHypothesis(
        "btc_lead_lag_alt_follow_5m", "xs_lead_lag", ("60",),
        "REJEITAR DEV: 1091 trades net-9030 PF0,52; lead-lag BTC->alt sem edge "
        "no 5m. 3/9 criterios.",
        {"num_trades": 1091, "net_pnl_usd": -9030, "profit_factor": 0.52},
        REJECTED),
    # --- FASE 62 (H1 da agenda FASE 61; ultima tentativa preditiva BTC-only) ---
    RejectedHypothesis(
        "variance_ratio_regime_switch_1h", "statistical_regime_switch", ("62",),
        "REJEITAR DEV 1h: condicionar por variance-ratio (momentum VR>=1,10 / MR "
        "VR<=0,90) NAO resgata o bet direcional. 6256 setups mas so 34 trades "
        "(perde rapido, esbarra max-loss); net-319 PF0,43 exp-9,4 maxDD-8,4%; "
        "8/9 criterios reprovados. VAL nao consultado; sem tuning. ENCERRA busca "
        "preditiva BTCUSDT-only.",
        {"setups": 6256, "num_trades": 34, "net_pnl_usd": -319,
         "profit_factor": 0.43, "expectancy": -9.37}, REJECTED),
    # --- FASE 59 (H1 da agenda FASE 58) ---
    RejectedHypothesis(
        "failed_breakout_fade_5m", "failed_breakout_reversal", ("59",),
        "REJEITAR no DEV 5m: fade de fakeout single-bar (Donchian-20) e RARO "
        "executavel + PERDEDOR. 309 setups mas so 11 trades (piso 0,5% + "
        "raridade); net-313 (~-6,3%, esbarrou no max loss) PF0,07; 8/9 criterios "
        "reprovados. VAL nao consultado; sem tuning corretivo.",
        {"setups": 309, "num_trades": 11, "net_pnl_usd": -313,
         "profit_factor": 0.07}, REJECTED),
    RejectedHypothesis(
        "breakout_oi_funding_confirmed", "compression_confirmed", ("55",),
        "NEAR-MISS: lucrativo (52tr net+122 PF1,19 maxDD-2,1% 9 meses) MAS "
        "falha robustez temporal (sign_consistency 0,556<0,60), significancia "
        "(CI expectancy nao fecha) e Hyro (1 tentativa, meta nao atingida) => "
        "standard_trader rejeitado. NAO candidata.",
        {"num_trades": 52, "net_pnl_usd": 122, "profit_factor": 1.19,
         "max_drawdown_pct": -2.1, "sign_consistency": 0.556,
         "active_months": 9}, NEAR_MISS),
)

# familias inteiras com varias rejeicoes (re-teste exige diferenca estrutural)
REJECTED_FAMILIES = tuple(sorted({h.family for h in REJECTED_HYPOTHESES}))

_MIN_JUSTIFICATION = 30


def find(name_or_family: str) -> List[RejectedHypothesis]:
    q = (name_or_family or "").strip().lower()
    return [h for h in REJECTED_HYPOTHESES
            if h.name.lower() == q or h.family.lower() == q]


def is_tombstoned(name_or_family: str) -> bool:
    return bool(find(name_or_family))


def check_before_test(name: str, family: Optional[str] = None, *,
                      structural_difference: Optional[str] = None
                      ) -> Dict[str, Any]:
    """Guard ANTES de testar uma hipotese. Nome ja rejeitado => BLOQUEIA
    (reexecucao com tuning superficial). Familia ja rejeitada => exige
    justificativa de diferenca ESTRUTURAL (>= _MIN_JUSTIFICATION chars).
    Retorna {allowed, reason, matches}."""
    name_q = (name or "").strip().lower()
    name_hit = [h for h in REJECTED_HYPOTHESES if h.name.lower() == name_q]
    fam_hit = ([h for h in REJECTED_HYPOTHESES
                if family and h.family.lower() == family.strip().lower()]
               if family else [])
    matches = [h.to_dict() for h in (name_hit or fam_hit)]
    if name_hit:
        return {"allowed": False, "matches": matches,
                "reason": (f"hipotese '{name}' JA REJEITADA (fases "
                           f"{name_hit[0].phases}); reexecucao com tuning "
                           f"superficial BLOQUEADA. Mude estruturalmente e use "
                           f"outro nome com justificativa.")}
    just_ok = bool(structural_difference
                   and len(structural_difference.strip()) >= _MIN_JUSTIFICATION)
    if fam_hit and not just_ok:
        return {"allowed": False, "matches": matches,
                "reason": (f"familia '{family}' ja rejeitada em {len(fam_hit)} "
                           f"hipotese(s); exige justificativa de diferenca "
                           f"ESTRUTURAL (>= {_MIN_JUSTIFICATION} chars), nao "
                           f"apenas trocar parametros.")}
    return {"allowed": True, "matches": matches,
            "reason": ("ok: nome nao rejeitado" + (
                "; familia nova" if not fam_hit
                else "; familia rejeitada POReM com justificativa estrutural"))}


# ---- POLITICA FASE 63: busca preditiva BTCUSDT-only ENCERRADA ----
PREDICTIVE_SEARCH_CLOSED = True
# dados ja EXAURIDOS (38-62): qualquer hipotese DIRECIONAL BTCUSDT baseada SO
# nestes esta bloqueada; reabrir exige dado/fonte ESTRUTURALMENTE NOVO.
EXHAUSTED_DATA = {
    "ohlcv", "price", "funding", "open_interest", "oi", "volume", "calendar",
    "session", "atr", "ema", "rsi", "bb", "bollinger", "vwap", "donchian",
    "variance_ratio", "multi_asset", "regime", "vol",
}
_REOPEN_MIN_JUSTIFICATION = 80


def is_structurally_new_data(data_used) -> bool:
    return any((d or "").strip().lower() not in EXHAUSTED_DATA
               for d in (data_used or []))


def check_reopen(name: str, family: Optional[str] = None, *,
                 data_used=(), structural_difference: Optional[str] = None
                 ) -> Dict[str, Any]:
    """Guard de REABERTURA da busca preditiva (FASE 63). Alem do check_before_
    test (nome/familia), aplica a politica de ENCERRAMENTO: hipotese direcional
    BTCUSDT baseada SO em dados exauridos (OHLCV/funding/OI/...) => BLOQUEADA.
    Reabre so com (a) fonte de dados estruturalmente NOVA, OU (b) justificativa
    estrutural FORTE (>= 80 chars)."""
    base = check_before_test(name, family,
                             structural_difference=structural_difference)
    if not base["allowed"]:
        return base
    if is_structurally_new_data(data_used):
        return {"allowed": True, "matches": base["matches"],
                "reason": ("reabertura OK: usa fonte de dados ESTRUTURALMENTE "
                           "NOVA (fora de OHLCV/funding/OI exauridos).")}
    strong = bool(structural_difference
                  and len(structural_difference.strip())
                  >= _REOPEN_MIN_JUSTIFICATION)
    if strong:
        return {"allowed": True, "matches": base["matches"],
                "reason": ("reabertura com justificativa estrutural FORTE, MAS "
                           "so OHLCV/funding/OI (exauridos 38-62) => revisar com "
                           "CETICISMO; expectativa baixa.")}
    return {"allowed": False, "matches": base["matches"],
            "reason": ("BUSCA PREDITIVA BTCUSDT-only ENCERRADA (FASE 63): "
                       "hipoteses DIRECIONAIS baseadas SO em OHLCV/funding/OI "
                       "estao BLOQUEADAS apos ~25 rejeicoes (38-62). Reabrir "
                       "exige dado/fonte estruturalmente NOVO (ex.: orderbook/"
                       "L2/liquidacoes/on-chain/sentimento) OU justificativa "
                       f"estrutural FORTE (>= {_REOPEN_MIN_JUSTIFICATION} chars).")}


def registry_summary() -> Dict[str, Any]:
    by_status: Dict[str, int] = {}
    by_family: Dict[str, int] = {}
    for h in REJECTED_HYPOTHESES:
        by_status[h.status] = by_status.get(h.status, 0) + 1
        by_family[h.family] = by_family.get(h.family, 0) + 1
    return {"total": len(REJECTED_HYPOTHESES), "by_status": by_status,
            "by_family": by_family, "families": list(REJECTED_FAMILIES),
            "oos_consulted": False, "any_promoted": False,
            "demo_blocked": True, "live_blocked": True}


__all__ = ["RejectedHypothesis", "REJECTED_HYPOTHESES", "REJECTED_FAMILIES",
           "REJECTED", "REJECTED_DEFINITIVELY", "NEAR_MISS", "LINE_CLOSED",
           "find", "is_tombstoned", "check_before_test", "registry_summary",
           "PREDICTIVE_SEARCH_CLOSED", "EXHAUSTED_DATA",
           "is_structurally_new_data", "check_reopen"]
