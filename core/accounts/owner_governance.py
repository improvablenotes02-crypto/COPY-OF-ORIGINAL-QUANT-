"""Owner-governed tenant membership and credential approval state machine.

This module stores identity references and credential metadata only. It never
accepts or persists API key material. Production deployments must use the
PostgreSQL implementation/migration and a trusted OIDC principal source; the
SQLite repository here is for deterministic tests and single-process development.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from core.accounts.request_tenant_authorization import (
    AuthenticatedPrincipal,
    SessionStatusValidator,
    TrustedPrincipalSource,
)


class GovernanceError(RuntimeError):
    """Base class for fail-closed governance errors."""


class OwnerAuthorizationError(GovernanceError):
    """The actor is not the configured owner."""


class GovernanceConflictError(GovernanceError):
    """The requested state transition is not valid."""


@dataclass(frozen=True, slots=True)
class Membership:
    tenant_id: str
    subject_id: str
    status: str
    permissions: tuple[str, ...]
    created_at_ns: int
    updated_at_ns: int


@dataclass(frozen=True, slots=True)
class CredentialApproval:
    tenant_id: str
    credential_id: str
    subject_id: str
    account_id: str
    fingerprint: str
    status: str
    created_at_ns: int
    updated_at_ns: int


class SQLiteOwnerGovernanceRepository:
    """Transactional local repository; explicitly not production-admissible."""
    production_ready = False
    durable_shared_storage = False
    tenant_isolation_enforced = False

    def __init__(self, database: str | Path = ":memory:"):
        self._db = sqlite3.connect(str(database), check_same_thread=False,
                                   isolation_level='IMMEDIATE', timeout=5.0)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._db.execute("PRAGMA foreign_keys=ON")
            self._db.execute("PRAGMA busy_timeout=5000")
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS qe_memberships (
                    tenant_id TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED','REVOKED')),
                    permissions_json TEXT NOT NULL,
                    created_at_ns INTEGER NOT NULL,
                    updated_at_ns INTEGER NOT NULL,
                    PRIMARY KEY(tenant_id, subject_id)
                );
                CREATE TABLE IF NOT EXISTS qe_credential_approvals (
                    tenant_id TEXT NOT NULL,
                    credential_id TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PENDING','APPROVED','REJECTED','REVOKED')),
                    created_at_ns INTEGER NOT NULL,
                    updated_at_ns INTEGER NOT NULL,
                    PRIMARY KEY(tenant_id, credential_id)
                );
                CREATE TABLE IF NOT EXISTS qe_governance_audit (
                    event_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    occurred_at_ns INTEGER NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS qe_membership_subject
                    ON qe_memberships(tenant_id,status,subject_id);
                CREATE INDEX IF NOT EXISTS qe_credentials_account
                    ON qe_credential_approvals(tenant_id,account_id,status);
                CREATE TRIGGER IF NOT EXISTS qe_audit_no_update
                    BEFORE UPDATE ON qe_governance_audit
                    BEGIN SELECT RAISE(ABORT,'governance audit is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS qe_audit_no_delete
                    BEFORE DELETE ON qe_governance_audit
                    BEGIN SELECT RAISE(ABORT,'governance audit is immutable'); END;
            """)

    def close(self):
        with self._lock:
            self._db.close()

    def _audit(self, tenant, actor, action, target, now):
        previous = self._db.execute(
            "SELECT event_hash FROM qe_governance_audit WHERE tenant_id=? "
            "ORDER BY occurred_at_ns DESC,event_id DESC LIMIT 1", (tenant,)
        ).fetchone()
        previous_hash = previous["event_hash"] if previous else "0" * 64
        event_id = str(uuid.uuid4())
        payload = json.dumps([event_id,tenant,actor,action,target,now,previous_hash],
                             separators=(",",":"),ensure_ascii=False)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        self._db.execute(
            "INSERT INTO qe_governance_audit VALUES(?,?,?,?,?,?,?,?)",
            (event_id,tenant,actor,action,target,now,previous_hash,digest)
        )

    def invite(self, tenant, subject, permissions, actor, now):
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO qe_memberships VALUES(?,?,'PENDING',?,?,?)",
                (tenant,subject,json.dumps(sorted(permissions)),now,now))
            self._audit(tenant, actor, "MEMBER_INVITED", subject, now)

    def decide_membership(self, tenant, subject, status, permissions, actor, now):
        with self._lock, self._db:
            cur=self._db.execute(
                "UPDATE qe_memberships SET status=?,permissions_json=?,updated_at_ns=? "
                "WHERE tenant_id=? AND subject_id=? AND status='PENDING'",
                (status,json.dumps(sorted(permissions)),now,tenant,subject))
            if cur.rowcount != 1: raise GovernanceConflictError("membership is not pending")
            self._audit(tenant,actor,"MEMBERSHIP_"+status,subject,now)

    def revoke_membership(self, tenant, subject, actor, now):
        """Revoke an approved member as an audited one-way transition."""
        with self._lock, self._db:
            cur = self._db.execute(
                "UPDATE qe_memberships SET status='REVOKED',permissions_json='[]',updated_at_ns=? "
                "WHERE tenant_id=? AND subject_id=? AND status='APPROVED'",
                (now, tenant, subject),
            )
            if cur.rowcount != 1:
                raise GovernanceConflictError("membership is not approved")
            credentials = self._db.execute(
                "SELECT credential_id FROM qe_credential_approvals "
                "WHERE tenant_id=? AND subject_id=? AND status IN ('PENDING','APPROVED') "
                "ORDER BY credential_id",
                (tenant, subject),
            ).fetchall()
            self._db.execute(
                "UPDATE qe_credential_approvals SET status='REVOKED',updated_at_ns=? "
                "WHERE tenant_id=? AND subject_id=? AND status IN ('PENDING','APPROVED')",
                (now, tenant, subject),
            )
            for credential in credentials:
                self._audit(tenant, actor, "CREDENTIAL_REVOKED_MEMBER_REMOVAL",
                            credential["credential_id"], now)
            self._audit(tenant, actor, "MEMBER_REVOKED", subject, now)

    def membership(self, tenant, subject):
        with self._lock:
            row=self._db.execute("SELECT * FROM qe_memberships WHERE tenant_id=? AND subject_id=?",
                                 (tenant,subject)).fetchone()
        if row is None: return None
        return Membership(row["tenant_id"],row["subject_id"],row["status"],
                          tuple(json.loads(row["permissions_json"])),
                          row["created_at_ns"],row["updated_at_ns"])

    def list_members(self, tenant):
        with self._lock:
            rows = self._db.execute("SELECT * FROM qe_memberships WHERE tenant_id=? ORDER BY created_at_ns,subject_id", (tenant,)).fetchall()
        return [Membership(row["tenant_id"], row["subject_id"], row["status"],
                           tuple(json.loads(row["permissions_json"])), row["created_at_ns"], row["updated_at_ns"])
                for row in rows]

    def list_credentials(self, tenant):
        with self._lock:
            rows = self._db.execute("SELECT * FROM qe_credential_approvals WHERE tenant_id=? ORDER BY created_at_ns,credential_id", (tenant,)).fetchall()
        return [CredentialApproval(row["tenant_id"], row["credential_id"], row["subject_id"],
                                   row["account_id"], row["fingerprint"], row["status"],
                                   row["created_at_ns"], row["updated_at_ns"]) for row in rows]

    def submit_credential(self, tenant, credential, subject, account, fingerprint, now):
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO qe_credential_approvals VALUES(?,?,?,?,?,'PENDING',?,?)",
                (tenant,credential,subject,account,fingerprint,now,now))
            self._audit(tenant,subject,"CREDENTIAL_SUBMITTED",credential,now)

    def decide_credential(self, tenant, credential, status, actor, now):
        with self._lock, self._db:
            row=self._db.execute(
                "SELECT subject_id FROM qe_credential_approvals WHERE tenant_id=? AND credential_id=? AND status='PENDING'",
                (tenant,credential)).fetchone()
            if row is None: raise GovernanceConflictError("credential is not pending")
            cur=self._db.execute(
                "UPDATE qe_credential_approvals SET status=?,updated_at_ns=? "
                "WHERE tenant_id=? AND credential_id=? AND status='PENDING'",
                (status,now,tenant,credential))
            if cur.rowcount != 1: raise GovernanceConflictError("credential state changed concurrently")
            self._audit(tenant,actor,"CREDENTIAL_"+status,credential,now)

    def credential(self, tenant, credential):
        with self._lock:
            row=self._db.execute(
                "SELECT * FROM qe_credential_approvals WHERE tenant_id=? AND credential_id=?",
                (tenant,credential)).fetchone()
        if row is None: return None
        return CredentialApproval(row["tenant_id"],row["credential_id"],row["subject_id"],
            row["account_id"],row["fingerprint"],row["status"],row["created_at_ns"],row["updated_at_ns"])

    def revoke_credential(self, tenant, credential, actor, now):
        """Revoke a previously approved credential as an audited one-way transition."""
        with self._lock, self._db:
            cur = self._db.execute(
                "UPDATE qe_credential_approvals SET status='REVOKED',updated_at_ns=? "
                "WHERE tenant_id=? AND credential_id=? AND status='APPROVED'",
                (now, tenant, credential),
            )
            if cur.rowcount != 1:
                raise GovernanceConflictError("credential is not approved")
            self._audit(tenant, actor, "CREDENTIAL_REVOKED", credential, now)

    def credentials_for_account_fingerprint(self, tenant, account, fingerprint):
        """Return every exact credential tuple match; callers must reject ambiguity."""
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM qe_credential_approvals "
                "WHERE tenant_id=? AND account_id=? AND fingerprint=? "
                "ORDER BY credential_id",
                (tenant, account, fingerprint),
            ).fetchall()
        return [
            CredentialApproval(row["tenant_id"], row["credential_id"], row["subject_id"],
                row["account_id"], row["fingerprint"], row["status"],
                row["created_at_ns"], row["updated_at_ns"])
            for row in rows
        ]

    def audit_events(self, tenant):
        with self._lock:
            return [dict(r) for r in self._db.execute(
                "SELECT * FROM qe_governance_audit WHERE tenant_id=? ORDER BY occurred_at_ns,event_id",
                (tenant,)).fetchall()]


