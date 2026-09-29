from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAULTS = ROOT / "evaluation" / "recovery" / "faults"
REPAIR = ROOT / "evaluation" / "recovery" / "repair.py"
UTF8_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

sys.path.insert(0, str(REPAIR.parent))
sys.path.insert(0, str(ROOT / "tests"))

import repair as repair_module  # noqa: E402
from _recovery_baseline import built_fixture  # noqa: E402


class RecoveryRepairTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = built_fixture()

    def test_cli_does_not_claim_repair_without_executed_step(self) -> None:
        with tempfile.TemporaryDirectory(prefix="repair-failed-plan-") as temp:
            project = Path(temp) / "project"
            shutil.copytree(self.fixture, project)
            plan = Path(temp) / "plan.json"
            plan.write_text(json.dumps({
                "ok": False, "errors": ["unresolved dependency"],
                "rerun_steps": [{"path": "never-made.txt", "role": "paper_source"}],
            }), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(REPAIR), "--project-root", str(project),
                 "--fault-id", "INVALID", "--gate", "P2", "--plan", str(plan)],
                text=True, capture_output=True, encoding="utf-8", errors="replace",
                check=False, env=UTF8_ENV,
            )
            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            self.assertFalse(json.loads(completed.stdout)["ok"])
            report = json.loads((project / ".harness" / "recovery" / "INVALID.json").read_text(encoding="utf-8"))
            self.assertFalse(report["repaired"])
            self.assertFalse(report["plan_ok"])
            self.assertFalse(report["steps"][0]["executed"])

    def test_freeze_artifact_repair_succeeds_via_supersession(self) -> None:
        """GAP-R1 closed: a deleted frozen result (F03) can be recovered through
        freeze supersession. The executor re-runs the freeze step declaring
        --supersedes-receipt, P2 verifies active lineage count == 1, and exits 0."""
        fault = FAULTS / "F03_frozen_results_deleted"
        with tempfile.TemporaryDirectory(prefix="repair-f03-") as temp:
            project = Path(temp) / "project"
            shutil.copytree(self.fixture, project)
            injected = subprocess.run(
                [sys.executable, str(fault / "inject.py"), "--project-root", str(project)],
                text=True, capture_output=True, encoding="utf-8", check=False,
            )
            self.assertEqual(injected.returncode, 0, injected.stdout + injected.stderr)

            result = subprocess.run(
                [sys.executable, str(REPAIR), "--project-root", str(project),
                 "--fault-id", "F03", "--gate", "P2", "--changed", "frozen_results.json"],
                text=True, capture_output=True, encoding="utf-8", errors="replace",
                check=False, env=UTF8_ENV,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            frozen_step = next(step for step in payload["steps"] if step["path"] == "frozen_results.json")
            self.assertEqual(frozen_step["status"], "rerun")
            self.assertTrue(frozen_step["executed"])
            self.assertEqual(payload["gate_exit_code"], 0)

            log = json.loads((project / ".harness" / "recovery" / "F03.json").read_text(encoding="utf-8"))
            self.assertTrue(log["repaired"])
            self.assertEqual(log["gate_report"].get("errors"), [])
            # The artifact is recovered and receipts are preserved.
            self.assertTrue((project / "frozen_results.json").exists())
            receipts = list((project / "receipts").glob("freeze-*.json"))
            self.assertEqual(len(receipts), 2)  # Original + superseded receipt

    def test_f04_receipt_binding_mismatch_repair_succeeds(self) -> None:
        """F04 recovery E2E: command binding mismatch repaired via supersession."""
        fault = FAULTS / "F04_receipt_binding_mismatch"
        with tempfile.TemporaryDirectory(prefix="repair-f04-") as temp:
            project = Path(temp) / "project"
            shutil.copytree(self.fixture, project)
            injected = subprocess.run(
                [sys.executable, str(fault / "inject.py"), "--project-root", str(project)],
                text=True, capture_output=True, encoding="utf-8", check=False,
            )
            self.assertEqual(injected.returncode, 0, injected.stdout + injected.stderr)

            result = subprocess.run(
                [sys.executable, str(REPAIR), "--project-root", str(project),
                 "--fault-id", "F04", "--gate", "P2", "--changed", "frozen_results.json"],
                text=True, capture_output=True, encoding="utf-8", errors="replace",
                check=False, env=UTF8_ENV,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["gate_exit_code"], 0)

    def test_gap_r2_receipt_backed_rerun_succeeds(self) -> None:
        """GAP-R2 closed: modifying raw_results triggers selective rerun of full
        execution stage then freeze stage with full receipt backing, passing P2."""
        with tempfile.TemporaryDirectory(prefix="repair-gap-r2-") as temp:
            project = Path(temp) / "project"
            shutil.copytree(self.fixture, project)
            raw_path = project / "raw_results.json"
            data = json.loads(raw_path.read_text(encoding="utf-8"))
            data["results"][0]["value"] = 88888
            raw_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

            result = subprocess.run(
                [sys.executable, str(REPAIR), "--project-root", str(project),
                 "--fault-id", "GAP_R2", "--gate", "P2", "--changed", "raw_results.json"],
                text=True, capture_output=True, encoding="utf-8", errors="replace",
                check=False, env=UTF8_ENV,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["gate_exit_code"], 0)
            executed_steps = [s["path"] for s in payload["steps"] if s.get("executed")]
            self.assertIn("raw_results.json", executed_steps)
            self.assertIn("frozen_results.json", executed_steps)

    def test_execute_argv_maps_receipt_facts_to_flags(self) -> None:
        receipt = {
            "stage": "smoke",
            "run_id": "run-1",
            "seed": 7,
            "selection": {"selected": False},
            "input_refs": [{"path": "input.json"}],
            "output_refs": [{"path": "smoke_results.json"}],
            "metadata": {"smoke_coverage": {"model_ids": ["M-Q1"], "question_ids": ["q1"],
                                            "covered_contract_item_ids": ["EQ-Q1-OBJ"]}},
            "cwd": "D:\\old\\project",
            "argv": [sys.executable, "D:\\old\\project\\model.py", "--smoke"],
        }
        project = Path("D:\\live\\project")
        argv = repair_module.execute_argv(receipt, project)
        text = " ".join(argv)
        self.assertIn("--stage smoke", text)
        self.assertIn("--run-id run-1", text)
        self.assertIn("--seed 7", text)
        self.assertIn("--input input.json", text)
        self.assertIn("--output-artifact smoke_results.json", text)
        self.assertIn("--covers-model M-Q1", text)
        self.assertIn("--covers-question q1", text)
        self.assertIn("--covers-contract-item EQ-Q1-OBJ", text)
        self.assertNotIn("--selected", text)
        self.assertNotIn("--freeze", text)
        self.assertNotIn("D:\\old\\project", text)
        self.assertIn("D:\\live\\project\\model.py", argv)

    def test_freeze_stage_receives_freeze_flag_but_never_reclaims_selection(self) -> None:
        receipt = {
            "stage": "freeze",
            "run_id": "run-1",
            "selection": {"selected": True},
            "input_refs": [], "output_refs": [{"path": "frozen_results.json"}],
            "cwd": "D:\\old\\project",
            "argv": ["python", "freeze.py"],
        }
        argv = repair_module.execute_argv(receipt, Path("D:\\live\\project"))
        text = " ".join(argv)
        self.assertIn("--freeze", text)
        # Re-claiming selection would leave two selected receipts and break P2.
        self.assertNotIn("--selected", text)


if __name__ == "__main__":
    unittest.main()
