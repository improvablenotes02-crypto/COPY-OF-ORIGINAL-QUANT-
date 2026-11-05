# Phase 298 — Timezone-Aware Source Observation Timestamps

## Contract

Every dataset provenance record must carry a valid ISO-8601 source observation timestamp with an explicit timezone offset or UTC `Z`. Naive timestamps and malformed calendar/time values are rejected at provenance construction.

Accepted examples include `2026-11-05T10:00:00Z` and `2026-11-05T15:30:00+05:30`.

## Rationale

A source observation time without a timezone is ambiguous across machines, regions, and data pipelines. Explicit offsets make the provenance field interpretable and stable for audit and comparison.

## Scope

This validates timestamp syntax and timezone awareness. It does not assert that the source clock is accurate, that the observation is fresh enough for a live trading decision, or that the exchange authenticated the timestamp. Freshness remains a separate runtime gate.

## Verification

Tests cover UTC Z, positive and negative offsets, naive timestamps, and malformed timestamps. The tests are included in the strict runtime CI workflow.
