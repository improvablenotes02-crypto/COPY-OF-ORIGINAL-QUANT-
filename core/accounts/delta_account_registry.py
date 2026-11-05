"""Tenant-scoped Delta account registry with encrypted credential persistence.

The registry deliberately has no built-in encryption key or provider. A
deployment must inject an approved encryption provider (normally a KMS-backed
provider) and a repository. The included SQLite repository stores ciphertext
only and is intended for local/single-process development, not as a claim of
production-grade multi-node storage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Protocol

from core.exchanges.delta import delta_environments


class AccountRegistryError(RuntimeError):
    """Base error for account registry operations."""


class AccountNotFoundError(AccountRegistryError):
    """The account is not owned by the requested tenant."""


class CredentialVaultError(AccountRegistryError):
    """Credential encryption/decryption failed or returned invalid data."""


class AccountScopeError(AccountRegistryError):
    """A provider identity does not match the registered account scope."""


@dataclass(frozen=True, slots=True)
class CiphertextEnvelope:
    key_id: str
    algorithm: str
    ciphertext: bytes = field(repr=False)


class EncryptionProvider(Protocol):
    """Authenticated encryption provider; associated_data must be authenticated."""

    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        ...

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        ...


@dataclass(frozen=True, slots=True)
class EncryptedDeltaAccount:
    account_id: str
    tenant_id: str
    venue: str
    region: str
    environment: str
    label: str
    provider_account_id: str | None
    key_id: str
    algorithm: str
    ciphertext: bytes = field(repr=False)
    created_at_ns: int
    updated_at_ns: int


@dataclass(frozen=True, slots=True)
class DeltaAccountMetadata:
    account_id: str
    venue: str
    region: str
    environment: str
    label: str
    provider_account_id: str | None
    created_at_ns: int
    updated_at_ns: int


class DeltaAccountRepository(Protocol):
    def save(self, record: EncryptedDeltaAccount) -> None:
        ...

    def get(self, tenant_id: str, account_id: str) -> EncryptedDeltaAccount | None:
        ...

    def list_for_tenant(self, tenant_id: str) -> list[EncryptedDeltaAccount]:
        ...

    def delete(self, tenant_id: str, account_id: str) -> bool:
        ...


class SQLiteDeltaAccountRepository:
    """SQLite ciphertext repository for local development and tests.

    SQLite's WHERE clauses enforce tenant ownership for every read/delete.
    The database contains no plaintext API keys or secrets. Production
    deployments should inject a durable shared repository implementation.
    """

    def __init__(self, database: str | Path = ":memory:"):
        self.database = str(database)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.database, check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS delta_accounts (
                    account_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    venue TEXT NOT NULL CHECK (venue = 'delta'),
                    region TEXT NOT NULL CHECK (region IN ('GLOBAL', 'INDIA')),
                    environment TEXT NOT NULL CHECK (environment IN ('PRODUCTION', 'SANDBOX')),
                    label TEXT NOT NULL,
                    provider_account_id TEXT,
                    key_id TEXT NOT NULL,
                    algorithm TEXT NOT NULL,
                    ciphertext BLOB NOT NULL,
                    created_at_ns INTEGER NOT NULL,
                    updated_at_ns INTEGER NOT NULL,
                    UNIQUE (tenant_id, account_id)
                )
                """
            )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_delta_accounts_tenant "
                "ON delta_accounts (tenant_id, created_at_ns, account_id)"
            )

    def save(self, record: EncryptedDeltaAccount) -> None:
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO delta_accounts (
                    account_id, tenant_id, venue, region, environment, label,
                    provider_account_id, key_id, algorithm, ciphertext,
                    created_at_ns, updated_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.account_id, record.tenant_id, record.venue,
                    record.region, record.environment, record.label,
                    record.provider_account_id, record.key_id, record.algorithm,
                    sqlite3.Binary(record.ciphertext), record.created_at_ns,
                    record.updated_at_ns,
                ),
            )

    @staticmethod
    def _record(row: sqlite3.Row) -> EncryptedDeltaAccount:
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
        )

    def get(self, tenant_id: str, account_id: str) -> EncryptedDeltaAccount | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM delta_accounts WHERE tenant_id = ? AND account_id = ?",
                (tenant_id, account_id),
            ).fetchone()
        return self._record(row) if row is not None else None

    def list_for_tenant(self, tenant_id: str) -> list[EncryptedDeltaAccount]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM delta_accounts WHERE tenant_id = ? "
                "ORDER BY created_at_ns, account_id",
                (tenant_id,),
            ).fetchall()
        return [self._record(row) for row in rows]

    def delete(self, tenant_id: str, account_id: str) -> bool:
        with self._lock:
            cursor = self._connection.execute(
                "DELETE FROM delta_accounts WHERE tenant_id = ? AND account_id = ?",
                (tenant_id, account_id),
            )
        return cursor.rowcount == 1

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def _require_text(value: object, name: str, *, max_length: int = 128) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise ValueError(f"{name} must be a non-empty string of at most {max_length} characters")
    return value.strip()


