"""Phase 323: abrupt process exit before COMMIT leaves risk state unchanged."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from core.accounts.account_risk import (
    AccountRiskProfile, AccountRiskScope, AccountRiskState,
)
from core.accounts.persistent_account_risk import SQLiteAccountRiskRepository


_WORKER = r"""
import os, sqlite3, sys, time
from pathlib import Path
database, ready, gate = sys.argv[1:]
connection = sqlite3.connect(database, timeout=10.0, isolation_level=None)
connection.execute("PRAGMA busy_timeout = 10000")
connection.execute("BEGIN IMMEDIATE")
connection.execute(
    "UPDATE account_risk_state SET revision = revision + 99 "
    "WHERE tenant_id = 'tenant-phase323' AND account_id = 'account-phase323'"
)
if connection.execute("SELECT changes()").fetchone()[0] != 1:
    raise SystemExit("crash worker did not update exactly one risk row")
Path(ready).write_text("transaction-open", encoding="utf-8")
deadline = time.monotonic() + 15
while not Path(gate).exists():
    if time.monotonic() >= deadline:
        raise SystemExit("crash gate timed out")
    time.sleep(0.01)
os._exit(73)  # Deliberately bypass Python cleanup and SQLite COMMIT/ROLLBACK.
"""


def _scope():
    return AccountRiskScope(
        tenant_id="tenant-phase323", account_id="account-phase323",
        provider_account_id="99301", region="INDIA", environment="SANDBOX",
    )


def _profile():
    return AccountRiskProfile(
        risk_per_trade_fraction=0.01, max_order_notional=1000.0,
        max_leverage=2.0, max_daily_loss_fraction=0.05,
        max_weekly_loss_fraction=0.10, max_monthly_loss_fraction=0.20,
        max_total_exposure_fraction=1.5, max_open_positions=10,
        max_pending_orders=5,
    )


def test_process_exit_inside_uncommitted_risk_transaction_recovers_to_last_commit(tmp_path):
    database = tmp_path / "risk-process-crash.sqlite"
    repository = SQLiteAccountRiskRepository(str(database))
    scope = _scope()
    repository.register(
        scope=scope, profile=_profile(),
        initial_state=AccountRiskState(
            scope=scope, risk_basis=10000.0, equity=10000.0, revision=0,
        ),
    )
    before = repository.get(scope)
    ready, gate = tmp_path / "transaction.ready", tmp_path / "crash.gate"
    process = subprocess.Popen(
        [sys.executable, "-c", _WORKER, str(database), str(ready), str(gate)],
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 20
        while not ready.exists():
            if time.monotonic() >= deadline:
                raise AssertionError("crash worker did not enter transaction")
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise AssertionError(f"crash worker exited early: {stdout} {stderr}")
            time.sleep(0.01)
        gate.touch()
        stdout, stderr = process.communicate(timeout=20)
        assert process.returncode == 73, (stdout, stderr)

        # Close the pre-crash connection and reopen through a fresh repository.
        repository.close()
        recovered = SQLiteAccountRiskRepository(str(database))
        try:
            after = recovered.get(scope)
            assert after == before
            assert recovered._connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert recovered._connection.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            recovered.close()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if not repository._connection is None:
            try:
                repository.close()
            except Exception:
                pass
