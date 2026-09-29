#!/usr/bin/env python3
"""Validate the five solve-stage contracts and their cross-references."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from _common import load_structured, rel_path, resolve_path, sha256_file, sha256_json  # noqa: E402
from validation.obligations import file_ref, verify_validation_report  # noqa: E402
from runtime_state import RuntimeStateError, load_runtime_state  # noqa: E402


REQUIRED_VALIDATION_CATEGORIES = {
    "optimization": {"feasibility", "objective_recomputation"},
    "prediction": {"out_of_sample", "leakage", "baseline"},
    "classification": {"out_of_sample", "leakage", "baseline"},
    "time_series": {"out_of_sample", "leakage", "baseline"},
    "evaluation": {"sensitivity", "stability"},
    "simulation": {"uncertainty", "convergence"},
    "differential_equation": {"numerical_error", "sensitivity"},
    "statistical_inference": {"uncertainty"},
}
ARTIFACT_REQUIRED_BY_CATEGORY = {
    "sensitivity": "sensitivity_experiment",
    "out_of_sample": "oos_artifact",
}


def _claim_test_errors(model: Mapping[str, Any], plan: Mapping[str, Any]) -> list[str]:
    """Check that an opt-in microcase pair belongs to one paper claim."""

    errors: list[str] = []
    claims = {row["claim_id"]: row for row in plan.get("claims", []) if isinstance(row, dict)}
    tested: dict[str, list[dict[str, Any]]] = {}
    for model_row in model.get("models", []):
        for obligation in model_row.get("validation_obligations", []):
            claim_test = obligation.get("claim_test")
            if not isinstance(claim_test, dict):
                continue
            claim_id = claim_test.get("claim_id")
            if claim_id not in claims:
                errors.append(f"validation obligation {obligation.get('obligation_id')} tests unknown claim_id {claim_id}")
                continue
            if claims[claim_id].get("question_id") != model_row.get("question_id"):
                errors.append(f"validation obligation {obligation.get('obligation_id')} tests claim {claim_id} from another question")
            tested.setdefault(claim_id, []).append(claim_test)
    for claim_id, rows in tested.items():
        roles = {row.get("case_role") for row in rows}
        if len(rows) != 2 or roles != {"supporting", "counterexample"}:
            errors.append(f"claim {claim_id} requires exactly one supporting and one counterexample validation obligation")
        if len({row.get("optimization_variable") for row in rows}) != 1:
            errors.append(f"claim {claim_id} microcases must use one optimization variable")
        input_cases = {json.dumps(row.get("input_case"), ensure_ascii=False, sort_keys=True) for row in rows}
        if len(input_cases) != len(rows):
            errors.append(f"claim {claim_id} microcases must use distinct input_case values")
    return errors


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    return True


def _resolve_ref(root_schema: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        raise ValueError(f"only local schema refs are supported: {ref}")
    node: Any = root_schema
    for part in ref[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    if not isinstance(node, dict):
        raise ValueError(f"schema ref does not resolve to an object: {ref}")
    return node


def _validate(value: Any, schema: dict[str, Any], root_schema: dict[str, Any], path: str, errors: list[str]) -> None:
    if "$ref" in schema:
        _validate(value, _resolve_ref(root_schema, schema["$ref"]), root_schema, path, errors)
        return

    if "allOf" in schema:
        for child in schema["allOf"]:
            _validate(value, child, root_schema, path, errors)
    if "oneOf" in schema:
        branches: list[list[str]] = []
        for child in schema["oneOf"]:
            child_errors: list[str] = []
            _validate(value, child, root_schema, path, child_errors)
            branches.append(child_errors)
        if not any(not branch for branch in branches):
            errors.append(f"{path}: does not match any oneOf branch")
            return

    expected = schema.get("type")
    if expected is not None:
        expected_types = expected if isinstance(expected, list) else [expected]
        if not any(_type_matches(value, item) for item in expected_types):
            errors.append(f"{path}: expected type {expected_types}, got {type(value).__name__}")
            return

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: expected one of {schema['enum']!r}")

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: length is below minLength={schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: length exceeds maxLength={schema['maxLength']}")
        if "pattern" in schema:
            try:
                matched = re.search(schema["pattern"], value)
            except re.error as exc:
                errors.append(f"{path}: invalid schema pattern: {exc}")
                matched = True
            if not matched:
                errors.append(f"{path}: does not match pattern {schema['pattern']!r}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: value is below minimum={schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: value exceeds maximum={schema['maximum']}")

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: item count is below minItems={schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: item count exceeds maxItems={schema['maxItems']}")
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in value]
            if len(encoded) != len(set(encoded)):
                errors.append(f"{path}: items must be unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate(item, item_schema, root_schema, f"{path}[{index}]", errors)

    if isinstance(value, dict):
        if len(value) < schema.get("minProperties", 0):
            errors.append(f"{path}: property count is below minProperties={schema['minProperties']}")
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            errors.append(f"{path}: property count exceeds maxProperties={schema['maxProperties']}")
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}: unexpected property {key!r}")
        for key, child_schema in properties.items():
            if key in value:
                _validate(value[key], child_schema, root_schema, f"{path}.{key}", errors)
        additional = schema.get("additionalProperties")
        if isinstance(additional, dict):
            for key, item in value.items():
                if key not in properties:
                    _validate(item, additional, root_schema, f"{path}.{key}", errors)


def _validate_document(path: Path, schema_path: Path) -> tuple[Any | None, list[str], str]:
    try:
        value = load_structured(path)
        schema = load_structured(schema_path)
        if not isinstance(schema, dict):
            return value, [f"{schema_path}: schema must be an object"], "fallback"
        errors: list[str] = []
        _validate(value, schema, schema, "$", errors)
        return value, errors, "fallback"
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return None, [f"{path}: {exc}"], "fallback"


def validate_value(value: Any, schema_path: Path) -> list[str]:
    """Validate an in-memory producer result before its first write."""

    schema = load_structured(schema_path)
    if not isinstance(schema, dict):
        return [f"{schema_path}: schema must be an object"]
    errors: list[str] = []
    _validate(value, schema, schema, "$", errors)
    return errors


def _cross_references_v2(
    model: dict[str, Any],
    manifest: dict[str, Any],
    frozen: dict[str, Any],
    registry: dict[str, Any],
    plan: dict[str, Any],
    *,
    root: Path,
    paths: dict[str, Path],
) -> tuple[list[str], list[str]]:
    """Validate shared solve contracts against normalized v2 roots.

    This deliberately checks canonical references and result semantics only;
    the v1 artifact list/profile fields are not reconstructed for v2.
    """

    errors: list[str] = []
    warnings: list[str] = []
    try:
        state = load_runtime_state(paths["run_manifest"], project_root=root, allow_legacy=False)
    except (OSError, ValueError, TypeError, RuntimeStateError) as exc:
        return [f"v2 runtime boundary: {exc}"], warnings
    if manifest.get("schema_version") != "2.0":
        errors.append("v2 normalized manifest is required")
    if any(key in manifest for key in ("competition_profile", "commands", "artifacts", "gates", "reviewer")):
        errors.append("v2 run_manifest contains duplicated v1 state")
    run_ids = {
        label: value.get("run_id")
        for label, value in (("model_contract", model), ("run_manifest", manifest), ("frozen_results", frozen), ("evidence_registry", registry), ("paper_plan", plan))
        if isinstance(value, dict) and value.get("run_id") is not None
    }
    if len(set(run_ids.values())) > 1:
        errors.append(f"run_id mismatch across contracts: {run_ids}")
    if model.get("project_id") != manifest.get("project_id"):
        errors.append("run_manifest.project_id does not match model_contract.project_id")
    model_root = state.root_path("model_contract")
    if model_root is None or model_root.resolve() != paths["model_contract"].resolve():
        errors.append("run_manifest roots.model_contract is not the supplied model contract")
    if not state.profile_path.is_file() or state.profile.get("profile_id") != manifest.get("competition_profile_ref", {}).get("profile_id"):
        errors.append("canonical competition_profile_ref does not resolve to the declared profile")
    # Shared frozen truth checks remain independent of the profile/Gate state.
    results = frozen.get("results", [])
    if frozen.get("results_sha256") != sha256_json(results):
        errors.append("frozen_results.results_sha256 does not match the canonical results array")
    verdict = frozen.get("validation_verdict")
    if verdict not in {"PASS", "FAIL", "ERROR"}:
        errors.append("frozen_results.validation_verdict must be PASS, FAIL, or ERROR")
    elif frozen.get("claimable") is not (verdict == "PASS"):
        errors.append("frozen_results.claimable must be derived from validation_verdict")
    for field in ("model_contract_snapshot", "source_snapshot"):
        ref = frozen.get(field)
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
            errors.append(f"frozen_results.{field} must be a file reference")
            continue
        path = resolve_path(ref["path"], root).resolve()
        if not path.is_file() or ref.get("sha256") != sha256_file(path):
            errors.append(f"frozen_results.{field} SHA-256 drift")
    for label, value in (("evidence_registry", registry), ("paper_plan", plan)):
        if value.get("run_id") != manifest.get("run_id"):
            errors.append(f"{label}.run_id does not match run_manifest.run_id")
    return errors, warnings


def _cross_references(
    model: dict[str, Any],
    manifest: dict[str, Any],
    frozen: dict[str, Any],
    registry: dict[str, Any],
    plan: dict[str, Any],
    *,
    root: Path,
    paths: dict[str, Path],
) -> tuple[list[str], list[str]]:
    if manifest.get("schema_version") == "2.0":
        return _cross_references_v2(model, manifest, frozen, registry, plan, root=root, paths=paths)
    errors: list[str] = []
    warnings: list[str] = []
    require_hashes = manifest.get("integrity_mode", "research") == "submission"

    def unique(label: str, values: list[Any]) -> set[Any]:
        if len(values) != len(set(values)):
            errors.append(f"{label} values must be unique")
        return set(values)

    def verify_file_ref(owner: str, ref: dict[str, Any]) -> Path | None:
        raw_path = ref.get("path")
        if not isinstance(raw_path, str):
            errors.append(f"{owner}.path must be a string")
            return None
        if raw_path.startswith(("http://", "https://", "s3://", "artifact://")):
            warnings.append(f"{owner} uses external path {raw_path}; local hash verification skipped")
            return None
        path = resolve_path(raw_path, root).resolve()
        if not path.is_file():
            errors.append(f"{owner} path does not exist: {raw_path}")
            return None
        expected = ref.get("sha256")
        if expected is None:
            if require_hashes:
                errors.append(f"{owner}.sha256 is required in submission integrity mode")
            return path
        actual = sha256_file(path)
        if expected != actual:
            errors.append(f"{owner} sha256 does not match {raw_path}")
        return path

    run_ids = {
        label: value.get("run_id")
        for label, value in (("model_contract", model), ("run_manifest", manifest), ("frozen_results", frozen), ("evidence_registry", registry), ("paper_plan", plan))
        if isinstance(value, dict) and value.get("run_id") is not None
    }
    if len(set(run_ids.values())) > 1:
        errors.append(f"run_id mismatch across contracts: {run_ids}")

    if manifest.get("project_id") != model.get("project_id"):
        errors.append("run_manifest.project_id does not match model_contract.project_id")
    manifest_model_path = verify_file_ref("run_manifest.model_contract", manifest["model_contract"])
    if manifest_model_path is not None and manifest_model_path != paths["model_contract"].resolve():
        errors.append("run_manifest.model_contract.path is not the supplied model contract")
    for index, artifact in enumerate(manifest.get("artifacts", [])):
        verify_file_ref(f"run_manifest.artifacts[{index}]", artifact)
    for index, rule in enumerate(manifest.get("competition_profile", {}).get("official_rules", [])):
        verify_file_ref(f"run_manifest.competition_profile.official_rules[{index}].snapshot", rule["snapshot"])
    for index, usage in enumerate(manifest.get("ai_usage", [])):
        verify_file_ref(f"run_manifest.ai_usage[{index}].interaction_record", usage["interaction_record"])
    for checkpoint_index, checkpoint in enumerate(manifest.get("human_checkpoints", [])):
        for artifact_index, ref in enumerate(checkpoint.get("artifacts", [])):
            verify_file_ref(
                f"run_manifest.human_checkpoints[{checkpoint_index}].artifacts[{artifact_index}]", ref
            )

    question_ids = [row["question_id"] for row in model["questions"]]
    question_set = unique("model_contract question_id", question_ids)
    question_by_id = {row["question_id"]: row for row in model["questions"]}
    data_ids = [row["data_id"] for row in model["data_sources"]]
    unique("model_contract data_id", data_ids)
    assumption_ids = [row["assumption_id"] for row in model["assumptions"]]
    unique("model_contract assumption_id", assumption_ids)
    model_ids = [row["model_id"] for row in model["models"]]
    unique("model_contract model_id", model_ids)
    term_names = [row["canonical"] for row in model["terminology"]]
    unique("model_contract terminology canonical", term_names)
    for index, source in enumerate(model["data_sources"]):
        verify_file_ref(f"model_contract.data_sources[{index}]", source)
    for question in model["questions"]:
        for dependency in question.get("depends_on", []):
            if dependency not in question_set:
                errors.append(f"question {question['question_id']} depends on unknown question_id {dependency}")
            if dependency == question["question_id"]:
                errors.append(f"question {question['question_id']} cannot depend on itself")
    obligation_ids: list[str] = []
    for row in model.get("models", []):
        if row.get("question_id") not in question_set:
            errors.append(f"model {row.get('model_id')} references unknown question_id {row.get('question_id')}")
            continue
        unique(f"model {row['model_id']} variable symbol", [item["symbol"] for item in row["variables"]])
        unique(f"model {row['model_id']} constraint_id", [item["constraint_id"] for item in row["constraints"]])
        unique(f"model {row['model_id']} validation check_id", [item["check_id"] for item in row["validation"]])
        model_obligations = [item["obligation_id"] for item in row["validation_obligations"]]
        unique(f"model {row['model_id']} validation obligation_id", model_obligations)
        obligation_ids.extend(model_obligations)
        categories = {item["category"] for item in row["validation_obligations"]}
        missing_categories = sorted(REQUIRED_VALIDATION_CATEGORIES.get(row.get("problem_type"), set()) - categories)
        if missing_categories:
            errors.append(
                f"model {row['model_id']} problem_type={row.get('problem_type')} is missing validation category/categories: {missing_categories}"
            )
        for obligation in row["validation_obligations"]:
            expected_role = ARTIFACT_REQUIRED_BY_CATEGORY.get(obligation.get("category"))
            if expected_role and obligation.get("artifact_role") != expected_role:
                errors.append(
                    f"model {row['model_id']} obligation {obligation.get('obligation_id')} "
                    f"category={obligation.get('category')} requires artifact_role={expected_role}"
                )
        details = row.get("plan_details")
        if isinstance(details, dict):
            parameter_names = {
                item.get("parameter")
                for item in details.get("parameter_plan", [])
                if isinstance(item, dict) and isinstance(item.get("parameter"), str)
            }
            uncovered_inputs = sorted(
                input_name for input_name in row.get("inputs", [])
                if isinstance(input_name, str) and input_name not in parameter_names
            )
            if uncovered_inputs:
                errors.append(
                    f"model {row['model_id']} inputs lack typed parameter provenance: {uncovered_inputs}"
                )
        unknown_outputs = set(row["outputs"]) - set(question_by_id[row["question_id"]]["outputs"])
        if unknown_outputs:
            errors.append(f"model {row['model_id']} outputs are not declared by its question: {sorted(unknown_outputs)}")
    obligation_set = unique("model_contract validation obligation_id", obligation_ids)

    frozen_results = frozen.get("results", [])
    result_ids = [row["result_id"] for row in frozen_results]
    result_set = unique("frozen_results result_id", result_ids)
    for result in frozen_results:
        if result["question_id"] not in question_set:
            errors.append(f"result {result['result_id']} references unknown question_id {result['question_id']}")
    if frozen.get("results_sha256") and frozen["results_sha256"] != sha256_json(frozen_results):
        errors.append("frozen_results.results_sha256 does not match the canonical results array")
    frozen_verdict = frozen.get("validation_verdict")
    frozen_claimable = frozen.get("claimable")
    frozen_statuses = [row.get("status") for row in frozen.get("validation_obligations", []) if isinstance(row, dict)]
    if frozen_verdict not in {"PASS", "FAIL", "ERROR"}:
        errors.append("frozen_results.validation_verdict must be PASS, FAIL, or ERROR")
    elif frozen_verdict == "PASS" and any(status != "PASS" for status in frozen_statuses):
        errors.append("frozen_results.validation_verdict=PASS conflicts with obligation verdicts")
    elif frozen_verdict == "FAIL" and "FAIL" not in frozen_statuses:
        errors.append("frozen_results.validation_verdict=FAIL requires at least one FAIL obligation")
    elif frozen_verdict == "ERROR" and "ERROR" not in frozen_statuses:
        errors.append("frozen_results.validation_verdict=ERROR requires at least one ERROR obligation")
    expected_claimable = frozen_verdict == "PASS"
    if frozen_claimable is not expected_claimable:
        errors.append("frozen_results.claimable must be derived from validation_verdict")
    for field in ("model_contract_snapshot", "source_snapshot"):
        verify_file_ref(f"frozen_results.{field}", frozen[field])
    frozen_model_path = resolve_path(frozen["model_contract_snapshot"]["path"], root).resolve()
    if frozen_model_path != paths["model_contract"].resolve():
        errors.append("frozen_results.model_contract_snapshot is not the supplied model contract")
    for field in ("input_snapshot", "code_snapshot", "validation_snapshot"):
        for index, ref in enumerate(frozen[field]):
            verify_file_ref(f"frozen_results.{field}[{index}]", ref)
    frozen_obligations = frozen.get("validation_obligations", [])
    frozen_obligation_ids = [row.get("obligation_id") for row in frozen_obligations]
    unique("frozen_results validation obligation_id", frozen_obligation_ids)
    if set(frozen_obligation_ids) != obligation_set:
        errors.append("frozen_results validation obligations do not match model_contract")
    validation_refs = {
        (ref.get("path"), ref.get("sha256"))
        for ref in frozen.get("validation_snapshot", [])
        if isinstance(ref, dict)
    }
    for row in frozen_obligations:
        ref = row.get("report", {})
        if (ref.get("path"), ref.get("sha256")) not in validation_refs:
            errors.append(f"validation obligation {row.get('obligation_id')} report is not in validation_snapshot")
    derived_obligations: dict[str, dict[str, Any]] = {}
    for index, ref in enumerate(frozen.get("validation_snapshot", [])):
        report_path = verify_file_ref(f"frozen_results.validation_snapshot[{index}]", ref)
        if report_path is None:
            continue
        try:
            report = load_structured(report_path)
            if not isinstance(report, dict):
                raise ValueError("validation report must be an object")
            measurement_ref = report.get("measurement_snapshot")
            if not isinstance(measurement_ref, dict):
                raise ValueError("validation report has no measurement_snapshot")
            measurements_path = verify_file_ref(
                f"validation report {rel_path(report_path, root)}.measurement_snapshot", measurement_ref
            )
            if measurements_path is None:
                continue
            measurements = load_structured(measurements_path)
            if not isinstance(measurements, dict):
                raise ValueError("measurement snapshot must be an object")
            expected_report = verify_validation_report(
                report,
                model,
                measurements,
                file_ref(paths["model_contract"], root),
                file_ref(measurements_path, root),
            )
            for expected_row in expected_report["obligations"]:
                obligation_id = expected_row["obligation_id"]
                if obligation_id in derived_obligations:
                    errors.append(f"validation obligation {obligation_id} is derived by more than one report")
                derived_obligations[obligation_id] = {
                    "obligation_id": obligation_id,
                    "status": expected_row["status"],
                    "report": ref,
                }
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"cannot independently verify validation report {ref.get('path')}: {exc}")
    frozen_by_id = {
        row.get("obligation_id"): row
        for row in frozen_obligations
        if isinstance(row, dict) and isinstance(row.get("obligation_id"), str)
    }
    if derived_obligations and frozen_by_id != derived_obligations:
        errors.append("frozen_results.validation_obligations do not equal independently recomputed validation report rows")
    for result in frozen_results:
        expected_result_status = {"PASS": "passed", "FAIL": "failed", "ERROR": "error"}.get(frozen_verdict)
        if expected_result_status is not None and result.get("validation_status") != expected_result_status:
            errors.append(f"result {result.get('result_id')} validation_status conflicts with frozen validation_verdict")
        if result.get("claimable") is not expected_claimable:
            errors.append(f"result {result.get('result_id')} claimable must match frozen_results.claimable")

    frozen_registry_snapshots = [
        row for row in registry.get("source_snapshots", [])
        if isinstance(row, dict) and row.get("kind") == "frozen_results"
    ]
    supplied_frozen = paths["frozen_results"].resolve()
    matching_snapshot = False
    for index, snapshot in enumerate(registry.get("source_snapshots", [])):
        snapshot_path = verify_file_ref(f"evidence_registry.source_snapshots[{index}]", snapshot)
        if (
            snapshot.get("kind") == "frozen_results"
            and snapshot_path == supplied_frozen
            and snapshot.get("sha256") == sha256_file(supplied_frozen)
        ):
            matching_snapshot = True
    if not frozen_registry_snapshots or not matching_snapshot:
        errors.append("evidence_registry has no current frozen_results source snapshot")

    evidence_rows = registry.get("evidence", [])
    evidence_ids = [row["evidence_id"] for row in evidence_rows]
    evidence_set = unique("evidence_registry evidence_id", evidence_ids)
    evidence_by_id = {row["evidence_id"]: row for row in evidence_rows}
    for evidence in evidence_rows:
        for result_id in evidence["result_ids"]:
            if result_id not in result_set:
                errors.append(f"evidence {evidence['evidence_id']} references unknown result_id {result_id}")
        if evidence["type"] == "result" and not evidence["result_ids"]:
            errors.append(f"result evidence {evidence['evidence_id']} must reference at least one result_id")
        if evidence["type"] == "citation":
            citation = evidence.get("citation")
            if not isinstance(citation, dict):
                errors.append(f"citation evidence {evidence['evidence_id']} has no citation contract")
            elif evidence["verification_status"] == "verified":
                for field in ("metadata_verified", "content_verified", "publication_status_checked"):
                    if citation.get(field) is not True:
                        errors.append(
                            f"verified citation evidence {evidence['evidence_id']} requires citation.{field}=true"
                        )
                if citation.get("access_level") != "full_text":
                    errors.append(f"verified citation evidence {evidence['evidence_id']} requires full_text access")
        elif "citation" in evidence:
            errors.append(f"non-citation evidence {evidence['evidence_id']} must not contain citation metadata")
        for index, ref in enumerate(evidence["artifacts"]):
            verify_file_ref(f"evidence {evidence['evidence_id']}.artifacts[{index}]", ref)
    if not expected_claimable:
        result_evidence = [row for row in evidence_rows if isinstance(row, dict) and row.get("type") == "result"]
        if result_evidence:
            errors.append("non-claimable frozen results cannot generate result evidence")

    requirement_ids = [row["requirement_id"] for row in plan["requirements"]]
    unique("paper_plan requirement_id", requirement_ids)
    claim_ids = [row["claim_id"] for row in plan["claims"]]
    claim_set = unique("paper_plan claim_id", claim_ids)
    claim_by_id = {row["claim_id"]: row for row in plan["claims"]}
    errors.extend(_claim_test_errors(model, plan))
    section_ids = [row["section_id"] for row in plan["sections"]]
    section_set = unique("paper_plan section_id", section_ids)
    argument_units = plan.get("argument_units", [])
    argument_unit_ids = [row["unit_id"] for row in argument_units]
    argument_unit_set = unique("paper_plan argument unit_id", argument_unit_ids)
    figure_ids = [row["figure_id"] for row in plan["figures"]]
    unique("paper_plan figure_id", figure_ids)
    table_ids = [row["table_id"] for row in plan["tables"]]
    unique("paper_plan table_id", table_ids)
    unique("paper_plan deliverable_id", [row["deliverable_id"] for row in plan.get("deliverables", [])])
    unique("paper_plan terminology canonical", [row["canonical"] for row in plan["terminology"]])

    def check_claim_refs(owner: str, row: dict[str, Any]) -> None:
        for claim_id in row.get("claim_ids", []):
            if claim_id not in claim_set:
                errors.append(f"{owner} references unknown claim_id {claim_id}")

    def check_evidence_refs(owner: str, row: dict[str, Any]) -> None:
        for evidence_id in row.get("evidence_ids", []):
            if evidence_id not in evidence_set:
                errors.append(f"{owner} references unknown evidence_id {evidence_id}")
            elif evidence_by_id[evidence_id]["verification_status"] != "verified":
                errors.append(f"{owner} references evidence {evidence_id} that is not verified")

    for requirement in plan.get("requirements", []):
        for claim_id in requirement.get("claim_ids", []):
            if claim_id not in claim_set:
                errors.append(f"requirement {requirement.get('requirement_id')} references unknown claim_id {claim_id}")
    for claim in plan.get("claims", []):
        if claim["question_id"] not in question_set:
            errors.append(f"claim {claim['claim_id']} references unknown question_id {claim['question_id']}")
        if claim["section"] not in section_set:
            errors.append(f"claim {claim['claim_id']} references unknown section {claim['section']}")
        else:
            section = next(row for row in plan["sections"] if row["section_id"] == claim["section"])
            if claim["claim_id"] not in section["claim_ids"]:
                errors.append(f"claim {claim['claim_id']} is not listed by section {claim['section']}")
        check_evidence_refs(f"claim {claim.get('claim_id')}", claim)
        for result_id in claim.get("result_ids", []):
            if result_id not in result_set:
                errors.append(f"claim {claim['claim_id']} references unknown result_id {result_id}")
        for derived_result_id in claim.get("derived_result_ids", []):
            if not isinstance(derived_result_id, str) or not derived_result_id.strip():
                errors.append(f"claim {claim['claim_id']} has an invalid derived_result_id")
        for claim_id in claim.get("precondition_claim_ids", []):
            if claim_id not in claim_set:
                errors.append(f"claim {claim['claim_id']} references unknown precondition_claim_id {claim_id}")
        claim_type = claim.get("claim_type")
        if claim_type == "observation" and not claim.get("result_ids"):
            errors.append(f"observation claim {claim['claim_id']} requires result_ids")
        if claim_type in {"inference", "recommendation"}:
            if claim.get("support_level") == "direct":
                errors.append(f"{claim_type} claim {claim['claim_id']} cannot claim direct support")
            if not claim.get("precondition_claim_ids"):
                errors.append(f"{claim_type} claim {claim['claim_id']} requires precondition_claim_ids")
        inference_strength = claim.get("inference_strength")
        if inference_strength == "causal" and claim_type == "observation":
            errors.append(f"observation claim {claim['claim_id']} cannot declare causal inference_strength")
        if inference_strength == "mechanistic" and claim_type == "observation":
            errors.append(f"observation claim {claim['claim_id']} cannot declare mechanistic inference_strength")
        if inference_strength == "descriptive" and claim_type in {"inference", "recommendation"}:
            errors.append(f"{claim_type} claim {claim['claim_id']} cannot declare descriptive inference_strength")
        if inference_strength == "causal" and not isinstance(claim.get("causal_design"), str):
            errors.append(f"causal claim {claim['claim_id']} requires causal_design")
        if any(token in claim.get("text", "") for token in ("最优", "显著", "稳健", "提升")) and "comparison" not in claim:
            errors.append(f"claim {claim['claim_id']} uses a comparative-strength term but has no comparison contract")
    thesis = plan.get("central_thesis", {})
    for claim_id in thesis.get("claim_ids", []):
        if claim_id not in claim_set:
            errors.append(f"central_thesis references unknown claim_id {claim_id}")
    # Legacy depth_budget remains readable metadata; it no longer controls a plan Gate.
    for unit in argument_units:
        if unit["section_id"] not in section_set:
            errors.append(f"argument unit {unit['unit_id']} references unknown section_id {unit['section_id']}")
        check_claim_refs(f"argument unit {unit.get('unit_id')}", unit)
        check_evidence_refs(f"argument unit {unit.get('unit_id')}", unit)
        scope = unit.get("scope")
        if isinstance(scope, Mapping):
            scope_type = scope.get("type")
            raw_question_ids = scope.get("question_ids", [])
            if scope_type not in {"question", "cross_question", "global"}:
                errors.append(f"argument unit {unit['unit_id']} has an unknown scope type {scope_type!r}")
            elif scope_type == "global" and "question_ids" in scope:
                errors.append(f"global argument unit {unit['unit_id']} must not declare question_ids")
            elif not isinstance(raw_question_ids, list):
                errors.append(f"argument unit {unit['unit_id']} scope.question_ids must be an array")
            else:
                scope_question_ids = [str(item) for item in raw_question_ids]
                if scope_type == "question" and len(scope_question_ids) != 1:
                    errors.append(f"question argument unit {unit['unit_id']} requires exactly one question_id")
                elif scope_type == "cross_question" and len(scope_question_ids) < 2:
                    errors.append(f"cross_question argument unit {unit['unit_id']} requires at least two question_ids")
                unknown_scope_questions = sorted(set(scope_question_ids) - question_set)
                if unknown_scope_questions:
                    errors.append(
                        f"argument unit {unit['unit_id']} scope references unknown question_id values: {unknown_scope_questions}"
                    )
        for prerequisite_id in unit.get("prerequisite_unit_ids", []):
            if prerequisite_id not in argument_unit_set:
                errors.append(f"argument unit {unit['unit_id']} references unknown prerequisite_unit_id {prerequisite_id}")
            if prerequisite_id == unit["unit_id"]:
                errors.append(f"argument unit {unit['unit_id']} cannot depend on itself")
        if unit.get("rhetorical_role") == "interpretation":
            if any(claim_by_id.get(claim_id, {}).get("claim_type") == "observation" for claim_id in unit.get("claim_ids", [])):
                errors.append(f"interpretation unit {unit['unit_id']} cannot realize an observation claim directly")
    for section in plan["sections"]:
        check_claim_refs(f"section {section['section_id']}", section)
    for figure in plan.get("figures", []):
        check_claim_refs(f"figure {figure.get('figure_id')}", figure)
        check_evidence_refs(f"figure {figure.get('figure_id')}", figure)
        if plan.get("status") == "ready" and not figure.get("semantic_type"):
            errors.append(f"figure {figure.get('figure_id')} requires semantic_type before the plan is ready")
        if (
            plan.get("status") == "ready"
            and figure.get("kind") == "concept"
            and figure.get("semantic_type") in {"methodology_overview", "data_flow", "model_structure"}
            and not isinstance(figure.get("diagram"), dict)
        ):
            errors.append(
                f"concept figure {figure.get('figure_id')} requires a diagram artifact contract "
                "for methodology_overview/data_flow/model_structure"
            )
    figure_by_id = {row.get("figure_id"): row for row in plan.get("figures", []) if isinstance(row, dict)}
    figure_references = plan.get("figure_references", [])
    if plan.get("status") == "ready" and figure_by_id and not figure_references:
        errors.append("ready paper_plan with figures requires figure_references semantic bindings")
    figure_reference_ids: set[str] = set()
    referenced_figure_ids: set[str] = set()
    for reference in figure_references:
        reference_id = reference.get("reference_id") if isinstance(reference, dict) else None
        if isinstance(reference_id, str):
            if reference_id in figure_reference_ids:
                errors.append(f"duplicate figure reference_id: {reference_id}")
            figure_reference_ids.add(reference_id)
        figure_reference_figure_id = reference.get("figure_id") if isinstance(reference, dict) else None
        if not isinstance(figure_reference_figure_id, str) or figure_reference_figure_id not in figure_by_id:
            errors.append(f"figure reference {reference_id} references an unknown figure")
        else:
            referenced_figure_ids.add(figure_reference_figure_id)
            if reference.get("section_id") not in section_set:
                errors.append(f"figure reference {reference_id} references an unknown section")
    if plan.get("status") == "ready":
        unreferenced_figures = sorted(set(figure_by_id) - referenced_figure_ids)
        if unreferenced_figures:
            errors.append(f"ready paper_plan has formal figure(s) without semantic references: {unreferenced_figures}")
    for table in plan.get("tables", []):
        check_claim_refs(f"table {table.get('table_id')}", table)
        check_evidence_refs(f"table {table.get('table_id')}", table)
    draft_coverage = plan.get("draft_coverage")
    if isinstance(draft_coverage, dict):
        anchors = [row for row in draft_coverage.get("anchors", []) if isinstance(row, dict)]
        unique("paper_plan draft anchor_id", [row.get("anchor_id") for row in anchors])
        anchor_unit_ids = [row.get("unit_id") for row in anchors]
        unique("paper_plan draft anchor unit_id", anchor_unit_ids)
        used_by_readiness: set[str] = set()
        readiness = plan.get("readiness", {})
        if isinstance(readiness, dict):
            for coverage in readiness.get("question_coverage", []):
                if not isinstance(coverage, dict):
                    continue
                for field in ("formulation_unit_ids", "result_unit_ids", "validation_unit_ids", "interpretation_unit_ids"):
                    used_by_readiness.update(
                        unit_id for unit_id in coverage.get(field, []) if isinstance(unit_id, str)
                    )
        if draft_coverage.get("status") in {"planned", "verified"} and plan.get("status") == "ready":
            missing_anchors = sorted(used_by_readiness - set(anchor_unit_ids))
            if missing_anchors:
                errors.append(f"draft_coverage is missing anchors for planned argument units: {missing_anchors}")
        for anchor in anchors:
            unit_id = anchor.get("unit_id")
            unit = next((row for row in argument_units if row.get("unit_id") == unit_id), None)
            if unit is None:
                errors.append(f"draft anchor {anchor.get('anchor_id')} references unknown unit_id {unit_id}")
                continue
            elif unit.get("section_id") not in section_set:
                errors.append(f"draft anchor {anchor.get('anchor_id')} unit has unknown section_id")
            unit_questions = {
                claim_by_id.get(claim_id, {}).get("question_id")
                for claim_id in unit.get("claim_ids", [])
                if claim_id in claim_by_id
            }
            anchor_scope = unit.get("scope")
            # A global/cross-question unit can intentionally omit a single anchor question.
            if isinstance(anchor_scope, Mapping):
                if anchor_scope.get("type") == "global":
                    unit_questions = set(question_set)
                elif anchor_scope.get("type") in {"question", "cross_question"}:
                    scoped_question_ids = anchor_scope.get("question_ids")
                    if isinstance(scoped_question_ids, list):
                        unit_questions.update(item for item in scoped_question_ids if isinstance(item, str))
            anchor_question_id = anchor.get("question_id")
            if anchor_question_id is not None and anchor_question_id not in unit_questions:
                errors.append(
                    f"draft anchor {anchor.get('anchor_id')} question_id does not match its argument unit"
                )
            if not all(isinstance(pattern, str) and pattern.strip() for pattern in anchor.get("patterns", [])):
                errors.append(f"draft anchor {anchor.get('anchor_id')} must contain non-empty patterns")
    recommendation = plan.get("canonical_recommendation") or {}
    check_evidence_refs("canonical_recommendation", recommendation)
    abstract_rows = [row for row in plan.get("abstract_results", []) if isinstance(row, dict)]
    abstract_result_ids = [row.get("result_id") for row in abstract_rows]
    unique("paper_plan abstract result_id", abstract_result_ids)
    for row in abstract_rows:
        result_id = row.get("result_id")
        if result_id not in result_set:
            errors.append(f"abstract_results references unknown result_id {result_id}")
        check_claim_refs(f"abstract result {result_id}", row)
    maximum_abstract_results = plan.get("precision_policy", {}).get("abstract_max_numeric_claims")
    if isinstance(maximum_abstract_results, int) and len(abstract_rows) > maximum_abstract_results:
        errors.append("abstract_results exceeds precision_policy.abstract_max_numeric_claims")
    nonresearch_tokens = [
        row.get("token") for row in plan.get("nonresearch_numeric_literals", []) if isinstance(row, dict)
    ]
    unique("paper_plan nonresearch numeric token", nonresearch_tokens)
    if plan["status"] == "ready":
        covered_questions = {claim["question_id"] for claim in plan["claims"]}
        uncovered = sorted(question_set - covered_questions)
        if uncovered:
            errors.append(f"ready paper_plan has no claim for question(s): {uncovered}")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-contract", required=True)
    parser.add_argument("--run-manifest", required=True)
    parser.add_argument("--frozen-results", required=True)
    parser.add_argument("--evidence-registry", required=True)
    parser.add_argument("--paper-plan", required=True)
    parser.add_argument("--schema-dir")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    schema_dir = Path(args.schema_dir).resolve() if args.schema_dir else Path(__file__).resolve().parents[2] / "schemas"
    inputs = {
        "model_contract": (resolve_path(args.model_contract, root).resolve(), schema_dir / "model_contract.schema.json"),
        "run_manifest": (resolve_path(args.run_manifest, root).resolve(), schema_dir / "run_manifest.schema.json"),
        "frozen_results": (resolve_path(args.frozen_results, root).resolve(), schema_dir / "frozen_results.schema.json"),
        "evidence_registry": (resolve_path(args.evidence_registry, root).resolve(), schema_dir / "evidence_registry.schema.json"),
        "paper_plan": (resolve_path(args.paper_plan, root).resolve(), schema_dir / "paper_plan.schema.json"),
    }
    documents: dict[str, Any] = {}
    errors: list[str] = []
    engines: set[str] = set()
    for label, (path, schema_path) in inputs.items():
        value, file_errors, engine = _validate_document(path, schema_path)
        engines.add(engine)
        if value is not None:
            documents[label] = value
        errors.extend(f"{label}: {error}" for error in file_errors)

    warnings: list[str] = []
    if len(documents) == len(inputs) and not errors:
        cross_errors, cross_warnings = _cross_references(
            documents["model_contract"],
            documents["run_manifest"],
            documents["frozen_results"],
            documents["evidence_registry"],
            documents["paper_plan"],
            root=root,
            paths={label: path for label, (path, _) in inputs.items()},
        )
        errors.extend(cross_errors)
        warnings.extend(cross_warnings)

    ok = not errors and (not args.strict or not warnings)
    report = {
        "ok": ok,
        "engine": "+".join(sorted(engines)) or "fallback",
        "files": {label: rel_path(path, root) for label, (path, _) in inputs.items()},
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
