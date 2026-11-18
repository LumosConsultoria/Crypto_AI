"""
Historical Data Providers (FASE 37 Parte A)
============================================
Camada READ-ONLY de busca de candles historicos. Provider-agnostic;
nada hardcoded (symbol/timeframe/range vem do operador).

⚠️  ZERO endpoint de execucao. ZERO credencial de trade. ZERO secret
    em log. Provider real usa SOMENTE endpoint PUBLICO read-only.
⚠️  Em TESTES: usar SEMPRE o FakeHistoricalProvider (deterministico,
    offline). O provider real (binance) NUNCA eh chamado em teste.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Protocol, Tuple, \
    runtime_checkable


# Timeframes suportados -> minutos. Nada hardcoded de symbol/range.
SUPPORTED_TIMEFRAMES: Dict[str, int] = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720,
    "1d": 1440,
}

# Pares conhecidos (lista extensivel; NAO restringe se vazio no perfil).
KNOWN_SYMBOLS: Tuple[str, ...] = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
)

_MAX_ROWS_PER_PAGE = 1000


class HistoricalDataError(Exception):
    """Erro de busca/validacao de dados historicos."""


@dataclass(frozen=True)
class CandleRow:
    """Linha canonica OHLCV (timestamp UTC)."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_csv_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.astimezone(
                timezone.utc,
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "open": self.open, "high": self.high, "low": self.low,
            "close": self.close, "volume": self.volume,
        }


def normalize_timeframe(timeframe: str) -> Tuple[str, int]:
    """Normaliza timeframe -> (label, minutos). Aceita '15' e '15m'."""
    tf = str(timeframe).strip().lower()
    if tf in SUPPORTED_TIMEFRAMES:
        return tf, SUPPORTED_TIMEFRAMES[tf]
    if tf.isdigit():
        mins = int(tf)
        for label, m in SUPPORTED_TIMEFRAMES.items():
            if m == mins:
                return label, m
    raise HistoricalDataError(
        f"timeframe nao suportado: {timeframe!r}. "
        f"Aceitos: {sorted(SUPPORTED_TIMEFRAMES)}"
    )


def validate_fetch_request(
    *, symbol: str, timeframe: str, start_date: str, end_date: str,
    allowed_symbols: Optional[Tuple[str, ...]] = None,
) -> Tuple[str, int, datetime, datetime]:
    """Valida inputs (puro). Retorna (tf_label, tf_min, start, end)."""
    if not symbol or not symbol.strip():
        raise HistoricalDataError("symbol obrigatorio")
    sym = symbol.strip().upper()
    if allowed_symbols and sym not in allowed_symbols:
        raise HistoricalDataError(
            f"symbol {sym!r} nao permitido. "
            f"Permitidos: {list(allowed_symbols)}"
        )
    tf_label, tf_min = normalize_timeframe(timeframe)
    start = _parse_date(start_date, "start-date")
    end = _parse_date(end_date, "end-date")
    if end <= start:
        raise HistoricalDataError(
            f"end-date ({end_date}) deve ser > start-date ({start_date})"
        )
    return tf_label, tf_min, start, end


