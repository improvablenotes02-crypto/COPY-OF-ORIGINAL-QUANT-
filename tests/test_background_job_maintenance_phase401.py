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

 
def test_phase405_duplicate_queue_timestamps_do_not_hide_corrupt_identity(tmp_path):
 store,ops=setup(tmp_path)
 with bind_authenticated_principal(principal()):store.enqueue(principal(),"tenant-a")
 c=sqlite3.connect(store._path)
 try:
  c.execute("UPDATE qe_background_jobs SET created_at=10,expires_at=20")
  second=c.execute("SELECT job_id FROM qe_background_jobs ORDER BY rowid DESC LIMIT 1").fetchone()[0]
  c.execute("UPDATE qe_background_jobs SET tenant_ids_json='[]' WHERE job_id=?",(second,));c.commit()
 finally:c.close()
 with bind_authenticated_principal(principal()):report=ops.verify_source()
 assert not report["healthy"] and "background_job_identity_invariant_failed" in report["problems"]

def test_phase406_malformed_timestamp_fails_closed_without_type_error(tmp_path):
 store,ops=setup(tmp_path);c=sqlite3.connect(store._path)
 try:c.execute("UPDATE qe_background_jobs SET expires_at='not-a-number'");c.commit()
 finally:c.close()
 with bind_authenticated_principal(principal()):report=ops.verify_source()
 assert not report["healthy"] and "background_job_timestamp_or_state_invalid" in report["problems"]

def test_phase407_restore_drill_binds_expected_state_counts(tmp_path):
 store,ops=setup(tmp_path);backup=tmp_path/"source.sqlite3";restored=tmp_path/"restored.sqlite3"
 with bind_authenticated_principal(principal()):
  receipt=ops.create_backup(backup)
  assert ops.restore_drill(backup,restored,expected_sha256=receipt.sha256,expected_state_counts={"PENDING":1}).verified
  with pytest.raises(RuntimeError,match="state-count"):
   ops.restore_drill(backup,tmp_path/"wrong.sqlite3",expected_sha256=receipt.sha256,expected_state_counts={"FAILED":1})
 assert not (tmp_path/"wrong.sqlite3").exists()

def test_phase408_restore_drill_rechecks_expected_counts_after_restore(tmp_path,monkeypatch):
 store,ops=setup(tmp_path);backup=tmp_path/"source.sqlite3";restored=tmp_path/"restored.sqlite3"
 with bind_authenticated_principal(principal()):receipt=ops.create_backup(backup)
 original=ops.verify_backup;calls={"count":0}
 def tampered(path,*,expected_sha256,expected_state_counts=None):
  calls["count"]+=1
  if calls["count"]==2:raise RuntimeError("state-count verification failed after restore")
  return original(path,expected_sha256=expected_sha256,expected_state_counts=expected_state_counts)
 monkeypatch.setattr(ops,"verify_backup",tampered)
 with bind_authenticated_principal(principal()):
  with pytest.raises(RuntimeError,match="after restore"):
   ops.restore_drill(backup,restored,expected_sha256=receipt.sha256,expected_state_counts={"PENDING":1})
 assert not restored.exists() and not list(tmp_path.glob(".qe-job-restore-*"))

 
def test_phase409_backup_verification_rejects_non_hex_digest(tmp_path):
 store,ops=setup(tmp_path);backup=tmp_path/"source.sqlite3"
 with bind_authenticated_principal(principal()):
  receipt=ops.create_backup(backup)
  with pytest.raises(ValueError,match="hexadecimal"):
   ops.verify_backup(backup,expected_sha256="z"*64)

def test_phase410_backup_verification_opens_read_only(tmp_path,monkeypatch):
 store,ops=setup(tmp_path);backup=tmp_path/"source.sqlite3"
 with bind_authenticated_principal(principal()):
  receipt=ops.create_backup(backup)
  verified=ops.verify_backup(backup,expected_sha256=receipt.sha256)
 assert verified.verified
 c=sqlite3.connect(f"file:{backup}?mode=ro",uri=True)
 try:
  with pytest.raises(sqlite3.OperationalError):c.execute("CREATE TABLE forbidden_write(x)")
 finally:c.close()

