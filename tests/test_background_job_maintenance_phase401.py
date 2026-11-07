"""Phases 401-404: identity integrity, state-count binding and process failure safety."""
import multiprocessing,sqlite3,os
import pytest
from core.accounts.request_tenant_authorization import AuthenticatedPrincipal,ContextVarPrincipalSource,bind_authenticated_principal
from core.accounts.postgres_tenant_services import SQLiteBackgroundJobStore
from core.accounts.background_job_maintenance import SQLiteBackgroundJobMaintenance
def principal():return AuthenticatedPrincipal("owner-1","session-1",frozenset({"tenant-a"}),9999999999)
def make_ops(path):
 store=SQLiteBackgroundJobStore(str(path));source=ContextVarPrincipalSource()
 return store,SQLiteBackgroundJobMaintenance(store,principal_source=source,owner_authorizer=lambda p:p.subject_id=="owner-1")
def _backup_worker(db_path,target,event,queue):
 try:
  store,ops=make_ops(db_path)
  with bind_authenticated_principal(principal()):
   event.wait(10)
   receipt=ops.create_backup(target)
  queue.put(("ok",receipt.sha256))
 except FileExistsError:queue.put(("collision",""))
 except Exception as exc:queue.put(("error",type(exc).__name__))
def setup(tmp_path):
 store,ops=make_ops(tmp_path/"jobs.sqlite3")
 with bind_authenticated_principal(principal()):store.enqueue(principal(),"tenant-a")
 return store,ops
def test_phase401_semantic_integrity_rejects_identity_tenant_mismatch(tmp_path):
 store,ops=setup(tmp_path)
 c=sqlite3.connect(store._path)
 try:c.execute("UPDATE qe_background_jobs SET tenant_ids_json='[]'");c.commit()
 finally:c.close()
 with bind_authenticated_principal(principal()):report=ops.verify_source()
 assert not report["healthy"] and "background_job_identity_invariant_failed" in report["problems"]
def test_phase402_backup_verification_can_bind_expected_state_counts(tmp_path):
 store,ops=setup(tmp_path);path=tmp_path/"snapshot.sqlite3"
 with bind_authenticated_principal(principal()):
  receipt=ops.create_backup(path)
  assert ops.verify_backup(path,expected_sha256=receipt.sha256,expected_state_counts={"PENDING":1}).verified
  with pytest.raises(RuntimeError,match="state-count"):
   ops.verify_backup(path,expected_sha256=receipt.sha256,expected_state_counts={"RUNNING":1})
  with pytest.raises(ValueError):ops.verify_backup(path,expected_sha256=receipt.sha256,expected_state_counts={"PENDING":True})
def test_phase403_cross_process_backup_publication_is_no_clobber(tmp_path):
 db=tmp_path/"jobs.sqlite3";_,ops=make_ops(db)
 with bind_authenticated_principal(principal()):ops._store.enqueue(principal(),"tenant-a")
 target=str(tmp_path/"shared.sqlite3")
 ctx=multiprocessing.get_context("spawn");event=ctx.Event();queue=ctx.Queue()
 workers=[ctx.Process(target=_backup_worker,args=(str(db),target,event,queue)) for _ in range(2)]
 for worker in workers:worker.start()
 event.set()
 results=[queue.get(timeout=20) for _ in workers]
 for worker in workers:worker.join(20)
 assert all(worker.exitcode==0 for worker in workers)
 assert sorted(x[0] for x in results)==["collision","ok"]
 with bind_authenticated_principal(principal()):
  digest=ops._digest(target);assert ops.verify_backup(target,expected_sha256=digest).verified
def test_phase404_failed_backup_validation_removes_private_temp_file(tmp_path,monkeypatch):
 _,ops=setup(tmp_path);target=tmp_path/"never-published.sqlite3"
 def fail(_):return {"healthy":False,"problems":("injected_failure",)}
 monkeypatch.setattr(ops,"_inspect",staticmethod(fail))
 with bind_authenticated_principal(principal()):
  with pytest.raises(RuntimeError,match="integrity"):ops.create_backup(target)
 assert not target.exists()
 assert not list(tmp_path.glob(".qe-job-backup-*"))
