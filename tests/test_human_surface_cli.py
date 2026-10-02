from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import yaml

from tests.test_competition_upgrades import base_contract
from tests import test_p0_harness as p0_harness


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "harness.py"


class HumanSurfaceCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="harness-human-surface-")
        self.project = Path(self.temp.name) / "project"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=str(ROOT), text=True, capture_output=True, encoding="utf-8", errors="replace", check=False,
        )

    def init(self) -> None:
        result = self.run_cli("init", "--project", str(self.project), "--competition", "cumcm", "--preset", "research", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_init_creates_human_surface_without_extra_json(self) -> None:
        self.init()
        self.assertEqual(
            sorted(path.name for path in self.project.glob("*.json")),
            ["artifact_dag.json", "competition_profile.json", "run_index.json", "run_manifest.json"],
        )
        for name in ("00_PROJECT_BRIEF.md", "01_RESEARCH_NOTES.md", "02_MODEL_DECISION.md", "03_SOLUTION_REPORT.md"):
            self.assertTrue((self.project / name).is_file(), name)
        self.assertTrue((self.project / "paper" / "00_PAPER_PLAN.md").is_file())
        for name in ("contracts", "receipts", "evidence", "results", "reports", "indexes", "cache", "views"):
            self.assertTrue((self.project / ".harness" / name).is_dir(), name)

    def test_authoring_facades_do_not_overwrite_research_or_other_sections(self) -> None:
        self.init()
        notes = self.project / "01_RESEARCH_NOTES.md"
        notes.write_text("# Team research notes\n\nactual finding\n", encoding="utf-8")
        research = self.run_cli("research", "--project", str(self.project), "--json")
        self.assertEqual(research.returncode, 0, research.stdout + research.stderr)
        self.assertEqual(notes.read_text(encoding="utf-8"), "# Team research notes\n\nactual finding\n")

        write = self.run_cli("paper", "write", "q2", "--project", str(self.project), "--json")
        self.assertEqual(write.returncode, 0, write.stdout + write.stderr)
        report = json.loads(write.stdout)
        self.assertEqual(report["section"]["section"], "q2")
        self.assertTrue((self.project / "paper" / "sections" / "q2" / "brief.md").is_file())
        self.assertFalse((self.project / "paper" / "sections" / "q1").exists())

    def test_figure_router_and_context_are_stage_local(self) -> None:
        self.init()
        diagram = self.run_cli("figure", "FIG-01", "--semantic-type", "workflow", "--project", str(self.project), "--json")
        self.assertEqual(diagram.returncode, 0, diagram.stdout + diagram.stderr)
        self.assertEqual(json.loads(diagram.stdout)["route"]["default_tool"], "pptx_template")
        data = self.run_cli("figure", "FIG-02", "--semantic-type", "trend", "--project", str(self.project), "--json")
        self.assertEqual(data.returncode, 0, data.stdout + data.stderr)
        self.assertEqual(json.loads(data.stdout)["route"]["default_tool"], "python_plotting")
        context = self.run_cli("context", "--stage", "paper:q2", "--project", str(self.project), "--json")
        self.assertEqual(context.returncode, 0, context.stdout + context.stderr)
        report = json.loads(context.stdout)
        self.assertEqual(report["stage"], "paper:q2")
        self.assertIn("other paper sections", report["optional_files_skipped"])
        self.assertEqual(len(report["loaded_files"]), 4)
        guideline = next(
            row for row in report["loaded_files"]
            if row["path"] == "references/writing/manuscript_logic.md"
        )
        self.assertEqual(guideline["location"], "harness")
        self.assertTrue(guideline["exists"])

    def test_model_facade_names_machine_source_without_claiming_review_readiness(self) -> None:
        self.init()
        result = self.run_cli("model", "--project", str(self.project), "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["structured_source"], ".harness/authoring/model_contract.yaml")
        self.assertTrue((self.project / payload["structured_source"]).is_file())
        self.assertIn(str(self.project.resolve()), payload["compile_argv"])
        self.assertNotIn("ready for review", payload["checkpoint"]["message"])
        human = self.run_cli("model", "--project", str(self.project))
        self.assertIn(payload["structured_source"], human.stdout)
        self.assertIn("does not establish model readiness", human.stdout)

    def test_pptx_figure_copy_preserves_existing_edits_and_drawio_is_explicit(self) -> None:
        self.init()
        first = self.run_cli(
            "figure", "FIG-PPTX", "--semantic-type", "workflow", "--prepare-pptx",
            "--project", str(self.project), "--json",
        )
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        report = json.loads(first.stdout)
        self.assertEqual(report["route"]["default_tool"], "pptx_template")
        staged = self.project / report["pptx_editable_copy"]["path"]
        source = ROOT / report["pptx_editable_copy"]["source_pptx"]
        self.assertTrue(staged.is_file())
        self.assertEqual(staged.read_bytes(), source.read_bytes())
        self.assertTrue((staged.parent / "pptx_editing.md").is_file())
        staged.write_bytes(b"user-edited-pptx")

        second = self.run_cli("figure", "FIG-PPTX", "--semantic-type", "workflow", "--prepare-pptx", "--project", str(self.project), "--json")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertFalse(json.loads(second.stdout)["pptx_editable_copy"]["created"])
        self.assertEqual(staged.read_bytes(), b"user-edited-pptx")

        drawio = self.run_cli("figure", "FIG-DRAWIO", "--semantic-type", "workflow", "--diagram-backend", "drawio", "--project", str(self.project), "--json")
        self.assertEqual(drawio.returncode, 0, drawio.stdout + drawio.stderr)
        self.assertEqual(json.loads(drawio.stdout)["route"]["default_tool"], "drawio")

    def test_empty_machine_contract_template_cannot_compile(self) -> None:
        self.init()
        result = self.run_cli("model", "--compile", "--project", str(self.project), "--json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("empty template", result.stdout)

    def test_model_compiles_explicit_yaml_to_internal_json_ir(self) -> None:
        self.init()
        contract = yaml.safe_dump({"model_contract": base_contract()}, allow_unicode=True, sort_keys=False)
        (self.project / "02_MODEL_DECISION.md").write_text(
            "# 模型选型报告\n\n## Machine contract source (optional)\n\n```yaml\n" + contract + "```\n",
            encoding="utf-8",
        )
        result = self.run_cli("model", "--compile", "--project", str(self.project), "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["output"], ".harness/contracts/model_contract.json")
        self.assertTrue((self.project / report["output"]).is_file())
        manifest = json.loads((self.project / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["roots"]["model_contract"]["path"], report["output"])

    def test_solution_report_compiles_and_registers_implementation_map_root(self) -> None:
        self.init()
        digest = "0" * 64
        mapping = {
            "schema_version": "1.0",
            "run_id": "run-1",
            "model_contract": {"path": ".harness/contracts/model_contract.json", "sha256": digest},
            "symbols": [{
                "symbol_id": "S-X", "latex": "x", "meaning": "state", "unit": "1",
                "scope": "q1", "model_id": "M1",
            }],
            "equations": [{
                "equation_id": "EQ1", "model_id": "M1", "question_id": "q1", "kind": "identity",
                "latex": "x=x", "symbol_ids": ["S-X"], "contract_item_ids": ["EQ1"],
                "code_refs": [{"path": "solver.py", "sha256": digest, "symbol": "solve"}],
                "tests": [{
                    "test_id": "TEST-EQ1", "path": "test_solver.py", "sha256": digest,
                    "purpose": "unit", "status": "pass",
                }],
                "status": "verified",
            }],
            "status": "verified",
        }
        source = self.project / "03_SOLUTION_REPORT.md"
        source.write_text(
            "# 求解与实现记录\n\n## Machine contract source (optional)\n\n```yaml\n"
            + yaml.safe_dump({"implementation_map": mapping}, allow_unicode=True, sort_keys=False)
            + "```\n",
            encoding="utf-8",
        )
        result = self.run_cli("solve", "--compile", "--project", str(self.project), "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        manifest = json.loads((self.project / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["roots"]["implementation_map"]["path"], report["output"])

    def test_paper_plan_compiles_v13_markdown_source_without_overwriting_it(self) -> None:
        self.init()
        fixture_project = Path(self.temp.name) / "complete-plan-fixture"
        fixture_project.mkdir()
        fixture = p0_harness.P0HarnessTest(methodName="runTest")
        fixture_paths = fixture.build_fixture(fixture_project)
        plan = deepcopy(p0_harness.read_json(fixture_paths["plan"]))
        plan["schema_version"] = "1.3"
        plan.pop("depth_budget", None)
        for index, unit in enumerate(plan["argument_units"]):
            unit.pop("target_words", None)
            unit["depth_priority"] = {
                "level": "core" if index == 0 else "supporting",
                "rationale": "This unit is needed to support the tested argument chain.",
            }

        source = self.project / "paper" / "00_PAPER_PLAN.md"
        source.write_text(
            "# Paper Director Plan\n\n## Machine contract source (optional)\n\n```yaml\n"
            + yaml.safe_dump({"paper_plan": plan}, allow_unicode=True, sort_keys=False)
            + "```\n",
            encoding="utf-8",
        )
        source_before = source.read_text(encoding="utf-8")

        result = self.run_cli("paper", "plan", "--compile", "--project", str(self.project), "--json")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["source"], "paper/00_PAPER_PLAN.md")
        self.assertEqual(report["output"], ".harness/contracts/paper_plan.json")
        self.assertEqual(source.read_text(encoding="utf-8"), source_before)
        self.assertEqual(p0_harness.read_json(self.project / report["output"]), plan)
        manifest = p0_harness.read_json(self.project / "run_manifest.json")
        self.assertEqual(manifest["roots"]["paper_plan"]["path"], report["output"])

    def test_top_level_help_works_with_a_legacy_windows_encoding(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CLI), "--help"],
            cwd=str(ROOT), capture_output=True, check=False,
            env={**os.environ, "PYTHONIOENCODING": "gbk"},
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        self.assertIn(b"usage: harness", result.stdout)


if __name__ == "__main__":
    unittest.main()
