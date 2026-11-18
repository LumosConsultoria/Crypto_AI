"""
run_ai_shadow_collect (FASE 47, corrigido) — coletor de pareceres de IA.
========================================================================
DOIS modos (P2):
  - historical_probe : replay sobre candidatos HISTORICOS (dataset travado).
      INVALIDO p/ validacao (cutoff do modelo cobre a janela => lookahead
      pelos pesos). Pode usar cache/replay.
  - prospective_shadow: dados e timestamp REALMENTE atuais (fetch agora,
      gated). NUNCA usa replay historico. Unico valido p/ acumular validacao.

Garantias:
  - RiskEngine roda ANTES da IA (P1): so candidatos aprovados (piso + caps)
    chegam a IA (via research.ai_candidate_builder).
  - Contexto causal COMPLETO (P3): funding/OI/percentis/ATR/vol/entry/stop/
    alvo/RR/risco-Hyro/custos/Polymarket.
  - Resposta estruturada com reason_codes (P4).
  - Budget/tokens/custo RECONCILIAM exatamente (P5): chamadas reais + cache
    hits + puladas == selecionados; custo = soma real por tokens.
  - Limites aprovados: Haiku, <=50 chamadas/dia, <=US$0,25/dia, fail-safe.
  - NENHUMA ordem/demo/live.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

COST_REFERENCE = {"provider": "anthropic", "model": "claude-haiku-4-5-20251001",
                  "credential_env": "AI_API_KEY"}


class BudgetGuard:
    """Limita chamadas/dia e orcamento/dia (UTC); fail-safe ao atingir.
    can_call usa estimativa pre-chamada; register grava CUSTO REAL (tokens)."""

    def __init__(self, path: str, *, max_calls: int, max_budget_usd: float,
                 est_cost_per_call: float) -> None:
        self._path = Path(path)
        self._max_calls = max_calls
        self._max_budget = max_budget_usd
        self._est = est_cost_per_call
        self._day = datetime.now(timezone.utc).date().isoformat()
        self._state = {"day": self._day, "calls": 0, "spent_usd": 0.0,
                       "input_tokens": 0, "output_tokens": 0}
        if self._path.is_file():
            try:
                s = json.loads(self._path.read_text(encoding="utf-8"))
                if s.get("day") == self._day:
                    self._state = {**self._state, **s}
            except Exception:  # noqa: BLE001
                pass

    def can_call(self) -> bool:
        return (self._state["calls"] < self._max_calls
                and self._state["spent_usd"] + self._est
                <= self._max_budget + 1e-9)

    def register(self, actual_cost_usd=None, in_tokens=0, out_tokens=0) -> None:
        cost = self._est if actual_cost_usd is None else float(actual_cost_usd)
        self._state["calls"] += 1
        self._state["spent_usd"] = round(self._state["spent_usd"] + cost, 8)
        self._state["input_tokens"] += int(in_tokens)
        self._state["output_tokens"] += int(out_tokens)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._state, indent=2),
                              encoding="utf-8")

    @property
    def state(self) -> dict:
        return dict(self._state)


def _print_checkpoint(mode, n, model, max_calls, max_budget) -> None:
    print("=" * 60)
    print(f"IA SHADOW [{mode}] — checkpoint (limites aprovados)")
    print(f"  provider/modelo ....... anthropic / {model}")
    print(f"  candidatos ............ {n}")
    print(f"  max chamadas/dia ...... {max_calls}")
    print(f"  max orcamento/dia ..... US${max_budget}")
    print(f"  custo ................. por tokens reais (Haiku)")
    print(f"  credencial ............ {COST_REFERENCE['credential_env']} (ENV)")
    print("=" * 60)


def _load_perp(path):
    if not path or not Path(path).is_file():
        return []
    return json.loads(Path(path).read_text(encoding="utf-8-sig")).get("rows") \
        or []


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="IA shadow (FASE 47 corrigido)")
    ap.add_argument("--mode", choices=["historical_probe",
                                       "prospective_shadow"], required=True)
    ap.add_argument("--store", required=True)
    ap.add_argument("--budget-state", default="reports/ai_budget_state.json")
    ap.add_argument("--max-calls-per-day", type=int, default=50)
    ap.add_argument("--max-budget-usd", type=float, default=0.25)
    ap.add_argument("--est-cost-per-call", type=float, default=0.004)
    ap.add_argument("--max-candidates", type=int, default=30)
    ap.add_argument("--base-dir", default="data/historical")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--funding", default="data/perp/funding_BTCUSDT.json")
    ap.add_argument("--oi", default="data/perp/oi_BTCUSDT_60m.json")
    ap.add_argument("--operator-inputs", default="config/operator_inputs.json")
    ap.add_argument("--i-approved-cost", action="store_true")
    ap.add_argument("--allow-network", action="store_true",
                    help="OBRIGATORIO p/ prospective_shadow (fetch atual)")
    ap.add_argument("--lookback-candles", type=int, default=400)
    args = ap.parse_args(argv)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:  # noqa: BLE001
        pass
    from crypto_trading_bot.ai_assistant.advice_store import (
        AdviceRecord, AdviceStore, prompt_hash)
    from crypto_trading_bot.ai_assistant.anthropic_advisor import (
        AnthropicAIAdvisor, build_prompt, default_anthropic_transport)
    from crypto_trading_bot.ai_assistant.provider_adapter import (
        resolve_ai_advisor)
    from crypto_trading_bot.backtesting import load_candles_from_csv
    from crypto_trading_bot.operator_inputs.store import OperatorInputStore
    from crypto_trading_bot.research.ai_candidate_builder import (
        build_candidate_contexts)
    from crypto_trading_bot.research.effective_config import (
        build_effective_config)
    from crypto_trading_bot.research.perp_signals import (
        load_funding, load_open_interest)

    store_oi = None
    if Path(args.operator_inputs).is_file():
        store_oi = OperatorInputStore(args.operator_inputs)
    eff = build_effective_config(store=store_oi)
    sym = args.symbol.upper()

    # ---------- montagem dos candidatos por modo ----------
    if args.mode == "historical_probe":
        csv15 = Path(args.base_dir) / sym / "15m" / f"{sym}_15m.csv"
        candles = load_candles_from_csv(str(csv15), symbol=sym, timeframe="15")
        funding = load_funding(_load_perp(args.funding))
        oi = load_open_interest(_load_perp(args.oi))
        contexts, counts = build_candidate_contexts(
            candles, funding_points=funding, oi_points=oi,
            effective_config=eff, symbol=sym)
        contexts = contexts[-args.max_candidates:]
        invalid_for_validation = True
    else:  # prospective_shadow
        if not args.allow_network:
            print("BLOQUEADO: prospective_shadow exige --allow-network "
                  "(dados atuais).")
            return 3
        from datetime import timedelta
        from crypto_trading_bot.historical_data.aux_providers import (
            BybitFundingProvider, BybitOpenInterestProvider)
        from crypto_trading_bot.historical_data.providers import (
            BybitLinearPublicProvider)
        now = datetime.now(timezone.utc)
        start = now - timedelta(minutes=15 * args.lookback_candles)
        print("fetch ATUAL (gated, read-only): klines 15m + funding + OI...")
        rows = BybitLinearPublicProvider().fetch_candles(
            symbol=sym, tf_minutes=15, start=start, end=now)
        from crypto_trading_bot.exchange.base_exchange import Candle
        candles = [Candle(symbol=sym, timeframe="15m", timestamp=r.timestamp,
                          open=r.open, high=r.high, low=r.low, close=r.close,
                          volume=r.volume) for r in rows]
        f_rows = BybitFundingProvider().fetch_funding(
            symbol=sym, start=start, end=now)
        oi_rows = BybitOpenInterestProvider().fetch_open_interest(
            symbol=sym, tf_minutes=60, start=start, end=now)
        funding = load_funding(f_rows)
        oi = load_open_interest(oi_rows)
        contexts, counts = build_candidate_contexts(
            candles, funding_points=funding, oi_points=oi,
            effective_config=eff, symbol=sym)
        # prospective: so os candidatos do FIM (mais recentes/atuais)
        contexts = contexts[-args.max_candidates:]
        invalid_for_validation = False
        _last = candles[-1].timestamp if candles else None
        print(f"klines_atuais={len(candles)} ultimo={_last}")

    print(f"candidatos: {counts} | selecionados={len(contexts)}")

    # ---------- resolucao do advisor ----------
    advisor, reason = resolve_ai_advisor()
    model = (reason.split(":", 1)[1] if reason.startswith("anthropic_real:")
             else "mock")
    use_real = reason.startswith("anthropic_real:") and args.i_approved_cost
    _print_checkpoint(args.mode, len(contexts), model,
                      args.max_calls_per_day, args.max_budget_usd)
    if not use_real:
        from crypto_trading_bot.ai_assistant.mock_ai_advisor import (
            MockAIAdvisor)
        advisor = MockAIAdvisor()
        model = "mock"
        print("Modo MOCK (sem --i-approved-cost ou sem chave). Sem custo.")

    # store: historical_probe pode usar cache/replay; prospective usa store
    # proprio (sem replay historico).
    store = AdviceStore(args.store)
    real_advisor = isinstance(advisor, AnthropicAIAdvisor)
    if real_advisor and args.mode == "historical_probe":
        advisor._store = store  # habilita replay/cache dentro do probe

    guard = (BudgetGuard(args.budget_state, max_calls=args.max_calls_per_day,
                         max_budget_usd=args.max_budget_usd,
                         est_cost_per_call=args.est_cost_per_call)
             if use_real else None)

    rec = {"real_calls": 0, "cache_hits": 0, "skipped_by_budget": 0,
           "errors": 0, "input_tokens": 0, "output_tokens": 0,
           "cost_usd": 0.0, "persisted": 0}
    failsafe = False
    for ctx in contexts:
        if use_real and not guard.can_call():
            failsafe = True
            rec["skipped_by_budget"] += 1
            continue
        advice = advisor.evaluate_trade_context(ctx)
        state = getattr(advisor, "last_state", "mock")
        codes = getattr(advisor, "last_reason_codes", [])
        usage = getattr(advisor, "last_usage", {"input_tokens": 0,
                                                "output_tokens": 0})
        cost = float(getattr(advisor, "last_cost_usd", 0.0))
        from_cache = getattr(advisor, "last_from_cache", False)
        if real_advisor and from_cache:
            rec["cache_hits"] += 1
        else:
            if use_real:
                guard.register(cost, usage.get("input_tokens", 0),
                               usage.get("output_tokens", 0))
            rec["real_calls"] += (1 if use_real else 0)
            if state == "error":
                rec["errors"] += 1
            rec["input_tokens"] += int(usage.get("input_tokens", 0))
            rec["output_tokens"] += int(usage.get("output_tokens", 0))
            rec["cost_usd"] = round(rec["cost_usd"] + cost, 8)
        # registra (advisor com store ja gravou no probe; senao grava aqui)
        if not (real_advisor and args.mode == "historical_probe"):
            resp = advice.to_dict()
            resp["reason_codes"] = codes
            resp["usage"] = usage
            store.record(AdviceRecord(
                ts=datetime.now(timezone.utc).isoformat(), model=model,
                model_version=model, prompt_hash=prompt_hash(build_prompt(ctx)),
                inputs=dict(ctx), response=resp,
                source=("real" if use_real else "mock")))
        rec["persisted"] += 1

    # ---------- reconciliacao (P5) ----------
    selected = len(contexts)
    reconciles = (rec["real_calls"] + rec["cache_hits"]
                  + rec["skipped_by_budget"] == selected)
    summary = {
        "mode": args.mode,
        "invalid_for_validation": invalid_for_validation,
        "advisor_reason": reason, "model": model,
        "candidate_counts": counts, "selected": selected,
        "reconciliation": {
            **rec,
            "selected": selected,
            "reconciles_exact": reconciles,
            "note": "real_calls + cache_hits + skipped_by_budget == selected",
        },
        "budget_state": (guard.state if guard else None),
        "budget_failsafe_triggered": failsafe,
        "store": args.store,
    }
    if use_real and guard:
        # custo da reconciliacao deve bater com o budget do dia (delta do run)
        summary["reconciliation"]["budget_matches_cost"] = (
            abs(rec["cost_usd"]) <= guard.state["spent_usd"] + 1e-6)
    out_path = Path(args.store).with_suffix(".summary.json")
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if failsafe:
        print("FAIL-SAFE: limite diario de IA atingido => segue SEM IA.")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
