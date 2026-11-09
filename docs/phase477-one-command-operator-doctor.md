# Phase 477 - One-command operator doctor

For the normal personal-account setup, use one command from the repository root:

```powershell
py scripts\quantengine_doctor.py
```

The doctor first performs the offline configuration preflight. If the exact region/environment or matching local credential pair is missing, or any live execution flag is present, it stops without making a network request. Otherwise it performs the read-only authenticated identity and public product-catalog connectivity check.

It does not read balances, positions, orders or fills and does not place/cancel orders. A pass means local configuration is consistent and the selected Delta REST identity/catalog endpoints responded. It does not certify market-data streaming, trading permissions, strategy correctness, profitability or production readiness.
