"""
BybitClient — Cliente Read-Only da Bybit V5 (FASE 3A)
=======================================================
Cliente HTTP para dados públicos de mercado da Bybit V5 API.

⚠️  FASE 3A — SOMENTE LEITURA:
    Este cliente acessa APENAS endpoints públicos da Bybit V5.
    Nenhuma autenticação é usada.
    Nenhuma ordem é enviada.
    Nenhum endpoint privado é implementado.

Endpoints públicos implementados (sem API key):
    ✅ GET /v5/market/kline       → candles OHLCV
    ✅ GET /v5/market/tickers     → ticker / preço atual
    ✅ GET /v5/market/orderbook   → livro de ofertas

Endpoints privados (FASE futura, com autenticação):
    ⛔ place_market_order()   → bloqueado
    ⛔ cancel_order()         → bloqueado
    ⛔ get_positions()        → bloqueado
    ⛔ get_balance()          → bloqueado

Parâmetro `category`:
    Todos os endpoints públicos da Bybit V5 exigem `category`.
    Valores suportados: "linear" (perps USDT), "spot", "inverse".
    Padrão: "linear" — adequado para BTCUSDT perp.

Uso (somente leitura, sem API key):
    client = BybitClient(use_testnet=True, default_category="linear")
    candles = client.get_candles("BTCUSDT", timeframe="15", limit=100)
    ticker = client.get_ticker("BTCUSDT")
    ob = client.get_order_book("BTCUSDT", depth=10)
    client.close()

    # ou como context manager:
    with BybitClient() as client:
        ticker = client.get_ticker("BTCUSDT")
"""

from __future__ import annotations

import re

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

import httpx

from crypto_trading_bot.exchange.base_exchange import (
    BaseExchange,
    Candle,
    OrderBook,
    OrderResult,
    Ticker,
)
from crypto_trading_bot.logging_system.logger import get_logger

_logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

_RETMSG_REDACT_PATTERNS = [
    # FASE 22 Final: origin_string vaza o payload (ts+key+window+query)
    # incluindo api_key parcial e dados de assinatura. Redactar AGRESSIVO.
    (re.compile(r"origin_string\[[^\]]*\]", re.IGNORECASE), "origin_string[REDACTED]"),
    (re.compile(r"origin[_ ]?string[\s:=]+[^\s,;]+", re.IGNORECASE),
     "origin_string=REDACTED"),
    # Outros tokens sensiveis que poderiam aparecer em retMsg de error.
    (re.compile(r"X-BAPI-SIGN[\s:=]+[^\s,;]+", re.IGNORECASE),
     "X-BAPI-SIGN=REDACTED"),
    (re.compile(r"Bearer\s+[A-Za-z0-9._-]+", re.IGNORECASE), "Bearer REDACTED"),
    (re.compile(r"Authorization[\s:=]+[^\s,;]+", re.IGNORECASE),
     "Authorization=REDACTED"),
    (re.compile(r"sign[\s:=]+[A-Fa-f0-9]{16,}", re.IGNORECASE),
     "sign=REDACTED"),
    (re.compile(r"signature[\s:=]+[A-Fa-f0-9]{16,}", re.IGNORECASE),
     "signature=REDACTED"),
    (re.compile(r"api[_-]?key[\s:=]+[A-Za-z0-9_-]+", re.IGNORECASE),
     "api_key=REDACTED"),
    (re.compile(r"api[_-]?secret[\s:=]+[A-Za-z0-9_-]+", re.IGNORECASE),
     "api_secret=REDACTED"),
]


def redact_ret_msg(ret_msg: str, *, max_len: int = 200) -> str:
    """FASE 22 Final — sanitiza retMsg da Bybit antes de log/serializacao.

    Bybit V5 retCode=10004 ("error sign") retorna retMsg como:
        "error sign! origin_string[<ts><key><window><query>]"
    O conteudo dentro de origin_string[...] inclui api_key parcial e o
    payload exato usado para assinar. Esta funcao remove esses trechos.

    Pode ser chamada com qualquer string proveniente de exception.ret_msg
    OU de qualquer string que possa carregar payload de assinatura.

    Args:
        ret_msg: mensagem bruta da Bybit.
        max_len: truncamento defensivo apos sanitizacao (default 200).

    Returns:
        String sanitizada e truncada.
    """
    if not isinstance(ret_msg, str):
        return ""
    sanitized = ret_msg
    for pat, replacement in _RETMSG_REDACT_PATTERNS:
        sanitized = pat.sub(replacement, sanitized)
    return sanitized[:max_len]


class BybitAPIError(Exception):
    """
    Exceção lançada quando a Bybit retorna retCode != 0.

    FASE 22 Final: ret_msg armazenado e exibido na exception eh
    SANITIZADO via redact_ret_msg(). Se o caller precisar do retMsg
    bruto para algum diagnostico exotico, ele pode armazenar separado
    em logs proprios — esta classe nao expoe o raw original.

    Atributos:
        ret_code: Código de erro da Bybit.
        ret_msg: Mensagem de erro da Bybit (SANITIZADA).
        endpoint: Endpoint que gerou o erro.
    """
    def __init__(self, ret_code: int, ret_msg: str, endpoint: str = "") -> None:
        self.ret_code = ret_code
        # SEMPRE sanitiza ao construir.
        self.ret_msg = redact_ret_msg(ret_msg)
        self.endpoint = endpoint
        super().__init__(
            f"Bybit API error | retCode={ret_code} | "
            f"retMsg='{self.ret_msg}' | endpoint={endpoint}"
        )


