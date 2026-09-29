"""Evaluation surface tests.

The reliability suite is slow because it builds a real project, so CI runs it as
its own step. What this test guards is the part that must never rot: the ablation
surface refuses to invent results, and the red-team outcome vocabulary cannot
silently drift out of sync with the README's boundary claims.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evaluation"))

import ablation  # noqa: E402
import redteam  # noqa: E402


class AblationSurfaceTest(unittest.TestCase):
    def test_plan_refuses_to_report_results(self) -> None:
        report = ablation.run(None)
        self.assertEqual(report["status"], "NOT_RUN")
        self.assertIn("no real backend runs", report["reason"])
        self.assertEqual(len(report["conditions"]), 3)
        self.assertIn("C_multi_agent_with_harness", report["conditions"])

    def test_pre_registered_metrics_cover_the_readme_claims(self) -> None:
        for metric in (
            "gate_bypass_rate", "fabricated_evidence_rate", "stale_artifact_acceptance_rate",
            "unsupported_claim_rate", "reviewer_independence_violation_rate",
        ):
            self.assertIn(metric, ablation.METRICS)

    def test_cli_plan_is_readable_without_a_results_dir(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "evaluation" / "ablation.py"), "plan"],
            text=True, capture_output=True, encoding="utf-8", errors="replace", check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("NOT_RUN", completed.stdout)

    def test_score_rejects_a_partial_condition_matrix(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            partial = Path(temp)
            (partial / "A_single_llm_prompt").mkdir()
            (partial / "A_single_llm_prompt" / "run_log.json").write_text(
                json.dumps({"target_stage": "W2", "runs": []}), encoding="utf-8",
            )
            with self.assertRaises(SystemExit) as raised:
                ablation.run(partial)
            self.assertIn("missing conditions", str(raised.exception))

    def test_score_cli_rejects_three_empty_run_logs(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            results = Path(temp)
            for name in ablation.CONDITIONS:
                condition = results / name
                condition.mkdir()
                (condition / "run_log.json").write_text(
                    json.dumps({"target_stage": "F1", "runs": []}), encoding="utf-8",
                )
            completed = subprocess.run(
                [sys.executable, str(ROOT / "evaluation" / "ablation.py"),
                 "score", "--results-dir", str(results), "--json"],
                text=True, capture_output=True, encoding="utf-8", errors="replace", check=False,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("expected 12 runs", completed.stderr)
            self.assertNotIn('"status": "RUN"', completed.stdout)


class RedTeamSurfaceTest(unittest.TestCase):
    def test_every_scenario_declares_an_expected_outcome(self) -> None:
        chain = {kind for kind, _, _ in redteam.CHAIN_SCENARIOS}
        self.assertEqual(len(redteam.CHAIN_SCENARIOS), 6)
        self.assertIn("gate_bypass", chain)
        self.assertIn("reviewer_independence_violation", chain)

    def test_invariant_outcome_marks_expected_allows_as_documented_gaps(self) -> None:
        row = redteam.outcome(
            "fabricated_evidence", "x", "p", "a",
            expect="allowed", actual="allowed", evidence=["no signature"],
        )
        self.assertTrue(row["held"])
        self.assertEqual(row["actual"], "allowed")

    def test_a_closed_gap_fails_the_suite_so_docs_cannot_go_stale(self) -> None:
        row = redteam.outcome(
            "fabricated_evidence", "x", "p", "a",
            expect="allowed", actual="blocked", evidence=["now refused"],
        )
        self.assertFalse(row["held"])

    def test_inert_projection_outcome_counts_as_defended(self) -> None:
        report = {
            "ok": True,
            "metrics": {"fabricated_evidence": {"attempts": 1, "blocked": 1, "gaps": 0, "held": 1}},
            "scenarios": [redteam.outcome(
                "fabricated_evidence", "x", "p", "a",
                expect="inert", actual="inert", evidence=["never read"],
            )],
            "not_measured": ["LLM task quality"],
        }
        rendered = redteam.render_human(report)  # type: ignore[arg-type]
        self.assertIn("PASS", rendered)
        self.assertIn("LLM task quality", rendered)


if __name__ == "__main__":
    unittest.main()
