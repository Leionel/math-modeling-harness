"""CLI and source views must retain question links and reject stale evidence."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from workflow_sources import read_source, source_catalog, action_details  # noqa: E402
from views.question_workbench import question_workbench  # noqa: E402
from _common import sha256_file  # noqa: E402


class QuestionWorkbenchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = tempfile.TemporaryDirectory(prefix="question-baseline-")
        cls.base = Path(cls.baseline.name) / "project"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "examples/user_walkthrough/run.py"),
                "--project",
                str(cls.base),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.baseline.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="question-test-")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        shutil.copytree(self.base, self.project)

    def test_cli_shows_q2_evidence_but_no_unregistered_writer_readiness(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/harness.py"),
                "questions",
                "--project",
                str(self.project),
                "--question",
                "q2",
                "--json",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        row = json.loads(result.stdout)["questions"][0]
        self.assertEqual(row["question_id"], "q2")
        self.assertEqual(row["validation_obligations"][0]["status"], "PASS")
        self.assertEqual(row["executed_outputs"][0]["path"], "raw_results.json")
        self.assertEqual(row["writer_eligibility"], "unverified")
        self.assertEqual(row["writer_claims"], [])
        missing = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/harness.py"),
                "questions",
                "--project",
                str(self.project),
                "--question",
                "q99",
                "--json",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(missing.returncode, 1)

    def test_changed_author_source_invalidates_question_validation(self):
        source = self.project / ".harness/authoring/model_contract.yaml"
        source.write_text(
            source.read_text(encoding="utf-8") + "\n# changed assumption\n",
            encoding="utf-8",
        )
        row = question_workbench(self.project)["questions"][0]
        self.assertTrue(row["model_source_stale"])
        self.assertEqual(row["validation_obligations"][0]["status"], "unknown")

    def test_changed_measurement_is_not_a_passing_validation(self):
        path = self.project / "measurements.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["observations"][0]["metrics"][0]["value"] = 5
        path.write_text(json.dumps(value), encoding="utf-8")
        report = question_workbench(self.project)
        self.assertTrue(report["errors"])
        self.assertEqual(
            report["questions"][0]["validation_obligations"][0]["status"], "unknown"
        )

    def test_explicit_shared_model_and_nested_tex_locations(self):
        manifest_path = self.project / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["roots"]["paper_plan"] = {"path": "paper_plan.json"}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        model_path = self.project / ".harness/contracts/model_contract.json"
        model = json.loads(model_path.read_text(encoding="utf-8"))
        model["questions"].append({"question_id": "q3", "task": "reuse Q2 model"})
        model_path.write_text(json.dumps(model), encoding="utf-8")
        plan = {
            "run_id": manifest["run_id"],
            "argument_units": [
                {
                    "unit_id": "UNIT-Q3",
                    "scope": {"question_ids": ["q3"]},
                    "model_ids": ["MODEL-Q2"],
                    "math_locators": ["ANCHOR-Q3", "ABSENT"],
                }
            ],
        }
        (self.project / "paper_plan.json").write_text(
            json.dumps(plan), encoding="utf-8"
        )
        paper = self.project / "paper"
        paper.mkdir(exist_ok=True)
        (paper / "main.tex").write_text("\\input{section}\n", encoding="utf-8")
        section = paper / "section.tex"
        section.write_text("text\nANCHOR-Q3\n", encoding="utf-8")
        report = question_workbench(self.project)
        row = next(q for q in report["questions"] if q["question_id"] == "q3")
        self.assertEqual(row["models"][0]["model_id"], "MODEL-Q2")
        self.assertEqual(
            row["paper_locations"][0]["matches"],
            [{"path": "paper/section.tex", "line": 2}],
        )
        self.assertEqual(row["paper_locations"][1]["state"], "missing")
        section.write_text("ANCHOR-Q3\nANCHOR-Q3\n", encoding="utf-8")
        row = question_workbench(self.project)["questions"][1]
        self.assertEqual(row["paper_locations"][0]["state"], "ambiguous")
        self.assertNotEqual(report["paper_binding"]["status"], "verified")

    def test_log_preview_uses_receipt_identity_and_bounds_text(self):
        source = next(
            row
            for row in source_catalog(self.project)
            if row["kind"] == "log" and row["source_id"].endswith(":stdout")
        )
        result = read_source(self.project, source["source_id"], limit=16)
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len(result["text"].encode("utf-8")), 16)
        with self.assertRaises(KeyError):
            read_source(self.project, "../../secret")

    def test_reviewed_source_change_does_not_show_current_text_as_reviewed_version(
        self,
    ):
        path = self.project / "reviewed.tex"
        path.write_text("version one", encoding="utf-8")
        review = self.project / "reports/review/test.json"
        review.parent.mkdir(parents=True, exist_ok=True)
        review.write_text(
            json.dumps(
                {
                    "perspective": "human_prose",
                    "reviewed_artifacts": [
                        {"path": "reviewed.tex", "sha256": sha256_file(path)}
                    ],
                }
            ),
            encoding="utf-8",
        )
        source = next(
            row
            for row in source_catalog(self.project)
            if row["kind"] == "reviewed_version"
        )
        self.assertEqual(
            read_source(self.project, source["source_id"])["text"], "version one"
        )
        path.write_text("version two", encoding="utf-8")
        result = read_source(self.project, source["source_id"])
        self.assertEqual(result["freshness"], "stale")
        self.assertEqual(result["text"], "")
        self.assertTrue(result["unavailable_reason"])

    def test_action_names_source_and_both_shell_commands_without_guessing_field(self):
        action = action_details(
            self.project, "m1", "model_contract canonical artifact is not declared"
        )
        self.assertEqual(action["target_source_id"], "authoring:model_contract")
        self.assertIsNone(action["field_pointer"])
        self.assertIn(str(self.project.resolve()), action["command"]["argv"])
        self.assertEqual(action["compile_command"]["effect"], "producer")
        self.assertTrue(action["command"]["powershell"])
        self.assertTrue(action["command"]["posix"])

    def test_compile_action_preserves_custom_source_and_output(self):
        from tests.test_p0_harness import P0HarnessTest

        research_fixture = Path(self.temp.name) / "research-fixture"
        research_fixture.mkdir()
        paths = P0HarnessTest(methodName="runTest").build_fixture(research_fixture)
        basis = json.loads(paths["model"].read_text(encoding="utf-8"))["research_basis"]
        (self.project / "custom research.json").write_text(
            json.dumps({"research_basis": basis}), encoding="utf-8"
        )
        source = self.project / "custom model.yaml"
        shutil.copyfile(self.project / ".harness/authoring/model_contract.yaml", source)
        command = [
            sys.executable,
            str(ROOT / "scripts/harness.py"),
            "model",
            "--project",
            str(self.project),
            "--compile",
            "--source",
            "custom model.yaml",
            "--output",
            "custom model.json",
            "--research-source",
            "custom research.json",
            "--json",
        ]
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        action = action_details(
            self.project, "m1", "model_contract authoring source changed"
        )
        argv = action["compile_command"]["argv"]
        self.assertEqual(action["target_path"], "custom model.yaml")
        self.assertEqual(argv[argv.index("--source") + 1], "custom model.yaml")
        self.assertEqual(argv[argv.index("--output") + 1], "custom model.json")
        self.assertEqual(
            argv[argv.index("--research-source") + 1], "custom research.json"
        )
        # The default YAML is deliberately broken: the copied command must use the indexed source.
        (self.project / ".harness/authoring/model_contract.yaml").write_text(
            "model_contract: invalid", encoding="utf-8"
        )
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/harness.py"), *argv[1:]],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.project / "custom model.json").is_file())
