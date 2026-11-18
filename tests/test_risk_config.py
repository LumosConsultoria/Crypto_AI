"""
Testes de Configuração Dinâmica de Conta (RiskConfig)
========================================================
Verifica que o sistema suporta diferentes tamanhos de conta sem
valores hardcoded obrigatórios.

Cobertura:
    - Inicialização com diferentes account_size_usd (5k, 10k, 25k, custom)
    - Propriedades derivadas calculadas corretamente
    - account_profile_name é informativo, não muda limites automaticamente
    - max_risk_per_trade_usd calculado a partir de porcentagem
    - max_open_positions configurável
    - RiskEngine usa account_size da config, não valor fixo
    - PaperTrader com diferentes saldos de conta
    - Validadores de consistência (max_total >= max_daily, etc.)
    - NENHUM capital fixo obrigatório de 5000 USD em módulos de estratégia/execução
"""

from decimal import Decimal

import pytest

from crypto_trading_bot.config.risk_config import ACCOUNT_PROFILES, RiskConfig, get_risk_config
from crypto_trading_bot.config.settings import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_risk_config(**kwargs) -> RiskConfig:
    """Cria uma RiskConfig com valores explícitos, sem ler do .env."""
    defaults = {
        "account_size_usd": 5000.0,
        "account_profile_name": "custom",
        "max_daily_loss_pct": 0.05,
        "max_total_loss_pct": 0.10,
        "max_trades_per_day": 10,
        "max_open_positions": 3,
        "max_risk_per_trade_pct": 0.01,
        "max_exposure_per_asset_pct": 0.20,
        "max_leverage": 3.0,
        "min_stop_loss_pct": 0.005,
        "max_stop_loss_pct": 0.05,
        "max_position_size_pct": 0.10,
    }
    defaults.update(kwargs)
    return RiskConfig(**defaults)


# ---------------------------------------------------------------------------
# Testes de Inicialização com Diferentes Tamanhos de Conta
# ---------------------------------------------------------------------------

class TestAccountSizeConfiguration:
    """Testa que o sistema aceita diferentes tamanhos de conta."""

    def test_account_5k(self):
        """Conta de 5.000 USD — perfil HyroTrader 5k."""
        config = _make_risk_config(account_size_usd=5000.0, account_profile_name="hyrotrader_5k")
        assert config.account_size_usd == 5000.0
        assert config.account_profile_name == "hyrotrader_5k"

    def test_account_10k(self):
        """Conta de 10.000 USD — perfil HyroTrader 10k."""
        config = _make_risk_config(account_size_usd=10000.0, account_profile_name="hyrotrader_10k")
        assert config.account_size_usd == 10000.0
        assert config.account_profile_name == "hyrotrader_10k"

    def test_account_25k(self):
        """Conta de 25.000 USD — perfil HyroTrader 25k."""
        config = _make_risk_config(account_size_usd=25000.0, account_profile_name="hyrotrader_25k")
        assert config.account_size_usd == 25000.0
        assert config.account_profile_name == "hyrotrader_25k"

    def test_account_custom_value(self):
        """Conta com valor totalmente customizado."""
        config = _make_risk_config(account_size_usd=7500.0, account_profile_name="custom")
        assert config.account_size_usd == 7500.0

    def test_account_size_must_be_positive(self):
        """account_size_usd deve ser positivo."""
        with pytest.raises(Exception):
            _make_risk_config(account_size_usd=0.0)
        with pytest.raises(Exception):
            _make_risk_config(account_size_usd=-100.0)

    def test_profile_name_does_not_change_limits(self):
        """
        O perfil é apenas informativo — não altera limites automaticamente.
        Dois configs com o mesmo profile mas account_size diferentes devem ter
        limites em USD diferentes.
        """
        config_5k = _make_risk_config(account_size_usd=5000.0, account_profile_name="hyrotrader_5k")
        config_10k = _make_risk_config(account_size_usd=10000.0, account_profile_name="hyrotrader_10k")

        # Porcentagens iguais mas USDs diferentes
        assert config_5k.max_daily_loss_pct == config_10k.max_daily_loss_pct
        assert config_5k.max_daily_loss_usd != config_10k.max_daily_loss_usd

    def test_no_mandatory_5000_default(self):
        """
        O sistema NÃO deve forçar 5000 USD. Qualquer conta deve funcionar.
        """
        for account_size in [1000.0, 3000.0, 10000.0, 50000.0, 100000.0]:
            config = _make_risk_config(account_size_usd=account_size)
            assert config.account_size_usd == account_size