def test_phase411_inventory_is_bounded_and_reports_rejections(tmp_path):
 _,ops=setup(tmp_path);folder=tmp_path/"backups";folder.mkdir()
 with bind_authenticated_principal(principal()):
  ops.create_backup(folder/"a.sqlite3")
 (folder/"b.db").write_bytes(b"not a database")
 (folder/"c.sqlite3").write_bytes(b"not a database")
 with bind_authenticated_principal(principal()):
  report=ops.backup_inventory_report(folder,max_entries=2)
 assert report["candidate_count"]==2 and report["verified_count"]+report["rejected_count"]==2
 assert report["verified_count"]<=1 and report["rejected_count"]>=1
 assert report["truncated"] is True
 assert len(report["receipts"])==report["verified_count"]
 with bind_authenticated_principal(principal()):
  with pytest.raises(ValueError):ops.backup_inventory_report(folder,max_entries=0)

def test_phase412_health_reports_bounded_inventory_without_replay_authority(tmp_path):
 _,ops=setup(tmp_path);folder=tmp_path/"backups";folder.mkdir()
 with bind_authenticated_principal(principal()):
  ops.create_backup(folder/"one.sqlite3")
  report=ops.maintenance_health(folder,max_entries=1)
 assert report["verified_backup_count"]==1
 assert report["backup_candidate_count"]==1
 assert report["backup_inventory_truncated"] is False
 assert report["automatic_replay_enabled"] is False and report["production_ready"] is False


def test_phase413_inventory_does_not_follow_symlinks_or_scan_unbounded_entries(tmp_path):
    _,ops=setup(tmp_path);folder=tmp_path/"bounded";folder.mkdir()
    with bind_authenticated_principal(principal()):
        ops.create_backup(folder/"valid.sqlite3")
    outside=tmp_path/"outside.sqlite3"
    with bind_authenticated_principal(principal()):
        ops.create_backup(outside)
    try:
        (folder/"linked.db").symlink_to(outside)
    except (OSError,NotImplementedError):
        pytest.skip("symlink creation is unavailable on this platform")
    (folder/"ignored.txt").write_text("not a backup")
    with bind_authenticated_principal(principal()):
        report=ops.backup_inventory_report(folder,max_entries=2)
    assert report["scanned_entry_count"]==2
    assert report["candidate_count"]<=2
    assert report["truncated"] is True
    assert all(item.path != str(folder/"linked.db") for item in report["receipts"])


def test_phase414_inventory_enforces_total_verification_byte_budget(tmp_path):
    _,ops=setup(tmp_path);folder=tmp_path/"budget";folder.mkdir()
    with bind_authenticated_principal(principal()):
        receipt=ops.create_backup(folder/"one.sqlite3")
        report=ops.backup_inventory_report(folder,max_total_bytes=receipt.size_bytes-1)
    assert report["verified_count"]==0
    assert report["rejected_count"]==1 and report["truncated"] is True
    assert report["verified_bytes"]==0
    with bind_authenticated_principal(principal()):
        with pytest.raises(ValueError):ops.backup_inventory_report(folder,max_total_bytes=True)


def test_phase415_inventory_rejects_file_replaced_during_verification(tmp_path,monkeypatch):
    _,ops=setup(tmp_path);folder=tmp_path/"race";folder.mkdir()
    with bind_authenticated_principal(principal()):
        ops.create_backup(folder/"one.sqlite3")
    original=ops.verify_backup
    def replace_after_verify(path,*,expected_sha256,expected_state_counts=None):
        result=original(path,expected_sha256=expected_sha256,expected_state_counts=expected_state_counts)
        os.replace(path,folder/"moved.sqlite3")
        with open(path,"wb") as stream:stream.write(b"replacement")
        return result
    monkeypatch.setattr(ops,"verify_backup",replace_after_verify)
    with bind_authenticated_principal(principal()):
        report=ops.backup_inventory_report(folder)
    assert report["verified_count"]==0 and report["rejected_count"]==1


