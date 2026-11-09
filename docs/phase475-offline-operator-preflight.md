# Phase 475 - Offline operator preflight

Run from the repository root after entering your own Delta credentials:

```powershell
py scripts\quantengine_preflight.py
```

The preflight checks the selected region/environment, exact REST endpoint, presence of that exact credential pair, and that live execution flags are disarmed. It performs no network requests and never prints credential values.

If it passes, run the separate read-only authentication check:

```powershell
py scripts\check_delta_credentials.py
```

A successful offline preflight proves only local configuration consistency. A successful identity check proves authentication only; neither proves market-data access, trading permissions, or execution readiness. Do not enable live flags as part of setup.
