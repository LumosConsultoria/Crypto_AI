"""
Testes do BybitClient — Cliente Read-Only da Bybit V5
=======================================================
⚠️  ZERO chamadas reais à internet — todos os testes usam mocks.

Cobertura:
    - Inicialização (testnet / mainnet)
    - get_ticker(): parse correto, erro de API, símbolo inexistente
    - get_candles(): parse correto, inversão de ordem, erro de resposta
    - get_order_book(): parse de bids/asks, uso de Decimal, erro
    - Métodos de execução bloqueados (place_order, cancel, positions, balance)
    - Tratamento de erros: timeout, HTTP error, retCode != 0, JSON inválido
    - Parâmetro category: resolução padrão e override
"""

import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from crypto_trading_bot.exchange.bybit_client import (
    BybitAPIError,
    BybitClient,
    BybitExecutionBlockedError,
)


# ---------------------------------------------------------------------------
# Helpers — fixtures de resposta Bybit V5 mockadas
# ---------------------------------------------------------------------------

def _make_ticker_response(
    symbol: str = "BTCUSDT",
    last_price: str = "65000.50",
    bid: str = "65000.00",
    ask: str = "65001.00",
    volume: str = "12345.678",
) -> dict:
    """Retorna a estrutura de resposta Bybit V5 para /v5/market/tickers."""
    return {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "category": "linear",
            "list": [{
                "symbol": symbol,
                "lastPrice": last_price,
                "bid1Price": bid,
                "ask1Price": ask,
                "volume24h": volume,
                "turnover24h": "800000000",
            }],
        },
    }


def _make_kline_response(rows: list | None = None) -> dict:
    """Retorna a estrutura de resposta Bybit V5 para /v5/market/kline.

    Bybit retorna as candles mais recentes primeiro (ordem decrescente).
    """
    if rows is None:
        # startTime, open, high, low, close, volume, turnover
        rows = [
            ["1716134400000", "65100.0", "65200.0", "64900.0", "65050.0", "10.5", "682000"],
            ["1716120000000", "64900.0", "65150.0", "64800.0", "65100.0", "12.3", "799000"],
            ["1716105600000", "64700.0", "64950.0", "64600.0", "64900.0", "8.9",  "577000"],
        ]
    return {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "symbol": "BTCUSDT",
            "category": "linear",
            "list": rows,
        },
    }


def _make_orderbook_response(
    symbol: str = "BTCUSDT",
    bids: list | None = None,
    asks: list | None = None,
) -> dict:
    """Retorna a estrutura de resposta Bybit V5 para /v5/market/orderbook."""
    if bids is None:
        bids = [["65000.00", "0.5"], ["64999.00", "1.2"], ["64998.00", "0.8"]]
    if asks is None:
        asks = [["65001.00", "0.3"], ["65002.00", "0.9"], ["65003.00", "1.5"]]
    return {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "s": symbol,
            "b": bids,
            "a": asks,
            "ts": 1716134400000,
            "u": 1,
        },
    }


def _make_error_response(ret_code: int = 10001, ret_msg: str = "params error") -> dict:
    """Retorna uma resposta de erro da Bybit."""
    return {"retCode": ret_code, "retMsg": ret_msg, "result": None}


