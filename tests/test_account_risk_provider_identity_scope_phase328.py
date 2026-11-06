"""Phase 328: provider-account identity is part of persisted risk scope."""
from dataclasses import replace

import pytest

from core.accounts.account_risk import (
    AccountRiskError, AccountRiskProfile, AccountRiskScope, AccountRiskState,
    OrderRiskProposal,
)
from core.accounts.persistent_account_risk import SQLiteAccountRiskRepository


def _scope():
    return AccountRiskScope(
        tenant_id="tenant-phase328", account_id="logical-account",
        provider_account_id="99801", region="INDIA", environment="SANDBOX",
    )


def _profile():
    return AccountRiskProfile(
        risk_per_trade_fraction=0.01, max_order_notional=1000.0,
        max_leverage=2.0, max_daily_loss_fraction=0.05,
        max_weekly_loss_fraction=0.10, max_monthly_loss_fraction=0.20,
        max_total_exposure_fraction=1.5, max_open_positions=10,
        max_pending_orders=5,
    )


def test_provider_identity_alias_cannot_read_or_mutate_another_persisted_scope(tmp_path):
    database = str(tmp_path / "provider-scope.sqlite")
    canonical = _scope()
    alias = replace(canonical, provider_account_id="99802")
    reservation_id = "QE-phase328-provider-bound"
    repository = SQLiteAccountRiskRepository(database)
    try:
        repository.register(
            scope=canonical, profile=_profile(),
            initial_state=AccountRiskState(
                scope=canonical, risk_basis=10000.0, equity=10000.0, revision=0,
            ),
        )
        decision, reservation = repository.reserve_order(
            reservation_id=reservation_id,
            proposal=OrderRiskProposal(
                scope=canonical, risk_amount=25.0, notional=500.0, leverage=1.0,
            ),
        )
        assert decision.allowed and reservation is not None
        repository.close()

        recovered = SQLiteAccountRiskRepository(database)
        try:
            with pytest.raises(AccountRiskError, match="persisted risk scope"):
                recovered.get(alias)
            with pytest.raises(AccountRiskError, match="persisted risk scope"):
                recovered.list_pending_reservations(alias)
            with pytest.raises(AccountRiskError, match="persisted risk scope"):
                recovered.release_reservation(
                    scope=alias, reservation_id=reservation_id,
                )
            _, original_state = recovered.get(canonical)
            assert original_state.pending_orders == 1
            assert original_state.pending_exposure == 500.0
            assert original_state.revision == 1
            assert len(recovered.list_pending_reservations(canonical)) == 1
            with pytest.raises(AccountRiskError, match="already registered"):
                recovered.register(
                    scope=alias, profile=_profile(),
                    initial_state=AccountRiskState(
                        scope=alias, risk_basis=10000.0, equity=10000.0,
                        revision=0,
                    ),
                )
        finally:
            recovered.close()
    except Exception:
        try:
            repository.close()
        except Exception:
            pass
        raise
