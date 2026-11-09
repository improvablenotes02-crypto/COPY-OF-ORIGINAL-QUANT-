"""Phase 477: one-command operator doctor remains read-only and fail-closed."""
from scripts.quantengine_doctor import run_doctor


def test_doctor_stops_before_network_when_offline_preflight_fails():
    calls = []
    output = []
    report = {
        "ready_for_authenticated_read_only_check": False,
        "region": "INDIA", "environment": "SANDBOX",
        "errors": ("Selected Delta credential pair is unavailable",),
    }
    result = run_doctor(
        preflight=lambda: report,
        connection_check=lambda **kwargs: calls.append("network"),
        emit=output.append,
    )
    assert result == 1
    assert calls == []
    assert "No network request was attempted." in output
    assert "credential pair is unavailable" in "\n".join(output)


def test_doctor_runs_only_the_readonly_connectivity_check_after_preflight():
    calls = []
    output = []
    report = {
        "ready_for_authenticated_read_only_check": True,
        "region": "INDIA", "environment": "SANDBOX",
        "errors": (),
    }
    def connection_check(*, emit):
        calls.append("read-only-connection")
        emit("Exchange writes: NOT USED")
        return 0

    result = run_doctor(
        preflight=lambda: report,
        connection_check=connection_check,
        emit=output.append,
    )
    assert result == 0
    assert calls == ["read-only-connection"]
    assert "Offline configuration preflight: PASS" in output
    assert "Exchange writes: NOT USED" in output


def test_doctor_propagates_connectivity_failure():
    report = {
        "ready_for_authenticated_read_only_check": True,
        "region": "GLOBAL", "environment": "PRODUCTION", "errors": (),
    }
    assert run_doctor(
        preflight=lambda: report,
        connection_check=lambda **kwargs: 1,
        emit=lambda _: None,
    ) == 1
