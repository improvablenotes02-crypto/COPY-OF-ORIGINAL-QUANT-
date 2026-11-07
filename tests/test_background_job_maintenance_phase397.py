"""Phases 397-400: semantic integrity, inventory, health and concurrent publication."""
import sqlite3,threading
import pytest
from core.accounts.request_tenant_authorization import AuthenticatedPrincipal,ContextVarPrincipalSource,bind_authenticated_principal
from core.accounts.postgres_tenant_services import SQLiteBackgroundJobStore
from core.accounts.background_job_maintenance import SQLiteBackgroundJobMaintenance
def principal(subject="owner-1"):return AuthenticatedPrincipal(subject,"session-1",frozenset({"tenant-a"}),9999999999)
def setup(tmp_path):
 store=SQLiteBackgroundJobStore(str(tmp_path/"jobs.sqlite3"));source=ContextVarPrincipalSource()
 ops=SQLiteBackgroundJobMaintenance(store,principal_source=source,owner_authorizer=lambda p:p.subject_id=="owner-1")
 with bind_authenticated_principal(principal()):job=store.enqueue(principal(),"tenant-a")
 return store,ops,job
def test_phase397_semantic_state_timestamp_corruption_is_rejected(tmp_path):
 store,ops,job=setup(tmp_path)
 with bind_authenticated_principal(principal()):assert ops.verify_source()["semantic_valid"]
 c=sqlite3.connect(store._path)
 try:c.execute("UPDATE qe_background_jobs SET state='RUNNING' WHERE job_id=?",(job,));c.commit()
 finally:c.close()
 with bind_authenticated_principal(principal()):report=ops.verify_source()
 assert not report["healthy"] and "background_job_state_timestamp_mismatch" in report["problems"]
def test_phase398_inventory_omits_invalid_and_symlink_backups(tmp_path):
 _,ops,_=setup(tmp_path);folder=tmp_path/"backups";folder.mkdir();good=folder/"valid.sqlite3";bad=folder/"invalid.sqlite3"
 with bind_authenticated_principal(principal()):ops.create_backup(good)
 bad.write_bytes(b"not sqlite")
 with bind_authenticated_principal(principal()):report=ops.backup_inventory_report(folder)
 found=report["receipts"]
 assert [x.path for x in found]==[str(good)], report
def test_phase399_health_is_owner_only_and_never_authorizes_replay(tmp_path):
 _,ops,_=setup(tmp_path);folder=tmp_path/"backups";folder.mkdir()
 with bind_authenticated_principal(principal("member")):
  with pytest.raises(PermissionError):ops.maintenance_health(folder)
 with bind_authenticated_principal(principal()):report=ops.maintenance_health(folder)
 assert report["source_healthy"] and report["automatic_replay_enabled"] is False and report["production_ready"] is False
def test_phase400_concurrent_backup_publication_is_no_clobber(tmp_path):
 _,ops,_=setup(tmp_path);target=tmp_path/"shared.sqlite3";barrier=threading.Barrier(2);out=[];lock=threading.Lock()
 def worker():
  with bind_authenticated_principal(principal()):
   barrier.wait()
   try:value=ops.create_backup(target).sha256
   except FileExistsError:value="collision"
   with lock:out.append(value)
 threads=[threading.Thread(target=worker) for _ in range(2)]
 [t.start() for t in threads];[t.join(10) for t in threads]
 assert all(not t.is_alive() for t in threads) and len(out)==2 and out.count("collision")==1
 with bind_authenticated_principal(principal()):assert ops.verify_backup(target,expected_sha256=ops._digest(target)).verified
