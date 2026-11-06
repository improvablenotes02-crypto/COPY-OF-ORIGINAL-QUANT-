"""Phase 341: explicit monotonic credential generations and SQLite migration."""

from dataclasses import replace
import hashlib
import sqlite3

from core.accounts.delta_account_registry import (
    CiphertextEnvelope,
    DeltaAccountRegistry,
    SQLiteDeltaAccountRepository,
)


class _IdentityExchange:
    def __init__(self, **kwargs):
        self.closed = False

    def _get_authenticated_account_id(self):
        return "987654"

    def close(self):
        self.closed = True


def _make_registry(repository, provider):
    return DeltaAccountRegistry(
        repository, provider, exchange_factory=_IdentityExchange
    )


class _TestOnlyProvider:
    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        tag = hashlib.sha256(associated_data).digest()[:16]
        return CiphertextEnvelope("phase341-test-key", "TEST-ONLY", tag + plaintext)

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        tag = hashlib.sha256(associated_data).digest()[:16]
        if not envelope.ciphertext.startswith(tag):
            raise ValueError("associated data mismatch")
        return envelope.ciphertext[16:]


def test_credential_generation_increments_once_per_successful_rotation(tmp_path):
    repository = SQLiteDeltaAccountRepository(tmp_path / "generation.sqlite3")
    registry = _make_registry(repository, _TestOnlyProvider())
    metadata = registry.register_account(
        tenant_id="tenant-phase341", label="generation", region="INDIA",
        environment="SANDBOX", api_key="key-one", api_secret="secret-one",
    )
    try:
        original = repository.get("tenant-phase341", metadata.account_id)
        assert original.credential_generation == 1
        rotated = registry.rotate_credentials(
            tenant_id="tenant-phase341", account_id=metadata.account_id,
            api_key="key-two", api_secret="secret-two",
        )
        current = repository.get("tenant-phase341", metadata.account_id)
        assert current.credential_generation == 2
        assert rotated.updated_at_ns == current.updated_at_ns
        assert current.created_at_ns == original.created_at_ns
    finally:
        repository.close()


def test_stale_generation_cannot_overwrite_newer_credentials(tmp_path):
    repository = SQLiteDeltaAccountRepository(tmp_path / "stale-generation.sqlite3")
    registry = _make_registry(repository, _TestOnlyProvider())
    metadata = registry.register_account(
        tenant_id="tenant-phase341-stale", label="stale", region="INDIA",
        environment="SANDBOX", api_key="key-one", api_secret="secret-one",
    )
    try:
        current = repository.get("tenant-phase341-stale", metadata.account_id)
        stale_candidate = replace(
            current, key_id="stale-key", algorithm="TEST-ONLY",
            ciphertext=b"stale-ciphertext", updated_at_ns=current.updated_at_ns + 1,
            credential_generation=current.credential_generation + 1,
        )
        registry.rotate_credentials(
            tenant_id="tenant-phase341-stale", account_id=metadata.account_id,
            api_key="key-two", api_secret="secret-two",
        )
        assert repository.replace_credentials(
            stale_candidate,
            expected_generation=current.credential_generation,
            expected_updated_at_ns=current.updated_at_ns,
        ) is False
        unchanged = repository.get("tenant-phase341-stale", metadata.account_id)
        assert unchanged.credential_generation == 2
        assert unchanged.key_id == "phase341-test-key"
    finally:
        repository.close()


def test_existing_sqlite_schema_is_migrated_to_generation_one(tmp_path):
    database = tmp_path / "legacy-account-schema.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(
        """
        CREATE TABLE delta_accounts (
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
    connection.execute(
        """
        INSERT INTO delta_accounts (
            account_id, tenant_id, venue, region, environment, label,
            provider_account_id, key_id, algorithm, ciphertext,
            created_at_ns, updated_at_ns
        ) VALUES (?, ?, 'delta', 'INDIA', 'SANDBOX', ?, NULL, ?, ?, ?, 10, 20)
        """,
        ("legacy-account", "legacy-tenant", "legacy", "legacy-key", "TEST-ONLY", b"opaque"),
    )
    connection.commit()
    connection.close()

    repository = SQLiteDeltaAccountRepository(database)
    try:
        migrated = repository.get("legacy-tenant", "legacy-account")
        assert migrated is not None
        assert migrated.credential_generation == 1
        columns = {
            row["name"]
            for row in repository._connection.execute("PRAGMA table_info(delta_accounts)")
        }
        assert "credential_generation" in columns
    finally:
        repository.close()
