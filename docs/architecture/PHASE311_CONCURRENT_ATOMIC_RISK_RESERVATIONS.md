# Phase 311 — Concurrent Atomic Order Reservations

## Contract

Two independent repository connections concurrently attempting to reserve the same remaining account exposure budget must serialize through the repository transaction. Exactly one reservation may consume the available capacity; the other must be denied after re-reading the committed risk state.

## Verification

A synchronized two-thread test gives both writers the same account state and a proposal that individually fits but whose combined notional exceeds the configured exposure cap. The test requires one approval, one `MAX_TOTAL_EXPOSURE` denial, and exactly one persisted pending reservation.
