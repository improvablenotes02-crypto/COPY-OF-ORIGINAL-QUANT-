# Phase 317 — Fail-Closed Risk Settlement Projection

## Objective

Prevent a caller from using terminal-order evidence and a matching state hash to smuggle unrelated risk-state changes into the persistent account-risk repository.

## Repository invariant

SQLiteAccountRiskRepository.settle_reservation() now:

- accepts only REJECTED terminal evidence;
- loads the reservation notional inside the same transaction;
- verifies the current state can cover exactly one pending reservation;
- requires pending order count to decrement by one and pending exposure by that reservation's notional;
- requires all other state fields (risk basis, equity, P&L windows, open positions, current exposure, kill switch, and trading-enabled control) to remain unchanged;
- commits state, reservation status, and evidence together.

The Delta orchestration checks the same projection before snapshot processing. For filled, cancelled, or expired orders it returns without transitioning the submission journal or releasing the risk reservation.

## Why execution outcomes are deferred

The current account snapshot is complete by endpoint and pagination evidence, but it is not exchange-atomic. A trusted position/equity/P&L projection from those sequential observations has not yet been implemented. Until that exists, releasing pending notional for an executed order could understate risk. The safe behavior is to keep that reservation pending.

## Verification

Adversarial tests cover attempts to settle a filled order, alter equity/P&L/exposure/controls under a valid matching hash, and release more than one pending reservation. Regression tests were adjusted to model rejected, zero-fill outcomes only.

GitHub Actions must pass on the exact phase commit. No local test execution is claimed by the repository-editing agent. This phase does not enable live trading.
