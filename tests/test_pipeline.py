import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PipelineTests(unittest.TestCase):
    def test_sample_bundle_generates_v2_inventory_and_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            subprocess.run(
                [
                    sys.executable, str(ROOT / "scripts" / "analyze.py"),
                    "--from-rows", str(ROOT / "example" / "sample-rows.json"),
                    "--credit-price", "3", "--out", str(out),
                ],
                check=True, capture_output=True, text=True,
            )
            inventory_path = out / "inventory.json"
            inventory = json.loads(inventory_path.read_text())
            self.assertEqual(inventory["schema_version"], 2)
            self.assertAlmostEqual(
                inventory["totals"]["credit_coverage_pct"], 51.93, places=2
            )
            actions = {row["ACTION"] for row in inventory["candidates"]}
            self.assertIn("Keep materialization", actions)
            self.assertIn("Retune materialization", actions)
            self.assertIn("Investigate materialization", actions)
            self.assertIn("Remove materialization candidate", actions)
            self.assertIn("Optimize query/model", actions)

            html_path = out / "report.html"
            subprocess.run(
                [
                    sys.executable, str(ROOT / "scripts" / "render-html.py"),
                    "--inv", str(inventory_path), "--out", str(html_path),
                    "--customer", "Synthetic Customer",
                ],
                check=True, capture_output=True, text=True,
            )
            html = html_path.read_text()
            self.assertIn("Performance per Dollar", html)
            self.assertIn("Retune materialization", html)
            self.assertIn("Remove materialization candidate", html)


if __name__ == "__main__":
    unittest.main()