class OwnerGovernance:
    """Owner-authorized membership and credential approval facade.

    owner_subject_id must be injected from trusted deployment configuration.
    Caller identity must be supplied by verified authentication middleware.
    """
    def __init__(self, repository: SQLiteOwnerGovernanceRepository, *,
                 owner_subject_id: str, clock: Callable[[], int] = time.time_ns):
        if not isinstance(owner_subject_id,str) or not owner_subject_id.strip():
            raise ValueError("trusted owner identity is required")
        if repository is None: raise ValueError("governance repository is required")
        self._repository=repository
        self._owner=owner_subject_id
        self._clock=clock

    def _owner_only(self, actor):
        if not isinstance(actor,str) or actor != self._owner:
            raise OwnerAuthorizationError("owner authorization required")

    @staticmethod
    def _text(value, name):
        if not isinstance(value,str) or not value.strip() or len(value)>256:
            raise ValueError(f"{name} must be non-empty and at most 256 characters")
        return value.strip()

    def invite_member(self, *, actor_id, tenant_id, subject_id, permissions=()):
        self._owner_only(actor_id)
        tenant=self._text(tenant_id,"tenant_id"); subject=self._text(subject_id,"subject_id")
        allowed={"read","trade_paper","manage_strategies"}
        perms=tuple(sorted(set(permissions)))
        if any(p not in allowed for p in perms): raise ValueError("unsupported permission")
        self._repository.invite(tenant,subject,perms,actor_id,self._clock())

    def decide_member(self, *, actor_id, tenant_id, subject_id, approve, permissions=()):
        self._owner_only(actor_id)
        if not isinstance(approve,bool): raise ValueError("approve must be boolean")
        tenant=self._text(tenant_id,"tenant_id"); subject=self._text(subject_id,"subject_id")
        allowed={"read","trade_paper","manage_strategies"}
        perms=tuple(sorted(set(permissions)))
        if any(p not in allowed for p in perms): raise ValueError("unsupported permission")
        self._repository.decide_membership(tenant,subject,"APPROVED" if approve else "REJECTED",
                                           perms if approve else (),actor_id,self._clock())

    def revoke_member(self, *, actor_id, tenant_id, subject_id):
        self._owner_only(actor_id)
        tenant = self._text(tenant_id, "tenant_id")
        subject = self._text(subject_id, "subject_id")
        if subject == self._owner:
            raise OwnerAuthorizationError("the configured owner cannot be revoked")
        self._repository.revoke_membership(tenant, subject, actor_id, self._clock())

    def list_members(self, *, actor_id, tenant_id):
        self._owner_only(actor_id)
        return self._repository.list_members(self._text(tenant_id, "tenant_id"))

    def list_credentials(self, *, actor_id, tenant_id):
        self._owner_only(actor_id)
        return self._repository.list_credentials(self._text(tenant_id, "tenant_id"))

    def submit_credential(self, *, actor_id, tenant_id, credential_id, account_id, fingerprint):
        actor=self._text(actor_id,"actor_id")
        tenant=self._text(tenant_id,"tenant_id"); cid=self._text(credential_id,"credential_id")
        account=self._text(account_id,"account_id")
        if not isinstance(fingerprint,str) or len(fingerprint)!=64 or any(c not in "0123456789abcdef" for c in fingerprint):
            raise ValueError("fingerprint must be a lowercase SHA-256 hex digest")
        membership=self._repository.membership(tenant,actor)
        if actor != self._owner and (membership is None or membership.status!="APPROVED"):
            raise OwnerAuthorizationError("approved tenant membership required")
        self._repository.submit_credential(tenant,cid,actor,account,fingerprint,self._clock())

    def decide_credential(self, *, actor_id, tenant_id, credential_id, approve):
        self._owner_only(actor_id)
        if not isinstance(approve,bool): raise ValueError("approve must be boolean")
        self._repository.decide_credential(
            self._text(tenant_id,"tenant_id"),self._text(credential_id,"credential_id"),
            "APPROVED" if approve else "REJECTED",actor_id,self._clock())

    def revoke_credential(self, *, actor_id, tenant_id, credential_id):
        self._owner_only(actor_id)
        self._repository.revoke_credential(
            self._text(tenant_id, "tenant_id"),
            self._text(credential_id, "credential_id"),
            actor_id,
            self._clock(),
        )

    def credential_is_approved(self, *, tenant_id, credential_id):
        record=self._repository.credential(self._text(tenant_id,"tenant_id"),
                                           self._text(credential_id,"credential_id"))
        return record is not None and record.status=="APPROVED"

    @property
    def storage_ready(self):
        """Whether the persistence adapter meets its declared storage contract."""
        return (
            getattr(self._repository, "production_ready", False) is True
            and getattr(self._repository, "durable_shared_storage", False) is True
            and getattr(self._repository, "tenant_isolation_enforced", False) is True
        )

    @property
    def production_ready(self):
        """The actor-id facade is internal and never request-facing/production-ready."""
        return False