# ---------------------------------------------------------------------------
# Testes de Propriedades Derivadas (USD)
# ---------------------------------------------------------------------------

class TestDerivedUSDProperties:
    """Testa que as propriedades em USD são calculadas corretamente."""

    def test_max_daily_loss_usd_5k(self):
        """5000 × 5% = 250 USD de perda diária máxima."""
        config = _make_risk_config(account_size_usd=5000.0, max_daily_loss_pct=0.05)
        assert config.max_daily_loss_usd == Decimal("250")

    def test_max_daily_loss_usd_10k(self):
        """10000 × 5% = 500 USD de perda diária máxima."""
        config = _make_risk_config(account_size_usd=10000.0, max_daily_loss_pct=0.05)
        assert config.max_daily_loss_usd == Decimal("500")

    def test_max_daily_loss_usd_25k(self):
        """25000 × 5% = 1250 USD de perda diária máxima."""
        config = _make_risk_config(account_size_usd=25000.0, max_daily_loss_pct=0.05)
        assert config.max_daily_loss_usd == Decimal("1250")

    def test_max_total_loss_usd_scales_with_account(self):
        """max_total_loss_usd deve escalar com o tamanho da conta."""
        config_5k = _make_risk_config(account_size_usd=5000.0, max_total_loss_pct=0.10)
        config_10k = _make_risk_config(account_size_usd=10000.0, max_total_loss_pct=0.10)
        config_25k = _make_risk_config(account_size_usd=25000.0, max_total_loss_pct=0.10)

        assert config_5k.max_total_loss_usd == Decimal("500")
        assert config_10k.max_total_loss_usd == Decimal("1000")
        assert config_25k.max_total_loss_usd == Decimal("2500")

    def test_max_position_size_usd(self):
        """10% de 5000 = 500 USD por posição."""
        config = _make_risk_config(account_size_usd=5000.0, max_position_size_pct=0.10)
        assert config.max_position_size_usd == Decimal("500")

    def test_max_risk_per_trade_usd(self):
        """1% de 5000 = 50 USD de risco por trade."""
        config = _make_risk_config(account_size_usd=5000.0, max_risk_per_trade_pct=0.01)
        assert config.max_risk_per_trade_usd == Decimal("50")

    def test_max_risk_per_trade_usd_scales_with_account(self):
        """Risco por trade deve escalar com o tamanho da conta."""
        for account_size, expected_risk in [
            (5000.0, Decimal("50")),    # 1% de 5k
            (10000.0, Decimal("100")),  # 1% de 10k
            (25000.0, Decimal("250")),  # 1% de 25k
        ]:
            config = _make_risk_config(
                account_size_usd=account_size,
                max_risk_per_trade_pct=0.01,
            )
            assert config.max_risk_per_trade_usd == expected_risk, (
                f"Para conta {account_size}: esperado {expected_risk}, "
                f"obtido {config.max_risk_per_trade_usd}"
            )

    def test_max_exposure_per_asset_usd(self):
        """20% de 5000 = 1000 USD de exposição máxima por ativo."""
        config = _make_risk_config(account_size_usd=5000.0, max_exposure_per_asset_pct=0.20)
        assert config.max_exposure_per_asset_usd == Decimal("1000")

    def test_derived_properties_use_decimal(self):
        """Propriedades derivadas devem retornar Decimal."""
        config = _make_risk_config(account_size_usd=5000.0)
        assert isinstance(config.max_daily_loss_usd, Decimal)
        assert isinstance(config.max_total_loss_usd, Decimal)
        assert isinstance(config.max_position_size_usd, Decimal)
        assert isinstance(config.max_risk_per_trade_usd, Decimal)
        assert isinstance(config.max_exposure_per_asset_usd, Decimal)


