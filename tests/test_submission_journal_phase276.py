"""Phase 276: cross-process no-clobber backup and restore publication."""
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from core.execution.submission_journal import SQLiteOrderSubmissionJournal


_PUBLISH_WORKER = r"""
import sys
import time
from pathlib import Path
from core.execution.submission_journal import (
    SQLiteOrderSubmissionJournal, SubmissionJournalError,
)

operation, source, target, ready, gate, result = sys.argv[1:]
ready_path, gate_path, result_path = map(Path, (ready, gate, result))
if operation == "backup":
    journal = SQLiteOrderSubmissionJournal(source, timeout_seconds=5.0)
else:
    journal = None
ready_path.write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 15.0
while not gate_path.exists():
    if time.monotonic() >= deadline:
        raise SystemExit("publication start gate timed out")
    time.sleep(0.01)
try:
    if operation == "backup":
        journal.backup_to(target)
    elif operation == "restore":
        SQLiteOrderSubmissionJournal.restore_from(source, target)
    else:
        raise SystemExit("unknown publication operation")
except SubmissionJournalError:
    result_path.write_text("rejected", encoding="utf-8")
else:
    result_path.write_text("published", encoding="utf-8")
"""


class TestSubmissionJournalCrossProcessPublicationPhase276(unittest.TestCase):
    def _race(self, root, operation, source, target):
        ready = [root / "publisher-a.ready", root / "publisher-b.ready"]
        results = [root / "publisher-a.result", root / "publisher-b.result"]
        gate = root / "publish.gate"
        project_root = Path(__file__).resolve().parents[1]
        processes = []
        try:
            for ready_path, result_path in zip(ready, results):
                processes.append(subprocess.Popen(
                    [
                        sys.executable, "-c", _PUBLISH_WORKER,
                        operation, str(source), str(target),
                        str(ready_path), str(gate), str(result_path),
                    ],
                    cwd=project_root,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                ))
            deadline = time.monotonic() + 20.0
            while not all(path.exists() for path in ready):
                if time.monotonic() >= deadline:
                    self.fail("publication workers did not become ready")
                if any(process.poll() is not None for process in processes):
                    self.fail("publication worker exited before the start gate")
                time.sleep(0.01)
            gate.touch()
            for process in processes:
                stdout, stderr = process.communicate(timeout=25.0)
                self.assertEqual(process.returncode, 0, f"{stdout} {stderr}")
            return [path.read_text(encoding="utf-8") for path in results]
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5.0)

    def test_two_processes_racing_to_publish_backup_have_one_winner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = root / "live.sqlite3"
            journal = SQLiteOrderSubmissionJournal(live)
            journal.reserve("QE-phase276-backup", {"symbol": "BTC"})
            target = root / "shared-backup.sqlite3"

            outcomes = self._race(root, "backup", live, target)

            self.assertCountEqual(outcomes, ["published", "rejected"])
            inventory = SQLiteOrderSubmissionJournal._validate_database_file(target)
            self.assertEqual(inventory["record_count"], 1)
            self.assertEqual(inventory["unresolved_count"], 1)

    def test_two_processes_racing_to_restore_have_one_winner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = SQLiteOrderSubmissionJournal(root / "live.sqlite3")
            live.reserve("QE-phase276-restore", {"symbol": "ETH"})
            backup = live.backup_to(root / "source-backup.sqlite3")["path"]
            target = root / "restored.sqlite3"

            outcomes = self._race(root, "restore", backup, target)

            self.assertCountEqual(outcomes, ["published", "rejected"])
            restored = SQLiteOrderSubmissionJournal(target)
            self.assertEqual(
                restored.get("QE-phase276-restore")["state"], "PREPARED"
            )
            self.assertTrue(restored.validate_integrity())


if __name__ == "__main__":
    unittest.main()
