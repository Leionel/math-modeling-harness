from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class StatisticalUnitAndOOSTest(unittest.TestCase):
    def run_checker(self, root: Path, data: Path, model: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "qa" / "check_data_contract.py"),
                "--project-root", str(root),
                "--data-contract", str(data),
                "--model-contract", str(model),
                "--strict",
                *extra,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

    def build_data_and_model(self, root: Path) -> tuple[Path, Path]:
        source = root / "observations.csv"
        source.write_text("subject,time,x,target\nA,1,2,0\nA,2,3,1\nB,1,4,0\n", encoding="utf-8")
        model = root / "model.json"
        write_json(model, {
            "schema_version": "1.3",
            "project_id": "unit-test",
            "run_id": "run-unit",
            "unit_system": "SI",
            "questions": [{"question_id": "q1", "task": "predict", "conclusion_type": "metric", "inputs": ["x"], "outputs": ["prediction"]}],
            "data_sources": [{
                "data_id": "observations", "path": source.name, "read_only": True, "sha256": sha256(source),
                "origin": "fixture", "license_or_terms": "fixture", "transformations": [], "quality_checks": ["schema"],
            }],
            "assumptions": [],
            "models": [{
                "model_id": "M1", "question_id": "q1", "name": "grouped predictor", "problem_type": "prediction",
                "characteristics": ["machine_learning"], "rationale": "fixture", "variables": [{"symbol": "x", "meaning": "feature", "unit": "unit", "domain": "x >= 0", "role": "input"}],
                "objective": "minimize prediction error", "constraints": [], "algorithm": "grouped validation",
                "inputs": ["x"], "outputs": ["prediction"], "validation": [{"check_id": "V1", "stage": "both", "method": "group split", "acceptance": "pass"}],
                "validation_obligations": [{"obligation_id": "V1", "category": "out_of_sample", "method": "GroupKFold", "acceptance": {"left_metric_id": "score", "operator": ">=", "right": {"kind": "literal", "value": 0}, "unit": "unit"}, "required_stage": "both"}],
                "risks": [], "fallback": "baseline", "decision_context": {"decision_time_column": "time", "feature_policy": "known_at_decision", "target_horizon": "one step"},
                "statistical_design": {"role": "predictive_validation", "methods": ["GroupKFold"], "waiver_reason": None, "unit_of_inference": "subject"},
            }],
            "terminology": [], "status": "ready",
        })
        data = root / "data_contract.json"
        write_json(data, {
            "schema_version": "1.0", "run_id": "run-unit", "data_id": "observations",
            "source": {"path": source.name, "sha256": sha256(source)}, "layer": "processed",
            "table": {"format": "csv", "row_count": 3, "column_count": 4, "primary_key": ["subject", "time"], "duplicate_key_count": 0, "encoding": "utf-8", "timezone": None},
            "columns": [
                {"name": "subject", "dtype": "string", "semantic_type": "entity identifier", "unit": None, "nullable": False, "missing_count": 0, "unique": False, "role": "group", "allowed": {}},
                {"name": "time", "dtype": "integer", "semantic_type": "decision time", "unit": "step", "nullable": False, "missing_count": 0, "unique": False, "role": "time", "allowed": {}},
                {"name": "x", "dtype": "number", "semantic_type": "feature", "unit": "unit", "nullable": False, "missing_count": 0, "unique": False, "role": "feature", "allowed": {}},
                {"name": "target", "dtype": "integer", "semantic_type": "target", "unit": "class", "nullable": False, "missing_count": 0, "unique": False, "role": "target", "allowed": {}},
            ],
            "invariants": [{"invariant_id": "I1", "description": "rows are parseable", "check": "csv parse", "status": "pass", "observed": True}],
            "leakage_policy": {"target_columns": ["target"], "split_keys": ["subject"], "time_boundary": "before target horizon", "forbidden_features": [], "status": "pass"},
            "profile": {"row_count": 3, "missing_cells": 0, "duplicate_rows": 0, "time_min": "1", "time_max": "2"},
            "observation_structure": {"unit_type": "entity_time", "row_granularity": "one_row_per_entity_time", "entity_key": ["subject"], "time_key": "time", "repeated_measure": True, "split_unit": "entity", "declared_entity_count": 2, "observed_entity_count": 2, "max_rows_per_entity": 2, "within_entity_time_order": "verified", "status": "validated"},
            "derived_feature_lineage": [{"feature_id": "x", "source_columns": ["time"], "derivation": "observed at decision time", "availability": "known_at_decision", "decision_time_column": "time", "cutoff_rule": "time <= decision time", "status": "verified"}],
            "status": "validated",
        })
        return data, model

    def test_repeated_entity_contract_passes_and_row_split_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="unit-contract-") as temp:
            root = Path(temp)
            data, model = self.build_data_and_model(root)
            result = self.run_checker(root, data, model, "--require-observation-structure", "--require-decision-context", "--require-statistical-design")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            contract = json.loads(data.read_text(encoding="utf-8"))
            contract["observation_structure"]["split_unit"] = "row"
            write_json(data, contract)
            result = self.run_checker(root, data, model, "--require-observation-structure")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("split_unit=row", result.stdout)

    def test_future_feature_is_rejected_at_decision_time(self) -> None:
        with tempfile.TemporaryDirectory(prefix="future-feature-") as temp:
            root = Path(temp)
            data, model = self.build_data_and_model(root)
            contract = json.loads(data.read_text(encoding="utf-8"))
            contract["derived_feature_lineage"][0]["availability"] = "future_dependent"
            write_json(data, contract)
            result = self.run_checker(root, data, model, "--require-observation-structure", "--require-decision-context")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("future_dependent", result.stdout)

    def test_raw_input_availability_distinguishes_policy_from_oracle(self) -> None:
        with tempfile.TemporaryDirectory(prefix="raw-decision-time-") as temp:
            root = Path(temp)
            data, model = self.build_data_and_model(root)
            contract = json.loads(data.read_text(encoding="utf-8"))
            contract["derived_feature_lineage"] = []
            feature = next(row for row in contract["columns"] if row["name"] == "x")
            feature["availability"] = "future_dependent"
            write_json(data, contract)
            flags = ("--require-observation-structure", "--require-decision-context")
            rejected = self.run_checker(root, data, model, *flags)
            self.assertEqual(rejected.returncode, 1, rejected.stdout + rejected.stderr)
            self.assertIn("model M1 uses feature x with availability='future_dependent'", rejected.stdout)

            model_contract = json.loads(model.read_text(encoding="utf-8"))
            model_contract["models"][0]["decision_context"]["feature_policy"] = "not_applicable"
            write_json(model, model_contract)
            oracle = self.run_checker(root, data, model, *flags)
            self.assertEqual(oracle.returncode, 0, oracle.stdout + oracle.stderr)

            feature["availability"] = "known_at_decision"
            write_json(data, contract)
            model_contract["models"][0]["decision_context"] = {
                "decision_time_column": "time", "feature_policy": "known_at_decision",
                "target_horizon": "one step", "forbidden_future_features": ["x"],
            }
            write_json(model, model_contract)
            forbidden = self.run_checker(root, data, model, *flags)
            self.assertEqual(forbidden.returncode, 1)
            self.assertIn("forbidden_future_features", forbidden.stdout)

            model_contract["models"][0]["decision_context"].pop("forbidden_future_features")
            write_json(model, model_contract)
            valid = self.run_checker(root, data, model, *flags)
            self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)

    def test_repeated_measure_ml_cannot_use_row_split_as_primary_validation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="row-split-") as temp:
            root = Path(temp)
            data, model = self.build_data_and_model(root)
            contract = json.loads(model.read_text(encoding="utf-8"))
            contract["models"][0]["statistical_design"]["methods"] = ["row_split"]
            write_json(model, contract)
            result = self.run_checker(root, data, model, "--require-observation-structure", "--require-statistical-design")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("group-aware validation", result.stdout)

    def test_oos_checker_recomputes_entity_overlap(self) -> None:
        from scripts.qa.check_oos_artifact import evaluate_oos

        with tempfile.TemporaryDirectory(prefix="oos-membership-") as temp:
            root = Path(temp)
            train = root / "train.csv"
            test = root / "test.csv"
            train.write_text("subject,time\nA,1\nB,1\n", encoding="utf-8")
            test.write_text("subject,time\nB,2\nC,2\n", encoding="utf-8")
            metrics = root / "metrics.json"
            metrics.write_text("{}\n", encoding="utf-8")
            artifact = {
                "run_id": "run-unit", "split_mode": "entity",
                "train_scenarios": {"seed": 1, "hash": "1" * 64, "count": 2, "source": "fixture"},
                "test_scenarios": {"seed": 2, "hash": "2" * 64, "count": 2, "source": "fixture"},
                "disjoint_check": "PASS", "leakage_check": "PASS",
                "metrics_artifact": {"path": metrics.name},
                "membership": {"key_columns": ["subject"], "train": {"path": train.name}, "test": {"path": test.name}},
            }
            errors = evaluate_oos(artifact, root, "run-unit", require_design=True)
            self.assertTrue(any("overlap" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
