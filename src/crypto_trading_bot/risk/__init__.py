"""
Motor de Risco
===============
Módulo de controle de risco com prioridade máxima sobre todas as estratégias.

⚠️  REGRA FUNDAMENTAL:
    O RiskEngine SEMPRE tem a palavra final sobre qualquer operação.
    Nenhuma estratégia, sinal ou executor pode contornar o RiskEngine.

Componentes:
    - RiskEngine: validador central (obrigatório para toda operação)
    - RiskState: estado de risco atual da sessão
    - RiskViolation: exceção para violações de risco

Uso:
    from crypto_trading_bot.risk import RiskEngine, RiskViolation

    engine = RiskEngine()
    result = engine.validate_signal(signal)
    if result.approved:
        executor.execute(signal)
"""

from crypto_trading_bot.risk.risk_engine import RiskEngine, RiskResult, RiskViolation

__all__ = ["RiskEngine", "RiskResult", "RiskViolation"]