class BybitExecutionBlockedError(NotImplementedError):
    """
    Exceção lançada quando um método de execução é chamado.

    Esta exceção é intencional — todos os métodos de execução estão
    bloqueados na FASE 3A. A execução via Bybit real será implementada
    somente na FASE 3B, após validação completa em testnet.
    """
    pass


# ---------------------------------------------------------------------------
# BybitClient
# ---------------------------------------------------------------------------

class BybitClient(BaseExchange):
    """
    Cliente read-only da Bybit V5 API.

    Implementa acesso aos dados públicos de mercado sem autenticação.
    Todos os métodos de execução permanecem bloqueados.

    Separação clara de responsabilidades:
        - BybitClient: HTTP bruto, parse de resposta, tratamento de erros
        - MarketDataService: lógica de alto nível, cache, validação
        - Strategy: utiliza MarketDataService, NÃO usa BybitClient diretamente

    Parâmetros:
        use_testnet: Se True, conecta à Bybit Testnet (padrão). Se False, mainnet.
        timeout: Timeout das requisições HTTP em segundos (padrão: 10).
        default_category: Categoria padrão para endpoints. Padrão: "linear".
            - "linear": contratos perpétuos USDT (ex: BTCUSDT)
            - "spot": mercado spot
            - "inverse": contratos inverse (ex: BTCUSD)
    """

    BASE_URL_MAINNET = "https://api.bybit.com"
    BASE_URL_TESTNET = "https://api-testnet.bybit.com"
    # FASE 9 — Fatia 1: Bybit Demo Trading é ambiente separado de testnet.
    # Endpoint dedicado, key separada, ledger próprio. Não confundir com testnet.
    BASE_URL_DEMO = "https://api-demo.bybit.com"

    # Mapeamento de timeframe → interval da Bybit V5
    TIMEFRAME_MAP: Dict[str, str] = {
        "1": "1", "3": "3", "5": "5", "15": "15", "30": "30",
        "60": "60", "120": "120", "240": "240", "360": "360", "720": "720",
        "D": "D", "W": "W", "M": "M",
    }

    def __init__(
        self,
        use_testnet: bool = True,
        timeout: int = 10,
        default_category: str = "linear",
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        recv_window: int = 5000,
        environment: Optional[str] = None,
    ) -> None:
        """
        Inicializa o BybitClient.

        Sem credentials (default): apenas endpoints públicos read-only. Métodos
        privados (place_market_order, cancel_order, get_positions, get_balance)
        continuam lançando BybitExecutionBlockedError.

        FASE 5: Aceita credentials OPCIONAIS para uso em testnet. Mesmo com
        credentials válidas, métodos privados SÓ funcionam quando:
            1. ambiente é testnet OU demo (mainnet permanece bloqueado aqui)
            2. credentials carregadas
            3. ModeGuard aprovou explicitamente
        Caso contrário, continuam bloqueados.

        FASE 9 — Fatia 1: argumento NOVO `environment` ("testnet" | "demo")
        que tem precedência sobre `use_testnet`. Bybit Demo Trading é um
        ambiente separado de testnet (https://api-demo.bybit.com), com key
        própria e ledger próprio — NÃO confundir os dois.

        Args:
            use_testnet:      (Legado) Se True (padrão), usa o endpoint testnet.
                              Ignorado quando `environment` é fornecido.
            timeout:          Timeout HTTP em segundos.
            default_category: Categoria Bybit padrão ("linear", "spot", "inverse").
            api_key:          FASE 5 — chave da API (opcional). Default None
                              mantém o cliente read-only (compatível 100%).
                              Tratado internamente como SecretStr (não loga).
            api_secret:       FASE 5 — segredo da API (opcional). Default None.
                              NUNCA aparece em logs.
            recv_window:      FASE 5 — janela de validade da requisição em ms
                              (default Bybit: 5000). Faixa [100, 60000].
            environment:      FASE 9 — "testnet" ou "demo". Quando fornecido,
                              tem precedência sobre `use_testnet`. Default None
                              (mantém comportamento legado por `use_testnet`).
                              "mainnet" não é aceito aqui — use `use_testnet=False`
                              explicitamente para o caminho legado.
        """
        # FASE 9 — Fatia 1: resolução do ambiente e da URL base.
        if environment is not None:
            env_normalized = str(environment).lower().strip()
            if env_normalized == "demo":
                self._environment = "demo"
                self._base_url = self.BASE_URL_DEMO
                self._use_testnet = False    # demo não é testnet
            elif env_normalized == "testnet":
                self._environment = "testnet"
                self._base_url = self.BASE_URL_TESTNET
                self._use_testnet = True
            else:
                raise ValueError(
                    f"BybitClient.environment inválido: '{environment}'. "
                    "Use 'testnet' ou 'demo'. Mainnet exige use_testnet=False explícito."
                )
        else:
            # Caminho legado: use_testnet decide (mantém retrocompat 100%).
            self._use_testnet = use_testnet
            if use_testnet:
                self._environment = "testnet"
                self._base_url = self.BASE_URL_TESTNET
            else:
                self._environment = "mainnet"
                self._base_url = self.BASE_URL_MAINNET

        if self._environment == "mainnet":
            _logger.warning(
                "BybitClient: ambiente=mainnet → usando endpoint produção. "
                "Apenas leitura de dados públicos (operações privadas continuam bloqueadas)."
            )

        # FASE 5 — armazenamento defensivo de credentials
        # Mesmo recebendo strings, NÃO logamos os valores.
        self._api_key: Optional[str] = api_key if (api_key and api_key.strip()) else None
        self._api_secret: Optional[str] = (
            api_secret if (api_secret and api_secret.strip()) else None
        )
        if not isinstance(recv_window, int) or recv_window < 100 or recv_window > 60000:
            raise ValueError(
                f"recv_window deve estar em [100, 60000] ms: {recv_window}"
            )
        self._recv_window = recv_window

        self._timeout = timeout
        self._default_category = default_category
        self._connected = False

        # Cliente HTTP com timeout e headers padrão
        self._http = httpx.Client(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": "crypto-trading-bot/0.1.0 (read-only/public)"},
        )
        self._connected = True

        # ⚠️  Log NÃO contém api_key/api_secret nem valores derivados.
        auth_status = "present" if self.has_credentials else "none"
        _logger.info(
            f"BybitClient inicializado | "
            f"mode={self._environment} | "
            f"category={default_category} | "
            f"timeout={timeout}s | "
            f"auth={auth_status} | "
            f"recv_window={recv_window}ms | "
            f"url={self._base_url}"
        )

    @property
    def has_credentials(self) -> bool:
        """True se api_key E api_secret estão presentes (sem expor valores)."""
        return self._api_key is not None and self._api_secret is not None

    @property
    def use_testnet(self) -> bool:
        """Expõe leitura do flag use_testnet (útil para executores externos).

        ⚠️  FASE 9 — Fatia 1: para clients construídos com `environment="demo"`,
            esta propriedade retorna False (demo NÃO é testnet). Executors que
            checam `use_testnet` para gating (ex.: BybitTestnetExecutor) continuam
            recusando demo automaticamente, o que é o comportamento desejado
            até existir um executor demo dedicado.
        """
        return self._use_testnet

    @property
    def environment(self) -> str:
        """
        FASE 9 — Fatia 1: ambiente efetivo do cliente.

        Returns:
            "testnet" | "demo" | "mainnet"
        """
        return self._environment

    @property
    def is_demo(self) -> bool:
        """Verdadeiro se o cliente está conectado ao ambiente Demo Trading."""
        return self._environment == "demo"

    @property
    def is_mainnet(self) -> bool:
        """Verdadeiro se o cliente está conectado ao endpoint mainnet."""
        return self._environment == "mainnet"

    # -----------------------------------------------------------------------
    # Propriedades obrigatórias
    # -----------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "bybit"

    @property
    def is_connected(self) -> bool:
        return self._connected

    # -----------------------------------------------------------------------
    # HTTP interno
    # -----------------------------------------------------------------------

    def _get(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executa uma requisição GET pública e retorna o campo 'result'.

        Trata erros HTTP, timeout e retCode da Bybit.

        Args:
            endpoint: Path da API (ex: "/v5/market/tickers").
            params: Query parameters (ex: {"category": "linear", "symbol": "BTCUSDT"}).

        Returns:
            Dicionário com o campo 'result' da resposta Bybit.

        Raises:
            TimeoutError: Se a requisição ultrapassar o timeout configurado.
            ConnectionError: Se houver erro HTTP (4xx, 5xx).
            BybitAPIError: Se retCode != 0.
            ValueError: Se o campo 'result' estiver ausente.
        """
        try:
            response = self._http.get(endpoint, params=params)
            response.raise_for_status()
        except httpx.TimeoutException as e:
            raise TimeoutError(
                f"Bybit timeout ({self._timeout}s) | endpoint={endpoint}"
            ) from e
        except httpx.HTTPStatusError as e:
            raise ConnectionError(
                f"Bybit HTTP {e.response.status_code} | endpoint={endpoint} | {e}"
            ) from e
        except httpx.RequestError as e:
            raise ConnectionError(
                f"Bybit conexão falhou | endpoint={endpoint} | {e}"
            ) from e

        try:
            data = response.json()
        except Exception as e:
            raise ValueError(
                f"Bybit resposta não é JSON válido | endpoint={endpoint} | {e}"
            ) from e

        ret_code = data.get("retCode")
        ret_msg = data.get("retMsg", "unknown")

        if ret_code is None:
            raise ValueError(
                f"Bybit resposta sem retCode | endpoint={endpoint} | response={data}"
            )

        if ret_code != 0:
            raise BybitAPIError(ret_code, ret_msg, endpoint)

        result = data.get("result")
        if result is None:
            raise ValueError(
                f"Bybit resposta sem campo 'result' | endpoint={endpoint}"
            )

        return result  # type: ignore[return-value]

    def _resolve_category(self, category: Optional[str]) -> str:
        """Resolve a categoria: usa o argumento ou o padrão configurado."""
        return category if category is not None else self._default_category

    # -----------------------------------------------------------------------
    # FASE 5 — Autenticação Bybit V5 (HMAC) para endpoints PRIVADOS
    # -----------------------------------------------------------------------

    def _require_private_access(self) -> None:
        """
        Defesa em profundidade: levanta BybitExecutionBlockedError se as
        condições mínimas para acesso privado não estiverem satisfeitas.

        Condições mínimas (FASE 9 — Fatia 1):
            1. ambiente é 'testnet' OU 'demo' (mainnet sempre bloqueado aqui)
            2. credentials carregadas (api_key + api_secret)

        ⚠️  Esta verificação NÃO substitui o ModeGuard externo. A camada
            chamadora (ex.: BybitTestnetExecutor) DEVE chamar o método
            apropriado do ModeGuard ANTES de invocar qualquer método privado.
            Demo ainda não tem executor dedicado nesta Fatia — endpoints
            privados em demo só podem ser acionados por código novo
            (próximas fatias) com seu próprio gate.
        """
        if self._environment == "mainnet":
            raise BybitExecutionBlockedError(
                "⛔ Endpoints privados bloqueados em MAINNET. "
                "Use environment='testnet' ou 'demo' (com credentials apropriadas) "
                "para autenticação nesta camada."
            )
        if not self.has_credentials:
            raise BybitExecutionBlockedError(
                "⛔ Endpoints privados exigem credentials (api_key + api_secret). "
                "Configure BYBIT_API_KEY e BYBIT_API_SECRET de TESTNET ou DEMO no .env."
            )

    def _signed_request(
        self,
        method: str,
        endpoint: str,
        query_params: Optional[Dict[str, Any]] = None,
        body_payload: Optional[Dict[str, Any]] = None,
        timestamp_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Executa uma requisição AUTENTICADA (HMAC) e retorna o campo 'result'.

        Defesa em profundidade: chama _require_private_access() ANTES de
        construir a assinatura.

        Args:
            method:       "GET" ou "POST".
            endpoint:     Path do endpoint (ex: "/v5/order/create").
            query_params: Params da query string (GET). Default {}.
            body_payload: Body JSON (POST). Default {}.
            timestamp_ms: Override do timestamp (útil para testes determinísticos).
                          Default: now() em ms.

        Returns:
            Campo 'result' do JSON de resposta da Bybit.

        Raises:
            BybitExecutionBlockedError, BybitAPIError, TimeoutError, ConnectionError, ValueError.
        """
        self._require_private_access()

        # Imports lazy para evitar overhead em runs read-only
        import time as _time

        from crypto_trading_bot.exchange.bybit_auth import (
            build_body_string,
            build_query_string,
            sign_request,
        )

        if method not in ("GET", "POST"):
            raise ValueError(f"_signed_request: method inválido {method!r}")

        ts_ms = timestamp_ms if timestamp_ms is not None else int(_time.time() * 1000)

        # FASE 22 Final — assinatura GET exige que httpx envie a query
        # exatamente na MESMA ordem usada para gerar o HMAC. Bybit V5
        # recalcula HMAC(secret, ts+key+window+query_recebida); divergencia
        # gera retCode=10004 ("error sign") com origin_string[...] no log.
        # Causa observada: dict Python preserva ordem de insercao; quando
        # essa ordem != ordem alfabetica usada por build_query_string, o
        # GET signing falhava. Fix: ordenar params ANTES de passar ao httpx.
        if method == "GET":
            ordered_query_params: Dict[str, Any] = dict(
                sorted((query_params or {}).items())
            )
            payload_for_sign = build_query_string(ordered_query_params)
        else:  # POST
            ordered_query_params = {}
            payload_for_sign = build_body_string(body_payload or {})

        # Gera headers com HMAC (NUNCA loga api_secret/sign)
        # type narrowing: _require_private_access já garantiu não-None
        assert self._api_key is not None and self._api_secret is not None
        signed_headers = sign_request(
            api_key=self._api_key,
            api_secret=self._api_secret,
            timestamp_ms=ts_ms,
            recv_window_ms=self._recv_window,
            method=method,
            query_or_body=payload_for_sign,
        )

        try:
            if method == "GET":
                response = self._http.get(
                    endpoint, params=ordered_query_params,
                    headers=signed_headers,
                )
            else:  # POST
                response = self._http.post(
                    endpoint, content=payload_for_sign, headers={
                        **signed_headers,
                        "Content-Type": "application/json",
                    }
                )
            response.raise_for_status()
        except httpx.TimeoutException as e:
            raise TimeoutError(
                f"Bybit timeout ({self._timeout}s) | endpoint={endpoint}"
            ) from e
        except httpx.HTTPStatusError as e:
            raise ConnectionError(
                f"Bybit HTTP {e.response.status_code} | endpoint={endpoint}"
            ) from e
        except httpx.RequestError as e:
            raise ConnectionError(
                f"Bybit conexão falhou | endpoint={endpoint}"
            ) from e

        try:
            data = response.json()
        except Exception as e:
            raise ValueError(
                f"Bybit resposta não é JSON válido | endpoint={endpoint}"
            ) from e

        ret_code = data.get("retCode")
        ret_msg = data.get("retMsg", "unknown")
        if ret_code is None:
            raise ValueError(
                f"Bybit resposta sem retCode | endpoint={endpoint}"
            )
        if ret_code != 0:
            raise BybitAPIError(ret_code, ret_msg, endpoint)

        result = data.get("result")
        if result is None:
            raise ValueError(
                f"Bybit resposta sem campo 'result' | endpoint={endpoint}"
            )
        return result  # type: ignore[return-value]

    # -----------------------------------------------------------------------
    # Métodos de Dados Públicos
    # -----------------------------------------------------------------------

    def get_ticker(self, symbol: str, category: Optional[str] = None) -> Ticker:
        """
        Obtém ticker atual (último preço, bid, ask, volume 24h) da Bybit V5.

        Endpoint: GET /v5/market/tickers
        Documentação: https://bybit-exchange.github.io/docs/v5/market/tickers

        Args:
            symbol: Símbolo do ativo (ex: "BTCUSDT").
            category: Categoria Bybit ("linear", "spot", "inverse").
                      Se None, usa default_category configurado.

        Returns:
            Ticker com dados atuais do ativo.

        Raises:
            BybitAPIError: Se a Bybit retornar erro.
            ValueError: Se o símbolo não for encontrado ou dados inválidos.
        """
        cat = self._resolve_category(category)

        _logger.debug(f"BybitClient.get_ticker | symbol={symbol} | category={cat}")

        result = self._get("/v5/market/tickers", {
            "category": cat,
            "symbol": symbol,
        })

        items: list = result.get("list", [])
        if not items:
            raise ValueError(
                f"Ticker vazio para symbol={symbol} category={cat}. "
                f"Verifique se o símbolo existe nesta categoria."
            )

        item = items[0]

        try:
            last_price = Decimal(str(item["lastPrice"]))
            # bid1Price/ask1Price podem não existir em alguns endpoints
            bid = Decimal(str(item.get("bid1Price") or item["lastPrice"]))
            ask = Decimal(str(item.get("ask1Price") or item["lastPrice"]))
            volume = Decimal(str(item.get("volume24h", "0")))
        except (KeyError, InvalidOperation) as e:
            raise ValueError(
                f"Erro ao parsear ticker de {symbol}: {e} | data={item}"
            ) from e

        return Ticker(
            symbol=symbol,
            last_price=float(last_price),
            bid=float(bid),
            ask=float(ask),
            volume_24h=float(volume),
            timestamp=datetime.now(timezone.utc),
        )

    def get_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
        category: Optional[str] = None,
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
    ) -> List[Candle]:
        """
        Obtém candles OHLCV históricas da Bybit V5 (somente leitura, público).

        Endpoint: GET /v5/market/kline
        Documentação: https://bybit-exchange.github.io/docs/v5/market/kline

        Timeframes suportados (Bybit V5 interval):
            "1"   → 1 minuto      "5"   → 5 minutos
            "15"  → 15 minutos    "30"  → 30 minutos
            "60"  → 1 hora        "120" → 2 horas
            "240" → 4 horas       "D"   → 1 dia
            "W"   → 1 semana      "M"   → 1 mês

        Bybit V5 kline format (list dentro de result):
            [startTime, open, high, low, close, volume, turnover]

        A Bybit retorna as candles mais recentes primeiro (ordem decrescente).
        Este método as inverte para ordem cronológica (mais antiga → mais recente).

        Args:
            symbol:    Símbolo do ativo (ex: "BTCUSDT").
            timeframe: Timeframe (ex: "15" para 15 minutos, "D" para diário).
            limit:    Quantidade de candles a retornar (máx. 1000 na Bybit V5).
            category: Categoria Bybit. Se None, usa default_category.
            start_ms: FASE 3G — timestamp inicial em ms (inclusive), opcional.
                      Para paginação histórica. None = sem filtro inferior.
            end_ms:   FASE 3G — timestamp final em ms (inclusive), opcional.
                      Para paginação histórica. None = sem filtro superior.

        Returns:
            Lista de Candle ordenadas do mais antigo para o mais recente.
        """
        cat = self._resolve_category(category)
        interval = self.TIMEFRAME_MAP.get(timeframe, timeframe)

        _logger.debug(
            f"BybitClient.get_candles | symbol={symbol} | "
            f"timeframe={timeframe}({interval}) | limit={limit} | category={cat} | "
            f"start_ms={start_ms} | end_ms={end_ms}"
        )

        params: Dict[str, Any] = {
            "category": cat,
            "symbol": symbol,
            "interval": interval,
            "limit": min(limit, 1000),  # Bybit limita a 1000
        }
        # FASE 3G — paginação histórica via timestamp (somente público, sem auth)
        if start_ms is not None:
            params["start"] = int(start_ms)
        if end_ms is not None:
            params["end"] = int(end_ms)

        result = self._get("/v5/market/kline", params)

        raw_list: list = result.get("list", [])
        candles: List[Candle] = []

        # Bybit retorna mais recente primeiro — invertemos para mais antigo primeiro
        for row in reversed(raw_list):
            try:
                # Formato: [startTime, open, high, low, close, volume, turnover]
                ts_ms = int(row[0])
                open_ = Decimal(str(row[1]))
                high = Decimal(str(row[2]))
                low = Decimal(str(row[3]))
                close = Decimal(str(row[4]))
                volume = Decimal(str(row[5]))

                timestamp = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
            except (IndexError, ValueError, InvalidOperation) as e:
                _logger.warning(
                    f"BybitClient.get_candles: erro ao parsear candle | row={row} | error={e}"
                )
                continue

            candles.append(Candle(
                symbol=symbol,
                timeframe=timeframe,
                timestamp=timestamp,
                open=float(open_),
                high=float(high),
                low=float(low),
                close=float(close),
                volume=float(volume),
            ))

        _logger.debug(
            f"BybitClient.get_candles: {len(candles)} candles retornadas | "
            f"symbol={symbol}"
        )

        return candles

    def get_order_book(
        self,
        symbol: str,
        depth: int = 25,
        category: Optional[str] = None,
    ) -> OrderBook:
        """
        Obtém snapshot do livro de ofertas (somente leitura) da Bybit V5.

        Endpoint: GET /v5/market/orderbook
        Documentação: https://bybit-exchange.github.io/docs/v5/market/orderbook

        Formato da resposta Bybit V5:
            result.b  → bids [[price, qty], ...]  (maior preço primeiro)
            result.a  → asks [[price, qty], ...]  (menor preço primeiro)

        Args:
            symbol: Símbolo do ativo.
            depth: Profundidade por lado. Valores comuns: 1, 25, 50, 200.
            category: Categoria Bybit. Se None, usa default_category.

        Returns:
            OrderBook com bids e asks como lista de (price, qty).
        """
        cat = self._resolve_category(category)

        _logger.debug(
            f"BybitClient.get_order_book | symbol={symbol} | depth={depth} | category={cat}"
        )

        result = self._get("/v5/market/orderbook", {
            "category": cat,
            "symbol": symbol,
            "limit": depth,
        })

        try:
            raw_bids: list = result.get("b", [])
            raw_asks: list = result.get("a", [])

            bids: List[tuple[float, float]] = [
                (float(Decimal(str(b[0]))), float(Decimal(str(b[1]))))
                for b in raw_bids
            ]
            asks: List[tuple[float, float]] = [
                (float(Decimal(str(a[0]))), float(Decimal(str(a[1]))))
                for a in raw_asks
            ]
        except (IndexError, InvalidOperation) as e:
            raise ValueError(
                f"Erro ao parsear orderbook de {symbol}: {e}"
            ) from e

        return OrderBook(
            symbol=symbol,
            bids=bids,
            asks=asks,
            timestamp=datetime.now(timezone.utc),
        )

    def get_instruments_info(
        self,
        symbol: str,
        *,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        FASE 9 Fatia 4B+ — Informação de instrumento (PÚBLICO, read-only).

        Endpoint: GET /v5/market/instruments-info
        Documentação: https://bybit-exchange.github.io/docs/v5/market/instrument

        Útil para descobrir minOrderQty, qtyStep, minNotionalValue, tickSize
        sem precisar de credentials. Usado pelo preflight automático.

        Args:
            symbol:   Símbolo (ex.: "BTCUSDT").
            category: Categoria Bybit; se None, usa default_category.

        Returns:
            Dict com a primeira entry de `result.list` (snapshot do instrumento).
            Contém pelo menos `lotSizeFilter` e `priceFilter` para Bybit V5.

        Raises:
            ValueError:       se nenhum instrumento for retornado.
            ConnectionError:  erro HTTP.
            TimeoutError:     timeout.
            BybitAPIError:    retCode != 0.
        """
        cat = self._resolve_category(category)
        _logger.debug(
            f"BybitClient.get_instruments_info | symbol={symbol} | category={cat}"
        )
        result = self._get(
            "/v5/market/instruments-info",
            {"category": cat, "symbol": symbol},
        )
        items = result.get("list", [])
        if not items:
            raise ValueError(
                f"Nenhuma informação de instrumento para symbol={symbol} category={cat}."
            )
        return dict(items[0])

    # -----------------------------------------------------------------------
    # Métodos de Execução — FASE 5: destravados CONDICIONALMENTE em testnet
    # -----------------------------------------------------------------------
    # Sem credentials + sem testnet → continuam lançando BybitExecutionBlockedError
    # (defesa em profundidade via _require_private_access).
    # Camada chamadora (BybitTestnetExecutor) DEVE também invocar
    # ModeGuard.assert_testnet_execution_allowed() ANTES.
    # Mainnet permanece BLOQUEADO independente de credentials.
    # -----------------------------------------------------------------------

    def place_market_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        *,
        category: Optional[str] = None,
        reduce_only: bool = False,
    ) -> OrderResult:
        """
        FASE 5 — Envia uma ordem market via endpoint privado da Bybit V5
        (testnet apenas).

        Pré-condições (verificadas em _require_private_access):
            - use_testnet=True
            - api_key + api_secret carregados
        Camada acima deve garantir ModeGuard.assert_testnet_execution_allowed().

        Args:
            symbol:      Símbolo (ex: "BTCUSDT").
            side:        "Buy" ou "Sell" (Bybit V5 espera case Title).
            qty:         Quantidade em contratos.
            stop_loss:   Preço de stop loss (opcional).
            take_profit: Preço de take profit (opcional).
            category:    Categoria Bybit (default linear).

        Returns:
            OrderResult com order_id, status, etc.
        """
        cat = self._resolve_category(category)
        # Normaliza side ("buy" → "Buy" se necessário)
        side_normalized = side[:1].upper() + side[1:].lower() if side else side

        body: Dict[str, Any] = {
            "category": cat,
            "symbol": symbol,
            "side": side_normalized,
            "orderType": "Market",
            "qty": str(qty),
        }
        if stop_loss is not None:
            body["stopLoss"] = str(stop_loss)
        if take_profit is not None:
            body["takeProfit"] = str(take_profit)
        # FASE 29 - reduceOnly opcional, AditiVO retrocompat. Default
        # False NUNCA injeta o campo no payload (preserva FASE 22 byte
        # a byte). Apenas quando explicitamente True envia reduceOnly.
        if reduce_only:
            body["reduceOnly"] = True

        # FASE 22.4 — Bybit V5 (Unified Trading Account / Demo Trading)
        # exige parametros adicionais para anexar SL/TP server-side numa
        # market order. Sem estes, a API ACEITA a ordem mas DESCARTA
        # silenciosamente stopLoss/takeProfit — sintoma observado
        # operacionalmente em Bybit Demo.
        # Fonte: Bybit V5 docs `POST /v5/order/create`.
        # Aplicado apenas quando SL ou TP estao presentes (preserva
        # comportamento legado em chamadas sem SL/TP).
        if stop_loss is not None or take_profit is not None:
            # tpslMode="Full" -> SL/TP aplicado a posicao inteira como
            # market close quando trigger atingir. Eh o modo padrao para
            # market order em UTA + linear/inverse perpetual.
            body["tpslMode"] = "Full"
            # Trigger price source para SL/TP. LastPrice eh o default
            # documentado pela Bybit (mais conservador que MarkPrice).
            if stop_loss is not None:
                body["slTriggerBy"] = "LastPrice"
                body["slOrderType"] = "Market"
            if take_profit is not None:
                body["tpTriggerBy"] = "LastPrice"
                body["tpOrderType"] = "Market"

        _logger.debug(
            f"BybitClient.place_market_order | symbol={symbol} | "
            f"side={side_normalized} | qty={qty} | category={cat} | "
            f"sl_present={stop_loss is not None} | "
            f"tp_present={take_profit is not None} | "
            f"tpsl_payload_present={'tpslMode' in body}"
        )

        result = self._signed_request(
            method="POST",
            endpoint="/v5/order/create",
            body_payload=body,
        )

        # Bybit V5 retorna order_id e orderLinkId; preço fica em null para market.
        order_id = result.get("orderId", "")
        return OrderResult(
            order_id=str(order_id),
            symbol=symbol,
            side=side_normalized.lower(),
            order_type="market",
            qty=float(qty),
            price=None,   # market: preço efetivo retornado em get_order_status
            status="submitted",
            fee=0.0,
            timestamp=datetime.now(timezone.utc),
        )

    def cancel_order(
        self,
        symbol: str,
        order_id: str,
        *,
        category: Optional[str] = None,
    ) -> bool:
        """
        FASE 5 — Cancela uma ordem pendente via endpoint privado (testnet).

        Returns:
            True se a Bybit confirmou o cancelamento.
        """
        cat = self._resolve_category(category)
        _logger.debug(
            f"BybitClient.cancel_order | symbol={symbol} | order_id={order_id} | category={cat}"
        )
        self._signed_request(
            method="POST",
            endpoint="/v5/order/cancel",
            body_payload={
                "category": cat,
                "symbol": symbol,
                "orderId": order_id,
            },
        )
        return True

    def get_positions(
        self,
        symbol: Optional[str] = None,
        *,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        FASE 5 — Lista posições abertas (privado, testnet).

        Returns:
            Lista de dicts com snapshot de posições da Bybit V5.
        """
        cat = self._resolve_category(category)
        params: Dict[str, Any] = {"category": cat}
        if symbol:
            params["symbol"] = symbol

        result = self._signed_request(
            method="GET",
            endpoint="/v5/position/list",
            query_params=params,
        )
        return list(result.get("list", []))

    def get_balance(
        self,
        *,
        account_type: str = "UNIFIED",
    ) -> Dict[str, Any]:
        """
        FASE 5 — Saldo da conta (privado, testnet).

        Returns:
            Dict com snapshot de wallet-balance da Bybit V5.
        """
        result = self._signed_request(
            method="GET",
            endpoint="/v5/account/wallet-balance",
            query_params={"accountType": account_type},
        )
        return dict(result)

    def get_open_orders(
        self,
        symbol: str,
        *,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        FASE 9 Fatia 4B+ — Lista ordens ATIVAS (privado, testnet ou demo).
        FASE 22.2 — fix de parametro: removido openOnly=1.

        Endpoint: GET /v5/order/realtime (sem openOnly explicito).

        Por Bybit V5 docs:
            openOnly = 0 (default): retorna ordens em aberto (active/untriggered).
            openOnly = 1: retorna ordens CONCLUIDAS recentes (nao queremos isso).
            openOnly = 2: idem 1 com cursor.

        Antes da FASE 22.2 este metodo enviava openOnly=1, o que retornava
        historico de fechadas em vez de abertas (e em Demo Trading podia
        retornar BybitAPIError dependendo do account_type/permissoes).
        O default omitido (= 0) e o correto para preflight.

        Útil para preflight: confirmar que NAO ha ordens pendentes em BTCUSDT
        antes de enviar uma ordem nova.

        Args:
            symbol:   Filtro por símbolo (obrigatório p/ Bybit V5).
            category: Categoria; se None, usa default.

        Returns:
            Lista (possivelmente vazia) de dicts com snapshot de cada ordem ativa.
        """
        cat = self._resolve_category(category)
        result = self._signed_request(
            method="GET",
            endpoint="/v5/order/realtime",
            query_params={
                "category": cat,
                "symbol": symbol,
            },
        )
        return list(result.get("list", []))

    def get_order_history(
        self,
        symbol: str,
        *,
        order_id: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        FASE 9 Fatia 4B+ — Lista ordens HISTÓRICAS (privado, testnet ou demo).

        Endpoint: GET /v5/order/history.

        Útil como FALLBACK na reconciliação: ordens preenchidas/canceladas
        migram de /v5/order/realtime para /v5/order/history rapidamente.
        Quando get_order_status (realtime) retorna vazio/erro logo após o
        envio, este endpoint pode encontrar o status final.

        Args:
            symbol:   Filtro por símbolo (obrigatório para Bybit V5).
            order_id: (Opcional) filtro por orderId específico.
            category: Categoria; se None, usa default.
            limit:    Limite de resultados; default 50.

        Returns:
            Lista de dicts (possivelmente vazia) com snapshots das ordens.
        """
        cat = self._resolve_category(category)
        params: Dict[str, Any] = {
            "category": cat,
            "symbol": symbol,
            "limit": limit,
        }
        if order_id:
            params["orderId"] = order_id
        result = self._signed_request(
            method="GET",
            endpoint="/v5/order/history",
            query_params=params,
        )
        return list(result.get("list", []))

    def get_executions(
        self,
        symbol: str,
        *,
        order_id: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        FASE 15 — Lista execuções/fills (privado, demo/testnet).

        Endpoint: GET /v5/execution/list.

        Read-only. Útil como **segunda fonte de triangulação** na
        reconciliação pós-submit: confirma se a Bybit realmente preencheu
        a ordem, mesmo quando `/v5/order/realtime` e `/v5/order/history`
        retornarem BybitAPIError.

        ⚠️  SOMENTE READ-ONLY. Não envia ordem. Não modifica posição.
        ⚠️  Bloqueado sem credentials e em mainnet (igual aos demais
            endpoints privados).

        Args:
            symbol:   Símbolo (obrigatório para Bybit V5).
            order_id: (Opcional) filtra por orderId específico. Quando
                      passado, V5 retorna apenas execuções dessa ordem.
            category: Categoria; se None, usa default ("linear").
            limit:    Limite de resultados; default 50.

        Returns:
            Lista (possivelmente vazia) de dicts com snapshot de cada
            execução: orderId, execId, symbol, side, execPrice, execQty,
            execTime, etc. NÃO contém credenciais nem secrets.
        """
        cat = self._resolve_category(category)
        params: Dict[str, Any] = {
            "category": cat,
            "symbol": symbol,
            "limit": limit,
        }
        if order_id:
            params["orderId"] = order_id
        result = self._signed_request(
            method="GET",
            endpoint="/v5/execution/list",
            query_params=params,
        )
        return list(result.get("list", []))

    def get_order_status(
        self,
        symbol: str,
        order_id: str,
        *,
        category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        FASE 5 — Status de uma ordem específica (privado, testnet).

        Útil para reconciliação após place_market_order.
        """
        cat = self._resolve_category(category)
        result = self._signed_request(
            method="GET",
            endpoint="/v5/order/realtime",
            query_params={
                "category": cat,
                "symbol": symbol,
                "orderId": order_id,
            },
        )
        items = result.get("list", [])
        if not items:
            return {"status": "unknown", "orderId": order_id}
        return dict(items[0])

    # -----------------------------------------------------------------------
    # Context Manager e Ciclo de Vida
    # -----------------------------------------------------------------------

    def close(self) -> None:
        """Fecha o cliente HTTP e libera recursos."""
        if self._connected:
            self._http.close()
            self._connected = False
            _logger.info("BybitClient fechado.")

    def __enter__(self) -> "BybitClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"BybitClient("
            f"env={self._environment}, "
            f"category={self._default_category}, "
            f"connected={self._connected}, "
            f"read_only=True)"
        )
