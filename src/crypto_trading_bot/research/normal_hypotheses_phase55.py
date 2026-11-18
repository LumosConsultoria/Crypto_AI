"""
FASE 55 — agenda de hipoteses NORMAIS (racional antes do teste). SO dados
disponiveis (OHLCV/volume/funding/OI/custos/calendario/derivados). Estrutural-
mente DIFERENTES das familias ja rejeitadas (38-54): NAO sao breakout/trend/vol
simples, MR simples, funding direcional, OI momentum simples, calendario simples,
volume-climax simples nem OI-divergence-fade simples. Aqui o diferencial e o
CONDICIONAMENTO (regime + filtro de volatilidade + confirmacao OI/funding) e o
BAIXO TURNOVER (poucos trades de alta qualidade, hold mais longo).

Avaliacao SEMPRE pelos DOIS perfis (standard_report): Hyro 5k (leitura principal
= hyro_challenge_attempts, multiplas tentativas) + Trader Padrao 5k (leitura
principal = standard_trader_monthly_close). Classificacao candidata_paper /
edge_possivel_incompativel_com_challenge / sem_edge_operacional.
"""

from __future__ import annotations

from typing import List

from crypto_trading_bot.research.research_loop import HypothesisSpec

_ACCEPT = ("DEV e VAL nos DOIS perfis (standard_report): Hyro via "
           "hyro_challenge_attempts (pass_rate>=0,50) E Trader Padrao via "
           "standard_trader_monthly_close (net>0, PF>=1,15, maxDD<=25%, "
           "retorno/DD>0, sign_consistency mensal>=0,6). VAL so se DEV passar; "
           "OOS intocado.")


def proposed_hypotheses_phase55() -> List[HypothesisSpec]:
    return [
        HypothesisSpec(
            name="trend_pullback_regime_gated",
            economic_rationale=(
                "em tendencia ESTABELECIDA e volatilidade CALMA (nem morta nem "
                "caotica), pullbacks a media tendem a retomar a direcao; operar "
                "so nesse regime evita os periodos ruins (chop/vol extrema)."),
            why_different=(
                "NAO e trend/breakout simples: e DUPLAMENTE condicionada "
                "(regime de tendencia + banda de volatilidade) com entrada por "
                "PULLBACK e hold longo/baixo turnover; o filtro de regime "
                "suprime operacao fora do contexto favoravel."),
            data_used=["ohlcv"],
            fixed_params={"ema_fast": 20, "ema_slow": 50, "slope_k": 12,
                          "vol_lo": 0.20, "vol_hi": 0.70, "pullback_atr": 0.6,
                          "swing_lookback": 20, "rr": 2.0, "hold_bars": 48,
                          "tf": "1h"},
            accept_criteria=_ACCEPT,
            expected_reason_to_work=(
                "continuacao de tendencia apos pullback tem follow-through "
                "quando o regime macro e estavel; o gate de vol corta ruido."),
            family="regime_setup", variants=1),
        HypothesisSpec(
            name="range_reversion_regime_gated",
            economic_rationale=(
                "em regime de RANGE CONFIRMADO (slope ~0 + volatilidade "
                "comprimida), extremos do canal revertem a media; fora de range "
                "(tendencia) NAO operar."),
            why_different=(
                "NAO e mean-reversion simples: a reversao e CONDICIONADA a um "
                "regime de range confirmado (slope baixo + vol comprimida + "
                "preco dentro do canal por N barras); alvo na MEDIA do canal, "
                "nao R-multiplo cego."),
            data_used=["ohlcv"],
            fixed_params={"ema_fast": 20, "ema_slow": 50, "flat_thr": 0.0035,
                          "vol_max": 0.40, "ch_lookback": 24, "hi": 0.85,
                          "lo": 0.15, "hold_bars": 24, "tf": "1h"},
            accept_criteria=_ACCEPT,
            expected_reason_to_work=(
                "em range, desvios da media sao temporarios; o gate de regime "
                "evita fade contra tendencia (causa classica de ruina do MR)."),
            family="regime_reversal", variants=1),
        HypothesisSpec(
            name="breakout_oi_funding_confirmed",
            economic_rationale=(
                "rompimento APOS compressao (squeeze) com EXPANSAO de Open "
                "Interest (dinheiro novo) e funding NAO sobre-posicionado tende "
                "a ter follow-through; sem confirmacao de OI, breakout falha."),
            why_different=(
                "NAO e breakout/vol simples nem OI-momentum simples: e a "
                "COMBINACAO compressao->expansao + confirmacao de OI + GATE de "
                "funding (rejeita lado lotado), hold longo, pouquissimos trades "
                "de alta qualidade."),
            data_used=["ohlcv", "open_interest", "funding"],
            fixed_params={"width_lookback": 50, "squeeze_pct": 0.30,
                          "donch": 20, "fund_hi": 0.85, "fund_lo": 0.15,
                          "rr": 2.5, "hold_bars": 48, "tf": "1h"},
            accept_criteria=_ACCEPT,
            expected_reason_to_work=(
                "expansao pos-squeeze confirmada por OI novo + funding nao-"
                "extremo filtra os falsos rompimentos que mataram o breakout "
                "puro."),
            family="compression_confirmed", variants=1),
    ]


__all__ = ["proposed_hypotheses_phase55"]
