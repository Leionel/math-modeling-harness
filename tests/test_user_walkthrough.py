"""The documented tutorial must exercise CLI exits and real artifacts."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UserWalkthroughTest(unittest.TestCase):
    def test_public_cli_tutorial_keeps_formal_boundary_and_records_execution(self):
        with tempfile.TemporaryDirectory(prefix="tutorial 中文 ") as temp:
            project = Path(temp) / "new project"
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "examples/user_walkthrough/run.py"),
                    "--project",
                    str(project),
                ],
                cwd=temp,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            frozen = json.loads(
                (project / ".harness/results/frozen_results.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(frozen["validation_verdict"], "PASS")
            self.assertEqual(frozen["results"][0]["value"], 0)
            receipt = json.loads(
                (project / "receipts/full.json").read_text(encoding="utf-8")
            )
            self.assertEqual(receipt["argv"], [sys.executable, "solver.py"])
            self.assertEqual(receipt["exit_code"], 0)
            self.assertIn(
                "enumerated 9 candidates",
                (project / receipt["stdout_path"]).read_text(encoding="utf-8"),
            )
            self.assertIn("formal M1 remains blocked", result.stdout)
            self.assertEqual(
                json.loads((project / "run_manifest.json").read_text(encoding="utf-8"))[
                    "human_checkpoints"
                ],
                [],
            )
            again = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "examples/user_walkthrough/run.py"),
                    "--project",
                    str(project),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(again.returncode, 2)

    def test_shell_display_preserves_literal_arguments(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        from command_display import render_command
        import shlex

        argv = ["python path", "a'b", "$(secret)", "中文", "line\nnext"]
        command = render_command(argv)
        self.assertEqual(shlex.split(command["posix"]), argv)
        self.assertIn("'a''b'", command["powershell"])
        self.assertIn("'$(secret)'", command["powershell"])
