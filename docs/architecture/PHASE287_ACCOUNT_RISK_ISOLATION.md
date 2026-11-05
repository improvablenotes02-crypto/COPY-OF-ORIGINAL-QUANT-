# Phase 287 — Per-account risk isolation

Status: an explicit, offline-tested account risk preflight has been added.
It is not yet wired into a live order path and does not authorize execution.

## Account-bound scope

Every profile, state and proposal carries the complete account scope:
- tenant ID;
- internal account ID;
- authenticated Delta provider account ID;
- region;
- environment;
- venue.

A coordinator indexes profiles by `(tenant_id, internal_account_id)`.
The gate additionally requires exact equality of the full scope, so a
proposal cannot reuse another tenant's profile or another provider identity,
region or environment.

## Explicit risk profile

No default risk profile is supplied. Each account must be provisioned with
explicit:
- risk-per-trade fraction;
- maximum order notional;
- maximum leverage;
- daily, weekly and monthly loss fractions;
- maximum total exposure fraction;
- maximum open positions;
- maximum pending orders.

Fractions must be finite and bounded; total exposure cannot exceed the
configured leverage ceiling. This avoids silently applying one user's risk
limits to another user.

## State and proposal checks

The pure gate rejects:
- account scope mismatch or missing profile;
- kill switch or disabled trading;
- non-positive/non-finite equity or risk basis;
- invalid PnL, exposure or position counters;
- daily/weekly/monthly loss-limit breach (equality blocks);
- open-position or pending-order capacity exhaustion;
- per-trade risk, order notional, leverage or aggregate exposure breach;
- a declared leverage value that understates notional/equity.

The coordinator is thread-safe but in-memory only. A production deployment
must persist risk profiles and state in the selected shared database and
derive tenant identity from authenticated server-side context.

## Integration boundary

This phase does not modify the existing single-account `RiskEngine`, does
not create orders, and does not mint a live-write permit. A multi-account
runtime must call this account-scoped gate for each proposal and then pass
through the existing independent execution safety gates. The current
read-only session remains read-only. `ALLOW_LIVE` and `LIVE_EXECUTE`
remain disabled by default.

## Validation

Offline tests cover two tenants with different policies, same internal IDs
across tenants, provider/region/environment mismatch, missing/duplicate
profiles, kill switch, disabled trading, exact loss boundaries, exposure and
position caps, malformed numbers, order caps and invalid state updates.
