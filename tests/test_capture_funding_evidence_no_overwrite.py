"""No-overwrite guarantees for funding evidence capture outputs."""
import tempfile
import unittest
from pathlib import Path
from scripts.capture_funding_evidence import _write_new_pair

class TestFundingEvidenceNoOverwrite(unittest.TestCase):
    def test_existing_raw_artifact_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); raw=root/"raw.json"; bound=root/"bound.json"
            raw.write_text("original raw",encoding="utf-8")
            with self.assertRaises(FileExistsError):
                _write_new_pair(raw,"new raw",bound,"new bound")
            self.assertEqual(raw.read_text(encoding="utf-8"),"original raw")
            self.assertFalse(bound.exists())

    def test_existing_bound_artifact_rolls_back_only_new_raw_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); raw=root/"raw.json"; bound=root/"bound.json"
            bound.write_text("original bound",encoding="utf-8")
            with self.assertRaises(FileExistsError):
                _write_new_pair(raw,"new raw",bound,"new bound")
            self.assertFalse(raw.exists())
            self.assertEqual(bound.read_text(encoding="utf-8"),"original bound")

    def test_new_pair_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); raw=root/"raw.json"; bound=root/"bound.json"
            _write_new_pair(raw,"raw payload",bound,"bound payload")
            self.assertEqual(raw.read_text(encoding="utf-8"),"raw payload")
            self.assertEqual(bound.read_text(encoding="utf-8"),"bound payload")

if __name__ == "__main__":
    unittest.main()
