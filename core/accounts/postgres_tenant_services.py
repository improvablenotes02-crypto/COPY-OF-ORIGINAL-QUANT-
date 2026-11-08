"""Trusted construction and execution boundaries for tenant-scoped services.

The DSN resolver must be created from server-controlled deployment configuration.
Never derive database role names, DSNs, or tenant mappings from request data.
"""
from __future__ import annotations

from typing import Callable, Protocol
from dataclasses import dataclass
import json
import math
import os
import secrets
import sqlite3
import time

from core.accounts.delta_account_registry import AccountScopeError
from core.accounts.oidc_tenant_principal import AuthenticatedPrincipal
from core.accounts.postgres_delta_account_repository import AuthenticatedPostgreSQLDeltaAccountRepository
from core.accounts.postgres_owner_governance_repository import (
    AuthenticatedPostgreSQLOwnerGovernanceRepository,
)
from core.accounts.request_tenant_authorization import (
    RequestScopedTenantAuthorizer,
    TrustedPrincipalSource,
    SessionStatusValidator,
)


class TenantDeltaAccountRepository:
    """Tenant-authorized facade; database identity is independently checked below."""
    production_ready = False
    durable_shared_storage = True
    tenant_isolation_enforced = True

    def __init__(self, repository, authorizer):
        self._repository = repository
        self._authorizer = authorizer

    def _require_tenant(self, tenant_id: str) -> None:
        if self._authorizer.authorize_tenant(tenant_id) is not True:
            raise AccountScopeError("tenant is not authorized for this operation")

    def save(self, record):
        self._require_tenant(record.tenant_id)
        return self._repository.save(record)

    def get(self, tenant_id, account_id):
        self._require_tenant(tenant_id)
        return self._repository.get(tenant_id, account_id)

    def list_for_tenant(self, tenant_id):
        self._require_tenant(tenant_id)
        return self._repository.list_for_tenant(tenant_id)

    def delete(self, tenant_id, account_id):
        self._require_tenant(tenant_id)
        return self._repository.delete(tenant_id, account_id)

    def bind_provider_identity(self, tenant_id, account_id, provider_account_id):
        self._require_tenant(tenant_id)
        return self._repository.bind_provider_identity(tenant_id, account_id, provider_account_id)

    def replace_credentials(self, record, *, expected_generation, expected_updated_at_ns):
        self._require_tenant(record.tenant_id)
        return self._repository.replace_credentials(
            record, expected_generation=expected_generation,
            expected_updated_at_ns=expected_updated_at_ns,
        )

    def list_credential_rotation_events(self, tenant_id, account_id):
        self._require_tenant(tenant_id)
        return self._repository.list_credential_rotation_events(tenant_id, account_id)


class TenantGovernanceRepository:
    """Tenant-authorized facade over owner-governance persistence.

    This enforces tenant membership, not owner permissions. The governance
    domain service must still enforce owner-only decisions and audit semantics.
    """
    production_ready = False

    def __init__(self, repository, authorizer):
        self._repository = repository
        self._authorizer = authorizer

    def _require_tenant(self, tenant_id: str) -> None:
        if self._authorizer.authorize_tenant(tenant_id) is not True:
            raise AccountScopeError("tenant is not authorized for this operation")

    def invite(self, tenant, *args, **kwargs):
        self._require_tenant(tenant)
        return self._repository.invite(tenant, *args, **kwargs)

    def decide_membership(self, tenant, *args, **kwargs):
        self._require_tenant(tenant)
        return self._repository.decide_membership(tenant, *args, **kwargs)

    def membership(self, tenant, *args, **kwargs):
        self._require_tenant(tenant)
        return self._repository.membership(tenant, *args, **kwargs)

    def list_members(self, tenant):
        self._require_tenant(tenant)
        return self._repository.list_members(tenant)

    def list_credentials(self, tenant):
        self._require_tenant(tenant)
        return self._repository.list_credentials(tenant)

    def submit_credential(self, tenant, *args, **kwargs):
        self._require_tenant(tenant)
        return self._repository.submit_credential(tenant, *args, **kwargs)

    def decide_credential(self, tenant, *args, **kwargs):
        self._require_tenant(tenant)
        return self._repository.decide_credential(tenant, *args, **kwargs)

    def credential(self, tenant, *args, **kwargs):
        self._require_tenant(tenant)
        return self._repository.credential(tenant, *args, **kwargs)

    def revoke_credential(self, tenant, *args, **kwargs):
        self._require_tenant(tenant)
        return self._repository.revoke_credential(tenant, *args, **kwargs)

    def credentials_for_account_fingerprint(self, tenant, *args, **kwargs):
        self._require_tenant(tenant)
        return self._repository.credentials_for_account_fingerprint(tenant, *args, **kwargs)

    def audit_events(self, tenant, *args, **kwargs):
        self._require_tenant(tenant)
        return self._repository.audit_events(tenant, *args, **kwargs)


