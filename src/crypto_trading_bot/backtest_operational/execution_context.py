"""
BacktestExecutionContext (FASE 37 Parte D)
==========================================
Contexto unico de configuracao do backtest OPERACIONAL (paridade com a
demo, porem SEM execucao real). Concentra TODOS os toggles em um objeto
imutavel com defaults SEGUROS (capacidades opcionais/perigosas OFF).

Invariantes inviolaveis (espelham as regras do operador):
  * Execucao SEMPRE simulada (`simulate_execution_only` travado em True).
  * RiskEngine soberano: piso de stop-loss = 0.005 e NUNCA reduzido aqui.
  * ModeGuard: backtest nunca eh live (live/mainnet impossiveis).
  * Nada de IA/Polymarket/MI inventado: toggles default OFF; quando ON,
    so usam dado REAL disponivel (ver context_availability.py).
  * Position management (scale-in/reducao/reversao) default OFF.

⚠️  Este objeto NAO envia ordem, NAO chama API real, NAO le secrets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

# Piso de stop-loss do RiskEngine (paridade). NUNCA reduzir aqui.
RISK_ENGINE_MIN_STOP_LOSS_PCT = 0.005


class BacktestContextError(Exception):
    """Erro de configuracao/validacao do contexto de backtest."""


@dataclass(frozen=True)
class BacktestExecutionContext:
    """Configuracao imutavel de um backtest operacional.

    Defaults sao a configuracao SEGURA: RiskEngine ON, execucao
    simulada, todos os contextos externos (IA/MI/Poly/funding/OI/
    orderbook/news) e position-management OFF, sem leverage, sem custos.
    """

    # --- Estrategia / perfil (sem hardcode: vem do operador) ---
    strategy: str = ""
    profile: Optional[str] = None

    # --- RiskEngine (soberano; parity) ---
    enforce_risk_engine: bool = True
    min_stop_loss_pct: float = RISK_ENGINE_MIN_STOP_LOSS_PCT

    # --- ModeGuard (sempre simulado; nunca live) ---
    mode_guard_simulated: bool = True
    simulate_execution_only: bool = True  # TRAVADO em True

    # --- Capital / custos / alavancagem / exposicao / ordens ---
    capital_usd: float = 0.0          # 0 => runner exige valor explicito
    fees_bps: float = 0.0             # disabled
    slippage_bps: float = 0.0         # disabled
    leverage: float = 1.0             # sem alavancagem
    max_exposure_usd: Optional[float] = None
    max_open_orders: int = 1          # sequencial (parity demo)

    # --- Position management (default OFF) ---
    enable_position_management: bool = False
    enable_scale_in: bool = False
    enable_partial_reduce: bool = False
    enable_reversal: bool = False

    # --- Contextos externos (default OFF; so dado REAL quando ON) ---
    enable_ai_context: bool = False
    enable_polymarket_context: bool = False
    enable_market_intelligence: bool = False
    enable_funding_context: bool = False
    enable_open_interest_context: bool = False
    enable_orderbook_context: bool = False
    enable_news_context: bool = False

    # Contexto AUSENTE: se opcional, continua; se obrigatorio, bloqueia.
    allow_missing_context: bool = True
    required_context_kinds: Tuple[str, ...] = field(default_factory=tuple)

    # --- Observabilidade ---
    enable_decision_trace: bool = True
    enable_readiness_gate: bool = False  # consultivo, nunca autoriza

    def __post_init__(self) -> None:
        if self.simulate_execution_only is not True:
            raise BacktestContextError(
                "simulate_execution_only e travado em True (backtest "
                "NUNCA executa ordem real)."
            )
        if not self.enforce_risk_engine:
            raise BacktestContextError(
                "enforce_risk_engine nao pode ser desligado (RiskEngine "
                "soberano em paridade com a demo)."
            )
        if self.min_stop_loss_pct < RISK_ENGINE_MIN_STOP_LOSS_PCT:
            raise BacktestContextError(
                "min_stop_loss_pct nao pode ficar abaixo do piso "
                f"{RISK_ENGINE_MIN_STOP_LOSS_PCT} (piso do RiskEngine)."
            )
        if self.leverage < 1.0:
            raise BacktestContextError("leverage deve ser >= 1.0")
        if self.fees_bps < 0 or self.slippage_bps < 0:
            raise BacktestContextError("fees/slippage bps devem ser >= 0")
        if self.max_open_orders < 1:
            raise BacktestContextError("max_open_orders deve ser >= 1")
        if self.capital_usd < 0:
            raise BacktestContextError("capital_usd deve ser >= 0")

    # ---- Propriedades de seguranca ----
    @property
    def real_execution_allowed(self) -> bool:
        """SEMPRE False. Backtest nunca envia ordem real."""
        return False

    def enabled_context_kinds(self) -> Tuple[str, ...]:
        """Kinds de contexto externo marcados como ON (toggle)."""
        mapping = {
            "ai": self.enable_ai_context,
            "polymarket": self.enable_polymarket_context,
            "market_intelligence": self.enable_market_intelligence,
            "funding": self.enable_funding_context,
            "open_interest": self.enable_open_interest_context,
            "orderbook": self.enable_orderbook_context,
            "news": self.enable_news_context,
        }
        return tuple(k for k, on in mapping.items() if on)

    def to_dict(self) -> dict:
        return {
            "schema": "backtest_execution_context_v1",
            "strategy": self.strategy,
            "profile": self.profile,
            "enforce_risk_engine": self.enforce_risk_engine,
            "min_stop_loss_pct": self.min_stop_loss_pct,
            "mode_guard_simulated": self.mode_guard_simulated,
            "simulate_execution_only": self.simulate_execution_only,
            "real_execution_allowed": self.real_execution_allowed,
            "capital_usd": self.capital_usd,
            "fees_bps": self.fees_bps,
            "slippage_bps": self.slippage_bps,
            "leverage": self.leverage,
            "max_exposure_usd": self.max_exposure_usd,
            "max_open_orders": self.max_open_orders,
            "enable_position_management": self.enable_position_management,
            "enable_scale_in": self.enable_scale_in,
            "enable_partial_reduce": self.enable_partial_reduce,
            "enable_reversal": self.enable_reversal,
            "enabled_context_kinds": list(self.enabled_context_kinds()),
            "allow_missing_context": self.allow_missing_context,
            "required_context_kinds": list(self.required_context_kinds),
            "enable_decision_trace": self.enable_decision_trace,
            "enable_readiness_gate": self.enable_readiness_gate,
        }


__all__ = [
    "BacktestContextError",
    "BacktestExecutionContext",
    "RISK_ENGINE_MIN_STOP_LOSS_PCT",
]
