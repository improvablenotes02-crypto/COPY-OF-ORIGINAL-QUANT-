"""PostgreSQL-backed shared Delta account repository.

Tenant context is transaction-local, but the custom GUC is set by the same
runtime role and can be changed by that role. RLS is scoped defense-in-depth,
not a database-authenticated tenant boundary. This adapter must not claim
tenant isolation until database identity is bound to tenant identity.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from core.accounts.delta_account_registry import (
    AccountNotFoundError,
    AccountScopeError,
    CredentialVaultError,
    DeltaCredentialRotationEvent,
    EncryptedDeltaAccount,
    _credential_rotation_event_hash,
)


class PostgreSQLDeltaAccountRepository:
    """Durable shared repository using PostgreSQL forced row-level security."""

    production_ready = False
    durable_shared_storage = True
    tenant_isolation_enforced = False

    def __init__(self, dsn: str, *, connect_timeout: int = 5):
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("PostgreSQL DSN is required")
        if isinstance(connect_timeout, bool) or not isinstance(connect_timeout, int) or not 1 <= connect_timeout <= 60:
            raise ValueError("connect_timeout must be an integer from 1 to 60")
        self._dsn = dsn
        self._connect_timeout = connect_timeout

    @contextmanager
    def _connection(self, tenant_id: str) -> Iterator[object]:
        if not isinstance(tenant_id, str) or not tenant_id.strip() or len(tenant_id) > 128:
            raise ValueError("tenant_id must be a non-empty string of at most 128 characters")
        try:
            import psycopg
            from psycopg.rows import dict_row
            with psycopg.connect(
                self._dsn, connect_timeout=self._connect_timeout, row_factory=dict_row
            ) as connection:
                with connection.transaction():
                    connection.execute(
                        "SELECT set_config('quantengine.tenant_id', %s, true)",
                        (tenant_id,),
                    )
                    yield connection
        except (AccountNotFoundError, AccountScopeError, CredentialVaultError, ValueError):
            raise
        except Exception as exc:
            # Never propagate DSNs, SQL parameters, or driver diagnostics to callers.
            raise CredentialVaultError("PostgreSQL account repository operation failed") from None

    @staticmethod
    def _record(row: dict) -> EncryptedDeltaAccount:
        return EncryptedDeltaAccount(
            account_id=row["account_id"],
            tenant_id=row["tenant_id"],
            venue=row["venue"],
            region=row["region"],
            environment=row["environment"],
            label=row["label"],
            provider_account_id=row["provider_account_id"],
            key_id=row["key_id"],
            algorithm=row["algorithm"],
            ciphertext=bytes(row["ciphertext"]),
            created_at_ns=row["created_at_ns"],
            updated_at_ns=row["updated_at_ns"],
            credential_generation=row["credential_generation"],
        )

    def save(self, record: EncryptedDeltaAccount) -> None:
        with self._connection(record.tenant_id) as conn:
            conn.execute(
                """
                INSERT INTO public.delta_accounts (
                    account_id, tenant_id, venue, region, environment, label,
                    provider_account_id, key_id, algorithm, ciphertext,
                    created_at_ns, updated_at_ns, credential_generation
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    record.account_id, record.tenant_id, record.venue, record.region,
                    record.environment, record.label, record.provider_account_id,
                    record.key_id, record.algorithm, record.ciphertext,
                    record.created_at_ns, record.updated_at_ns,
                    record.credential_generation,
                ),
            )

    def get(self, tenant_id: str, account_id: str) -> EncryptedDeltaAccount | None:
        with self._connection(tenant_id) as conn:
            row = conn.execute(
                "SELECT * FROM public.delta_accounts WHERE tenant_id=%s AND account_id=%s",
                (tenant_id, account_id),
            ).fetchone()
        return self._record(row) if row else None

    def list_for_tenant(self, tenant_id: str) -> list[EncryptedDeltaAccount]:
        with self._connection(tenant_id) as conn:
            rows = conn.execute(
                "SELECT * FROM public.delta_accounts WHERE tenant_id=%s ORDER BY created_at_ns, account_id",
                (tenant_id,),
            ).fetchall()
        return [self._record(row) for row in rows]

    def delete(self, tenant_id: str, account_id: str) -> bool:
        with self._connection(tenant_id) as conn:
            cursor = conn.execute(
                "DELETE FROM public.delta_accounts WHERE tenant_id=%s AND account_id=%s",
                (tenant_id, account_id),
            )
            return cursor.rowcount == 1

    def bind_provider_identity(
        self, tenant_id: str, account_id: str, provider_account_id: str
    ) -> None:
        if not isinstance(provider_account_id, str) or not provider_account_id.strip():
            raise ValueError("provider_account_id must be non-empty")
        with self._connection(tenant_id) as conn:
            cursor = conn.execute(
                """
                UPDATE public.delta_accounts
                SET provider_account_id=%s,
                    updated_at_ns=GREATEST(%s, updated_at_ns + 1)
                WHERE tenant_id=%s AND account_id=%s
                  AND (provider_account_id IS NULL OR provider_account_id=%s)
                """,
                (provider_account_id, __import__("time").time_ns(), tenant_id,
                 account_id, provider_account_id),
            )
            if cursor.rowcount == 1:
                return
            row = conn.execute(
                "SELECT provider_account_id FROM public.delta_accounts WHERE tenant_id=%s AND account_id=%s",
                (tenant_id, account_id),
            ).fetchone()
            if row is None:
                raise AccountNotFoundError("Delta account not found for tenant")
            raise AccountScopeError("registered Delta account is bound to a different provider identity")

    def replace_credentials(
        self, record: EncryptedDeltaAccount, *, expected_generation: int,
        expected_updated_at_ns: int,
    ) -> bool:
        if record.credential_generation != expected_generation + 1:
            return False
        with self._connection(record.tenant_id) as conn:
            previous = conn.execute(
                """
                SELECT credential_generation, updated_at_ns, key_id
                FROM public.delta_accounts
                WHERE tenant_id=%s AND account_id=%s
                FOR UPDATE
                """,
                (record.tenant_id, record.account_id),
            ).fetchone()
            if (
                previous is None
                or previous["credential_generation"] != expected_generation
                or previous["updated_at_ns"] != expected_updated_at_ns
                or record.updated_at_ns <= previous["updated_at_ns"]
            ):
                return False
            updated = conn.execute(
                """
                UPDATE public.delta_accounts
                SET key_id=%s, algorithm=%s, ciphertext=%s, updated_at_ns=%s,
                    credential_generation=%s, provider_account_id=%s
                WHERE tenant_id=%s AND account_id=%s
                  AND credential_generation=%s AND updated_at_ns=%s
                """,
                (
                    record.key_id, record.algorithm, record.ciphertext,
                    record.updated_at_ns, record.credential_generation,
                    record.provider_account_id, record.tenant_id, record.account_id,
                    expected_generation, expected_updated_at_ns,
                ),
            )
            if updated.rowcount != 1:
                return False
            last = conn.execute(
                """
                SELECT event_hash FROM public.delta_credential_rotation_events
                WHERE tenant_id=%s AND account_id=%s
                ORDER BY new_generation DESC, occurred_at_ns DESC, event_id DESC
                LIMIT 1
                """,
                (record.tenant_id, record.account_id),
            ).fetchone()
            previous_hash = last["event_hash"] if last else "0" * 64
            import uuid
            event_id = str(uuid.uuid4())
            event_hash = _credential_rotation_event_hash(
                event_id=event_id, tenant_id=record.tenant_id,
                account_id=record.account_id,
                previous_generation=previous["credential_generation"],
                new_generation=record.credential_generation,
                previous_key_id=previous["key_id"], new_key_id=record.key_id,
                occurred_at_ns=record.updated_at_ns,
                previous_event_hash=previous_hash,
            )
            conn.execute(
                """
                INSERT INTO public.delta_credential_rotation_events (
                    event_id, tenant_id, account_id, previous_generation,
                    new_generation, previous_key_id, new_key_id, occurred_at_ns,
                    previous_event_hash, event_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    event_id, record.tenant_id, record.account_id,
                    previous["credential_generation"], record.credential_generation,
                    previous["key_id"], record.key_id, record.updated_at_ns,
                    previous_hash, event_hash,
                ),
            )
            return True

    def list_credential_rotation_events(
        self, tenant_id: str, account_id: str
    ) -> list[DeltaCredentialRotationEvent]:
        with self._connection(tenant_id) as conn:
            rows = conn.execute(
                """
                SELECT event_id, tenant_id, account_id, previous_generation,
                       new_generation, previous_key_id, new_key_id, occurred_at_ns,
                       previous_event_hash, event_hash
                FROM public.delta_credential_rotation_events
                WHERE tenant_id=%s AND account_id=%s
                ORDER BY new_generation, occurred_at_ns, event_id
                """,
                (tenant_id, account_id),
            ).fetchall()
        events = []
        expected_previous_hash = "0" * 64
        for row in rows:
            if row["previous_event_hash"] != expected_previous_hash:
                raise CredentialVaultError("credential rotation audit hash chain is invalid")
            digest = _credential_rotation_event_hash(
                event_id=row["event_id"], tenant_id=row["tenant_id"],
                account_id=row["account_id"],
                previous_generation=row["previous_generation"],
                new_generation=row["new_generation"],
                previous_key_id=row["previous_key_id"],
                new_key_id=row["new_key_id"],
                occurred_at_ns=row["occurred_at_ns"],
                previous_event_hash=expected_previous_hash,
            )
            if row["event_hash"] != digest:
                raise CredentialVaultError("credential rotation audit event integrity check failed")
            events.append(DeltaCredentialRotationEvent(
                event_id=row["event_id"], tenant_id=row["tenant_id"],
                account_id=row["account_id"],
                previous_generation=row["previous_generation"],
                new_generation=row["new_generation"],
                previous_key_id=row["previous_key_id"],
                new_key_id=row["new_key_id"],
                occurred_at_ns=row["occurred_at_ns"],
                previous_event_hash=expected_previous_hash, event_hash=digest,
            ))
            expected_previous_hash = digest
        return events


class AuthenticatedPostgreSQLDeltaAccountRepository(PostgreSQLDeltaAccountRepository):
    """Delta repository bound to a trusted tenant-specific PostgreSQL login."""
    production_ready = False
    durable_shared_storage = True
    tenant_isolation_enforced = True

    def __init__(self, dsn_resolver, *, connect_timeout: int = 5, connect_factory=None):
        from core.accounts.postgres_tenant_connection import TenantBoundPostgreSQLConnection
        self._tenant_connection = TenantBoundPostgreSQLConnection(dsn_resolver, connect_timeout=connect_timeout, connect_factory=connect_factory)

    @contextmanager
    def _connection(self, tenant_id: str) -> Iterator[object]:
        try:
            with self._tenant_connection.connect(tenant_id) as connection: yield connection
        except (AccountNotFoundError, AccountScopeError, CredentialVaultError, ValueError): raise
        except Exception: raise CredentialVaultError("PostgreSQL account repository operation failed") from None
