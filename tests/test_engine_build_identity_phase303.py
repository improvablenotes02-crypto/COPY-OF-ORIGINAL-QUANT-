"""Phase 303: standardized QuantEngine build identity fingerprints."""
from dataclasses import replace

import pytest

from core.research.acquisition.scope_provenance import (
    EngineBuildIdentity,
    ScopeProvenanceError,
)


def _build(**changes):
    values = dict(
        release_version="1.0.0",
        source_revision="a" * 40,
        artifact_sha256="b" * 64,
        dependency_lock_sha256="c" * 64,
        runtime_identity="cpython-3.12.16-linux-x86_64",
    )
    values.update(changes)
    return EngineBuildIdentity(**values)


def test_build_identity_fingerprint_is_deterministic():
    one, two = _build(), _build()
    assert one.fingerprint == two.fingerprint
    assert len(one.fingerprint) == 64


@pytest.mark.parametrize("change", [
    {"release_version": "1.0.1"},
    {"source_revision": "d" * 40},
    {"artifact_sha256": "d" * 64},
    {"dependency_lock_sha256": "d" * 64},
    {"runtime_identity": "cpython-3.12.16-windows-x86_64"},
])
def test_any_build_component_change_changes_fingerprint(change):
    original = _build()
    changed = replace(original, **change)
    assert original.fingerprint != changed.fingerprint


@pytest.mark.parametrize("change", [
    {"source_revision": "not-a-git-revision"},
    {"artifact_sha256": "not-a-hash"},
    {"dependency_lock_sha256": "not-a-hash"},
    {"release_version": " "},
    {"runtime_identity": ""},
])
def test_malformed_build_identity_is_rejected(change):
    with pytest.raises(ScopeProvenanceError):
        _build(**change)