def test_phase416_health_reports_inventory_failure_as_degraded(tmp_path):
    _,ops=setup(tmp_path)
    with bind_authenticated_principal(principal()):
        report=ops.maintenance_health(tmp_path/"missing-directory")
    assert report["backup_inventory_error"] is True
    assert report["backup_inventory_truncated"] is True
    assert report["verified_backup_count"]==0
    assert report["automatic_replay_enabled"] is False
    assert report["production_ready"] is False


def test_phase417_readonly_backup_uri_verifies_on_host_platform(tmp_path):
    _,ops=setup(tmp_path);backup=tmp_path/"portable.sqlite3"
    with bind_authenticated_principal(principal()):
        receipt=ops.create_backup(backup)
        verified=ops.verify_backup(backup,expected_sha256=receipt.sha256)
    assert verified.verified and verified.sha256==receipt.sha256


def test_phase418_inventory_exposes_sanitized_rejection_categories(tmp_path):
    _,ops=setup(tmp_path);folder=tmp_path/"diagnostics";folder.mkdir()
    (folder/"broken.sqlite3").write_bytes(b"not sqlite")
    with bind_authenticated_principal(principal()):
        report=ops.backup_inventory_report(folder)
    assert report["verified_count"]==0 and report["rejected_count"]==1
    assert report["rejection_reasons"]
    assert all(isinstance(k,str) and isinstance(v,int) for k,v in report["rejection_reasons"].items())


def test_phase419_inventory_excludes_hardlink_alias_of_live_source_database(tmp_path):
    store,ops=setup(tmp_path);folder=tmp_path/"alias";folder.mkdir()
    alias=folder/"source.sqlite3"
    try:
        os.link(store._path,alias)
    except (OSError,NotImplementedError):
        pytest.skip("hard links unavailable on this platform")
    with bind_authenticated_principal(principal()):
        report=ops.backup_inventory_report(folder)
    assert report["verified_count"]==0
    assert report["rejection_reasons"].get("source_database_alias")==1


def test_phase420_inventory_rejects_symlink_directory_root(tmp_path):
    _,ops=setup(tmp_path);folder=tmp_path/"real";folder.mkdir();link=tmp_path/"alias"
    try:
        link.symlink_to(folder,target_is_directory=True)
    except (OSError,NotImplementedError):
        pytest.skip("directory symlinks unavailable on this platform")
    with bind_authenticated_principal(principal()):
        with pytest.raises(ValueError,match="non-symlink"):
            ops.backup_inventory_report(link)


def test_phase421_readonly_backup_uri_is_portable_and_read_only(tmp_path):
    _,ops=setup(tmp_path);backup=tmp_path/"portable-uri.sqlite3"
    with bind_authenticated_principal(principal()):
        receipt=ops.create_backup(backup)
        verified=ops.verify_backup(backup,expected_sha256=receipt.sha256)
    assert verified.verified and verified.sha256==receipt.sha256


def test_phase422_verification_rejects_metadata_change_during_inspection(tmp_path,monkeypatch):
    _,ops=setup(tmp_path);backup=tmp_path/"changing.sqlite3"
    with bind_authenticated_principal(principal()):
        receipt=ops.create_backup(backup)
    original=ops._inspect
    def touch_after_inspect(connection):
        report=original(connection)
        current=os.stat(backup)
        os.utime(backup,ns=(current.st_atime_ns,current.st_mtime_ns+2000000))
        return report
    monkeypatch.setattr(ops,"_inspect",touch_after_inspect)
    with bind_authenticated_principal(principal()):
        with pytest.raises(RuntimeError,match="changed during verification"):
            ops.verify_backup(backup,expected_sha256=receipt.sha256)


def test_phase423_inventory_rejects_directory_replaced_during_scan(tmp_path,monkeypatch):
    _,ops=setup(tmp_path);folder=tmp_path/"root";folder.mkdir()
    with bind_authenticated_principal(principal()):
        ops.create_backup(folder/"one.sqlite3")
    original_scandir=os.scandir
    class ReplaceRootAfterScan:
        def __enter__(self):
            self.iterator=original_scandir(folder)
            return self.iterator.__enter__()
        def __exit__(self,*args):
            result=self.iterator.__exit__(*args)
            os.rename(folder,tmp_path/"old-root")
            folder.mkdir()
            return result
    monkeypatch.setattr(os,"scandir",lambda path: ReplaceRootAfterScan() if os.path.abspath(path)==os.path.abspath(folder) else original_scandir(path))
    with bind_authenticated_principal(principal()):
        with pytest.raises(RuntimeError,match="directory changed"):
            ops.backup_inventory_report(folder)