def _make_mock_response(body: dict, status_code: int = 200) -> MagicMock:
    """Cria um mock de httpx.Response."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = body
    mock.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx
        mock.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=mock,
        )
    return mock


# ---------------------------------------------------------------------------
# Testes de Inicialização
# ---------------------------------------------------------------------------

class TestBybitClientInit:
    """Testa a inicialização do BybitClient."""

    def test_default_init_uses_testnet(self):
        with patch("httpx.Client"):
            client = BybitClient()
            assert client._use_testnet is True
            assert "testnet" in client._base_url
            assert client._default_category == "linear"

    def test_mainnet_init(self):
        with patch("httpx.Client"):
            client = BybitClient(use_testnet=False)
            assert "testnet" not in client._base_url
            assert "bybit.com" in client._base_url

    def test_custom_category(self):
        with patch("httpx.Client"):
            client = BybitClient(default_category="spot")
            assert client._default_category == "spot"

    def test_name_is_bybit(self):
        with patch("httpx.Client"):
            client = BybitClient()
            assert client.name == "bybit"

    def test_is_connected_after_init(self):
        with patch("httpx.Client"):
            client = BybitClient()
            assert client.is_connected is True

    def test_repr(self):
        with patch("httpx.Client"):
            client = BybitClient(use_testnet=True)
            r = repr(client)
            assert "testnet" in r
            assert "read_only=True" in r

    def test_context_manager(self):
        with patch("httpx.Client"):
            with BybitClient() as client:
                assert client.is_connected is True
            assert client.is_connected is False


# ---------------------------------------------------------------------------
# FASE 9 — Fatia 1: separação Demo Trading vs Testnet
# ---------------------------------------------------------------------------

class TestBybitClientEnvironmentDemo:
    """Cobre o argumento NOVO `environment` ('testnet' | 'demo')."""

    def test_environment_demo_uses_api_demo_url(self):
        with patch("httpx.Client"):
            client = BybitClient(environment="demo")
            assert client._base_url == BybitClient.BASE_URL_DEMO
            assert client._base_url == "https://api-demo.bybit.com"
            assert client.environment == "demo"
            assert client.is_demo is True
            # demo NÃO é testnet — executors testnet recusam por design
            assert client.use_testnet is False
            assert client.is_mainnet is False

    def test_environment_testnet_uses_api_testnet_url(self):
        with patch("httpx.Client"):
            client = BybitClient(environment="testnet")
            assert client._base_url == BybitClient.BASE_URL_TESTNET
            assert "api-testnet.bybit.com" in client._base_url
            assert client.environment == "testnet"
            assert client.use_testnet is True
            assert client.is_demo is False

    def test_environment_overrides_legacy_use_testnet(self):
        with patch("httpx.Client"):
            # environment='demo' tem precedência sobre use_testnet=True
            client = BybitClient(environment="demo", use_testnet=True)
            assert client.is_demo is True
            assert client._base_url == BybitClient.BASE_URL_DEMO

    def test_environment_mainnet_string_rejected(self):
        # Não permitido — usuário deve usar use_testnet=False explicitamente
        with patch("httpx.Client"):
            with pytest.raises(ValueError, match="environment inválido"):
                BybitClient(environment="mainnet")

    def test_environment_invalid_string_rejected(self):
        with patch("httpx.Client"):
            with pytest.raises(ValueError, match="environment inválido"):
                BybitClient(environment="prod")

    def test_legacy_path_preserved_no_environment(self):
        """Sem environment, comportamento antigo é preservado byte-a-byte."""
        with patch("httpx.Client"):
            c_testnet = BybitClient(use_testnet=True)
            assert c_testnet.environment == "testnet"
            assert c_testnet.use_testnet is True
            assert c_testnet._base_url == BybitClient.BASE_URL_TESTNET

            c_mainnet = BybitClient(use_testnet=False)
            assert c_mainnet.environment == "mainnet"
            assert c_mainnet.is_mainnet is True
            assert c_mainnet._base_url == BybitClient.BASE_URL_MAINNET

    def test_repr_reflects_environment(self):
        with patch("httpx.Client"):
            c_demo = BybitClient(environment="demo")
            assert "env=demo" in repr(c_demo)
            assert "read_only=True" in repr(c_demo)

            c_testnet = BybitClient(environment="testnet")
            assert "env=testnet" in repr(c_testnet)


class TestPrivateAccessGateByEnvironment:
    """`_require_private_access` aceita demo/testnet, rejeita mainnet."""

    def test_mainnet_blocks_private_even_with_credentials(self):
        with patch("httpx.Client"):
            client = BybitClient(
                use_testnet=False,
                api_key="AKEY_fake",
                api_secret="ASEC_fake",
            )
            with pytest.raises(BybitExecutionBlockedError, match="MAINNET"):
                client._require_private_access()

    def test_demo_with_credentials_passes_private_guard(self):
        with patch("httpx.Client"):
            client = BybitClient(
                environment="demo",
                api_key="AKEY_demo",
                api_secret="ASEC_demo",
            )
            # NÃO levanta — demo + credentials = passa pelo guard local
            client._require_private_access()

    def test_testnet_with_credentials_passes_private_guard(self):
        with patch("httpx.Client"):
            client = BybitClient(
                environment="testnet",
                api_key="AKEY_test",
                api_secret="ASEC_test",
            )
            client._require_private_access()

    def test_demo_without_credentials_blocks_private(self):
        with patch("httpx.Client"):
            client = BybitClient(environment="demo")
            with pytest.raises(BybitExecutionBlockedError) as exc_info:
                client._require_private_access()
            msg = str(exc_info.value).lower()
            assert "credentials" in msg

    def test_demo_private_error_message_mentions_demo_or_testnet(self):
        with patch("httpx.Client"):
            client = BybitClient(environment="demo")
            with pytest.raises(BybitExecutionBlockedError) as exc_info:
                client._require_private_access()
            msg = str(exc_info.value).lower()
            # Mensagem atualizada deixa claro que demo é aceito
            assert "demo" in msg or "testnet" in msg


# ---------------------------------------------------------------------------
# Testes de get_ticker()
# ---------------------------------------------------------------------------

class TestBybitClientGetTicker:
    """Testa o método get_ticker()."""

    def test_get_ticker_returns_correct_values(self):
        response = _make_mock_response(_make_ticker_response(
            last_price="65000.50",
            bid="65000.00",
            ask="65001.00",
            volume="12345.678",
        ))

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.return_value = response

            client = BybitClient()
            ticker = client.get_ticker("BTCUSDT")

        assert ticker.symbol == "BTCUSDT"
        assert ticker.last_price == pytest.approx(65000.50)
        assert ticker.bid == pytest.approx(65000.00)
        assert ticker.ask == pytest.approx(65001.00)
        assert ticker.volume_24h == pytest.approx(12345.678)
        assert ticker.timestamp is not None

    def test_get_ticker_uses_default_category(self):
        response = _make_mock_response(_make_ticker_response())

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.return_value = response

            client = BybitClient(default_category="linear")
            client.get_ticker("BTCUSDT")

            call_params = mock_http.get.call_args
            params = call_params[1]["params"] if "params" in call_params[1] else call_params[0][1]
            # Verifica que category=linear foi passado
            assert "linear" in str(params)

    def test_get_ticker_override_category(self):
        response = _make_mock_response(_make_ticker_response())

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.return_value = response

            client = BybitClient(default_category="linear")
            client.get_ticker("BTCUSDT", category="spot")

            call_params = mock_http.get.call_args
            params = call_params[1].get("params", call_params[0][1] if len(call_params[0]) > 1 else {})
            assert "spot" in str(params)

    def test_get_ticker_raises_on_empty_list(self):
        body = {
            "retCode": 0,
            "retMsg": "OK",
            "result": {"list": []},
        }
        response = _make_mock_response(body)

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.return_value = response

            client = BybitClient()
            with pytest.raises(ValueError, match="Ticker vazio"):
                client.get_ticker("INVALID_SYMBOL")

    def test_get_ticker_raises_on_api_error(self):
        response = _make_mock_response(_make_error_response(10001, "symbol not found"))

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.return_value = response

            client = BybitClient()
            with pytest.raises(BybitAPIError) as exc_info:
                client.get_ticker("BTCUSDT")
            assert exc_info.value.ret_code == 10001

    def test_get_ticker_raises_on_http_error(self):
        import httpx
        response = _make_mock_response({}, status_code=429)

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.return_value = response

            client = BybitClient()
            with pytest.raises(ConnectionError):
                client.get_ticker("BTCUSDT")


# ---------------------------------------------------------------------------
# Testes de get_candles()
# ---------------------------------------------------------------------------

class TestBybitClientGetCandles:
    """Testa o método get_candles()."""

    def test_get_candles_returns_candles_in_chronological_order(self):
        """Bybit retorna mais recente primeiro — o método deve inverter."""
        response = _make_mock_response(_make_kline_response())

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.return_value = response

            client = BybitClient()
            candles = client.get_candles("BTCUSDT", timeframe="15", limit=3)

        assert len(candles) == 3
        # Deve estar ordenado do mais antigo para o mais recente
        assert candles[0].timestamp < candles[-1].timestamp

    def test_get_candles_parses_ohlcv_correctly(self):
        rows = [["1716134400000", "65100.0", "65200.0", "64900.0", "65050.0", "10.5", "682000"]]
        response = _make_mock_response(_make_kline_response(rows=rows))

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.return_value = response

            client = BybitClient()
            candles = client.get_candles("BTCUSDT", timeframe="15")

        assert len(candles) == 1
        c = candles[0]
        assert c.symbol == "BTCUSDT"
        assert c.timeframe == "15"
        assert c.open == pytest.approx(65100.0)
        assert c.high == pytest.approx(65200.0)
        assert c.low == pytest.approx(64900.0)
        assert c.close == pytest.approx(65050.0)
        assert c.volume == pytest.approx(10.5)

    def test_get_candles_uses_timeframe_map(self):
        """O campo interval deve ser mapeado corretamente para a Bybit."""
        response = _make_mock_response(_make_kline_response(rows=[]))

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.return_value = response

            client = BybitClient()
            client.get_candles("BTCUSDT", timeframe="15")

            call_kwargs = mock_http.get.call_args[1]
            params = call_kwargs.get("params", {})
            assert params.get("interval") == "15"

    def test_get_candles_maps_D_to_D(self):
        response = _make_mock_response(_make_kline_response(rows=[]))

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.return_value = response

            client = BybitClient()
            client.get_candles("BTCUSDT", timeframe="D")

            call_kwargs = mock_http.get.call_args[1]
            params = call_kwargs.get("params", {})
            assert params.get("interval") == "D"

    def test_get_candles_returns_empty_on_empty_list(self):
        response = _make_mock_response(_make_kline_response(rows=[]))

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.return_value = response

            client = BybitClient()
            candles = client.get_candles("BTCUSDT", timeframe="15")

        assert candles == []

    def test_get_candles_skips_malformed_rows(self):
        """Linhas incorretas devem ser ignoradas com log, sem lançar exceção."""
        rows = [
            ["1716134400000", "65100.0", "65200.0", "64900.0", "65050.0", "10.5", "682000"],
            ["INVALID", "NÃO_É_NÚMERO"],  # linha malformada
            ["1716120000000", "64900.0", "65150.0", "64800.0", "65100.0", "12.3", "799000"],
        ]
        response = _make_mock_response(_make_kline_response(rows=rows))

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.return_value = response

            client = BybitClient()
            candles = client.get_candles("BTCUSDT", timeframe="15")

        # Deve retornar as 2 candles válidas (a malformada é ignorada)
        assert len(candles) == 2

    def test_get_candles_raises_on_api_error(self):
        response = _make_mock_response(_make_error_response(10002, "invalid symbol"))

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.return_value = response

            client = BybitClient()
            with pytest.raises(BybitAPIError) as exc_info:
                client.get_candles("INVALID", timeframe="15")
            assert exc_info.value.ret_code == 10002


# ---------------------------------------------------------------------------
# Testes de get_order_book()
# ---------------------------------------------------------------------------

class TestBybitClientGetOrderBook:
    """Testa o método get_order_book()."""

    def test_get_order_book_parses_bids_and_asks(self):
        response = _make_mock_response(_make_orderbook_response())

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.return_value = response

            client = BybitClient()
            ob = client.get_order_book("BTCUSDT", depth=3)

        assert len(ob.bids) == 3
        assert len(ob.asks) == 3
        assert ob.best_bid == pytest.approx(65000.0)
        assert ob.best_ask == pytest.approx(65001.0)
        assert ob.mid_price == pytest.approx(65000.5)

    def test_get_order_book_uses_decimal_precision(self):
        """Preços devem ser parseados via Decimal antes de converter para float."""
        bids = [["65000.123456789", "0.1"]]
        asks = [["65001.987654321", "0.2"]]
        response = _make_mock_response(_make_orderbook_response(bids=bids, asks=asks))

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.return_value = response

            client = BybitClient()
            ob = client.get_order_book("BTCUSDT")

        # Verifica que o preço foi parseado com precisão
        assert abs(ob.bids[0][0] - 65000.123456789) < 1e-6

    def test_get_order_book_raises_on_api_error(self):
        response = _make_mock_response(_make_error_response(10003, "orderbook error"))

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.return_value = response

            client = BybitClient()
            with pytest.raises(BybitAPIError):
                client.get_order_book("BTCUSDT")


# ---------------------------------------------------------------------------
# Testes de Métodos de Execução Bloqueados
# ---------------------------------------------------------------------------

class TestBybitClientExecutionBlocked:
    """Garante que todos os métodos de execução estão bloqueados."""

    def get_client(self) -> BybitClient:
        with patch("httpx.Client"):
            return BybitClient()

    def test_place_market_order_is_blocked(self):
        """
        FASE 5: Sem credentials, métodos privados continuam bloqueados.
        Mensagem agora cita "credentials" / "endpoints privados" / "bloqueado".
        """
        client = self.get_client()
        with pytest.raises(BybitExecutionBlockedError) as exc_info:
            client.place_market_order("BTCUSDT", "buy", qty=0.01)
        msg = str(exc_info.value).lower()
        assert (
            "credentials" in msg
            or "bloqueado" in msg
            or "endpoints privados" in msg
        )

    def test_cancel_order_is_blocked(self):
        client = self.get_client()
        with pytest.raises(BybitExecutionBlockedError):
            client.cancel_order("BTCUSDT", "order123")

    def test_get_positions_is_blocked(self):
        client = self.get_client()
        with pytest.raises(BybitExecutionBlockedError):
            client.get_positions()

    def test_get_balance_is_blocked(self):
        client = self.get_client()
        with pytest.raises(BybitExecutionBlockedError):
            client.get_balance()


# ---------------------------------------------------------------------------
# Testes de Tratamento de Erros HTTP
# ---------------------------------------------------------------------------

class TestBybitClientErrorHandling:
    """Testa o tratamento de erros de rede e HTTP."""

    def test_timeout_raises_timeout_error(self):
        import httpx

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.side_effect = httpx.TimeoutException("timeout")

            client = BybitClient()
            with pytest.raises(TimeoutError, match="timeout"):
                client.get_ticker("BTCUSDT")

    def test_connection_error_raises_connection_error(self):
        import httpx

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.side_effect = httpx.ConnectError("connection refused")

            client = BybitClient()
            with pytest.raises(ConnectionError):
                client.get_ticker("BTCUSDT")

    def test_missing_result_field_raises_value_error(self):
        body = {"retCode": 0, "retMsg": "OK"}  # sem campo 'result'
        response = _make_mock_response(body)

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.return_value = response

            client = BybitClient()
            with pytest.raises(ValueError, match="result"):
                client.get_ticker("BTCUSDT")

    def test_missing_ret_code_raises_value_error(self):
        body = {"result": {}}  # sem retCode
        response = _make_mock_response(body)

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.return_value = response

            client = BybitClient()
            with pytest.raises(ValueError, match="retCode"):
                client.get_ticker("BTCUSDT")

    def test_non_zero_ret_code_raises_bybit_api_error(self):
        response = _make_mock_response(_make_error_response(110001, "Order does not exist"))

        with patch("httpx.Client") as mock_client_cls:
            mock_http = mock_client_cls.return_value
            mock_http.get.return_value = response

            client = BybitClient()
            with pytest.raises(BybitAPIError) as exc_info:
                client.get_ticker("BTCUSDT")
            assert exc_info.value.ret_code == 110001
            assert "Order does not exist" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Testes de BybitAPIError
# ---------------------------------------------------------------------------

class TestBybitAPIError:
    """Testa a exception BybitAPIError."""

    def test_bybit_api_error_attributes(self):
        err = BybitAPIError(10001, "params error", "/v5/market/tickers")
        assert err.ret_code == 10001
        assert err.ret_msg == "params error"
        assert err.endpoint == "/v5/market/tickers"

    def test_bybit_api_error_str_representation(self):
        err = BybitAPIError(10001, "params error", "/v5/market/tickers")
        s = str(err)
        assert "10001" in s
        assert "params error" in s