def _parse_date(value: str, label: str) -> datetime:
    v = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(v, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise HistoricalDataError(
        f"{label} invalido: {value!r}. Use YYYY-MM-DD (UTC)."
    )


@runtime_checkable
class HistoricalDataProvider(Protocol):
    """Contrato read-only de provider de candles historicos."""

    @property
    def name(self) -> str: ...

    @property
    def is_real(self) -> bool: ...

    def fetch_candles(
        self, *, symbol: str, tf_minutes: int,
        start: datetime, end: datetime,
    ) -> List[CandleRow]:
        """Retorna candles [start, end). Read-only. Pode paginar."""
        ...


# ---------------------------------------------------------------------------
# Fake provider (testes/offline) - DETERMINISTICO
# ---------------------------------------------------------------------------

class FakeHistoricalProvider:
    """Provider determinISTIco offline. Pagina internamente.

    NAO representa mercado real. Usado em testes e dry-runs. Gera um
    random-walk reprodutivel (sem rede).
    """

    name = "fake"
    is_real = False

    def __init__(self, *, base_price: float = 65000.0,
                 vol_pct: float = 0.0024, seed: int = 37) -> None:
        self._base = base_price
        self._vol = vol_pct
        self._seed = seed

    def fetch_candles(self, *, symbol, tf_minutes, start, end):
        import random
        rng = random.Random(f"{self._seed}:{symbol}:{tf_minutes}")
        rows: List[CandleRow] = []
        step = timedelta(minutes=tf_minutes)
        t = start
        price = self._base
        # Pagina em blocos (prova de paginacao) ate o fim.
        while t < end:
            drift = rng.gauss(0.0002, self._vol)
            open_p = round(price, 2)
            close_p = round(open_p * (1 + drift), 2)
            hi = round(max(open_p, close_p) * (1 + abs(rng.gauss(
                0, self._vol / 2))), 2)
            lo = round(min(open_p, close_p) * (1 - abs(rng.gauss(
                0, self._vol / 2))), 2)
            vol = round(abs(rng.gauss(100, 30)), 4)
            rows.append(CandleRow(
                timestamp=t, open=open_p, high=hi, low=lo,
                close=close_p, volume=vol,
            ))
            price = close_p
            t += step
            if len(rows) % _MAX_ROWS_PER_PAGE == 0:
                # ponto de paginacao logico (sem efeito de rede).
                continue
        return rows


# ---------------------------------------------------------------------------
# Binance public provider (real, read-only, SEM auth) - lazy/urllib
# ---------------------------------------------------------------------------

class BinancePublicProvider:
    """Provider REAL read-only via Binance public klines (sem auth).

    ⚠️  Endpoint PUBLICO de mercado; NUNCA endpoint de execucao.
    ⚠️  NUNCA chamado em testes (testes usam FakeHistoricalProvider).
    ⚠️  Sem API key/secret; logs sem segredos. Paginacao por startTime,
        timeout e retries simples.
    """

    name = "binance"
    is_real = True
    _BASE_URL = "https://api.binance.com/api/v3/klines"

    def __init__(self, *, timeout_seconds: float = 15.0,
                 max_retries: int = 3,
                 rate_limit_sleep: float = 0.25) -> None:
        self._timeout = timeout_seconds
        self._retries = max_retries
        self._sleep = rate_limit_sleep

    def fetch_candles(self, *, symbol, tf_minutes, start, end):
        # Imports e rede SOMENTE aqui (nunca em import-time / teste).
        import json
        import time
        import urllib.parse
        import urllib.request

        label, _ = _minutes_to_binance_interval(tf_minutes)
        rows: List[CandleRow] = []
        cur_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        step_ms = tf_minutes * 60 * 1000

        while cur_ms < end_ms:
            params = urllib.parse.urlencode({
                "symbol": symbol.upper(), "interval": label,
                "startTime": cur_ms, "endTime": end_ms,
                "limit": _MAX_ROWS_PER_PAGE,
            })
            url = f"{self._BASE_URL}?{params}"
            data = self._get_json(url)
            if not data:
                break
            for k in data:
                ts = datetime.fromtimestamp(
                    int(k[0]) / 1000, tz=timezone.utc,
                )
                if ts >= end:
                    break
                rows.append(CandleRow(
                    timestamp=ts, open=float(k[1]), high=float(k[2]),
                    low=float(k[3]), close=float(k[4]),
                    volume=float(k[5]),
                ))
            last_open = int(data[-1][0])
            nxt = last_open + step_ms
            if nxt <= cur_ms:
                break
            cur_ms = nxt
            time.sleep(self._sleep)
        return rows

    def _get_json(self, url: str):
        import json
        import time
        import urllib.request
        last_err = None
        for attempt in range(self._retries):
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "crypto-ai-readonly"},
                )
                with urllib.request.urlopen(
                    req, timeout=self._timeout,
                ) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(self._sleep * (attempt + 1))
        raise HistoricalDataError(
            f"falha ao buscar klines publicos (sem segredos no log): "
            f"{type(last_err).__name__}"
        )


def _minutes_to_binance_interval(tf_minutes: int) -> Tuple[str, int]:
    for label, m in SUPPORTED_TIMEFRAMES.items():
        if m == tf_minutes:
            return label, m
    raise HistoricalDataError(
        f"timeframe {tf_minutes}m sem mapeamento Binance"
    )


# ---------------------------------------------------------------------------
# Bybit LINEAR public provider (real, read-only, SEM auth) - mercado-alvo
# ---------------------------------------------------------------------------

# Bybit V5 kline interval (minutos -> codigo). D/W nao usados aqui.
_BYBIT_INTERVALS = {1: "1", 3: "3", 5: "5", 15: "15", 30: "30",
                    60: "60", 120: "120", 240: "240", 1440: "D"}