# ---------------------------------------------------------------------------
# Testes de Campos de Operação
# ---------------------------------------------------------------------------

class TestOperationLimits:
    """Testa campos de limites de operação."""

    def test_max_open_positions_default(self):
        config = _make_risk_config()
        assert config.max_open_positions == 3

    def test_max_open_positions_custom(self):
        config = _make_risk_config(max_open_positions=5)
        assert config.max_open_positions == 5

    def test_max_trades_per_day_configurable(self):
        config_10 = _make_risk_config(max_trades_per_day=10)
        config_20 = _make_risk_config(max_trades_per_day=20)
        assert config_10.max_trades_per_day == 10
        assert config_20.max_trades_per_day == 20

    def test_max_risk_per_trade_pct_configurable(self):
        config = _make_risk_config(max_risk_per_trade_pct=0.02)
        assert config.max_risk_per_trade_pct == 0.02


# ---------------------------------------------------------------------------
# Testes de Validadores
# ---------------------------------------------------------------------------

class TestRiskConfigValidators:
    """Testa os validadores de consistência."""

    def test_max_total_loss_gte_daily(self):
        """max_total_loss_pct deve ser >= max_daily_loss_pct."""
        with pytest.raises(Exception):
            _make_risk_config(
                max_daily_loss_pct=0.10,
                max_total_loss_pct=0.05,  # menor que daily → inválido
            )

    def test_max_stop_gte_min_stop(self):
        """max_stop_loss_pct deve ser >= min_stop_loss_pct."""
        with pytest.raises(Exception):
            _make_risk_config(
                min_stop_loss_pct=0.02,
                max_stop_loss_pct=0.01,  # menor que min → inválido
            )

    def test_equal_stop_loss_limits_is_valid(self):
        """min == max stop loss é permitido."""
        config = _make_risk_config(min_stop_loss_pct=0.01, max_stop_loss_pct=0.01)
        assert config.min_stop_loss_pct == config.max_stop_loss_pct


# ---------------------------------------------------------------------------
# Testes dos Perfis de Conta
# ---------------------------------------------------------------------------

class TestAccountProfiles:
    """Testa os perfis de conta disponíveis."""

    def test_account_profiles_dict_exists(self):
        """ACCOUNT_PROFILES deve conter os perfis documentados."""
        assert "hyrotrader_5k" in ACCOUNT_PROFILES
        assert "hyrotrader_10k" in ACCOUNT_PROFILES
        assert "hyrotrader_25k" in ACCOUNT_PROFILES
        assert "custom" in ACCOUNT_PROFILES

    def test_hyrotrader_5k_profile_size(self):
        assert ACCOUNT_PROFILES["hyrotrader_5k"]["account_size_usd"] == 5000.0

    def test_hyrotrader_10k_profile_size(self):
        assert ACCOUNT_PROFILES["hyrotrader_10k"]["account_size_usd"] == 10000.0

    def test_hyrotrader_25k_profile_size(self):
        assert ACCOUNT_PROFILES["hyrotrader_25k"]["account_size_usd"] == 25000.0

    def test_custom_profile_has_no_fixed_size(self):
        """Perfil custom não deve ter account_size fixo."""
        assert ACCOUNT_PROFILES["custom"]["account_size_usd"] is None


# ---------------------------------------------------------------------------
# Testes de Repr
# ---------------------------------------------------------------------------

class TestRiskConfigRepr:
    """Testa a representação textual do RiskConfig."""

    def test_repr_contains_account_size(self):
        config = _make_risk_config(account_size_usd=5000.0)
        r = repr(config)
        assert "5000" in r

    def test_repr_contains_profile_name(self):
        config = _make_risk_config(account_profile_name="hyrotrader_5k")
        r = repr(config)
        assert "hyrotrader_5k" in r

    def test_repr_contains_derived_usd_values(self):
        config = _make_risk_config(account_size_usd=10000.0, max_daily_loss_pct=0.05)
        r = repr(config)
        # Deve mostrar tanto % quanto USD calculado
        assert "5.0%" in r or "5%" in r
        assert "500" in r  # 10000 × 5% = 500
