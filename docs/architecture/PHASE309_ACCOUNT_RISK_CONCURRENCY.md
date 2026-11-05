# Phase 309 — Concurrent Account Risk State Writers

## Contract

The SQLite repository's revision compare-and-swap behavior is tested with two independent repository connections and simultaneous writers targeting the same tenant/account revision.

Exactly one update may advance revision zero to revision one. The losing writer must receive a stale-revision rejection, and the winning state must remain intact.

## Deployment boundary

This verifies local SQLite transaction behavior under concurrent connections. It does not certify a distributed PostgreSQL implementation or a multi-region consistency model. Production repository adapters must provide equivalent atomic compare-and-swap semantics and their own concurrency tests.

## Verification

A barrier synchronizes two writer threads; both read revision zero before racing to update. The test asserts one winner, one stale rejection, one revision increment, and no lost update.
