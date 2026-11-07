import pytest
import multiprocessing
from core.accounts.request_tenant_authorization import AuthenticatedPrincipal,ContextVarPrincipalSource,bind_authenticated_principal
from core.accounts.postgres_tenant_services import SQLiteBackgroundJobStore
from core.accounts.background_job_operations import SQLiteBackgroundJobOperations
def p(s="owner-1"):return AuthenticatedPrincipal(s,"s1",frozenset({"tenant-a"}),9999999999)
def setup(tmp_path):
 st=SQLiteBackgroundJobStore(str(tmp_path/"jobs.db"),clock=lambda:100.0);src=ContextVarPrincipalSource()
 op=SQLiteBackgroundJobOperations(st,principal_source=src,owner_authorizer=lambda x:x.subject_id=="owner-1",clock=lambda:101.0)
 with bind_authenticated_principal(p()):j=st.enqueue(src.current_principal(),"tenant-a");st.claim_job(j)
 return st,src,op,j
def test_phase385_owner_only_sanitized_inspection(tmp_path):
 st,src,op,j=setup(tmp_path)
 with bind_authenticated_principal(p("member")):
  with pytest.raises(PermissionError):op.inspect(j)
 with bind_authenticated_principal(p()):r=op.inspect(j)
 assert r["state"]=="RUNNING" and "session_id" not in r and "tenant_ids_json" not in r
def test_phase386_stale_inventory_bounded_and_read_only(tmp_path):
 st,src,op,j=setup(tmp_path)
 with bind_authenticated_principal(p()):r=op.stale_running(before_epoch=999,limit=3)
 assert len(r)==1 and r[0]["job_id"]==j and st.status(j)=="RUNNING"
 with bind_authenticated_principal(p()):
  with pytest.raises(ValueError):op.stale_running(before_epoch=999,limit=501)
def test_phase387_review_never_changes_or_replays_job(tmp_path):
 st,src,op,j=setup(tmp_path)
 with bind_authenticated_principal(p()):
  e=op.review_running(j,disposition="OUTCOME_UNKNOWN",reason="venue outcome ambiguous")
  assert op.audit_chain_valid()
 assert e.actor_id=="owner-1" and st.status(j)=="RUNNING" and st.claim_job(j) is None
def test_phase388_owner_only_hash_chain_detects_tampering(tmp_path):
 st,src,op,j=setup(tmp_path)
 with bind_authenticated_principal(p("member")):
  with pytest.raises(PermissionError):op.review_running(j,disposition="NO_EXTERNAL_EFFECT",reason="checked")
 with bind_authenticated_principal(p()):
  op.review_running(j,disposition="NO_EXTERNAL_EFFECT",reason="reviewed")
  assert op.audit_chain_valid()
 c=st._connect()
 try:c.execute("DROP TRIGGER qe_job_review_no_update");c.execute("UPDATE qe_background_job_reviews SET reason='tampered'")
 finally:c.close()
 with bind_authenticated_principal(p()):assert not op.audit_chain_valid()

def _phase389_claim_in_child(database_path,job_id,output):
    try:
        store=SQLiteBackgroundJobStore(database_path)
        output.put("claimed" if store.claim_job(job_id) is not None else "lost")
    except Exception as exc:
        output.put("error:"+type(exc).__name__)

def test_phase389_independent_processes_have_one_claim_winner(tmp_path):
    database=str(tmp_path/"cross-process.sqlite3")
    store=SQLiteBackgroundJobStore(database)
    with bind_authenticated_principal(p()):job=store.enqueue(p(),"tenant-a")
    ctx=multiprocessing.get_context("spawn")
    output=ctx.Queue()
    workers=[ctx.Process(target=_phase389_claim_in_child,args=(database,job,output)) for _ in range(2)]
    for worker in workers:worker.start()
    for worker in workers:worker.join(15)
    for worker in workers:
        if worker.is_alive():worker.terminate();worker.join(5)
    assert all(worker.exitcode==0 for worker in workers)
    results=sorted(output.get(timeout=3) for _ in workers)
    assert results==["claimed","lost"]
    assert store.status(job)=="RUNNING"

def test_phase390_crashed_worker_remains_stale_and_never_replays(tmp_path):
    database=str(tmp_path/"crashed-worker.sqlite3")
    store=SQLiteBackgroundJobStore(database)
    with bind_authenticated_principal(p()):job=store.enqueue(p(),"tenant-a")
    ctx=multiprocessing.get_context("spawn");output=ctx.Queue()
    worker=ctx.Process(target=_phase389_claim_in_child,args=(database,job,output))
    worker.start();worker.join(15)
    assert worker.exitcode==0 and output.get(timeout=3)=="claimed"
    src=ContextVarPrincipalSource()
    ops=SQLiteBackgroundJobOperations(store,principal_source=src,owner_authorizer=lambda x:x.subject_id=="owner-1",clock=lambda:101.0)
    with bind_authenticated_principal(p()):
        stale=ops.stale_running(before_epoch=9999999999)
        assert [row["job_id"] for row in stale]==[job]
        assert store.claim_job(job) is None
        ops.review_running(job,disposition="OUTCOME_UNKNOWN",reason="worker process exited; external effect unverified")
    assert store.status(job)=="RUNNING"

def test_phase391_owner_health_snapshot_is_bounded_and_non_replaying(tmp_path):
    store,src,ops,job=setup(tmp_path)
    with bind_authenticated_principal(p()):
        report=ops.health_snapshot(stale_before_epoch=999,limit=10)
    assert report["counts"]["RUNNING"]==1
    assert report["stale_running"][0]["job_id"]==job
    assert "subject_id" not in report["stale_running"][0]
    assert report["audit_chain_valid"] is True
    assert report["automatic_replay_enabled"] is False
    assert report["production_ready"] is False
    assert store.status(job)=="RUNNING"

def test_phase392_health_snapshot_fails_closed_on_audit_corruption(tmp_path):
    store,src,ops,job=setup(tmp_path)
    with bind_authenticated_principal(p()):
        ops.review_running(job,disposition="OUTCOME_UNKNOWN",reason="reviewed")
    connection=store._connect()
    try:
        connection.execute("DROP TRIGGER qe_job_review_no_update")
        connection.execute("UPDATE qe_background_job_reviews SET reason='tampered'")
    finally:connection.close()
    with bind_authenticated_principal(p()):
        with pytest.raises(RuntimeError,match="audit integrity"):
            ops.health_snapshot(stale_before_epoch=999)
