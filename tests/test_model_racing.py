"""Regression tests for minimal Model Racing workflow."""

from __future__ import annotations

import json
import shutil
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
from model_racing import run_model_race  # noqa: E402


class ModelRacingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = built_fixture()

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
