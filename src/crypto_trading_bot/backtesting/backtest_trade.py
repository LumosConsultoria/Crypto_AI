"""
BacktestTrade — Registro de Trade Simulado no Backtest
=======================================================
Dataclass imutável que representa um trade simulado durante o backtest.

⚠️  Este módulo é EXCLUSIVO para backtesting.
    Não envia ordens reais. Não conecta APIs. Não usa API keys.

Ciclo de vida de um BacktestTrade:
    1. OPEN  → RiskEngine aprova sinal → trade aberto no candle de entrada
    2. CLOSED_SL  → candle futuro tem low <= stop_loss_price
    3. CLOSED_TP  → candle futuro tem high >= take_profit_price
    4. CLOSED_EOD → fim dos dados — posição fechada ao preço do último candle

Regra de ambiguidade (stop e take profit no mesmo candle):
    ⚠️  Se um candle tiver low <= stop_loss E high >= take_profit,
    considera-se que o STOP LOSS foi atingido PRIMEIRO.
    Motivo: abordagem conservadora — evita superestimar performance.
    Esta decisão está documentada em docs/backtesting.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class CloseReason(str, Enum):
    """Motivo de encerramento do trade simulado."""
    STOP_LOSS = "stop_loss"                # stop loss atingido
    TAKE_PROFIT = "take_profit"            # take profit atingido
    END_OF_DATA = "end_of_data"            # fim dos dados históricos
    RISK_BLOCKED = "risk_blocked"          # não aberto — RiskEngine bloqueou
    # FASE 12 — disponíveis apenas quando ExitPolicy está integrada (opt-in).
    # NÃO removem nem reordenam valores existentes (compat. de serialização).
    TIME_LIMIT = "time_limit"              # fechamento por tempo máximo
    OPPOSITE_SIGNAL = "opposite_signal"    # fechamento por sinal contrário


@dataclass
class BacktestTrade:
    """
    Registro de um trade simulado no backtesting.

    Campos de entrada (preenchidos na abertura):
        symbol          : Símbolo negociado (ex: "BTCUSDT")
        strategy_name   : Nome da estratégia que gerou o sinal
        entry_candle_idx: Índice do candle de entrada (para auditoria)
        entry_time      : Timestamp do candle de entrada
        entry_price     : Preço de entrada (close do candle de entrada)
        stop_loss_price : Preço de stop loss obrigatório
        take_profit_price: Preço de take profit (opcional)
        position_size_usd: Tamanho da posição em USD
        side            : "buy" ou "sell"

    Campos de saída (preenchidos no fechamento):
        exit_candle_idx : Índice do candle de saída
        exit_time       : Timestamp do candle de saída
        exit_price      : Preço de saída
        close_reason    : Motivo do fechamento (CloseReason)
        pnl_usd         : PnL realizado em USD (positivo = lucro)
        pnl_pct         : PnL como % do position_size_usd

    Propriedades calculadas:
        is_open         : True se trade ainda não foi fechado
        is_winner       : True se pnl_usd > 0
        duration_candles: Quantidade de candles que o trade ficou aberto
    """

    # --- Campos de entrada (obrigatórios na abertura) ---
    symbol: str
    strategy_name: str
    entry_candle_idx: int
    entry_time: datetime
    entry_price: float
    stop_loss_price: float
    take_profit_price: Optional[float]
    position_size_usd: float
    side: str = "buy"

    # --- Campos de saída (preenchidos no fechamento) ---
    exit_candle_idx: Optional[int] = field(default=None)
    exit_time: Optional[datetime] = field(default=None)
    exit_price: Optional[float] = field(default=None)
    close_reason: Optional[CloseReason] = field(default=None)
    # pnl_usd e pnl_pct representam o PnL REALIZADO/LÍQUIDO (após custos).
    # Com ExecutionCostConfig zerado, pnl_usd == gross_pnl_usd exatamente.
    pnl_usd: Optional[float] = field(default=None)
    pnl_pct: Optional[float] = field(default=None)

    # --- FASE 3E.1: Campos de execução com custos (retrocompatíveis) ---
    # Todos opcionais/zero por default → comportamento da FASE 3D.5 preservado.
    entry_price_theoretical: Optional[float] = field(default=None)
    exit_price_theoretical: Optional[float] = field(default=None)
    entry_fee_usd: float = field(default=0.0)
    exit_fee_usd: float = field(default=0.0)
    entry_slippage_cost_usd: float = field(default=0.0)
    exit_slippage_cost_usd: float = field(default=0.0)
    gross_pnl_usd: Optional[float] = field(default=None)
    gross_pnl_pct: Optional[float] = field(default=None)

    # --- Metadados ---
    trade_id: str = field(default="")

    # --- FASE 12: snapshot opcional da ExitDecision (quando ExitPolicy ativa) ---
    # None por default → preserva comportamento legado e serialização da FASE 3E.
    # to_dict() inclui esta chave apenas quando o snapshot não for None.
    exit_decision_snapshot: Optional[dict] = field(default=None)

    def __post_init__(self) -> None:
        """Valida campos obrigatórios e gera ID único."""
        if self.entry_price <= 0:
            raise ValueError(f"entry_price deve ser positivo: {self.entry_price}")
        if self.stop_loss_price <= 0:
            raise ValueError(f"stop_loss_price deve ser positivo: {self.stop_loss_price}")
        if self.position_size_usd <= 0:
            raise ValueError(f"position_size_usd deve ser positivo: {self.position_size_usd}")
        if self.side not in ("buy", "sell"):
            raise ValueError(f"side deve ser 'buy' ou 'sell': {self.side}")

        # Valida direção do stop loss
        if self.side == "buy" and self.stop_loss_price >= self.entry_price:
            raise ValueError(
                f"Para BUY, stop_loss_price ({self.stop_loss_price}) "
                f"deve ser < entry_price ({self.entry_price})"
            )
        if self.side == "sell" and self.stop_loss_price <= self.entry_price:
            raise ValueError(
                f"Para SELL, stop_loss_price ({self.stop_loss_price}) "
                f"deve ser > entry_price ({self.entry_price})"
            )

        # Gera ID único se não fornecido
        if not self.trade_id:
            ts = self.entry_time.strftime("%Y%m%d_%H%M%S")
            self.trade_id = f"BT_{self.symbol}_{self.side.upper()}_{ts}_{self.entry_candle_idx}"

    @property
    def is_open(self) -> bool:
        """True se o trade ainda não foi fechado."""
        return self.exit_price is None

    @property
    def is_winner(self) -> bool:
        """True se o trade foi fechado com lucro. False se aberto ou perdedor."""
        if self.pnl_usd is None:
            return False
        return self.pnl_usd > 0

    @property
    def is_loser(self) -> bool:
        """True se o trade foi fechado com perda."""
        if self.pnl_usd is None:
            return False
        return self.pnl_usd <= 0

    @property
    def duration_candles(self) -> Optional[int]:
        """Quantidade de candles que o trade ficou aberto. None se ainda aberto."""
        if self.exit_candle_idx is None:
            return None
        return self.exit_candle_idx - self.entry_candle_idx

    @property
    def risk_reward_ratio(self) -> Optional[float]:
        """R:R teórico (take_profit / stop_loss distance). None se sem TP."""
        if self.take_profit_price is None:
            return None
        if self.side == "buy":
            risk = self.entry_price - self.stop_loss_price
            reward = self.take_profit_price - self.entry_price
        else:
            risk = self.stop_loss_price - self.entry_price
            reward = self.entry_price - self.take_profit_price
        if risk <= 0:
            return None
        return round(reward / risk, 2)

    @property
    def total_execution_cost_usd(self) -> float:
        """
        Custo total de execução do trade (fees + slippage) em USD.
        Zero se nenhum custo foi aplicado.
        """
        return round(
            self.entry_fee_usd
            + self.exit_fee_usd
            + self.entry_slippage_cost_usd
            + self.exit_slippage_cost_usd,
            4,
        )

    def close(
        self,
        exit_candle_idx: int,
        exit_time: datetime,
        exit_price: float,
        close_reason: CloseReason,
        exit_price_theoretical: Optional[float] = None,
        entry_fee_usd: float = 0.0,
        exit_fee_usd: float = 0.0,
        entry_slippage_cost_usd: float = 0.0,
        exit_slippage_cost_usd: float = 0.0,
        exit_decision_snapshot: Optional[dict] = None,
    ) -> None:
        """
        Fecha o trade e calcula PnL bruto e líquido.

        Args:
            exit_candle_idx:         Índice do candle de saída.
            exit_time:               Timestamp do candle de saída.
            exit_price:              Preço de saída EXECUTADO (após slippage/spread).
                                     Em backtests sem custos é igual ao preço teórico.
            close_reason:            Motivo do fechamento.
            exit_price_theoretical:  Preço de saída TEÓRICO (sem custos).
                                     None → assume igual a exit_price (FASE 3D.5).
            entry_fee_usd:           Fee paga na entrada (>= 0).
            exit_fee_usd:            Fee paga na saída (>= 0).
            entry_slippage_cost_usd: Custo de slippage+spread na entrada em USD (>= 0).
            exit_slippage_cost_usd:  Custo de slippage+spread na saída em USD (>= 0).

        Raises:
            ValueError: Se o trade já estiver fechado.
        """
        if not self.is_open:
            raise ValueError(f"Trade {self.trade_id} já está fechado.")

        self.exit_candle_idx = exit_candle_idx
        self.exit_time = exit_time
        self.exit_price = exit_price
        self.close_reason = close_reason
        # FASE 12 — armazena snapshot apenas se fornecido (default None preserva legado)
        if exit_decision_snapshot is not None:
            self.exit_decision_snapshot = dict(exit_decision_snapshot)

        # Registra custos do leg de saída + acumula leg de entrada (se foi setado fora)
        self.exit_fee_usd = float(exit_fee_usd)
        self.exit_slippage_cost_usd = float(exit_slippage_cost_usd)
        if entry_fee_usd:
            self.entry_fee_usd = float(entry_fee_usd)
        if entry_slippage_cost_usd:
            self.entry_slippage_cost_usd = float(entry_slippage_cost_usd)
        if exit_price_theoretical is not None:
            self.exit_price_theoretical = float(exit_price_theoretical)
        else:
            # Sem custos → teórico == executado (compat. FASE 3D.5)
            self.exit_price_theoretical = float(exit_price)

        # --- PnL LÍQUIDO (realizado, após slippage/spread no preço executado) ---
        # BUY: lucro se exit > entry; SELL: lucro se exit < entry
        if self.side == "buy":
            price_diff_executed = exit_price - self.entry_price
        else:
            price_diff_executed = self.entry_price - exit_price

        # PnL após slippage: usa preços executados (entry e exit já ajustados)
        # Subtrai fees para obter PnL líquido final realizado.
        price_pct_executed = price_diff_executed / self.entry_price
        net_pnl_before_fees = price_pct_executed * self.position_size_usd
        net_pnl_after_fees = net_pnl_before_fees - self.entry_fee_usd - self.exit_fee_usd

        self.pnl_usd = round(net_pnl_after_fees, 4)
        self.pnl_pct = round(net_pnl_after_fees / self.position_size_usd * 100, 4)

        # --- PnL BRUTO (teórico, ignorando slippage/spread/fees) ---
        # Usa preços teóricos quando disponíveis; caso contrário usa executados.
        entry_theo = (
            self.entry_price_theoretical
            if self.entry_price_theoretical is not None
            else self.entry_price
        )
        exit_theo = (
            self.exit_price_theoretical
            if self.exit_price_theoretical is not None
            else self.exit_price
        )
        if self.side == "buy":
            price_diff_theo = exit_theo - entry_theo
        else:
            price_diff_theo = entry_theo - exit_theo
        price_pct_theo = price_diff_theo / entry_theo if entry_theo > 0 else 0.0
        self.gross_pnl_usd = round(price_pct_theo * self.position_size_usd, 4)
        self.gross_pnl_pct = round(price_pct_theo * 100, 4)

    def to_dict(self) -> dict:
        """Serializa o trade para dicionário (para relatórios e CSV).

        FASE 12: exit_decision_snapshot só é incluído quando não-None
        (preserva schema legado quando ExitPolicy está desligada).
        """
        d = {
            "trade_id":           self.trade_id,
            "symbol":             self.symbol,
            "strategy_name":      self.strategy_name,
            "side":               self.side,
            "entry_candle_idx":   self.entry_candle_idx,
            "entry_time":         self.entry_time.isoformat() if self.entry_time else None,
            "entry_price":        self.entry_price,
            "stop_loss_price":    self.stop_loss_price,
            "take_profit_price":  self.take_profit_price,
            "position_size_usd":  self.position_size_usd,
            "exit_candle_idx":    self.exit_candle_idx,
            "exit_time":          self.exit_time.isoformat() if self.exit_time else None,
            "exit_price":         self.exit_price,
            "close_reason":       self.close_reason.value if self.close_reason else None,
            "pnl_usd":            self.pnl_usd,
            "pnl_pct":            self.pnl_pct,
            "duration_candles":   self.duration_candles,
            "is_winner":          self.is_winner,
            "risk_reward_ratio":  self.risk_reward_ratio,
            # FASE 3E.1 — custos de execução (zero quando ExecutionCostConfig zerado)
            "entry_price_theoretical":    self.entry_price_theoretical,
            "exit_price_theoretical":     self.exit_price_theoretical,
            "entry_fee_usd":              self.entry_fee_usd,
            "exit_fee_usd":               self.exit_fee_usd,
            "entry_slippage_cost_usd":    self.entry_slippage_cost_usd,
            "exit_slippage_cost_usd":     self.exit_slippage_cost_usd,
            "gross_pnl_usd":              self.gross_pnl_usd,
            "gross_pnl_pct":              self.gross_pnl_pct,
            "total_execution_cost_usd":   self.total_execution_cost_usd,
        }
        if self.exit_decision_snapshot is not None:
            d["exit_decision_snapshot"] = dict(self.exit_decision_snapshot)
        return d

    def __repr__(self) -> str:
        status = "OPEN" if self.is_open else (
            f"{'WIN' if self.is_winner else 'LOSS'} "
            f"PnL={self.pnl_usd:+.2f}USD"
        )
        return (
            f"BacktestTrade("
            f"id={self.trade_id} | "
            f"{self.side.upper()} {self.symbol} @ {self.entry_price} | "
            f"size={self.position_size_usd}USD | "
            f"{status})"
        )
