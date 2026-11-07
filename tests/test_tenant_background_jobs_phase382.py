"""Phases 382-384: durable, one-shot tenant background jobs."""
import threading
import pytest
from core.accounts.delta_account_registry import AccountScopeError
from core.accounts.oidc_tenant_principal import AuthenticatedPrincipal
from core.accounts.postgres_tenant_services import SQLiteBackgroundJobStore, TenantBackgroundTaskRunner
from core.accounts.request_tenant_authorization import ContextVarPrincipalSource, RequestScopedTenantAuthorizer, bind_authenticated_principal
from core.accounts.tenant_governance_runtime import AuthenticatedTenantGovernanceRuntime
import core.accounts.tenant_governance_runtime as runtime_module

class Sessions:
    production_ready=True
    def __init__(self): self.active=True
    def is_session_active(self,p): return self.active

def principal(expiry=9999999999):
    return AuthenticatedPrincipal("owner-1","session-1",frozenset({"tenant-a"}),expiry)

def setup(tmp_path, clock=lambda:100.0):
    store=SQLiteBackgroundJobStore(str(tmp_path/"jobs.sqlite3"),clock=clock)
    source,sessions=ContextVarPrincipalSource(),Sessions()
    auth=RequestScopedTenantAuthorizer(source,sessions,clock=clock)
    return store,source,sessions,auth

def test_phase382_job_scope_is_from_server_envelope_not_worker_argument(tmp_path):
    store,source,_,auth=setup(tmp_path); runner=TenantBackgroundTaskRunner(store,auth)
    with bind_authenticated_principal(principal()):
        job=store.enqueue(source.current_principal(),"tenant-a")
    seen=[]
    assert runner.run(job,lambda: seen.append(auth.authorize_tenant("tenant-a")) or "ok")=="ok"
    assert seen==[True] and store.status(job)=="SUCCEEDED"
    with pytest.raises(ValueError,match="callback must be callable"): runner.run(job,"tenant-b",lambda:None)

def test_phase382_enqueue_rejects_wrong_tenant_and_expired_principal(tmp_path):
    store,_,_,_=setup(tmp_path)
    with pytest.raises(AccountScopeError): store.enqueue(principal(),"tenant-b")
    with pytest.raises(AccountScopeError): store.enqueue(principal(99),"tenant-a")

def test_phase383_expired_job_is_terminal(tmp_path):
    now=[100.0]; store,source,_,auth=setup(tmp_path,clock=lambda:now[0])
    with bind_authenticated_principal(principal()): job=store.enqueue(source.current_principal(),"tenant-a",ttl_seconds=2)
    now[0]=103.0
    with pytest.raises(AccountScopeError): TenantBackgroundTaskRunner(store,auth).run(job,lambda:pytest.fail("expired job ran"))
    assert store.status(job)=="EXPIRED"

def test_phase383_callback_failure_is_terminal_and_not_replayed(tmp_path):
    store,source,_,auth=setup(tmp_path)
    with bind_authenticated_principal(principal()): job=store.enqueue(source.current_principal(),"tenant-a")
    runner=TenantBackgroundTaskRunner(store,auth)
    with pytest.raises(RuntimeError,match="callback failure"): runner.run(job,lambda:(_ for _ in ()).throw(RuntimeError("callback failure")))
    assert store.status(job)=="FAILED"
    with pytest.raises(AccountScopeError): runner.run(job,lambda:pytest.fail("replayed"))

def test_phase383_crash_after_claim_is_not_automatically_retried(tmp_path):
    store,source,_,auth=setup(tmp_path)
    with bind_authenticated_principal(principal()): job=store.enqueue(source.current_principal(),"tenant-a")
    assert store.claim_job(job) is not None
    with pytest.raises(AccountScopeError): TenantBackgroundTaskRunner(store,auth).run(job,lambda:pytest.fail("replayed"))
    assert store.status(job)=="RUNNING"

def test_phase384_concurrent_workers_execute_only_once(tmp_path):
    store,source,_,auth=setup(tmp_path)
    with bind_authenticated_principal(principal()): job=store.enqueue(source.current_principal(),"tenant-a")
    barrier=threading.Barrier(2); calls=[]; results=[]; lock=threading.Lock()
    def worker():
        barrier.wait()
        try:
            result=TenantBackgroundTaskRunner(store,auth).run(job,lambda:(lock.acquire(),calls.append(1),lock.release(),"ok")[-1])
            results.append(result)
        except AccountScopeError: results.append("rejected")
    threads=[threading.Thread(target=worker) for _ in range(2)]
    [t.start() for t in threads]; [t.join(5) for t in threads]
    assert all(not t.is_alive() for t in threads)
    assert calls==[1] and sorted(results)==["ok","rejected"]
    assert store.status(job)=="SUCCEEDED"

def test_phase384_revoked_session_blocks_callback_and_fails_job(tmp_path):
    store,source,sessions,auth=setup(tmp_path)
    with bind_authenticated_principal(principal()): job=store.enqueue(source.current_principal(),"tenant-a")
    sessions.active=False
    with pytest.raises(AccountScopeError): TenantBackgroundTaskRunner(store,auth).run(job,lambda:pytest.fail("revoked session ran"))
    assert store.status(job)=="FAILED"

def test_phase384_runtime_owns_enqueue_and_opaque_worker_dispatch(tmp_path,monkeypatch):
    store=SQLiteBackgroundJobStore(str(tmp_path/"runtime.sqlite3"),clock=lambda:100.0)
    source,sessions=ContextVarPrincipalSource(),Sessions()
    from core.accounts.owner_governance import SQLiteOwnerGovernanceRepository
    class Repo(SQLiteOwnerGovernanceRepository):
        production_ready=False
        durable_shared_storage=True
        tenant_isolation_enforced=True
        def __init__(self,resolver,*,connect_timeout=5): super().__init__()
    monkeypatch.setattr(runtime_module,"AuthenticatedPostgreSQLOwnerGovernanceRepository",Repo)
    service=AuthenticatedTenantGovernanceRuntime(owner_subject_id="owner-1",principal_source=source,
        session_validator=sessions,tenant_dsn_resolver=lambda tenant:"test-"+tenant,
        background_job_store=store,auth_clock=lambda:100.0)
    with bind_authenticated_principal(principal()): job=service.enqueue_background_job("tenant-a")
    assert service.run_background_job(job,lambda:"worker-ran")=="worker-ran"
    assert store.status(job)=="SUCCEEDED" and service.production_ready is False
    with bind_authenticated_principal(principal()):
        with pytest.raises(PermissionError): service.enqueue_background_job("tenant-b")