def _associated_data(record: EncryptedDeltaAccount) -> bytes:
    scope = {
        "account_id": record.account_id,
        "environment": record.environment,
        "region": record.region,
        "tenant_id": record.tenant_id,
        "venue": record.venue,
    }
    return json.dumps(scope, sort_keys=True, separators=(",", ":")).encode("utf-8")


class DeltaReadOnlySession:
    """Narrow account-bound facade; deliberately exposes no order-write methods."""

    __slots__ = ("_exchange", "_record")

    def __init__(self, exchange: object, record: EncryptedDeltaAccount):
        self._exchange = exchange
        self._record = record

    @property
    def account_id(self) -> str:
        return self._record.account_id

    @property
    def tenant_id(self) -> str:
        return self._record.tenant_id

    @property
    def region(self) -> str:
        return self._record.region

    @property
    def environment(self) -> str:
        return self._record.environment

    def verify_provider_identity(self) -> str:
        observed = self._exchange._get_authenticated_account_id()
        expected = self._record.provider_account_id
        if expected is not None and observed != expected:
            raise AccountScopeError("authenticated Delta identity does not match the registered account")
        return observed

    def _verify_snapshot_scope(self, snapshot: dict) -> dict:
        observed = snapshot.get("account_id")
        expected = self._record.provider_account_id
        if expected is not None and observed != expected:
            raise AccountScopeError("Delta snapshot identity does not match the registered account")
        return snapshot

    def get_balance(self):
        return self._exchange.get_balance()

    def get_positions(self):
        return self._exchange.get_positions()

    def get_order_history_snapshot(self, *, max_pages: int = 100):
        return self._verify_snapshot_scope(
            self._exchange.get_order_history_snapshot(max_pages=max_pages)
        )

    def get_fill_history_snapshot(self, *, max_pages: int = 100):
        return self._verify_snapshot_scope(
            self._exchange.get_fill_history_snapshot(max_pages=max_pages)
        )


