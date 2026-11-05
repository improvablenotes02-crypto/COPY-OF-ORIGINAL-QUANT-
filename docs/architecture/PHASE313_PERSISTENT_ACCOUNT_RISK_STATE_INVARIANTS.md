# Phase 313 — Persistent Account Risk State Invariants

## Problem

The risk gate validates state before evaluating an order, but persistence previously accepted some invalid state values. A caller could persist negative exposure or invalid position counters through registration, compare-and-swap, or settlement, leaving the durable account state inconsistent until a later gate evaluation.

## Change

The SQLite persistence boundary now validates every state read or written:

- risk basis and equity must be finite and positive;
- daily, weekly, and monthly P&L must be finite;
- current and pending exposure must be finite and non-negative;
- open-position and pending-order counts must be non-negative integers (booleans are rejected);
- kill-switch and trading-enabled controls must be booleans;
- the state must belong to the requested account scope and carry a valid non-negative revision.

Validation occurs before transaction commit. Invalid settlement data therefore cannot mark a reservation settled or release its pending risk capacity.

## Verification

The Phase 313 tests cover invalid registration, compare-and-swap, and settlement, plus a valid revisioned update. The runtime CI workflow runs this test alongside the Phase 308–312 account-risk suite.

## Limits

These checks protect local persistence invariants; they do not establish that a caller-supplied account snapshot is authentic. Production settlement still requires authenticated exchange reconciliation and a shared transactional repository. Live order writing remains disarmed.
