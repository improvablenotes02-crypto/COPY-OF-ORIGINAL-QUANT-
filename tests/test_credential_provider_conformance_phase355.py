"""Phase 355: repeated-envelope validation and decrypt-error redaction."""
from dataclasses import replace

from core.accounts.delta_account_registry import CiphertextEnvelope
from core.accounts.credential_provider_conformance import assess_encryption_provider
from tests.test_credential_provider_conformance_phase353 import _TestOnlyConformingProvider


class _MalformedSecondEnvelopeProvider(_TestOnlyConformingProvider):
    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        envelope = super().encrypt(plaintext, associated_data=associated_data)
        if self.counter == 2:
            return replace(envelope, key_id="", ciphertext=b"")
        return envelope


class _AlgorithmSwitchingProvider(_TestOnlyConformingProvider):
    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        envelope = super().encrypt(plaintext, associated_data=associated_data)
        if self.counter == 2:
            return replace(envelope, algorithm="AES-128-GCM")
        return envelope


class _LeakyDecryptProvider(_TestOnlyConformingProvider):
    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        raise RuntimeError("private-key-material-and-credential-secret")


def test_conformance_rejects_malformed_second_envelope():
    report = assess_encryption_provider(_MalformedSecondEnvelopeProvider())
    assert report.passed is False
    assert "repeat_envelope_fields" in report.failures


def test_conformance_rejects_algorithm_change_between_encryptions():
    report = assess_encryption_provider(_AlgorithmSwitchingProvider())
    assert report.passed is False
    assert "repeat_envelope_fields" in report.failures


def test_decrypt_exception_details_never_escape_conformance_report():
    report = assess_encryption_provider(_LeakyDecryptProvider())
    assert report.passed is False
    assert "decrypt_round_trip" in report.failures
    assert "private-key-material" not in repr(report)
    assert "credential-secret" not in repr(report)
