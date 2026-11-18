"""
Primeiras hipoteses NORMAIS (FASE 53 re-escopo) — para o research loop
controlado. SO dados disponiveis: OHLCV, indicadores de preco/volume, funding,
open interest, custos, calendario/sessao. SEM orderbook/L2/liquidacoes/tick/
on-chain/dado pago. Cada spec traz o RACIONAL antes do teste (regra 2).

Estas sao PROPOSTAS (racional + por que diferem das rejeitadas 38-52.1). Os
detectores e a execucao via standard_report dual-profile (Hyro 5k + Trader
Padrao) vem APOS aprovacao do operador. Avaliacao SEMPRE pelos DOIS perfis
obrigatorios (standard_report); classificacao final candidata / edge_possivel_
incompativel_com_challenge / sem_edge_operacional.
"""

from __future__ import annotations

from typing import List

from crypto_trading_bot.research.research_loop import HypothesisSpec

_ACCEPT = ("standard_report DEV e VAL nos DOIS perfis: net>0, PF>=1,15, "
           "maxDD<=25%, retorno/DD>0, sign_consistency>=0,6; classificacao "
           "!= sem_edge_operacional. VAL so se DEV passar; OOS intocado.")


def proposed_hypotheses() -> List[HypothesisSpec]:
    return [
        HypothesisSpec(
            name="seasonality_session_bias",
            economic_rationale=(
                "BTC perp tem estrutura de SESSAO (abertura Asia/EU/US, eventos "
                "de funding 00/08/16 UTC); certos buckets de hora/dia podem ter "
                "vies de retorno persistente explorvel com hold curto."),
            why_different=(
                "Dimensao CALENDARIO/sessao, nunca usada como SINAL primario "
                "(38-52.1 foram padroes de preco/funding/vol). Nao e breakout/"
                "trend/MR; e um prior temporal."),
            data_used=["ohlcv", "calendar"],
            fixed_params={"bucket": "hour_utc", "direction_from": "DEV_mean",
                          "hold_bars": 6, "tf": "1h"},
            accept_criteria=_ACCEPT,
            expected_reason_to_work=(
                "fluxos institucionais por sessao + mecanica de funding criam "
                "viés intradia recorrente; se existir, e estavel mes a mes."),
            family="calendar", variants=1),
        HypothesisSpec(
            name="volume_climax_reversal",
            economic_rationale=(
                "pico CLIMATICO de volume (z-score extremo) marca exaustao/"
                "capitulacao de curtissimo prazo; o preco tende a reverter o "
                "overshoot logo apos o climax."),
            why_different=(
                "Gatilho e VOLUME (z-score), nao ATR/Bollinger breakout nem MR "
                "de preco puro; volume nunca foi o trigger PRIMARIO nas familias "
                "rejeitadas (era confirmacao/filtro)."),
            data_used=["ohlcv"],
            fixed_params={"vol_z_window": 50, "vol_z_trigger": 3.0,
                          "hold_bars": 8, "stop_atr": 1.5, "tf": "1h"},
            accept_criteria=_ACCEPT,
            expected_reason_to_work=(
                "climax de volume = transferencia forcada/iliquida momentanea => "
                "reversao de curto prazo enquanto a liquidez normaliza."),
            family="volume", variants=1),
        HypothesisSpec(
            name="oi_divergence_exhaustion",
            economic_rationale=(
                "preco estende mas Open Interest CAI (ou vice-versa) = movimento "
                "sem dinheiro novo (short/long covering) => exaustao => fade da "
                "extensao em direcao a media."),
            why_different=(
                "FASE 47 F2 era OI-CONFIRMED momentum (entrar COM expansao de "
                "OI). Aqui e o OPOSTO: fade na DIVERGENCIA preco-OI. Nao e "
                "funding direcional (encerrado em 52.1)."),
            data_used=["ohlcv", "open_interest"],
            fixed_params={"oi_change_k": 4, "divergence_min": 0.0,
                          "ext_lookback": 50, "hold_bars": 12, "tf": "1h"},
            accept_criteria=_ACCEPT,
            expected_reason_to_work=(
                "divergencia preco-OI sinaliza que a extensao e de cobertura, "
                "nao de iniciativa nova => reverte."),
            family="open_interest", variants=1),
    ]


__all__ = ["proposed_hypotheses"]
