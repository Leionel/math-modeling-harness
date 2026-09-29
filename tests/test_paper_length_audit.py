from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from qa.audit_paper_length import evaluate_length_audit  # noqa: E402


def plan(*, include_anchor: bool = True) -> dict:
    coverage = (
        {
            "status": "planned",
            "anchors": [
                {
                    "anchor_id": "CORE",
                    "unit_id": "U-CORE",
                    "question_id": "q1",
                    "patterns": ["[[CORE]]"],
                }
            ],
        }
        if include_anchor
        else {"status": "planned", "anchors": []}
    )
    return {
        "claims": [{"claim_id": "C1", "question_id": "q1"}],
        "argument_units": [
            {
                "unit_id": "U-CORE",
                "section_id": "model",
                "rhetorical_role": "mechanism_derivation",
                "claim_ids": ["C1"],
                "depth_priority": {"level": "core", "rationale": "central mechanism"},
            }
        ],
        "draft_coverage": coverage,
    }


class PaperLengthAuditTest(unittest.TestCase):
    def test_missing_anchored_core_argument_is_a_hard_failure(self) -> None:
        report = evaluate_length_audit(
            plan(),
            {"status": "verified", "submission": {"max_pages": 8}},
            "No declared core discussion.",
            page_count=4,
        )

        self.assertEqual(report["summary"]["verdict"], "fail")
        self.assertIn("core argument unit U-CORE", report["errors"][0])
        self.assertEqual(report["triage"][0]["kind"], "CORE_ARGUMENT_MISSING")

    def test_page_limit_is_hard_only_for_verified_profile(self) -> None:
        report = evaluate_length_audit(
            plan(),
            {"status": "verified", "submission": {"max_pages": 2}},
            "[[CORE]] Mechanism and constraint explain the selected decision.",
            page_count=3,
        )

        self.assertEqual(report["summary"]["verdict"], "fail")
        self.assertTrue(
            any(row["kind"] == "PAGE_LIMIT_EXCEEDED" for row in report["triage"])
        )

        seed_report = evaluate_length_audit(
            plan(),
            {"status": "seed", "submission": {"max_pages": 2}},
            "[[CORE]] Mechanism and constraint explain the selected decision.",
            page_count=3,
        )
        self.assertEqual(
            seed_report["summary"]["verdict"], "pass_with_manual_layout_review"
        )
        self.assertFalse(seed_report["errors"])
        self.assertTrue(seed_report["warnings"])

    def test_pdf_total_does_not_trigger_body_page_limit(self) -> None:
        report = evaluate_length_audit(
            plan(),
            {"status": "verified", "submission": {"max_pages": 30, "page_count_scope": "paper_body"}},
            "[[CORE]] Mechanism and constraint explain the selected decision.",
            page_count=42,
        )
        self.assertFalse(any(row["kind"] == "PAGE_LIMIT_EXCEEDED" for row in report["triage"]))
        self.assertTrue(any("body pages separately" in warning for warning in report["warnings"]))


if __name__ == "__main__":
    unittest.main()
