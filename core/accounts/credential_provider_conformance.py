"""Vendor-neutral conformance checks for injected credential encryption providers.

This module checks observable interface behavior only. It is not a cryptographic
implementation, KMS attestation, or substitute for independent security review.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.accounts.delta_account_registry import CiphertextEnvelope


@dataclass(frozen=True, slots=True)
class ProviderConformanceReport:
    """Secret-free summary of a provider conformance run."""

    passed: bool
    checks: tuple[str, ...]
    failures: tuple[str, ...]
    algorithm: str | None
    key_id: str | None


def assess_encryption_provider(
    provider: Any,
    *,
    plaintext: bytes = b"quantengine-kms-provider-conformance-vector-v1",
    associated_data: bytes = b"quantengine|conformance|tenant|account|delta|sandbox",
) -> ProviderConformanceReport:
    """Exercise round-trip, nonce uniqueness, AAD binding, and tamper rejection.

    Only fixed non-secret test vectors are used. Provider exception text is
    intentionally discarded because SDK errors can contain sensitive context.
    """
    checks: list[str] = []
    failures: list[str] = []
    algorithm: str | None = None
    key_id: str | None = None

    if not isinstance(plaintext, bytes) or not plaintext:
        raise ValueError("plaintext must be non-empty bytes")
    if not isinstance(associated_data, bytes) or not associated_data:
        raise ValueError("associated_data must be non-empty bytes")

    encrypt = getattr(provider, "encrypt", None)
    decrypt = getattr(provider, "decrypt", None)
    if not callable(encrypt) or not callable(decrypt):
        return ProviderConformanceReport(
            False, (), ("provider_interface",), None, None
        )

    if getattr(provider, "production_ready", False) is not True:
        failures.append("production_declaration")
    if getattr(provider, "algorithm", None) != "AES-256-GCM":
        failures.append("algorithm_declaration")
    else:
        algorithm = "AES-256-GCM"

    try:
        first = encrypt(plaintext, associated_data=associated_data)
    except Exception:
        failures.append("encrypt_operation")
        return ProviderConformanceReport(
            False, tuple(checks), tuple(failures), algorithm, None
        )

    if not isinstance(first, CiphertextEnvelope):
        failures.append("envelope_type")
        return ProviderConformanceReport(
            False, tuple(checks), tuple(failures), algorithm, None
        )
    if (
        not isinstance(first.key_id, str) or not first.key_id.strip()
        or first.algorithm != "AES-256-GCM"
        or not isinstance(first.ciphertext, bytes) or not first.ciphertext
    ):
        failures.append("envelope_fields")
        return ProviderConformanceReport(
            False, tuple(checks), tuple(failures), algorithm, None
        )
    key_id = first.key_id
    checks.append("envelope_fields")

    if plaintext in first.ciphertext:
        failures.append("plaintext_not_exposed")
    else:
        checks.append("plaintext_not_exposed")

    try:
        second = encrypt(plaintext, associated_data=associated_data)
    except Exception:
        failures.append("repeat_encrypt_operation")
        second = None
    if isinstance(second, CiphertextEnvelope):
        if second.ciphertext != first.ciphertext:
            checks.append("ciphertext_uniqueness")
        else:
            failures.append("ciphertext_uniqueness")
        if second.key_id == first.key_id:
            checks.append("key_version_stability")
        else:
            failures.append("key_version_stability")
    else:
        failures.append("repeat_encrypt_envelope")
        failures.append("key_version_stability")

    try:
        recovered = decrypt(first, associated_data=associated_data)
    except Exception:
        failures.append("decrypt_round_trip")
    else:
        if recovered == plaintext:
            checks.append("decrypt_round_trip")
        else:
            failures.append("decrypt_round_trip")

    wrong_aad = associated_data + b"|wrong-scope"
    try:
        decrypt(first, associated_data=wrong_aad)
    except Exception:
        checks.append("associated_data_authentication")
    else:
        failures.append("associated_data_authentication")

    unknown_key_envelope = CiphertextEnvelope(
        key_id=first.key_id + "-unknown",
        algorithm=first.algorithm,
        ciphertext=first.ciphertext,
    )
    try:
        decrypt(unknown_key_envelope, associated_data=associated_data)
    except Exception:
        checks.append("key_version_binding")
    else:
        failures.append("key_version_binding")

    tampered = first.ciphertext[:-1] + bytes([first.ciphertext[-1] ^ 1])
    tampered_envelope = CiphertextEnvelope(
        key_id=first.key_id,
        algorithm=first.algorithm,
        ciphertext=tampered,
    )
    try:
        decrypt(tampered_envelope, associated_data=associated_data)
    except Exception:
        checks.append("ciphertext_integrity")
    else:
        failures.append("ciphertext_integrity")

    return ProviderConformanceReport(
        passed=not failures,
        checks=tuple(checks),
        failures=tuple(failures),
        algorithm=algorithm,
        key_id=key_id,
    )
