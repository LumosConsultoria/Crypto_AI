"""
BybitDemoExecutor — FASE 9 Fatia 4B
=====================================
Executor para Bybit Demo Trading (https://api-demo.bybit.com).

⚠️  PARALELO ao BybitTestnetExecutor — NUNCA substitui nem reusa.
⚠️  Demo Trading é AMBIENTE SEPARADO de Testnet (endpoint, key, ledger).

⚠️  FATIA 4B liberou execute(dry_run=False) para envio real de ordem demo
    via place_market_order + reconciliação. Ainda 100% gated por:
        - safe_check_only(dry_run=False) → chama get_balance (read-only) OK.
        - execute(dry_run=True)          → simula sem rede OK.
        - execute(dry_run=False)         → ENVIA ordem real após gates.
        - cancel_pending(dry_run=False)  → CONTINUA NotImplementedError.
          (fechamento de posição é manual via UI Bybit Demo → Close Position;
          sem reduceOnly suportado, cancelar via API pode flipar a posição).

⚠️  Toda chamada privada exige:
    1. client com environment="demo" (rejeita testnet/mainnet no __init__);
    2. ModeGuard.assert_demo_execution_allowed (triple-lock TRADING_MODE=demo
       + ENABLE_DEMO_EXECUTION=true + confirm_demo_execution=True);
    3. Credentials carregadas no BybitClient.

⚠️  Resultados em demo NÃO garantem performance em conta real.
⚠️  Logs NUNCA contêm api_key / api_secret / assinatura / headers sensíveis.
⚠️  Sem hardcode operacional de capital/sizing/leverage — sempre vem de
    TradingSignal/RiskResult.

ARQUITETURA:
    BybitDemoExecutor
        ├─ ModeGuard.assert_demo_execution_allowed  (triple-lock demo)
        ├─ BybitClient(environment="demo")          (HMAC + api-demo.bybit.com)
        ├─ RiskEngine                               (sovereign — invariante)
        └─ DemoTrade + DemoExecutionResult          (audit local, sanitizado)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Union

from crypto_trading_bot.core.mode_guard import ModeGuard
from crypto_trading_bot.exchange.bybit_client import (
    BybitAPIError,
    BybitClient,
    BybitExecutionBlockedError,
)
from crypto_trading_bot.logging_system.logger import get_audit_logger, get_logger
from crypto_trading_bot.risk.risk_engine import RiskEngine, RiskResult, TradingSignal

_logger = get_logger(__name__)
_audit = get_audit_logger(__name__)


# ---------------------------------------------------------------------------
# Tipos auxiliares (sanitizados, frozen, sem secrets)
# ---------------------------------------------------------------------------

class DemoExecutionError(RuntimeError):
    """Erro genérico durante execução demo (sem expor secrets)."""


class DemoTradeStatus(str, Enum):
    """
    Estado de um trade demo.

    SUBMITTED            — ordem aceita pela API; reconciliação confirma estado
                           ativo (orderStatus="New"/"Triggered"/etc.).
    FILLED               — reconciliação confirma orderStatus="Filled" ou
                           "PartiallyFilled".
    CANCELED             — reconciliação confirma orderStatus="Cancelled".
    FAILED               — falha CONFIRMADA pela API (place_market_order erro).
    RECONCILIATION_FAILED — ordem enviada com sucesso (Bybit retornou order_id)
                            MAS reconciliação pós-place não confirmou orderStatus
                            via /v5/order/realtime nem via /v5/order/history.
                            Operador deve verificar UI Bybit Demo manualmente.
                            NÃO chama record_trade_opened.
    FILLED_BY_TRIANGULATION — FASE 15: /v5/order/realtime + /v5/order/history
                            falharam, MAS uma fonte secundária (execution/list
                            ou position/list) confirmou fill compatível com a
                            ordem (symbol+side+qty). NÃO chama
                            record_trade_opened. Resultado marca
                            manual_review_required=True e
                            safety_halt_recommended=True. NÃO é equivalente a
                            FILLED canônico — exige decisão humana sobre
                            continuidade.
    """
    SUBMITTED = "submitted"
    FILLED = "filled"
    CANCELED = "canceled"
    FAILED = "failed"
    RECONCILIATION_FAILED = "reconciliation_failed"
    FILLED_BY_TRIANGULATION = "filled_by_triangulation"


# ---------------------------------------------------------------------------
# FASE 15 — ReconciliationAttempt + triangulação read-only
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReconciliationAttempt:
    """
    Tentativa única de reconciliação read-only após place_market_order.

    Cada chamada ao endpoint privado de leitura (order/realtime,
    order/history, execution/list, position/list) produz uma attempt
    auditável. retCode/retMsg expostos quando BybitAPIError ocorre.

    Imutável (frozen=True). NUNCA contém api_key/api_secret/headers.
    """
    method: str                # "order_status_attempt_1" / "order_history_fallback" / "executions_triangulation" / "positions_triangulation"
    endpoint: str              # "/v5/order/realtime" etc.
    success: bool
    ret_code: Optional[int] = None
    ret_msg: Optional[str] = None
    elapsed_ms: int = 0

    def to_dict(self) -> dict:
        d: Dict[str, Any] = {
            "method": self.method,
            "endpoint": self.endpoint,
            "success": self.success,
            "elapsed_ms": self.elapsed_ms,
        }
        if self.ret_code is not None:
            d["ret_code"] = self.ret_code
        if self.ret_msg is not None:
            d["ret_msg"] = self.ret_msg
        return d


@dataclass(frozen=True)
class DemoTrade:
    """
    Registro imutável de um trade enviado à Bybit Demo Trading.

    ⚠️  NUNCA contém api_key / secret / headers. Apenas dados públicos do trade.
    """
    trade_id: str
    order_id: str
    symbol: str
    side: str
    qty: float
    position_size_usd: float
    leverage: float
    entry_price_signal: float
    stop_loss_price: float
    take_profit_price: Optional[float]
    submitted_at: datetime
    status: DemoTradeStatus
    raw_order_status: Mapping[str, Any] = field(default_factory=dict)
    position_snapshot: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DemoExecutionResult:
    """
    Resultado imutável de uma chamada a execute()/cancel_pending()/safe_check_only().

    ⚠️  SANITIZADO: NUNCA contém credenciais. Reason pode citar tipo de
        exceção mas nunca a mensagem completa (que poderia incluir headers).
    """
    success: bool
    operation: str           # "place_order" | "cancel_order" | "safe_check"
    trade: Optional[DemoTrade] = None
    reason: str = ""
    dry_run: bool = False
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    # FASE 14 — Quando a Bybit retorna retCode != 0, estes campos expõem o
    # erro estruturado SEM secrets (Bybit retCode é numérico e retMsg é
    # descritivo, ex.: "Insufficient balance"). Default None preserva
    # serialização legada e compat. com casos não-API.
    ret_code: Optional[int] = None
    ret_msg: Optional[str] = None
    # FASE 15 — Reconciliação read-only estendida. Lista de tentativas
    # estruturadas (cada uma com retCode/retMsg quando aplicável). Default
    # tupla vazia preserva serialização legada (to_dict omite quando vazio).
    reconciliation_attempts: tuple = field(default_factory=tuple)
    # FASE 15 — Sinalizadores de segurança usados quando a reconciliação
    # confirmou fill por triangulação (executions/positions) mas NÃO pelos
    # endpoints canônicos (order/realtime, order/history).
    # Default False preserva semântica anterior.
    manual_review_required: bool = False
    safety_halt_recommended: bool = False
    reconciliation_confidence: str = "canonical"   # "canonical" | "triangulated" | "none"

    def to_dict(self) -> dict:
        """Serializa para dict (sem secrets — apenas metadados do trade)."""
        d: Dict[str, Any] = {
            "success": self.success,
            "operation": self.operation,
            "reason": self.reason,
            "dry_run": self.dry_run,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.trade is not None:
            d["trade"] = {
                "trade_id": self.trade.trade_id,
                "order_id": self.trade.order_id,
                "symbol": self.trade.symbol,
                "side": self.trade.side,
                "qty": self.trade.qty,
                "position_size_usd": self.trade.position_size_usd,
                "leverage": self.trade.leverage,
                "status": self.trade.status.value,
                "submitted_at": self.trade.submitted_at.isoformat(),
            }
        # FASE 14 — só inclui ret_code/ret_msg quando houver erro Bybit estruturado
        if self.ret_code is not None:
            d["ret_code"] = self.ret_code
        if self.ret_msg is not None:
            d["ret_msg"] = self.ret_msg
        # FASE 15 — só inclui reconciliation_attempts quando não-vazio
        if self.reconciliation_attempts:
            d["reconciliation_attempts"] = [
                a.to_dict() for a in self.reconciliation_attempts
            ]
        # FASE 15 — só inclui safety flags quando não-default (evita ruído)
        if self.manual_review_required:
            d["manual_review_required"] = True
        if self.safety_halt_recommended:
            d["safety_halt_recommended"] = True
        if self.reconciliation_confidence != "canonical":
            d["reconciliation_confidence"] = self.reconciliation_confidence
        return d


# ---------------------------------------------------------------------------
# FASE 14 (qty hardening) — Helper puro de normalização de qty
# ---------------------------------------------------------------------------

_FLOAT_PRECISION_TOLERANCE: Decimal = Decimal("1e-9")


def normalize_qty_to_step(
    qty_raw: Union[float, Decimal, str],
    qty_step: Union[Decimal, float, str],
    *,
    tolerance: Decimal = _FLOAT_PRECISION_TOLERANCE,
) -> Decimal:
    """
    Normaliza qty_raw ao múltiplo do qty_step, conservador, com tolerância
    para erros de float IEEE-754.

    Comportamento:
        - Default: ROUND_DOWN ao step (nunca aumenta exposição vs. operador).
        - Exceção: se ``qty_raw`` estiver "colado" no próximo step por uma
          fração menor que ``tolerance`` (default 1e-9 do step), assume que
          a intenção era esse step exato. Isso corrige o bug clássico em
          que ``71.518350 / 71518.35 → 0.0009999999999999998`` (queria 0.001).
        - O bug real do double IEEE-754 está na ordem de ~2e-16, muito
          dentro da tolerância de 1e-9. Operadores que querem 0.0007 (ratio
          0.7 do step) NÃO sofrem arredondamento agressivo.

    Args:
        qty_raw:   qty pretendido (float, Decimal ou str).
        qty_step:  incremento mínimo do símbolo (Decimal, float ou str).
                   Ex.: Decimal("0.001") para BTCUSDT linear demo.
        tolerance: fração do step abaixo da qual erros de float são
                   "absorvidos" para o próximo step. Default 1e-9.

    Returns:
        Decimal >= 0, múltiplo exato de qty_step. Quando qty_raw < step e
        fora da tolerância, retorna ``Decimal("0")``.

    Raises:
        ValueError: se qty_step <= 0.
    """
    qty_step_dec = (
        qty_step if isinstance(qty_step, Decimal)
        else Decimal(str(qty_step))
    )
    if qty_step_dec <= 0:
        raise ValueError(f"qty_step deve ser > 0; recebido {qty_step_dec}")

    qty_raw_dec = (
        qty_raw if isinstance(qty_raw, Decimal)
        else Decimal(str(qty_raw))
    )
    if qty_raw_dec <= 0:
        return Decimal("0")

    # Quantos steps inteiros cabem (ROUND_DOWN — conservador).
    ratio = qty_raw_dec / qty_step_dec
    floor_steps = ratio.to_integral_value(rounding=ROUND_DOWN)
    fractional = ratio - floor_steps  # in [0, 1)

    # Se o ratio estiver "colado" no próximo step por menos que tolerância,
    # corrige (típico do bug 0.9999999999999998 vs 1.0 do IEEE-754).
    if (Decimal("1") - fractional) < tolerance:
        steps = floor_steps + 1
    else:
        steps = floor_steps

    quantized = steps * qty_step_dec
    # Normaliza o expoente ao step para serialização limpa
    # (ex.: "0.001" em vez de "0.0010").
    return quantized.quantize(qty_step_dec)


def stage_lower(stage: Optional[str]) -> str:
    """FASE 22 close-out helper: normaliza string de stage, default
    'after_entry' quando vazio/invalido."""
    if not isinstance(stage, str):
        return "after_entry"
    norm = stage.lower().strip()
    if norm not in ("after_entry", "flat_check"):
        return "after_entry"
    return norm


def _position_has_protection(
    position_snapshot: Mapping[str, Any], field_name: str,
) -> bool:
    """FASE 22 close-out helper: True se o campo SL/TP esta presente e
    nao-zero na posicao snapshot. Espelha a Bybit V5 convencao de
    `stopLoss`/`takeProfit` como string ('' ou '0' = ausente)."""
    raw = position_snapshot.get(field_name)
    if raw is None or raw == "":
        return False
    try:
        return float(raw) != 0.0
    except (TypeError, ValueError):
        # nao-numerico -> assume presente.
        return True


def _sl_or_tp_missing_in_position(
    position_snapshot: Mapping[str, Any],
    field_name: str,
    expected_value: Optional[float],
) -> bool:
    """FASE 22.4 helper: True se o campo SL/TP foi REQUISITADO no signal
    (expected_value > 0) mas a posicao snapshot reporta ausente/zerado.

    Bybit V5 retorna `stopLoss` e `takeProfit` como strings; ausencia
    eh tipicamente "" ou "0" / "0.0" / "0.00".

    Se expected_value is None ou <= 0 -> nao havia SL/TP a anexar;
    retorna False (nao eh ausencia).
    """
    if expected_value is None:
        return False
    try:
        if float(expected_value) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    raw = position_snapshot.get(field_name)
    if raw is None or raw == "":
        return True
    try:
        return float(raw) == 0.0
    except (TypeError, ValueError):
        # valor nao-numerico, mas presente -> considera presente.
        return False


# ---------------------------------------------------------------------------
# BybitDemoExecutor
# ---------------------------------------------------------------------------

class BybitDemoExecutor:
    """
    Executor para Bybit Demo Trading (manual, via scripts).

    INVARIANTES:
        1. Constructor REJEITA client com environment != "demo" (testnet/mainnet).
        2. execute(risk_result) REJEITA risk_result.approved=False (igual ao testnet).
        3. ModeGuard verificado ANTES de qualquer chamada privada de escrita.
        4. dry_run=True em execute()/cancel_pending() NUNCA chama API privada.
        5. dry_run=False em execute()/cancel_pending() levanta NotImplementedError
           na Fatia 4A — execução real fica para fatia futura com aprovação.
        6. safe_check_only chama APENAS get_balance (read-only) quando dry_run=False.
        7. Logs NUNCA contêm api_key/api_secret/sign — log_redaction + SecretStr.
        8. position_size e leverage vêm de TradingSignal; nada hardcoded aqui.
    """

    def __init__(
        self,
        client: BybitClient,
        mode_guard: ModeGuard,
        risk_engine: RiskEngine,
        confirm_demo_execution: bool = False,
        *,
        reconciliation_attempts: int = 3,
        reconciliation_delay_seconds: float = 0.2,
        # FASE 14 (qty hardening) — qty_step usado para normalizar o qty
        # calculado via float (position_size_usd / entry_price). Default
        # Decimal("0.001") é o qty_step de BTCUSDT linear demo (auditado
        # via instruments-info). Para outros símbolos, o caller deve
        # passar o qty_step coletado pelo preflight.
        qty_step: Union[Decimal, str, float] = Decimal("0.001"),
    ) -> None:
        """
        Args:
            client:                   BybitClient JÁ configurado com environment="demo".
                                      Rejeitado se environment for testnet/mainnet.
            mode_guard:               ModeGuard configurado pelas Settings.
            risk_engine:              RiskEngine soberano.
            confirm_demo_execution:   DEVE ser True para qualquer chamada que
                                      faça I/O privado (read ou write). Default
                                      False — força o caller a tomar decisão
                                      explícita.
            reconciliation_attempts:  Número de tentativas de get_order_status
                                      após place_market_order. Default 3.
                                      Hardening pós-primeira-ordem-real: cobre
                                      race window entre ack e propagação.
                                      Aceita >= 1. Em testes use 1 ou 2.
            reconciliation_delay_seconds: Pausa entre tentativas (s). Default 0.2.
                                      Aceita >= 0. Em testes use 0 para velocidade.
        """
        if reconciliation_attempts < 1:
            raise ValueError(
                f"reconciliation_attempts deve ser >= 1; recebido {reconciliation_attempts}"
            )
        if reconciliation_delay_seconds < 0:
            raise ValueError(
                f"reconciliation_delay_seconds deve ser >= 0; recebido {reconciliation_delay_seconds}"
            )
        # Defesa em profundidade: client DEVE ser demo
        env = getattr(client, "environment", None)
        if env != "demo":
            raise BybitExecutionBlockedError(
                f"⛔ BybitDemoExecutor recusa BybitClient com environment={env!r}. "
                "Use BybitClient(environment='demo'). Testnet e mainnet são "
                "BLOQUEADOS aqui por design — use BybitTestnetExecutor para testnet "
                "e nunca toque mainnet."
            )

        self._client = client
        self._mode_guard = mode_guard
        self._risk_engine = risk_engine
        self._confirm_demo_execution = bool(confirm_demo_execution)
        self._reconciliation_attempts = int(reconciliation_attempts)
        self._reconciliation_delay_seconds = float(reconciliation_delay_seconds)
        # FASE 14 (qty hardening) — normaliza/valida qty_step recebido.
        # Decimal(str(...)) evita o bug clássico de float (Decimal(0.001)
        # produziria 0.001000000000000000020816681711721685...).
        qty_step_decimal = (
            qty_step if isinstance(qty_step, Decimal)
            else Decimal(str(qty_step))
        )
        if qty_step_decimal <= 0:
            raise ValueError(
                f"qty_step deve ser > 0, recebido {qty_step_decimal}"
            )
        self._qty_step: Decimal = qty_step_decimal
        self._submitted_trades: Dict[str, DemoTrade] = {}

        _audit.info(
            f"BybitDemoExecutor inicializado | "
            f"client_environment={env} | "
            f"client_has_credentials={client.has_credentials} | "
            f"confirm_demo_execution={self._confirm_demo_execution}"
        )

    # -----------------------------------------------------------------------
    # safe_check_only — read-only get_balance (LIBERADO via Fatia 3)
    # -----------------------------------------------------------------------

    def safe_check_only(self, dry_run: bool = True) -> DemoExecutionResult:
        """
        Sanity check: chama get_balance() em demo APENAS — não envia ordem.

        Args:
            dry_run: Se True (default), NÃO chama BybitClient. Apenas valida
                     configuração e retorna sucesso simulado.

        Returns:
            DemoExecutionResult com operation="safe_check".
        """
        if dry_run:
            _logger.info("safe_check_only: DRY-RUN — nenhuma chamada feita.")
            return DemoExecutionResult(
                success=True,
                operation="safe_check",
                reason="dry_run: configuração validada sem chamar API",
                dry_run=True,
            )

        # Verifica ModeGuard ANTES de qualquer chamada privada
        try:
            self._mode_guard.assert_demo_execution_allowed(
                confirm_demo_execution=self._confirm_demo_execution,
                context="BybitDemoExecutor.safe_check_only",
            )
        except Exception as e:
            return DemoExecutionResult(
                success=False,
                operation="safe_check",
                reason=f"ModeGuard bloqueou: {e}",
            )

        try:
            _ = self._client.get_balance()
        except BybitExecutionBlockedError as e:
            return DemoExecutionResult(
                success=False,
                operation="safe_check",
                reason=f"BybitClient bloqueou (sem credentials?): {e}",
            )
        except BybitAPIError as e:
            # FASE 14 — expõe retCode/retMsg estruturados (sem secrets).
            return DemoExecutionResult(
                success=False,
                operation="safe_check",
                reason=(
                    f"Bybit API erro: BybitAPIError "
                    f"retCode={e.ret_code} retMsg='{e.ret_msg}'"
                ),
                ret_code=e.ret_code,
                ret_msg=e.ret_msg,
            )
        except Exception as e:
            # NÃO inclui str(e) — pode conter headers/assinatura.
            # Apenas o type name é seguro.
            return DemoExecutionResult(
                success=False,
                operation="safe_check",
                reason=f"Bybit API erro: {type(e).__name__}",
            )

        _audit.info("safe_check_only: get_balance() OK — demo auth validada.")
        return DemoExecutionResult(
            success=True,
            operation="safe_check",
            reason="get_balance executado com sucesso (demo)",
        )

    # -----------------------------------------------------------------------
    # post_session_check — FASE 22 Final: read-only fortalecido
    # -----------------------------------------------------------------------

    def post_session_check(
        self,
        symbol: str,
        dry_run: bool = True,
        *,
        stage: str = "after_entry",
        expected_qty: Optional[float] = None,
        require_sl: bool = True,
        require_tp: bool = True,
        sltp_propagation_retries: int = 2,
        sltp_propagation_delay_seconds: float = 0.3,
    ) -> DemoExecutionResult:
        """FASE 22 Final + close-out: check pos-sessao read-only com stage.

        Diferenca vs safe_check_only:
            - get_balance (legacy) + get_positions + get_open_orders.
            - 100% read-only. NUNCA fecha posicao, NUNCA cancela ordem.

        Stages (correcao da inconsistencia da FASE 22 close-out):
            stage="after_entry" (default):
                Imediatamente apos Comando B com sucesso. Espera-se
                UMA posicao aberta no `symbol` com SL/TP anexados
                quando o blueprint pediu. NESTE stage:
                  - posicao aberta == OK se size aprox. `expected_qty`
                    e SL/TP server-side presentes.
                  - posicao aberta SEM SL/TP -> manual_review.
                  - multiplas posicoes ou qty divergente -> manual_review.
                  - open orders pendentes inesperados -> manual_review
                    (SL/TP server-side em tpslMode=Full geralmente NAO
                    aparecem em open orders separados).
                  - api error -> safety_halt.
            stage="flat_check":
                Apos operador fechar/gerenciar manualmente pela UI.
                Espera-se ZERO posicoes e ZERO ordens. Qualquer
                residual -> manual_review/safety_halt.

        Args:
            symbol: simbolo a checar (ex.: "BTCUSDT").
            dry_run: True (default) NAO chama API; retorna sucesso
                     simulado. False executa os 3 reads.
            stage: "after_entry" (default) ou "flat_check".
            expected_qty: para stage="after_entry", qty esperada da
                          posicao. None = aceita qualquer qty > 0.
            require_sl: para stage="after_entry", True (default) exige
                        stopLoss server-side anexado na posicao.
            require_tp: idem para takeProfit.

        Returns:
            DemoExecutionResult com operation="post_session_check".
        """
        if dry_run:
            return DemoExecutionResult(
                success=True,
                operation="post_session_check",
                reason="dry_run: post_session_check simulado, sem rede",
                dry_run=True,
            )

        try:
            self._mode_guard.assert_demo_execution_allowed(
                confirm_demo_execution=self._confirm_demo_execution,
                context="BybitDemoExecutor.post_session_check",
            )
        except Exception as e:
            return DemoExecutionResult(
                success=False,
                operation="post_session_check",
                reason=f"ModeGuard bloqueou: {type(e).__name__}",
                manual_review_required=True,
                safety_halt_recommended=True,
            )

        api_errors: List[str] = []
        balance_check_ok = False
        positions: List[Mapping[str, Any]] = []
        open_orders: List[Mapping[str, Any]] = []

        # 1) get_balance — legacy check.
        try:
            _ = self._client.get_balance()
            balance_check_ok = True
        except BybitAPIError as e:
            # ret_msg ja vem sanitizado de BybitAPIError.__init__.
            api_errors.append(
                f"get_balance:BybitAPIError"
                f"(retCode={e.ret_code},retMsg='{e.ret_msg}')"
            )
        except Exception as e:
            api_errors.append(f"get_balance:{type(e).__name__}")

        # 2) get_positions
        # FASE 22 close-out: para stage="after_entry", se a primeira leitura
        # nao mostra SL/TP populados, faz N retries curtos para tolerar
        # latencia de propagacao do endpoint /v5/position/list (Bybit Demo
        # leva ate alguns segundos entre o ack do submit e o snapshot).
        try:
            positions = self._client.get_positions(symbol=symbol) or []
            if (
                stage_lower(stage) == "after_entry"
                and (require_sl or require_tp)
                and positions
                and sltp_propagation_retries > 0
            ):
                attempts_remaining = int(sltp_propagation_retries)
                while attempts_remaining > 0:
                    pos0 = positions[0]
                    sl_missing = (
                        require_sl
                        and not _position_has_protection(pos0, "stopLoss")
                    )
                    tp_missing = (
                        require_tp
                        and not _position_has_protection(pos0, "takeProfit")
                    )
                    if not (sl_missing or tp_missing):
                        break
                    import time as _time
                    _time.sleep(
                        max(0.0, float(sltp_propagation_delay_seconds))
                    )
                    attempts_remaining -= 1
                    try:
                        positions = (
                            self._client.get_positions(symbol=symbol) or []
                        )
                    except Exception:  # noqa: BLE001
                        break
                    if not positions:
                        break
        except BybitAPIError as e:
            api_errors.append(
                f"get_positions:BybitAPIError"
                f"(retCode={e.ret_code},retMsg='{e.ret_msg}')"
            )
        except Exception as e:
            api_errors.append(f"get_positions:{type(e).__name__}")

        # 3) get_open_orders
        try:
            open_orders = self._client.get_open_orders(
                symbol, category="linear",
            ) or []
        except BybitAPIError as e:
            api_errors.append(
                f"get_open_orders:BybitAPIError"
                f"(retCode={e.ret_code},retMsg='{e.ret_msg}')"
            )
        except Exception as e:
            api_errors.append(f"get_open_orders:{type(e).__name__}")

        # Resumo bruto das posicoes (independente do stage).
        open_positions = []
        for p in positions:
            try:
                size = float(p.get("size", 0) or 0)
            except (TypeError, ValueError):
                size = 0.0
            if size != 0:
                open_positions.append(p)

        # Stage-aware decisao.
        stage_norm = (stage or "after_entry").lower().strip()
        if stage_norm not in ("after_entry", "flat_check"):
            stage_norm = "after_entry"

        clean = False
        manual_review = False
        safety_halt = False
        stage_notes: List[str] = []

        if stage_norm == "after_entry":
            # Esperado: 1 posicao protegida com SL/TP, zero open orders
            # adicionais inesperados, balance check ok.
            if api_errors:
                # API quebrada -> halt sempre.
                manual_review = True
                safety_halt = True
                stage_notes.append("after_entry:api_errors")
            elif not balance_check_ok:
                manual_review = True
                stage_notes.append("after_entry:balance_failed")
            elif len(open_positions) == 0:
                # Sem posicao apos entry -> manual review (fill nao
                # propagou ainda OU foi fechado por SL/TP instantaneo).
                manual_review = True
                stage_notes.append("after_entry:no_position")
            elif len(open_positions) > 1:
                manual_review = True
                stage_notes.append("after_entry:multiple_positions")
            else:
                pos = open_positions[0]
                # qty check (tolerancia 1e-9)
                try:
                    size_val = float(pos.get("size", 0) or 0)
                except (TypeError, ValueError):
                    size_val = 0.0
                qty_ok = True
                if expected_qty is not None and expected_qty > 0:
                    if abs(size_val - float(expected_qty)) > 1e-9:
                        qty_ok = False
                        manual_review = True
                        stage_notes.append(
                            f"after_entry:qty_mismatch"
                            f"(got={size_val},expected={expected_qty})"
                        )
                # SL check
                sl_present = _position_has_protection(pos, "stopLoss")
                tp_present = _position_has_protection(pos, "takeProfit")
                if require_sl and not sl_present:
                    manual_review = True
                    stage_notes.append("after_entry:missing_sl")
                if require_tp and not tp_present:
                    manual_review = True
                    stage_notes.append("after_entry:missing_tp")
                if (
                    qty_ok and sl_present and tp_present
                ):
                    stage_notes.append("after_entry:position_protected")
                # Open orders pendentes inesperados nesta posicao -> review.
                # Quando tpslMode=Full, SL/TP NAO viram entries em open_orders
                # (ficam no nivel da posicao). Qualquer entry em open_orders
                # aqui eh inesperado neste stage.
                if len(open_orders) > 0:
                    manual_review = True
                    stage_notes.append(
                        f"after_entry:unexpected_open_orders="
                        f"{len(open_orders)}"
                    )
            clean = (
                balance_check_ok
                and not manual_review
                and not safety_halt
                and not api_errors
            )
        else:  # flat_check
            # Espera-se zero positions e zero open_orders.
            if api_errors:
                manual_review = True
                safety_halt = True
                stage_notes.append("flat_check:api_errors")
            if not balance_check_ok:
                manual_review = True
                stage_notes.append("flat_check:balance_failed")
            if len(open_positions) > 0:
                manual_review = True
                safety_halt = True
                stage_notes.append(
                    f"flat_check:residual_positions={len(open_positions)}"
                )
            if len(open_orders) > 0:
                manual_review = True
                stage_notes.append(
                    f"flat_check:residual_orders={len(open_orders)}"
                )
            clean = (
                balance_check_ok
                and len(open_positions) == 0
                and len(open_orders) == 0
                and not api_errors
            )

        reason_parts = [
            f"stage={stage_norm}",
            f"balance_check_ok={balance_check_ok}",
            f"positions_count={len(positions)}",
            f"open_positions_count={len(open_positions)}",
            f"open_orders_count={len(open_orders)}",
            f"api_errors_count={len(api_errors)}",
            f"clean={clean}",
            f"notes={stage_notes}",
        ]
        if api_errors:
            reason_parts.append(f"api_errors={api_errors}")

        return DemoExecutionResult(
            success=clean,
            operation="post_session_check",
            reason=" | ".join(reason_parts)[:500],
            dry_run=False,
            manual_review_required=manual_review,
            safety_halt_recommended=safety_halt,
        )

    # -----------------------------------------------------------------------
    # execute — envio de ordem (BLOQUEADO em dry_run=False nesta fatia)
    # -----------------------------------------------------------------------

    def execute(
        self,
        risk_result: RiskResult,
        dry_run: bool = True,
    ) -> DemoExecutionResult:
        """
        Envia uma ordem demo, condicionado a:
            1. risk_result.approved=True (INVARIANTE).
            2. ModeGuard.assert_demo_execution_allowed passa.
            3. signal.entry_price > 0.
            4. dry_run=False quer envio real; dry_run=True só simula.

        ⚠️  FATIA 4B: envio real LIBERADO via place_market_order + reconciliação.
            Continua exigindo triple-lock demo. Logs nunca contêm secrets.
            reduceOnly NÃO é enviado — fechamento via UI Bybit Demo.

        Args:
            risk_result: Resultado do RiskEngine. DEVE ter approved=True.
            dry_run:     Se True (default), simula sem chamar a API.
                         Se False, envia ordem real à Bybit Demo após gates.

        Returns:
            DemoExecutionResult com trade preenchido em caso de sucesso.

        Raises:
            ValueError: se risk_result.approved=False (INVARIANTE).
        """
        # Invariante: NUNCA executa sem aprovação
        if not risk_result.approved:
            raise ValueError(
                "BybitDemoExecutor.execute REJEITA risk_result não aprovado. "
                "Esta é uma INVARIANTE de segurança — fluxo deve passar pelo RiskEngine."
            )

        signal: TradingSignal = risk_result.signal

        if dry_run:
            _logger.info(
                f"execute: DRY-RUN | symbol={signal.symbol} | "
                f"side={signal.side.value} | size_usd={signal.position_size_usd}"
            )
            return DemoExecutionResult(
                success=True,
                operation="place_order",
                reason=(
                    "dry_run: ordem demo NÃO enviada à Bybit. "
                    f"Payload simulado: symbol={signal.symbol}, "
                    f"side={signal.side.value}, size_usd={signal.position_size_usd}."
                ),
                dry_run=True,
            )

        # ============== FATIA 4B: ENVIO REAL ==============
        # Verifica ModeGuard ANTES de qualquer chamada privada de escrita
        try:
            self._mode_guard.assert_demo_execution_allowed(
                confirm_demo_execution=self._confirm_demo_execution,
                context="BybitDemoExecutor.execute",
            )
        except Exception as e:
            return DemoExecutionResult(
                success=False,
                operation="place_order",
                reason=f"ModeGuard bloqueou: {e}",
            )

        # Valida entry_price (qty = position_size_usd / entry_price; entry > 0)
        if signal.entry_price <= 0:
            return DemoExecutionResult(
                success=False,
                operation="place_order",
                reason="entry_price inválido no signal (<=0)",
            )

        # Calcula qty a partir do position_size_usd e entry_price do signal.
        # ⚠️  position_size e leverage vêm DO SIGNAL; nada hardcoded aqui.
        # ⚠️  leverage NÃO é enviado no payload — é configurada na conta Bybit
        #     Demo via UI. O campo signal.leverage é usado apenas pelo RiskEngine.
        #
        # FASE 14 (qty hardening) — float division pode produzir
        # 0.0009999999999999998 (vs 0.001), o que a Bybit rejeita com
        # retCode=10001 "Qty invalid". normalize_qty_to_step() arredonda
        # PARA BAIXO ao step (conservador: nunca abre posição maior que o
        # operador pediu) usando Decimal para evitar o bug de float.
        qty_decimal = normalize_qty_to_step(
            qty_raw=signal.position_size_usd / signal.entry_price,
            qty_step=self._qty_step,
        )
        if qty_decimal <= 0:
            return DemoExecutionResult(
                success=False,
                operation="place_order",
                reason=(
                    f"qty normalizado é 0 — position_size_usd "
                    f"({signal.position_size_usd}) menor que entry_price "
                    f"({signal.entry_price}) × qty_step ({self._qty_step})"
                ),
            )
        # float() preserva o valor numérico exato do Decimal ao step;
        # BybitClient serializa via str() ao montar payload.
        qty = float(qty_decimal)

        # Envia ordem (BybitClient verifica credentials + environment)
        # ⚠️  BybitClient.place_market_order NÃO aceita reduceOnly nem leverage —
        #     verificado por análise estática FASE 7/9 e por testes.
        try:
            order_result = self._client.place_market_order(
                symbol=signal.symbol,
                side=signal.side.value,           # "buy" ou "sell"
                qty=qty,
                stop_loss=signal.stop_loss_price,
                take_profit=signal.take_profit_price,
            )
        except BybitExecutionBlockedError as e:
            return DemoExecutionResult(
                success=False,
                operation="place_order",
                reason=f"BybitClient bloqueou: {e}",
            )
        except BybitAPIError as e:
            # FASE 14 — expõe retCode/retMsg estruturados (sem secrets).
            # retCode é numérico; retMsg é texto descritivo da Bybit
            # (ex.: "Insufficient balance", "leverage not set").
            return DemoExecutionResult(
                success=False,
                operation="place_order",
                reason=(
                    f"Bybit API erro ao enviar ordem demo: BybitAPIError "
                    f"retCode={e.ret_code} retMsg='{e.ret_msg}'"
                ),
                ret_code=e.ret_code,
                ret_msg=e.ret_msg,
            )
        except Exception as e:
            # NÃO inclui str(e) — pode conter X-BAPI-SIGN/Authorization.
            return DemoExecutionResult(
                success=False,
                operation="place_order",
                reason=f"Bybit API erro ao enviar ordem demo: {type(e).__name__}",
            )

        order_id = order_result.order_id
        _audit.info(
            f"execute: ordem demo submetida | order_id={order_id} | "
            f"symbol={signal.symbol} | side={signal.side.value} | qty={qty}"
        )

        # ============== HARDENING DE RECONCILIAÇÃO (FASE 9.5 + FASE 15) ==============
        # 1) /v5/order/realtime com retries (race window do ack vs propagação).
        # 2) Fallback /v5/order/history (orders preenchidas migram p/ histórico).
        # 3) FASE 15: triangulação por /v5/execution/list (executions match).
        # 4) FASE 15: triangulação por /v5/position/list (symbol+side+qty).
        # 5) Se todos falharem → RECONCILIATION_FAILED (NÃO força FILLED).
        # 6) record_trade_opened SOMENTE com FILLED canônico (não dispara
        #    para FILLED_BY_TRIANGULATION).
        raw_order_status, reconciliation_method, attempts = self._reconcile_order_status(
            signal.symbol, order_id,
            expected_side=signal.side.value,
            expected_qty=qty,
        )

        # Snapshot de posição (best-effort; independente do status determinado)
        position_snapshot: Dict[str, Any] = {}
        try:
            positions = self._client.get_positions(symbol=signal.symbol)
            if positions:
                position_snapshot = dict(positions[0])
        except Exception as e:
            _logger.warning(
                f"Não foi possível obter position snapshot demo: {type(e).__name__}"
            )

        # Decisão de status
        status = self._classify_status(raw_order_status, reconciliation_method)

        trade_id = f"BT_DEMO_{signal.symbol}_{order_id}"
        trade = DemoTrade(
            trade_id=trade_id,
            order_id=order_id,
            symbol=signal.symbol,
            side=signal.side.value,
            qty=qty,
            position_size_usd=signal.position_size_usd,
            leverage=signal.leverage,
            entry_price_signal=signal.entry_price,
            stop_loss_price=signal.stop_loss_price,
            take_profit_price=signal.take_profit_price,
            submitted_at=datetime.now(timezone.utc),
            status=status,
            raw_order_status=raw_order_status,
            position_snapshot=position_snapshot,
        )
        self._submitted_trades[trade_id] = trade

        # Notifica RiskEngine APENAS se FILLED canônico confirmado.
        # ⚠️  FILLED_BY_TRIANGULATION explicitamente NÃO chama record_trade_opened —
        #     a invariante "só registra trade aberto com confirmação canônica"
        #     é preservada. Triangulação é evidência forte mas não-canônica;
        #     decisão sobre continuidade exige intervenção humana.
        if status is DemoTradeStatus.FILLED:
            try:
                self._risk_engine.record_trade_opened(signal)
            except Exception as e:
                _logger.warning(
                    f"RiskEngine.record_trade_opened (demo) falhou: {type(e).__name__}"
                )

        # FASE 15 — Safety flags quando o fill veio por triangulação
        manual_review_required = (status is DemoTradeStatus.FILLED_BY_TRIANGULATION)
        safety_halt_recommended = (status is DemoTradeStatus.FILLED_BY_TRIANGULATION)
        if status is DemoTradeStatus.FILLED_BY_TRIANGULATION:
            confidence = "triangulated"
        elif status is DemoTradeStatus.RECONCILIATION_FAILED:
            confidence = "none"
        else:
            confidence = "canonical"

        # FASE 22.4 — defesa em profundidade: se o signal tinha SL/TP
        # mas a posicao snapshot retornada pela API NAO tem SL/TP
        # anexados (Bybit V5 silenciosamente descarta quando faltam
        # tpslMode/triggers), marca manual_review_required.
        # Isso eh independente da reconciliacao canonica vs triangulada.
        #
        # FASE 22 close-out: aceita raw_order_status como fonte CANONICA
        # alternativa. Bybit Demo tem latencia entre o ack do submit em
        # /v5/order/realtime e a propagacao de stopLoss/takeProfit em
        # /v5/position/list (pode levar varios segundos). Quando o ack
        # da ordem ja confirma os valores SL/TP populados, eh evidencia
        # canonica suficiente — UI tambem confirma.
        if status is DemoTradeStatus.FILLED:
            sl_missing_pos = _sl_or_tp_missing_in_position(
                position_snapshot or {}, "stopLoss", signal.stop_loss_price,
            )
            tp_missing_pos = _sl_or_tp_missing_in_position(
                position_snapshot or {}, "takeProfit", signal.take_profit_price,
            )
            sl_missing_order = _sl_or_tp_missing_in_position(
                raw_order_status or {}, "stopLoss", signal.stop_loss_price,
            )
            tp_missing_order = _sl_or_tp_missing_in_position(
                raw_order_status or {}, "takeProfit", signal.take_profit_price,
            )
            # SL/TP considerado MISSING somente se ausente em AMBAS as
            # fontes (position_snapshot E raw_order_status).
            sl_missing = sl_missing_pos and sl_missing_order
            tp_missing = tp_missing_pos and tp_missing_order
            if sl_missing or tp_missing:
                manual_review_required = True
                _logger.warning(
                    "execute: SL/TP request OK mas snapshot+order_status "
                    f"reportaram sl_missing={sl_missing} tp_missing={tp_missing}"
                    " — marcando manual_review_required=True"
                )
            elif (sl_missing_pos or tp_missing_pos):
                # Latencia da API: posicao snapshot ainda nao propagou SL/TP
                # mas raw_order_status confirma. Apenas log de diagnostico,
                # sem manual_review (UI tambem confirma).
                _logger.info(
                    "execute: SL/TP confirmados via raw_order_status; "
                    f"position_snapshot ainda nao propagou "
                    f"(sl_pos_missing={sl_missing_pos}, "
                    f"tp_pos_missing={tp_missing_pos}) — latencia esperada"
                )

        # Reason informativo do método usado na reconciliação
        if status is DemoTradeStatus.RECONCILIATION_FAILED:
            reason_text = (
                "ordem demo submetida; RECONCILIAÇÃO FALHOU "
                "(realtime, history, executions e positions não confirmaram). "
                "Verifique a UI Bybit Demo manualmente."
            )
        elif status is DemoTradeStatus.FILLED_BY_TRIANGULATION:
            reason_text = (
                f"ordem demo submetida; fill confirmado por TRIANGULAÇÃO via "
                f"{reconciliation_method}. ⚠️  NÃO equivalente a FILLED canônico. "
                f"manual_review_required=True; safety_halt_recommended=True. "
                f"Operador deve validar UI antes de qualquer continuidade autônoma."
            )
        else:
            reason_text = (
                f"ordem demo submetida; status={status.value} via "
                f"reconciliação={reconciliation_method or 'best-effort'}."
            )

        return DemoExecutionResult(
            success=True,
            operation="place_order",
            trade=trade,
            reason=reason_text,
            reconciliation_attempts=attempts,
            manual_review_required=manual_review_required,
            safety_halt_recommended=safety_halt_recommended,
            reconciliation_confidence=confidence,
        )

    # -----------------------------------------------------------------------
    # submit_reduce_only_close - FASE 29 (gestao de saida reduceOnly)
    # -----------------------------------------------------------------------

    def submit_reduce_only_close(
        self,
        symbol: str,
        side: str,
        qty: float,
        *,
        dry_run: bool = True,
        confirm_demo_execution: bool = False,
    ) -> DemoExecutionResult:
        """FASE 29: envio reduceOnly close para Bybit Demo.

        SEPARADO de `execute()` (entry). Compartilha defesas:
            - ModeGuard.assert_demo_execution_allowed
            - client.environment == "demo"
            - confirm_demo_execution=True OBRIGATORIO
            - dry_run=False exige confirm_demo_execution=True
            - qty > 0
            - side in {buy, sell}

        ⚠️  Envia reduceOnly=True via BybitClient.place_market_order
            (parametro aditivo FASE 29). NUNCA cria nova posicao;
            Bybit rejeita se nao houver posicao a fechar.

        Args:
            symbol:                 ex "BTCUSDT".
            side:                   "buy" ou "sell" (oposto do lado da
                                    posicao aberta).
            qty:                    qty integral da posicao (close integral).
            dry_run:                True (default) -> nao envia.
            confirm_demo_execution: obrigatorio True para dry_run=False.

        Returns:
            DemoExecutionResult com operation="reduce_only_close".

        Raises:
            ValueError: side/qty invalido OU dry_run=False sem confirm.
        """
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("symbol deve ser string nao-vazia")
        side_norm = str(side).strip().lower()
        if side_norm not in ("buy", "sell"):
            raise ValueError(f"side invalido: {side!r}; aceitos: buy|sell")
        if not isinstance(qty, (int, float)) or qty <= 0:
            raise ValueError(f"qty deve ser > 0: {qty!r}")
        if not dry_run and not confirm_demo_execution:
            raise ValueError(
                "dry_run=False exige confirm_demo_execution=True"
            )

        # ModeGuard demo (mesmo gate de execute()).
        self._mode_guard.assert_demo_execution_allowed(
            confirm_demo_execution=confirm_demo_execution,
        )

        # Sanity client demo.
        env = getattr(self._client, "environment", None)
        if env != "demo":
            raise BybitExecutionBlockedError(
                f"⛔ submit_reduce_only_close exige client.environment="
                f"'demo'; recebido {env!r}"
            )

        _audit.info(
            f"BybitDemoExecutor.submit_reduce_only_close | "
            f"symbol={symbol} | side={side_norm} | qty={qty} | "
            f"dry_run={dry_run} | confirm={confirm_demo_execution}"
        )

        if dry_run:
            return DemoExecutionResult(
                success=True,
                operation="reduce_only_close",
                trade=None,
                reason=(
                    f"reduce_only_close DRY-RUN | symbol={symbol} | "
                    f"side={side_norm} | qty={qty}"
                ),
                manual_review_required=False,
                safety_halt_recommended=False,
            )

        # Envio real (gated).
        try:
            order_result = self._client.place_market_order(
                symbol=symbol,
                side=side_norm,
                qty=float(qty),
                reduce_only=True,
            )
        except Exception as e:  # noqa: BLE001
            from crypto_trading_bot.exchange.bybit_client import (
                redact_ret_msg,
            )
            return DemoExecutionResult(
                success=False,
                operation="reduce_only_close",
                trade=None,
                reason=(
                    f"reduce_only_close FAILED | "
                    f"err={type(e).__name__}: "
                    f"{redact_ret_msg(str(e))[:160]}"
                ),
                manual_review_required=True,
                safety_halt_recommended=True,
            )

        # Sucesso operacional. Reconciliacao detalhada eh feita por
        # post_session_check(flat_check) externamente.
        _audit.info(
            f"BybitDemoExecutor.reduce_only_close_submitted | "
            f"order_id={order_result.order_id} | qty={qty}"
        )

        return DemoExecutionResult(
            success=True,
            operation="reduce_only_close",
            trade=None,
            reason=(
                f"reduce_only_close submitted | order_id="
                f"{order_result.order_id} | qty={qty}"
            ),
            manual_review_required=False,
            safety_halt_recommended=False,
        )

    # ------------------------------------------------------------- helpers privados

    def _reconcile_order_status(
        self, symbol: str, order_id: str,
        *,
        expected_side: Optional[str] = None,
        expected_qty: Optional[float] = None,
    ) -> "tuple[Dict[str, Any], str, tuple]":
        """
        Reconciliação read-only multi-camadas (FASE 15).

        Ordem de fallback determinística:
          1. /v5/order/realtime (com retries do construtor).
          2. /v5/order/history (fallback canônico).
          3. /v5/execution/list (triangulação por execuções — FASE 15).
          4. /v5/position/list (triangulação por posição — FASE 15).

        Cada tentativa produz uma `ReconciliationAttempt` com retCode/retMsg
        sanitizados quando há `BybitAPIError`.

        Returns:
            (raw_order_status_dict, reconciliation_method, attempts_tuple)
            - raw_order_status_dict: dict (vazio se nada confirmado).
            - reconciliation_method:
                "order_status_attempt_N" / "order_history_fallback" /
                "executions_triangulation" / "positions_triangulation" / "".
            - attempts_tuple: tuple imutável de ReconciliationAttempt.

        Args:
            symbol:        Símbolo da ordem.
            order_id:      ID da ordem retornado pelo place_market_order.
            expected_side: Lado esperado ("buy"/"sell") para triangulação
                           por positions (FASE 15). None desativa o check.
            expected_qty:  Quantidade esperada para triangulação por
                           positions/executions. None desativa o check.
        """
        import time as _time

        attempts: List[ReconciliationAttempt] = []

        # ----- 1. /v5/order/realtime com retries -----
        for attempt in range(1, self._reconciliation_attempts + 1):
            t0 = _time.monotonic()
            try:
                data = self._client.get_order_status(
                    symbol=symbol, order_id=order_id,
                )
                elapsed = int((_time.monotonic() - t0) * 1000)
                if isinstance(data, dict) and data.get("orderStatus"):
                    attempts.append(ReconciliationAttempt(
                        method=f"order_status_attempt_{attempt}",
                        endpoint="/v5/order/realtime",
                        success=True,
                        elapsed_ms=elapsed,
                    ))
                    _logger.info(
                        f"reconciliação OK via order_status (attempt {attempt})"
                    )
                    self._audit_attempt(attempts[-1], order_id=order_id)
                    return dict(data), f"order_status_attempt_{attempt}", tuple(attempts)
                # Resposta sem orderStatus — registra como sucesso parcial mas continua
                attempts.append(ReconciliationAttempt(
                    method=f"order_status_attempt_{attempt}",
                    endpoint="/v5/order/realtime",
                    success=False,
                    ret_msg="response sem orderStatus",
                    elapsed_ms=elapsed,
                ))
                self._audit_attempt(attempts[-1], order_id=order_id)
            except BybitExecutionBlockedError:
                raise
            except BybitAPIError as e:
                elapsed = int((_time.monotonic() - t0) * 1000)
                attempts.append(ReconciliationAttempt(
                    method=f"order_status_attempt_{attempt}",
                    endpoint="/v5/order/realtime",
                    success=False,
                    ret_code=e.ret_code,
                    ret_msg=e.ret_msg,
                    elapsed_ms=elapsed,
                ))
                _logger.warning(
                    f"get_order_status attempt {attempt} BybitAPIError "
                    f"retCode={e.ret_code} retMsg='{e.ret_msg}'"
                )
                self._audit_attempt(attempts[-1], order_id=order_id)
            except Exception as e:
                elapsed = int((_time.monotonic() - t0) * 1000)
                attempts.append(ReconciliationAttempt(
                    method=f"order_status_attempt_{attempt}",
                    endpoint="/v5/order/realtime",
                    success=False,
                    ret_msg=type(e).__name__,
                    elapsed_ms=elapsed,
                ))
                _logger.warning(
                    f"get_order_status attempt {attempt} falhou: {type(e).__name__}"
                )
                self._audit_attempt(attempts[-1], order_id=order_id)
            if attempt < self._reconciliation_attempts and self._reconciliation_delay_seconds > 0:
                _time.sleep(self._reconciliation_delay_seconds)

        # ----- 2. /v5/order/history (fallback canônico) -----
        t0 = _time.monotonic()
        try:
            history = self._client.get_order_history(
                symbol=symbol, order_id=order_id,
            )
            elapsed = int((_time.monotonic() - t0) * 1000)
            if history:
                first = history[0]
                if isinstance(first, dict) and first.get("orderStatus"):
                    attempts.append(ReconciliationAttempt(
                        method="order_history_fallback",
                        endpoint="/v5/order/history",
                        success=True,
                        elapsed_ms=elapsed,
                    ))
                    _logger.info("reconciliação OK via order_history (fallback)")
                    self._audit_attempt(attempts[-1], order_id=order_id)
                    return dict(first), "order_history_fallback", tuple(attempts)
            attempts.append(ReconciliationAttempt(
                method="order_history_fallback",
                endpoint="/v5/order/history",
                success=False,
                ret_msg="history vazio ou sem orderStatus",
                elapsed_ms=elapsed,
            ))
            self._audit_attempt(attempts[-1], order_id=order_id)
        except BybitExecutionBlockedError:
            raise
        except BybitAPIError as e:
            elapsed = int((_time.monotonic() - t0) * 1000)
            attempts.append(ReconciliationAttempt(
                method="order_history_fallback",
                endpoint="/v5/order/history",
                success=False,
                ret_code=e.ret_code,
                ret_msg=e.ret_msg,
                elapsed_ms=elapsed,
            ))
            _logger.warning(
                f"get_order_history fallback BybitAPIError "
                f"retCode={e.ret_code} retMsg='{e.ret_msg}'"
            )
            self._audit_attempt(attempts[-1], order_id=order_id)
        except Exception as e:
            elapsed = int((_time.monotonic() - t0) * 1000)
            attempts.append(ReconciliationAttempt(
                method="order_history_fallback",
                endpoint="/v5/order/history",
                success=False,
                ret_msg=type(e).__name__,
                elapsed_ms=elapsed,
            ))
            _logger.warning(
                f"get_order_history fallback falhou: {type(e).__name__}"
            )
            self._audit_attempt(attempts[-1], order_id=order_id)

        # ----- 3. /v5/execution/list (triangulação por execuções) -----
        t0 = _time.monotonic()
        try:
            execs = self._client.get_executions(
                symbol=symbol, order_id=order_id,
            )
            elapsed = int((_time.monotonic() - t0) * 1000)
            triangulated = self._triangulate_executions(
                execs, order_id=order_id, expected_qty=expected_qty,
            )
            if triangulated is not None:
                attempts.append(ReconciliationAttempt(
                    method="executions_triangulation",
                    endpoint="/v5/execution/list",
                    success=True,
                    elapsed_ms=elapsed,
                ))
                _logger.info("reconciliação OK via executions_triangulation")
                self._audit_attempt(attempts[-1], order_id=order_id)
                return triangulated, "executions_triangulation", tuple(attempts)
            attempts.append(ReconciliationAttempt(
                method="executions_triangulation",
                endpoint="/v5/execution/list",
                success=False,
                ret_msg="sem execução compatível",
                elapsed_ms=elapsed,
            ))
            self._audit_attempt(attempts[-1], order_id=order_id)
        except BybitExecutionBlockedError:
            raise
        except BybitAPIError as e:
            elapsed = int((_time.monotonic() - t0) * 1000)
            attempts.append(ReconciliationAttempt(
                method="executions_triangulation",
                endpoint="/v5/execution/list",
                success=False,
                ret_code=e.ret_code,
                ret_msg=e.ret_msg,
                elapsed_ms=elapsed,
            ))
            _logger.warning(
                f"get_executions BybitAPIError retCode={e.ret_code} "
                f"retMsg='{e.ret_msg}'"
            )
            self._audit_attempt(attempts[-1], order_id=order_id)
        except Exception as e:
            elapsed = int((_time.monotonic() - t0) * 1000)
            attempts.append(ReconciliationAttempt(
                method="executions_triangulation",
                endpoint="/v5/execution/list",
                success=False,
                ret_msg=type(e).__name__,
                elapsed_ms=elapsed,
            ))
            _logger.warning(
                f"get_executions falhou: {type(e).__name__}"
            )
            self._audit_attempt(attempts[-1], order_id=order_id)

        # ----- 4. /v5/position/list (triangulação por posição) -----
        # Só ativa se temos symbol+side+qty para validar compatibilidade.
        if expected_side is not None and expected_qty is not None:
            t0 = _time.monotonic()
            try:
                positions = self._client.get_positions(symbol=symbol)
                elapsed = int((_time.monotonic() - t0) * 1000)
                triangulated = self._triangulate_positions(
                    positions, symbol=symbol,
                    expected_side=expected_side, expected_qty=expected_qty,
                )
                if triangulated is not None:
                    attempts.append(ReconciliationAttempt(
                        method="positions_triangulation",
                        endpoint="/v5/position/list",
                        success=True,
                        elapsed_ms=elapsed,
                    ))
                    _logger.info("reconciliação OK via positions_triangulation")
                    self._audit_attempt(attempts[-1], order_id=order_id)
                    return triangulated, "positions_triangulation", tuple(attempts)
                attempts.append(ReconciliationAttempt(
                    method="positions_triangulation",
                    endpoint="/v5/position/list",
                    success=False,
                    ret_msg="sem posição compatível (symbol+side+qty)",
                    elapsed_ms=elapsed,
                ))
                self._audit_attempt(attempts[-1], order_id=order_id)
            except BybitExecutionBlockedError:
                raise
            except BybitAPIError as e:
                elapsed = int((_time.monotonic() - t0) * 1000)
                attempts.append(ReconciliationAttempt(
                    method="positions_triangulation",
                    endpoint="/v5/position/list",
                    success=False,
                    ret_code=e.ret_code,
                    ret_msg=e.ret_msg,
                    elapsed_ms=elapsed,
                ))
                _logger.warning(
                    f"get_positions (triangulation) BybitAPIError "
                    f"retCode={e.ret_code} retMsg='{e.ret_msg}'"
                )
                self._audit_attempt(attempts[-1], order_id=order_id)
            except Exception as e:
                elapsed = int((_time.monotonic() - t0) * 1000)
                attempts.append(ReconciliationAttempt(
                    method="positions_triangulation",
                    endpoint="/v5/position/list",
                    success=False,
                    ret_msg=type(e).__name__,
                    elapsed_ms=elapsed,
                ))
                _logger.warning(
                    f"get_positions (triangulation) falhou: {type(e).__name__}"
                )
                self._audit_attempt(attempts[-1], order_id=order_id)

        # 5. Nenhuma reconciliação conclusiva
        _logger.warning(
            "RECONCILIAÇÃO FALHOU — todos os fallbacks (realtime, history, "
            "executions, positions) não confirmaram orderStatus."
        )
        return {}, "", tuple(attempts)

    @staticmethod
    def _triangulate_executions(
        execs: List[Dict[str, Any]],
        *,
        order_id: str,
        expected_qty: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        FASE 15 — Triangula fill por /v5/execution/list.

        Confirma fill APENAS se:
          - Há ao menos 1 execução com orderId == order_id.
          - Se expected_qty != None, soma de execQty bate (tolerância 0.5%).

        Returns:
            dict sintetizado (com orderStatus="Filled" + execList) se
            confirmado; None caso contrário.
        """
        if not execs:
            return None
        # Preferência: filtrar por orderId (V5 já filtra; defesa adicional).
        matched = [
            e for e in execs
            if isinstance(e, dict) and str(e.get("orderId", "")) == str(order_id)
        ]
        if not matched:
            return None

        # Validação opcional de qty agregada (tolerância 0.5% para slippage)
        if expected_qty is not None:
            try:
                total_qty = sum(float(e.get("execQty", 0) or 0) for e in matched)
            except (TypeError, ValueError):
                total_qty = 0.0
            if total_qty <= 0:
                return None
            tolerance = max(abs(expected_qty) * 0.005, 1e-9)
            if abs(total_qty - expected_qty) > tolerance:
                _logger.warning(
                    f"executions triangulation: qty mismatch "
                    f"(total={total_qty} vs expected={expected_qty})"
                )
                return None

        # Síntese: marca como Filled (com execList no payload p/ auditoria)
        return {
            "orderId": order_id,
            "orderStatus": "Filled",
            "triangulated_by": "executions",
            "execList": list(matched),
        }

    @staticmethod
    def _triangulate_positions(
        positions: List[Dict[str, Any]],
        *,
        symbol: str,
        expected_side: str,
        expected_qty: float,
    ) -> Optional[Dict[str, Any]]:
        """
        FASE 15 — Triangula fill por /v5/position/list.

        Confirma fill APENAS se:
          - Há posição com symbol == expected symbol (sem ambiguidade).
          - Side da posição bate ("Buy"/"buy" para BUY; "Sell"/"sell" para SELL).
          - Size bate com expected_qty (tolerância 0.5%).
          - Apenas 1 posição compatível (sem múltiplas posições no mesmo símbolo).

        Returns:
            dict sintetizado se confirmado; None caso contrário.

        Defesa: NÃO confirma se houver posição preexistente ambígua (size > qty),
        nem se símbolo divergente. NUNCA infere fill por similaridade fraca.
        """
        if not positions:
            return None

        expected_side_norm = (expected_side or "").lower()
        if expected_side_norm not in ("buy", "sell"):
            return None

        # Filtra posições do símbolo correto com size > 0
        candidates = []
        for p in positions:
            if not isinstance(p, dict):
                continue
            sym_match = str(p.get("symbol", "")).upper() == symbol.upper()
            try:
                size = float(p.get("size", 0) or 0)
            except (TypeError, ValueError):
                size = 0.0
            if not sym_match or size <= 0:
                continue
            candidates.append((p, size))

        if len(candidates) != 1:
            # 0 → não confirma; >1 → ambíguo, defesa, não confirma.
            return None

        p, size = candidates[0]
        # Side da posição
        pos_side = str(p.get("side", "")).lower()
        if pos_side != expected_side_norm:
            return None

        # Match de quantidade (tolerância 0.5%)
        tolerance = max(abs(expected_qty) * 0.005, 1e-9)
        if abs(size - expected_qty) > tolerance:
            _logger.warning(
                f"positions triangulation: qty mismatch "
                f"(size={size} vs expected={expected_qty})"
            )
            return None

        return {
            "symbol": symbol,
            "orderStatus": "Filled",
            "triangulated_by": "positions",
            "position": dict(p),
        }

    @staticmethod
    def _audit_attempt(
        attempt: ReconciliationAttempt, *, order_id: str,
    ) -> None:
        """Emite linha de audit estruturada (sanitizada)."""
        ret_code_str = (
            f"retCode={attempt.ret_code}" if attempt.ret_code is not None
            else "retCode=n/a"
        )
        ret_msg_str = (
            f"retMsg='{attempt.ret_msg}'" if attempt.ret_msg
            else "retMsg=''"
        )
        _audit.info(
            f"RECONCILIATION_ATTEMPT | "
            f"method={attempt.method} | "
            f"endpoint={attempt.endpoint} | "
            f"success={attempt.success} | "
            f"{ret_code_str} | "
            f"{ret_msg_str} | "
            f"elapsed_ms={attempt.elapsed_ms} | "
            f"order_id={order_id}"
        )

    @staticmethod
    def _classify_status(
        raw_order_status: Dict[str, Any], reconciliation_method: str,
    ) -> DemoTradeStatus:
        """
        Classifica DemoTradeStatus a partir do orderStatus retornado pela Bybit
        ou pela triangulação (FASE 15).

        Regra conservadora:
            - reconciliação NÃO confirmou nada → RECONCILIATION_FAILED.
            - método == triangulação (executions ou positions) → FILLED_BY_TRIANGULATION.
              ⚠️  NÃO chama record_trade_opened. Resultado marca
                  manual_review_required=True e safety_halt_recommended=True.
            - orderStatus in {Filled, PartiallyFilled}     → FILLED.
            - orderStatus in {Cancelled, Canceled}          → CANCELED.
            - orderStatus presente mas outro (New, etc.)    → SUBMITTED.
        """
        if not reconciliation_method or not raw_order_status:
            return DemoTradeStatus.RECONCILIATION_FAILED
        # FASE 15 — Triangulação NUNCA é equivalente a FILLED canônico.
        if reconciliation_method in (
            "executions_triangulation", "positions_triangulation",
        ):
            return DemoTradeStatus.FILLED_BY_TRIANGULATION
        raw = str(raw_order_status.get("orderStatus", "")).lower()
        if raw in ("filled", "partiallyfilled"):
            return DemoTradeStatus.FILLED
        if raw in ("cancelled", "canceled"):
            return DemoTradeStatus.CANCELED
        # Qualquer outro estado conhecido (New, Untriggered, etc.) → SUBMITTED
        return DemoTradeStatus.SUBMITTED

    # -----------------------------------------------------------------------
    # cancel_pending — também bloqueado em escrita real
    # -----------------------------------------------------------------------

    def cancel_pending(
        self,
        symbol: str,
        order_id: str,
        dry_run: bool = True,
    ) -> DemoExecutionResult:
        """
        Cancela uma ordem demo previamente submetida.

        ⚠️  FATIA 4A: cancelamento real BLOQUEADO. dry_run=False levanta
            NotImplementedError — mesma esteira de aprovação que envio de ordem.

        Args:
            symbol:   Símbolo da ordem.
            order_id: Order ID retornado por execute().
            dry_run:  Se True (default), NÃO chama API.
        """
        if dry_run:
            return DemoExecutionResult(
                success=True,
                operation="cancel_order",
                reason=f"dry_run: cancel demo simulado para order_id={order_id}",
                dry_run=True,
            )

        raise NotImplementedError(
            "BybitDemoExecutor.cancel_pending(dry_run=False) está BLOQUEADO na "
            "Fatia 4A. Cancelamento real demo requer mesma esteira de aprovação "
            "que envio de ordem. Use a UI Bybit Demo Trading se necessário."
        )

    # -----------------------------------------------------------------------
    # Acessadores e summary sanitizado
    # -----------------------------------------------------------------------

    @property
    def submitted_trades(self) -> Mapping[str, DemoTrade]:
        """Snapshot read-only de trades submetidos nesta sessão."""
        return dict(self._submitted_trades)

    def get_summary(self) -> dict:
        """
        Resumo dos trades demo (sem secrets).

        Útil para diagnóstico em scripts. NUNCA inclui credenciais.
        """
        return {
            "n_submitted": len(self._submitted_trades),
            "n_filled": sum(
                1 for t in self._submitted_trades.values()
                if t.status is DemoTradeStatus.FILLED
            ),
            "n_canceled": sum(
                1 for t in self._submitted_trades.values()
                if t.status is DemoTradeStatus.CANCELED
            ),
            "trade_ids": list(self._submitted_trades.keys()),
        }

    def __repr__(self) -> str:
        # NUNCA inclui valores de config completos no repr (defesa contra leak)
        return (
            f"BybitDemoExecutor("
            f"environment=demo, "
            f"confirm_demo_execution={self._confirm_demo_execution}, "
            f"n_submitted={len(self._submitted_trades)})"
        )