class AuthenticatedOwnerGovernance:
    """Request-facing owner governance facade bound to a trusted principal.

    The caller cannot supply an actor_id. Identity, tenant membership, token
    expiry, and session activity are derived from injected trusted services.
    """

    def __init__(
        self,
        governance: OwnerGovernance,
        principal_source: TrustedPrincipalSource,
        session_validator: SessionStatusValidator,
        *,
        clock: Callable[[], float] = time.time,
    ):
        if governance is None:
            raise ValueError("owner governance service is required")
        if not callable(getattr(principal_source, "current_principal", None)):
            raise ValueError("trusted principal source is required")
        if not callable(getattr(session_validator, "is_session_active", None)):
            raise ValueError("session status validator is required")
        self._governance = governance
        self._principal_source = principal_source
        self._session_validator = session_validator
        self._clock = clock

    def _identity(self, tenant_id: str) -> tuple[str, str]:
        tenant = OwnerGovernance._text(tenant_id, "tenant_id")
        try:
            principal = self._principal_source.current_principal()
            if not isinstance(principal, AuthenticatedPrincipal):
                raise ValueError("authenticated principal missing")
            if (
                not isinstance(principal.subject_id, str)
                or not principal.subject_id.strip()
                or not isinstance(principal.session_id, str)
                or not principal.session_id.strip()
                or not isinstance(principal.tenant_ids, frozenset)
                or any(
                    not isinstance(item, str) or not item.strip()
                    for item in principal.tenant_ids
                )
                or isinstance(principal.expires_at_epoch, bool)
                or not isinstance(principal.expires_at_epoch, (int, float))
                or not math.isfinite(principal.expires_at_epoch)
            ):
                raise ValueError("authenticated principal is malformed")
            now = self._clock()
            if (
                isinstance(now, bool)
                or not isinstance(now, (int, float))
                or not math.isfinite(now)
                or principal.expires_at_epoch <= now
                or tenant not in principal.tenant_ids
            ):
                raise ValueError("authenticated principal is expired or out of scope")
            if self._session_validator.is_session_active(principal) is not True:
                raise ValueError("authenticated session is inactive")
            return tenant, principal.subject_id
        except Exception:
            raise OwnerAuthorizationError(
                "authenticated tenant principal required"
            ) from None

    def invite_member(self, *, tenant_id, subject_id, permissions=()):
        tenant, actor = self._identity(tenant_id)
        self._governance.invite_member(
            actor_id=actor,
            tenant_id=tenant,
            subject_id=subject_id,
            permissions=permissions,
        )

    def decide_member(self, *, tenant_id, subject_id, approve, permissions=()):
        tenant, actor = self._identity(tenant_id)
        self._governance.decide_member(
            actor_id=actor,
            tenant_id=tenant,
            subject_id=subject_id,
            approve=approve,
            permissions=permissions,
        )

    def revoke_member(self, *, tenant_id, subject_id):
        tenant, actor = self._identity(tenant_id)
        self._governance.revoke_member(
            actor_id=actor, tenant_id=tenant, subject_id=subject_id
        )

    def list_members(self, *, tenant_id):
        tenant, actor = self._identity(tenant_id)
        return self._governance.list_members(actor_id=actor, tenant_id=tenant)

    def list_credentials(self, *, tenant_id):
        tenant, actor = self._identity(tenant_id)
        return self._governance.list_credentials(actor_id=actor, tenant_id=tenant)

    def submit_credential(
        self, *, tenant_id, credential_id, account_id, fingerprint
    ):
        tenant, actor = self._identity(tenant_id)
        self._governance.submit_credential(
            actor_id=actor,
            tenant_id=tenant,
            credential_id=credential_id,
            account_id=account_id,
            fingerprint=fingerprint,
        )

    def decide_credential(self, *, tenant_id, credential_id, approve):
        tenant, actor = self._identity(tenant_id)
        self._governance.decide_credential(
            actor_id=actor,
            tenant_id=tenant,
            credential_id=credential_id,
            approve=approve,
        )

    def revoke_credential(self, *, tenant_id, credential_id):
        tenant, actor = self._identity(tenant_id)
        self._governance.revoke_credential(
            actor_id=actor, tenant_id=tenant, credential_id=credential_id
        )

    def credential_is_approved(self, *, tenant_id, credential_id):
        tenant, _actor = self._identity(tenant_id)
        return self._governance.credential_is_approved(
            tenant_id=tenant,
            credential_id=credential_id,
        )

    @property
    def production_ready(self):
        return (
            getattr(self._principal_source, "production_ready", False) is True
            and getattr(self._session_validator, "production_ready", False) is True
            and self._governance.storage_ready is True
        )
