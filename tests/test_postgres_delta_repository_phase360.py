"""Phase 360: PostgreSQL cross-process rotation and crash recovery."""
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import psycopg
import pytest

from core.accounts.delta_account_registry import EncryptedDeltaAccount
from core.accounts.postgres_delta_account_repository import PostgreSQLDeltaAccountRepository

ADMIN = os.getenv("QUANTENGINE_TEST_POSTGRES_ADMIN_DSN")
RUNTIME = os.getenv("QUANTENGINE_TEST_POSTGRES_RUNTIME_DSN")
pytestmark = pytest.mark.skipif(not ADMIN or not RUNTIME, reason="PostgreSQL CI DSNs absent")


def _record(account_id, tenant_id, *, generation=1, updated=10, key_id="key-v1", ciphertext=b"cipher-v1"):
    return EncryptedDeltaAccount(
        account_id=account_id, tenant_id=tenant_id, venue="delta",
        region="INDIA", environment="SANDBOX", label=account_id,
        provider_account_id=None, key_id=key_id, algorithm="AES-256-GCM",
        ciphertext=ciphertext, created_at_ns=1, updated_at_ns=updated,
        credential_generation=generation,
    )


def _rotate_worker(payload):
    dsn, candidate = payload
    return PostgreSQLDeltaAccountRepository(dsn).replace_credentials(
        candidate, expected_generation=1, expected_updated_at_ns=10
    )


def _crash_worker(dsn):
    conn = psycopg.connect(dsn)
    conn.execute("SELECT set_config('quantengine.tenant_id', %s, true)", ("tenant-crash",))
    conn.execute(
        """UPDATE public.delta_accounts
           SET credential_generation=2, key_id='uncommitted-key',
               ciphertext=%s, updated_at_ns=20
           WHERE tenant_id=%s AND account_id=%s""",
        (b"uncommitted-ciphertext", "tenant-crash", "acct-crash"),
    )
    os._exit(73)


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
        db.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON public.delta_accounts, public.delta_credential_rotation_events TO qe_runtime_phase358")
    try:
        yield PostgreSQLDeltaAccountRepository(RUNTIME)
    finally:
        with psycopg.connect(ADMIN, autocommit=True) as db:
            if db.execute("SELECT 1 FROM pg_roles WHERE rolname='qe_runtime_phase358'").fetchone():
                db.execute("DROP OWNED BY qe_runtime_phase358")
                db.execute("DROP ROLE qe_runtime_phase358")


def test_independent_processes_have_exactly_one_rotation_winner(repository):
    repository.save(_record("acct-race", "tenant-race"))
    candidates = (
        _record("acct-race", "tenant-race", generation=2, updated=20, key_id="key-a", ciphertext=b"candidate-a"),
        _record("acct-race", "tenant-race", generation=2, updated=21, key_id="key-b", ciphertext=b"candidate-b"),
    )
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn")) as pool:
        outcomes = list(pool.map(_rotate_worker, ((RUNTIME, candidates[0]), (RUNTIME, candidates[1]))))
    assert sorted(outcomes) == [False, True]
    restarted = PostgreSQLDeltaAccountRepository(RUNTIME)
    saved = restarted.get("tenant-race", "acct-race")
    events = restarted.list_credential_rotation_events("tenant-race", "acct-race")
    assert saved.credential_generation == 2
    assert saved.key_id in {"key-a", "key-b"}
    assert len(events) == 1
    assert (events[0].previous_generation, events[0].new_generation) == (1, 2)


def test_process_crash_rolls_back_partial_rotation_and_restart_recovers(repository):
    repository.save(_record("acct-crash", "tenant-crash"))
    worker = multiprocessing.get_context("spawn").Process(target=_crash_worker, args=(RUNTIME,))
    worker.start()
    worker.join(timeout=15)
    if worker.is_alive():
        worker.terminate()
        worker.join(timeout=5)
        pytest.fail("crash-recovery worker exceeded its time bound")
    assert worker.exitcode == 73

    restarted = PostgreSQLDeltaAccountRepository(RUNTIME)
    saved = restarted.get("tenant-crash", "acct-crash")
    assert (saved.credential_generation, saved.key_id, saved.ciphertext) == (1, "key-v1", b"cipher-v1")
    assert restarted.list_credential_rotation_events("tenant-crash", "acct-crash") == []

    replacement = replace(
        _record("acct-crash", "tenant-crash", generation=2, updated=11, key_id="key-v2", ciphertext=b"committed"),
        updated_at_ns=saved.updated_at_ns + 1,
    )
    assert restarted.replace_credentials(replacement, expected_generation=1, expected_updated_at_ns=saved.updated_at_ns)
    after_restart = PostgreSQLDeltaAccountRepository(RUNTIME)
    events = after_restart.list_credential_rotation_events("tenant-crash", "acct-crash")
    assert len(events) == 1
    assert (events[0].previous_generation, events[0].new_generation) == (1, 2)
    assert after_restart.get("tenant-crash", "acct-crash").ciphertext == b"committed"
