"""Phase 359 PostgreSQL repository integration and concurrency tests."""
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import psycopg
import pytest

from core.accounts.delta_account_registry import EncryptedDeltaAccount, AccountScopeError
from core.accounts.postgres_delta_account_repository import PostgreSQLDeltaAccountRepository

ADMIN = os.getenv("QUANTENGINE_TEST_POSTGRES_ADMIN_DSN")
RUNTIME = os.getenv("QUANTENGINE_TEST_POSTGRES_RUNTIME_DSN")
pytestmark = pytest.mark.skipif(not ADMIN or not RUNTIME, reason="PostgreSQL CI DSNs absent")


def _record(account_id, tenant_id, *, generation=1, updated=10,
            key_id="key-v1", ciphertext=b"cipher-v1"):
    return EncryptedDeltaAccount(
        account_id=account_id, tenant_id=tenant_id, venue="delta",
        region="INDIA", environment="SANDBOX", label=account_id,
        provider_account_id=None, key_id=key_id, algorithm="AES-256-GCM",
        ciphertext=ciphertext, created_at_ns=1, updated_at_ns=updated,
        credential_generation=generation,
    )


@pytest.fixture
def repository():
    sql = Path("migrations/postgres/001_delta_account_registry.sql").read_text()
    with psycopg.connect(ADMIN, autocommit=True) as db:
        db.execute("DROP TABLE IF EXISTS public.delta_credential_rotation_events CASCADE")
        db.execute("DROP TABLE IF EXISTS public.delta_accounts CASCADE")
        db.execute("DROP FUNCTION IF EXISTS public.reject_delta_rotation_mutation() CASCADE")
        if db.execute("SELECT 1 FROM pg_roles WHERE rolname='qe_runtime_phase358'").fetchone():
            db.execute("DROP OWNED BY qe_runtime_phase358")
            db.execute("DROP ROLE qe_runtime_phase358")
        db.execute("CREATE ROLE qe_runtime_phase358 LOGIN PASSWORD 'qe_runtime_phase358_test' NOSUPERUSER NOBYPASSRLS")
        db.execute(sql)
        db.execute("GRANT USAGE ON SCHEMA public TO qe_runtime_phase358")
        db.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON public.delta_accounts,public.delta_credential_rotation_events TO qe_runtime_phase358")
    try:
        yield PostgreSQLDeltaAccountRepository(RUNTIME)
    finally:
        with psycopg.connect(ADMIN, autocommit=True) as db:
            if db.execute("SELECT 1 FROM pg_roles WHERE rolname='qe_runtime_phase358'").fetchone():
                db.execute("DROP OWNED BY qe_runtime_phase358")
                db.execute("DROP ROLE qe_runtime_phase358")


def test_repository_tenant_scope_rotation_atomicity_and_hash_chain(repository):
    assert repository.production_ready is False
    repository.save(_record("acct-a", "tenant-a"))
    repository.save(_record("acct-b", "tenant-b"))

    assert repository.get("tenant-a", "acct-a").ciphertext == b"cipher-v1"
    assert repository.get("tenant-a", "acct-b") is None
    assert [item.account_id for item in repository.list_for_tenant("tenant-a")] == ["acct-a"]
    assert [item.account_id for item in repository.list_for_tenant("tenant-b")] == ["acct-b"]

    repository.bind_provider_identity("tenant-a", "acct-a", "delta-user-a")
    assert repository.get("tenant-a", "acct-a").provider_account_id == "delta-user-a"
    with pytest.raises(AccountScopeError, match="different provider identity"):
        repository.bind_provider_identity("tenant-a", "acct-a", "delta-user-other")

    current = repository.get("tenant-a", "acct-a")
    candidate = _record("acct-a", "tenant-a", generation=2, updated=11,
                        key_id="key-v2", ciphertext=b"cipher-v2")
    replacement = replace(candidate, provider_account_id="delta-user-a", updated_at_ns=current.updated_at_ns + 1)
    assert repository.replace_credentials(
        replacement, expected_generation=current.credential_generation,
        expected_updated_at_ns=current.updated_at_ns,
    ) is True
    assert repository.replace_credentials(
        replacement, expected_generation=current.credential_generation,
        expected_updated_at_ns=current.updated_at_ns,
    ) is False

    events = repository.list_credential_rotation_events("tenant-a", "acct-a")
    assert len(events) == 1
    assert (events[0].previous_generation, events[0].new_generation) == (1, 2)
    assert (events[0].previous_key_id, events[0].new_key_id) == ("key-v1", "key-v2")
    assert repository.list_credential_rotation_events("tenant-b", "acct-a") == []
    assert repository.get("tenant-a", "acct-a").ciphertext == b"cipher-v2"


def test_concurrent_rotation_has_exactly_one_winner(repository):
    repository.save(_record("acct-race", "tenant-race"))
    first = _record("acct-race", "tenant-race", generation=2, updated=20,
                    key_id="key-v2", ciphertext=b"candidate-one")
    second = _record("acct-race", "tenant-race", generation=2, updated=21,
                     key_id="key-v3", ciphertext=b"candidate-two")

    def rotate(candidate):
        return repository.replace_credentials(
            candidate, expected_generation=1, expected_updated_at_ns=10
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(rotate, (first, second)))
    assert sorted(results) == [False, True]
    saved = repository.get("tenant-race", "acct-race")
    assert saved.credential_generation == 2
    assert len(repository.list_credential_rotation_events("tenant-race", "acct-race")) == 1


def test_delete_is_tenant_scoped(repository):
    repository.save(_record("acct-delete", "tenant-one"))
    assert repository.delete("tenant-two", "acct-delete") is False
    assert repository.get("tenant-one", "acct-delete") is not None
    assert repository.delete("tenant-one", "acct-delete") is True
    assert repository.get("tenant-one", "acct-delete") is None