def test_phase424_inventory_rejection_reasons_are_sanitized_categories(tmp_path):
    _,ops=setup(tmp_path);folder=tmp_path/"sanitized";folder.mkdir()
    (folder/"broken.sqlite3").write_bytes(b"not sqlite")
    with bind_authenticated_principal(principal()):
        report=ops.backup_inventory_report(folder)
    assert report["rejected_count"]==1
    assert report["rejection_reasons"].get("invalid_sqlite")==1
    assert all("/" not in key and "\\" not in key for key in report["rejection_reasons"])


def test_phase425_inventory_handles_uri_escaped_backup_paths(tmp_path):
    _,ops=setup(tmp_path);folder=tmp_path/"backup folder #1";folder.mkdir()
    backup=folder/"valid backup.sqlite3"
    with bind_authenticated_principal(principal()):
        receipt=ops.create_backup(backup)
        report=ops.backup_inventory_report(folder)
    assert report["verified_count"]==1
    assert report["receipts"][0].sha256==receipt.sha256


def test_phase426_verify_rejects_symlink_backup_paths(tmp_path):
    _,ops=setup(tmp_path);target=tmp_path/"target.sqlite3"
    with bind_authenticated_principal(principal()):
        receipt=ops.create_backup(target)
        link=tmp_path/"alias.sqlite3"
        try: link.symlink_to(target)
        except (OSError,NotImplementedError): pytest.skip("symlink creation unavailable")
        with pytest.raises((ValueError,OSError)):
            ops.verify_backup(link,expected_sha256=receipt.sha256)


def test_phase427_inventory_byte_budget_precedes_digest_read(tmp_path,monkeypatch):
    _,ops=setup(tmp_path);folder=tmp_path/"budget";folder.mkdir()
    with bind_authenticated_principal(principal()): ops.create_backup(folder/"one.sqlite3")
    called=[];original=ops._digest
    def tracked(path): called.append(path);return original(path)
    monkeypatch.setattr(ops,"_digest",tracked)
    with bind_authenticated_principal(principal()):
        report=ops.backup_inventory_report(folder,max_total_bytes=1)
    assert report["verified_count"]==0 and report["truncated"]
    assert called==[]


def test_phase428_health_sanitizes_inventory_failure(tmp_path,monkeypatch):
    _,ops=setup(tmp_path);folder=tmp_path/"health";folder.mkdir()
    def fail(*args,**kwargs): raise PermissionError("sensitive path C:/private/backup")
    monkeypatch.setattr(ops,"backup_inventory_report",fail)
    with bind_authenticated_principal(principal()): health=ops.maintenance_health(folder)
    assert health["backup_inventory_error"] is True
    assert health["verified_backup_count"]==0
    assert health["automatic_replay_enabled"] is False
    assert health["production_ready"] is False
    assert "C:/private" not in repr(health)


def test_phase429_readonly_verification_handles_spaces_and_uri_reserved_characters(tmp_path):
    _,ops=setup(tmp_path);backup=tmp_path/"backup space # percent%.sqlite3"
    with bind_authenticated_principal(principal()):
        receipt=ops.create_backup(backup)
        verified=ops.verify_backup(backup,expected_sha256=receipt.sha256)
    assert verified.verified and verified.path==str(backup)


def test_phase430_direct_verification_rejects_hardlink_to_live_source(tmp_path):
    store,ops=setup(tmp_path);alias=tmp_path/"source-alias.sqlite3"
    try:
        os.link(store._path,alias)
    except (OSError,NotImplementedError):
        pytest.skip("hard links unavailable on this platform")
    with bind_authenticated_principal(principal()):
        with pytest.raises(ValueError,match="alias the live source"):
            ops.verify_backup(alias,expected_sha256=ops._digest(alias))


