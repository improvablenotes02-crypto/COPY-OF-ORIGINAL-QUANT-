# QuantEngine project status — 10 November 2026

**Overall verdict: HOLD — NOT PRODUCTION READY.** This repository has useful paper-mode, risk, credential-handling, and regression infrastructure, but it is not certified for live trading and no profitability or strategy-edge claim is made.

## Recent verified engineering changes

- Consolidated audit remediations cover Delta India/Global and Sandbox/Production credential-name detection, redaction, strict execution-mode configuration, direct-executor mode resolution, and Delta REST origin allowlisting.
- Secret scanning now checks reachable Git history for root/nested environment files, legacy interrupted credential-writer files, and the actual atomic-writer `.env.tmp-*` pattern. The scanner emits commit identifiers, not matched secret values.
- GitHub Actions dependencies are pinned to immutable commit SHAs.
- Remote API rate limiting uses bounded per-client state rather than one shared global window.
- The extended historical regression job is configured for weekly scheduled and manual release runs. A push/PR run does not exercise that extended step.
- Personal Delta credential setup and read-only identity verification are documented in [OPERATOR_PERSONAL_DELTA_API_KEYS.md](docs/OPERATOR_PERSONAL_DELTA_API_KEYS.md).

## Latest verification snapshot

- PR #22 (atomic `.env.tmp-*` history scanning) merged as `e293d61abbe3f16fc02d9e3d3504b558c7694451`.
- On PR #22 head, the secret-scan, option-chain integrity, Ubuntu runtime, Windows runtime, and PostgreSQL tenant-isolation jobs completed successfully.
- The extended historical regression step was skipped in that PR run because it was neither a scheduled nor a manual-dispatch run. Its weekly configuration has not yet been validated by an actual scheduled invocation.
- These CI results certify the jobs and tests that ran; they do not certify exchange production connectivity, strategy performance, or live execution.

## Operator credential warning

An earlier uploaded project archive contained credential-bearing environment entries. **If any real Delta key from that archive has not already been revoked, revoke it in the relevant Delta account immediately and replace it.** Review account activity and permissions. Removing a file or Git commit alone does not invalidate a credential. Do not paste credentials into chat, issues, pull requests, or source files. The current local setup guide uses hidden prompts and a root `.env` file; CI uses synthetic test values and does not need the operator's personal keys.

## Release blockers

1. **Credential incident closure:** confirm exposed keys were revoked/replaced and account activity reviewed. This is an operator action; repository tests cannot prove it.
2. **Authoritative market data:** the production-wired, venue-verified traded-candle feed and its reconnect, gap-recovery, and freshness evidence remain incomplete. Ticker marks are reference-only and must not be promoted to strategy candles.
3. **Execution safety:** complete end-to-end review of the actual production entrypoint, durable order/fill journaling, reconciliation, idempotency, partial fills, and emergency-stop behavior before any live execution is considered.
4. **Research validity:** establish reproducible fee/funding/slippage assumptions, out-of-sample and walk-forward results, drawdown/tail-risk analysis, and independent strategy-edge validation.
5. **Regression baseline:** run the full historical suite through the scheduled/manual path in a pinned environment and disposition every failure. Focused CI success is not a substitute.
6. **Operational certification:** verify venue-specific permissions, IP allowlisting, rate limits, recovery, monitoring, backup/restore, and incident procedures in Sandbox before any separate production review.

## Safe personal use now

- Configure only your own Delta credentials locally with `python scripts/configure_delta_credentials.py`.
- Start with **Sandbox** and the least-privilege read-only key permissions.
- Run `python scripts/check_delta_credentials.py` to verify the selected venue/environment identity endpoint. This makes no order writes.
- Use paper/research workflows only. Credential verification does not arm live trading.

**Live trading remains NO-GO.** Do not enable `ALLOW_LIVE` or `LIVE_EXECUTE` based solely on successful CI or credential verification.
