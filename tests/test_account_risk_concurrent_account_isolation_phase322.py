"""Phase 322: concurrent settlements remain isolated across account scopes."""
import json
import subprocess
import sys
import time
from pathlib import Path

from core.accounts.account_risk import (
    AccountRiskProfile, AccountRiskScope, AccountRiskState, OrderRiskProposal,
)
from core.accounts.persistent_account_risk import (
    AccountRiskReconciliationEvidence, SQLiteAccountRiskRepository,
    hash_account_risk_state,
)


_WORKER = r"""
import json, sys, time
from dataclasses import replace
from pathlib import Path
from core.accounts.account_risk import AccountRiskScope
from core.accounts.persistent_account_risk import (
    AccountRiskReconciliationEvidence, SQLiteAccountRiskRepository,
    hash_account_risk_state,
)
database, account_id, provider_id, reservation_id, ready, gate = sys.argv[1:]
repository = SQLiteAccountRiskRepository(database)
scope = AccountRiskScope(
    tenant_id="tenant-phase322", account_id=account_id,
    provider_account_id=provider_id, region="INDIA", environment="SANDBOX",
)
stored = repository.get(scope)
if stored is None:
    raise SystemExit("worker account state missing")
_, current = stored
projected = replace(current, pending_orders=current.pending_orders - 1,
                    pending_exposure=current.pending_exposure - 500.0)
evidence = AccountRiskReconciliationEvidence(
    scope=scope, reservation_id=reservation_id, client_order_id=reservation_id,
    source="DELTA_AUTHENTICATED_READ", exchange_order_id="delta-" + account_id,
    terminal_status="REJECTED", observed_at="2026-11-06T00:00:00+00:00",
    snapshot_hash=("c" if account_id.endswith("a") else "d") * 64,
    risk_state_hash=hash_account_risk_state(projected),
    identity_verified=True, orders_complete=True, fills_complete=True,
    positions_complete=True, open_order_absent=True,
)
Path(ready).write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 15
while not Path(gate).exists():
    if time.monotonic() >= deadline:
        raise SystemExit("account-isolation gate timed out")
    time.sleep(0.01)
settled = repository.settle_reservation(
    scope=scope, reservation_id=reservation_id,
    expected_revision=current.revision, reconciled_state=projected,
    evidence=evidence,
)
print(json.dumps({"account": account_id, "settled": settled}, sort_keys=True))
repository.close()
"""


def _scope(account, provider):
    return AccountRiskScope(
        tenant_id="tenant-phase322", account_id=account,
        provider_account_id=provider, region="INDIA", environment="SANDBOX",
    )


def _profile():
    return AccountRiskProfile(
        risk_per_trade_fraction=0.01, max_order_notional=1000.0,
        max_leverage=2.0, max_daily_loss_fraction=0.05,
        max_weekly_loss_fraction=0.10, max_monthly_loss_fraction=0.20,
        max_total_exposure_fraction=1.5, max_open_positions=10,
        max_pending_orders=5,
    )


def test_concurrent_settlements_for_two_accounts_do_not_cross_mutate_state(tmp_path):
    database = tmp_path / "account-isolation-settlement.sqlite"
    repository = SQLiteAccountRiskRepository(str(database))
    accounts = (("account-a", "99201", "QE-phase322-a"),
                ("account-b", "99202", "QE-phase322-b"))
    for account, provider, reservation_id in accounts:
        scope = _scope(account, provider)
        repository.register(
            scope=scope, profile=_profile(),
            initial_state=AccountRiskState(
                scope=scope, risk_basis=10000.0, equity=10000.0, revision=0,
            ),
        )
        decision, reservation = repository.reserve_order(
            reservation_id=reservation_id,
            proposal=OrderRiskProposal(
                scope=scope, risk_amount=25.0, notional=500.0, leverage=1.0,
            ),
        )
        assert decision.allowed and reservation is not None

    gate = tmp_path / "settlement.gate"
    ready = [tmp_path / "account-a.ready", tmp_path / "account-b.ready"]
    processes = []
    try:
        for (account, provider, reservation_id), ready_path in zip(accounts, ready):
            processes.append(subprocess.Popen(
                [sys.executable, "-c", _WORKER, str(database), account, provider,
                 reservation_id, str(ready_path), str(gate)],
                cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            ))
        deadline = time.monotonic() + 20
        while not all(path.exists() for path in ready):
            if time.monotonic() >= deadline:
                raise AssertionError("both account workers did not become ready")
            if any(process.poll() is not None for process in processes):
                raise AssertionError("account worker exited before start gate")
            time.sleep(0.01)
        gate.touch()
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=25)
            assert process.returncode == 0, stderr
            results.append(json.loads(stdout.strip()))
        assert {item["account"] for item in results} == {"account-a", "account-b"}
        assert all(item["settled"] is True for item in results)

        for account, provider, reservation_id in accounts:
            scope = _scope(account, provider)
            _, state = repository.get(scope)
            assert state.pending_orders == 0
            assert state.pending_exposure == 0.0
            assert state.revision == 2
            assert repository.list_pending_reservations(scope) == ()
            evidence = repository.get_reservation_evidence(
                scope=scope, reservation_id=reservation_id,
            )
            assert evidence is not None
            assert evidence.scope == scope
            assert evidence.reservation_id == reservation_id
            assert evidence.risk_state_hash == hash_account_risk_state(
                AccountRiskState(
                    scope=scope, risk_basis=state.risk_basis, equity=state.equity,
                    daily_pnl=state.daily_pnl, weekly_pnl=state.weekly_pnl,
                    monthly_pnl=state.monthly_pnl, open_positions=state.open_positions,
                    pending_orders=0, current_exposure=state.current_exposure,
                    pending_exposure=0.0, kill_switch=state.kill_switch,
                    trading_enabled=state.trading_enabled, revision=1,
                )
            )
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
        repository.close()
