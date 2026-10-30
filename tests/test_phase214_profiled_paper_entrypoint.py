"""Startup ordering and failure behavior for the explicit PAPER profile path."""
import pytest

from core.runtime.paper_gate_profile import MAX_AGE_ENV, PROFILE_ENV
from core.runtime.profiled_paper_entrypoint import run_profiled_paper_with_monitoring


class FakeEngine:
    market_data_max_age_seconds = None
    market_data_gate_required = False
    market_data_now_provider = None


def test_invalid_strict_config_fails_before_builder_or_runner():
    calls = []

    def builder(**kwargs):
        calls.append("builder")
        return FakeEngine(), object()

    def runner(engine):
        calls.append("runner")

    with pytest.raises(ValueError):
        run_profiled_paper_with_monitoring(
            builder=builder,
            runner=runner,
            environ={PROFILE_ENV: "strict"},
        )
    assert calls == []


def test_strict_profile_is_applied_before_runner_receives_engine():
    engine = FakeEngine()
    manager = object()
    seen = []

    def builder(**kwargs):
        return engine, manager

    def runner(received):
        seen.append(received)
        assert received.market_data_max_age_seconds == 15.0
        assert received.market_data_gate_required is True
        return "runner-result"

    result, returned_manager = run_profiled_paper_with_monitoring(
        builder=builder,
        runner=runner,
        environ={PROFILE_ENV: "strict", MAX_AGE_ENV: "15"},
    )
    assert result == "runner-result"
    assert returned_manager is manager
    assert seen == [engine]


def test_runner_failure_is_propagated_without_fallback_to_legacy_runner():
    engine = FakeEngine()
    calls = []

    def builder(**kwargs):
        return engine, object()

    def runner(received):
        calls.append(received)
        raise RuntimeError("runner failed")

    with pytest.raises(RuntimeError, match="runner failed"):
        run_profiled_paper_with_monitoring(
            builder=builder,
            runner=runner,
            environ={PROFILE_ENV: "strict", MAX_AGE_ENV: "10"},
        )
    assert calls == [engine]


def test_compat_profile_preserves_legacy_gate_defaults():
    engine = FakeEngine()

    result, _ = run_profiled_paper_with_monitoring(
        builder=lambda **kwargs: (engine, "manager"),
        runner=lambda received: received.market_data_gate_required,
        environ={PROFILE_ENV: "compat"},
    )
    assert result is False
    assert engine.market_data_max_age_seconds is None
