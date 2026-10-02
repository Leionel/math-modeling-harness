"""Status transport failures must never become readiness claims."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from mcp_tools.state import get_run_state  # noqa: E402
from harness_status import _next_action  # noqa: E402


class StateProjectionTest(unittest.TestCase):
    def project(self, code, stdout):
        return get_run_state(Path("."), {}, {
            "HARNESS_CLI": "harness.py",
            "run_harness": lambda argv, root: (code, stdout, ""),
        })

    def test_failed_status_never_reports_ready(self):
        for code, stdout in [(2, ""), (0, "broken"), (0, "[]"),
                             (0, '{"ok":false}'), (2, '{"ok":true}')]:
            with self.subTest(code=code, stdout=stdout):
                result = self.project(code, stdout)
                self.assertEqual(result["gate_status"], "ERROR")
                self.assertTrue(result["errors"])

    def test_gate_blocker_keeps_identity_and_action(self):
        result = self.project(0, json.dumps({
            "ok": True, "first_blocked_gate": "m1", "failures_summary": {"items": [
                {"source": "gate", "id": "m1", "message": "missing contract", "next_action": "compile model"},
                {"source": "receipt", "id": "R1", "message": "failed"},
            ]},
        }))
        self.assertEqual(result["gate_status"], "BLOCKED")
        self.assertEqual(result["next_actions"], ["compile model"])
        self.assertEqual(len(result["blockers"]), 1)

    def test_legacy_status_does_not_claim_recomputed_readiness(self):
        result = self.project(0, '{"ok":true,"deprecated":true,"deprecation":"migrate"}')
        self.assertEqual(result["gate_status"], "LEGACY")

    def test_future_checkpoint_does_not_displace_current_gate(self):
        action = _next_action("m1", [{"stage": "w2"}], [])
        self.assertIn("M1", action)
        self.assertNotIn("human review pending", action)
