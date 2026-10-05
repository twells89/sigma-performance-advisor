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
                inventory["totals"]["credit_coverage_pct"], 60.74, places=2
            )
            coverage = inventory["coverage"]
            self.assertAlmostEqual(
                coverage["attributable_credits"]
                + coverage["materialization_credits"]
                + coverage["unattributed_credits"],
                coverage["all_sigma_credits"],
                places=4,
            )
            actions = {row["ACTION"] for row in inventory["candidates"]}
            self.assertIn("Add materialization candidate", actions)
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

    def test_explicit_default_flag_overrides_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            config = tmp / "config.json"
            config.write_text(json.dumps({"days": 90}))
            out = tmp / "out"
            subprocess.run(
                [
                    sys.executable, str(ROOT / "scripts" / "analyze.py"),
                    "--from-rows", str(ROOT / "example" / "sample-rows.json"),
                    "--config", str(config), "--days", "30",
                    "--credit-price", "3", "--out", str(out),
                ],
                check=True, capture_output=True, text=True,
            )
            inventory = json.loads((out / "inventory.json").read_text())
            self.assertEqual(inventory["days"], 30)


if __name__ == "__main__":
    unittest.main()
