import importlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
MATERIALIZATION_SQL = importlib.import_module("analyze").MATERIALIZATION_SQL
match_workbook = importlib.import_module("enrich").match_workbook


class PipelineTests(unittest.TestCase):
    def test_workbook_matching_rejects_substring_collisions(self):
        candidate = {
            "OBJECT": "/workbook/Customer-Overview-jjj000",
            "SAMPLE_URL": (
                "https://app.sigmacomputing.com/northwind/workbook/"
                "Customer-Overview-jjj000?:displayNodeId=orders"
            ),
        }
        wrong = {
            "workbookId": "Overview",
            "workbookUrlId": "Overview",
            "url": "https://app.sigmacomputing.com/northwind/workbook/Overview",
        }
        expected = {
            "workbookId": "workbook-id",
            "workbookUrlId": "Customer-Overview-jjj000",
            "url": (
                "https://app.sigmacomputing.com/northwind/workbook/"
                "Customer-Overview-jjj000"
            ),
        }
        self.assertIs(match_workbook(candidate, [wrong, expected]), expected)

    def test_report_materializations_are_included_in_utilization_sql(self):
        self.assertIn("'/(workbook|report)/[^?]+'", MATERIALIZATION_SQL)
        sql_file = (ROOT / "sql" / "sigma_materialization_roi.sql").read_text()
        self.assertIn("'/(workbook|report)/[^?]+'", sql_file)

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

    def test_org_scoped_bundle_omits_account_wide_warehouse_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            subprocess.run(
                [
                    sys.executable, str(ROOT / "scripts" / "analyze.py"),
                    "--from-rows", str(ROOT / "example" / "sample-rows.json"),
                    "--org", "northwind", "--credit-price", "3",
                    "--out", str(out),
                ],
                check=True, capture_output=True, text=True,
            )
            inventory = json.loads((out / "inventory.json").read_text())
            self.assertEqual(inventory["warehouse"], {})
            self.assertNotIn("## Warehouse context", (out / "REPORT.md").read_text())


if __name__ == "__main__":
    unittest.main()
