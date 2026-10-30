"""Deployment launcher tests: strict profile is mandatory and fail-closed."""
import pytest

from core.runtime.paper_gate_profile import MAX_AGE_ENV, PROFILE_ENV
from core.runtime.strict_profiled_paper_launcher import run_strict_profiled_paper_launcher


class FakeEngine:
    market_data_max_age_seconds = None
    market_data_gate_required = False
    market_data_now_provider = None


@pytest.mark.parametrize("environ", [
    {},
    {PROFILE_ENV: "compat", MAX_AGE_ENV: "15"},
    {PROFILE_ENV: "strict"},
])
def test_launcher_rejects_missing_or_compat_profile_before_builder_and_runner(environ):
    calls = []

    def builder(**kwargs):
        calls.append("builder")
        return FakeEngine(), object()

    def runner(engine):
        calls.append("runner")

    with pytest.raises(ValueError):
        run_strict_profiled_paper_launcher(
            builder=builder, runner=runner, environ=environ
        )
    assert calls == []


def test_launcher_uses_strict_profile_before_real_runner_boundary():
    engine = FakeEngine()
    manager = object()
    calls = []

    def builder(**kwargs):
        calls.append("builder")
        return engine, manager

    def runner(received):
        calls.append("runner")
        assert received is engine
        assert received.market_data_gate_required is True
        assert received.market_data_max_age_seconds == 12.5
        return "paper-started"

    result, returned_manager = run_strict_profiled_paper_launcher(
        builder=builder,
        runner=runner,
        environ={PROFILE_ENV: "strict", MAX_AGE_ENV: "12.5"},
    )
    assert result == "paper-started"
    assert returned_manager is manager
    assert calls == ["builder", "runner"]


@pytest.mark.parametrize("raw_age", ["nan", "inf", "-1", "not-a-number", " "])
def test_invalid_threshold_fails_closed_without_constructing_engine(raw_age):
    calls = []
    with pytest.raises(ValueError):
        run_strict_profiled_paper_launcher(
            builder=lambda **kwargs: (calls.append("builder"), FakeEngine(), object())[1:],
            runner=lambda engine: calls.append("runner"),
            environ={PROFILE_ENV: "strict", MAX_AGE_ENV: raw_age},
        )
    assert calls == []


def test_runner_exception_propagates_without_legacy_fallback():
    calls = []

    def runner(engine):
        calls.append("strict-runner")
        raise RuntimeError("paper lifecycle failed")

    with pytest.raises(RuntimeError, match="paper lifecycle failed"):
        run_strict_profiled_paper_launcher(
            builder=lambda **kwargs: (FakeEngine(), object()),
            runner=runner,
            environ={PROFILE_ENV: "strict", MAX_AGE_ENV: "5"},
        )
    assert calls == ["strict-runner"]
