# QuantEngine

QuantEngine is a multi-market research, backtesting, market-data and trading-engine codebase. This README describes the verified repository baseline; it is not a claim of production readiness.

## Current safety and support boundary

- **Release posture: HOLD / NOT PRODUCTION READY.**
- **Live exchange order writing remains disarmed by default.** Do not enable live execution based only on a passing focused CI workflow.
- The personal credential setup currently documented and supported in the mainline is **Delta Exchange** (India/Global and Sandbox/Production selection). Do not assume another broker or exchange is supported until its adapter, tests, and operational evidence are present on this branch.
- Paper/research workflows do not require live credentials.
- Passing tests does not establish profitability, a strategy edge, or production readiness.

See [Next Actions](NEXT_ACTIONS.md), [Implementation State](IMPLEMENTATION_STATE.md), and [Security Phase 362](SECURITY_PHASE362.md) for the recorded blockers and security boundaries.

## Quick start

Use Python 3.11 or the version pinned by your deployment environment.

```bash
python -m venv .venv
# Windows PowerShell:
.venv\\Scripts\\Activate.ps1
# macOS/Linux:
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Create a local environment file from the template:

```bash
# Windows PowerShell
Copy-Item .env.example .env
# macOS/Linux
cp .env.example .env
```

Keep `.env` local. Never commit credentials, API secrets, session tokens, or account identifiers. The repository ignore rules are intended to exclude local environment files; verify that before adding any new secret-bearing configuration.

## Configure your own Delta Exchange API keys

The supported personal-key workflow is:

1. Run `python scripts/configure_delta_credentials.py`.
2. Select the correct region (`INDIA` or `GLOBAL`) and environment (`SANDBOX` or `PRODUCTION`).
3. Confirm the local update and enter the API key and secret at the hidden prompts.
4. Run `python scripts/check_delta_credentials.py` to verify the selected local configuration.

Credentials are written to the ignored local `.env`; they are not stored in Git. Follow [Personal Delta API key setup](docs/OPERATOR_PERSONAL_DELTA_API_KEYS.md) for the operator procedure. Start with Sandbox and paper/research workflows. Credential presence is not permission to submit live orders.

## Run tests

Install the pinned dependencies above, then run:

```bash
python -m pytest tests/ -q
```

For a focused test file:

```bash
python -m pytest tests/<test_file>.py -q
```

Use the CI workflows under `.github/workflows/` as the authoritative hosted evidence for their respective gates. A focused workflow is not a substitute for the full regression suite. Record the exact commit, platform, command, test counts, skips, and failures when reporting verification.

## Repository safety rules

- Work on a feature branch and open a pull request; do not commit directly to `main`.
- Keep one consolidated continuation branch and avoid creating a branch for every small phase.
- Rebase/merge only after inspecting the full diff against the current `main`; do not force-update shared branches to hide divergence.
- Regenerate `BUILD_MANIFEST.sha256` with the repository's own manifest-generation procedure whenever tracked source files change. Never hand-edit or approximate digest values.
- Do not commit `.env`, credentials, tokens, private account data, local caches, or test artifacts containing secrets.
- Preserve fail-closed execution defaults. Any change to order-writing paths requires explicit safety tests proving that unauthorized or invalid states produce zero exchange writes.
- Do not claim a market, broker, exchange, or asset class is supported unless its actual adapter and tests exist in this branch.

## Project status and handoff

The repository's current release posture remains **HOLD / NOT PRODUCTION READY / EDGE NOT ESTABLISHED**. Phases 239–245 have completed the documented cross-platform release-archive and credential-setup hardening work on the continuation branch. Remaining operator and evidence gates include owner-run Sandbox credential verification, multi-day market-data evidence, external tax-invoice reconciliation, independent execution/strategy validation, and release governance.

Read [NEXT_ACTIONS.md](NEXT_ACTIONS.md) before selecting the next engineering task. Update status documents only when supported by reproducible evidence.
