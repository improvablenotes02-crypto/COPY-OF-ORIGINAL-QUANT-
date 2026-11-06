"""Phase 324: semantic corruption in persisted account risk state fails closed."""
import json

import pytest

from core.accounts.account_risk import (
    AccountRiskError, AccountRiskProfile, AccountRiskScope, AccountRiskState,
)
from core.accounts.persistent_account_risk import SQLiteAccountRiskRepository


def _scope():
    return AccountRiskScope(
        tenant_id="tenant-phase324", account_id="account-phase324",
        provider_account_id="99401", region="INDIA", environment="SANDBOX",
    )


def _profile():
    return AccountRiskProfile(
        risk_per_trade_fraction=0.01, max_order_notional=1000.0,
        max_leverage=2.0, max_daily_loss_fraction=0.05,
        max_weekly_loss_fraction=0.10, max_monthly_loss_fraction=0.20,
        max_total_exposure_fraction=1.5, max_open_positions=10,
        max_pending_orders=5,
    )


def test_invalid_persisted_risk_state_is_rejected_without_silent_repair(tmp_path):
    database = tmp_path / "semantic-corruption.sqlite"
    repository = SQLiteAccountRiskRepository(str(database))
    scope = _scope()
    repository.register(
        scope=scope, profile=_profile(),
        initial_state=AccountRiskState(
            scope=scope, risk_basis=10000.0, equity=10000.0, revision=0,
        ),
    )
    original = repository._connection.execute(
        "SELECT state_json FROM account_risk_state WHERE tenant_id = ? AND account_id = ?",
        (scope.tenant_id, scope.account_id),
    ).fetchone()[0]
    corrupted = json.loads(original)
    corrupted["pending_exposure"] = -1.0
    repository._connection.execute(
        "UPDATE account_risk_state SET state_json = ? WHERE tenant_id = ? AND account_id = ?",
        (json.dumps(corrupted, sort_keys=True, separators=(",", ":")),
         scope.tenant_id, scope.account_id),
    )
    try:
        with pytest.raises(AccountRiskError, match="pending_exposure"):
            repository.get(scope)
        # SQLite page integrity is not enough: application invariants must also pass.
        assert repository._connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert repository._connection.execute("PRAGMA foreign_key_check").fetchall() == []
        # Recovery is explicit: restore the known-good serialized state, never auto-heal.
        repository._connection.execute(
            "UPDATE account_risk_state SET state_json = ? WHERE tenant_id = ? AND account_id = ?",
            (original, scope.tenant_id, scope.account_id),
        )
        restored = repository.get(scope)
        assert restored is not None
        assert restored[1].pending_exposure == 0.0
        assert restored[1].revision == 0
    finally:
        repository.close()
