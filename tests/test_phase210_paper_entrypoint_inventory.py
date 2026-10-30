"""Phase 210: make paper-ingestion protection boundaries explicit.

These tests intentionally document both gated and legacy entrypoints. They do
not claim that every paper API is guarded by default; callers must choose a
quality-gated path or configure the canonical RealTimeEngine/PaperRuntime.
"""
import inspect

from core.paper_trading.paper_trading_engine import PaperTradingEngine
from core.runtime.gated_paper_entrypoints import (
    GatedPaperTradingEngine,
    GatedVerifiedPaperRuntime,
)
from core.runtime.paper_runtime import PaperRuntime
from core.runtime.realtime_engine import RealTimeEngine
from core.runtime.verified_runtime import VerifiedPaperRuntime


def test_canonical_realtime_and_paper_runtime_gate_are_opt_in_for_compatibility():
    assert inspect.signature(RealTimeEngine).parameters[
        "market_data_max_age_seconds"
    ].default is None
    assert inspect.signature(PaperRuntime).parameters[
        "market_data_max_age_seconds"
    ].default is None


def test_gated_entrypoints_require_explicit_age_threshold():
    for cls in (GatedPaperTradingEngine, GatedVerifiedPaperRuntime):
        parameter = inspect.signature(cls).parameters[
            "market_data_max_age_seconds"
        ]
        assert parameter.default is inspect.Parameter.empty
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_legacy_paper_entrypoints_remain_distinct_and_ungated():
    # This is a guardrail against accidentally claiming global enforcement.
    # The classes remain available for compatibility; use the gated variants
    # or canonical runtime with an explicit threshold when quality checks are
    # required.
    assert not issubclass(PaperTradingEngine, GatedPaperTradingEngine)
    assert not issubclass(VerifiedPaperRuntime, GatedVerifiedPaperRuntime)
