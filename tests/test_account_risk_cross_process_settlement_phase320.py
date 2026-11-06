"""Phase 320: cross-process risk settlement is exactly-once and evidence-durable."""
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
from core.accounts.persistent_account_risk import (
    PersistentAccountRiskCoordinator,
    SQLiteAccountRiskRepository,
    hash_account_risk_state,
)


_WORKER = r"""
import json
import sys
import time
from pathlib import Path
from dataclasses import replace
from core.accounts.account_risk import AccountRiskScope
from core.accounts.persistent_account_risk import (
    AccountRiskReconciliationEvidence,
    SQLiteAccountRiskRepository,
    hash_account_risk_state,
)

database, reservation_id, ready, gate = sys.argv[1:]
ready_path, gate_path = Path(ready), Path(gate)
repository = SQLiteAccountRiskRepository(database)
scope = AccountRiskScope(
    tenant_id="tenant-phase320", account_id="account-phase320",
    provider_account_id="99140", region="INDIA", environment="SANDBOX",
)
stored = repository.get(scope)
if stored is None:
    raise SystemExit("risk state missing")
_, current = stored
projected = replace(current, pending_orders=current.pending_orders - 1,
                    pending_exposure=current.pending_exposure - 500.0)
evidence = AccountRiskReconciliationEvidence(
    scope=scope, reservation_id=reservation_id, client_order_id=reservation_id,
    source="DELTA_AUTHENTICATED_READ", exchange_order_id="delta-order-phase320",
    terminal_status="REJECTED", observed_at="2026-11-06T00:00:00+00:00",
    snapshot_hash="a" * 64, risk_state_hash=hash_account_risk_state(projected),
    identity_verified=True, orders_complete=True, fills_complete=True,
    positions_complete=True, open_order_absent=True,
)
ready_path.write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 15.0
while not gate_path.exists():
    if time.monotonic() >= deadline:
        raise SystemExit("settlement gate timed out")
    time.sleep(0.01)

settled = repository.settle_reservation(
    scope=scope, reservation_id=reservation_id,
    expected_revision=current.revision, reconciled_state=projected,
    evidence=evidence,
)
print(json.dumps({"settled": settled}, sort_keys=True))
repository.close()
"""


def _scope():
    return AccountRiskScope(
        tenant_id="tenant-phase320", account_id="account-phase320",
        provider_account_id="99140", region="INDIA", environment="SANDBOX",
    )


def _profile():
    return AccountRiskProfile(
        risk_per_trade_fraction=0.01, max_order_notional=1000.0,
        max_leverage=2.0, max_daily_loss_fraction=0.05,
        max_weekly_loss_fraction=0.10, max_monthly_loss_fraction=0.20,
        max_total_exposure_fraction=1.5, max_open_positions=10,
        max_pending_orders=5,
    )


def test_two_processes_racing_to_settle_one_rejected_reservation_commit_once(tmp_path):
    database = tmp_path / "cross-process-settlement.sqlite"
    repository = SQLiteAccountRiskRepository(str(database))
    scope = _scope()
    coordinator = PersistentAccountRiskCoordinator(repository)
    coordinator.register(
        scope=scope, profile=_profile(),
        initial_state=AccountRiskState(
            scope=scope, risk_basis=10000.0, equity=10000.0, revision=0,
        ),
    )
    decision, reservation = coordinator.reserve_order(
        reservation_id="QE-phase320-settle",
        proposal=OrderRiskProposal(
            scope=scope, risk_amount=25.0, notional=500.0, leverage=1.0,
        ),
    )
    assert decision.allowed
    assert reservation is not None

    ready = [tmp_path / "settle-a.ready", tmp_path / "settle-b.ready"]
    gate = tmp_path / "settle.gate"
    processes = []
    try:
        for ready_path in ready:
            processes.append(subprocess.Popen(
                [
                    sys.executable, "-c", _WORKER, str(database),
                    "QE-phase320-settle", str(ready_path), str(gate),
                ],
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            ))

        deadline = time.monotonic() + 20.0
        while not all(path.exists() for path in ready):
            if time.monotonic() >= deadline:
                raise AssertionError("settlement workers did not become ready")
            if any(process.poll() is not None for process in processes):
                raise AssertionError("settlement worker exited before start gate")
            time.sleep(0.01)

        gate.touch()
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=25.0)
            assert process.returncode == 0, stderr
            results.append(json.loads(stdout.strip())["settled"])

        assert results.count(True) == 1
        assert results.count(False) == 1
        persisted = coordinator.get_state(scope)[1]
        assert persisted.pending_orders == 0
        assert persisted.pending_exposure == 0.0
        assert persisted.revision == 2
        assert coordinator.list_pending_reservations(scope) == ()
        evidence = coordinator.get_reservation_evidence(
            scope=scope, reservation_id="QE-phase320-settle",
        )
        assert evidence is not None
        assert evidence.terminal_status == "REJECTED"
        assert evidence.risk_state_hash == hash_account_risk_state(
            persisted.__class__(
                scope=scope, risk_basis=persisted.risk_basis,
                equity=persisted.equity, daily_pnl=persisted.daily_pnl,
                weekly_pnl=persisted.weekly_pnl, monthly_pnl=persisted.monthly_pnl,
                open_positions=persisted.open_positions, pending_orders=0,
                current_exposure=persisted.current_exposure, pending_exposure=0.0,
                kill_switch=persisted.kill_switch, trading_enabled=persisted.trading_enabled,
                revision=1,
            )
        )
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5.0)
        repository.close()
