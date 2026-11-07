"""Exact owner-governance admission for Delta account credentials.

The adapter is intentionally not production-admissible until the repository
provides authenticated tenant isolation and shared durable storage.
"""
from __future__ import annotations


class OwnerGovernanceDeltaCredentialApprovalProvider:
    """Bind runtime credential fingerprints to exactly one approved governance row."""

    production_ready = False

    def __init__(self, repository):
        if repository is None or not callable(
            getattr(repository, "credentials_for_account_fingerprint", None)
        ):
            raise ValueError("credential governance repository lookup is required")
        self._repository = repository

    def is_approved(self, *, tenant_id: str, account_id: str, fingerprint: str) -> bool:
        for value in (tenant_id, account_id):
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                return False
        if (
            not isinstance(fingerprint, str)
            or len(fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in fingerprint)
        ):
            return False
        records = self._repository.credentials_for_account_fingerprint(
            tenant_id, account_id, fingerprint
        )
        # Ambiguous duplicate registrations fail closed, even if one is approved.
        if not isinstance(records, list) or len(records) != 1:
            return False
        record = records[0]
        return (
            record.tenant_id == tenant_id
            and record.account_id == account_id
            and record.fingerprint == fingerprint
            and record.status == "APPROVED"
        )
