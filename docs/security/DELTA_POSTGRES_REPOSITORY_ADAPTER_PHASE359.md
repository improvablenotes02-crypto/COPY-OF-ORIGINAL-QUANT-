# Phase 359 — PostgreSQL Delta account repository

## Scope
Implement the existing `DeltaAccountRepository` protocol on PostgreSQL using the Phase 358 tenant-isolation schema. The adapter uses a fresh connection per operation and transaction-local `quantengine.tenant_id` context. Tenant predicates remain explicit in SQL in addition to forced row-level security.

## Security and transaction properties
- Credential ciphertext only; no API key or secret plaintext is persisted by this adapter.
- Forced RLS is required on both account and rotation-event tables. The runtime role must not be a superuser, table owner, or `BYPASSRLS` role.
- Credential generation compare-and-swap locks the account row with `SELECT ... FOR UPDATE`.
- Updating the encrypted envelope and inserting its rotation event occur in one database transaction. A failed audit insert rolls back the credential update.
- Rotation history is returned only after verifying the complete SHA-256 event chain.
- Provider identity binding is tenant-scoped and cannot silently replace an existing different identity.
- Account deletion does not delete immutable rotation history.

## Explicit non-admission
The adapter declares `production_ready = False`. PostgreSQL durability and RLS are necessary foundations, not production certification. Production admission still requires managed database hardening, external KMS/HSM-backed encryption, tenant authorization, external immutable audit, backup/restore and disaster-recovery evidence, operational monitoring, incident response, and independent security review. No live Delta order path is enabled by this phase.

## CI evidence
The PostgreSQL integration job exercises the repository against PostgreSQL 16 with a non-superuser, non-BYPASSRLS runtime role. Tests cover cross-tenant reads, scoped listing/deletion, provider identity binding, generation CAS, atomic audit history, hash-chain verification, and concurrent rotation attempts. Passing tests certify only these scoped behaviors.
