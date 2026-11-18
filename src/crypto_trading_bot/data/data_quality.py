"""
Data Quality Validator — FASE 3G
==================================
Funções e dataclasses para validar a integridade de séries de candles OHLCV.

⚠️  Funções puras: sem efeitos colaterais, sem I/O.
⚠️  Dados válidos NÃO garantem performance futura — apenas auditam consistência.

Validações realizadas:
    - Timestamps estritamente crescentes (não monotônico → issue).
    - Timestamps únicos (duplicatas → issue).
    - high >= max(open, close).
    - low <= min(open, close).
    - low > 0 (estritamente positivo).
    - volume >= 0.
    - Gaps esperados (se timeframe conhecido).
    - Consistência de symbol entre candles.
    - Consistência de timeframe entre candles.

API:
    validate_candles(candles, *, expected_timeframe_minutes=None, detect_gaps=True)
        → DataQualityReport (sempre retorna; nunca lança em dados ruins).
    validate_candles_strict(candles, **kw)
        → None se ok; lança DataQualityError se houver issues.
    timeframe_to_minutes(timeframe) → int (helper).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from crypto_trading_bot.exchange.base_exchange import Candle


class DataQualityError(Exception):
    """Erro levantado por validate_candles_strict quando há issues."""
    def __init__(self, report: "DataQualityReport") -> None:
        super().__init__(
            f"Data quality issues encontradas: {len(report.issues)} "
            f"(gaps={len(report.gap_indices)}, dup={len(report.duplicate_indices)})"
        )
        self.report = report


# ---------------------------------------------------------------------------
# Helper: timeframe → minutos
# ---------------------------------------------------------------------------

_TIMEFRAME_MINUTES = {
    "1": 1,
    "3": 3,
    "5": 5,
    "15": 15,
    "30": 30,
    "60": 60,
    "120": 120,
    "240": 240,
    "360": 360,
    "720": 720,
    "D": 60 * 24,
    "W": 60 * 24 * 7,
}


def timeframe_to_minutes(timeframe: str) -> int:
    """
    Converte timeframe string para minutos.

    Aceita: "1", "3", "5", "15", "30", "60", "120", "240", "360", "720", "D", "W".
    Para inteiros desconhecidos, tenta int(timeframe) (assume minutos).

    Args:
        timeframe: String de timeframe.

    Returns:
        Inteiro de minutos.

    Raises:
        ValueError: se timeframe não pode ser convertido.
    """
    if timeframe in _TIMEFRAME_MINUTES:
        return _TIMEFRAME_MINUTES[timeframe]
    # Tentativa: timeframe como inteiro de minutos
    try:
        m = int(timeframe)
    except (TypeError, ValueError):
        raise ValueError(
            f"Timeframe não suportado: {timeframe!r}. "
            f"Aceitos: {sorted(_TIMEFRAME_MINUTES.keys())} ou inteiro de minutos."
        )
    if m <= 0:
        raise ValueError(
            f"Timeframe em minutos deve ser positivo: {m}"
        )
    return m


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DataQualityIssue:
    """
    Representa uma issue específica de qualidade dos dados.

    Atributos:
        kind:        Identificador estável (snake_case).
                     Valores possíveis:
                       "duplicate_timestamp", "non_monotonic_timestamp",
                       "high_below_max_oc", "low_above_min_oc",
                       "non_positive_low", "negative_volume",
                       "gap_detected", "symbol_inconsistency",
                       "timeframe_inconsistency"
        index:       Índice do candle problemático (-1 se geral/lista).
        description: Texto descritivo da issue.
    """
    kind: str
    index: int
    description: str


@dataclass(frozen=True)
class DataQualityReport:
    """
    Relatório imutável de qualidade dos dados.

    Atributos:
        n_candles:         Total de candles analisadas.
        issues:            Tupla de DataQualityIssue encontradas.
        gap_indices:       Tupla de índices ANTES de cada gap detectado.
        duplicate_indices: Tupla de índices de timestamps duplicados.

    Properties:
        ok: True se issues == ().
    """
    n_candles: int
    issues: Tuple[DataQualityIssue, ...] = ()
    gap_indices: Tuple[int, ...] = ()
    duplicate_indices: Tuple[int, ...] = ()

    @property
    def ok(self) -> bool:
        return len(self.issues) == 0

    def summary(self) -> str:
        """Texto resumido para logs/saídas."""
        lines = [
            "=" * 60,
            "  🔍 DATA QUALITY REPORT",
            "=" * 60,
            f"  Total candles:  {self.n_candles}",
            f"  Issues:         {len(self.issues)}",
            f"  Duplicatas:     {len(self.duplicate_indices)}",
            f"  Gaps:           {len(self.gap_indices)}",
            f"  Status:         {'✅ OK' if self.ok else '⚠️  PROBLEMAS DETECTADOS'}",
        ]
        if self.issues:
            lines.append("─" * 60)
            lines.append("  Issues detalhadas:")
            for issue in self.issues[:20]:  # limita exibição a 20
                lines.append(
                    f"    [{issue.kind}] idx={issue.index}: {issue.description}"
                )
            if len(self.issues) > 20:
                lines.append(f"    ... (+{len(self.issues) - 20} mais)")
        lines.append("=" * 60)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Validador
# ---------------------------------------------------------------------------

def validate_candles(
    candles: List[Candle],
    *,
    expected_timeframe_minutes: Optional[int] = None,
    detect_gaps: bool = True,
) -> DataQualityReport:
    """
    Valida uma lista de Candle e retorna DataQualityReport (não-fatal).

    Args:
        candles:                    Lista de Candle a validar.
        expected_timeframe_minutes: Minutos esperados entre candles consecutivos.
                                    Se None e detect_gaps=True, infere via
                                    timeframe_to_minutes(candles[0].timeframe).
        detect_gaps:                Se True, detecta gaps com base no timeframe.

    Returns:
        DataQualityReport (sempre retorna; nunca lança).

    Issues detectadas (em ordem de prioridade):
        1. symbol_inconsistency / timeframe_inconsistency (qualquer candle != candles[0])
        2. duplicate_timestamp / non_monotonic_timestamp (vs. candle anterior)
        3. high_below_max_oc / low_above_min_oc (OHLCV inválido por candle)
        4. non_positive_low (low <= 0)
        5. negative_volume (volume < 0)
        6. gap_detected (delta > timeframe esperado)
    """
    n = len(candles)
    issues: List[DataQualityIssue] = []
    gap_indices: List[int] = []
    duplicate_indices: List[int] = []

    if n == 0:
        return DataQualityReport(n_candles=0)

    # --- 1) Consistência de symbol/timeframe ---
    base_symbol = candles[0].symbol
    base_timeframe = candles[0].timeframe
    for i, c in enumerate(candles):
        if c.symbol != base_symbol:
            issues.append(DataQualityIssue(
                kind="symbol_inconsistency",
                index=i,
                description=f"symbol={c.symbol!r} != esperado {base_symbol!r}",
            ))
        if c.timeframe != base_timeframe:
            issues.append(DataQualityIssue(
                kind="timeframe_inconsistency",
                index=i,
                description=f"timeframe={c.timeframe!r} != esperado {base_timeframe!r}",
            ))

    # --- Resolve timeframe esperado em minutos (para gaps) ---
    tf_minutes: Optional[int] = expected_timeframe_minutes
    if tf_minutes is None and detect_gaps:
        try:
            tf_minutes = timeframe_to_minutes(base_timeframe)
        except ValueError:
            tf_minutes = None  # silencioso — apenas não detecta gaps

    # --- 2) Validação por candle + ordem temporal ---
    for i, c in enumerate(candles):
        # OHLCV invariantes
        if c.high < max(c.open, c.close):
            issues.append(DataQualityIssue(
                kind="high_below_max_oc",
                index=i,
                description=(
                    f"high={c.high} < max(open={c.open}, close={c.close})"
                ),
            ))
        if c.low > min(c.open, c.close):
            issues.append(DataQualityIssue(
                kind="low_above_min_oc",
                index=i,
                description=(
                    f"low={c.low} > min(open={c.open}, close={c.close})"
                ),
            ))
        if c.low <= 0:
            issues.append(DataQualityIssue(
                kind="non_positive_low",
                index=i,
                description=f"low={c.low} deve ser estritamente positivo",
            ))
        if c.volume < 0:
            issues.append(DataQualityIssue(
                kind="negative_volume",
                index=i,
                description=f"volume={c.volume} deve ser >= 0",
            ))

        # Comparação com candle anterior
        if i > 0:
            prev = candles[i - 1]
            if c.timestamp == prev.timestamp:
                duplicate_indices.append(i)
                issues.append(DataQualityIssue(
                    kind="duplicate_timestamp",
                    index=i,
                    description=(
                        f"timestamp={c.timestamp.isoformat()} duplicado com idx={i - 1}"
                    ),
                ))
            elif c.timestamp < prev.timestamp:
                issues.append(DataQualityIssue(
                    kind="non_monotonic_timestamp",
                    index=i,
                    description=(
                        f"timestamp={c.timestamp.isoformat()} "
                        f"< anterior={prev.timestamp.isoformat()}"
                    ),
                ))
            elif detect_gaps and tf_minutes is not None:
                # Detecta gap: delta deve ser exatamente tf_minutes
                delta = c.timestamp - prev.timestamp
                delta_minutes = delta.total_seconds() / 60.0
                # Tolerância pequena para arredondamento (1 segundo)
                if delta_minutes > tf_minutes + (1.0 / 60.0):
                    gap_indices.append(i - 1)
                    issues.append(DataQualityIssue(
                        kind="gap_detected",
                        index=i - 1,
                        description=(
                            f"gap entre idx={i - 1} e idx={i}: "
                            f"delta={delta_minutes:.2f}min > esperado={tf_minutes}min"
                        ),
                    ))

    return DataQualityReport(
        n_candles=n,
        issues=tuple(issues),
        gap_indices=tuple(gap_indices),
        duplicate_indices=tuple(duplicate_indices),
    )


def validate_candles_strict(
    candles: List[Candle],
    *,
    expected_timeframe_minutes: Optional[int] = None,
    detect_gaps: bool = True,
) -> None:
    """
    Wrapper estrito: lança DataQualityError se report não estiver ok.

    Útil quando o chamador exige dados limpos (ex: feed de produção).

    Raises:
        DataQualityError: se report.ok == False (carrega `.report`).
    """
    report = validate_candles(
        candles,
        expected_timeframe_minutes=expected_timeframe_minutes,
        detect_gaps=detect_gaps,
    )
    if not report.ok:
        raise DataQualityError(report)
