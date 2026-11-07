"""Owner-only inspection and non-replaying review of ambiguous background jobs."""
from dataclasses import dataclass
import hashlib,json,math
from core.accounts.request_tenant_authorization import AuthenticatedPrincipal
@dataclass(frozen=True,slots=True)
class BackgroundJobReview:
    sequence:int; job_id:str; tenant_id:str; actor_id:str; disposition:str; reason:str; occurred_at:float; previous_hash:str; event_hash:str
class SQLiteBackgroundJobOperations:
    production_ready=False
    dispositions=frozenset({"NO_EXTERNAL_EFFECT","EXTERNAL_EFFECT_CONFIRMED","OUTCOME_UNKNOWN"})
    def __init__(self,store,*,principal_source,owner_authorizer,clock):
        if not callable(getattr(store,"_connect",None)) or not callable(getattr(principal_source,"current_principal",None)) or not callable(owner_authorizer) or not callable(clock):raise ValueError("trusted dependencies required")
        self.store,self.source,self.authorize,self.clock=store,principal_source,owner_authorizer,clock
        c=store._connect()
        try:
            c.execute("""CREATE TABLE IF NOT EXISTS qe_background_job_reviews(sequence INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,tenant_id TEXT NOT NULL,actor_id TEXT NOT NULL,disposition TEXT NOT NULL CHECK(disposition IN ('NO_EXTERNAL_EFFECT','EXTERNAL_EFFECT_CONFIRMED','OUTCOME_UNKNOWN')),reason TEXT NOT NULL,occurred_at REAL NOT NULL,previous_hash TEXT NOT NULL,event_hash TEXT NOT NULL UNIQUE)""")
            c.execute("CREATE TRIGGER IF NOT EXISTS qe_job_review_no_update BEFORE UPDATE ON qe_background_job_reviews BEGIN SELECT RAISE(ABORT,'immutable audit'); END")
            c.execute("CREATE TRIGGER IF NOT EXISTS qe_job_review_no_delete BEFORE DELETE ON qe_background_job_reviews BEGIN SELECT RAISE(ABORT,'immutable audit'); END")
        finally:c.close()
    def _owner(self):
        p=self.source.current_principal()
        if not isinstance(p,AuthenticatedPrincipal) or self.authorize(p) is not True:raise PermissionError("owner authorization required")
        return p
    def inspect(self,job_id):
        self._owner()
        if not isinstance(job_id,str) or not job_id.strip() or len(job_id)>256:return None
        c=self.store._connect()
        try:
            r=c.execute("SELECT job_id,tenant_id,subject_id,state,created_at,claimed_at,finished_at,expires_at FROM qe_background_jobs WHERE job_id=?",(job_id,)).fetchone()
            return dict(zip(("job_id","tenant_id","subject_id","state","created_at","claimed_at","finished_at","expires_at"),r)) if r else None
        finally:c.close()
    def stale_running(self,*,before_epoch,limit=100):
        self._owner()
        if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=500:raise ValueError("limit must be 1..500")
        if isinstance(before_epoch,bool) or not isinstance(before_epoch,(int,float)) or not math.isfinite(before_epoch):raise ValueError("finite cutoff required")
        c=self.store._connect()
        try:
            rows=c.execute("SELECT job_id,tenant_id,subject_id,state,created_at,claimed_at,expires_at FROM qe_background_jobs WHERE state='RUNNING' AND claimed_at<=? ORDER BY claimed_at,job_id LIMIT ?",(float(before_epoch),limit)).fetchall()
            keys=("job_id","tenant_id","subject_id","state","created_at","claimed_at","expires_at")
            return tuple(dict(zip(keys,r)) for r in rows)
        finally:c.close()
    def review_running(self,job_id,*,disposition,reason):
        actor=self._owner()
        if not isinstance(job_id,str) or not job_id.strip() or len(job_id)>256:raise ValueError("valid job ID required")
        if disposition not in self.dispositions:raise ValueError("invalid disposition")
        if not isinstance(reason,str) or not reason.strip() or len(reason)>1000:raise ValueError("bounded reason required")
        now=self.clock()
        if isinstance(now,bool) or not isinstance(now,(int,float)) or not math.isfinite(now):raise RuntimeError("clock unavailable")
        c=self.store._connect()
        try:
            c.execute("BEGIN IMMEDIATE");job=c.execute("SELECT tenant_id,state FROM qe_background_jobs WHERE job_id=?",(job_id,)).fetchone()
            if job is None or job[1]!="RUNNING":raise ValueError("only RUNNING jobs can be reviewed")
            last=c.execute("SELECT event_hash FROM qe_background_job_reviews ORDER BY sequence DESC LIMIT 1").fetchone();prev=last[0] if last else "0"*64
            data={"job_id":job_id,"tenant_id":job[0],"actor_id":actor.subject_id,"disposition":disposition,"reason":reason.strip(),"occurred_at":float(now),"previous_hash":prev}
            digest=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
            cur=c.execute("INSERT INTO qe_background_job_reviews(job_id,tenant_id,actor_id,disposition,reason,occurred_at,previous_hash,event_hash) VALUES(?,?,?,?,?,?,?,?)",(job_id,job[0],actor.subject_id,disposition,reason.strip(),float(now),prev,digest))
            seq=cur.lastrowid;c.execute("COMMIT")
            return BackgroundJobReview(seq,job_id,job[0],actor.subject_id,disposition,reason.strip(),float(now),prev,digest)
        except Exception:
            if c.in_transaction:c.execute("ROLLBACK")
            raise
        finally:c.close()
    def health_snapshot(self,*,stale_before_epoch,limit=100,require_valid_audit=True):
        """Owner-only diagnostic snapshot; never mutates or replays queue work."""
        self._owner()
        if not isinstance(require_valid_audit,bool):raise ValueError("audit requirement must be boolean")
        stale=self.stale_running(before_epoch=stale_before_epoch,limit=limit)
        c=self.store._connect()
        try:
            rows=c.execute("SELECT state,COUNT(*) FROM qe_background_jobs GROUP BY state").fetchall()
        finally:c.close()
        counts={state:count for state,count in rows}
        for state in ("PENDING","RUNNING","SUCCEEDED","FAILED","EXPIRED"):
            counts.setdefault(state,0)
        audit_valid=self.audit_chain_valid()
        if require_valid_audit and not audit_valid:
            raise RuntimeError("background job audit integrity check failed")
        return {
            "counts":counts,
            "stale_running":tuple({"job_id":r["job_id"],"claimed_at":r["claimed_at"],"expires_at":r["expires_at"]} for r in stale),
            "audit_chain_valid":audit_valid,
            "automatic_replay_enabled":False,
            "production_ready":False,
        }
    def audit_chain_valid(self):
        self._owner();c=self.store._connect()
        try:rows=c.execute("SELECT sequence,job_id,tenant_id,actor_id,disposition,reason,occurred_at,previous_hash,event_hash FROM qe_background_job_reviews ORDER BY sequence").fetchall()
        finally:c.close()
        prev="0"*64
        for n,r in enumerate(rows,1):
            seq,j,t,a,d,reason,when,prior,digest=r
            data={"job_id":j,"tenant_id":t,"actor_id":a,"disposition":d,"reason":reason,"occurred_at":when,"previous_hash":prior}
            if seq!=n or prior!=prev or hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()!=digest:return False
            prev=digest
        return True
