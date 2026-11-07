"""Phase 365 PostgreSQL owner-governance repository.

The transaction-local tenant GUC is caller-settable; this adapter does not yet
provide database-authenticated tenant isolation.
"""
from __future__ import annotations
from contextlib import contextmanager
import hashlib, json, uuid
from typing import Iterator
from core.accounts.owner_governance import CredentialApproval, GovernanceConflictError, Membership

class PostgreSQLOwnerGovernanceRepository:
    """Persistence only; RLS context is not a database-authenticated identity."""
    production_ready = False
    durable_shared_storage = True
    tenant_isolation_enforced = False
    def __init__(self, dsn: str, *, connect_timeout: int = 5):
        if not isinstance(dsn,str) or not dsn.strip(): raise ValueError("PostgreSQL DSN is required")
        if isinstance(connect_timeout,bool) or not isinstance(connect_timeout,int) or not 1 <= connect_timeout <= 60: raise ValueError("invalid connect_timeout")
        self._dsn,self._connect_timeout=dsn,connect_timeout
    @contextmanager
    def _connection(self,tenant:str)->Iterator[object]:
        if not isinstance(tenant,str) or not tenant.strip() or len(tenant)>128: raise ValueError("invalid tenant_id")
        try:
            import psycopg
            from psycopg.rows import dict_row
            with psycopg.connect(self._dsn,connect_timeout=self._connect_timeout,row_factory=dict_row) as conn:
                with conn.transaction():
                    conn.execute("SELECT set_config('quantengine.tenant_id',%s,true)",(tenant,))
                    yield conn
        except (ValueError,GovernanceConflictError,PermissionError): raise
        except Exception: raise RuntimeError("PostgreSQL owner-governance operation failed") from None
    @staticmethod
    def _audit(conn,tenant,actor,action,target,now):
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",(tenant,))
        row=conn.execute("SELECT event_hash FROM public.qe_governance_audit WHERE tenant_id=%s ORDER BY occurred_at_ns DESC,event_id DESC LIMIT 1",(tenant,)).fetchone()
        previous=row["event_hash"] if row else "0"*64
        event=str(uuid.uuid4())
        payload=json.dumps([event,tenant,actor,action,target,now,previous],separators=(",",":"),ensure_ascii=False)
        digest=hashlib.sha256(payload.encode()).hexdigest()
        conn.execute("INSERT INTO public.qe_governance_audit VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",(event,tenant,actor,action,target,now,previous,digest))
    def invite(self,tenant,subject,permissions,actor,now):
        with self._connection(tenant) as c:
            c.execute("INSERT INTO public.qe_memberships VALUES(%s,%s,'PENDING',%s::jsonb,%s,%s)",(tenant,subject,json.dumps(sorted(permissions)),now,now))
            self._audit(c,tenant,actor,"MEMBER_INVITED",subject,now)
    def decide_membership(self,tenant,subject,status,permissions,actor,now):
        with self._connection(tenant) as c:
            cur=c.execute("UPDATE public.qe_memberships SET status=%s,permissions_json=%s::jsonb,updated_at_ns=%s WHERE tenant_id=%s AND subject_id=%s AND status='PENDING'",(status,json.dumps(sorted(permissions)),now,tenant,subject))
            if cur.rowcount!=1: raise GovernanceConflictError("membership is not pending")
            self._audit(c,tenant,actor,"MEMBERSHIP_"+status,subject,now)
    def membership(self,tenant,subject):
        with self._connection(tenant) as c: row=c.execute("SELECT * FROM public.qe_memberships WHERE tenant_id=%s AND subject_id=%s",(tenant,subject)).fetchone()
        if row is None:return None
        return Membership(row["tenant_id"],row["subject_id"],row["status"],tuple(row["permissions_json"]),row["created_at_ns"],row["updated_at_ns"])
    def submit_credential(self,tenant,credential,subject,account,fingerprint,now):
        with self._connection(tenant) as c:
            c.execute("INSERT INTO public.qe_credential_approvals VALUES(%s,%s,%s,%s,%s,'PENDING',%s,%s)",(tenant,credential,subject,account,fingerprint,now,now))
            self._audit(c,tenant,subject,"CREDENTIAL_SUBMITTED",credential,now)
    def decide_credential(self,tenant,credential,status,actor,now):
        with self._connection(tenant) as c:
            cur=c.execute("UPDATE public.qe_credential_approvals SET status=%s,updated_at_ns=%s WHERE tenant_id=%s AND credential_id=%s AND status='PENDING'",(status,now,tenant,credential))
            if cur.rowcount!=1:raise GovernanceConflictError("credential is not pending")
            self._audit(c,tenant,actor,"CREDENTIAL_"+status,credential,now)
    def credential(self,tenant,credential):
        with self._connection(tenant) as c: row=c.execute("SELECT * FROM public.qe_credential_approvals WHERE tenant_id=%s AND credential_id=%s",(tenant,credential)).fetchone()
        if row is None:return None
        return CredentialApproval(row["tenant_id"],row["credential_id"],row["subject_id"],row["account_id"],row["fingerprint"],row["status"],row["created_at_ns"],row["updated_at_ns"])
    def credentials_for_account_fingerprint(self,tenant,account,fingerprint):
        """Return every exact credential tuple match; callers must reject ambiguity."""
        with self._connection(tenant) as c:
            rows=c.execute(
                "SELECT * FROM public.qe_credential_approvals "
                "WHERE tenant_id=%s AND account_id=%s AND fingerprint=%s ORDER BY credential_id",
                (tenant,account,fingerprint),
            ).fetchall()
        return [CredentialApproval(row["tenant_id"],row["credential_id"],row["subject_id"],
            row["account_id"],row["fingerprint"],row["status"],row["created_at_ns"],row["updated_at_ns"])
            for row in rows]
    def audit_events(self,tenant):
        with self._connection(tenant) as c: rows=c.execute("SELECT * FROM public.qe_governance_audit WHERE tenant_id=%s ORDER BY occurred_at_ns,event_id",(tenant,)).fetchall()
        return [dict(row) for row in rows]
