# Phase 306 — Typed Strategy and Configuration Identity

## Contract

Evidence-bearing scoped replay APIs now accept typed `StrategyArtifactIdentity` and `BacktestConfigurationIdentity` objects directly, alongside `EngineBuildIdentity`.

The strategy descriptor binds strategy ID, version, source revision, artifact SHA-256, and parameter-schema version. The configuration descriptor binds configuration version, canonical configuration SHA-256, and parameter-schema version. Each exposes a deterministic fingerprint.

Raw fingerprint strings remain supported. If a raw digest and typed descriptor are both supplied for the same identity, they must match exactly. Invalid descriptor types and conflicting values fail closed before replay. A complete execution fingerprint still requires strategy, configuration, and engine identities together.

## Verification

Tests cover typed descriptor integration, strategy/configuration change sensitivity, conflicting raw/typed values, invalid descriptor types, and full evidence-envelope verification.
