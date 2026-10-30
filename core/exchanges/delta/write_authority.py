"""
Process-minted write authority for Delta exchange writes.

Phase193B closes the Phase 189+ audit finding that the low-level write
boundary (``DeltaExchange.place_order``/``cancel_order`` and the raw
``DeltaSignedREST.post``/``delete``) enforced only *authentication*: any
caller that assembled the right client could submit an order without the
mandatory authorization stages (LiveSafetyGate / TestnetAuthorizationGate).

Design (matches the existing gate mint discipline):

  * Every armed write carries a ``WriteAuthorityToken`` stamped with THIS
    process's mint secret.  The token cannot be hand-constructed outside
    this module's issue functions (``__init__`` is private; dataclass
    freezes it; the mint is never logged or serialized).
  * Issue functions verify the upstream authorization themselves:
      - ``token_for_live_safety`` re-plays ``LiveSafetyGate.require_decision``
        so a stale/forged SafetyDecision can never arm a transport.
      - ``token_for_testnet_experiment`` requires a gate-minted
        ``AuthorizationDecision`` that ``is_armed()``.
      - ``offline_test_token`` exists ONLY for unit tests driving fake
        transports; it is process-minted like everything else and must
        never be reachable from production entrypoints.
  * ``require_write_authority`` binds the token to the exact endpoint
    AND write kind, so a testnet-experiment authority cannot authorize a
    live adapter write and vice versa.

Nothing here ever strings-formats secret material; reasons name only the
missing KINDS or binding mismatches.

Hard rules:  pure stdlib; no network; no file I/O; no global mutable
state beyond the process mint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import secrets

MINT = secrets.token_hex(16)

KIND_OFFLINE_TEST = "OFFLINE_TEST"
KIND_LIVE_SAFETY = "LIVE_SAFETY"
KIND_TESTNET_EXPERIMENT = "TESTNET_EXPERIMENT"

#: All authorized kinds.  Independent verification is by kind, so one
#: authorization family can never silently ride over another.
ALL_KINDS = frozenset({KIND_OFFLINE_TEST, KIND_LIVE_SAFETY,
                       KIND_TESTNET_EXPERIMENT})

#: Base-URL normalization for offline fake transports (no ``base_url``).
OFFLINE_FALLBACK_BASE_URL = "offline-fake-transport"


class TransportWriteAuthorityError(RuntimeError):
    """An exchange write was attempted without a valid armed token."""


@dataclass(frozen=True)
class WriteAuthorityToken:
    """Armed transport-write token (see module docstring)."""
    mint: str = field(repr=False)
    kind: str
    base_url: str
    endpoint: str

    def __post_init__(self):
        if self.mint != MINT:
            raise TransportWriteAuthorityError(
                "write-authority token mint does not match this process "
                "(forged or stale token)")
        if self.kind not in ALL_KINDS:
            raise TransportWriteAuthorityError(
                "unknown write-authority kind {!r}".format(self.kind))


def _issue(kind: str, base_url: str, endpoint: str) -> WriteAuthorityToken:
    return WriteAuthorityToken(mint=MINT, kind=kind,
                               base_url=base_url, endpoint=endpoint)


def offline_test_token(base_url: str = OFFLINE_FALLBACK_BASE_URL,
                       endpoint: str = "/v2/orders") -> WriteAuthorityToken:
    """TEST-ONLY authority for fake transports.

    Production entrypoints must never call this: real writes must be
    armed by the safety/authorization gates instead.  The kind marks the
    token so a mixed gate can assert it is absent.
    """
    return _issue(KIND_OFFLINE_TEST, base_url, endpoint)


def _bind_base_url(base_url) -> str:
    """Normalize the armed-base-URL string for binding checks."""
    return str(base_url) if base_url is not None and str(base_url) != "" else OFFLINE_FALLBACK_BASE_URL


def token_for_live_safety(decision, base_url,
                          endpoint: str = "/v2/orders"
                          ) -> WriteAuthorityToken:
    """Arm a transport write from a minted ``LiveSafetyGate`` decision.

    The decision is re-verified through ``LiveSafetyGate.require_decision``
    so hand-built or stale tokens fail closed before the issue.
    """
    from core.execution.live_safety_gate import LiveSafetyGate

    verified = LiveSafetyGate.require_decision(
        decision, component="write_authority.token_for_live_safety")
    return _issue(KIND_LIVE_SAFETY, _bind_base_url(base_url), endpoint)


def token_for_testnet_experiment(decision, base_url,
                                 endpoint: str = "/v2/orders"
                                 ) -> WriteAuthorityToken:
    """Arm a transport write from an armed testnet authorization decision.

    Requires an ``AuthorizationDecision`` minted by
    ``TestnetAuthorizationGate.evaluate_preflight`` (``is_armed()``).
    """
    is_armed = getattr(decision, "is_armed", None)
    if not callable(is_armed) or not decision.is_armed():
        raise TransportWriteAuthorityError(
            "testnet experiment write requires an armed "
            "TestnetAuthorizationGate decision (PENDING_OPERATOR_APPROVAL "
            "or refused scope arms nothing)")
    return _issue(KIND_TESTNET_EXPERIMENT, _bind_base_url(base_url), endpoint)


def require_write_authority(token, *, base_url: str, endpoint: str,
                            kinds: frozenset = ALL_KINDS
                            ) -> WriteAuthorityToken:
    """Fail closed: return the validated token or raise.

    Refuses: no token, forged/de-serialized tokens (mint mismatch),
    unbound base URL, unbound endpoint, and unauthorized kind for this
    boundary.

    The *endpoint* argument accepts exactly one path; a token scoped to
    ``/v2/orders`` cannot authorize ``/v2/positions``.
    """
    if token is None:
        raise TransportWriteAuthorityError(
            "exchange write refused: no write authority provided "
            "(Delta adapter writes are authorization-gated at the "
            "transport boundary since Phase193B)")
    if not isinstance(token, WriteAuthorityToken):
        raise TransportWriteAuthorityError(
            "exchange write refused: token is not a minted "
            "WriteAuthorityToken")
    if token.mint != MINT:
        raise TransportWriteAuthorityError(
            "exchange write refused: token was not minted by this "
            "process")
    if token.kind == KIND_OFFLINE_TEST and KIND_OFFLINE_TEST not in kinds:
        raise TransportWriteAuthorityError(
            "exchange write refused: OFFLINE_TEST authority is not "
            "valid for this boundary")
    if token.kind not in kinds:
        raise TransportWriteAuthorityError(
            "exchange write refused: token kind {!r} is not allowed "
            "for this boundary (requires one of {!r})".format(
                token.kind, sorted(kinds)))
    if token.base_url != _bind_base_url(base_url):
        raise TransportWriteAuthorityError(
            "exchange write refused: token is armed for endpoint host "
            "{!r}, not {!r}".format(token.base_url, base_url))
    if token.endpoint != endpoint:
        raise TransportWriteAuthorityError(
            "exchange write refused: token is armed for {!r}, not "
            "{!r}".format(token.endpoint, endpoint))
    return token
