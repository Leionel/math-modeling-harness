"""Regression tests for the shared stage-aware capability evaluator."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys
import io
import json
from contextlib import redirect_stdout

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import doctor_core  # noqa: E402
import harness  # noqa: E402
import mcp_server  # noqa: E402


def _dependency(name: str, status: str = "available") -> dict:
    return {
        "name": name, "kind": "python_dependency", "status": status,
        "source": "python import", "version": "test", "path": "test",
        "required_for_stages": [], "guidance": "install it",
    }


def _command(name: str, status: str = "available") -> dict:
    return {
        "name": name, "kind": "command", "status": status,
        "source": "PATH", "version": "test", "path": "test",
        "required_for_stages": [], "guidance": "configure it",
    }


class DoctorStageTest(unittest.TestCase):
    def test_cli_prints_interpreter_and_repair_for_current_dependency(self) -> None:
        with tempfile.TemporaryDirectory(prefix="doctor cli ") as temp, patch.object(doctor_core, "probe_dependency", side_effect=lambda name: _dependency(name, "missing" if name == "yaml" else "available")), patch.object(doctor_core, "probe_command", side_effect=self._probe_command):
            output = io.StringIO()
            with redirect_stdout(output):
                code = harness.main(["doctor", "--project", temp, "--stage", "M1", "--offline"])
            self.assertEqual(code, 1)
            text = output.getvalue()
            self.assertIn(sys.executable, text)
            self.assertIn("PyYAML", text)
            self.assertIn("当前阶段缺项: yaml", text)
            self.assertNotIn("必需: latexmk", text)
            self.assertNotIn("configure it", text)
            self.assertIn(str(Path(temp).resolve()), text)
            output = io.StringIO()
            with redirect_stdout(output):
                code = harness.main(["doctor", "--project", temp, "--stage", "M1", "--json"])
            self.assertEqual(code, 1)
            self.assertFalse(json.loads(output.getvalue())["ok"])

    def test_cli_verbose_lists_later_tools_without_blocking_m1(self) -> None:
        with tempfile.TemporaryDirectory() as temp, patch.object(doctor_core, "probe_dependency", side_effect=self._probe_dependency), patch.object(doctor_core, "probe_command", side_effect=self._probe_command):
            output = io.StringIO()
            with redirect_stdout(output):
                code = harness.main(["doctor", "--project", temp, "--stage", "M1", "--verbose"])
            self.assertEqual(code, 0)
            self.assertIn("后续/可选: latexmk", output.getvalue())

    def _probe_dependency(self, name: str) -> dict:
        return _dependency(name)

    def _probe_command(self, name: str) -> dict:
        return _command(name, "missing" if name in {"latexmk", "xelatex", "pdfinfo", "pdffonts", "pdftoppm"} else "available")

    def test_report_has_normalized_fields_and_does_not_block_m1_on_latex(self) -> None:
        with tempfile.TemporaryDirectory(prefix="doctor-stage-") as temp, patch.object(doctor_core, "probe_dependency", side_effect=self._probe_dependency), patch.object(doctor_core, "probe_command", side_effect=self._probe_command):
            report = doctor_core.evaluate_capabilities(Path(temp), stage="M1", repo_root=ROOT)
        self.assertTrue(report["ok"])
        self.assertEqual(report["stage"], "M1")
        self.assertEqual(report["stages"]["M1"]["status"], "ready")
        self.assertEqual(report["stages"]["W2"]["status"], "blocked")
        for capability in report["capabilities"]:
            self.assertTrue({"status", "source", "version", "path", "required_for_stages", "guidance"} <= capability.keys())

    def test_parser_and_mcp_preserve_legacy_doctor_and_add_optional_stage(self) -> None:
        parsed = harness.build_parser().parse_args(["doctor", "--stage", "W2", "--project", "."])
        self.assertEqual(parsed.stage, "W2")
        argv = mcp_server.build_argv("doctor", {"stage": "S1"}, Path("."))
        self.assertIn("--stage", argv)
        self.assertIn("S1", argv)
        legacy = mcp_server.build_argv("doctor", {}, Path("."))
        self.assertNotIn("--stage", legacy)

    def test_w2_accepts_any_supported_template_engine(self) -> None:
        def command(name: str) -> dict:
            return _command(name, "missing" if name == "xelatex" else "available")

        with tempfile.TemporaryDirectory(prefix="doctor-engine-") as temp, patch.object(doctor_core, "probe_dependency", side_effect=self._probe_dependency), patch.object(doctor_core, "probe_command", side_effect=command):
            report = doctor_core.evaluate_capabilities(Path(temp), stage="W2", repo_root=ROOT)
        self.assertTrue(report["ok"])
        self.assertEqual(report["stages"]["W2"]["status"], "ready")
        self.assertIn(["xelatex", "lualatex", "pdflatex"], report["stages"]["W2"]["alternative_capabilities"])


if __name__ == "__main__":
    unittest.main()
