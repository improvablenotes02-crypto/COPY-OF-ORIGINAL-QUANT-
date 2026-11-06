"""Phase 319: cross-process reservation release is exactly-once and idempotent."""
import json
import subprocess
import sys
import time
from pathlib import Path

from core.accounts.account_risk import (
    AccountRiskProfile,
    AccountRiskScope,
    AccountRiskState,
    OrderRiskProposal,
)
from core.accounts.persistent_account_risk import SQLiteAccountRiskRepository


_WORKER = r"""
import json
import sys
import time
from pathlib import Path
from core.accounts.account_risk import AccountRiskScope
from core.accounts.persistent_account_risk import SQLiteAccountRiskRepository

database, reservation_id, ready, gate = sys.argv[1:]
ready_path, gate_path = Path(ready), Path(gate)
repository = SQLiteAccountRiskRepository(database)
ready_path.write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 15.0
while not gate_path.exists():
    if time.monotonic() >= deadline:
        raise SystemExit("release gate timed out")
    time.sleep(0.01)
scope = AccountRiskScope(
    tenant_id="tenant-phase319", account_id="account-phase319",
    provider_account_id="99139", region="INDIA", environment="SANDBOX",
)
released = repository.release_reservation(
    scope=scope, reservation_id=reservation_id,
)
print(json.dumps({"released": released}, sort_keys=True))
repository.close()
"""


def _scope():
    return AccountRiskScope(
        tenant_id="tenant-phase319", account_id="account-phase319",
        provider_account_id="99139", region="INDIA", environment="SANDBOX",
    )


def _profile():
    return AccountRiskProfile(
        risk_per_trade_fraction=0.01, max_order_notional=1000.0,
        max_leverage=2.0, max_daily_loss_fraction=0.05,
        max_weekly_loss_fraction=0.10, max_monthly_loss_fraction=0.20,
        max_total_exposure_fraction=1.5, max_open_positions=10,
        max_pending_orders=5,
    )


def test_two_processes_racing_to_release_one_reservation_change_risk_once(tmp_path):
    database = tmp_path / "cross-process-release.sqlite"
    repository = SQLiteAccountRiskRepository(str(database))
    scope = _scope()
    repository.register(
        scope=scope, profile=_profile(),
        initial_state=AccountRiskState(
            scope=scope, risk_basis=10000.0, equity=10000.0, revision=0,
        ),
    )
    decision, reservation = repository.reserve_order(
        reservation_id="QE-phase319-release",
        proposal=OrderRiskProposal(
            scope=scope, risk_amount=25.0, notional=500.0, leverage=1.0,
        ),
    )
    assert decision.allowed
    assert reservation is not None

    ready = [tmp_path / "release-a.ready", tmp_path / "release-b.ready"]
    gate = tmp_path / "release.gate"
    processes = []
    try:
        for ready_path in ready:
            processes.append(subprocess.Popen(
                [
                    sys.executable, "-c", _WORKER, str(database),
                    "QE-phase319-release", str(ready_path), str(gate),
                ],
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            ))

        deadline = time.monotonic() + 20.0
        while not all(path.exists() for path in ready):
            if time.monotonic() >= deadline:
                raise AssertionError("release workers did not become ready")
            if any(process.poll() is not None for process in processes):
                raise AssertionError("release worker exited before start gate")
            time.sleep(0.01)

        gate.touch()
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=25.0)
            assert process.returncode == 0, stderr
            results.append(json.loads(stdout.strip())["released"])

        assert results.count(True) == 1
        assert results.count(False) == 1
        state = repository.get(scope)[1]
        assert state.pending_orders == 0
        assert state.pending_exposure == 0.0
        assert repository.list_pending_reservations(scope) == ()
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5.0)
        repository.close()
