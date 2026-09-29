"""Unit tests for receipt generation supersession, lineage validation and error modes."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from v2_gate_runtime import _v2_resolve_active_freeze_lineage  # noqa: E402


class SupersessionLineageTest(unittest.TestCase):
    def test_single_receipt_lineage(self) -> None:
        receipts = [
            {"receipt_id": "R1", "stage": "freeze", "run_id": "run-1", "exit_code": 0},
        ]
        errors: list[str] = []
        active = _v2_resolve_active_freeze_lineage(receipts, "run-1", errors)
        self.assertEqual(errors, [])
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["receipt_id"], "R1")

    def test_linear_supersession_chain(self) -> None:
        receipts = [
            {"receipt_id": "R1", "stage": "freeze", "run_id": "run-1", "exit_code": 0, "generation": 1},
            {"receipt_id": "R2", "stage": "freeze", "run_id": "run-1", "exit_code": 0, "generation": 2, "supersedes_receipt_id": "R1"},
            {"receipt_id": "R3", "stage": "freeze", "run_id": "run-1", "exit_code": 0, "generation": 3, "supersedes_receipt_id": "R2"},
        ]
        errors: list[str] = []
        active = _v2_resolve_active_freeze_lineage(receipts, "run-1", errors)
        self.assertEqual(errors, [])
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["receipt_id"], "R3")

    def test_reject_superseding_unknown_predecessor(self) -> None:
        receipts = [
            {"receipt_id": "R2", "stage": "freeze", "run_id": "run-1", "exit_code": 0, "generation": 2, "supersedes_receipt_id": "R_NONEXISTENT"},
        ]
        errors: list[str] = []
        _ = _v2_resolve_active_freeze_lineage(receipts, "run-1", errors)
        self.assertTrue(any("unknown or unsuccessful freeze receipt" in err for err in errors))

    def test_reject_self_loop(self) -> None:
        receipts = [
            {"receipt_id": "R1", "stage": "freeze", "run_id": "run-1", "exit_code": 0, "supersedes_receipt_id": "R1"},
        ]
        errors: list[str] = []
        _ = _v2_resolve_active_freeze_lineage(receipts, "run-1", errors)
        self.assertTrue(any("cannot supersede itself" in err for err in errors))

    def test_reject_multiple_active_lineages_from_fork(self) -> None:
        # R1 superseded by both R2a and R2b -> conflicting active heads
        receipts = [
            {"receipt_id": "R1", "stage": "freeze", "run_id": "run-1", "exit_code": 0, "generation": 1},
            {"receipt_id": "R2a", "stage": "freeze", "run_id": "run-1", "exit_code": 0, "generation": 2, "supersedes_receipt_id": "R1"},
            {"receipt_id": "R2b", "stage": "freeze", "run_id": "run-1", "exit_code": 0, "generation": 2, "supersedes_receipt_id": "R1"},
        ]
        errors: list[str] = []
        active = _v2_resolve_active_freeze_lineage(receipts, "run-1", errors)
        self.assertTrue(any("conflicting supersession" in err for err in errors))
        self.assertEqual(len(active), 0)

    def test_two_independent_unlinked_roots(self) -> None:
        # Two independent freeze receipts neither of which supersedes the other
        receipts = [
            {"receipt_id": "R1", "stage": "freeze", "run_id": "run-1", "exit_code": 0},
            {"receipt_id": "R2", "stage": "freeze", "run_id": "run-1", "exit_code": 0},
        ]
        errors: list[str] = []
        active = _v2_resolve_active_freeze_lineage(receipts, "run-1", errors)
        self.assertTrue(any("exactly one active freeze lineage, found 2" in err for err in errors))
        self.assertEqual(len(active), 0)


if __name__ == "__main__":
    unittest.main()
