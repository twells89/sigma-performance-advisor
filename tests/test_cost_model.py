import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cost_model import recommend  # noqa: E402


class CostModelTests(unittest.TestCase):
    def test_keeps_well_used_fast_materialization(self):
        row = {
            "MATERIALIZATION_RUNS": 20,
            "MATERIALIZATION_CREDITS": 1,
            "MATCHED_MATERIALIZED_READS": 200,
            "MATCHED_READ_P95_SEC": 1.2,
            "P95_SEC": 1.2,
        }
        self.assertEqual(recommend(row)["ACTION"], "Keep materialization")

    def test_retunes_low_utilization_instead_of_removing(self):
        row = {
            "MATERIALIZATION_RUNS": 100,
            "MATERIALIZATION_CREDITS": 5,
            "MATCHED_MATERIALIZED_READS": 2,
            "P95_SEC": 10,
        }
        result = recommend(row)
        self.assertEqual(result["ACTION"], "Retune materialization")
        self.assertNotIn("Remove", result["ACTION"])

    def test_controls_force_investigation(self):
        row = {
            "MATERIALIZATION_RUNS": 30,
            "MATCHED_MATERIALIZED_READS": 100,
            "HAS_CONTROLS": True,
            "CONTROL_TARGETS_RESOLVED": False,
        }
        self.assertEqual(recommend(row)["ACTION"], "Investigate materialization")

    def test_removal_requires_measured_counterfactual(self):
        base = {
            "MATERIALIZATION_RUNS": 30,
            "MATERIALIZATION_CREDITS": 8,
            "MATCHED_MATERIALIZED_READS": 1,
            "P95_SEC": 1,
        }
        self.assertNotIn("Remove", recommend(base)["ACTION"])
        measured = {
            **base,
            "COUNTERFACTUAL_P95_SEC": 3,
            "COUNTERFACTUAL_CREDITS": .25,
        }
        self.assertEqual(
            recommend(measured, {"min_monthly_savings": 10})["ACTION"],
            "Remove materialization candidate",
        )

    def test_optimizes_intrinsically_expensive_query(self):
        row = {
            "RUNS": 5, "CREDITS": 1, "P95_SEC": 20,
            "MAX_BYTES": 5_000_000_000,
        }
        self.assertEqual(recommend(row)["ACTION"], "Optimize query/model")

    def test_adds_only_when_repeated_and_nontrivial(self):
        row = {"RUNS": 100, "CREDITS": 3, "P95_SEC": 4}
        self.assertEqual(recommend(row)["ACTION"], "Add materialization candidate")
        self.assertEqual(
            recommend(row, {"freshness": "real-time"})["ACTION"], "Monitor"
        )


if __name__ == "__main__":
    unittest.main()
