# Phase 299 — Canonical UTC Source Timestamps

## Contract

After validating an ISO-8601 source observation timestamp with an explicit timezone, provenance construction normalizes it to UTC and stores the canonical representation with a trailing `Z`.

Equivalent instants such as `2026-11-05T10:00:00Z`, `2026-11-05T15:30:00+05:30`, and `2026-11-05T02:00:00-08:00` now produce the same canonical timestamp and provenance fingerprint.

## Rationale

Without canonicalization, equivalent instants represented with different offsets would produce different provenance identities. UTC normalization removes that representation-only difference while preserving the actual instant.

## Verification

Tests cover equivalent positive/negative offsets, canonical UTC output, and equality of provenance fingerprints for equivalent instants.
