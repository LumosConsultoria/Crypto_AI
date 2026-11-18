"""
conftest.py — Configuração Global do pytest
=============================================
Fixtures e configurações compartilhadas por todos os testes.
Carregado automaticamente pelo pytest.

StubStrategy e make_stub_engine estão em tests/helpers.py.
"""

import os
import sys
from pathlib import Path

import pytest

# Garante que o pacote src/ está no sys.path para imports nos testes
src_path = str(Path(__file__).parent.parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Importa helpers de teste (necessário para que conftest os re-exporte se necessário)
from tests.helpers import StubStrategy, make_stub_engine


# ---------------------------------------------------------------------------
# Fixtures Globais
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_os_environ():
    """Snapshot + restore de os.environ em torno de cada teste.

    Garante isolamento hermetico: nenhum teste pode vazar variaveis de
    ambiente para outro (ex.: import de scripts/run_demo_30_min_endurance.py
    chama load_dotenv() no import e injeta TRADING_MODE/ENABLE_DEMO_EXECUTION
    do .env em os.environ, quebrando testes que constroem
    Settings(_env_file=None) e leem os.environ). Restaurar aqui elimina
    essa classe de falhas dependentes de ordem.
    """
    snapshot = dict(os.environ)
    yield
    # Restaura exatamente o estado anterior (remove adicoes, repoe remocoes).
    os.environ.clear()
    os.environ.update(snapshot)


@pytest.fixture(autouse=True)
def clear_settings_cache():
    """
    Limpa o cache das Settings antes de cada teste.
    Garante que cada teste começa com configurações limpas.
    """
    from crypto_trading_bot.config.settings import get_settings
    from crypto_trading_bot.config.risk_config import get_risk_config
    from crypto_trading_bot.config.exchange_config import get_exchange_config

    get_settings.cache_clear()
    get_risk_config.cache_clear()
    get_exchange_config.cache_clear()

    yield

    get_settings.cache_clear()
    get_risk_config.cache_clear()
    get_exchange_config.cache_clear()


@pytest.fixture
def paper_mode_env(monkeypatch):
    """Fixture que garante variáveis de ambiente para modo paper."""
    monkeypatch.setenv("TRADING_MODE", "paper")
    monkeypatch.setenv("ENABLE_LIVE_TRADING", "false")
    monkeypatch.setenv("BYBIT_USE_TESTNET", "true")
    yield


@pytest.fixture
def live_mode_env(monkeypatch):
    """
    Fixture que simula variáveis de ambiente para modo live (APENAS TESTES).
    ⚠️  SOMENTE para testar que o ModeGuard bloqueia corretamente o modo live.
    """
    monkeypatch.setenv("TRADING_MODE", "live")
    monkeypatch.setenv("ENABLE_LIVE_TRADING", "true")
    yield


# ---------------------------------------------------------------------------
# Fixtures para Cenários Determinísticos
# ---------------------------------------------------------------------------

def _make_stub_buy_signal():
    from crypto_trading_bot.strategies.signal_model import StrategySignal
    return StrategySignal.buy(
        symbol="BTCUSDT",
        strategy_name="stub_strategy",
        entry_price=65000.0,
        stop_loss_price=64000.0,
        take_profit_price=67000.0,
        position_size_usd=200.0,
    )


def _make_stub_hold_signal():
    from crypto_trading_bot.strategies.signal_model import StrategySignal
    return StrategySignal.hold(
        symbol="BTCUSDT",
        strategy_name="stub_strategy",
        reason="stub: sem condições de entrada",
    )


@pytest.fixture
def stub_buy_signal():
    """Sinal BUY padrão para testes determinísticos."""
    return _make_stub_buy_signal()


@pytest.fixture
def stub_hold_signal():
    """Sinal HOLD padrão para testes determinísticos."""
    return _make_stub_hold_signal()


@pytest.fixture
def engine_buy_scenario():
    """BotEngine garantidamente BUY: capital=5000, position=200."""
    return make_stub_engine(_make_stub_buy_signal(), capital=5000.0, n_candles=60)


@pytest.fixture
def engine_hold_scenario():
    """BotEngine garantidamente HOLD: StubStrategy retorna HOLD."""
    return make_stub_engine(_make_stub_hold_signal(), capital=5000.0, n_candles=60)


@pytest.fixture
def engine_risk_blocked_scenario():
    """BotEngine garantidamente risk_blocked: capital=1.0, position=200."""
    return make_stub_engine(_make_stub_buy_signal(), capital=1.0, n_candles=60)


@pytest.fixture
def engine_no_candles_scenario():
    """BotEngine garantidamente no_candles: MockExchange sem dados."""
    return make_stub_engine(_make_stub_buy_signal(), capital=5000.0, n_candles=0)


@pytest.fixture
def engine_insufficient_data_scenario():
    """BotEngine garantidamente insufficient_data: n_candles=3."""
    return make_stub_engine(_make_stub_buy_signal(), capital=5000.0, n_candles=3)
