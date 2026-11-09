# Phase 476 - Read-only Delta connectivity check

After the offline preflight and authenticated identity check, run:

```powershell
py scripts\check_delta_connection.py
```

This command creates a client using the selected Delta region/environment, verifies the authenticated identity, and requests the public product catalog through that same region-pinned REST transport. It prints only a product count; account identifiers, credentials and provider exception details are redacted.

The command performs no balance, position, order, fill, cancel or other exchange-write operation. It is a connectivity smoke test, not proof of market-data freshness, trading permissions, or execution readiness. If the public catalog is unavailable, it fails rather than substituting another region or environment.
