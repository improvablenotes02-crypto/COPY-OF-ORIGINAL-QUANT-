import sqlite3
import pytest
from core.accounts.request_tenant_authorization import AuthenticatedPrincipal,ContextVarPrincipalSource,bind_authenticated_principal
from core.accounts.postgres_tenant_services import SQLiteBackgroundJobStore
from core.accounts.background_job_maintenance import SQLiteBackgroundJobMaintenance
def p(subject="owner-1"):return AuthenticatedPrincipal(subject,"session-1",frozenset({"tenant-a"}),9999999999)
def setup(tmp_path):
    store=SQLiteBackgroundJobStore(str(tmp_path/"jobs.sqlite3"));source=ContextVarPrincipalSource()
    ops=SQLiteBackgroundJobMaintenance(store,principal_source=source,owner_authorizer=lambda x:x.subject_id=="owner-1")
    with bind_authenticated_principal(p()):
        job=store.enqueue(p(),"tenant-a");store.claim_job(job)
    return store,source,ops,job
def test_phase393_owner_only_read_only_integrity_and_schema_check(tmp_path):
    store,source,ops,job=setup(tmp_path)
    with bind_authenticated_principal(p("member")):
        with pytest.raises(PermissionError):ops.verify_source()
    with bind_authenticated_principal(p()):report=ops.verify_source()
    assert report["healthy"] and report["quick_check"]==("ok",)
    assert report["state_counts"]=={"RUNNING":1} and store.status(job)=="RUNNING"
def test_phase394_online_backup_is_verified_and_no_clobber(tmp_path):
    store,source,ops,job=setup(tmp_path);destination=tmp_path/"snapshots"/"jobs.sqlite3";destination.parent.mkdir()
    with bind_authenticated_principal(p()):
        receipt=ops.create_backup(destination);verified=ops.verify_backup(destination,expected_sha256=receipt.sha256)
        with pytest.raises(FileExistsError):ops.create_backup(destination)
    assert receipt.verified and receipt.size_bytes>0 and verified.sha256==receipt.sha256
    c=sqlite3.connect(str(destination))
    try:assert c.execute("SELECT state FROM qe_background_jobs WHERE job_id=?",(job,)).fetchone()==("RUNNING",)
    finally:c.close()
    assert store.status(job)=="RUNNING"
def test_phase395_backup_digest_and_invalid_schema_are_rejected(tmp_path):
    store,source,ops,job=setup(tmp_path);backup=tmp_path/"backup.sqlite3"
    with bind_authenticated_principal(p()):
        receipt=ops.create_backup(backup)
        with pytest.raises(RuntimeError,match="SHA-256 mismatch"):ops.verify_backup(backup,expected_sha256="0"*64)
    backup.write_bytes(backup.read_bytes()+b"tamper")
    with bind_authenticated_principal(p()):
        with pytest.raises(RuntimeError,match="SHA-256 mismatch"):ops.verify_backup(backup,expected_sha256=receipt.sha256)
    invalid=tmp_path/"invalid.sqlite3";c=sqlite3.connect(str(invalid));c.execute("CREATE TABLE unrelated(x)");c.close()
    digest=ops._digest(invalid)
    with bind_authenticated_principal(p()):
        with pytest.raises(RuntimeError,match="integrity verification"):ops.verify_backup(invalid,expected_sha256=digest)
def test_phase396_restore_drill_isolated_and_no_clobber(tmp_path):
    store,source,ops,job=setup(tmp_path);backup=tmp_path/"backup.sqlite3";target=tmp_path/"restore-drill.sqlite3"
    with bind_authenticated_principal(p()):
        receipt=ops.create_backup(backup);restored=ops.restore_drill(backup,target,expected_sha256=receipt.sha256)
        assert restored.sha256==receipt.sha256
        with pytest.raises(FileExistsError):ops.restore_drill(backup,target,expected_sha256=receipt.sha256)
    c=sqlite3.connect(str(target))
    try:assert c.execute("SELECT state FROM qe_background_jobs WHERE job_id=?",(job,)).fetchone()==("RUNNING",)
    finally:c.close()
    assert store.status(job)=="RUNNING"
