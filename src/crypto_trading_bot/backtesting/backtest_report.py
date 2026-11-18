"""
BacktestReport — Métricas e Relatório de Performance
=====================================================
Calcula e consolida métricas de performance de um backtest.

⚠️  AVISOS OBRIGATÓRIOS:
    1. Resultados de backtest NÃO garantem performance futura.
    2. Dados sintéticos NÃO representam condições reais de mercado.
    3. Meta de challenge (challenge_profit_target_usd) é APENAS KPI informativo.
       Nunca bloqueia trades, nunca encerra posições.
    4. Este módulo é exclusivo para backtesting — não envia ordens reais.

Métricas calculadas:
    Performance geral:
        total_trades, winning_trades, losing_trades, win_rate
        total_pnl_usd, total_pnl_pct
        avg_win_usd, avg_loss_usd, profit_factor
        initial_capital, final_capital, peak_capital

    Risco/Drawdown:
        max_drawdown_usd, max_drawdown_pct
        equity_curve (evolução do capital candle a candle)

    KPIs informativos (não bloqueantes):
        challenge_profit_target_usd
        challenge_target_reached
        account_goal_progress_pct

Uso:
    report = BacktestReport.from_trades(
        trades=closed_trades,
        initial_capital=5000.0,
        equity_curve=[5000.0, 5050.0, 5010.0, ...],
    )
    print(report.summary())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from crypto_trading_bot.backtesting.backtest_trade import BacktestTrade, CloseReason
from crypto_trading_bot.logging_system.logger import get_logger

_logger = get_logger(__name__)


@dataclass
class BacktestReport:
    """
    Relatório completo de performance de um backtest.

    Todos os campos são calculados a partir dos trades simulados e da equity curve.
    Campos de challenge são APENAS informativos — nunca bloqueiam trades.

    ⚠️  Resultados de backtest NÃO garantem performance futura.
    ⚠️  Meta de challenge (challenge_target_reached) é apenas KPI informativo.
    """

    # --- Configuração ---
    strategy_name: str
    symbol: str
    initial_capital: float
    timeframe: str = "15"
    n_candles_total: int = 0

    # --- Métricas de Trade ---
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    risk_blocked_count: int = 0       # trades não executados por bloqueio do RiskEngine
    # FASE 37.3: bloqueios agregados por categoria (ex.:
    # {"max_trades_today": 2701, "stop_loss_too_small": 120, ...}).
    risk_blocked_reasons: Dict[str, int] = field(default_factory=dict)

    # --- Métricas de PnL ---
    total_pnl_usd: float = 0.0
    total_pnl_pct: float = 0.0
    avg_win_usd: float = 0.0
    avg_loss_usd: float = 0.0         # valor negativo
    # ⚠️  CAMPOS LEGADOS (preservados para retrocompatibilidade — FASE 3D):
    # Apesar do prefixo "gross_*", estes campos somam PnL LÍQUIDO (após custos)
    # dos vencedores/perdedores. A semântica histórica é "soma por sinal de pnl_usd".
    # NÃO confundir com gross_total_pnl_usd / gross_winning_pnl_sum_usd / gross_losing_pnl_sum_usd
    # (estes sim representam métricas BRUTAS, antes de custos).
    # Para clareza, use os novos agregados explícitos da FASE 3E.2:
    #   - net_winning_pnl_sum_usd  (== gross_profit_usd, nome inequívoco)
    #   - net_losing_pnl_sum_usd   (== gross_loss_usd, nome inequívoco)
    #   - gross_winning_pnl_sum_usd / gross_losing_pnl_sum_usd (BRUTOS de verdade)
    gross_profit_usd: float = 0.0
    gross_loss_usd: float = 0.0
    largest_win_usd: float = 0.0
    largest_loss_usd: float = 0.0     # valor negativo

    # --- Capital ---
    final_capital: float = 0.0
    peak_capital: float = 0.0

    # --- Drawdown ---
    max_drawdown_usd: float = 0.0    # valor negativo (queda do pico ao vale)
    max_drawdown_pct: float = 0.0    # porcentagem negativa

    # --- Equity Curve ---
    equity_curve: List[float] = field(default_factory=list)

    # --- Trades Individuais ---
    trades: List[BacktestTrade] = field(default_factory=list)

    # --- KPIs de Challenge (APENAS INFORMATIVOS — nunca bloqueantes) ---
    # ⚠️  Meta de lucro não bloqueia trades.
    # ⚠️  Lucro é métrica de performance, não trava de segurança.
    challenge_profit_target_usd: Optional[float] = None

    # --- FASE 3E.1 — Agregados de custos de execução ---
    # ⚠️  Zero quando ExecutionCostConfig zerado (compat. FASE 3D.5).
    # ⚠️  total_pnl_usd CONTINUA sendo o PnL líquido/realizado.
    gross_total_pnl_usd: float = 0.0    # soma de gross_pnl_usd dos trades
    net_total_pnl_usd: float = 0.0      # = total_pnl_usd (alias semântico)
    total_fees_usd: float = 0.0         # entry_fee + exit_fee somados
    total_slippage_usd: float = 0.0     # entry_slippage + exit_slippage somados
    total_execution_cost_usd: float = 0.0  # fees + slippage

    # --- FASE 3E.2 — Agregados net/gross com classificação SEPARADA ---
    # net_*: classificação pelo sinal de pnl_usd (LÍQUIDO).
    # gross_*: classificação pelo sinal de gross_pnl_usd (BRUTO, antes de custos).
    # ⚠️  Com custos > 0, um trade pode ser bruto vencedor (gross_pnl_usd > 0)
    #     mas líquido perdedor (pnl_usd <= 0). As classificações DIVERGEM nesse caso.
    # ⚠️  Com custo zero, gross_* == net_* exatamente.
    net_winning_pnl_sum_usd: float = 0.0
    net_losing_pnl_sum_usd: float = 0.0
    gross_winning_pnl_sum_usd: float = 0.0
    gross_losing_pnl_sum_usd: float = 0.0

    # -----------------------------------------------------------------------
    # Propriedades Calculadas
    # -----------------------------------------------------------------------

    @property
    def win_rate(self) -> float:
        """Taxa de acerto como percentual (0-100). 0.0 se sem trades."""
        if self.total_trades == 0:
            return 0.0
        return round(self.winning_trades / self.total_trades * 100, 2)

    @property
    def loss_rate(self) -> float:
        """Taxa de perda como percentual (0-100)."""
        if self.total_trades == 0:
            return 0.0
        return round(self.losing_trades / self.total_trades * 100, 2)

    @property
    def profit_factor(self) -> Optional[float]:
        """
        Gross profit / |Gross loss|.
        None se não houver trades perdedores (divisão por zero).
        > 1.0 = lucrativo; < 1.0 = não lucrativo.
        """
        if self.gross_loss_usd >= 0.0:
            return None
        return round(abs(self.gross_profit_usd / self.gross_loss_usd), 4)

    @property
    def return_pct(self) -> float:
        """Retorno total como % do capital inicial."""
        if self.initial_capital == 0:
            return 0.0
        return round((self.final_capital - self.initial_capital) / self.initial_capital * 100, 4)

    @property
    def avg_trade_pnl_usd(self) -> float:
        """PnL médio por trade em USD."""
        if self.total_trades == 0:
            return 0.0
        return round(self.total_pnl_usd / self.total_trades, 4)

    # --- KPIs de Challenge (APENAS INFORMATIVOS) ---

    @property
    def challenge_target_reached(self) -> bool:
        """
        True se o PnL total atingiu a meta de challenge.
        APENAS INFORMATIVO — não encerra backtest, não bloqueia trades.
        O backtest sempre roda até o fim dos dados.
        """
        if self.challenge_profit_target_usd is None:
            return False
        return self.total_pnl_usd >= self.challenge_profit_target_usd

    @property
    def account_goal_progress_pct(self) -> float:
        """
        Progresso em relação à meta de challenge (0-100+%).
        APENAS INFORMATIVO — não bloqueia trades.
        Pode ser > 100% se o PnL superou a meta.
        0.0 se meta não configurada ou PnL negativo.
        """
        if self.challenge_profit_target_usd is None or self.challenge_profit_target_usd <= 0:
            return 0.0
        pct = (self.total_pnl_usd / self.challenge_profit_target_usd) * 100
        return round(max(0.0, pct), 2)

    # -----------------------------------------------------------------------
    # FASE 3E.2 — Métricas Avançadas
    # Todas derivam de self.trades + agregados; nenhuma altera o engine.
    # Política de None: retorna None quando o cálculo não é válido (sem trades,
    # divisão por zero), consistente com profit_factor legado.
    # -----------------------------------------------------------------------

    @property
    def expectancy_usd(self) -> float:
        """
        PnL esperado por trade em USD (média ponderada).

        Fórmula: (win_rate/100) × avg_win_usd + (loss_rate/100) × avg_loss_usd
        Usa PnL LÍQUIDO (avg_win_usd / avg_loss_usd já são líquidos).

        Cenários:
            sem trades       → 0.0
            só vencedores    → avg_win_usd
            só perdedores    → avg_loss_usd (negativo)
        """
        if self.total_trades == 0:
            return 0.0
        win_frac = self.winning_trades / self.total_trades
        loss_frac = self.losing_trades / self.total_trades
        return round(win_frac * self.avg_win_usd + loss_frac * self.avg_loss_usd, 4)

    @property
    def payoff_ratio(self) -> Optional[float]:
        """
        Payoff ratio LÍQUIDO: avg_win_usd / |avg_loss_usd|.

        Cenários:
            sem trades                  → None
            só vencedores (sem losses)  → None (divisão por zero)
            só perdedores (avg_win=0)   → 0.0
            misto válido                → float > 0
        """
        if self.total_trades == 0:
            return None
        if abs(self.avg_loss_usd) == 0.0:
            return None
        if self.avg_win_usd == 0.0:
            return 0.0
        return round(self.avg_win_usd / abs(self.avg_loss_usd), 4)

    @property
    def net_payoff_ratio(self) -> Optional[float]:
        """Alias semântico explícito de payoff_ratio (já líquido)."""
        return self.payoff_ratio

    @property
    def gross_payoff_ratio(self) -> Optional[float]:
        """
        Payoff ratio BRUTO: avg(gross_pnl_usd dos brutos vencedores) /
        |avg(gross_pnl_usd dos brutos perdedores)|.

        ⚠️  Classificação por sinal de gross_pnl_usd (NÃO usa is_winner).
        ⚠️  Com custo zero, idêntico a net_payoff_ratio.
        ⚠️  Com custos > 0, pode divergir.
        """
        n_wins = 0
        n_losses = 0
        for t in self.trades:
            g = t.gross_pnl_usd if t.gross_pnl_usd is not None else t.pnl_usd
            if g is None:
                continue
            if g > 0:
                n_wins += 1
            else:
                n_losses += 1
        if n_wins == 0 and n_losses == 0:
            return None
        if n_losses == 0:
            return None  # sem perdedores brutos
        gross_avg_loss = self.gross_losing_pnl_sum_usd / n_losses
        if abs(gross_avg_loss) == 0.0:
            return None
        if n_wins == 0:
            return 0.0
        gross_avg_win = self.gross_winning_pnl_sum_usd / n_wins
        return round(gross_avg_win / abs(gross_avg_loss), 4)

    @property
    def net_profit_factor(self) -> Optional[float]:
        """
        Profit factor LÍQUIDO: |net_winning_pnl_sum_usd / net_losing_pnl_sum_usd|.

        Numericamente igual ao profit_factor legado (apenas alias claro).
        None quando não há perdedores líquidos (divisão por zero).
        """
        if self.net_losing_pnl_sum_usd >= 0.0:
            return None
        return round(
            abs(self.net_winning_pnl_sum_usd / self.net_losing_pnl_sum_usd), 4
        )

    @property
    def gross_profit_factor(self) -> Optional[float]:
        """
        Profit factor BRUTO: |gross_winning_pnl_sum_usd / gross_losing_pnl_sum_usd|.

        ⚠️  Usa classificação por sinal de gross_pnl_usd.
        ⚠️  Com custo zero, idêntico a net_profit_factor.
        ⚠️  Com custos > 0, pode divergir.
        None quando não há perdedores brutos.
        """
        if self.gross_losing_pnl_sum_usd >= 0.0:
            return None
        return round(
            abs(self.gross_winning_pnl_sum_usd / self.gross_losing_pnl_sum_usd), 4
        )

    @property
    def max_consecutive_wins(self) -> int:
        """
        Máxima sequência consecutiva de vencedores LÍQUIDOS (is_winner).

        Cenários:
            sem trades      → 0
            só vencedores   → total_trades
            só perdedores   → 0
            alternados      → 1
        """
        max_streak = 0
        current = 0
        for t in self.trades:
            if t.is_winner:
                current += 1
                if current > max_streak:
                    max_streak = current
            else:
                current = 0
        return max_streak

    @property
    def max_consecutive_losses(self) -> int:
        """Máxima sequência consecutiva de perdedores LÍQUIDOS (is_loser)."""
        max_streak = 0
        current = 0
        for t in self.trades:
            if t.is_loser:
                current += 1
                if current > max_streak:
                    max_streak = current
            else:
                current = 0
        return max_streak

    @property
    def avg_trade_duration_candles(self) -> float:
        """
        Duração média dos trades em candles.
        Trades sem exit_candle_idx são ignorados no cálculo.
        Retorna 0.0 se não houver trades com duração calculável.
        """
        durations = [
            t.duration_candles for t in self.trades
            if t.duration_candles is not None
        ]
        if not durations:
            return 0.0
        return round(sum(durations) / len(durations), 2)

    @property
    def risk_reward_realized_avg(self) -> Optional[float]:
        """
        R:R realizado médio = média de (pnl_usd / risk_usd_inicial).

        risk_usd_inicial é calculado a partir de entry_price_theoretical
        (preferido) ou entry_price (fallback compat. FASE 3D.5), usando:
            BUY:  risk_per_unit = entry - stop_loss_price
            SELL: risk_per_unit = stop_loss_price - entry
            risk_usd = (risk_per_unit / entry) × position_size_usd

        Trades com risk_usd <= 0 (sinal inválido) ou pnl_usd None são ignorados.

        Cenários típicos:
            todos com SL atingido         → próximo a -1.0
            todos com TP atingido em 2:1  → próximo a +2.0
            sem trades válidos            → None
        """
        if not self.trades:
            return None
        rr_values: List[float] = []
        for t in self.trades:
            entry_theo = (
                t.entry_price_theoretical
                if t.entry_price_theoretical is not None
                else t.entry_price
            )
            if entry_theo <= 0 or t.stop_loss_price <= 0 or t.position_size_usd <= 0:
                continue
            if t.side == "buy":
                risk_per_unit = entry_theo - t.stop_loss_price
            else:
                risk_per_unit = t.stop_loss_price - entry_theo
            if risk_per_unit <= 0:
                continue
            risk_usd = (risk_per_unit / entry_theo) * t.position_size_usd
            if risk_usd <= 0 or t.pnl_usd is None:
                continue
            rr_values.append(t.pnl_usd / risk_usd)
        if not rr_values:
            return None
        return round(sum(rr_values) / len(rr_values), 4)

    @property
    def stop_loss_count(self) -> int:
        """Número de trades fechados por stop loss."""
        return sum(1 for t in self.trades if t.close_reason == CloseReason.STOP_LOSS)

    @property
    def take_profit_count(self) -> int:
        """Número de trades fechados por take profit."""
        return sum(1 for t in self.trades if t.close_reason == CloseReason.TAKE_PROFIT)

    @property
    def end_of_data_count(self) -> int:
        """Número de trades fechados por fim dos dados."""
        return sum(1 for t in self.trades if t.close_reason == CloseReason.END_OF_DATA)

    # -----------------------------------------------------------------------
    # Factory Method
    # -----------------------------------------------------------------------

    @classmethod
    def from_trades(
        cls,
        trades: List[BacktestTrade],
        initial_capital: float,
        equity_curve: List[float],
        strategy_name: str = "unknown",
        symbol: str = "BTCUSDT",
        timeframe: str = "15",
        n_candles_total: int = 0,
        risk_blocked_count: int = 0,
        risk_blocked_reasons: Optional[Dict[str, int]] = None,
        challenge_profit_target_usd: Optional[float] = None,
    ) -> "BacktestReport":
        """
        Constrói o relatório a partir de uma lista de BacktestTrade.

        Args:
            trades:                      Lista de trades simulados (fechados).
            initial_capital:             Capital inicial do backtest.
            equity_curve:                Lista de valores de capital por candle.
            strategy_name:               Nome da estratégia.
            symbol:                      Símbolo negociado.
            timeframe:                   Timeframe dos candles.
            n_candles_total:             Total de candles no dataset.
            risk_blocked_count:          Trades não executados por bloqueio do RiskEngine.
            challenge_profit_target_usd: Meta de challenge em USD (APENAS KPI).

        Returns:
            BacktestReport com todas as métricas calculadas.
        """
        closed_trades = [t for t in trades if not t.is_open and t.pnl_usd is not None]

        total_trades = len(closed_trades)
        winning = [t for t in closed_trades if t.is_winner]
        losing = [t for t in closed_trades if t.is_loser]

        winning_trades = len(winning)
        losing_trades = len(losing)

        total_pnl_usd = sum(t.pnl_usd for t in closed_trades if t.pnl_usd is not None)
        gross_profit_usd = sum(t.pnl_usd for t in winning if t.pnl_usd is not None)
        gross_loss_usd = sum(t.pnl_usd for t in losing if t.pnl_usd is not None)

        avg_win_usd = (
            round(gross_profit_usd / winning_trades, 4)
            if winning_trades > 0 else 0.0
        )
        avg_loss_usd = (
            round(gross_loss_usd / losing_trades, 4)
            if losing_trades > 0 else 0.0
        )

        largest_win = max((t.pnl_usd for t in winning if t.pnl_usd is not None), default=0.0)
        largest_loss = min((t.pnl_usd for t in losing if t.pnl_usd is not None), default=0.0)

        final_capital = initial_capital + total_pnl_usd

        total_pnl_pct = (
            round(total_pnl_usd / initial_capital * 100, 4)
            if initial_capital > 0 else 0.0
        )

        # Calcula peak capital e max drawdown a partir da equity curve
        peak_capital, max_drawdown_usd, max_drawdown_pct = _calculate_drawdown(
            equity_curve=equity_curve,
            initial_capital=initial_capital,
        )

        # FASE 3E.1 — Agregados de custos de execução
        # Soma campos que existem nos trades; zero quando ExecutionCostConfig zerado.
        total_fees_usd = sum(
            (t.entry_fee_usd or 0.0) + (t.exit_fee_usd or 0.0)
            for t in closed_trades
        )
        total_slippage_usd = sum(
            (t.entry_slippage_cost_usd or 0.0) + (t.exit_slippage_cost_usd or 0.0)
            for t in closed_trades
        )
        total_execution_cost_usd = total_fees_usd + total_slippage_usd
        gross_total_pnl_usd = sum(
            (t.gross_pnl_usd if t.gross_pnl_usd is not None else (t.pnl_usd or 0.0))
            for t in closed_trades
        )
        net_total_pnl_usd = total_pnl_usd  # alias semântico

        # FASE 3E.2 — Agregados net/gross com CLASSIFICAÇÃO SEPARADA
        # net_*: usa sinal de pnl_usd (LÍQUIDO)
        # gross_*: usa sinal de gross_pnl_usd (BRUTO, antes de custos)
        # Trade bruto vencedor / líquido perdedor entra em buckets diferentes.
        net_winning_pnl_sum_usd = sum(
            t.pnl_usd for t in closed_trades
            if t.pnl_usd is not None and t.pnl_usd > 0
        )
        net_losing_pnl_sum_usd = sum(
            t.pnl_usd for t in closed_trades
            if t.pnl_usd is not None and t.pnl_usd <= 0
        )

        def _gross_value(t: BacktestTrade) -> Optional[float]:
            """Retorna gross_pnl_usd; fallback para pnl_usd (compat. FASE 3D.5)."""
            return t.gross_pnl_usd if t.gross_pnl_usd is not None else t.pnl_usd

        gross_winning_pnl_sum_usd = sum(
            _gross_value(t) for t in closed_trades
            if _gross_value(t) is not None and _gross_value(t) > 0
        )
        gross_losing_pnl_sum_usd = sum(
            _gross_value(t) for t in closed_trades
            if _gross_value(t) is not None and _gross_value(t) <= 0
        )

        report = cls(
            strategy_name=strategy_name,
            symbol=symbol,
            initial_capital=initial_capital,
            timeframe=timeframe,
            n_candles_total=n_candles_total,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            risk_blocked_count=risk_blocked_count,
            risk_blocked_reasons=dict(risk_blocked_reasons or {}),
            total_pnl_usd=round(total_pnl_usd, 4),
            total_pnl_pct=total_pnl_pct,
            avg_win_usd=avg_win_usd,
            avg_loss_usd=avg_loss_usd,
            gross_profit_usd=round(gross_profit_usd, 4),
            gross_loss_usd=round(gross_loss_usd, 4),
            largest_win_usd=round(largest_win, 4),
            largest_loss_usd=round(largest_loss, 4),
            final_capital=round(final_capital, 4),
            peak_capital=round(peak_capital, 4),
            max_drawdown_usd=round(max_drawdown_usd, 4),
            max_drawdown_pct=round(max_drawdown_pct, 4),
            equity_curve=equity_curve,
            trades=closed_trades,
            challenge_profit_target_usd=challenge_profit_target_usd,
            # FASE 3E.1 — agregados de custos
            gross_total_pnl_usd=round(gross_total_pnl_usd, 4),
            net_total_pnl_usd=round(net_total_pnl_usd, 4),
            total_fees_usd=round(total_fees_usd, 4),
            total_slippage_usd=round(total_slippage_usd, 4),
            total_execution_cost_usd=round(total_execution_cost_usd, 4),
            # FASE 3E.2 — agregados net/gross com classificação separada
            net_winning_pnl_sum_usd=round(net_winning_pnl_sum_usd, 4),
            net_losing_pnl_sum_usd=round(net_losing_pnl_sum_usd, 4),
            gross_winning_pnl_sum_usd=round(gross_winning_pnl_sum_usd, 4),
            gross_losing_pnl_sum_usd=round(gross_losing_pnl_sum_usd, 4),
        )

        _logger.info(
            f"BacktestReport gerado | "
            f"strategy={strategy_name} | symbol={symbol} | "
            f"trades={total_trades} | win_rate={report.win_rate:.1f}% | "
            f"pnl={total_pnl_usd:+.2f}USD | "
            f"max_dd={max_drawdown_usd:.2f}USD ({max_drawdown_pct:.2f}%)"
        )

        return report

    # -----------------------------------------------------------------------
    # Formatação
    # -----------------------------------------------------------------------

    def summary(self, verbose: bool = True) -> str:
        """
        Retorna um resumo textual do relatório de backtest.

        ⚠️  Resultados de backtest NÃO garantem performance futura.
        """
        lines = [
            "",
            "=" * 60,
            "  📊 RELATÓRIO DE BACKTEST",
            "  ⚠️  Resultados NÃO garantem performance futura.",
            "  ⚠️  Dados sintéticos NÃO representam mercado real.",
            "=" * 60,
            f"  Estratégia:  {self.strategy_name}",
            f"  Símbolo:     {self.symbol}",
            f"  Timeframe:   {self.timeframe}",
            f"  Candles:     {self.n_candles_total}",
            "",
            "─" * 60,
            "  📈 PERFORMANCE",
            "─" * 60,
            f"  Capital inicial:   ${self.initial_capital:>10,.2f}",
            f"  Capital final:     ${self.final_capital:>10,.2f}",
            f"  Retorno total:     {self.total_pnl_usd:>+10.2f} USD ({self.return_pct:+.2f}%)",
            f"  Capital de pico:   ${self.peak_capital:>10,.2f}",
            "",
            "─" * 60,
            "  🎯 TRADES",
            "─" * 60,
            f"  Total de trades:       {self.total_trades:>6}",
            f"  Vencedores:            {self.winning_trades:>6}  ({self.win_rate:.1f}%)",
            f"  Perdedores:            {self.losing_trades:>6}  ({self.loss_rate:.1f}%)",
            f"  Bloqueados (risco):    {self.risk_blocked_count:>6}",
            f"  Stop loss:             {self.stop_loss_count:>6}",
            f"  Take profit:           {self.take_profit_count:>6}",
            f"  Fim dos dados:         {self.end_of_data_count:>6}",
            f"  Média ganho/trade:     ${self.avg_win_usd:>+9.2f}",
            f"  Média perda/trade:     ${self.avg_loss_usd:>+9.2f}",
            f"  Maior ganho:           ${self.largest_win_usd:>+9.2f}",
            f"  Maior perda:           ${self.largest_loss_usd:>+9.2f}",
        ]

        if self.profit_factor is not None:
            lines.append(f"  Profit Factor:         {self.profit_factor:>9.2f}")
        else:
            lines.append(f"  Profit Factor:         {'N/A':>9}")

        lines += [
            "",
            "─" * 60,
            "  📉 DRAWDOWN",
            "─" * 60,
            f"  Máximo drawdown:   ${self.max_drawdown_usd:>+9.2f}",
            f"  Máximo drawdown %: {self.max_drawdown_pct:>9.2f}%",
        ]

        # FASE 3E.2 — Métricas avançadas (sempre presentes, "N/A" quando não calculável).
        def _fmt(v, fmt="{:>9.2f}"):
            return fmt.format(v) if v is not None else f"{'N/A':>9}"

        lines += [
            "",
            "─" * 60,
            "  📐 MÉTRICAS AVANÇADAS",
            "─" * 60,
            f"  Expectancy/trade:      ${self.expectancy_usd:>+9.2f}",
            f"  Payoff ratio (net):    {_fmt(self.net_payoff_ratio)}",
            f"  Payoff ratio (gross):  {_fmt(self.gross_payoff_ratio)}",
            f"  Profit factor (net):   {_fmt(self.net_profit_factor)}",
            f"  Profit factor (gross): {_fmt(self.gross_profit_factor)}",
            f"  R:R realizado (médio): {_fmt(self.risk_reward_realized_avg)}",
            f"  Duração média:         {self.avg_trade_duration_candles:>9.2f} candles",
            f"  Máx. vitórias consec.: {self.max_consecutive_wins:>9}",
            f"  Máx. perdas consec.:   {self.max_consecutive_losses:>9}",
        ]

        # FASE 3E.1 — Custos de execução (apenas quando > 0; preserva summary
        # antigo quando ExecutionCostConfig zerado).
        if self.total_execution_cost_usd > 0:
            lines += [
                "",
                "─" * 60,
                "  💰 CUSTOS DE EXECUÇÃO",
                "─" * 60,
                f"  PnL bruto:             ${self.gross_total_pnl_usd:>+9.2f}",
                f"  PnL líquido:           ${self.net_total_pnl_usd:>+9.2f}",
                f"  Fees totais:           ${self.total_fees_usd:>+9.2f}",
                f"  Slippage + spread:     ${self.total_slippage_usd:>+9.2f}",
                f"  Custo total execução:  ${self.total_execution_cost_usd:>+9.2f}",
            ]

        # KPIs de challenge (apenas se configurados)
        if self.challenge_profit_target_usd is not None:
            lines += [
                "",
                "─" * 60,
                "  🏆 KPI DE CHALLENGE (apenas informativo — não bloqueia trades)",
                "─" * 60,
                f"  Meta de lucro:         ${self.challenge_profit_target_usd:>9,.2f}",
                f"  PnL atingido:          ${self.total_pnl_usd:>+9.2f}",
                f"  Progresso:             {self.account_goal_progress_pct:>8.1f}%",
                f"  Meta atingida:         {'✅ SIM' if self.challenge_target_reached else '❌ NÃO':>9}",
                "  ⚠️  Meta NÃO encerra backtest. Bot continua até fim dos dados.",
            ]

        lines += [
            "",
            "=" * 60,
        ]

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Serializa o relatório para dicionário (para logs, JSON, etc.)."""
        return {
            "strategy_name":             self.strategy_name,
            "symbol":                    self.symbol,
            "timeframe":                 self.timeframe,
            "n_candles_total":           self.n_candles_total,
            "initial_capital":           self.initial_capital,
            "final_capital":             self.final_capital,
            "peak_capital":              self.peak_capital,
            "total_pnl_usd":             self.total_pnl_usd,
            "total_pnl_pct":             self.total_pnl_pct,
            "return_pct":                self.return_pct,
            "total_trades":              self.total_trades,
            "winning_trades":            self.winning_trades,
            "losing_trades":             self.losing_trades,
            "win_rate":                  self.win_rate,
            "loss_rate":                 self.loss_rate,
            "risk_blocked_count":        self.risk_blocked_count,
            "risk_blocked_reasons":      dict(self.risk_blocked_reasons),
            "stop_loss_count":           self.stop_loss_count,
            "take_profit_count":         self.take_profit_count,
            "end_of_data_count":         self.end_of_data_count,
            "avg_win_usd":               self.avg_win_usd,
            "avg_loss_usd":              self.avg_loss_usd,
            "largest_win_usd":           self.largest_win_usd,
            "largest_loss_usd":          self.largest_loss_usd,
            "gross_profit_usd":          self.gross_profit_usd,
            "gross_loss_usd":            self.gross_loss_usd,
            "profit_factor":             self.profit_factor,
            "avg_trade_pnl_usd":         self.avg_trade_pnl_usd,
            "max_drawdown_usd":          self.max_drawdown_usd,
            "max_drawdown_pct":          self.max_drawdown_pct,
            # KPIs de challenge (apenas informativos)
            "challenge_profit_target_usd":  self.challenge_profit_target_usd,
            "challenge_target_reached":     self.challenge_target_reached,
            "account_goal_progress_pct":   self.account_goal_progress_pct,
            "equity_curve_length":          len(self.equity_curve),
            # FASE 3E.1 — agregados de custos de execução (zero quando custo zero)
            "gross_total_pnl_usd":          self.gross_total_pnl_usd,
            "net_total_pnl_usd":            self.net_total_pnl_usd,
            "total_fees_usd":               self.total_fees_usd,
            "total_slippage_usd":           self.total_slippage_usd,
            "total_execution_cost_usd":     self.total_execution_cost_usd,
            # FASE 3E.2 — agregados net/gross com classificação separada
            "net_winning_pnl_sum_usd":      self.net_winning_pnl_sum_usd,
            "net_losing_pnl_sum_usd":       self.net_losing_pnl_sum_usd,
            "gross_winning_pnl_sum_usd":    self.gross_winning_pnl_sum_usd,
            "gross_losing_pnl_sum_usd":     self.gross_losing_pnl_sum_usd,
            # FASE 3E.2 — métricas avançadas
            "expectancy_usd":               self.expectancy_usd,
            "payoff_ratio":                 self.payoff_ratio,
            "net_payoff_ratio":             self.net_payoff_ratio,
            "gross_payoff_ratio":           self.gross_payoff_ratio,
            "net_profit_factor":            self.net_profit_factor,
            "gross_profit_factor":          self.gross_profit_factor,
            "max_consecutive_wins":         self.max_consecutive_wins,
            "max_consecutive_losses":       self.max_consecutive_losses,
            "avg_trade_duration_candles":   self.avg_trade_duration_candles,
            "risk_reward_realized_avg":     self.risk_reward_realized_avg,
        }

    def __repr__(self) -> str:
        return (
            f"BacktestReport("
            f"strategy={self.strategy_name!r} | "
            f"trades={self.total_trades} | "
            f"win_rate={self.win_rate:.1f}% | "
            f"pnl={self.total_pnl_usd:+.2f}USD | "
            f"max_dd={self.max_drawdown_usd:.2f}USD)"
        )


# ---------------------------------------------------------------------------
# Funções Auxiliares
# ---------------------------------------------------------------------------

def _calculate_drawdown(
    equity_curve: List[float],
    initial_capital: float,
) -> tuple[float, float, float]:
    """
    Calcula peak capital, max drawdown em USD e max drawdown em %.

    O drawdown é calculado como a maior queda do pico ao vale
    ao longo da equity curve.

    Args:
        equity_curve:    Lista de valores de capital por ponto.
        initial_capital: Capital inicial.

    Returns:
        (peak_capital, max_drawdown_usd, max_drawdown_pct)
        max_drawdown_usd é negativo (queda)
        max_drawdown_pct é negativo (% de queda)
    """
    if not equity_curve:
        return initial_capital, 0.0, 0.0

    peak = initial_capital
    max_dd_usd = 0.0
    max_dd_pct = 0.0

    for capital in equity_curve:
        if capital > peak:
            peak = capital

        drawdown = capital - peak
        drawdown_pct = (drawdown / peak * 100) if peak > 0 else 0.0

        if drawdown < max_dd_usd:
            max_dd_usd = drawdown
            max_dd_pct = drawdown_pct

    return peak, max_dd_usd, max_dd_pct