class AuthenticatedTenantRepositoryFactory:
    """Build repositories only with trusted, server-configured tenant routing."""

    production_ready = False

    def __init__(
        self,
        *,
        principal_source: TrustedPrincipalSource,
        session_validator: SessionStatusValidator,
        tenant_dsn_resolver: Callable[[str], str],
        connect_timeout: int = 5,
    ):
        if not callable(tenant_dsn_resolver):
            raise ValueError("server-configured tenant DSN resolver is required")
        self._resolver = tenant_dsn_resolver
        self._timeout = connect_timeout
        self._authorizer = RequestScopedTenantAuthorizer(
            principal_source, session_validator
        )

    @property
    def tenant_authorizer(self):
        return self._authorizer

    def delta_repository(self):
        persistence = AuthenticatedPostgreSQLDeltaAccountRepository(
            self._resolver, connect_timeout=self._timeout
        )
        return TenantDeltaAccountRepository(persistence, self._authorizer)

    def _governance_persistence(self):
        return AuthenticatedPostgreSQLOwnerGovernanceRepository(
            self._resolver, connect_timeout=self._timeout
        )

    def governance_repository(self):
        return TenantGovernanceRepository(
            self._governance_persistence(), self._authorizer
        )


@dataclass(frozen=True, slots=True)
class BackgroundJobEnvelope:
    job_id: str
    tenant_id: str
    principal: AuthenticatedPrincipal
    expires_at_epoch: float


class TrustedBackgroundJobStore(Protocol):
    production_ready: bool
    def enqueue(self, principal: AuthenticatedPrincipal, tenant_id: str, *, ttl_seconds: float = 300.0) -> str: ...
    def claim_job(self, job_id: str) -> BackgroundJobEnvelope | None: ...
    def finish_job(self, job_id: str, *, success: bool) -> None: ...


class SQLiteBackgroundJobStore:
    """Single-host durable queue; crashed RUNNING jobs are never auto-replayed."""
    production_ready = False

    def __init__(self, database_path: str, *, clock: Callable[[], float] = time.time, busy_timeout_ms: int = 5000):
        if not isinstance(database_path, str) or not database_path.strip() or database_path == ":memory:":
            raise ValueError("a durable background job database path is required")
        if isinstance(busy_timeout_ms, bool) or not isinstance(busy_timeout_ms, int) or not 1 <= busy_timeout_ms <= 60000:
            raise ValueError("busy timeout must be between 1 and 60000 milliseconds")
        self._path = os.path.abspath(database_path)
        if os.path.islink(self._path) or (os.path.exists(self._path) and not os.path.isfile(self._path)):
            raise ValueError("background job database must be a regular non-symlink file")
        if not os.path.isdir(os.path.dirname(self._path)):
            raise ValueError("background job database parent directory must exist")
        self._clock, self._timeout = clock, busy_timeout_ms
        con = self._connect()
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("""CREATE TABLE IF NOT EXISTS qe_background_jobs (
                job_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, subject_id TEXT NOT NULL,
                session_id TEXT NOT NULL, tenant_ids_json TEXT NOT NULL,
                principal_expires_at REAL NOT NULL, expires_at REAL NOT NULL,
                created_at REAL NOT NULL, claimed_at REAL, finished_at REAL,
                state TEXT NOT NULL CHECK(state IN
                ('PENDING','RUNNING','SUCCEEDED','FAILED','EXPIRED')))""")
            con.execute("CREATE INDEX IF NOT EXISTS qe_background_jobs_state_expiry ON qe_background_jobs(state,expires_at)")
        finally:
            con.close()
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            if os.name != "nt": raise

    def _connect(self):
        con = sqlite3.connect(self._path, timeout=self._timeout / 1000.0, isolation_level=None)
        con.execute("PRAGMA busy_timeout=%d" % self._timeout)
        con.execute("PRAGMA synchronous=FULL")
        return con

    @staticmethod
    def _validate_principal(p):
        if (not isinstance(p, AuthenticatedPrincipal) or not isinstance(p.subject_id, str) or not p.subject_id.strip()
            or not isinstance(p.session_id, str) or not p.session_id.strip()
            or not isinstance(p.tenant_ids, frozenset) or not p.tenant_ids
            or any(not isinstance(x, str) or not x.strip() for x in p.tenant_ids)
            or isinstance(p.expires_at_epoch, bool) or not isinstance(p.expires_at_epoch, (int,float))
            or not math.isfinite(p.expires_at_epoch)):
            raise AccountScopeError("background task identity could not be verified")

    def enqueue(self, principal: AuthenticatedPrincipal, tenant_id: str, *, ttl_seconds: float = 300.0) -> str:
        self._validate_principal(principal)
        if not isinstance(tenant_id, str) or not tenant_id.strip() or tenant_id not in principal.tenant_ids:
            raise AccountScopeError("background task tenant is not authorized")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int,float)) or not math.isfinite(ttl_seconds) or not 1 <= ttl_seconds <= 86400:
            raise ValueError("background task TTL must be between 1 and 86400 seconds")
        now = self._clock()
        if isinstance(now, bool) or not isinstance(now, (int,float)) or not math.isfinite(now):
            raise RuntimeError("background task clock unavailable")
        expiry = min(float(principal.expires_at_epoch), float(now) + float(ttl_seconds))
        if expiry <= now: raise AccountScopeError("background task identity could not be verified")
        job_id = secrets.token_urlsafe(32)
        con = self._connect()
        try:
            con.execute("""INSERT INTO qe_background_jobs
                (job_id,tenant_id,subject_id,session_id,tenant_ids_json,principal_expires_at,expires_at,created_at,state)
                VALUES (?,?,?,?,?,?,?,?, 'PENDING')""",
                (job_id,tenant_id,principal.subject_id,principal.session_id,
                 json.dumps(sorted(principal.tenant_ids),separators=(",",":")),
                 float(principal.expires_at_epoch),expiry,float(now)))
        finally: con.close()
        return job_id

    def claim_job(self, job_id: str) -> BackgroundJobEnvelope | None:
        if not isinstance(job_id, str) or not job_id.strip() or len(job_id)>256: return None
        now = self._clock()
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("""SELECT tenant_id,subject_id,session_id,tenant_ids_json,
                principal_expires_at,expires_at,state FROM qe_background_jobs WHERE job_id=?""",(job_id,)).fetchone()
            if row is None or row[6] != "PENDING":
                con.execute("COMMIT"); return None
            if row[5] <= now or row[4] <= now:
                con.execute("UPDATE qe_background_jobs SET state='EXPIRED',finished_at=? WHERE job_id=? AND state='PENDING'",(float(now),job_id))
                con.execute("COMMIT"); return None
            if con.execute("UPDATE qe_background_jobs SET state='RUNNING',claimed_at=? WHERE job_id=? AND state='PENDING'",(float(now),job_id)).rowcount != 1:
                con.execute("ROLLBACK"); return None
            con.execute("COMMIT")
            p=AuthenticatedPrincipal(row[1],row[2],frozenset(json.loads(row[3])),float(row[4]))
            return BackgroundJobEnvelope(job_id,row[0],p,float(row[5]))
        except Exception:
            if con.in_transaction: con.execute("ROLLBACK")
            raise
        finally: con.close()

    def finish_job(self, job_id: str, *, success: bool) -> None:
        if not isinstance(success,bool): raise ValueError("success must be boolean")
        con=self._connect()
        try:
            state="SUCCEEDED" if success else "FAILED"
            if con.execute("UPDATE qe_background_jobs SET state=?,finished_at=? WHERE job_id=? AND state='RUNNING'",
                           (state,float(self._clock()),job_id)).rowcount != 1:
                raise RuntimeError("background task state transition was not accepted")
        finally: con.close()

    def status(self, job_id: str) -> str | None:
        con=self._connect()
        try:
            row=con.execute("SELECT state FROM qe_background_jobs WHERE job_id=?",(job_id,)).fetchone()
            return row[0] if row else None
        finally: con.close()


