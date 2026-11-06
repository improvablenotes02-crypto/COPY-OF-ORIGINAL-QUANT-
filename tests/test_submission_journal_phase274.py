"""Phase 274: read isolation and cross-process submission reservation."""
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from core.execution.submission_journal import SQLiteOrderSubmissionJournal


_WORKER = r"""
import sys
import time
from pathlib import Path
from core.execution.submission_journal import SQLiteOrderSubmissionJournal

db_path, client_id, ready_path, gate_path = map(Path, sys.argv[1:])
journal = SQLiteOrderSubmissionJournal(db_path, timeout_seconds=8.0)
ready_path.write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 12.0
while not gate_path.exists():
    if time.monotonic() >= deadline:
        raise SystemExit("start gate timed out")
    time.sleep(0.01)
print("1" if journal.reserve(str(client_id), {"symbol": "BTC", "side": "BUY"}) else "0")
"""


class TestSubmissionJournalConcurrencyPhase274(unittest.TestCase):
    def test_health_report_reads_while_another_connection_holds_reserved_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.sqlite3"
            journal = SQLiteOrderSubmissionJournal(path, timeout_seconds=0.1)
            journal.reserve("QE-phase274-lock", {"symbol": "BTC"})
            writer = sqlite3.connect(path, timeout=0.1, isolation_level=None)
            try:
                writer.execute("BEGIN IMMEDIATE")
                report = journal.health_report()
                self.assertTrue(report["integrity_valid"])
                self.assertEqual(report["record_count"], 1)
            finally:
                if writer.in_transaction:
                    writer.execute("ROLLBACK")
                writer.close()

    def test_two_processes_cannot_reserve_the_same_client_order_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "journal.sqlite3"
            journal = SQLiteOrderSubmissionJournal(db_path, timeout_seconds=8.0)
            ready = [root / "worker-a.ready", root / "worker-b.ready"]
            gate = root / "start.gate"
            processes = []
            try:
                for ready_path in ready:
                    processes.append(subprocess.Popen(
                        [sys.executable, "-c", _WORKER, str(db_path),
                         "QE-phase274-cross-process", str(ready_path), str(gate)],
                        cwd=Path(__file__).resolve().parents[1],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    ))
                deadline = time.monotonic() + 15.0
                while not all(path.exists() for path in ready):
                    if time.monotonic() >= deadline:
                        self.fail("reservation workers did not become ready")
                    if any(process.poll() is not None for process in processes):
                        self.fail("reservation worker exited before start gate")
                    time.sleep(0.01)
                gate.touch()
                results = []
                for process in processes:
                    stdout, stderr = process.communicate(timeout=20.0)
                    self.assertEqual(process.returncode, 0, stderr)
                    results.append(stdout.strip())
                self.assertCountEqual(results, ["0", "1"])
                self.assertEqual(
                    journal.get("QE-phase274-cross-process")["state"], "PREPARED"
                )
                self.assertEqual(len(journal.unresolved()), 1)
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5.0)


if __name__ == "__main__":
    unittest.main()