def _minutes_to_bybit_interval(tf_minutes: int) -> str:
    code = _BYBIT_INTERVALS.get(tf_minutes)
    if code is None:
        raise HistoricalDataError(
            f"timeframe {tf_minutes}m sem mapeamento Bybit")
    return code


class BybitLinearPublicProvider:
    """Provider REAL read-only via Bybit V5 public kline (LINEAR/perp; sem
    auth). Mercado-ALVO do bot (BTCUSDT linear). Endpoint PUBLICO de mercado
    (mainnet), NUNCA execucao; sem API key/secret; logs sem segredos.

    ⚠️  NUNCA chamado em testes (testes usam FakeHistoricalProvider).
    Paginacao por JANELA (Bybit retorna ate `limit` bars DESC por requisicao);
    ordena ascendente e deduplica por timestamp.
    """

    name = "bybit"
    is_real = True
    _BASE_URL = "https://api.bybit.com/v5/market/kline"
    _CATEGORY = "linear"

    def __init__(self, *, timeout_seconds: float = 15.0,
                 max_retries: int = 3,
                 rate_limit_sleep: float = 0.25) -> None:
        self._timeout = timeout_seconds
        self._retries = max_retries
        self._sleep = rate_limit_sleep

    def fetch_candles(self, *, symbol, tf_minutes, start, end):
        import time
        import urllib.parse
        interval = _minutes_to_bybit_interval(tf_minutes)
        step_ms = tf_minutes * 60 * 1000
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        seen = set()
        rows: List[CandleRow] = []
        cur = start_ms
        while cur < end_ms:
            win_end = min(cur + _MAX_ROWS_PER_PAGE * step_ms, end_ms)
            params = urllib.parse.urlencode({
                "category": self._CATEGORY, "symbol": symbol.upper(),
                "interval": interval, "start": cur, "end": win_end - 1,
                "limit": _MAX_ROWS_PER_PAGE,
            })
            payload = self._get_json(f"{self._BASE_URL}?{params}")
            lst = (((payload or {}).get("result") or {}).get("list")) or []
            if not lst:
                cur = win_end
                time.sleep(self._sleep)
                continue
            # Bybit retorna DESC (newest first); ordena ASC por openTime.
            for k in sorted(lst, key=lambda r: int(r[0])):
                t_ms = int(k[0])
                if t_ms < start_ms or t_ms >= end_ms or t_ms in seen:
                    continue
                seen.add(t_ms)
                ts = datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc)
                rows.append(CandleRow(
                    timestamp=ts, open=float(k[1]), high=float(k[2]),
                    low=float(k[3]), close=float(k[4]), volume=float(k[5]),
                ))
            cur = win_end
            time.sleep(self._sleep)
        rows.sort(key=lambda r: r.timestamp)
        return rows

    def _get_json(self, url: str):
        import json
        import time
        import urllib.request
        last_err = None
        for attempt in range(self._retries):
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "crypto-ai-readonly"},
                )
                with urllib.request.urlopen(
                    req, timeout=self._timeout,
                ) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(self._sleep * (attempt + 1))
        raise HistoricalDataError(
            f"falha ao buscar klines publicos Bybit (sem segredos no log): "
            f"{type(last_err).__name__}"
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def get_provider(name: str, **kw) -> HistoricalDataProvider:
    """Resolve provider. 'fake' (offline) | 'binance' (spot real) |
    'bybit'/'bybit_linear' (linear perp real, mercado-alvo)."""
    n = str(name).strip().lower()
    if n == "fake":
        return FakeHistoricalProvider(**kw)
    if n == "binance":
        return BinancePublicProvider(**kw)
    if n in ("bybit", "bybit_linear"):
        return BybitLinearPublicProvider(**kw)
    raise HistoricalDataError(
        f"provider desconhecido: {name!r}. "
        "Aceitos: fake | binance | bybit"
    )


SUPPORTED_PROVIDERS: Tuple[str, ...] = ("fake", "binance", "bybit")


__all__ = [
    "BinancePublicProvider",
    "BybitLinearPublicProvider",
    "CandleRow",
    "FakeHistoricalProvider",
    "HistoricalDataError",
    "HistoricalDataProvider",
    "KNOWN_SYMBOLS",
    "SUPPORTED_PROVIDERS",
    "SUPPORTED_TIMEFRAMES",
    "get_provider",
    "normalize_timeframe",
    "validate_fetch_request",
]
