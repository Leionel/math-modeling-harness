"""A claim's supporting and counterexample cases use measured comparisons."""

from __future__ import annotations

import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from qa.validate_contracts import _claim_test_errors, _validate  # noqa: E402
from validation.obligations import evaluate_obligations  # noqa: E402


class ClaimMicrocasesTest(unittest.TestCase):
    def fixture(self) -> tuple[dict, dict, dict]:
        plan = {"claims": [{"claim_id": "C-OPT", "question_id": "q1"}]}
        cases = [
            ("supporting", "OB-SUPPORT", "support_delta", "<=", 0),
            ("counterexample", "OB-CHALLENGE", "challenge_delta", ">", 0),
        ]
        obligations = [{
            "obligation_id": obligation_id,
            "category": "objective_recomputation",
            "method": "recompute finite difference on a fixed actual quantity",
            "acceptance": {"left_metric_id": metric_id, "operator": operator, "right": {"kind": "literal", "value": 0}, "unit": "cost"},
            "required_stage": "full",
            "claim_test": {
                "claim_id": "C-OPT", "case_role": role, "optimization_variable": "planned_quantity",
                "scope": "fixed actual quantity", "boundary_case": "plan below versus above actual",
                "input_case": {"actual": 10, "planned": 9 if role == "supporting" else 11},
            },
        } for role, obligation_id, metric_id, operator, _ in cases]
        model = {"run_id": "run-1", "status": "ready", "models": [{
            "model_id": "M-OPT", "question_id": "q1", "validation_obligations": obligations,
        }]}
        observations = [{
            "obligation_id": obligation_id,
            "metrics": [{"metric_id": metric_id, "value": -1 if role == "supporting" else 1,
                         "unit": "cost", "locator": f"output.json#{metric_id}"}],
        } for role, obligation_id, metric_id, _, _ in cases]
        measurements = {"schema_version": "1.0", "run_id": "run-1", "observations": observations}
        return model, plan, measurements

    def test_pair_is_schema_valid_and_recomputed_from_measurements(self) -> None:
        model, plan, measurements = self.fixture()
        schema = json.loads((ROOT / "schemas" / "model_contract.schema.json").read_text(encoding="utf-8"))
        for obligation in model["models"][0]["validation_obligations"]:
            errors: list[str] = []
            _validate(obligation, schema["$defs"]["validation_obligation"], schema, "$", errors)
            self.assertEqual(errors, [])
        self.assertEqual(_claim_test_errors(model, plan), [])
        self.assertEqual([row["status"] for row in evaluate_obligations(model, measurements)], ["PASS", "PASS"])

        contrary = deepcopy(measurements)
        contrary["observations"][1]["metrics"][0]["value"] = -1
        self.assertEqual([row["status"] for row in evaluate_obligations(model, contrary)], ["FAIL", "PASS"])

    def test_missing_partner_and_unknown_claim_are_rejected(self) -> None:
        model, plan, _ = self.fixture()
        pair = model["models"][0]["validation_obligations"]
        pair[1]["claim_test"]["input_case"] = pair[0]["claim_test"]["input_case"]
        self.assertIn("distinct input_case", _claim_test_errors(model, plan)[0])
        model["models"][0]["validation_obligations"].pop()
        self.assertIn("requires exactly one supporting", _claim_test_errors(model, plan)[0])
        model["models"][0]["validation_obligations"][0]["claim_test"]["claim_id"] = "C-UNKNOWN"
        self.assertIn("unknown claim_id", _claim_test_errors(model, plan)[0])

    def test_extra_supporting_case_is_not_a_valid_pair(self) -> None:
        model, plan, _ = self.fixture()
        extra = deepcopy(model["models"][0]["validation_obligations"][0])
        extra["obligation_id"] = "OB-SUPPORT-2"
        extra["claim_test"]["input_case"] = {"actual": 10, "planned": 8}
        model["models"][0]["validation_obligations"].append(extra)
        self.assertIn("exactly one supporting", _claim_test_errors(model, plan)[0])


if __name__ == "__main__":
    unittest.main()