class DeltaAccountRegistry:
    """Tenant-scoped account lifecycle; plaintext credentials never leave this service."""

    def __init__(
        self,
        repository: DeltaAccountRepository,
        encryption_provider: EncryptionProvider,
    ):
        if repository is None or encryption_provider is None:
            raise ValueError("repository and encryption_provider are required")
        self._repository = repository
        self._encryption_provider = encryption_provider

    def register_account(
        self,
        *,
        tenant_id: str,
        label: str,
        region: str,
        environment: str,
        api_key: str,
        api_secret: str,
    ) -> DeltaAccountMetadata:
        tenant = _require_text(tenant_id, "tenant_id")
        account_label = _require_text(label, "label", max_length=80)
        normalized_region = delta_environments.resolve_region(region)
        normalized_environment = delta_environments.resolve_environment(environment)
        if normalized_region == delta_environments.UNKNOWN_REGION:
            raise ValueError("unsupported Delta region")
        if normalized_environment == delta_environments.UNKNOWN:
            raise ValueError("unsupported Delta environment")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key must be non-empty")
        if not isinstance(api_secret, str) or not api_secret.strip():
            raise ValueError("api_secret must be non-empty")

        account_id = str(uuid.uuid4())
        now = time.time_ns()
        provisional = EncryptedDeltaAccount(
            account_id=account_id,
            tenant_id=tenant,
            venue="delta",
            region=normalized_region,
            environment=normalized_environment,
            label=account_label,
            provider_account_id=None,
            key_id="pending",
            algorithm="pending",
            ciphertext=b"pending",
            created_at_ns=now,
            updated_at_ns=now,
        )
        plaintext = json.dumps(
            {"api_key": api_key, "api_secret": api_secret},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            envelope = self._encryption_provider.encrypt(
                plaintext, associated_data=_associated_data(provisional)
            )
        except Exception:
            raise CredentialVaultError("Delta credential encryption failed") from None
        if (
            not isinstance(envelope, CiphertextEnvelope)
            or not envelope.key_id
            or not envelope.algorithm
            or not isinstance(envelope.ciphertext, bytes)
            or not envelope.ciphertext
        ):
            raise CredentialVaultError("encryption provider returned an invalid ciphertext envelope")

        record = EncryptedDeltaAccount(
            account_id=account_id,
            tenant_id=tenant,
            venue="delta",
            region=normalized_region,
            environment=normalized_environment,
            label=account_label,
            provider_account_id=None,
            key_id=envelope.key_id,
            algorithm=envelope.algorithm,
            ciphertext=envelope.ciphertext,
            created_at_ns=now,
            updated_at_ns=now,
        )
        self._repository.save(record)
        return self._metadata(record)

    def list_accounts(self, tenant_id: str) -> list[DeltaAccountMetadata]:
        tenant = _require_text(tenant_id, "tenant_id")
        return [self._metadata(record) for record in self._repository.list_for_tenant(tenant)]

    def delete_account(self, *, tenant_id: str, account_id: str) -> bool:
        tenant = _require_text(tenant_id, "tenant_id")
        account = _require_text(account_id, "account_id")
        return self._repository.delete(tenant, account)

    def open_read_only_session(
        self, *, tenant_id: str, account_id: str
    ) -> DeltaReadOnlySession:
        tenant = _require_text(tenant_id, "tenant_id")
        account = _require_text(account_id, "account_id")
        record = self._repository.get(tenant, account)
        if record is None:
            raise AccountNotFoundError("Delta account not found for tenant")
        envelope = CiphertextEnvelope(
            key_id=record.key_id,
            algorithm=record.algorithm,
            ciphertext=record.ciphertext,
        )
        try:
            plaintext = self._encryption_provider.decrypt(
                envelope, associated_data=_associated_data(record)
            )
            payload = json.loads(plaintext.decode("utf-8"))
            if (
                not isinstance(payload, dict)
                or set(payload) != {"api_key", "api_secret"}
                or not isinstance(payload["api_key"], str)
                or not payload["api_key"]
                or not isinstance(payload["api_secret"], str)
                or not payload["api_secret"]
            ):
                raise ValueError("invalid credential payload")
        except Exception:
            raise CredentialVaultError("Delta credential decryption or validation failed") from None

        endpoint = delta_environments.resolve_rest_endpoint(
            record.environment, record.region
        )
        from core.exchanges.delta.delta_exchange import DeltaExchange
        exchange = DeltaExchange(
            api_key=payload["api_key"],
            api_secret=payload["api_secret"],
            base_url=endpoint,
        )
        return DeltaReadOnlySession(exchange, record)

    @staticmethod
    def _metadata(record: EncryptedDeltaAccount) -> DeltaAccountMetadata:
        return DeltaAccountMetadata(
            account_id=record.account_id,
            venue=record.venue,
            region=record.region,
            environment=record.environment,
            label=record.label,
            provider_account_id=record.provider_account_id,
            created_at_ns=record.created_at_ns,
            updated_at_ns=record.updated_at_ns,
        )
