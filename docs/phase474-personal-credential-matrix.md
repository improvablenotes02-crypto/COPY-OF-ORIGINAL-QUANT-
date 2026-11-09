# Phase 474 - Personal Delta credential matrix regression

- Exercise all four supported personal credential selections: Global/India crossed with Production/Sandbox.
- Assert that each selection writes only its matching key/secret pair and never falls back across regions or environments.
- Assert that paper/live safety flags are preserved and not enabled by credential configuration.
- Assert that the repository ignores local `.env` files while allowing the non-secret `.env.example` template.
- Tests use synthetic values only and never contact an exchange.

Validation: Phase 458 setup tests plus Phase 474 credential matrix and Git-ignore regression tests on Ubuntu and Windows.
