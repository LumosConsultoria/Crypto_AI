"""
Testes do ModeGuard — Proteção de Modo de Operação
====================================================
Testa todas as regras de segurança do ModeGuard.

⚠️  Estes testes são CRÍTICOS para a segurança do sistema.
    Qualquer falha aqui indica risco de execução acidental de ordens reais.

Cobertura:
    - Modo paper: operações permitidas
    - Modo testnet: operações permitidas
    - Modo live sem confirmação: bloqueado
    - Modo live com confirmação parcial: bloqueado
    - Modo live com confirmação total: permitido
    - assert_not_live() em modo paper: passa
    - assert_not_live() em modo live: lança TradingModeError
    - get_status_summary(): retorna dados corretos
"""

import pytest

from crypto_trading_bot.config.settings import Settings, TradingMode
from crypto_trading_bot.core.mode_guard import ModeGuard, TradingModeError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_settings(
    mode: str = "paper",
    enable_live: bool = False,
) -> Settings:
    """Cria uma instância de Settings com valores customizados para testes."""
    # Cria Settings diretamente com valores, sem ler do .env
    return Settings(
        trading_mode=mode,
        enable_live_trading=enable_live,
    )


@pytest.fixture
def paper_settings():
    return _make_settings(mode="paper", enable_live=False)


@pytest.fixture
def testnet_settings():
    return _make_settings(mode="testnet", enable_live=False)


@pytest.fixture
def live_settings_disabled():
    """Modo live configurado, mas ENABLE_LIVE_TRADING=false."""
    return _make_settings(mode="live", enable_live=False)


@pytest.fixture
def live_settings_enabled():
    """Modo live com ENABLE_LIVE_TRADING=true (perigoso — apenas para teste)."""
    return _make_settings(mode="live", enable_live=True)


# ---------------------------------------------------------------------------
# Testes de Estado
# ---------------------------------------------------------------------------

class TestModeGuardState:
    """Testa as propriedades de estado do ModeGuard."""

    def test_paper_mode_is_paper(self, paper_settings):
        guard = ModeGuard(paper_settings)
        assert guard.is_paper is True
        assert guard.is_testnet is False
        assert guard.is_live is False
        assert guard.is_safe is True

    def test_testnet_mode_is_testnet(self, testnet_settings):
        guard = ModeGuard(testnet_settings)
        assert guard.is_paper is False
        assert guard.is_testnet is True
        assert guard.is_live is False
        assert guard.is_safe is True

    def test_live_mode_with_disabled_flag_is_not_live(self, live_settings_disabled):
        """Modo live no .env mas ENABLE_LIVE_TRADING=false → não é live."""
        guard = ModeGuard(live_settings_disabled)
        assert guard.is_live is False
        assert guard.is_safe is True

    def test_live_mode_with_enabled_flag_is_live(self, live_settings_enabled):
        """Modo live + ENABLE_LIVE_TRADING=true → is_live=True."""
        guard = ModeGuard(live_settings_enabled)
        assert guard.is_live is True
        assert guard.is_safe is False

    def test_mode_property_returns_correct_enum(self, paper_settings):
        guard = ModeGuard(paper_settings)
        assert guard.mode == TradingMode.PAPER

    def test_default_settings_is_paper(self, monkeypatch):
        """Sem configuração alguma, o padrão deve ser paper.

        Isola do .env real (FASE 7: pode estar em TRADING_MODE=testnet) e de
        variáveis de ambiente — testa o DEFAULT puro, não a config local.
        """
        monkeypatch.delenv("TRADING_MODE", raising=False)
        monkeypatch.delenv("ENABLE_LIVE_TRADING", raising=False)
        monkeypatch.delenv("ENABLE_TESTNET_EXECUTION", raising=False)
        settings = Settings(_env_file=None)  # ignora .env; usa só os defaults
        guard = ModeGuard(settings)
        assert guard.is_paper is True
        assert guard.is_safe is True


# ---------------------------------------------------------------------------
# Testes de assert_not_live()
# ---------------------------------------------------------------------------