class TenantBackgroundTaskRunner:
    """Worker receives only an opaque job ID; tenant and identity come from storage."""
    production_ready = False

    def __init__(self, job_store: TrustedBackgroundJobStore, authorizer: RequestScopedTenantAuthorizer):
        if not callable(getattr(job_store,"claim_job",None)) or not callable(getattr(job_store,"finish_job",None)):
            raise ValueError("trusted durable background job store is required")
        if not isinstance(authorizer,RequestScopedTenantAuthorizer):
            raise ValueError("trusted request-scoped tenant authorizer is required")
        self._store,self._authorizer=job_store,authorizer

    def run(self, job_id: str, callback, *args, **kwargs):
        from core.accounts.request_tenant_authorization import bind_authenticated_principal
        if not isinstance(job_id,str) or not job_id.strip() or len(job_id)>256:
            raise AccountScopeError("background task identity could not be verified")
        if not callable(callback): raise ValueError("background task callback must be callable")
        try: envelope=self._store.claim_job(job_id)
        except Exception: raise AccountScopeError("background task could not be claimed") from None
        if not isinstance(envelope,BackgroundJobEnvelope) or envelope.job_id != job_id:
            raise AccountScopeError("background task is unavailable or already claimed")
        try:
            SQLiteBackgroundJobStore._validate_principal(envelope.principal)
            if envelope.tenant_id not in envelope.principal.tenant_ids:
                raise AccountScopeError("background task tenant is not authorized")
            with bind_authenticated_principal(envelope.principal):
                if self._authorizer.authorize_tenant(envelope.tenant_id) is not True:
                    raise AccountScopeError("background task tenant is not authorized")
                result=callback(*args,**kwargs)
            self._store.finish_job(job_id,success=True)
            return result
        except Exception:
            try: self._store.finish_job(job_id,success=False)
            except Exception: pass
            raise
