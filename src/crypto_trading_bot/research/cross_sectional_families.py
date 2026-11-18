"""
Hipoteses CROSS-SECTIONAL (FASE 60). Cada detector e um SCAN/RANKING que, a cada
barra, escolhe NO MAXIMO 1 ativo elegivel (sem basket). Params PRE-FIXADOS; sem
grid; causal/anti-lookahead. Stop estrutural por ATR do ativo (piso 0,5%
soberano: setups<piso descartados). Saida por tempo no backtest.

H1 relative_strength_continuation_5m: regime amplo favoravel (basket up) => LONG
   o ativo de MAIOR forca relativa (outperformer); evita operar em queda ampla.
H2 relative_reversion_after_dispersion_5m: dispersao EXTREMA do basket + ativo
   mais esticado REVERTENDO => fade controlado de volta a media do basket.
H3 btc_lead_lag_alt_follow_5m: BTC lider; entra no ALT que ATRASOU (gap medido)
   na direcao do BTC, com confirmacao causal (alt ja virando na direcao).
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Dict, List, Optional

from crypto_trading_bot.research.cross_sectional import Universe, XSetup, mk_xsetup
from crypto_trading_bot.research.perp_signals import causal_percentile_rank

H1_PARAMS = {"lookback": 12, "reg_thr": 0.0, "k_atr": 2.0, "rr": 1.5}
H2_PARAMS = {"lookback": 12, "disp_pctile": 0.85, "k_atr": 2.0, "rr": 1.5}
H3_PARAMS = {"lookback": 12, "move_thr": 0.005, "k_atr": 2.0, "rr": 1.5}
HOLD_BARS = 24


def _valid_atr(u: Universe, sym: str, i: int) -> Optional[float]:
    a = u.atr[sym][i]
    return a if (not math.isnan(a) and a > 0) else None


def detect_relative_strength_continuation(
    u: Universe, *, params: Optional[Dict[str, Any]] = None) -> List[XSetup]:
    p = {**H1_PARAMS, **(params or {})}
    L = int(p["lookback"]); reg = float(p["reg_thr"])
    k = float(p["k_atr"]); rr = float(p["rr"])
    out: List[XSetup] = []
    for i in range(max(L, 20), u.n):
        rets = {s: u.ret(s, i, L) for s in u.symbols}
        if any(v is None for v in rets.values()):
            continue
        basket = statistics.mean(rets.values())
        if basket <= reg:                          # evita queda ampla
            continue
        s_star = max(u.symbols, key=lambda s: rets[s])
        if rets[s_star] <= basket:                 # so outperformer
            continue
        a = _valid_atr(u, s_star, i)
        c = u.closes[s_star][i]
        if a is None or c <= 0:
            continue
        s = mk_xsetup(u.timestamps[i], s_star, i, "long", c, c - k * a, rr)
        if s is not None:
            out.append(s)
    return out


def detect_relative_reversion_after_dispersion(
    u: Universe, *, params: Optional[Dict[str, Any]] = None) -> List[XSetup]:
    p = {**H2_PARAMS, **(params or {})}
    L = int(p["lookback"]); k = float(p["k_atr"]); rr = float(p["rr"])
    pct = float(p["disp_pctile"])
    dispersion: List[Optional[float]] = [None] * u.n
    dev_by_i: Dict[int, Dict[str, float]] = {}
    for i in range(max(L, 20), u.n):
        rets = {s: u.ret(s, i, L) for s in u.symbols}
        if any(v is None for v in rets.values()):
            continue
        basket = statistics.mean(rets.values())
        dev = {s: rets[s] - basket for s in u.symbols}
        dev_by_i[i] = dev
        dispersion[i] = statistics.pstdev(dev.values())
    disp_pct = causal_percentile_rank(dispersion, window=200)
    out: List[XSetup] = []
    for i in range(max(L, 20), u.n):
        if disp_pct[i] is None or disp_pct[i] < pct or i not in dev_by_i:
            continue
        dev = dev_by_i[i]
        s_hi = max(u.symbols, key=lambda s: dev[s])   # esticado ACIMA
        s_lo = min(u.symbols, key=lambda s: dev[s])   # esticado ABAIXO
        cand = None
        # reversao: ativo esticado vira na barra atual
        hi_rev = u.closes[s_hi][i] < u.closes[s_hi][i - 1]   # virando p/ baixo
        lo_rev = u.closes[s_lo][i] > u.closes[s_lo][i - 1]   # virando p/ cima
        if abs(dev[s_hi]) >= abs(dev[s_lo]) and hi_rev:
            cand = (s_hi, "short")
        elif lo_rev:
            cand = (s_lo, "long")
        elif hi_rev:
            cand = (s_hi, "short")
        if cand is None:
            continue
        sym, direction = cand
        a = _valid_atr(u, sym, i)
        c = u.closes[sym][i]
        if a is None or c <= 0:
            continue
        stop = c + k * a if direction == "short" else c - k * a
        s = mk_xsetup(u.timestamps[i], sym, i, direction, c, stop, rr)
        if s is not None:
            out.append(s)
    return out


def detect_btc_lead_lag_alt_follow(
    u: Universe, *, params: Optional[Dict[str, Any]] = None) -> List[XSetup]:
    p = {**H3_PARAMS, **(params or {})}
    L = int(p["lookback"]); mv = float(p["move_thr"])
    k = float(p["k_atr"]); rr = float(p["rr"])
    btc = "BTCUSDT"
    if btc not in u.symbols:
        return []
    alts = [s for s in u.symbols if s != btc]
    out: List[XSetup] = []
    for i in range(max(L, 20), u.n):
        br = u.ret(btc, i, L)
        if br is None or abs(br) < mv:             # BTC precisa de movimento
            continue
        direction = "long" if br > 0 else "short"
        cand = []
        for s in alts:
            r = u.ret(s, i, L)
            if r is None:
                continue
            if direction == "long" and r < br and r >= 0 \
                    and u.closes[s][i] > u.closes[s][i - 1]:
                cand.append((br - r, s))           # gap de atraso + confirma
            elif direction == "short" and r > br and r <= 0 \
                    and u.closes[s][i] < u.closes[s][i - 1]:
                cand.append((r - br, s))
        if not cand:
            continue
        _, s_star = max(cand)
        a = _valid_atr(u, s_star, i)
        c = u.closes[s_star][i]
        if a is None or c <= 0:
            continue
        stop = c - k * a if direction == "long" else c + k * a
        s = mk_xsetup(u.timestamps[i], s_star, i, direction, c, stop, rr)
        if s is not None:
            out.append(s)
    return out


DETECTORS = {
    "relative_strength_continuation_5m": detect_relative_strength_continuation,
    "relative_reversion_after_dispersion_5m":
        detect_relative_reversion_after_dispersion,
    "btc_lead_lag_alt_follow_5m": detect_btc_lead_lag_alt_follow,
}

__all__ = ["DETECTORS", "HOLD_BARS", "H1_PARAMS", "H2_PARAMS", "H3_PARAMS",
           "detect_relative_strength_continuation",
           "detect_relative_reversion_after_dispersion",
           "detect_btc_lead_lag_alt_follow"]