class TestAssertNotLive:
    """Testa o método assert_not_live()."""

    def test_paper_mode_passes_assert_not_live(self, paper_settings):
        """Em modo paper, assert_not_live() não deve lançar exceção."""
        guard = ModeGuard(paper_settings)
        guard.assert_not_live("teste")  # Não deve lançar

    def test_testnet_mode_passes_assert_not_live(self, testnet_settings):
        """Em modo testnet, assert_not_live() não deve lançar exceção."""
        guard = ModeGuard(testnet_settings)
        guard.assert_not_live("teste")  # Não deve lançar

    def test_live_mode_disabled_passes_assert_not_live(self, live_settings_disabled):
        """live + enable_live=False → is_live=False → não deve lançar."""
        guard = ModeGuard(live_settings_disabled)
        guard.assert_not_live("teste")  # Não deve lançar

    def test_live_mode_enabled_raises_trading_mode_error(self, live_settings_enabled):
        """live + enable_live=True → assert_not_live() deve lançar TradingModeError."""
        guard = ModeGuard(live_settings_enabled)
        with pytest.raises(TradingModeError) as exc_info:
            guard.assert_not_live("operação de teste")
        # A mensagem usa "BLOQUEADA" ou "BLOQUEADO" dependendo do contexto em pt-BR
        # Verificamos apenas a raiz "BLOQUEAD" para ser agnóstico ao gênero
        msg_upper = str(exc_info.value).upper()
        assert "BLOQUEAD" in msg_upper or "MODEGUARD" in msg_upper

    def test_assert_safe_mode_is_alias_for_assert_not_live(self, paper_settings):
        """assert_safe_mode() deve ser equivalente a assert_not_live()."""
        guard = ModeGuard(paper_settings)
        guard.assert_safe_mode()  # Não deve lançar

    def test_assert_safe_mode_raises_on_live(self, live_settings_enabled):
        guard = ModeGuard(live_settings_enabled)
        with pytest.raises(TradingModeError):
            guard.assert_safe_mode()


# ---------------------------------------------------------------------------
# Testes de assert_live_allowed()
# ---------------------------------------------------------------------------

class TestAssertLiveAllowed:
    """Testa as verificações de triple-lock para live trading."""

    def test_paper_mode_blocks_live(self, paper_settings):
        """Modo paper nunca pode ser autorizado como live."""
        guard = ModeGuard(paper_settings)
        with pytest.raises(TradingModeError) as exc_info:
            guard.assert_live_allowed(confirm_live_trading=True)
        assert "live" in str(exc_info.value).lower()

    def test_testnet_mode_blocks_live(self, testnet_settings):
        """Modo testnet nunca pode ser autorizado como live."""
        guard = ModeGuard(testnet_settings)
        with pytest.raises(TradingModeError):
            guard.assert_live_allowed(confirm_live_trading=True)

    def test_live_mode_without_env_flag_blocks(self, live_settings_disabled):
        """TRADING_MODE=live mas ENABLE_LIVE_TRADING=false → bloqueado."""
        guard = ModeGuard(live_settings_disabled)
        with pytest.raises(TradingModeError) as exc_info:
            guard.assert_live_allowed(confirm_live_trading=True)
        assert "ENABLE_LIVE_TRADING" in str(exc_info.value)

    def test_live_mode_without_explicit_confirm_blocks(self, live_settings_enabled):
        """TRADING_MODE=live + ENABLE_LIVE_TRADING=true mas sem confirm → bloqueado."""
        guard = ModeGuard(live_settings_enabled)
        with pytest.raises(TradingModeError) as exc_info:
            guard.assert_live_allowed(confirm_live_trading=False)
        assert "confirm_live_trading" in str(exc_info.value)

    def test_live_mode_with_all_conditions_passes(self, live_settings_enabled):
        """Todas as condições satisfeitas → deve passar sem exceção."""
        guard = ModeGuard(live_settings_enabled)
        # Não deve lançar exceção — todas as 3 condições satisfeitas
        guard.assert_live_allowed(confirm_live_trading=True)


# ---------------------------------------------------------------------------
# Testes do Status Summary
# ---------------------------------------------------------------------------

class TestModeGuardStatusSummary:
    """Testa o método get_status_summary()."""

    def test_paper_status_summary(self, paper_settings):
        guard = ModeGuard(paper_settings)
        summary = guard.get_status_summary()

        assert summary["mode"] == "paper"
        assert summary["is_paper"] is True
        assert summary["is_testnet"] is False
        assert summary["is_live"] is False
        assert summary["is_safe"] is True
        assert summary["warning"] is None

    def test_live_status_summary_has_warning(self, live_settings_enabled):
        guard = ModeGuard(live_settings_enabled)
        summary = guard.get_status_summary()

        assert summary["mode"] == "live"
        assert summary["is_live"] is True
        assert summary["warning"] is not None
        assert "LIVE" in summary["warning"].upper() or "REAL" in summary["warning"].upper()

    def test_testnet_status_summary(self, testnet_settings):
        guard = ModeGuard(testnet_settings)
        summary = guard.get_status_summary()

        assert summary["mode"] == "testnet"
        assert summary["is_safe"] is True
        assert summary["warning"] is None


# ---------------------------------------------------------------------------
# Testes de Repr
# ---------------------------------------------------------------------------

class TestModeGuardRepr:
    """Testa a representação textual do ModeGuard."""

    def test_paper_repr_contains_safe(self, paper_settings):
        guard = ModeGuard(paper_settings)
        assert "paper" in repr(guard).lower()
        assert "SAFE" in repr(guard)

    def test_live_repr_contains_live_marker(self, live_settings_enabled):
        guard = ModeGuard(live_settings_enabled)
        assert "live" in repr(guard).lower()
        assert "LIVE" in repr(guard)
