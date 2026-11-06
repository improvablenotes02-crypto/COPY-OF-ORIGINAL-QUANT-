# Phase 300 — Empty Dataset Rejection

## Contract

A dataset may be structurally complete and have exhausted pagination while still containing zero rows. Such a dataset is not a valid input to a backtest. `validate_backtest_inputs()` now rejects zero-row records before replay eligibility is granted.

For portfolios, one empty leg rejects the entire portfolio evidence set before any symbol engine can run.

## Rationale

An empty result must not be mistaken for a valid zero-trade backtest or a successful no-signal strategy outcome. It usually indicates an empty query window, symbol mismatch, upstream retrieval defect, or an acquisition issue that needs explicit handling.

## Verification

Tests cover a zero-row complete dataset, an empty portfolio leg, and a nonempty complete dataset that remains eligible.
