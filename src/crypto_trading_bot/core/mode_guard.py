"""
ModeGuard — Proteção de Modo de Operação
==========================================
Componente de segurança CRÍTICO que protege contra execução real acidental.

Regras de segurança:
    1. O modo padrão é SEMPRE "paper" (simulação).
    2. Modo "testnet" requer configuração explícita no .env.
    3. Modo "live" requer:
       - TRADING_MODE=live no .env
       - ENABLE_LIVE_TRADING=true no .env
       - Parâmetro confirm_live_trading=True na chamada explícita.
    4. Qualquer falha nas verificações lança TradingModeError.
    5. Este módulo nunca deve ser contornado.

⛔  NUNCA modifique este arquivo para remover verificações de segurança.
    Qualquer alteração aqui deve ser revisada e documentada.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from crypto_trading_bot.config.settings import Settings, TradingMode, get_settings
from crypto_trading_bot.logging_system.logger import get_audit_logger

_logger = get_audit_logger(__name__)


class TradingModeError(RuntimeError):
    """
    Exceção lançada quando uma operação é bloqueada pelo ModeGuard.

    Esta exceção indica que o sistema tentou executar uma operação
    não permitida no modo atual de operação.
    """
    pass


class OperationType(str, Enum):
    """Tipos de operação que o ModeGuard pode verificar."""
    PLACE_ORDER = "place_order"
    CANCEL_ORDER = "cancel_order"
    CLOSE_POSITION = "close_position"
    CONNECT_LIVE_API = "connect_live_api"
    MODIFY_LEVERAGE = "modify_leverage"
    ANY_REAL_ACTION = "any_real_action"


class ModeGuard:
    """
    Guardião de modo de operação.

    Deve ser instanciado uma vez e verificado antes de qualquer
    operação que possa enviar ordens reais para a exchange.

    Exemplo de uso seguro:
        guard = ModeGuard()
        guard.assert_not_live("Enviando ordem")  # Bloqueia em modo live

    Exemplo de uso com permissão explícita (APENAS para executores reais):
        guard = ModeGuard()
        guard.assert_live_allowed(confirm_live_trading=True)  # Exige confirmação
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        """
        Inicializa o ModeGuard com as configurações do sistema.

        Args:
            settings: Instância de Settings. Se None, carrega automaticamente.
        """
        self._settings = settings or get_settings()
        self._mode = self._settings.trading_mode
        self._live_enabled = self._settings.enable_live_trading
        # FASE 5 — trava dupla para execução em testnet (não afrouxa live)
        self._testnet_execution_enabled = self._settings.enable_testnet_execution
        # FASE 9 Fatia 2 — trava dupla para execução em Bybit Demo Trading
        # (paralela à testnet; também não afrouxa live)
        self._demo_execution_enabled = self._settings.enable_demo_execution

        _logger.info(
            f"ModeGuard inicializado | "
            f"mode={self._mode.value} | "
            f"live_enabled={self._live_enabled} | "
            f"testnet_exec_enabled={self._testnet_execution_enabled} | "
            f"demo_exec_enabled={self._demo_execution_enabled} | "
            f"safe={self.is_safe}"
        )

    # --- PROPRIEDADES DE ESTADO ---

    @property
    def mode(self) -> TradingMode:
        """Modo de operação atual."""
        return self._mode

    @property
    def is_paper(self) -> bool:
        """Verdadeiro se o modo é paper trading."""
        return self._mode == TradingMode.PAPER

    @property
    def is_testnet(self) -> bool:
        """Verdadeiro se o modo é testnet."""
        return self._mode == TradingMode.TESTNET

    @property
    def is_demo(self) -> bool:
        """FASE 9 Fatia 2 — Verdadeiro se o modo é demo (Bybit Demo Trading)."""
        return self._mode == TradingMode.DEMO

    @property
    def is_live(self) -> bool:
        """
        Verdadeiro APENAS se modo=live E enable_live_trading=true.
        A simples presença de TRADING_MODE=live NÃO é suficiente.
        """
        return (
            self._mode == TradingMode.LIVE
            and self._live_enabled is True
        )

    @property
    def is_safe(self) -> bool:
        """
        Verdadeiro se o sistema está em modo seguro (sem ordens reais).
        Equivalente a: not is_live.
        """
        return not self.is_live

    # --- VERIFICAÇÕES DE SEGURANÇA ---

    def assert_not_live(self, context: str = "") -> None:
        """
        Garante que o sistema NÃO está em modo live.

        Use isto em qualquer lugar onde ordens reais não devem ser enviadas.
        Lança TradingModeError se o modo for live.

        Args:
            context: Descrição do contexto para o log de erro.

        Raises:
            TradingModeError: Se o modo for live.
        """
        if self.is_live:
            msg = (
                f"⛔ OPERAÇÃO BLOQUEADA PELO MODEGUARD: modo live não permitido aqui."
                f"{f' Contexto: {context}' if context else ''}"
            )
            _logger.error(msg)
            raise TradingModeError(msg)

    def assert_safe_mode(self, context: str = "") -> None:
        """
        Alias para assert_not_live(). Garante que estamos em modo seguro.

        Args:
            context: Descrição do contexto para o log.

        Raises:
            TradingModeError: Se o modo for live.
        """
        self.assert_not_live(context)

    def assert_live_allowed(
        self,
        confirm_live_trading: bool = False,
        context: str = "",
    ) -> None:
        """
        Verifica se live trading está EXPLICITAMENTE autorizado.

        Esta é a ÚNICA forma de passar pelo ModeGuard em modo live.
        Requer:
            1. TRADING_MODE=live no .env
            2. ENABLE_LIVE_TRADING=true no .env
            3. confirm_live_trading=True passado explicitamente como argumento

        Args:
            confirm_live_trading: DEVE ser True para permitir execução live.
                                   É um parâmetro intencional — não use True
                                   a não ser que tenha consciência plena do que faz.
            context: Descrição do contexto para o log.

        Raises:
            TradingModeError: Se qualquer condição não for satisfeita.
        """
        # Verificação 1: modo deve ser live
        if self._mode != TradingMode.LIVE:
            msg = (
                f"⛔ Live trading bloqueado: TRADING_MODE={self._mode.value} "
                f"(necessário: live). {context}"
            )
            _logger.error(msg)
            raise TradingModeError(msg)

        # Verificação 2: ENABLE_LIVE_TRADING deve ser true no .env
        if not self._live_enabled:
            msg = (
                f"⛔ Live trading bloqueado: ENABLE_LIVE_TRADING=false. "
                f"Para habilitar, configure ENABLE_LIVE_TRADING=true no .env. "
                f"ATENÇÃO: Isso permite envio de ordens reais com dinheiro real. {context}"
            )
            _logger.error(msg)
            raise TradingModeError(msg)

        # Verificação 3: confirmação explícita na chamada
        if not confirm_live_trading:
            msg = (
                f"⛔ Live trading bloqueado: confirm_live_trading=False. "
                f"Para executar, passe confirm_live_trading=True explicitamente. "
                f"ATENÇÃO: Isso é intencional — protege contra execução acidental. {context}"
            )
            _logger.error(msg)
            raise TradingModeError(msg)

        # Todas as verificações passaram — registra com destaque
        _logger.warning(
            f"⚠️  LIVE TRADING AUTORIZADO | "
            f"mode={self._mode.value} | "
            f"live_enabled={self._live_enabled} | "
            f"explicit_confirmation=True | "
            f"context={context or 'N/A'}"
        )

    # -----------------------------------------------------------------------
    # FASE 5 — Trava dupla para execução em testnet (NÃO afrouxa live)
    # -----------------------------------------------------------------------

    @property
    def is_testnet_execution_allowed(self) -> bool:
        """
        Verdadeiro APENAS se trading_mode=testnet E enable_testnet_execution=true.

        ⚠️  Não confundir com `is_testnet` (que só verifica o modo, não a flag).
        ⚠️  Não confundir com `is_live` (que é independente desta property).
        """
        return (
            self._mode == TradingMode.TESTNET
            and self._testnet_execution_enabled is True
        )

    def assert_testnet_execution_allowed(
        self,
        confirm_testnet_execution: bool = False,
        context: str = "",
    ) -> None:
        """
        FASE 5 — Verifica se execução em TESTNET está EXPLICITAMENTE autorizada.

        ⚠️  Esta verificação é DISTINTA de assert_live_allowed.
        ⚠️  NÃO afrouxa nenhuma trava de live trading.
        ⚠️  Mainnet/live continua exigindo o triple-lock de assert_live_allowed.

        Triple-lock para testnet:
            1. TRADING_MODE=testnet no .env
            2. ENABLE_TESTNET_EXECUTION=true no .env
            3. confirm_testnet_execution=True passado explicitamente

        Args:
            confirm_testnet_execution: DEVE ser True. Parâmetro intencional
                                       que protege contra execução acidental
                                       de ordens (mesmo que em testnet).
            context: Descrição do contexto para o log.

        Raises:
            TradingModeError: Se qualquer condição não for satisfeita.
        """
        # Verificação 1: modo deve ser testnet
        if self._mode != TradingMode.TESTNET:
            msg = (
                f"⛔ Testnet execution bloqueada: TRADING_MODE={self._mode.value} "
                f"(necessário: testnet). {context}"
            )
            _logger.error(msg)
            raise TradingModeError(msg)

        # Verificação 2: ENABLE_TESTNET_EXECUTION deve ser true no .env
        if not self._testnet_execution_enabled:
            msg = (
                f"⛔ Testnet execution bloqueada: ENABLE_TESTNET_EXECUTION=false. "
                f"Para habilitar, configure ENABLE_TESTNET_EXECUTION=true no .env. "
                f"Lembre-se: testnet usa credentials reais (mesmo que sem dinheiro real). "
                f"{context}"
            )
            _logger.error(msg)
            raise TradingModeError(msg)

        # Verificação 3: confirmação explícita na chamada
        if not confirm_testnet_execution:
            msg = (
                f"⛔ Testnet execution bloqueada: confirm_testnet_execution=False. "
                f"Para executar, passe confirm_testnet_execution=True explicitamente. "
                f"Esta proteção evita execução acidental mesmo em testnet. {context}"
            )
            _logger.error(msg)
            raise TradingModeError(msg)

        # Todas as verificações passaram — registra com destaque (sem secrets!)
        _logger.warning(
            f"⚠️  TESTNET EXECUTION AUTORIZADA | "
            f"mode={self._mode.value} | "
            f"testnet_execution_enabled={self._testnet_execution_enabled} | "
            f"explicit_confirmation=True | "
            f"context={context or 'N/A'}"
        )

    # -----------------------------------------------------------------------
    # FASE 9 Fatia 2 — Trava dupla para execução em Bybit Demo Trading
    # ⚠️  PARALELA a assert_testnet_execution_allowed — NÃO substitui nem afrouxa.
    # ⚠️  assert_live_allowed permanece intocado.
    # -----------------------------------------------------------------------

    @property
    def is_demo_execution_allowed(self) -> bool:
        """
        Verdadeiro APENAS se trading_mode=demo E enable_demo_execution=true.

        ⚠️  Não confundir com `is_demo` (que só verifica o modo, não a flag).
        ⚠️  Não confundir com `is_live` (que é independente desta property).
        ⚠️  Não confundir com `is_testnet_execution_allowed` — são paralelos.
        """
        return (
            self._mode == TradingMode.DEMO
            and self._demo_execution_enabled is True
        )

    def assert_demo_execution_allowed(
        self,
        confirm_demo_execution: bool = False,
        context: str = "",
    ) -> None:
        """
        FASE 9 Fatia 2 — Verifica se execução em Bybit DEMO TRADING está autorizada.

        ⚠️  Esta verificação é DISTINTA de assert_live_allowed E de
            assert_testnet_execution_allowed. Demo Trading é ambiente separado
            de testnet (endpoint https://api-demo.bybit.com).
        ⚠️  NÃO afrouxa qualquer trava de live trading.
        ⚠️  Mainnet/live continua exigindo o triple-lock de assert_live_allowed.

        Triple-lock para demo:
            1. TRADING_MODE=demo no .env
            2. ENABLE_DEMO_EXECUTION=true no .env
            3. confirm_demo_execution=True passado explicitamente

        Args:
            confirm_demo_execution: DEVE ser True. Parâmetro intencional
                                    que protege contra execução acidental
                                    de ordens (mesmo que em demo).
            context:                Descrição do contexto para o log.

        Raises:
            TradingModeError: Se qualquer condição não for satisfeita.
        """
        # Verificação 1: modo deve ser demo
        if self._mode != TradingMode.DEMO:
            msg = (
                f"⛔ Demo execution bloqueada: TRADING_MODE={self._mode.value} "
                f"(necessário: demo). {context}"
            )
            _logger.error(msg)
            raise TradingModeError(msg)

        # Verificação 2: ENABLE_DEMO_EXECUTION deve ser true no .env
        if not self._demo_execution_enabled:
            msg = (
                f"⛔ Demo execution bloqueada: ENABLE_DEMO_EXECUTION=false. "
                f"Para habilitar, configure ENABLE_DEMO_EXECUTION=true no .env. "
                f"Lembre-se: Bybit Demo Trading usa credentials reais separadas "
                f"de testnet (https://api-demo.bybit.com). {context}"
            )
            _logger.error(msg)
            raise TradingModeError(msg)

        # Verificação 3: confirmação explícita na chamada
        if not confirm_demo_execution:
            msg = (
                f"⛔ Demo execution bloqueada: confirm_demo_execution=False. "
                f"Para executar, passe confirm_demo_execution=True explicitamente. "
                f"Esta proteção evita execução acidental mesmo em demo. {context}"
            )
            _logger.error(msg)
            raise TradingModeError(msg)

        # Todas as verificações passaram — registra com destaque (sem secrets!)
        _logger.warning(
            f"⚠️  DEMO EXECUTION AUTORIZADA | "
            f"mode={self._mode.value} | "
            f"demo_execution_enabled={self._demo_execution_enabled} | "
            f"explicit_confirmation=True | "
            f"context={context or 'N/A'}"
        )

    # -----------------------------------------------------------------------
    # FASE 8 — Delegação ao ProviderRegistry (NÃO afrouxa nada existente)
    # -----------------------------------------------------------------------

    def assert_provider_allowed(
        self,
        provider_id: str,
        *,
        confirm_provider: bool = False,
        context: str = "",
    ) -> None:
        """
        FASE 8 — Bloqueia uso de provider conforme status no ProviderRegistry.

        ⚠️  COMPLEMENTAR — NÃO substitui:
            - assert_safe_mode / assert_not_live (modo live continua bloqueado).
            - assert_live_allowed (triple-lock de live intocado).
            - assert_testnet_execution_allowed (triple-lock de testnet intocado).

        Regras (delegadas ao registry):
            ACTIVE       → passa.
            OPT_IN       → passa SOMENTE com confirm_provider=True.
            DRY_RUN_ONLY → bloqueia (execução real vedada).
            FROZEN / RESTRICTED / UNCONFIRMED → bloqueia.

        Args:
            provider_id:      slug do provider (ex.: "paper", "bybit_testnet_linear").
            confirm_provider: confirmação explícita exigida pelo status OPT_IN.
            context:          texto curto para logs.

        Raises:
            TradingModeError: se o registry bloquear o uso.
        """
        # Import LAZY para evitar import circular com execution/__init__.py.
        from crypto_trading_bot.execution.provider_registry import (
            ProviderBlockedError,
            get_registry,
        )

        try:
            get_registry().assert_usable(
                provider_id, confirm_provider=confirm_provider
            )
        except KeyError as e:
            msg = (
                f"⛔ Provider desconhecido pelo registry: '{provider_id}'. "
                f"context={context or 'N/A'}"
            )
            _logger.error(msg)
            raise TradingModeError(msg) from e
        except ProviderBlockedError as e:
            msg = (
                f"⛔ Provider bloqueado pelo registry: {e}. "
                f"context={context or 'N/A'}"
            )
            _logger.error(msg)
            raise TradingModeError(msg) from e

        _logger.info(
            f"ModeGuard.assert_provider_allowed | provider_id={provider_id} | "
            f"confirm_provider={confirm_provider} | context={context or 'N/A'}"
        )

    def check_operation(
        self,
        operation: OperationType,
        context: str = "",
    ) -> bool:
        """
        Verifica se uma operação é permitida no modo atual.

        Retorna True se permitida, False se bloqueada.
        Registra o resultado em log para auditoria.

        Args:
            operation: Tipo de operação a verificar.
            context: Contexto adicional para o log.

        Returns:
            True se a operação é permitida.
        """
        allowed = self.is_safe

        _logger.info(
            f"ModeGuard.check_operation | "
            f"operation={operation.value} | "
            f"mode={self._mode.value} | "
            f"allowed={allowed} | "
            f"context={context or 'N/A'}"
        )

        return allowed

    def get_status_summary(self) -> dict:
        """
        Retorna um resumo do estado atual do ModeGuard.

        Útil para diagnóstico e para o script check_config.py.

        Returns:
            Dicionário com o estado atual.
        """
        return {
            "mode": self._mode.value,
            "is_paper": self.is_paper,
            "is_testnet": self.is_testnet,
            "is_demo": self.is_demo,
            "is_live": self.is_live,
            "is_safe": self.is_safe,
            "live_env_enabled": self._live_enabled,
            # FASE 5
            "testnet_execution_env_enabled": self._testnet_execution_enabled,
            "is_testnet_execution_allowed": self.is_testnet_execution_allowed,
            # FASE 9 Fatia 2
            "demo_execution_env_enabled": self._demo_execution_enabled,
            "is_demo_execution_allowed": self.is_demo_execution_allowed,
            "warning": (
                "⚠️  LIVE TRADING ATIVO — ORDENS REAIS PODEM SER ENVIADAS"
                if self.is_live else None
            ),
        }

    def __repr__(self) -> str:
        status = "🟢 SAFE" if self.is_safe else "🔴 LIVE"
        return f"ModeGuard(mode={self._mode.value}, status={status})"
