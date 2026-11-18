"""
Calibration Cost Scenarios (FASE 37.4)
======================================
Cenarios de custo de execucao ROTULADOS para o "cost realism" da
calibracao offline. Estes valores sao PARAMETROS DE SIMULACAO de
pesquisa — NAO sao a tabela real de taxas de nenhuma exchange e NAO sao
limite de risco. O operador pode sobrescrever por flag e deve substituir
por valores reais antes de qualquer decisao operacional.

Rotulos:
    zero_cost          -> sem custo (baseline puro).
    realistic_research -> aproximacao ilustrativa (taker ~0.06%,
                          slippage ~0.05%, spread ~0.02%).
    stressed_research  -> ~2x o realista (teste de robustez a custo).

⚠️  ZERO rede / ordem / secret. So constroi ExecutionCostConfig.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from crypto_trading_bot.backtesting.execution_costs import (
    ExecutionCostConfig,
)

# Defaults de PESQUISA (ilustrativos; NAO sao taxa real de exchange).
_REALISTIC_TAKER_FEE_PCT = 0.0006   # 0.06%
_REALISTIC_SLIPPAGE_PCT = 0.0005    # 0.05%
_REALISTIC_SPREAD_PCT = 0.0002      # 0.02%

COST_SCENARIO_LABELS: Tuple[str, ...] = (
    "zero_cost", "realistic_research", "stressed_research",
)


@dataclass(frozen=True)
class CostScenario:
    """Um cenario de custo nomeado/rotulado para a calibracao."""
    label: str
    config: ExecutionCostConfig
    is_research_illustrative: bool   # True => NAO e taxa real de exchange

    def to_dict(self) -> dict:
        c = self.config
        return {
            "label": self.label,
            "is_research_illustrative": self.is_research_illustrative,
            "taker_fee_pct": c.taker_fee_pct,
            "slippage_pct": c.slippage_pct,
            "spread_pct": c.spread_pct,
            "entry_latency_candles": c.entry_latency_candles,
        }


def build_cost_scenario(
    label: str,
    *,
    fees_bps: Optional[float] = None,
    slippage_bps: Optional[float] = None,
    spread_bps: Optional[float] = None,
    entry_latency_candles: int = 0,
) -> CostScenario:
    """Constroi um CostScenario rotulado.

    Overrides (em BPS) tem precedencia sobre os defaults de pesquisa. Se
    qualquer override for informado, o cenario continua marcado como
    research_illustrative=True (pois ainda nao foi validado como tabela
    real); use rotulo proprio se fornecer valores reais.
    """
    lbl = str(label).strip().lower()
    if lbl == "zero_cost":
        return CostScenario(
            label="zero_cost",
            config=ExecutionCostConfig(
                entry_latency_candles=max(0, int(entry_latency_candles))),
            is_research_illustrative=False,  # zero e neutro/honesto
        )

    if fees_bps is not None or slippage_bps is not None or \
            spread_bps is not None:
        cfg = ExecutionCostConfig(
            taker_fee_pct=(fees_bps or 0.0) / 10000.0,
            slippage_pct=(slippage_bps or 0.0) / 10000.0,
            spread_pct=(spread_bps or 0.0) / 10000.0,
            entry_latency_candles=max(0, int(entry_latency_candles)),
        )
        return CostScenario(label=lbl, config=cfg,
                            is_research_illustrative=True)

    if lbl == "realistic_research":
        cfg = ExecutionCostConfig(
            taker_fee_pct=_REALISTIC_TAKER_FEE_PCT,
            slippage_pct=_REALISTIC_SLIPPAGE_PCT,
            spread_pct=_REALISTIC_SPREAD_PCT,
            entry_latency_candles=max(0, int(entry_latency_candles)),
        )
        return CostScenario(label="realistic_research", config=cfg,
                            is_research_illustrative=True)

    if lbl == "stressed_research":
        cfg = ExecutionCostConfig(
            taker_fee_pct=_REALISTIC_TAKER_FEE_PCT * 2,
            slippage_pct=_REALISTIC_SLIPPAGE_PCT * 2,
            spread_pct=_REALISTIC_SPREAD_PCT * 2,
            entry_latency_candles=max(1, int(entry_latency_candles or 1)),
        )
        return CostScenario(label="stressed_research", config=cfg,
                            is_research_illustrative=True)

    raise ValueError(
        f"cenario de custo desconhecido: {label!r}. "
        f"Aceitos: {list(COST_SCENARIO_LABELS)} (ou override por bps)."
    )


def default_cost_sweep(
    *, entry_latency_candles: int = 0,
) -> List[CostScenario]:
    """Sweep padrao: zero_cost -> realistic_research -> stressed_research.

    Todos os custos != zero sao ROTULADOS research_illustrative.
    """
    return [
        build_cost_scenario("zero_cost",
                            entry_latency_candles=entry_latency_candles),
        build_cost_scenario("realistic_research",
                            entry_latency_candles=entry_latency_candles),
        build_cost_scenario("stressed_research",
                            entry_latency_candles=entry_latency_candles),
    ]


__all__ = [
    "COST_SCENARIO_LABELS",
    "CostScenario",
    "build_cost_scenario",
    "default_cost_sweep",
]
