"""Regression tests for minimal Model Racing workflow."""

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
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

import checkpoints  # noqa: E402
from _recovery_baseline import built_fixture  # noqa: E402
from model_racing import extract_candidate_facts, run_model_race  # noqa: E402


class ModelRacingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = built_fixture()

    def test_cli_rejects_candidate_path_before_touching_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="race-path-test-") as temp:
            temp_dir = Path(temp)
            spec = temp_dir / "race.json"
            spec.write_text(json.dumps({
                "candidate_models": [{"id": "../../victim"}, {"id": "safe"}],
            }), encoding="utf-8")
            victim = temp_dir / "victim"
            victim.mkdir()
            sentinel = victim / "keep.txt"
            sentinel.write_text("keep me", encoding="utf-8")
            output = temp_dir / "output"
            completed = subprocess.run(
                [sys.executable, str(SCRIPTS / "model_racing.py"), "--spec", str(spec),
                 "--base-project", str(temp_dir), "--output-dir", str(output)],
                text=True, capture_output=True, encoding="utf-8", errors="replace", check=False,
            )
            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            self.assertIn("invalid candidate id", completed.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep me")
            self.assertFalse(output.exists())

    def test_declared_frozen_claim_cannot_override_failed_gates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="race-gates-test-") as temp:
            branch = Path(temp)
            (branch / "frozen_results.json").write_text(json.dumps({
                "claimable": True, "validation_verdict": "PASS", "results": [],
            }), encoding="utf-8")
            facts = extract_candidate_facts(branch, {"id": "candidate"})
            self.assertFalse(facts["passed_all_gates"])
            self.assertFalse(facts["claimable"])

    def test_cli_rejects_redirected_branches_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="race-link-test-") as temp:
            root = Path(temp)
            output = root / "output"
            output.mkdir()
            victim = root / "victim"
            victim.mkdir()
            sentinel = victim / "keep.txt"
            sentinel.write_text("keep me", encoding="utf-8")
            try:
                os.symlink(victim, output / "branches", target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlink unavailable: {exc}")
            spec = root / "race.json"
            spec.write_text(json.dumps({"candidate_models": [
                {"id": "model_a"}, {"id": "model_b"},
            ]}), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPTS / "model_racing.py"), "--spec", str(spec),
                 "--base-project", str(root), "--output-dir", str(output)],
                text=True, capture_output=True, encoding="utf-8", errors="replace", check=False,
            )
            self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
            self.assertIn("branches directory must stay inside", completed.stderr)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep me")

    def test_model_racing_fork_and_factual_compare(self) -> None:
        with tempfile.TemporaryDirectory(prefix="race-test-") as temp:
            temp_dir = Path(temp)
            base_proj = temp_dir / "base"
            shutil.copytree(self.fixture, base_proj)

            # Ensure checkpoint exists on base
            checkpoints.create_checkpoint(base_proj, "m1_baseline", force=True)

            spec_path = temp_dir / "race_spec.json"
            spec_data = {
                "race_id": "test_race_01",
                "problem_snapshot": "test_problem.txt",
                "base_checkpoint": "m1_baseline",
                "candidate_models": [
                    {
                        "id": "model_a_exact",
                        "name": "Exhaustive Assignment Model",
                        "method_cards": ["milp.md"],
                        "hypothesis": "Enumeration explores all 27 combinations guaranteeing global optimum.",
                        "assumptions": ["Small finite candidate set"],
                    },
                    {
                        "id": "model_b_heuristic",
                        "name": "Greedy Allocation Model",
                        "method_cards": ["genetic_algorithm.md"],
                        "hypothesis": "Greedy allocation achieves near-optimal objective with O(N) runtime.",
                        "assumptions": ["Subproblem greedy choice property holds"],
                    },
                ],
                "evaluation": {
                    "metrics": ["optimal_cost"],
                    "required_validations": ["VAL-FEASIBILITY"],
                },
            }
            spec_path.write_text(json.dumps(spec_data, indent=2), encoding="utf-8")

            race_out = temp_dir / "race_output"
            comparison = run_model_race(spec_path, base_proj, race_out)

            # Assertions
            self.assertEqual(comparison["race_id"], "test_race_01")
            self.assertEqual(comparison["execution_mode"], "fork_and_inspect_only")
            self.assertEqual(len(comparison["candidates"]), 2)
            cands = {c["candidate_id"]: c for c in comparison["candidates"]}
            self.assertIn("model_a_exact", cands)
            self.assertIn("model_b_heuristic", cands)

            # Verify branches are physically created and independent
            branch_a = race_out / "branches" / "model_a_exact"
            branch_b = race_out / "branches" / "model_b_heuristic"
            self.assertTrue(branch_a.is_dir())
            self.assertTrue(branch_b.is_dir())

            # Verify summary JSON and markdown exist
            self.assertTrue((race_out / "race_summary.json").is_file())
            self.assertTrue((race_out / "comparison.md").is_file())
            md_text = (race_out / "comparison.md").read_text(encoding="utf-8")
            self.assertIn("model_a_exact", md_text)
            self.assertIn("model_b_heuristic", md_text)
            self.assertIn("milp.md", md_text)


if __name__ == "__main__":
    unittest.main()
