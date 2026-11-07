"""Owner-only integrity verification and atomic backup/restore drills for the local job queue."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib,hmac,os,sqlite3,tempfile
from core.accounts.request_tenant_authorization import AuthenticatedPrincipal
_REQUIRED=frozenset({"job_id","tenant_id","subject_id","session_id","tenant_ids_json","principal_expires_at","expires_at","created_at","claimed_at","finished_at","state"})
@dataclass(frozen=True,slots=True)
class SQLiteBackupReceipt:
    path:str
    sha256:str
    size_bytes:int
    verified:bool
class SQLiteBackgroundJobMaintenance:
    """Single-host SQLite maintenance; never changes job state or authorizes replay."""
    production_ready=False
    def __init__(self,store,*,principal_source,owner_authorizer):
        if not callable(getattr(store,"_connect",None)) or not callable(getattr(principal_source,"current_principal",None)) or not callable(owner_authorizer):raise ValueError("trusted maintenance dependencies required")
        self._store,self._source,self._authorize=store,principal_source,owner_authorizer
    def _owner(self):
        p=self._source.current_principal()
        if not isinstance(p,AuthenticatedPrincipal) or self._authorize(p) is not True:raise PermissionError("owner authorization required")
        return p
    @staticmethod
    def _inspect(c):
        problems=[]
        try:quick=tuple(r[0] for r in c.execute("PRAGMA quick_check").fetchall())
        except sqlite3.DatabaseError:quick=("quick_check failed",)
        if quick!=("ok",):problems.append("sqlite_integrity_check_failed")
        try:
            columns=frozenset(r[1] for r in c.execute("PRAGMA table_info(qe_background_jobs)").fetchall())
            if not _REQUIRED.issubset(columns):problems.append("background_job_schema_incomplete")
            indexes={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
            if "qe_background_jobs_state_expiry" not in indexes:problems.append("background_job_index_missing")
            counts={r[0]:r[1] for r in c.execute("SELECT state,COUNT(*) FROM qe_background_jobs GROUP BY state").fetchall()}
        except sqlite3.DatabaseError:
            problems.append("background_job_schema_unreadable");counts={}
        semantic=[]
        if "background_job_schema_incomplete" not in problems:
            try:
                import math
                rows=c.execute("SELECT state,created_at,claimed_at,finished_at,expires_at,tenant_id,subject_id,session_id,tenant_ids_json,principal_expires_at FROM qe_background_jobs").fetchall()
                allowed={"PENDING","RUNNING","SUCCEEDED","FAILED","EXPIRED"}
                for state,created,claimed,finished,expires,tenant,subject,session,tenant_json,principal_expiry in rows:
                    values=(created,expires,principal_expiry)+(() if claimed is None else (claimed,))+(() if finished is None else (finished,))
                    if state not in allowed or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):
                        semantic.append("background_job_timestamp_or_state_invalid");break
                    try:
                        tenant_ids=__import__("json").loads(tenant_json)
                        valid_identity=(isinstance(tenant,str) and bool(tenant.strip()) and isinstance(subject,str) and bool(subject.strip())
                            and isinstance(session,str) and bool(session.strip()) and isinstance(tenant_ids,list)
                            and all(isinstance(item,str) and item.strip() for item in tenant_ids)
                            and tenant_ids==sorted(set(tenant_ids)) and tenant in tenant_ids
                            and expires<=principal_expiry)
                    except (TypeError,ValueError):
                        valid_identity=False
                    if not valid_identity:
                        semantic.append("background_job_identity_invariant_failed");break
                    if expires<created or (claimed is not None and claimed<created) or (finished is not None and ((claimed is not None and finished<claimed) or finished<created)):
                        semantic.append("background_job_timeline_invalid");break
                    if (state=="PENDING" and (claimed is not None or finished is not None)) or (state=="RUNNING" and (claimed is None or finished is not None)) or (state in {"SUCCEEDED","FAILED","EXPIRED"} and finished is None):
                        semantic.append("background_job_state_timestamp_mismatch");break
            except sqlite3.DatabaseError: semantic.append("background_job_semantics_unreadable")
        problems.extend(semantic)
        return {"healthy":not problems,"quick_check":quick,"problems":tuple(problems),"state_counts":counts,"semantic_valid":not semantic}
    def verify_source(self):
        """393: read-only SQLite quick-check, required schema/index and state counts."""
        self._owner();c=self._store._connect()
        try:return self._inspect(c)
        finally:c.close()
    @staticmethod
    def _safe_destination(destination,source):
        if not isinstance(destination,(str,os.PathLike)):raise ValueError("destination path required")
        target=os.path.abspath(os.fspath(destination))
        if os.path.normcase(target)==os.path.normcase(os.path.abspath(source)):raise ValueError("destination must differ from source")
        parent=os.path.dirname(target)
        if not os.path.isdir(parent):raise ValueError("destination parent directory must exist")
        if os.path.islink(parent):raise ValueError("destination parent must not be a symlink")
        if os.path.lexists(target):raise FileExistsError("destination already exists")
        return target
    @staticmethod
    def _digest(path):
        h=hashlib.sha256()
        with open(path,"rb") as f:
            for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
        return h.hexdigest()
    def create_backup(self,destination):
        """394: online SQLite snapshot, verify, fsync and atomic no-clobber publication."""
        self._owner();target=self._safe_destination(destination,self._store._path)
        fd,temp=tempfile.mkstemp(prefix=".qe-job-backup-",dir=os.path.dirname(target));os.close(fd)
        try:
            source=self._store._connect();snapshot=sqlite3.connect(temp,isolation_level=None)
            try:source.backup(snapshot)
            finally:snapshot.close();source.close()
            with open(temp,"rb+") as f:os.fsync(f.fileno())
            c=sqlite3.connect(temp)
            try:report=self._inspect(c)
            finally:c.close()
            if not report["healthy"]:raise RuntimeError("backup integrity verification failed")
            os.link(temp,target);os.unlink(temp)
            if os.name!="nt":
                d=os.open(os.path.dirname(target),os.O_RDONLY)
                try:os.fsync(d)
                finally:os.close(d)
            return SQLiteBackupReceipt(target,self._digest(target),os.path.getsize(target),True)
        finally:
            if os.path.exists(temp):os.unlink(temp)
    def verify_backup(self,backup_path,*,expected_sha256,expected_state_counts=None):
        """395: verify backup digest and its SQLite integrity/schema before use."""
        self._owner()
        if not isinstance(backup_path,(str,os.PathLike)) or not isinstance(expected_sha256,str) or len(expected_sha256)!=64:raise ValueError("backup path and SHA-256 digest required")
        path=os.path.abspath(os.fspath(backup_path))
        if os.path.islink(path) or not os.path.isfile(path):raise ValueError("backup must be a regular non-symlink file")
        actual=self._digest(path)
        if not hmac.compare_digest(actual,expected_sha256.lower()):raise RuntimeError("backup SHA-256 mismatch")
        c=sqlite3.connect(path)
        try:report=self._inspect(c)
        finally:c.close()
        if not report["healthy"]:raise RuntimeError("backup integrity verification failed")
        if expected_state_counts is not None:
            if not isinstance(expected_state_counts,dict) or any(not isinstance(k,str) or isinstance(v,bool) or not isinstance(v,int) or v<0 for k,v in expected_state_counts.items()):
                raise ValueError("expected state counts must be a non-negative integer mapping")
            if report["state_counts"]!=expected_state_counts:raise RuntimeError("backup state-count verification failed")
        return SQLiteBackupReceipt(path,actual,os.path.getsize(path),True)
    def restore_drill(self,backup_path,destination,*,expected_sha256,expected_state_counts=None)
        """396: SQLite restore into an isolated temp DB, then atomic no-clobber publication."""
        self._owner()
        source_receipt=self.verify_backup(backup_path,expected_sha256=expected_sha256,expected_state_counts=expected_state_counts)
        target=self._safe_destination(destination,self._store._path)
        if os.path.normcase(target)==os.path.normcase(source_receipt.path):
            raise ValueError("restore destination must differ from backup")
        fd,temp=tempfile.mkstemp(prefix=".qe-job-restore-",dir=os.path.dirname(target))
        os.close(fd)
        try:
            source=sqlite3.connect(source_receipt.path)
            restored=sqlite3.connect(temp,isolation_level=None)
            try:
                source.backup(restored)
            finally:
                restored.close()
                source.close()
            with open(temp,"rb+") as stream:
                os.fsync(stream.fileno())
            check=sqlite3.connect(temp)
            try:
                report=self._inspect(check)
            finally:
                check.close()
            if not report["healthy"]:
                raise RuntimeError("restored database integrity verification failed")
            os.link(temp,target)
            os.unlink(temp)
            if os.name!="nt":
                directory_fd=os.open(os.path.dirname(target),os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            digest=self._digest(target)
            return self.verify_backup(target,expected_sha256=digest,expected_state_counts=expected_state_counts)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def backup_inventory(self,directory):
        """398: owner-only inventory of verified SQLite backup files."""
        self._owner()
        if not isinstance(directory,(str,os.PathLike)): raise ValueError("backup directory required")
        root=os.path.abspath(os.fspath(directory))
        if os.path.islink(root) or not os.path.isdir(root): raise ValueError("backup directory must be a regular directory")
        results=[]
        for name in sorted(os.listdir(root)):
            path=os.path.join(root,name)
            if not name.lower().endswith((".sqlite3",".db")) or os.path.islink(path) or not os.path.isfile(path): continue
            try: results.append(self.verify_backup(path,expected_sha256=self._digest(path)))
            except (OSError,RuntimeError,ValueError,sqlite3.DatabaseError): continue
        return tuple(results)

    def maintenance_health(self,directory):
        """399: owner-only bounded maintenance health summary."""
        self._owner()
        source=self.verify_source();backups=self.backup_inventory(directory)
        return {"source_healthy":source["healthy"],"source_state_counts":source["state_counts"],
                "verified_backup_count":len(backups),"verified_backup_bytes":sum(x.size_bytes for x in backups),
                "automatic_replay_enabled":False,"production_ready":False}
