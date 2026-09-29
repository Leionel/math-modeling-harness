from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from qa.validate_contracts import _validate_document  # noqa: E402


class RunAndRecordTest(unittest.TestCase):
    def _run(self, *args: str, cwd: Path):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_and_record.py"), *args],
            cwd=str(cwd), text=True, capture_output=True, encoding="utf-8", check=False,
        )

    def test_success_and_failure_receipts_with_index(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-run-record-") as temp:
            project = Path(temp)
            (project / "input.txt").write_text("demand\n", encoding="utf-8")

            ok = self._run(
                "--run-id", "run-001", "--stage", "full",
                "--receipt", "reports/receipt_ok.json", "--index", "reports/run_index.json",
                "--selected", "--selection-policy", "first successful full run is selected",
                "--input", "input.txt", "--output-artifact", "results/out.txt", "--note", "baseline full run",
                "--", sys.executable, "-c",
                "from pathlib import Path; Path('results').mkdir(exist_ok=True); Path('results/out.txt').write_text('42\\n', encoding='utf-8')",
                cwd=project,
            )
            self.assertEqual(ok.returncode, 0, ok.stderr[-800:])
            receipt = json.loads((project / "reports" / "receipt_ok.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["exit_code"], 0)
            self.assertEqual(receipt["argv"][0], sys.executable)
            self.assertEqual(receipt["output_refs"][0]["existed_before"], False)
            _, schema_errors, _ = _validate_document(
                project / "reports" / "receipt_ok.json", ROOT / "schemas" / "command_receipt.schema.json"
            )
            self.assertEqual(schema_errors, [])

            fail = self._run(
                "--run-id", "run-001", "--stage", "full",
                "--receipt", "reports/receipt_fail.json", "--index", "reports/run_index.json",
                "--selection-policy", "first successful full run is selected",
                "--note", "failed tuning run, kept for audit",
                "--", sys.executable, "-c", "import sys; sys.exit(3)",
                cwd=project,
            )
            self.assertEqual(fail.returncode, 3)
            failed_receipt = json.loads((project / "reports" / "receipt_fail.json").read_text(encoding="utf-8"))
            self.assertEqual(failed_receipt["exit_code"], 3)

            index = json.loads((project / "reports" / "run_index.json").read_text(encoding="utf-8"))
            self.assertEqual(len(index["runs"]), 2)
            self.assertEqual([r["exit_code"] for r in index["runs"]], [0, 3])
            self.assertEqual([r["selected"] for r in index["runs"]], [True, False])
            _, index_errors, _ = _validate_document(
                project / "reports" / "run_index.json", ROOT / "schemas" / "run_index.schema.json"
            )
            self.assertEqual(index_errors, [])

    def test_missing_declared_output_is_reported_not_swallowed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-run-record-missing-") as temp:
            project = Path(temp)
            result = self._run(
                "--run-id", "run-002", "--stage", "smoke",
                "--receipt", "reports/receipt.json",
                "--output-artifact", "results/never_created.txt",
                "--", sys.executable, "-c", "print('ran fine')",
                cwd=project,
            )
            self.assertEqual(result.returncode, 3)
            self.assertIn("was not produced", result.stdout)

    def test_mutable_outputs_and_control_files_cannot_escape_project_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-run-record-boundary-") as temp:
            base = Path(temp)
            project = base / "project"
            project.mkdir()
            outside = base / "outside.json"
            cases = (
                ("--receipt", str(outside)),
                ("--index", str(outside)),
                ("--output-artifact", str(outside)),
            )
            for option, target in cases:
                with self.subTest(option=option):
                    marker = project / f"ran-{option[2:]}.txt"
                    args = [
                        "--run-id", "run-boundary", "--stage", "full", "--v2",
                        "--receipt", f"reports/{option[2:]}.json",
                    ]
                    args.extend([option, target])
                    args.extend([
                        "--", sys.executable, "-c",
                        f"from pathlib import Path; Path(r'{marker}').write_text('ran', encoding='utf-8')",
                    ])
                    result = self._run(*args, cwd=project)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("inside the project root", result.stdout)
                    self.assertFalse(marker.exists(), result.stdout + result.stderr)
            self.assertFalse(outside.exists())

    def test_existing_v1_receipt_is_rejected_before_child_runs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-run-record-immutable-") as temp:
            project = Path(temp)
            receipt = project / "reports" / "receipt.json"
            receipt.parent.mkdir()
            receipt.write_text("{}\n", encoding="utf-8")
            marker = project / "ran.txt"
            result = self._run(
                "--run-id", "run-immutable", "--stage", "full",
                "--receipt", "reports/receipt.json",
                "--", sys.executable, "-c",
                "from pathlib import Path; Path('ran.txt').write_text('ran', encoding='utf-8')",
                cwd=project,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing to overwrite immutable receipt", result.stdout)
            self.assertFalse(marker.exists())

    def test_invalid_supersession_is_rejected_before_child_runs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-run-record-supersession-") as temp:
            project = Path(temp)
            marker = project / "ran.txt"
            result = self._run(
                "--run-id", "run-1", "--stage", "freeze", "--v2",
                "--receipt", "receipts/new.json", "--supersedes-receipt", "REC-missing",
                "--", sys.executable, "-c",
                "from pathlib import Path; Path('ran.txt').write_text('ran', encoding='utf-8')",
                cwd=project,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("does not exist", result.stdout)
            self.assertFalse(marker.exists())
            self.assertFalse((project / "receipts" / "new.json").exists())

    def test_v2_timeout_records_failure_without_child_exit_code(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-run-record-timeout-") as temp:
            project = Path(temp)
            result = self._run(
                "--run-id", "run-timeout", "--stage", "full", "--v2",
                "--receipt", "receipts/timed.json", "--index", "run_index.json",
                "--timeout", "1", "--", sys.executable, "-c",
                "import time; print('started', flush=True); time.sleep(5)",
                cwd=project,
            )
            self.assertEqual(result.returncode, 124, result.stdout + result.stderr)
            receipt_path = project / "receipts" / "timed.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertIsNone(receipt["exit_code"])
            self.assertEqual(receipt["metadata"]["failure_reason"], "timeout")
            self.assertEqual(receipt["metadata"]["timeout_seconds"], 1)
            self.assertIn("started", (project / receipt["stdout_path"]).read_text(encoding="utf-8"))
            self.assertTrue((project / "run_index.json").is_file())
            _, schema_errors, _ = _validate_document(receipt_path, ROOT / "schemas" / "command_receipt.schema.json")
            self.assertEqual(schema_errors, [])
            receipt["metadata"].pop("timeout_seconds")
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            _, invalid_errors, _ = _validate_document(receipt_path, ROOT / "schemas" / "command_receipt.schema.json")
            self.assertTrue(invalid_errors)

    def test_v2_default_time_limit_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-run-record-default-timeout-") as temp:
            project = Path(temp)
            result = self._run(
                "--run-id", "run-bounded", "--stage", "smoke", "--v2",
                "--receipt", "receipts/bounded.json", "--", sys.executable, "-c", "print('ok')",
                cwd=project,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            receipt = json.loads((project / "receipts" / "bounded.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["metadata"]["timeout_seconds"], 900)


if __name__ == "__main__":
    unittest.main()
