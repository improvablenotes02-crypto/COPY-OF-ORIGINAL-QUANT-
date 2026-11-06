"""Phase 353: vendor-neutral credential encryption provider conformance."""
import hashlib
import hmac

from core.accounts.delta_account_registry import CiphertextEnvelope
from core.accounts.credential_provider_conformance import assess_encryption_provider


class _TestOnlyConformingProvider:
    """Behavioral test double; deliberately not real AES-GCM or KMS."""

    production_ready = True
    algorithm = "AES-256-GCM"

    def __init__(self):
        self.counter = 0
        self._test_key = b"test-only-key-material"

    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> CiphertextEnvelope:
        self.counter += 1
        nonce = self.counter.to_bytes(8, "big")
        body = bytes(value ^ self._test_key[index % len(self._test_key)] for index, value in enumerate(plaintext))
        tag = hmac.new(self._test_key, associated_data + nonce + body, hashlib.sha256).digest()
        return CiphertextEnvelope("test-kms-key-version-1", self.algorithm, nonce + body + tag)

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        nonce, body, tag = envelope.ciphertext[:8], envelope.ciphertext[8:-32], envelope.ciphertext[-32:]
        expected = hmac.new(self._test_key, associated_data + nonce + body, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ValueError("test authentication failure")
        return bytes(value ^ self._test_key[index % len(self._test_key)] for index, value in enumerate(body))


class _BrokenProvider(_TestOnlyConformingProvider):
    """Broken test double that ignores AAD and accepts modified ciphertext."""

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes) -> bytes:
        body = envelope.ciphertext[8:-32]
        return bytes(value ^ self._test_key[index % len(self._test_key)] for index, value in enumerate(body))


class _LeakyFailureProvider:
    production_ready = True
    algorithm = "AES-256-GCM"

    def encrypt(self, plaintext: bytes, *, associated_data: bytes):
        raise RuntimeError("secret-value-must-not-appear")

    def decrypt(self, envelope: CiphertextEnvelope, *, associated_data: bytes):
        raise AssertionError("not reached")


def test_conforming_test_double_passes_behavioral_contract_without_claiming_crypto():
    report = assess_encryption_provider(_TestOnlyConformingProvider())
    assert report.passed is True
    assert report.failures == ()
    assert {
        "envelope_fields",
        "plaintext_not_exposed",
        "ciphertext_uniqueness",
        "decrypt_round_trip",
        "associated_data_authentication",
        "ciphertext_integrity",
    }.issubset(report.checks)
    assert report.algorithm == "AES-256-GCM"
    assert report.key_id == "test-kms-key-version-1"


def test_provider_that_ignores_aad_and_integrity_fails_closed():
    report = assess_encryption_provider(_BrokenProvider())
    assert report.passed is False
    assert "associated_data_authentication" in report.failures
    assert "ciphertext_integrity" in report.failures


def test_provider_exception_text_is_not_returned_in_report():
    report = assess_encryption_provider(_LeakyFailureProvider())
    assert report.passed is False
    assert report.failures == ("encrypt_operation",)
    assert "secret-value-must-not-appear" not in repr(report)


def test_provider_without_production_declaration_is_not_admitted():
    provider = _TestOnlyConformingProvider()
    provider.production_ready = False
    report = assess_encryption_provider(provider)
    assert report.passed is False
    assert "production_declaration" in report.failures
