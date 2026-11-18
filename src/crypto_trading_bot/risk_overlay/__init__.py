"""
Risk & Exposure Overlay (FASE 57) — alternativa C (operacional NAO-preditiva).
=============================================================================
Camada ADVISORY read-only: avalia posicoes + conta contra as regras de risco
(RiskConfig efetivo / HyroTrader) e emite ALERTAS + recomendacoes de reducao de
exposicao/risco. NAO preve direcao. NUNCA envia ordem. demo/live bloqueados;
RiskEngine/ModeGuard/piso 0.005 intactos. Input MANUAL/offline (sem rede).
"""

from crypto_trading_bot.risk_overlay.models import (
    Alert, AccountState, Position, RiskLimits, SEVERITY_ORDER)
from crypto_trading_bot.risk_overlay.overlay import evaluate_risk_overlay

__all__ = ["Alert", "AccountState", "Position", "RiskLimits", "SEVERITY_ORDER",
           "evaluate_risk_overlay"]
