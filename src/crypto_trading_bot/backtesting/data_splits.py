"""
data_splits.py — Divisão temporal de candles para validação
=============================================================
Funções puras para particionar candles em janelas cronológicas:
    - split_in_sample_out_of_sample: divisão única treino/teste.
    - walk_forward_split:           múltiplos folds adjacentes (rolling).

⚠️  Estas funções NÃO treinam modelos.
⚠️  Backtesting é apenas auditoria temporal — sem ajuste de parâmetros automático.
⚠️  Zero API real. Zero ordens reais. Zero dependências novas.

Princípios:
    - Ordem cronológica preservada (responsabilidade do chamador fornecer candles
      já ordenados; load_candles_from_* fazem isso por padrão).
    - Sem sobreposição entre janelas.
    - Sem vazamento de futuro (folds adjacentes; o `BacktestEngine` já é
      anti-lookahead dentro de cada janela).
    - Determinístico: chamadas idênticas produzem resultados idênticos.

Política de sobra (walk_forward_split):
    Quando `len(candles) % n_folds != 0`, o resto (até `n_folds - 1` candles)
    é DESCARTADO do final, mantendo todos os folds com tamanho IGUAL =
    `floor(len(candles) / n_folds)`. Comportamento explícito e auditável.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from crypto_trading_bot.backtesting.backtest_data import BacktestDataError
from crypto_trading_bot.exchange.base_exchange import Candle
from crypto_trading_bot.logging_system.logger import get_logger

_logger = get_logger(__name__)


def split_in_sample_out_of_sample(
    candles: List[Candle],
    in_sample_pct: float = 0.7,
) -> Tuple[List[Candle], List[Candle]]:
    """
    Divide candles cronologicamente em (in_sample, out_of_sample).

    Args:
        candles:        Lista de Candle em ORDEM CRONOLÓGICA.
        in_sample_pct:  Fração para in-sample, em (0.0, 1.0) exclusivo.
                        Default 0.7 (70% treino, 30% teste).

    Returns:
        Tupla (in_sample, out_of_sample).
        - in_sample        = candles[:floor(n × pct)]
        - out_of_sample    = candles[floor(n × pct):]
        - Ambos não-vazios (validado).

    Raises:
        BacktestDataError: se candles estiver vazio.
        ValueError:        se in_sample_pct fora de (0.0, 1.0) exclusivo, ou se
                           o split resultar em alguma janela vazia.

    Garantias:
        - Sem sobreposição: candle_idx ∈ in_sample → candle_idx ∉ out_of_sample.
        - Ordem preservada: in_sample[-1].timestamp < out_of_sample[0].timestamp.
        - Tamanhos somam ao total: len(in) + len(out) == len(candles).
    """
    if not candles:
        raise BacktestDataError("Lista de candles vazia.")
    if not (0.0 < in_sample_pct < 1.0):
        raise ValueError(
            f"in_sample_pct deve estar em (0.0, 1.0) exclusivo: {in_sample_pct}"
        )

    n = len(candles)
    split_idx = int(n * in_sample_pct)
    in_sample = candles[:split_idx]
    out_of_sample = candles[split_idx:]

    if not in_sample or not out_of_sample:
        raise ValueError(
            f"Split produziu janela vazia (n={n}, pct={in_sample_pct}, "
            f"split_idx={split_idx}). Aumente n ou ajuste pct."
        )

    return in_sample, out_of_sample


def walk_forward_split(
    candles: List[Candle],
    n_folds: int = 5,
    train_pct: float = 0.7,
) -> List[Tuple[List[Candle], List[Candle]]]:
    """
    Divide candles em n_folds janelas adjacentes (ROLLING/SLIDING).

    Cada fold é uma tupla (train_window, test_window):
        - train_window = primeiros `train_pct%` da janela do fold.
        - test_window  = restante (`(1 - train_pct)%`) da janela do fold.

    Args:
        candles:    Lista de Candle em ORDEM CRONOLÓGICA.
        n_folds:    Número de folds (>= 2).
        train_pct:  Fração da janela para train (em (0.0, 1.0) exclusivo).

    Returns:
        Lista de n_folds tuplas (train, test), todas com:
        - Janelas adjacentes e não-sobrepostas.
        - Mesmo tamanho fold = floor(len(candles) / n_folds).
        - Mesmo train_size = floor(fold_size × train_pct).
        - Mesmo test_size = fold_size - train_size.

    Raises:
        BacktestDataError: se candles estiver vazio.
        ValueError:        se n_folds < 2; train_pct fora de (0,1); n < n_folds;
                           ou se train_pct resultar em train_size = 0 ou == fold_size.

    SOBRA DE CANDLES:
        Quando len(candles) % n_folds != 0, os últimos (n % n_folds) candles
        são DESCARTADOS para manter folds com tamanho IGUAL. Esta é uma decisão
        explícita e documentada — comportamento determinístico e auditável.

    Aviso operacional:
        Se fold_size for menor que FeatureEngine._MIN_CANDLES_RECOMMENDED (50),
        a estratégia pode nunca ser avaliada → zero trades por fold. Use
        datasets grandes (recomendado: len(candles) >= n_folds * 200).

    Exemplo:
        100 candles, n_folds=5, train_pct=0.7:
            fold_size = 20, train_size = 14, test_size = 6
            Fold 0: candles[0:14]  train, candles[14:20] test
            Fold 1: candles[20:34] train, candles[34:40] test
            Fold 2: candles[40:54] train, candles[54:60] test
            Fold 3: candles[60:74] train, candles[74:80] test
            Fold 4: candles[80:94] train, candles[94:100] test
    """
    if not candles:
        raise BacktestDataError("Lista de candles vazia.")
    if n_folds < 2:
        raise ValueError(f"n_folds deve ser >= 2: {n_folds}")
    if not (0.0 < train_pct < 1.0):
        raise ValueError(
            f"train_pct deve estar em (0.0, 1.0) exclusivo: {train_pct}"
        )

    n = len(candles)
    if n < n_folds:
        raise ValueError(
            f"len(candles)={n} é menor que n_folds={n_folds}. "
            f"Cada fold precisa de pelo menos 1 candle."
        )

    fold_size = n // n_folds  # SOBRA (n % n_folds) descartada do final
    train_size = int(fold_size * train_pct)

    if train_size == 0 or train_size >= fold_size:
        raise ValueError(
            f"train_pct={train_pct} produziu particionamento inválido em fold "
            f"de tamanho {fold_size} (train_size={train_size}). "
            f"Aumente fold_size (mais candles ou menos folds) ou ajuste train_pct."
        )

    discarded = n - (fold_size * n_folds)
    if discarded > 0:
        _logger.info(
            f"walk_forward_split: {discarded} candle(s) do final descartado(s) "
            f"para manter folds iguais (n={n}, n_folds={n_folds}, fold_size={fold_size})."
        )

    if fold_size < 50:
        _logger.warning(
            f"walk_forward_split: fold_size={fold_size} < 50 "
            f"(FeatureEngine._MIN_CANDLES_RECOMMENDED). "
            f"A estratégia pode nunca ser avaliada em cada fold → zero trades. "
            f"Use len(candles) >= n_folds * 200 para resultados significativos."
        )

    folds: List[Tuple[List[Candle], List[Candle]]] = []
    for k in range(n_folds):
        fold_start = k * fold_size
        fold_end = (k + 1) * fold_size
        window = candles[fold_start:fold_end]
        train = window[:train_size]
        test = window[train_size:]
        folds.append((train, test))

    return folds


def split_by_calendar_month(
    candles: List[Candle],
) -> List[Tuple[str, int, int]]:
    """
    Particiona candles por MES-CALENDARIO (UTC), retornando indices GLOBAIS.

    Funcao PURA / deterministica. NAO recomputa indicadores. Preserva a
    ordem cronologica (assume candles ja ordenados, como load_candles_*).
    Cada janela mensal e contigua e nao-sobreposta.

    Args:
        candles: Lista de Candle em ORDEM CRONOLOGICA.

    Returns:
        Lista de (label, start_index, end_index) — label "YYYY-MM",
        indices INCLUSIVOS no array global de candles. Vazio se candles
        vazio.

    Garantias:
        - Sem vazamento: janelas sao recortes contiguos por timestamp; o
          BacktestEngine continua anti-lookahead DENTRO de cada janela.
        - A uniao dos intervalos cobre exatamente [0, len(candles)-1].
    """
    out: List[Tuple[str, int, int]] = []
    if not candles:
        return out
    cur_key: Optional[str] = None
    start = 0
    for i, c in enumerate(candles):
        ts = getattr(c, "timestamp", None)
        if ts is None:
            key = "unknown"
        else:
            key = f"{ts.year:04d}-{ts.month:02d}"
        if cur_key is None:
            cur_key = key
            start = i
        elif key != cur_key:
            out.append((cur_key, start, i - 1))
            cur_key = key
            start = i
    out.append((cur_key, start, len(candles) - 1))
    return out
