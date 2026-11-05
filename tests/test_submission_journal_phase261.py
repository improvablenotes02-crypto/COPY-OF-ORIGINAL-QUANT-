import tempfile
import threading
import unittest
from pathlib import Path

from core.execution.submission_journal import (
    ACKNOWLEDGED, DISPATCHING, RECONCILED, UNKNOWN,
    SQLiteOrderSubmissionJournal, SubmissionJournalError,
)


class TestSQLiteOrderSubmissionJournal(unittest.TestCase):
    def journal(self, root):
        return SQLiteOrderSubmissionJournal(Path(root) / "orders.sqlite3")

    def test_restart_blocks_duplicate_and_exposes_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.journal(tmp)
            self.assertTrue(first.reserve("QE-1", {"symbol": "BTC", "size": 2}))
            first.transition("QE-1", DISPATCHING)
            restarted = self.journal(tmp)
            self.assertFalse(restarted.reserve("QE-1", {"symbol": "BTC", "size": 2}))
            self.assertEqual(restarted.get("QE-1")["state"], DISPATCHING)
            self.assertEqual(len(restarted.unresolved()), 1)

    def test_ambiguous_state_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = self.journal(tmp)
            first.reserve("QE-timeout", {"side": "buy"})
            first.transition("QE-timeout", DISPATCHING)
            first.transition("QE-timeout", UNKNOWN, "transport timeout")
            restarted = self.journal(tmp)
            self.assertEqual(restarted.get("QE-timeout")["state"], UNKNOWN)
            self.assertFalse(restarted.reserve("QE-timeout", {"side": "buy"}))

    def test_concurrent_reservation_has_one_winner(self):
        with tempfile.TemporaryDirectory() as tmp:
            journals = [self.journal(tmp) for _ in range(6)]
            barrier = threading.Barrier(len(journals))
            results = []
            lock = threading.Lock()

            def reserve(journal):
                barrier.wait()
                result = journal.reserve("QE-race", {"qty": 1})
                with lock:
                    results.append(result)

            threads = [threading.Thread(target=reserve, args=(j,)) for j in journals]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(results.count(True), 1)
            self.assertEqual(results.count(False), len(journals) - 1)

    def test_payload_is_represented_only_by_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = self.journal(tmp)
            journal.reserve("QE-digest", {"symbol": "BTC"})
            record = journal.get("QE-digest")
            self.assertEqual(len(record["payload_sha256"]), 64)
            self.assertNotIn("BTC", str(record))

    def test_invalid_transition_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = self.journal(tmp)
            journal.reserve("QE-state", {})
            with self.assertRaises(SubmissionJournalError):
                journal.transition("QE-state", ACKNOWLEDGED)
            journal.transition("QE-state", RECONCILED)
            self.assertEqual(journal.unresolved(), [])


if __name__ == "__main__":
    unittest.main()
