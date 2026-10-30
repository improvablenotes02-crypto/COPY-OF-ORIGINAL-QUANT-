"""Phase 213 deployment-profile coverage for canonical PAPER startup."""
import pytest

from core.runtime.paper_gate_profile import (
    MAX_AGE_ENV,
    PROFILE_ENV,
    resolve_paper_gate_profile,
)


def test_default_profile_preserves_compatibility():
    assert resolve_paper_gate_profile({}) == {
        "market_data_max_age_seconds": None,
        "market_data_gate_required": False,
    }


def test_compat_profile_can_enable_optional_gate():
    config = resolve_paper_gate_profile({
        PROFILE_ENV: "compat",
        MAX_AGE_ENV: "12.5",
    })
    assert config == {
        "market_data_max_age_seconds": 12.5,
        "market_data_gate_required": False,
    }


def test_strict_profile_requires_valid_threshold():
    with pytest.raises(ValueError, match="required"):
        resolve_paper_gate_profile({PROFILE_ENV: "strict"})
    config = resolve_paper_gate_profile({
        PROFILE_ENV: "strict",
        MAX_AGE_ENV: "30",
    })
    assert config == {
        "market_data_max_age_seconds": 30.0,
        "market_data_gate_required": True,
    }


@pytest.mark.parametrize("value", ["", "-1", "nan", "inf", "True", "bad"])
def test_strict_profile_rejects_invalid_threshold(value):
    with pytest.raises(ValueError):
        resolve_paper_gate_profile({PROFILE_ENV: "strict", MAX_AGE_ENV: value})


def test_unknown_profile_fails_closed():
    with pytest.raises(ValueError, match="must be 'compat' or 'strict'"):
        resolve_paper_gate_profile({PROFILE_ENV: "surprise", MAX_AGE_ENV: "10"})



def test_profiled_builder_applies_config_before_returning_engine():
    from core.runtime.paper_gate_profile import build_profiled_paper_engine

    class Engine:
        market_data_max_age_seconds = None
        market_data_gate_required = False
        market_data_now_provider = None

    engine = Engine()
    manager = object()

    def builder(**kwargs):
        assert kwargs == {"marker": 7}
        return engine, manager

    built, returned_manager = build_profiled_paper_engine(
        marker=7,
        builder=builder,
        environ={PROFILE_ENV: "strict", MAX_AGE_ENV: "8"},
    )
    assert built is engine
    assert returned_manager is manager
    assert built.market_data_max_age_seconds == 8.0
    assert built.market_data_gate_required is True
    assert built.market_data_now_provider is None
