import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import materialize  # noqa: E402


class MaterializeCliTests(unittest.TestCase):
    def run_cli(self, *args):
        env = dict(os.environ)
        env.pop("SIGMA_BASE_URL", None)
        env.pop("SIGMA_API_TOKEN", None)
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "materialize.py"), *args],
            env=env, check=True, capture_output=True, text=True,
        ).stdout

    def test_dry_run_uses_element_id_for_schedule_crud(self):
        output = self.run_cli(
            "create", "--workbook", "wb", "--element-id", "element",
            "--cron", "0 0 * * *", "--dry-run",
        )
        request = json.loads(output)
        self.assertIn("/elements/element/materializationSchedules", request["path"])

    def test_dry_run_uses_sheet_id_for_refresh(self):
        output = self.run_cli(
            "run", "--workbook", "wb", "--sheet-id", "schedule", "--dry-run",
        )
        request = json.loads(output)
        self.assertEqual(request["body"], {"sheetId": "schedule"})

    def test_workbook_schedule_list_paginates_and_prints_both_ids(self):
        pages = [
            {"entries": [{"sheetId": "sheet-1", "elementId": "element-1",
                          "elementName": "A", "schedule": {}, "paused": False}],
             "nextPage": "next"},
            {"entries": [{"sheetId": "sheet-2", "elementId": "element-2",
                          "elementName": "B", "schedule": {}, "paused": False}],
             "nextPage": None},
        ]
        with mock.patch.object(materialize, "api", side_effect=pages) as api:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                materialize.list_schedules(
                    SimpleNamespace(workbook="wb", datamodel=None)
                )
        self.assertEqual(api.call_count, 2)
        self.assertIn("page=next", api.call_args_list[1].args[1])
        self.assertIn("sheetId=sheet-1  elementId=element-1", output.getvalue())


if __name__ == "__main__":
    unittest.main()