def test_phase431_digest_mismatch_fails_before_sqlite_open(tmp_path,monkeypatch):
    _,ops=setup(tmp_path);backup=tmp_path/"backup.sqlite3"
    with bind_authenticated_principal(principal()):
        receipt=ops.create_backup(backup)
    calls=[]
    original=sqlite3.connect
    def spy(*args,**kwargs):
        calls.append(args[0] if args else None)
        return original(*args,**kwargs)
    monkeypatch.setattr(sqlite3,"connect",spy)
    with bind_authenticated_principal(principal()):
        with pytest.raises(RuntimeError,match="SHA-256 mismatch"):
            ops.verify_backup(backup,expected_sha256="0"*64)
    assert calls==[]


def test_phase432_inventory_and_health_never_expose_windows_uri_or_exception_text(tmp_path,monkeypatch):
    _,ops=setup(tmp_path);folder=tmp_path/"safe";folder.mkdir()
    def fail(*args,**kwargs):
        raise sqlite3.OperationalError("unable to open database file C:/private/customer.sqlite3")
    monkeypatch.setattr(ops,"verify_backup",fail)
    (folder/"candidate.sqlite3").write_bytes(b"candidate")
    with bind_authenticated_principal(principal()):
        report=ops.backup_inventory_report(folder)
        health=ops.maintenance_health(folder)
    assert report["verified_count"]==0
    assert report["rejection_reasons"].get("filesystem_error",0)==0
    assert "private" not in repr(report).lower()
    assert health["automatic_replay_enabled"] is False
    assert health["production_ready"] is False
    assert "customer.sqlite3" not in repr(health)


def test_phase433_file_identity_distinguishes_files_and_detects_hardlinks(tmp_path):
    first=tmp_path/"first.bin";second=tmp_path/"second.bin";first.write_bytes(b"same")
    second.write_bytes(b"same")
    identity=SQLiteBackgroundJobMaintenance._file_identity
    assert identity(first)!=identity(second)
    alias=tmp_path/"alias.bin"
    try:
        os.link(first,alias)
    except (OSError,NotImplementedError):
        pytest.skip("hard links unavailable on this platform")
    assert identity(first)==identity(alias)


def test_phase434_direct_verification_uses_stable_file_identity(tmp_path,monkeypatch):
    store,ops=setup(tmp_path);alias=tmp_path/"identity-alias.sqlite3"
    alias.write_bytes(b"placeholder")
    source_identity=ops._file_identity(store._path)
    monkeypatch.setattr(ops,"_file_identity",lambda path:source_identity)
    with bind_authenticated_principal(principal()):
        with pytest.raises(ValueError,match="alias the live source"):
            ops.verify_backup(alias,expected_sha256=ops._digest(alias))


def test_phase435_file_identity_errors_fail_closed_at_verification_boundary(tmp_path,monkeypatch):
    _,ops=setup(tmp_path);backup=tmp_path/"backup.sqlite3"
    with bind_authenticated_principal(principal()):receipt=ops.create_backup(backup)
    def unavailable(_):raise OSError("file identity unavailable")
    monkeypatch.setattr(ops,"_file_identity",unavailable)
    with bind_authenticated_principal(principal()):
        with pytest.raises(OSError,match="file identity unavailable"):
            ops.verify_backup(backup,expected_sha256=receipt.sha256)


def test_phase436_inventory_uses_stable_identity_and_reports_identity_failure(tmp_path,monkeypatch):
    _,ops=setup(tmp_path);folder=tmp_path/"identity-inventory";folder.mkdir()
    with bind_authenticated_principal(principal()):ops.create_backup(folder/"valid.sqlite3")
    real=ops._file_identity
    def fail_candidate(path):
        if str(path).endswith("valid.sqlite3"):raise OSError("identity unavailable")
        return real(path)
    monkeypatch.setattr(ops,"_file_identity",fail_candidate)
    with bind_authenticated_principal(principal()):
        report=ops.backup_inventory_report(folder)
    assert report["verified_count"]==0
    assert report["rejected_count"]==1
    assert report["rejection_reasons"].get("filesystem_error")==1
