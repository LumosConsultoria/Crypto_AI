"""
RiskEngine — Motor de Risco Central
=======================================
Validador soberano de todas as operações de trading.

⚠️  PRIORIDADE MÁXIMA:
    O RiskEngine tem autoridade absoluta sobre qualquer operação.
    Nenhum sinal, estratégia ou executor pode contorná-lo.
    Se o RiskEngine bloquear, a operação NÃO acontece. Ponto.

Validações implementadas:
    ✅ Stop loss obrigatório por operação
    ✅ Limite de perda diária configurável
    ✅ Limite de perda total configurável
    ✅ Limite máximo de trades por dia (anti-overtrading)
    ✅ Exposição máxima por ativo
    ✅ Alavancagem máxima permitida
    ✅ Modo seguro (bloqueia se ModeGuard inativo)
    ✅ Todas as decisões são auditadas em log

Uso:
    engine = RiskEngine(initial_capital=5000.0)
    result = engine.validate_signal(signal)

    if result.approved:
        executor.execute(signal)
    else:
        logger.warning(f"Bloqueado: {result.reason}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from crypto_trading_bot.config.risk_config import RiskConfig, get_risk_config
from crypto_trading_bot.config.settings import Settings, get_settings
from crypto_trading_bot.logging_system.logger import get_audit_logger, get_logger

_logger = get_logger(__name__)
_audit = get_audit_logger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class RiskViolation(Exception):
    """
    Exceção lançada quando uma operação viola uma regra de risco.

    NÃO use esta exceção para fluxo de controle normal — use RiskResult.
    Esta exceção indica uma violação grave que deve ser tratada explicitamente.
    """
    pass


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RiskBlockReason(str, Enum):
    """Razões de bloqueio pelo RiskEngine."""
    NO_STOP_LOSS = "no_stop_loss"
    STOP_LOSS_TOO_SMALL = "stop_loss_too_small"
    STOP_LOSS_TOO_LARGE = "stop_loss_too_large"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    TOTAL_LOSS_LIMIT = "total_loss_limit"
    MAX_TRADES_TODAY = "max_trades_today"
    EXPOSURE_LIMIT = "exposure_limit"
    LEVERAGE_LIMIT = "leverage_limit"
    UNSAFE_MODE = "unsafe_mode"
    INVALID_SIGNAL = "invalid_signal"
    CAPITAL_INSUFFICIENT = "capital_insufficient"


class OrderSide(str, Enum):
    """Lado da operação."""
    BUY = "buy"
    SELL = "sell"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TradingSignal:
    """
    Sinal de trading gerado por uma estratégia.

    Todos os campos obrigatórios devem ser preenchidos pela estratégia.
    O RiskEngine valida e pode rejeitar qualquer sinal.

    Atributos:
        symbol: Símbolo do ativo (ex: BTCUSDT)
        side: Direção da operação (buy/sell)
        entry_price: Preço pretendido de entrada
        stop_loss_price: Preço de stop loss (OBRIGATÓRIO)
        take_profit_price: Preço alvo (opcional, mas recomendado)
        position_size_usd: Tamanho da posição em USD
        leverage: Alavancagem desejada (padrão: 1.0 = sem alavancagem)
        strategy_name: Nome da estratégia que gerou o sinal
        timestamp: Momento de geração do sinal
        metadata: Dados adicionais da estratégia (para auditoria)
    """
    symbol: str
    side: OrderSide
    entry_price: float
    stop_loss_price: float
    position_size_usd: float
    strategy_name: str
    take_profit_price: Optional[float] = None
    leverage: float = 1.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict = field(default_factory=dict)

    @property
    def stop_loss_pct(self) -> float:
        """Percentual de stop loss em relação ao preço de entrada."""
        if self.entry_price <= 0:
            return 0.0
        return abs(self.entry_price - self.stop_loss_price) / self.entry_price

    @property
    def risk_reward_ratio(self) -> Optional[float]:
        """Ratio risco/retorno. None se take_profit_price não definido."""
        if self.take_profit_price is None or self.entry_price <= 0:
            return None
        potential_gain = abs(self.take_profit_price - self.entry_price)
        potential_loss = abs(self.entry_price - self.stop_loss_price)
        if potential_loss <= 0:
            return None
        return potential_gain / potential_loss


@dataclass
class RiskResult:
    """
    Resultado da validação do RiskEngine.

    Sempre retornado por validate_signal(). Nunca lança exceção no fluxo normal.

    Atributos:
        approved: True se o sinal foi aprovado para execução.
        reason: Motivo do bloqueio (vazio se aprovado).
        block_reason: Enum do motivo de bloqueio (None se aprovado).
        signal: Sinal avaliado.
        checks_passed: Lista de verificações que passaram.
        checks_failed: Lista de verificações que falharam.
    """
    approved: bool
    reason: str
    signal: TradingSignal
    block_reason: Optional[RiskBlockReason] = None
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)

    def __repr__(self) -> str:
        status = "✅ APROVADO" if self.approved else f"⛔ BLOQUEADO ({self.block_reason})"
        return f"RiskResult({status} | {self.signal.symbol} {self.signal.side.value})"


@dataclass
class DailyRiskState:
    """
    Estado de risco da sessão atual (dia corrente).

    Resetado automaticamente a cada novo dia.

    Atributos:
        date: Data da sessão
        trades_today: Número de trades executados hoje
        realized_pnl_today: PnL realizado hoje (negativo = perda)
        open_positions: Exposição aberta por ativo {symbol: usd_exposure}
    """
    date: date = field(default_factory=date.today)
    trades_today: int = 0
    realized_pnl_today: float = 0.0
    open_positions: Dict[str, float] = field(default_factory=dict)

    def total_open_exposure(self) -> float:
        """Total de exposição aberta em USD."""
        return sum(self.open_positions.values())

    def reset_if_new_day(self, today: Optional[date] = None) -> bool:
        """
        Reseta o estado se for um novo dia.

        Args:
            today: Data de referencia. Se None, usa date.today() (relogio
                real — comportamento de producao/paper/live). O backtest
                passa a DATA SIMULADA do candle para que o limite diario
                (max_trades_per_day) resete por dia simulado, e nao acumule
                como sessao unica. NUNCA enfraquece o risco — apenas torna
                a contagem diaria fiel ao tempo simulado.

        Returns:
            True se o estado foi resetado.
        """
        today = today or date.today()
        if self.date != today:
            old_date = self.date
            self.date = today
            self.trades_today = 0
            self.realized_pnl_today = 0.0
            # Exposições abertas NÃO são resetadas — posições podem continuar de um dia p/ outro
            _logger.info(f"DailyRiskState: novo dia detectado ({old_date} → {today}). Contadores resetados.")
            return True
        return False


# ---------------------------------------------------------------------------
# RiskEngine
# ---------------------------------------------------------------------------

class RiskEngine:
    """
    Motor de risco soberano.

    Toda operação DEVE passar pelo validate_signal() antes de ser executada.
    As validações são executadas em sequência — a primeira falha bloqueia o sinal.

    Exemplo:
        engine = RiskEngine(initial_capital=5000.0)

        signal = TradingSignal(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            entry_price=65000.0,
            stop_loss_price=64000.0,
            position_size_usd=500.0,
            strategy_name="example_strategy",
        )

        result = engine.validate_signal(signal)
        if result.approved:
            executor.execute(signal)
    """

    def __init__(
        self,
        initial_capital: float = 5000.0,
        config: Optional[RiskConfig] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        """
        Inicializa o RiskEngine.

        Args:
            initial_capital: Capital inicial da conta (USD). 
                             Para HyroTrader: 5000.0 USD.
            config: Configuração de risco. Se None, carrega do .env.
            settings: Configurações gerais. Se None, carrega do .env.
        """
        self._config = config or get_risk_config()
        self._settings = settings or get_settings()
        self._initial_capital = initial_capital
        self._current_capital = initial_capital
        self._daily_state = DailyRiskState()
        # Data simulada (somente backtest). None => relogio real (prod).
        self._sim_date: Optional[date] = None

        _logger.info(
            f"RiskEngine inicializado | "
            f"capital={initial_capital} | "
            f"max_daily_loss={self._config.max_daily_loss_pct:.1%} | "
            f"max_total_loss={self._config.max_total_loss_pct:.1%} | "
            f"max_trades_day={self._config.max_trades_per_day} | "
            f"max_leverage={self._config.max_leverage}x"
        )

    # -----------------------------------------------------------------------
    # Relogio simulado (somente backtest; nao usado em prod/paper/live)
    # -----------------------------------------------------------------------

    def set_simulation_date(self, sim_date: Optional[date]) -> bool:
        """Define a data SIMULADA corrente (apenas backtest).

        O BacktestEngine chama isto por candle com `candle.timestamp.date()`
        para que o limite diario (max_trades_per_day) e o PnL diario
        resetem por DIA SIMULADO — e nao acumulem como sessao unica ao
        longo de todo o backtest. Em producao/paper/live este metodo NAO
        eh chamado (sim_date permanece None => relogio real). Nao altera
        nenhuma regra de risco; apenas torna a janela diaria fiel.

        Returns:
            True se a mudanca de data resetou os contadores diarios.
        """
        self._sim_date = sim_date
        return self._daily_state.reset_if_new_day(self._sim_date)

    # -----------------------------------------------------------------------
    # Validação Principal
    # -----------------------------------------------------------------------

    def validate_signal(self, signal: TradingSignal) -> RiskResult:
        """
        Valida um sinal de trading contra todas as regras de risco.

        Executa verificações em sequência. A primeira falha bloqueia o sinal.
        Todas as decisões são registradas em log de auditoria.

        Args:
            signal: Sinal gerado pela estratégia.

        Returns:
            RiskResult com approved=True se aprovado, ou False com motivo.
        """
        # Garante que o estado diário está atualizado
        self._daily_state.reset_if_new_day(self._sim_date)

        checks_passed: List[str] = []
        checks_failed: List[str] = []

        # Definindo as verificações em ordem de prioridade
        validations = [
            ("modo_seguro", self._check_safe_mode),
            ("sinal_valido", self._check_signal_validity),
            ("stop_loss_obrigatorio", self._check_stop_loss_present),
            ("stop_loss_minimo", self._check_stop_loss_minimum),
            ("stop_loss_maximo", self._check_stop_loss_maximum),
            ("limite_perda_total", self._check_total_loss_limit),
            ("limite_perda_diaria", self._check_daily_loss_limit),
            ("maximo_trades_dia", self._check_max_trades_today),
            ("exposicao_por_ativo", self._check_asset_exposure),
            ("alavancagem_maxima", self._check_leverage),
            ("capital_suficiente", self._check_sufficient_capital),
        ]

        for check_name, check_fn in validations:
            passed, reason, block_reason = check_fn(signal)
            if passed:
                checks_passed.append(check_name)
            else:
                checks_failed.append(check_name)
                result = RiskResult(
                    approved=False,
                    reason=reason,
                    signal=signal,
                    block_reason=block_reason,
                    checks_passed=checks_passed,
                    checks_failed=checks_failed,
                )
                _audit.warning(
                    f"RiskEngine.BLOQUEADO | "
                    f"symbol={signal.symbol} | "
                    f"side={signal.side.value} | "
                    f"check={check_name} | "
                    f"reason={reason} | "
                    f"strategy={signal.strategy_name}"
                )
                return result

        # Todas as verificações passaram
        result = RiskResult(
            approved=True,
            reason="",
            signal=signal,
            block_reason=None,
            checks_passed=checks_passed,
            checks_failed=[],
        )

        _audit.info(
            f"RiskEngine.APROVADO | "
            f"symbol={signal.symbol} | "
            f"side={signal.side.value} | "
            f"entry={signal.entry_price} | "
            f"stop={signal.stop_loss_price} | "
            f"size_usd={signal.position_size_usd} | "
            f"sl_pct={signal.stop_loss_pct:.2%} | "
            f"strategy={signal.strategy_name} | "
            f"checks_passed={len(checks_passed)}"
        )

        return result

    # -----------------------------------------------------------------------
    # Atualização de Estado
    # -----------------------------------------------------------------------

    def record_trade_opened(self, signal: TradingSignal) -> None:
        """
        Registra que um trade foi aberto.

        Deve ser chamado pelo executor após a abertura de uma posição.

        Args:
            signal: Sinal que originou a operação.
        """
        self._daily_state.reset_if_new_day(self._sim_date)
        self._daily_state.trades_today += 1

        # Registra exposição aberta
        current_exposure = self._daily_state.open_positions.get(signal.symbol, 0.0)
        self._daily_state.open_positions[signal.symbol] = (
            current_exposure + signal.position_size_usd
        )

        _audit.info(
            f"RiskEngine.trade_aberto | "
            f"symbol={signal.symbol} | "
            f"side={signal.side.value} | "
            f"size_usd={signal.position_size_usd} | "
            f"trades_hoje={self._daily_state.trades_today} | "
            f"exposicao_ativo={self._daily_state.open_positions[signal.symbol]:.2f}"
        )

    def record_trade_closed(self, symbol: str, pnl: float, size_usd: float) -> None:
        """
        Registra que um trade foi fechado.

        Deve ser chamado pelo executor após o fechamento de uma posição.

        Args:
            symbol: Símbolo do ativo.
            pnl: PnL realizado (positivo = lucro, negativo = perda).
            size_usd: Tamanho da posição fechada em USD.
        """
        self._daily_state.reset_if_new_day(self._sim_date)
        self._daily_state.realized_pnl_today += pnl
        self._current_capital += pnl

        # Reduz exposição aberta
        current_exposure = self._daily_state.open_positions.get(symbol, 0.0)
        new_exposure = max(0.0, current_exposure - size_usd)
        self._daily_state.open_positions[symbol] = new_exposure

        _audit.info(
            f"RiskEngine.trade_fechado | "
            f"symbol={symbol} | "
            f"pnl={pnl:+.2f} | "
            f"capital_atual={self._current_capital:.2f} | "
            f"pnl_diario={self._daily_state.realized_pnl_today:+.2f}"
        )

        # Verificar se limites foram atingidos após o fechamento
        self._check_and_log_limit_alerts()

    def _check_and_log_limit_alerts(self) -> None:
        """Verifica e loga alertas de proximidade de limites."""
        daily_loss_pct = (
            self._daily_state.realized_pnl_today / self._initial_capital
            if self._initial_capital > 0 else 0.0
        )
        total_loss_pct = (
            (self._current_capital - self._initial_capital) / self._initial_capital
            if self._initial_capital > 0 else 0.0
        )

        # Alerta se estiver a 80% do limite diário
        if daily_loss_pct < 0 and abs(daily_loss_pct) >= self._config.max_daily_loss_pct * 0.8:
            _logger.warning(
                f"⚠️  ALERTA DE RISCO: perda diária em "
                f"{abs(daily_loss_pct):.1%} do limite de {self._config.max_daily_loss_pct:.1%}"
            )

        # Alerta se estiver a 80% do limite total
        if total_loss_pct < 0 and abs(total_loss_pct) >= self._config.max_total_loss_pct * 0.8:
            _logger.warning(
                f"⚠️  ALERTA DE RISCO: drawdown total em "
                f"{abs(total_loss_pct):.1%} do limite de {self._config.max_total_loss_pct:.1%}"
            )

    # -----------------------------------------------------------------------
    # Verificações Individuais
    # -----------------------------------------------------------------------

    def _check_safe_mode(
        self, signal: TradingSignal
    ) -> tuple[bool, str, Optional[RiskBlockReason]]:
        """Verifica se o sistema está em modo seguro."""
        if not self._settings.is_safe_mode:
            return (
                False,
                "Sistema em modo live sem aprovação pelo ModeGuard",
                RiskBlockReason.UNSAFE_MODE,
            )
        return True, "", None

    def _check_signal_validity(
        self, signal: TradingSignal
    ) -> tuple[bool, str, Optional[RiskBlockReason]]:
        """Verifica validade básica do sinal."""
        if signal.entry_price <= 0:
            return False, f"entry_price inválido: {signal.entry_price}", RiskBlockReason.INVALID_SIGNAL
        if signal.position_size_usd <= 0:
            return False, f"position_size_usd inválido: {signal.position_size_usd}", RiskBlockReason.INVALID_SIGNAL
        if signal.leverage <= 0:
            return False, f"leverage inválido: {signal.leverage}", RiskBlockReason.INVALID_SIGNAL
        if not signal.symbol:
            return False, "symbol não definido", RiskBlockReason.INVALID_SIGNAL
        return True, "", None

    def _check_stop_loss_present(
        self, signal: TradingSignal
    ) -> tuple[bool, str, Optional[RiskBlockReason]]:
        """Verifica se stop loss está definido (OBRIGATÓRIO)."""
        if signal.stop_loss_price <= 0:
            return (
                False,
                f"Stop loss obrigatório não definido (stop_loss_price={signal.stop_loss_price})",
                RiskBlockReason.NO_STOP_LOSS,
            )

        # Verifica se o stop loss está do lado correto do preço
        if signal.side == OrderSide.BUY and signal.stop_loss_price >= signal.entry_price:
            return (
                False,
                f"Stop loss (BUY) deve ser ABAIXO do preço de entrada. "
                f"entry={signal.entry_price}, stop={signal.stop_loss_price}",
                RiskBlockReason.NO_STOP_LOSS,
            )

        if signal.side == OrderSide.SELL and signal.stop_loss_price <= signal.entry_price:
            return (
                False,
                f"Stop loss (SELL) deve ser ACIMA do preço de entrada. "
                f"entry={signal.entry_price}, stop={signal.stop_loss_price}",
                RiskBlockReason.NO_STOP_LOSS,
            )

        return True, "", None

    def _check_stop_loss_minimum(
        self, signal: TradingSignal
    ) -> tuple[bool, str, Optional[RiskBlockReason]]:
        """Verifica se o stop loss respeita o mínimo configurado."""
        sl_pct = signal.stop_loss_pct
        min_sl = self._config.min_stop_loss_pct

        if sl_pct < min_sl:
            return (
                False,
                f"Stop loss muito pequeno: {sl_pct:.3%} < mínimo {min_sl:.3%}",
                RiskBlockReason.STOP_LOSS_TOO_SMALL,
            )
        return True, "", None

    def _check_stop_loss_maximum(
        self, signal: TradingSignal
    ) -> tuple[bool, str, Optional[RiskBlockReason]]:
        """Verifica se o stop loss não excede o máximo configurado."""
        sl_pct = signal.stop_loss_pct
        max_sl = self._config.max_stop_loss_pct

        if sl_pct > max_sl:
            return (
                False,
                f"Stop loss muito grande: {sl_pct:.3%} > máximo {max_sl:.3%}",
                RiskBlockReason.STOP_LOSS_TOO_LARGE,
            )
        return True, "", None

    def _check_total_loss_limit(
        self, signal: TradingSignal
    ) -> tuple[bool, str, Optional[RiskBlockReason]]:
        """Verifica se o limite de perda total foi atingido."""
        if self._initial_capital <= 0:
            return True, "", None

        total_loss_pct = (self._current_capital - self._initial_capital) / self._initial_capital

        if total_loss_pct <= -self._config.max_total_loss_pct:
            return (
                False,
                f"Limite de perda total atingido: "
                f"drawdown={abs(total_loss_pct):.2%} >= limite={self._config.max_total_loss_pct:.2%}. "
                f"Capital: {self._current_capital:.2f} / {self._initial_capital:.2f}",
                RiskBlockReason.TOTAL_LOSS_LIMIT,
            )
        return True, "", None

    def _check_daily_loss_limit(
        self, signal: TradingSignal
    ) -> tuple[bool, str, Optional[RiskBlockReason]]:
        """Verifica se o limite de perda diária foi atingido."""
        if self._initial_capital <= 0:
            return True, "", None

        daily_loss_pct = self._daily_state.realized_pnl_today / self._initial_capital

        if daily_loss_pct <= -self._config.max_daily_loss_pct:
            return (
                False,
                f"Limite de perda diária atingido: "
                f"perda_hoje={abs(daily_loss_pct):.2%} >= limite={self._config.max_daily_loss_pct:.2%}. "
                f"PnL hoje: {self._daily_state.realized_pnl_today:+.2f}",
                RiskBlockReason.DAILY_LOSS_LIMIT,
            )
        return True, "", None

    def _check_max_trades_today(
        self, signal: TradingSignal
    ) -> tuple[bool, str, Optional[RiskBlockReason]]:
        """Verifica se o limite diário de trades já foi atingido."""
        if self._daily_state.trades_today >= self._config.max_trades_per_day:
            return (
                False,
                f"Limite de trades diários atingido: "
                f"{self._daily_state.trades_today}/{self._config.max_trades_per_day}",
                RiskBlockReason.MAX_TRADES_TODAY,
            )
        return True, "", None

    def _check_asset_exposure(
        self, signal: TradingSignal
    ) -> tuple[bool, str, Optional[RiskBlockReason]]:
        """Verifica se a exposição por ativo está dentro do limite."""
        current_exposure = self._daily_state.open_positions.get(signal.symbol, 0.0)
        new_exposure = current_exposure + signal.position_size_usd
        max_exposure_usd = self._current_capital * self._config.max_exposure_per_asset_pct

        if new_exposure > max_exposure_usd:
            return (
                False,
                f"Exposição por ativo excedida para {signal.symbol}: "
                f"atual={current_exposure:.2f} + novo={signal.position_size_usd:.2f} = {new_exposure:.2f} "
                f"> limite={max_exposure_usd:.2f} ({self._config.max_exposure_per_asset_pct:.0%} do capital)",
                RiskBlockReason.EXPOSURE_LIMIT,
            )
        return True, "", None

    def _check_leverage(
        self, signal: TradingSignal
    ) -> tuple[bool, str, Optional[RiskBlockReason]]:
        """Verifica se a alavancagem está dentro do limite."""
        if signal.leverage > self._config.max_leverage:
            return (
                False,
                f"Alavancagem excedida: {signal.leverage}x > limite {self._config.max_leverage}x",
                RiskBlockReason.LEVERAGE_LIMIT,
            )
        return True, "", None

    def _check_sufficient_capital(
        self, signal: TradingSignal
    ) -> tuple[bool, str, Optional[RiskBlockReason]]:
        """Verifica se há capital suficiente para a operação."""
        required = signal.position_size_usd / max(signal.leverage, 1.0)
        if required > self._current_capital:
            return (
                False,
                f"Capital insuficiente: requerido={required:.2f} > disponível={self._current_capital:.2f}",
                RiskBlockReason.CAPITAL_INSUFFICIENT,
            )
        return True, "", None

    # -----------------------------------------------------------------------
    # Estado e Diagnóstico
    # -----------------------------------------------------------------------

    @property
    def current_capital(self) -> float:
        """Capital atual da conta."""
        return self._current_capital

    @property
    def daily_state(self) -> DailyRiskState:
        """Estado de risco do dia corrente."""
        self._daily_state.reset_if_new_day(self._sim_date)
        return self._daily_state

    def get_status_summary(self) -> dict:
        """
        Retorna um resumo do estado atual do RiskEngine.

        Útil para diagnóstico, dashboard e script check_config.
        """
        self._daily_state.reset_if_new_day(self._sim_date)

        total_pnl_pct = (
            (self._current_capital - self._initial_capital) / self._initial_capital
            if self._initial_capital > 0 else 0.0
        )
        daily_pnl_pct = (
            self._daily_state.realized_pnl_today / self._initial_capital
            if self._initial_capital > 0 else 0.0
        )

        return {
            "initial_capital": self._initial_capital,
            "current_capital": self._current_capital,
            "total_pnl_usd": self._current_capital - self._initial_capital,
            "total_pnl_pct": total_pnl_pct,
            "daily_pnl_usd": self._daily_state.realized_pnl_today,
            "daily_pnl_pct": daily_pnl_pct,
            "trades_today": self._daily_state.trades_today,
            "max_trades_today": self._config.max_trades_per_day,
            "open_positions": dict(self._daily_state.open_positions),
            "total_open_exposure": self._daily_state.total_open_exposure(),
            "limits": {
                "max_daily_loss_pct": self._config.max_daily_loss_pct,
                "max_total_loss_pct": self._config.max_total_loss_pct,
                "max_trades_per_day": self._config.max_trades_per_day,
                "max_leverage": self._config.max_leverage,
                "min_stop_loss_pct": self._config.min_stop_loss_pct,
            },
            "daily_loss_limit_used_pct": (
                abs(daily_pnl_pct) / self._config.max_daily_loss_pct
                if daily_pnl_pct < 0 else 0.0
            ),
            "total_loss_limit_used_pct": (
                abs(total_pnl_pct) / self._config.max_total_loss_pct
                if total_pnl_pct < 0 else 0.0
            ),
        }

    def __repr__(self) -> str:
        return (
            f"RiskEngine("
            f"capital={self._current_capital:.2f}, "
            f"trades_today={self._daily_state.trades_today}, "
            f"daily_pnl={self._daily_state.realized_pnl_today:+.2f})"
        )
