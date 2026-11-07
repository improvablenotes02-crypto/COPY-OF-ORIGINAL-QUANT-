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
        return {"healthy":not problems,"quick_check":quick,"problems":tuple(problems),"state_counts":counts}
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
    def verify_backup(self,backup_path,*,expected_sha256):
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
        return SQLiteBackupReceipt(path,actual,os.path.getsize(path),True)
    def restore_drill(self,backup_path,destination,*,expected_sha256):
        """396: SQLite restore into an isolated temp DB, then atomic no-clobber publication."""
        self._owner()
        source_receipt=self.verify_backup(backup_path,expected_sha256=expected_sha256)
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
            return self.verify_backup(target,expected_sha256=digest)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
