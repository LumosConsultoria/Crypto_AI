# Crypto_AI — Engineering Portfolio Summary

## Scope
Research-oriented Python quantitative trading system with modular market-data adapters, backtesting, strategies, risk controls, execution modes, operational CLI tools, exchange integration experiments, audit logs and tests.

## Technical focus
- Clear separation between data, strategies, execution and risk decisions.
- Paper/testnet and explicit operational safeguards before any live orders.
- Structured source tree, unit/integration tests and traceable operational reports.
- AI is an **auxiliary analytical tool**, not a verified autonomous decision engine.

## Verification at publication preparation
- Python source/test/script compilation succeeded in the evaluation environment (Python 3.13).
- 69 offline tests for mode guard, risk engine and paper trader passed.
- 145 additional offline tests for Bybit authentication/client, market data and backtesting passed.
- An attempted full-suite run exceeded the evaluation timeout at approximately 17% progress, **not** evidence of a complete pass.
- No authenticated exchange trade, live order, public-cloud deployment or financial profitability is certified.

## Disclosure boundaries
The published snapshot deliberately excludes the original `.env`, `.env.local`, any exchange/API secrets, virtual environments, historical datasets, execution reports, logs, cached files and internal archived artifacts. The source is provided for engineering discussion and should never be executed against a funded account without a comprehensive independent security and risk review.

## Rights
Public source visibility does not grant an unrestricted reuse license. See [LICENSE.md](LICENSE.md).
