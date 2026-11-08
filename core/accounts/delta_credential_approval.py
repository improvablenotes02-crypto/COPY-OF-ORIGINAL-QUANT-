"""Exact owner-governance admission for Delta account credentials.

The adapter is intentionally not production-admissible until the repository
provides authenticated tenant isolation and shared durable storage.
"""
from __future__ import annotations


class OwnerGovernanceDeltaCredentialApprovalProvider:
    """Bind runtime credential fingerprints to exactly one approved governance row."""

    def __init__(self, repository):
        if repository is None or not callable(
            getattr(repository, "credentials_for_account_fingerprint", None)
        ):
            raise ValueError("credential governance repository lookup is required")
        self._repository = repository

    @property
    def production_ready(self) -> bool:
        """Delegate admission to the guarded, durable tenant repository."""
        return (
            getattr(self._repository, "production_ready", False) is True
            and getattr(self._repository, "durable_shared_storage", False) is True
            and getattr(self._repository, "tenant_isolation_enforced", False) is True
        )

    def is_approved(self, *, tenant_id: str, account_id: str, fingerprint: str) -> bool:
        """Legacy tenant-wide check; retained for offline compatibility only."""
        record = self._matching_record(tenant_id, account_id, fingerprint)
        return record is not None and record.status == "APPROVED"

    def is_approved_for_subject(
        self, *, tenant_id: str, account_id: str, fingerprint: str, subject_id: str
    ) -> bool:
        """Admit a credential only to its verified submitting member."""
        if not isinstance(subject_id, str) or not subject_id.strip() or len(subject_id) > 256:
            return False
        record = self._matching_record(tenant_id, account_id, fingerprint)
        return (
            record is not None
            and record.subject_id == subject_id
            and record.status == "APPROVED"
        )

    def _matching_record(self, tenant_id: str, account_id: str, fingerprint: str):
        for value in (tenant_id, account_id):
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                return None
        if (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in fingerprint)
        ):
            return None
        records = self._repository.credentials_for_account_fingerprint(
            tenant_id, account_id, fingerprint
        )
        # Ambiguous duplicate registrations fail closed, even if one is approved.
        if not isinstance(records, list) or len(records) != 1:
            return None
        record = records[0]
        if (
            record.tenant_id != tenant_id
            or record.account_id != account_id
            or record.fingerprint != fingerprint
        ):
            return None
        return record
