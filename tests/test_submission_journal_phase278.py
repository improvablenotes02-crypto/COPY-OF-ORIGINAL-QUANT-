"""Phase 278: journal-level evidence binding for UNKNOWN resolution."""
import tempfile
import unittest
from pathlib import Path

from core.execution.submission_journal import (
    DISPATCHING, REJECTED, UNKNOWN, SQLiteOrderSubmissionJournal,
    SubmissionJournalError,
)


class TestUnknownResolutionEvidencePhase278(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = SQLiteOrderSubmissionJournal(Path(self.tmp.name) / "orders.db")
        self.journal.reserve("QE-278", {"symbol": "BTC", "qty": 1})
        self.journal.transition("QE-278", UNKNOWN)

    def tearDown(self):
        self.tmp.cleanup()

    def test_unknown_cannot_be_resolved_without_evidence_digest(self):
        with self.assertRaisesRegex(SubmissionJournalError, "requires.*SHA-256"):
            self.journal.transition("QE-278", REJECTED, "manual-resolution")
        self.assertEqual(self.journal.get("QE-278")["state"], UNKNOWN)

    def test_unknown_rejects_malformed_evidence_digest(self):
        for digest in ("", "not-a-digest", "A" * 64, "0" * 63):
            with self.subTest(digest=digest):
                with self.assertRaisesRegex(SubmissionJournalError, "requires.*SHA-256"):
                    self.journal.transition(
                        "QE-278", REJECTED, "manual-resolution",
                        evidence_sha256=digest,
                    )
                self.assertEqual(self.journal.get("QE-278")["state"], UNKNOWN)

    def test_unknown_resolution_persists_evidence_digest_reference(self):
        digest = "a" * 64
        self.journal.transition(
            "QE-278", REJECTED, "venue-history:complete",
            evidence_sha256=digest,
        )
        row = self.journal.get("QE-278")
        self.assertEqual(row["state"], REJECTED)
        self.assertIn(f"evidence_sha256={digest}", row["detail"])

    def test_non_unknown_lifecycle_does_not_require_reconciliation_digest(self):
        self.journal.reserve("QE-278-dispatch", {"symbol": "ETH"})
        self.journal.transition("QE-278-dispatch", DISPATCHING)
        self.assertEqual(self.journal.get("QE-278-dispatch")["state"], DISPATCHING)


if __name__ == "__main__":
    unittest.main()
