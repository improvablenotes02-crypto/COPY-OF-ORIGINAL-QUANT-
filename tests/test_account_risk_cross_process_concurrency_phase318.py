"""Phase 318: cross-process account-risk reservations cannot overspend shared headroom."""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from core.accounts.account_risk import (
    AccountRiskProfile,
    AccountRiskScope,
    AccountRiskState,
)
from core.accounts.persistent_account_risk import (
    PersistentAccountRiskCoordinator,
    SQLiteAccountRiskRepository,
)


_WORKER = r"""
import json
import sys
import time
from pathlib import Path
from core.accounts.account_risk import AccountRiskScope, OrderRiskProposal
from core.accounts.persistent_account_risk import SQLiteAccountRiskRepository

database, reservation_id, ready, gate = sys.argv[1:]
ready_path, gate_path = Path(ready), Path(gate)
repository = SQLiteAccountRiskRepository(database)
ready_path.write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 15.0
while not gate_path.exists():
    if time.monotonic() >= deadline:
        raise SystemExit("reservation gate timed out")
    time.sleep(0.01)
scope = AccountRiskScope(
    tenant_id="tenant-phase318", account_id="account-phase318",
    provider_account_id="99138", region="INDIA", environment="SANDBOX",
)
proposal = OrderRiskProposal(
    scope=scope, risk_amount=25.0, notional=1000.0, leverage=1.0,
)
decision, reservation = repository.reserve_order(
    reservation_id=reservation_id, proposal=proposal,
)
print(json.dumps({"allowed": decision.allowed, "reason": decision.reason,
                  "reservation": reservation is not None}, sort_keys=True))
repository.close()
"""


def _scope():
    return AccountRiskScope(
        tenant_id="tenant-phase318", account_id="account-phase318",
        provider_account_id="99138", region="INDIA", environment="SANDBOX",
    )


def _profile():
    return AccountRiskProfile(
        risk_per_trade_fraction=0.01, max_order_notional=1000.0,
        max_leverage=2.0, max_daily_loss_fraction=0.05,
        max_weekly_loss_fraction=0.10, max_monthly_loss_fraction=0.20,
        max_total_exposure_fraction=0.15, max_open_positions=10,
        max_pending_orders=5,
    )


def test_separate_processes_cannot_overreserve_one_account_exposure_budget(tmp_path):
    database = tmp_path / "cross-process-risk.sqlite"
    repository = SQLiteAccountRiskRepository(str(database))
    coordinator = PersistentAccountRiskCoordinator(repository)
    scope = _scope()
    coordinator.register(
        scope=scope, profile=_profile(),
        initial_state=AccountRiskState(
            scope=scope, risk_basis=10000.0, equity=10000.0, revision=0,
        ),
    )

    ready = [tmp_path / "worker-a.ready", tmp_path / "worker-b.ready"]
    gate = tmp_path / "start.gate"
    processes = []
    try:
        for index, ready_path in enumerate(ready):
            processes.append(subprocess.Popen(
                [
                    sys.executable, "-c", _WORKER, str(database),
                    f"QE-phase318-{index}", str(ready_path), str(gate),
                ],
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            ))

        deadline = time.monotonic() + 20.0
        while not all(path.exists() for path in ready):
            if time.monotonic() >= deadline:
                raise AssertionError("risk reservation workers did not become ready")
            if any(process.poll() is not None for process in processes):
                raise AssertionError("risk reservation worker exited before start gate")
            time.sleep(0.01)

        gate.touch()
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=25.0)
            assert process.returncode == 0, stderr
            results.append(json.loads(stdout.strip()))

        assert sum(item["allowed"] for item in results) == 1
        assert sum(item["reason"] == "MAX_TOTAL_EXPOSURE" for item in results) == 1
        state = coordinator.get_state(scope)[1]
        assert state.pending_orders == 1
        assert state.pending_exposure == 1000.0
        assert len(coordinator.list_pending_reservations(scope)) == 1
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5.0)
        repository.close()
