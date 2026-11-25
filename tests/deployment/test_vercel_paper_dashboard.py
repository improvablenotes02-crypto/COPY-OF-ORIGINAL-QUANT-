import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class VercelPaperDashboardTests(unittest.TestCase):
    def test_vercel_uses_static_output_not_main_py_python_detection(self):
        config = json.loads((ROOT / "vercel.json").read_text())
        self.assertIsNone(config["framework"])
        self.assertEqual(config["outputDirectory"], "public")

    def test_static_dashboard_is_explicitly_read_only_and_fail_closed(self):
        page = (ROOT / "public" / "index.html").read_text()
        for marker in (
            "PAPER / RESEARCH ONLY",
            "Not connected",
            "PAPER ONLY",
            "LIVE_MODE",
            "LIVE_EXECUTE",
            "ALLOW_LIVE",
            "does not invent account balances",
            "No order-entry controls",
        ):
            self.assertIn(marker, page)
        self.assertNotIn('type="password"', page.lower())
        self.assertNotIn("exchange-api-key", page.lower())


if __name__ == "__main__":
    unittest.main()
