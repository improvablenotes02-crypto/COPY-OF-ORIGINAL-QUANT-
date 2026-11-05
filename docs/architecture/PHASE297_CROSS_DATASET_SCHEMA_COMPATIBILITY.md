# Phase 297 — Cross-Dataset Schema Compatibility

## Contract

A multi-dataset backtest now rejects portfolio legs whose normalized data schema versions or normalization versions differ. Venue, region, environment, public/private data class, and exact private-account identity checks remain in force.

This prevents a portfolio replay from silently combining rows that share field names but were produced under incompatible normalization contracts.

## Deliberate compatibility boundary

Timeframes and instrument types are not forced to be identical here: legitimate strategies may combine multiple bar intervals or instrument classes. Those dimensions remain explicitly represented in each provenance record and should be constrained by the strategy's own declared compatibility policy.

## Verification

Tests cover schema-version mismatch, normalization-version mismatch, and successful validation when versions match. The new test file is part of the strict runtime CI workflow.
