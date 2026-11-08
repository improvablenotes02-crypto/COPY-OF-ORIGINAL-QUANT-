"""Phase 279: competing cross-process lifecycle transitions are serialized."""
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from core.execution.submission_journal import (
    ACKNOWLEDGED,
    DISPATCHING,
    REJECTED,
    SQLiteOrderSubmissionJournal,
)


_TRANSITION_WORKER = r"""
import sys
import time
from pathlib import Path
from core.execution.submission_journal import (
    SQLiteOrderSubmissionJournal, SubmissionJournalError,
)

database, client_id, target_state, ready, gate, result = sys.argv[1:]
ready_path, gate_path, result_path = map(Path, (ready, gate, result))
journal = SQLiteOrderSubmissionJournal(database, timeout_seconds=8.0)
ready_path.write_text("ready", encoding="utf-8")
deadline = time.monotonic() + 12.0
while not gate_path.exists():
    if time.monotonic() >= deadline:
        raise SystemExit("transition start gate timed out")
    time.sleep(0.01)
try:
    journal.transition(client_id, target_state, "cross-process race")
except SubmissionJournalError:
    result_path.write_text("rejected", encoding="utf-8")
else:
    result_path.write_text("committed", encoding="utf-8")
"""


class TestSubmissionJournalTransitionRacePhase279(unittest.TestCase):
    def test_competing_terminal_transitions_commit_exactly_one_winner(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "journal.sqlite3"
            client_id = "QE-phase279-transition-race"
            journal = SQLiteOrderSubmissionJournal(database, timeout_seconds=8.0)
            journal.reserve(client_id, {"symbol": "BTC", "side": "BUY"})
            journal.transition(client_id, DISPATCHING)

            ready = [root / "ack.ready", root / "reject.ready"]
            results = [root / "ack.result", root / "reject.result"]
            gate = root / "start.gate"
            project_root = Path(__file__).resolve().parents[1]
            processes = []
            try:
                for state, ready_path, result_path in zip(
                    (ACKNOWLEDGED, REJECTED), ready, results
                ):
                    processes.append(subprocess.Popen(
                        [
                            sys.executable, "-c", _TRANSITION_WORKER,
                            str(database), client_id, state,
                            str(ready_path), str(gate), str(result_path),
                        ],
                        cwd=project_root,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    ))
                deadline = time.monotonic() + 15.0
                while not all(path.exists() for path in ready):
                    if time.monotonic() >= deadline:
                        self.fail("transition workers did not become ready")
                    if any(process.poll() is not None for process in processes):
                        self.fail("transition worker exited before start gate")
                    time.sleep(0.01)

                gate.touch()
                for process in processes:
                    stdout, stderr = process.communicate(timeout=20.0)
                    self.assertEqual(process.returncode, 0, f"{stdout} {stderr}")

                self.assertCountEqual(
                    [path.read_text(encoding="utf-8") for path in results],
                    ["committed", "rejected"],
                )
                final = journal.get(client_id)
                self.assertIn(final["state"], (ACKNOWLEDGED, REJECTED))
                self.assertTrue(journal.validate_integrity())
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5.0)


if __name__ == "__main__":
    unittest.main()
