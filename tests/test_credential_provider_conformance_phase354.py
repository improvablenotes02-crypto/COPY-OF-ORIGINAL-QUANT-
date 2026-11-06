"""Phase 354: key-version binding in credential provider conformance."""
from dataclasses import replace

from core.accounts.credential_provider_conformance import assess_encryption_provider
from tests.test_credential_provider_conformance_phase353 import (
    _BrokenProvider,
    _TestOnlyConformingProvider,
)


def test_conformance_requires_stable_key_version_during_one_assessment():
    report = assess_encryption_provider(_TestOnlyConformingProvider())
    assert report.passed is True
    assert "key_version_stability" in report.checks


def test_conformance_rejects_provider_that_does_not_bind_decryption_to_key_id():
    report = assess_encryption_provider(_BrokenProvider())
    assert report.passed is False
    assert "key_version_binding" in report.failures


class _SwitchingKeyVersionProvider(_TestOnlyConformingProvider):
    def encrypt(self, plaintext: bytes, *, associated_data: bytes):
        envelope = super().encrypt(plaintext, associated_data=associated_data)
        if self.counter > 1:
            return replace(envelope, key_id="test-kms-key-version-2")
        return envelope


def test_conformance_rejects_key_version_switch_during_assessment():
    report = assess_encryption_provider(_SwitchingKeyVersionProvider())
    assert report.passed is False
    assert "key_version_stability" in report.failures
