"""Tenant-scoped Delta account registry with encrypted credential persistence.

The registry deliberately has no built-in encryption key or provider. A
deployment must inject an approved encryption provider (normally a KMS-backed
provider) and a repository. The included SQLite repository stores ciphertext
only and is intended for local/single-process development, not as a claim of
production-grade multi-node storage.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
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


class CredentialRotationConflictError(AccountRegistryError):
    """A concurrent account change won the credential-rotation compare-and-swap."""


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
    credential_generation: int = 1


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


@dataclass(frozen=True, slots=True)
class DeltaCredentialRotationEvent:
    event_id: str
    tenant_id: str
    account_id: str
    previous_generation: int
    new_generation: int
    previous_key_id: str
    new_key_id: str
    occurred_at_ns: int
    previous_event_hash: str
    event_hash: str


class DeltaAccountRepository(Protocol):
    def save(self, record: EncryptedDeltaAccount) -> None:
        ...

    def get(self, tenant_id: str, account_id: str) -> EncryptedDeltaAccount | None:
        ...

    def list_for_tenant(self, tenant_id: str) -> list[EncryptedDeltaAccount]:
        ...

    def delete(self, tenant_id: str, account_id: str) -> bool:
        ...

    def bind_provider_identity(
        self, tenant_id: str, account_id: str, provider_account_id: str
    ) -> None:
        ...

    def replace_credentials(
        self, record: EncryptedDeltaAccount, *, expected_generation: int,
        expected_updated_at_ns: int,
    ) -> bool:
        ...

    def list_credential_rotation_events(
        self, tenant_id: str, account_id: str
    ) -> list[DeltaCredentialRotationEvent]:
        ...


class SQLiteDeltaAccountRepository:
    """SQLite ciphertext repository for local development and tests.

    SQLite's WHERE clauses enforce tenant ownership for every read/delete.
    The database contains no plaintext API keys or secrets. Production
    deployments should inject a durable shared repository implementation.
    """

    # This local SQLite implementation is never production-admissible.
    production_ready = False

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
                    credential_generation INTEGER NOT NULL DEFAULT 1
                        CHECK (credential_generation >= 1),
                    UNIQUE (tenant_id, account_id)
                )
                """
            )
            columns = {
                row["name"]
                for row in self._connection.execute("PRAGMA table_info(delta_accounts)")
            }
            if "credential_generation" not in columns:
                self._connection.execute(
                    "ALTER TABLE delta_accounts ADD COLUMN credential_generation "
                    "INTEGER NOT NULL DEFAULT 1 CHECK (credential_generation >= 1)"
                )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS delta_credential_rotation_events (
                    event_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    previous_generation INTEGER NOT NULL,
                    new_generation INTEGER NOT NULL,
                    previous_key_id TEXT NOT NULL,
                    new_key_id TEXT NOT NULL,
                    occurred_at_ns INTEGER NOT NULL,
                    previous_event_hash TEXT NOT NULL DEFAULT '',
                    event_hash TEXT NOT NULL DEFAULT '',
                    UNIQUE (tenant_id, account_id, new_generation)
                )
                """
            )
            event_columns = {
                row["name"]
                for row in self._connection.execute(
                    "PRAGMA table_info(delta_credential_rotation_events)"
                )
            }
            if "previous_event_hash" not in event_columns:
                self._connection.execute(
                    "ALTER TABLE delta_credential_rotation_events "
                    "ADD COLUMN previous_event_hash TEXT NOT NULL DEFAULT ''"
                )
            if "event_hash" not in event_columns:
                self._connection.execute(
                    "ALTER TABLE delta_credential_rotation_events "
                    "ADD COLUMN event_hash TEXT NOT NULL DEFAULT ''"
                )
            self._connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_delta_credential_events_account "
                "ON delta_credential_rotation_events "
                "(tenant_id, account_id, occurred_at_ns, event_id)"
            )
            self._connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS prevent_delta_credential_event_update
                BEFORE UPDATE ON delta_credential_rotation_events
                BEGIN
                    SELECT RAISE(ABORT, 'credential rotation audit events are immutable');
                END
                """
            )
            self._connection.execute(
                """
                CREATE TRIGGER IF NOT EXISTS prevent_delta_credential_event_delete
                BEFORE DELETE ON delta_credential_rotation_events
                BEGIN
                    SELECT RAISE(ABORT, 'credential rotation audit events are immutable');
                END
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
                    created_at_ns, updated_at_ns, credential_generation
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.account_id, record.tenant_id, record.venue,
                    record.region, record.environment, record.label,
                    record.provider_account_id, record.key_id, record.algorithm,
                    sqlite3.Binary(record.ciphertext), record.created_at_ns,
                    record.updated_at_ns, record.credential_generation,
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
            credential_generation=row["credential_generation"],
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

    def bind_provider_identity(
        self, tenant_id: str, account_id: str, provider_account_id: str
    ) -> None:
        """Atomically bind an account to one authenticated Delta user ID."""
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE delta_accounts
                SET provider_account_id = ?, updated_at_ns = MAX(?, updated_at_ns + 1)
                WHERE tenant_id = ? AND account_id = ?
                  AND (provider_account_id IS NULL OR provider_account_id = ?)
                """,
                (
                    provider_account_id, time.time_ns(), tenant_id,
                    account_id, provider_account_id,
                ),
            )
            if cursor.rowcount == 1:
                return
            row = self._connection.execute(
                "SELECT provider_account_id FROM delta_accounts "
                "WHERE tenant_id = ? AND account_id = ?",
                (tenant_id, account_id),
            ).fetchone()
        if row is None:
            raise AccountNotFoundError("Delta account not found for tenant")
        raise AccountScopeError(
            "registered Delta account is already bound to a different provider identity"
        )

    def replace_credentials(
        self, record: EncryptedDeltaAccount, *, expected_generation: int,
        expected_updated_at_ns: int,
    ) -> bool:
        """Commit a credential generation and its audit event in one transaction."""
        if record.credential_generation != expected_generation + 1:
            return False
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                previous = self._connection.execute(
                    """
                    SELECT credential_generation, updated_at_ns, key_id
                    FROM delta_accounts
                    WHERE tenant_id = ? AND account_id = ?
                    """,
                    (record.tenant_id, record.account_id),
                ).fetchone()
                if (
                    previous is None
                    or previous["credential_generation"] != expected_generation
                    or previous["updated_at_ns"] != expected_updated_at_ns
                    or record.updated_at_ns <= previous["updated_at_ns"]
                ):
                    self._connection.execute("ROLLBACK")
                    return False
                cursor = self._connection.execute(
                    """
                    UPDATE delta_accounts
                    SET key_id = ?, algorithm = ?, ciphertext = ?, updated_at_ns = ?,
                        credential_generation = ?, provider_account_id = ?
                    WHERE tenant_id = ? AND account_id = ? AND credential_generation = ?
                      AND updated_at_ns = ?
                    """,
                    (
                        record.key_id, record.algorithm, sqlite3.Binary(record.ciphertext),
                        record.updated_at_ns, record.credential_generation,
                        record.provider_account_id, record.tenant_id, record.account_id,
                        expected_generation, expected_updated_at_ns,
                    ),
                )
                if cursor.rowcount != 1:
                    self._connection.execute("ROLLBACK")
                    return False
                self._connection.execute(
                    """
                    previous_events = self.list_credential_rotation_events(
                        record.tenant_id, record.account_id
                    )
                    previous_hash = (
                        previous_events[-1].event_hash if previous_events else "0" * 64
                    )
                    event_id = str(uuid.uuid4())
                    event_hash = _credential_rotation_event_hash(
                        event_id=event_id,
                        tenant_id=record.tenant_id,
                        account_id=record.account_id,
                        previous_generation=previous["credential_generation"],
                        new_generation=record.credential_generation,
                        previous_key_id=previous["key_id"],
                        new_key_id=record.key_id,
                        occurred_at_ns=record.updated_at_ns,
                        previous_event_hash=previous_hash,
                    )
                    self._connection.execute(
                        """
                        INSERT INTO delta_credential_rotation_events (
                            event_id, tenant_id, account_id, previous_generation,
                            new_generation, previous_key_id, new_key_id, occurred_at_ns,
                            previous_event_hash, event_hash
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event_id, record.tenant_id, record.account_id,
                            previous["credential_generation"], record.credential_generation,
                            previous["key_id"], record.key_id, record.updated_at_ns,
                            previous_hash, event_hash,
                        ),
                )
                self._connection.execute("COMMIT")
                return True
            except Exception:
                if self._connection.in_transaction:
                    self._connection.execute("ROLLBACK")
                raise

    def list_credential_rotation_events(
        self, tenant_id: str, account_id: str
    ) -> list[DeltaCredentialRotationEvent]:
        """Return a verified hash chain; legacy unhashed rows are upgraded in memory.

        The chain detects record corruption or offline edits, but is not a
        cryptographic signature against an attacker able to rewrite the database.
        """
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT event_id, tenant_id, account_id, previous_generation,
                       new_generation, previous_key_id, new_key_id, occurred_at_ns,
                       previous_event_hash, event_hash
                FROM delta_credential_rotation_events
                WHERE tenant_id = ? AND account_id = ?
                ORDER BY new_generation, occurred_at_ns, event_id
                """,
                (tenant_id, account_id),
            ).fetchall()
        events = []
        expected_previous_hash = "0" * 64
        for row in rows:
            stored_previous_hash = row["previous_event_hash"] or ""
            if stored_previous_hash and stored_previous_hash != expected_previous_hash:
                raise CredentialVaultError("credential rotation audit hash chain is invalid")
            digest = _credential_rotation_event_hash(
                event_id=row["event_id"],
                tenant_id=row["tenant_id"],
                account_id=row["account_id"],
                previous_generation=row["previous_generation"],
                new_generation=row["new_generation"],
                previous_key_id=row["previous_key_id"],
                new_key_id=row["new_key_id"],
                occurred_at_ns=row["occurred_at_ns"],
                previous_event_hash=expected_previous_hash,
            )
            stored_digest = row["event_hash"] or ""
            if stored_digest and stored_digest != digest:
                raise CredentialVaultError("credential rotation audit event integrity check failed")
            events.append(
                DeltaCredentialRotationEvent(
                    event_id=row["event_id"],
                    tenant_id=row["tenant_id"],
                    account_id=row["account_id"],
                    previous_generation=row["previous_generation"],
                    new_generation=row["new_generation"],
                    previous_key_id=row["previous_key_id"],
                    new_key_id=row["new_key_id"],
                    occurred_at_ns=row["occurred_at_ns"],
                    previous_event_hash=expected_previous_hash,
                    event_hash=digest,
                )
            )
            expected_previous_hash = digest
        return events

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


def _credential_rotation_event_hash(
    *, event_id: str, tenant_id: str, account_id: str,
    previous_generation: int, new_generation: int,
    previous_key_id: str, new_key_id: str, occurred_at_ns: int,
    previous_event_hash: str,
) -> str:
    payload = {
        "account_id": account_id,
        "event_id": event_id,
        "new_generation": new_generation,
        "new_key_id": new_key_id,
        "occurred_at_ns": occurred_at_ns,
        "previous_event_hash": previous_event_hash,
        "previous_generation": previous_generation,
        "previous_key_id": previous_key_id,
        "tenant_id": tenant_id,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class DeltaReadOnlySession:
    """Narrow account-bound facade; deliberately exposes no order-write methods."""

    __slots__ = ("_exchange", "_record", "_closed", "_authorization_check")

    def __init__(
        self,
        exchange: object,
        record: EncryptedDeltaAccount,
        authorization_check=None,
    ):
        self._exchange = exchange
        self._record = record
        self._closed = False
        self._authorization_check = authorization_check

    @property
    def closed(self) -> bool:
        return self._closed

    def _require_open(self) -> None:
        if self._closed or self._exchange is None:
            raise CredentialVaultError("Delta read-only session is closed")
        if self._authorization_check is not None:
            try:
                authorized = self._authorization_check()
            except Exception:
                raise CredentialVaultError(
                    "Delta read-only session authorization could not be verified"
                ) from None
            if authorized is not True:
                raise CredentialVaultError(
                    "Delta read-only session is no longer authorized"
                )

    def close(self) -> None:
        """Close this local client session; venue-side API-key revocation is separate."""
        if self._closed:
            return
        exchange = self._exchange
        self._closed = True
        self._exchange = None
        close = getattr(exchange, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                # A failed cleanup must never reopen this session or leak client details.
                pass

    def __enter__(self):
        self._require_open()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
        return False

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

    @property
    def provider_account_id(self) -> str | None:
        return self._record.provider_account_id

    def verify_provider_identity(self) -> str:
        self._require_open()
        observed = self._exchange._get_authenticated_account_id()
        expected = self._record.provider_account_id
        if expected is not None and observed != expected:
            raise AccountScopeError("authenticated Delta identity does not match the registered account")
        return observed

    def _verify_snapshot_scope(self, snapshot: dict) -> dict:
        self._require_open()
        observed = snapshot.get("account_id")
        expected = self._record.provider_account_id
        if expected is not None and observed != expected:
            raise AccountScopeError("Delta snapshot identity does not match the registered account")
        return snapshot

    def get_balance(self):
        self._require_open()
        return self._exchange.get_balance()

    def get_positions(self):
        self._require_open()
        return self._exchange.get_positions()

    def get_order_history_snapshot(self, *, max_pages: int = 100):
        self._require_open()
        return self._verify_snapshot_scope(
            self._exchange.get_order_history_snapshot(max_pages=max_pages)
        )

    def get_fill_history_snapshot(self, *, max_pages: int = 100):
        self._require_open()
        return self._verify_snapshot_scope(
            self._exchange.get_fill_history_snapshot(max_pages=max_pages)
        )

    def get_account_snapshot(self, *, max_pages: int = 100) -> dict:
        """Collect complete read-only account views under one verified identity.

        This is a sequence of observations, not an exchange-atomic snapshot.
        Any unsuccessful or incomplete component refuses the whole result.
        """
        self._require_open()
        expected = self._record.provider_account_id
        if expected is None:
            raise AccountScopeError(
                "Delta account identity must be verified and bound before snapshot collection"
            )
        identity_before = self.verify_provider_identity()
        if identity_before != expected:
            raise AccountScopeError("authenticated Delta identity does not match the registered account")

        self._require_open()
        balances = self._exchange.get_balance()
        balances_observed_at_ns = time.time_ns()
        self._require_open()
        positions = self._exchange.get_positions()
        positions_observed_at_ns = time.time_ns()
        if not isinstance(balances, dict) or balances.get("success") is not True:
            raise AccountScopeError("Delta balance observation is unsuccessful or malformed")
        if not isinstance(positions, dict) or positions.get("success") is not True:
            raise AccountScopeError("Delta positions observation is unsuccessful or malformed")

        orders = self.get_order_history_snapshot(max_pages=max_pages)
        fills = self.get_fill_history_snapshot(max_pages=max_pages)
        if orders.get("complete") is not True or not isinstance(orders.get("orders"), list):
            raise AccountScopeError("Delta order history is incomplete or malformed")
        if fills.get("complete") is not True or not isinstance(fills.get("fills"), list):
            raise AccountScopeError("Delta fill history is incomplete or malformed")
        order_evidence = orders.get("pagination_evidence")
        fill_evidence = fills.get("pagination_evidence")
        if (
            not isinstance(order_evidence, dict)
            or order_evidence.get("active_cursor_exhausted") is not True
            or order_evidence.get("history_cursor_exhausted") is not True
            or not isinstance(fill_evidence, dict)
            or fill_evidence.get("cursor_exhausted") is not True
        ):
            raise AccountScopeError("Delta account snapshot pagination evidence is incomplete")

        identity_after = self.verify_provider_identity()
        if identity_after != identity_before:
            raise AccountScopeError("authenticated Delta identity changed during snapshot collection")

        return {
            "venue": "delta",
            "tenant_id": self._record.tenant_id,
            "internal_account_id": self._record.account_id,
            "provider_account_id": identity_before,
            "region": self._record.region,
            "environment": self._record.environment,
            "source": "delta-v2-read-only-account-snapshot",
            "observed_at_ns": time.time_ns(),
            "observation_is_exchange_atomic": False,
            "balances": balances,
            "positions": positions,
            "orders": orders["orders"],
            "fills": fills["fills"],
            "completeness": {
                "balances": True,
                "positions": True,
                "orders": True,
                "fills": True,
                "order_cursor_exhausted": True,
                "fill_cursor_exhausted": True,
            },
            "component_observed_at_ns": {
                "balances": balances_observed_at_ns,
                "positions": positions_observed_at_ns,
                "orders": orders.get("snapshot_as_of_ns"),
                "fills": fills.get("snapshot_as_of_ns"),
            },
        }


class DeltaAccountRegistry:
    """Tenant-scoped account lifecycle; plaintext credentials never leave this service."""

    def __init__(
        self,
        repository: DeltaAccountRepository,
        encryption_provider: EncryptionProvider,
        *,
        exchange_factory=None,
        require_production_security: bool = False,
    ):
        if repository is None or encryption_provider is None:
            raise ValueError("repository and encryption_provider are required")
        if not isinstance(require_production_security, bool):
            raise ValueError("require_production_security must be a boolean")
        self._repository = repository
        self._encryption_provider = encryption_provider
        self._exchange_factory = exchange_factory
        self._require_production_security = require_production_security
        if self._require_production_security:
            self._assert_production_security_contract()

    def _assert_production_security_contract(self) -> str:
        """Require explicit production declarations from crypto and storage.

        These declarations are admission gates, not cryptographic attestations.
        Deployments must separately audit the provider and backing KMS/storage.
        """
        provider_ready = getattr(self._encryption_provider, "production_ready", False)
        provider_algorithm = getattr(self._encryption_provider, "algorithm", None)
        repository_ready = getattr(self._repository, "production_ready", False)
        if (
            provider_ready is not True
            or provider_algorithm != "AES-256-GCM"
            or repository_ready is not True
        ):
            raise CredentialVaultError(
                "production credential security requires an approved AES-256-GCM provider "
                "and production-grade repository"
            )
        return provider_algorithm

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
            expected_algorithm = (
                self._assert_production_security_contract()
                if self._require_production_security else None
            )
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
            or (expected_algorithm is not None and envelope.algorithm != expected_algorithm)
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

    def rotate_credentials(
        self, *, tenant_id: str, account_id: str, api_key: str, api_secret: str
    ) -> DeltaAccountMetadata:
        """Re-encrypt credentials and atomically revoke sessions from older generations.

        A compare-and-swap on updated_at_ns prevents concurrent rotations or
        account changes from silently overwriting one another. The venue identity
        binding and account scope are preserved.
        """
        tenant = _require_text(tenant_id, "tenant_id")
        account = _require_text(account_id, "account_id")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key must be non-empty")
        if not isinstance(api_secret, str) or not api_secret.strip():
            raise ValueError("api_secret must be non-empty")
        current = self._repository.get(tenant, account)
        if current is None:
            raise AccountNotFoundError("Delta account not found for tenant")
        replace_credentials = getattr(self._repository, "replace_credentials", None)
        if not callable(replace_credentials):
            raise CredentialVaultError(
                "account repository does not support atomic credential rotation"
            )

        endpoint = delta_environments.resolve_rest_endpoint(
            current.environment, current.region
        )
        probe = None
        try:
            if self._exchange_factory is None:
                from core.exchanges.delta.delta_exchange import DeltaExchange
                probe = DeltaExchange(
                    api_key=api_key, api_secret=api_secret, base_url=endpoint
                )
            else:
                probe = self._exchange_factory(
                    api_key=api_key, api_secret=api_secret, base_url=endpoint
                )
            verify_identity = getattr(probe, "_get_authenticated_account_id", None)
            if not callable(verify_identity):
                raise RuntimeError("Delta client does not expose authenticated identity verification")
            observed_provider_id = verify_identity()
            if (
                not isinstance(observed_provider_id, str)
                or not observed_provider_id.isdigit()
                or int(observed_provider_id) <= 0
            ):
                raise AccountScopeError(
                    "replacement credentials returned an invalid Delta provider identity"
                )
            if (
                current.provider_account_id is not None
                and observed_provider_id != current.provider_account_id
            ):
                raise AccountScopeError(
                    "replacement credentials belong to a different Delta provider identity"
                )
        except AccountScopeError:
            raise
        except Exception:
            raise CredentialVaultError(
                "replacement Delta credentials could not be authenticated"
            ) from None
        finally:
            close_probe = getattr(probe, "close", None)
            if callable(close_probe):
                try:
                    close_probe()
                except Exception:
                    pass

        plaintext = json.dumps(
            {"api_key": api_key, "api_secret": api_secret},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        try:
            expected_algorithm = (
                self._assert_production_security_contract()
                if self._require_production_security else None
            )
            envelope = self._encryption_provider.encrypt(
                plaintext, associated_data=_associated_data(current)
            )
        except Exception:
            raise CredentialVaultError("Delta credential encryption failed") from None
        if (
            not isinstance(envelope, CiphertextEnvelope)
            or not isinstance(envelope.key_id, str)
            or not envelope.key_id
            or not isinstance(envelope.algorithm, str)
            or not envelope.algorithm
            or not isinstance(envelope.ciphertext, bytes)
            or not envelope.ciphertext
            or (expected_algorithm is not None and envelope.algorithm != expected_algorithm)
        ):
            raise CredentialVaultError("encryption provider returned an invalid ciphertext envelope")

        updated = EncryptedDeltaAccount(
            account_id=current.account_id,
            tenant_id=current.tenant_id,
            venue=current.venue,
            region=current.region,
            environment=current.environment,
            label=current.label,
            provider_account_id=observed_provider_id,
            key_id=envelope.key_id,
            algorithm=envelope.algorithm,
            ciphertext=envelope.ciphertext,
            created_at_ns=current.created_at_ns,
            updated_at_ns=max(time.time_ns(), current.updated_at_ns + 1),
            credential_generation=current.credential_generation + 1,
        )
        try:
            committed = replace_credentials(
                updated,
                expected_generation=current.credential_generation,
                expected_updated_at_ns=current.updated_at_ns,
            )
        except Exception:
            raise CredentialVaultError("Delta credential rotation could not be committed") from None
        if committed is not True:
            latest = self._repository.get(tenant, account)
            if latest is None:
                raise AccountNotFoundError("Delta account not found for tenant")
            raise CredentialRotationConflictError(
                "Delta credentials changed concurrently; reload the account before rotating again"
            )
        return self._metadata(updated)

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
            expected_algorithm = self._assert_production_security_contract() if self._require_production_security else None
            if expected_algorithm is not None and record.algorithm != expected_algorithm:
                raise ValueError("credential algorithm does not match production policy")
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
        try:
            if self._exchange_factory is None:
                from core.exchanges.delta.delta_exchange import DeltaExchange
                exchange = DeltaExchange(
                    api_key=payload["api_key"],
                    api_secret=payload["api_secret"],
                    base_url=endpoint,
                )
            else:
                exchange = self._exchange_factory(
                    api_key=payload["api_key"],
                    api_secret=payload["api_secret"],
                    base_url=endpoint,
                )
        except Exception:
            # Third-party constructors may echo credentials in exception text.
            raise CredentialVaultError(
                "Delta read-only client initialization failed"
            ) from None
        def authorization_check() -> bool:
            current = self._repository.get(tenant, account)
            if current is None:
                return False
            # Any credential, scope, or metadata generation change invalidates
            # clients created from the prior record. Shared repositories make
            # this effective across processes; local SQLite remains single-node.
            return (
                current.tenant_id == record.tenant_id
                and current.account_id == record.account_id
                and current.venue == record.venue
                and current.region == record.region
                and current.environment == record.environment
                and current.key_id == record.key_id
                and current.algorithm == record.algorithm
                and current.provider_account_id == record.provider_account_id
                and current.credential_generation == record.credential_generation
                and current.ciphertext == record.ciphertext
                and current.updated_at_ns == record.updated_at_ns
            )

        return DeltaReadOnlySession(exchange, record, authorization_check)

    def verify_and_bind_identity(
        self, *, tenant_id: str, account_id: str
    ) -> DeltaAccountMetadata:
        """Authenticate read-only, then bind the venue-reported user ID once."""
        tenant = _require_text(tenant_id, "tenant_id")
        account = _require_text(account_id, "account_id")
        session = self.open_read_only_session(
            tenant_id=tenant, account_id=account
        )
        try:
            provider_id = session.verify_provider_identity()
            if (
                not isinstance(provider_id, str)
                or not provider_id.isdigit()
                or int(provider_id) <= 0
            ):
                raise AccountScopeError(
                    "authenticated Delta provider identity is missing or invalid"
                )
            self._repository.bind_provider_identity(
                tenant, account, provider_id
            )
            bound = self._repository.get(tenant, account)
            if bound is None:
                raise AccountNotFoundError("Delta account not found for tenant")
            return self._metadata(bound)
        finally:
            session.close()

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
