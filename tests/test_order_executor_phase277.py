"""Phase 277: preserve DISPATCHING when post-ack journal commit fails."""
import tempfile
import unittest
from pathlib import Path

from core.exchanges.contract_registry import ContractRegistry
from core.exchanges.delta.delta_contract import DeltaContract
from core.execution.live_safety_gate import LiveSafetyGate
from core.execution.order_executor import DeltaOrderExecutor
from core.execution.submission_journal import (
    DISPATCHING,
    SQLiteOrderSubmissionJournal,
    SubmissionJournalError,
)
from core.risk.order_intent import OrderIntent


def _contract():
    return DeltaContract(
        symbol="BTCUSDT",
        exchange="DELTA",
        contract_type="perpetual_futures",
        tick_size=0.01,
        quantity_step=0.001,
        min_quantity=0.00001,
        max_leverage=100.0,
        maker_fee=0.0005,
        taker_fee=0.001,
        price_precision=2,
        quantity_precision=5,
        product_id=2,
        live_execution_verified=True,
        live_execution_evidence="offline phase 277 test fixture",
    )


def _intent():
    return OrderIntent(
        direction="BULLISH",
        entry=80000.0,
        stop_loss=79500.0,
        take_profit=81000.0,
        quantity=0.0623,
        symbol="BTCUSDT",
        valid=True,
        reason="",
    )


class _AcceptedFakeExchange:
    authenticated = True

    def __init__(self):
        self.placed = []

    def post(self, path, payload=None):
        self.placed.append(payload)
        return {
            "success": True,
            "result": {
                "id": "offline-order-277",
                "product_id": payload["product_id"],
                "side": payload["side"],
                "state": "open",
            },
        }


class TestExecutorPostAcknowledgementJournalFailurePhase277(unittest.TestCase):
    def test_acknowledged_transport_with_failed_journal_transition_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "submissions.sqlite3"
            registry = ContractRegistry()
            registry.add(_contract())
            first_exchange = _AcceptedFakeExchange()
            first_journal = SQLiteOrderSubmissionJournal(database)
            original_transition = first_journal.transition

            def fail_ack_transition(client_order_id, state, detail=""):
                if state == "ACKNOWLEDGED":
                    raise SubmissionJournalError(
                        "simulated journal failure after fake venue acknowledgement"
                    )
                return original_transition(client_order_id, state, detail)

            first_journal.transition = fail_ack_transition
            first_executor = DeltaOrderExecutor(
                exchange=first_exchange,
                registry=registry,
                order_id_factory=lambda value: "QE-PHASE277-POST-ACK",
                submission_journal=first_journal,
            )

            with self.assertRaisesRegex(
                SubmissionJournalError, "after fake venue acknowledgement"
            ):
                first_executor.execute(
                    _intent(), safety=LiveSafetyGate.test_armed()
                )

            self.assertEqual(len(first_exchange.placed), 1)
            recovered = SQLiteOrderSubmissionJournal(database)
            record = recovered.get("QE-PHASE277-POST-ACK")
            self.assertEqual(record["state"], DISPATCHING)
            self.assertEqual(len(recovered.unresolved()), 1)

            # A fresh executor and journal must refuse the same ID before
            # reaching the fake transport, even though the venue response
            # was already received by the previous process path.
            retry_exchange = _AcceptedFakeExchange()
            retry_executor = DeltaOrderExecutor(
                exchange=retry_exchange,
                registry=registry,
                order_id_factory=lambda value: "QE-PHASE277-POST-ACK",
                submission_journal=recovered,
            )
            retry = retry_executor.execute(
                _intent(), safety=LiveSafetyGate.test_armed()
            )

            self.assertFalse(retry["success"])
            self.assertIn("duplicate durable", retry["reason"])
            self.assertEqual(retry_exchange.placed, [])
            self.assertEqual(
                recovered.get("QE-PHASE277-POST-ACK")["state"], DISPATCHING
            )


if __name__ == "__main__":
    unittest.main()


def test_direct_execute_respects_configured_paper_mode_and_never_writes(monkeypatch):
    from config.settings import settings
    from core.execution.live_safety_gate import LiveBlockedError

    monkeypatch.setattr(settings, "PAPER_MODE", True)
    monkeypatch.setattr(settings, "LIVE_MODE", False)
    monkeypatch.setattr(settings, "EXECUTION_MODE", "")
    monkeypatch.setattr(settings, "ALLOW_LIVE", True)
    monkeypatch.setattr(settings, "LIVE_EXECUTE", True)

    registry = ContractRegistry()
    registry.add(_contract())
    exchange = _AcceptedFakeExchange()
    exchange.api_key = "offline-key"
    exchange.api_secret = "offline-secret"
    executor = DeltaOrderExecutor(exchange=exchange, registry=registry)

    with unittest.TestCase().assertRaises(LiveBlockedError):
        executor.execute(_intent())

    assert exchange.placed == []
