"""Phases 447-449: PostgreSQL session revocation persistence and concurrency."""
import os, threading
from pathlib import Path
import pytest
from core.accounts.postgres_session_revocation import PostgreSQLSessionRevocationStore
DSN=os.getenv("QUANTENGINE_TEST_POSTGRES_ADMIN_DSN")
pytestmark=pytest.mark.skipif(not DSN,reason="PostgreSQL admin DSN absent")

@pytest.fixture
def store():
    import psycopg
    with psycopg.connect(DSN,autocommit=True) as db:
        db.execute("DROP TABLE IF EXISTS public.qe_session_revocations")
        db.execute(Path("migrations/postgres/003_session_revocation.sql").read_text())
    value=PostgreSQLSessionRevocationStore(DSN, require_tls=False)
    try: yield value
    finally:
        with psycopg.connect(DSN,autocommit=True) as db: db.execute("DROP TABLE IF EXISTS public.qe_session_revocations")

def test_restart_and_idempotency(store):
    store.revoke("subject","session",revoked_at_epoch=100)
    store.revoke("subject","session",revoked_at_epoch=120)
    assert PostgreSQLSessionRevocationStore(DSN, require_tls=False).is_revoked("subject","session")
    assert not store.is_revoked("subject","other")

def test_global_idp_session_scope(store):
    store.revoke("member","global-session",revoked_at_epoch=1)
    assert store.is_revoked("member","global-session")

def test_concurrent_writers_converge(store):
    errors=[]; barrier=threading.Barrier(8)
    def run(i):
        try:
            barrier.wait(timeout=3)
            store.revoke("member","race-session",revoked_at_epoch=10+i)
        except Exception as exc: errors.append(type(exc).__name__)
    threads=[threading.Thread(target=run,args=(i,)) for i in range(8)]
    [t.start() for t in threads]; [t.join(timeout=5) for t in threads]
    assert not errors and all(not t.is_alive() for t in threads)
    assert store.is_revoked("member","race-session")

def test_bad_values_and_error_redaction(store):
    with pytest.raises(ValueError): store.is_revoked("","session")
    with pytest.raises(ValueError): store.revoke("member","session",revoked_at_epoch=float("nan"))
    def broken(*a,**k): raise RuntimeError("secret dsn")
    bad=PostgreSQLSessionRevocationStore("invalid",connect_factory=broken,require_tls=False)
    with pytest.raises(RuntimeError,match="lookup failed") as err: bad.is_revoked("member","session")
    assert "secret" not in str(err.value)


def test_tls_modes_fail_before_connection_attempt():
    for mode in ("disable", "allow", "prefer", "require", "verify-ca"):
        calls=[]
        store=PostgreSQLSessionRevocationStore(
            f"postgresql://identity/db?sslmode={mode}",
            connect_factory=lambda *args, **kwargs: calls.append((args, kwargs)),
        )
        with pytest.raises(RuntimeError, match="verify-full"):
            store.is_revoked("member", "session")
        assert calls == []


def test_tls_is_required_by_default():
    calls=[]
    store=PostgreSQLSessionRevocationStore(
        "postgresql://identity/db",
        connect_factory=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    with pytest.raises(RuntimeError, match="verify-full"):
        store.is_revoked("member", "session")
    assert calls == []
