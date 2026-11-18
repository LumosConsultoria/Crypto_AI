"""
Strategy Research Framework — implementação principal (FASE 3F)
================================================================
Componentes:
    - StrategySpec: representação imutável de uma estratégia registrada.
    - StrategyRegistry: registro instanciável (não singleton global).
    - StrategyEvaluationResult: resultado de uma avaliação (single + opcional WF).
    - evaluate_strategy(): roda backtest single + opcionalmente walk-forward.
    - compare_strategies(): avalia N specs no MESMO dataset.
    - rank_strategies(): 3 rankings independentes (sem composite).
    - summarize_comparison(): tabela textual com avisos obrigatórios.

⚠️  GARANTIAS:
    - Não altera BacktestEngine, BacktestTrade, BacktestReport.
    - Não altera ExecutionCostConfig, walk_forward.py.
    - Não altera RiskEngine nem ModeGuard.
    - Sem auto-otimização de parâmetros.
    - Sem composite score (mascara trade-offs).
    - Avisos obrigatórios em todo output.
    - Provider-agnostic (zero referência a provider_name).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from crypto_trading_bot.backtesting.backtest_engine import BacktestEngine
from crypto_trading_bot.backtesting.backtest_report import BacktestReport
from crypto_trading_bot.backtesting.execution_costs import ExecutionCostConfig
from crypto_trading_bot.backtesting.walk_forward import (
    WalkForwardFoldResult,
    run_walk_forward,
    summarize_walk_forward,
)
from crypto_trading_bot.data.feature_engine import FeatureEngine
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.logging_system.logger import get_logger
from crypto_trading_bot.risk.risk_engine import RiskEngine

_logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# StrategySpec — representação imutável de uma estratégia registrada
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StrategySpec:
    """
    Representação imutável de uma estratégia registrada no framework.

    Atributos:
        name:           Identificador único (ex: "ema_rsi_default").
        factory:        Callable[[Dict[str, Any]], Any] que recebe a config
                        final e retorna uma instância pronta para uso
                        (idealmente já com set_running()).
        description:    Texto descritivo opcional.
        default_config: Configuração padrão (read-only).
        tags:           Categorias (ex: ("trend-following", "demo")).

    Proteções:
        - frozen=True (atributos não podem ser alterados após criação).
        - default_config é convertida para MappingProxyType (snapshot read-only).
        - tags é convertida para tuple imutável.
        - Mutar o dict ORIGINAL passado como default_config NÃO afeta o spec.
    """

    name: str
    factory: Callable[[Dict[str, Any]], Any]
    description: str = ""
    default_config: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    tags: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Validação básica de name
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError(
                f"StrategySpec.name deve ser string não-vazia: {self.name!r}"
            )
        if not callable(self.factory):
            raise ValueError("StrategySpec.factory deve ser callable.")

        # Garante imutabilidade de default_config:
        # tira snapshot (dict(...)) e embrulha em MappingProxyType.
        if not isinstance(self.default_config, MappingProxyType):
            object.__setattr__(
                self,
                "default_config",
                MappingProxyType(dict(self.default_config)),
            )

        # Garante que tags é tuple
        if not isinstance(self.tags, tuple):
            object.__setattr__(self, "tags", tuple(self.tags))


# ---------------------------------------------------------------------------
# StrategyRegistry — registro instanciável (sem singleton global)
# ---------------------------------------------------------------------------

class StrategyRegistry:
    """
    Registro instanciável de StrategySpec, identificado por nome único.

    ⚠️  Sem singleton global. Cada caso de uso (produção, teste) cria seu
        próprio registry. Garante isolamento total.

    Métodos:
        register(spec):    adiciona spec; lança ValueError se nome duplicado.
        get(name):         recupera spec; lança KeyError se nome desconhecido.
        list_names():      retorna nomes ORDENADOS alfabeticamente.
        clear():           limpa o registry (útil para testes).
        __contains__(name): suporte para `name in registry`.
        __len__():         número de specs registradas.
    """

    def __init__(self) -> None:
        self._specs: Dict[str, StrategySpec] = {}

    def register(self, spec: StrategySpec) -> None:
        """
        Registra uma spec.

        Raises:
            ValueError: se já existir spec com o mesmo nome (evita override
                        silencioso).
        """
        if spec.name in self._specs:
            raise ValueError(
                f"Strategy '{spec.name}' já registrada. "
                f"Para substituir, chame clear() antes."
            )
        self._specs[spec.name] = spec

    def get(self, name: str) -> StrategySpec:
        """
        Recupera spec pelo nome.

        Raises:
            KeyError: se o nome não estiver registrado.
        """
        if name not in self._specs:
            available = sorted(self._specs.keys())
            raise KeyError(
                f"Strategy '{name}' não encontrada. Disponíveis: {available}"
            )
        return self._specs[name]

    def list_names(self) -> List[str]:
        """Retorna nomes registrados em ordem alfabética."""
        return sorted(self._specs.keys())

    def clear(self) -> None:
        """Remove todas as specs registradas."""
        self._specs.clear()

    def __contains__(self, name: str) -> bool:
        return name in self._specs

    def __len__(self) -> int:
        return len(self._specs)


# ---------------------------------------------------------------------------
# StrategyEvaluationResult — resultado imutável de uma avaliação
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StrategyEvaluationResult:
    """
    Resultado imutável de uma avaliação de estratégia.

    Atributos:
        spec:                       StrategySpec avaliada.
        config_used:                Config final (default + override) read-only.
        single_report:              BacktestReport do backtest completo.
        wf_fold_results:            Tupla de WalkForwardFoldResult (None se WF não rodou).
        wf_summary:                 Sumário do walk-forward (None se WF não rodou).
        overfitting_divergence_usd: |single_pnl - mean(wf_test_pnl)| (None se WF não rodou).
                                    Quanto MAIOR, mais sinal de overfitting.
    """

    spec: StrategySpec
    config_used: Mapping[str, Any]
    single_report: BacktestReport
    wf_fold_results: Optional[Tuple[WalkForwardFoldResult, ...]] = None
    wf_summary: Optional[Mapping[str, Any]] = None
    overfitting_divergence_usd: Optional[float] = None


# ---------------------------------------------------------------------------
# evaluate_strategy: avalia 1 spec (single + opcionalmente walk-forward)
# ---------------------------------------------------------------------------

def evaluate_strategy(
    spec: StrategySpec,
    candles: List[Candle],
    *,
    config_override: Optional[Mapping[str, Any]] = None,
    initial_capital: float = 5000.0,
    min_candles: int = 50,
    symbol: str = "BTCUSDT",
    execution_cost_config: Optional[ExecutionCostConfig] = None,
    challenge_profit_target_usd: Optional[float] = None,
    walk_forward_n_folds: Optional[int] = None,
    walk_forward_train_pct: float = 0.7,
    precompute_features: bool = False,
    risk_config: Optional["RiskConfig"] = None,
    max_holding_candles: Optional[int] = None,
) -> StrategyEvaluationResult:
    """
    Avalia uma StrategySpec executando 1 backtest single + opcionalmente
    walk-forward usando run_walk_forward() existente.

    A config final é obtida por merge: {**spec.default_config, **(config_override or {})}.

    Args:
        spec:                          Strategy spec a avaliar.
        candles:                       Lista de Candle (ordem cronológica).
        config_override:               Override de config (None = usa default).
        initial_capital:               Capital inicial dos engines.
        min_candles:                   min_candles do BacktestEngine.
        symbol:                        Símbolo passado aos engines.
        execution_cost_config:         FASE 3E.1 custos opcionais (propagados para single E WF).
        challenge_profit_target_usd:   KPI propagado (NÃO bloqueia).
        walk_forward_n_folds:          Se None → só single; se int >= 2 → roda WF.
        walk_forward_train_pct:        train_pct do walk-forward (default 0.7).

    Returns:
        StrategyEvaluationResult imutável.

    Garantias:
        - Spec.default_config NÃO é mutado.
        - Strategy factory é chamada 1× para single + (2 × N) para WF (independentes).
        - RiskEngine, FeatureEngine e BacktestEngine criados frescos por avaliação.
    """
    # Merge config (snapshot, sem mutar spec.default_config)
    config_used: Dict[str, Any] = dict(spec.default_config)
    if config_override:
        config_used.update(config_override)
    config_used_readonly: Mapping[str, Any] = MappingProxyType(dict(config_used))

    # --- Single backtest ---
    strategy_single = spec.factory(dict(config_used))  # cópia defensiva
    engine_single = BacktestEngine(
        strategy=strategy_single,
        risk_engine=RiskEngine(initial_capital=initial_capital,
                               config=risk_config),
        feature_engine=FeatureEngine(),
        initial_capital=initial_capital,
        min_candles=min_candles,
        symbol=symbol,
        execution_cost_config=execution_cost_config,
        challenge_profit_target_usd=challenge_profit_target_usd,
        max_holding_candles=max_holding_candles,
    )
    single_report = engine_single.run(
        candles, precompute_features=precompute_features)

    # --- Walk-forward opcional ---
    wf_fold_results: Optional[Tuple[WalkForwardFoldResult, ...]] = None
    wf_summary_readonly: Optional[Mapping[str, Any]] = None
    overfitting_divergence_usd: Optional[float] = None

    if walk_forward_n_folds is not None:
        def factory_for_wf():
            return spec.factory(dict(config_used))

        wf_results_list = run_walk_forward(
            strategy_factory=factory_for_wf,
            candles=candles,
            n_folds=walk_forward_n_folds,
            train_pct=walk_forward_train_pct,
            initial_capital=initial_capital,
            min_candles=min_candles,
            symbol=symbol,
            execution_cost_config=execution_cost_config,
            challenge_profit_target_usd=challenge_profit_target_usd,
            precompute_features=precompute_features,
            risk_config=risk_config,
            max_holding_candles=max_holding_candles,
        )
        wf_fold_results = tuple(wf_results_list)
        wf_summary = summarize_walk_forward(wf_results_list)
        wf_summary_readonly = MappingProxyType(dict(wf_summary))

        # Divergência |single - mean(wf_test)| — alto valor sugere overfitting
        overfitting_divergence_usd = round(
            abs(single_report.total_pnl_usd - wf_summary["mean_test_pnl_usd"]),
            4,
        )

    return StrategyEvaluationResult(
        spec=spec,
        config_used=config_used_readonly,
        single_report=single_report,
        wf_fold_results=wf_fold_results,
        wf_summary=wf_summary_readonly,
        overfitting_divergence_usd=overfitting_divergence_usd,
    )


# ---------------------------------------------------------------------------
# compare_strategies: avalia múltiplas specs no mesmo dataset
# ---------------------------------------------------------------------------

def compare_strategies(
    specs: Sequence[StrategySpec],
    candles: List[Candle],
    **runner_kwargs,
) -> List[StrategyEvaluationResult]:
    """
    Avalia múltiplas specs no MESMO dataset com os MESMOS parâmetros de runner.

    ⚠️  Sem otimização. Sem parameter sweep.
    ⚠️  Ordem do retorno PRESERVA a ordem de entrada (determinístico).

    Args:
        specs:           Sequência de StrategySpec a comparar.
        candles:         Dataset comum a todas as specs.
        **runner_kwargs: Argumentos repassados para evaluate_strategy
                         (initial_capital, execution_cost_config,
                          walk_forward_n_folds, etc.).

    Returns:
        Lista de StrategyEvaluationResult, na ordem de entrada.
    """
    return [
        evaluate_strategy(spec, candles, **runner_kwargs) for spec in specs
    ]


# ---------------------------------------------------------------------------
# Ranking — 3 métricas independentes (SEM composite)
# ---------------------------------------------------------------------------

RankMetric = Literal["expectancy_usd", "net_profit_factor", "max_drawdown_pct"]

_VALID_METRICS = ("expectancy_usd", "net_profit_factor", "max_drawdown_pct")


def rank_strategies(
    results: Sequence[StrategyEvaluationResult],
    metric: RankMetric = "expectancy_usd",
    min_trades: int = 0,
) -> List[StrategyEvaluationResult]:
    """
    Ordena resultados pela métrica indicada.

    ⚠️  SEM composite score — métricas têm trade-offs.
    ⚠️  Ranking NÃO garante performance futura.

    Convenções:
        expectancy_usd     → MAIOR é melhor.
        net_profit_factor  → MAIOR é melhor; None vai para o FIM do ranking.
        max_drawdown_pct   → MAIOR (menos negativo, mais perto de zero) é melhor.

    Args:
        results:    Lista de StrategyEvaluationResult.
        metric:     Métrica usada para ordenar.
        min_trades: Filtra resultados com `single_report.total_trades < min_trades`.
                    Default 0 (sem filtro). Recomendação: usar >= 30 em
                    comparações sérias para evitar "estratégia que fez
                    1 trade lucrativo".

    Returns:
        Lista ordenada (cópia; não muta input).

    Raises:
        ValueError: se metric inválida.
    """
    if metric not in _VALID_METRICS:
        raise ValueError(
            f"metric inválida: {metric!r}. Aceitas: {_VALID_METRICS}"
        )

    # Filtro por min_trades
    filtered = [
        r for r in results
        if r.single_report.total_trades >= min_trades
    ]

    if metric == "expectancy_usd":
        # Maior expectancy = melhor
        return sorted(
            filtered,
            key=lambda r: r.single_report.expectancy_usd,
            reverse=True,
        )

    if metric == "net_profit_factor":
        # Maior PF = melhor; None vai para o FIM
        def _pf_key(r: StrategyEvaluationResult):
            pf = r.single_report.net_profit_factor
            # (is_none, -pf): is_none False=0 antes de True=1 → None vai por último.
            # -pf para inverter (sorted ascendente do score negativo = maior pf primeiro).
            return (pf is None, -(pf or 0.0))
        return sorted(filtered, key=_pf_key)

    # max_drawdown_pct: maior (menos negativo) = melhor
    return sorted(
        filtered,
        key=lambda r: r.single_report.max_drawdown_pct,
        reverse=True,
    )


# ---------------------------------------------------------------------------
# summarize_comparison — tabela textual com avisos obrigatórios
# ---------------------------------------------------------------------------

# Limiar heurístico (em % do single_pnl) para flag de overfitting.
_OVERFITTING_WARNING_THRESHOLD_PCT = 20.0


def summarize_comparison(
    results: Sequence[StrategyEvaluationResult],
    overfitting_warning_threshold_pct: float = _OVERFITTING_WARNING_THRESHOLD_PCT,
) -> str:
    """
    Retorna tabela textual com métricas chave + avisos obrigatórios.

    ⚠️  CONTRATO: o output SEMPRE contém o aviso
        "RANKING NÃO GARANTE PERFORMANCE FUTURA".

    Args:
        results: Sequence de StrategyEvaluationResult.
        overfitting_warning_threshold_pct: limiar em % de divergência
            (|single - mean_wf| / |single|) acima do qual a estratégia
            recebe flag visual de overfitting suspeito. Default 20%.

    Returns:
        String textual formatada com header de aviso, tabela e legenda.
    """
    lines: List[str] = []
    lines.append("=" * 80)
    lines.append("  📊 STRATEGY RESEARCH — COMPARISON SUMMARY")
    lines.append("  ⚠️  RANKING NÃO GARANTE PERFORMANCE FUTURA.")
    lines.append("  ⚠️  Backtest é aproximação; valide em paper/testnet real.")
    lines.append("=" * 80)

    if not results:
        lines.append("  Nenhuma estratégia avaliada.")
        lines.append("=" * 80)
        return "\n".join(lines)

    lines.append(f"  Estratégias avaliadas: {len(results)}")
    lines.append("")
    lines.append("─" * 80)
    lines.append(
        f"  {'Strategy':<24} {'Trades':>7} {'PnL$':>9} "
        f"{'Expec.':>8} {'PF':>6} {'MaxDD%':>7}   Flag"
    )
    lines.append("─" * 80)

    for r in results:
        rep = r.single_report
        pf = rep.net_profit_factor
        pf_str = f"{pf:.2f}" if pf is not None else "  N/A"

        # Flag de overfitting suspeito (se WF rodou)
        flag = ""
        if r.overfitting_divergence_usd is not None:
            if abs(rep.total_pnl_usd) > 1e-9:
                div_pct = (
                    abs(r.overfitting_divergence_usd / rep.total_pnl_usd)
                    * 100.0
                )
                if div_pct > overfitting_warning_threshold_pct:
                    flag = "⚠️  OF?"

        lines.append(
            f"  {r.spec.name:<24} {rep.total_trades:>7} "
            f"{rep.total_pnl_usd:>+9.2f} {rep.expectancy_usd:>+8.2f} "
            f"{pf_str:>6} {rep.max_drawdown_pct:>+7.2f}   {flag}"
        )

    lines.append("─" * 80)
    lines.append("")
    lines.append("  Legenda:")
    lines.append("    Expec. = expectancy_usd (PnL líquido esperado/trade)")
    lines.append("    PF     = net_profit_factor")
    lines.append("    MaxDD% = max_drawdown_pct (negativo; menos negativo é melhor)")
    lines.append("    OF?    = overfitting suspeito (|single - mean_wf| > "
                 f"{overfitting_warning_threshold_pct:.0f}% de |single|)")
    lines.append("")
    lines.append("  ⚠️  Métricas têm trade-offs.")
    lines.append("  ⚠️  Não existe 'melhor estratégia única'.")
    lines.append("  ⚠️  Use 3 rankings independentes: expectancy / profit_factor / drawdown.")
    lines.append("  ⚠️  Backtest NÃO garante performance futura.")
    lines.append("=" * 80)

    return "\n".join(lines)
