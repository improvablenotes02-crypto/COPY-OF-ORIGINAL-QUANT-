"""Phase 275: abrupt process-exit durability and restart safety."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from core.execution.submission_journal import SQLiteOrderSubmissionJournal


_CRASH_WORKER = r"""
import os
import sys
from core.execution.submission_journal import SQLiteOrderSubmissionJournal

database, client_order_id, final_state = sys.argv[1:]
journal = SQLiteOrderSubmissionJournal(database, timeout_seconds=5.0)
if not journal.reserve(client_order_id, {"symbol": "BTC", "side": "BUY"}):
    raise SystemExit(10)
if final_state != "PREPARED":
    journal.transition(client_order_id, "DISPATCHING")
if final_state in ("UNKNOWN", "ACKNOWLEDGED"):
    journal.transition(
        client_order_id,
        final_state,
        "simulated durable outcome before abrupt process exit",
    )
os._exit(73)
"""


class TestSubmissionJournalCrashRecoveryPhase275(unittest.TestCase):
    def test_committed_lifecycle_states_survive_abrupt_process_exit(self):
        scenarios = (
            ("PREPARED", True),
            ("DISPATCHING", True),
            ("UNKNOWN", True),
            ("ACKNOWLEDGED", False),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_root = Path(__file__).resolve().parents[1]
            for expected_state, should_be_unresolved in scenarios:
                with self.subTest(state=expected_state):
                    database = root / f"{expected_state.lower()}.sqlite3"
                    client_order_id = f"QE-phase275-{expected_state.lower()}"
                    process = subprocess.Popen(
                        [
                            sys.executable, "-c", _CRASH_WORKER,
                            str(database), client_order_id, expected_state,
                        ],
                        cwd=project_root,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    try:
                        stdout, stderr = process.communicate(timeout=15.0)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate(timeout=5.0)
                        self.fail(f"{expected_state} crash worker exceeded timeout")

                    self.assertEqual(
                        process.returncode, 73,
                        f"worker missed abrupt-exit checkpoint: {stdout} {stderr}",
                    )
                    recovered = SQLiteOrderSubmissionJournal(
                        database, timeout_seconds=1.0
                    )
                    record = recovered.get(client_order_id)
                    self.assertIsNotNone(record)
                    self.assertEqual(record["state"], expected_state)
                    self.assertFalse(recovered.reserve(
                        client_order_id, {"symbol": "BTC", "side": "BUY"}
                    ))
                    unresolved_ids = {
                        row["client_order_id"] for row in recovered.unresolved()
                    }
                    self.assertEqual(
                        client_order_id in unresolved_ids, should_be_unresolved
                    )


if __name__ == "__main__":
    unittest.main()
