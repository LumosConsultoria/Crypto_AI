"""
ExecutionCostConfig — Modelagem de Custos de Execução para Backtesting
========================================================================
Modela custos realistas de execução em backtesting offline:
    - Fees (taker/maker) percentuais sobre o notional da posição.
    - Slippage percentual (ajuste adverso de preço).
    - Slippage fixo no preço (ajuste em USD do preço do ativo).
    - Spread percentual (custo de cruzar bid-ask).
    - Spread fixo no preço (ajuste em USD do preço do ativo).

⚠️  AVISOS OBRIGATÓRIOS:
    1. Este módulo é EXCLUSIVO para backtesting.
    2. ZERO ordens reais. ZERO API real. ZERO API key.
    3. Custos modelados aqui são uma APROXIMAÇÃO — não substituem testes
       em ambiente paper/testnet reais.
    4. Resultados de backtest NÃO garantem performance futura.
    5. Custo zero (ExecutionCostConfig() sem argumentos) preserva
       integralmente o comportamento da FASE 3D.5.

CONVENÇÕES DE NOMENCLATURA:
    - `*_pct` → fração decimal (0.0006 = 0.06%).
    - `*_fixed_price_usd` → ajuste em USD aplicado AO PREÇO do ativo
      (ex: BTC executado 5 USD mais caro). NÃO é custo financeiro do trade.
    - `*_fee_usd` (em outros módulos) → custo financeiro em USD do trade.

DIREÇÃO ADVERSA (slippage/spread sempre pioram a execução):
    BUY entry: preço executado > preço teórico (compra mais caro).
    BUY exit:  preço executado < preço teórico (vende mais barato).
    SELL entry: preço executado < preço teórico (vende mais barato).
    SELL exit:  preço executado > preço teórico (cobre mais caro).

DETECÇÃO DE STOP/TP:
    A detecção de hit (candle.low <= stop_loss_price etc.) continua usando
    o preço TEÓRICO, não o preço executado. Slippage/spread ajustam apenas
    o preço de saída APÓS o hit ser detectado. A regra conservadora de
    ambiguidade (stop tem prioridade sobre TP) permanece inalterada.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ExecutionCostConfig:
    """
    Configuração imutável de custos de execução para o backtesting.

    Todos os campos têm default zero. Instanciar sem argumentos
    (`ExecutionCostConfig()`) preserva o comportamento da FASE 3D.5.

    Atributos:
        taker_fee_pct:           Fee de taker (mercado) em fração decimal.
                                 Ex: 0.0006 = 0.06%.
        maker_fee_pct:           Fee de maker (limit) em fração decimal.
                                 Ex: 0.0002 = 0.02%.
        slippage_pct:            Ajuste percentual adverso de preço.
                                 Ex: 0.0005 = 0.05% pior por execução.
        slippage_fixed_price_usd: Ajuste fixo em USD AO PREÇO do ativo.
                                 Ex: 5.0 → BUY entry custa 5 USD a mais por unidade.
                                 NÃO é fee. É deslocamento no preço de execução.
        spread_pct:              Custo de cruzar o spread bid-ask, em fração.
                                 Ex: 0.0002 = 0.02% adicional por lado.
        spread_fixed_price_usd:  Custo de cruzar spread como ajuste fixo de preço em USD.
        fee_side:                "taker" (default) ou "maker" — qual fee aplicar.

    Convenções:
        - Todos os campos devem ser >= 0 (custos não podem ser negativos).
        - Slippage e spread se somam no preço executado.
        - Fees são percentuais sobre o notional (position_size_usd).
        - O modelo cobra fee na entrada E na saída de cada trade.
    """

    taker_fee_pct: float = 0.0
    maker_fee_pct: float = 0.0
    slippage_pct: float = 0.0
    slippage_fixed_price_usd: float = 0.0
    spread_pct: float = 0.0
    spread_fixed_price_usd: float = 0.0
    fee_side: Literal["taker", "maker"] = "taker"
    # FASE 3E.4B — Latência simulada de execução
    # Quantos candles entre a geração do sinal e sua execução efetiva.
    # 0 (default) → execução imediata no close do candle (FASE 3E.4A preservada).
    # N > 0       → pending signal; executa no `open` do candle i+N.
    entry_latency_candles: int = 0

    def __post_init__(self) -> None:
        """Valida que todos os custos são não-negativos."""
        for field_name in (
            "taker_fee_pct",
            "maker_fee_pct",
            "slippage_pct",
            "slippage_fixed_price_usd",
            "spread_pct",
            "spread_fixed_price_usd",
        ):
            value = getattr(self, field_name)
            if value < 0:
                raise ValueError(
                    f"{field_name} deve ser >= 0 (custos não podem ser negativos): {value}"
                )
        if self.fee_side not in ("taker", "maker"):
            raise ValueError(
                f"fee_side deve ser 'taker' ou 'maker': {self.fee_side!r}"
            )
        if self.entry_latency_candles < 0:
            raise ValueError(
                f"entry_latency_candles deve ser >= 0: {self.entry_latency_candles}"
            )

    @property
    def is_zero(self) -> bool:
        """
        True se todos os custos são zero E latência é zero
        (comportamento da FASE 3D.5/3E.4A preservado).
        """
        return (
            self.taker_fee_pct == 0.0
            and self.maker_fee_pct == 0.0
            and self.slippage_pct == 0.0
            and self.slippage_fixed_price_usd == 0.0
            and self.spread_pct == 0.0
            and self.spread_fixed_price_usd == 0.0
            and self.entry_latency_candles == 0
        )

    @property
    def active_fee_pct(self) -> float:
        """Fee aplicado de acordo com fee_side."""
        return self.taker_fee_pct if self.fee_side == "taker" else self.maker_fee_pct


# ---------------------------------------------------------------------------
# Resultado de aplicação de custos (estrutura imutável)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExecutionResult:
    """
    Resultado da aplicação de custos de execução em um leg do trade
    (entrada OU saída — um para cada).

    Atributos:
        price_theoretical:    Preço sem custos (referência).
        price_executed:       Preço após slippage e spread (adverso).
        fee_usd:              Fee paga no leg (>= 0).
        slippage_cost_usd:    Custo de slippage + spread no leg (>= 0),
                              expresso em USD sobre o notional.
                              É a "perda em PnL" causada pela diferença
                              entre price_theoretical e price_executed.
    """

    price_theoretical: float
    price_executed: float
    fee_usd: float
    slippage_cost_usd: float


# ---------------------------------------------------------------------------
# Funções puras de aplicação de custos
# ---------------------------------------------------------------------------

def _price_adjustment(
    side: str,
    leg: str,
    price_theoretical: float,
    config: ExecutionCostConfig,
) -> float:
    """
    Calcula o preço executado aplicando slippage + spread na direção adversa.

    Args:
        side:              "buy" ou "sell" (lado do TRADE, não do leg).
        leg:               "entry" ou "exit".
        price_theoretical: Preço sem custos.
        config:            Configuração de custos.

    Returns:
        Preço executado (sempre pior que o teórico quando há custos).

    Direção adversa:
        BUY  + entry → executado MAIOR (compra mais caro)
        BUY  + exit  → executado MENOR (vende mais barato)
        SELL + entry → executado MENOR (vende mais barato)
        SELL + exit  → executado MAIOR (cobre mais caro)
    """
    if side not in ("buy", "sell"):
        raise ValueError(f"side deve ser 'buy' ou 'sell': {side!r}")
    if leg not in ("entry", "exit"):
        raise ValueError(f"leg deve ser 'entry' ou 'exit': {leg!r}")

    pct_adj = config.slippage_pct + config.spread_pct
    fixed_adj = config.slippage_fixed_price_usd + config.spread_fixed_price_usd

    # Determina a direção adversa: positiva = preço sobe, negativa = preço cai
    # BUY entry, SELL exit → preço sobe (pior)
    # BUY exit, SELL entry → preço cai (pior)
    sign_up = (side == "buy" and leg == "entry") or (side == "sell" and leg == "exit")

    if sign_up:
        return price_theoretical * (1 + pct_adj) + fixed_adj
    return price_theoretical * (1 - pct_adj) - fixed_adj


def apply_entry_costs(
    side: str,
    price_theoretical: float,
    position_size_usd: float,
    config: ExecutionCostConfig,
) -> ExecutionResult:
    """
    Aplica custos de execução à entrada do trade.

    Args:
        side:              "buy" ou "sell".
        price_theoretical: Preço de entrada sem custos (close do candle).
        position_size_usd: Notional da posição em USD.
        config:            Configuração de custos.

    Returns:
        ExecutionResult com price_executed (preço adverso),
        fee_usd e slippage_cost_usd.
    """
    if price_theoretical <= 0:
        raise ValueError(
            f"price_theoretical deve ser positivo: {price_theoretical}"
        )
    if position_size_usd <= 0:
        raise ValueError(
            f"position_size_usd deve ser positivo: {position_size_usd}"
        )

    price_executed = _price_adjustment(side, "entry", price_theoretical, config)
    fee_usd = position_size_usd * config.active_fee_pct
    price_drift = abs(price_executed - price_theoretical)
    slippage_cost_usd = (
        price_drift / price_theoretical * position_size_usd if price_theoretical > 0 else 0.0
    )

    return ExecutionResult(
        price_theoretical=price_theoretical,
        price_executed=price_executed,
        fee_usd=fee_usd,
        slippage_cost_usd=slippage_cost_usd,
    )


def apply_exit_costs(
    side: str,
    price_theoretical: float,
    position_size_usd: float,
    config: ExecutionCostConfig,
) -> ExecutionResult:
    """
    Aplica custos de execução à saída do trade.

    Args:
        side:              "buy" ou "sell" — lado do TRADE original.
                           Para fechar um BUY vendemos, mas o `side` aqui
                           é "buy" porque identifica o trade.
        price_theoretical: Preço teórico de saída (stop_loss_price,
                           take_profit_price ou close do último candle).
        position_size_usd: Notional da posição em USD.
        config:            Configuração de custos.

    Returns:
        ExecutionResult com price_executed (preço adverso),
        fee_usd e slippage_cost_usd.
    """
    if price_theoretical <= 0:
        raise ValueError(
            f"price_theoretical deve ser positivo: {price_theoretical}"
        )
    if position_size_usd <= 0:
        raise ValueError(
            f"position_size_usd deve ser positivo: {position_size_usd}"
        )

    price_executed = _price_adjustment(side, "exit", price_theoretical, config)
    fee_usd = position_size_usd * config.active_fee_pct
    price_drift = abs(price_executed - price_theoretical)
    slippage_cost_usd = (
        price_drift / price_theoretical * position_size_usd if price_theoretical > 0 else 0.0
    )

    return ExecutionResult(
        price_theoretical=price_theoretical,
        price_executed=price_executed,
        fee_usd=fee_usd,
        slippage_cost_usd=slippage_cost_usd,
    )
