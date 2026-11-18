# Security and safe operation

- Do not commit `.env`, `.env.local`, API keys, wallet details, actual trade reports, real account IDs or private data.
- Assume credentials from older archives may be exposed and rotate them before reuse.
- Keep `TRADING_MODE=paper` and `ENABLE_LIVE_TRADING=false` for research.
- No live trading is approved or warranted by this public demonstration.
- This project is not security-audited for production; test exchange integrations only with segregated fake/demo accounts after reviewing all safeguards.
