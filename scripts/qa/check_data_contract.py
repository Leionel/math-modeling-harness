#!/usr/bin/env python3
"""Validate dataset semantics, file identity, invariants, and leakage status."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from _common import load_structured, rel_path, resolve_path, sha256_file  # noqa: E402
from qa.validate_contracts import _validate_document  # noqa: E402


def _input_mentions(input_name: object, feature_name: str) -> bool:
    """Match a declared feature without assuming one naming convention."""

    text = str(input_name or "")
    return text == feature_name or text.endswith(f".{feature_name}") or text.endswith(f":{feature_name}")


def _check_observation_structure(
    contract: dict[str, Any],
    model: dict[str, Any],
    *,
    require: bool,
    require_decision_context: bool,
    require_statistical_design: bool,
    errors: list[str],
    warnings: list[str],
) -> None:
    observation = contract.get("observation_structure")
    if not isinstance(observation, dict):
        if require:
            errors.append("data_contract.observation_structure is required for formal QA")
        else:
            warnings.append("observation structure is not declared; entity/time split review is incomplete")
        return

    columns = {row.get("name"): row for row in contract.get("columns", []) if isinstance(row, dict)}
    entity_key = observation.get("entity_key", [])
    if not isinstance(entity_key, list):
        entity_key = []
    for name in entity_key:
        column = columns.get(name)
        if column is None:
            errors.append(f"observation_structure.entity_key references missing column: {name}")
        elif column.get("role") not in {"identifier", "group"}:
            errors.append(f"observation_structure.entity_key column must have role identifier/group: {name}")
    time_key = observation.get("time_key")
    if time_key is not None:
        time_column = columns.get(time_key)
        if time_column is None:
            errors.append(f"observation_structure.time_key references missing column: {time_key}")
        elif time_column.get("role") != "time":
            errors.append(f"observation_structure.time_key column must have role=time: {time_key}")
    if observation.get("repeated_measure") is True:
        if not entity_key:
            errors.append("repeated_measure=true requires a non-empty entity_key")
        if observation.get("split_unit") == "row":
            errors.append("repeated measures cannot declare split_unit=row")
        if observation.get("within_entity_time_order") not in {"verified", "not_applicable"}:
            errors.append("repeated measures require within_entity_time_order=verified or not_applicable")
    declared = observation.get("declared_entity_count")
    observed = observation.get("observed_entity_count")
    if isinstance(declared, int) and isinstance(observed, int) and declared != observed:
        errors.append("observation_structure declared_entity_count differs from observed_entity_count")
    if observation.get("status") != "validated":
        errors.append("observation_structure.status must be validated")

    lineage_rows = contract.get("derived_feature_lineage", [])
    lineage_by_feature: dict[str, dict[str, Any]] = {}
    for row in lineage_rows if isinstance(lineage_rows, list) else []:
        if not isinstance(row, dict):
            continue
        feature_id = row.get("feature_id")
        if not isinstance(feature_id, str):
            continue
        if feature_id in lineage_by_feature:
            errors.append(f"duplicate derived_feature_lineage.feature_id: {feature_id}")
        lineage_by_feature[feature_id] = row
        if feature_id not in columns:
            errors.append(f"derived_feature_lineage references missing feature column: {feature_id}")
        for source_column in row.get("source_columns", []):
            if source_column not in columns:
                errors.append(f"derived feature {feature_id} references missing source column: {source_column}")
        if row.get("status") != "verified":
            errors.append(f"derived feature {feature_id} lineage status is not verified")

    models = [row for row in model.get("models", []) if isinstance(row, dict)]
    for model_row in models:
        model_id = str(model_row.get("model_id", ""))
        inputs = model_row.get("inputs", [])
        used_lineage = {
            feature_id: row
            for feature_id, row in lineage_by_feature.items()
            if any(_input_mentions(item, feature_id) for item in inputs if isinstance(item, str))
        }
        used_raw = {
            column_name: column for column_name, column in columns.items()
            if isinstance(column_name, str)
            and column_name not in lineage_by_feature
            and any(_input_mentions(item, column_name) for item in inputs if isinstance(item, str))
        }
        used_availability = {
            **{name: row.get("availability") for name, row in used_raw.items()},
            **{name: row.get("availability") for name, row in used_lineage.items()},
        }
        decision = model_row.get("decision_context")
        if isinstance(decision, dict):
            decision_column = decision.get("decision_time_column")
            if decision_column not in columns or columns.get(decision_column, {}).get("role") != "time":
                errors.append(f"model {model_id} decision_context.decision_time_column must reference role=time")
            if time_key and decision_column != time_key:
                errors.append(f"model {model_id} decision time column differs from observation_structure.time_key")
            policy = decision.get("feature_policy")
            for feature_id, availability in used_availability.items():
                if policy in {"known_at_decision", "strict_pre_cutoff"} and availability != "known_at_decision":
                    errors.append(
                        f"model {model_id} uses feature {feature_id} with availability={availability!r} "
                        f"under feature_policy={policy}"
                    )
            forbidden = set(decision.get("forbidden_future_features", []))
            used_forbidden = sorted(name for name in columns if name in forbidden and any(_input_mentions(item, name) for item in inputs if isinstance(item, str)))
            if used_forbidden:
                errors.append(f"model {model_id} uses forbidden_future_features: {used_forbidden}")
        elif used_availability and require_decision_context:
            errors.append(f"model {model_id} uses availability-declared inputs but has no decision_context")

        future_features = [
            feature_id for feature_id, availability in used_availability.items()
            if availability in {"future_dependent", "unknown"}
        ]
        if future_features and not (isinstance(decision, dict) and decision.get("feature_policy") == "not_applicable"):
            errors.append(f"model {model_id} uses unavailable-at-decision feature(s): {future_features}")

        if observation.get("repeated_measure") is True:
            design = model_row.get("statistical_design")
            characteristics = set(model_row.get("characteristics", []))
            methods = set(design.get("methods", [])) if isinstance(design, dict) else set()
            if require_statistical_design and not isinstance(design, dict):
                errors.append(f"model {model_id} requires statistical_design for repeated measures")
            if "machine_learning" in characteristics and not methods.intersection(
                {"GroupKFold", "StratifiedGroupKFold", "GroupShuffleSplit", "subject_level_aggregation", "grouped_bootstrap"}
            ):
                errors.append(f"model {model_id} repeated-measure ML requires a group-aware validation method")
            if "statistical_inference" == model_row.get("problem_type") and model_row.get("statistical_design"):
                if not methods.intersection(
                    {"mixed_effects", "GEE", "cluster_robust_SE", "subject_level_aggregation", "grouped_bootstrap"}
                ):
                    errors.append(f"model {model_id} repeated-measure inference lacks clustered/mixed/aggregated design")

    if observation.get("repeated_measure") is True:
        split_keys = set(contract.get("leakage_policy", {}).get("split_keys", []))
        if not split_keys.intersection(entity_key):
            errors.append("repeated measures require leakage_policy.split_keys to include an entity key")
    if require_decision_context and lineage_by_feature and not any(isinstance(row.get("decision_context"), dict) for row in models):
        errors.append("derived feature lineage is present but no model declares decision_context")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-contract", required=True)
    parser.add_argument("--model-contract", required=True)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--require-observation-structure", action="store_true")
    parser.add_argument("--require-decision-context", action="store_true")
    parser.add_argument("--require-statistical-design", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    contract_path = resolve_path(args.data_contract, root).resolve()
    model_path = resolve_path(args.model_contract, root).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    contract, schema_errors, _ = _validate_document(
        contract_path, Path(__file__).resolve().parents[2] / "schemas" / "data_contract.schema.json"
    )
    errors.extend(f"data_contract schema: {message}" for message in schema_errors)
    try:
        model = load_structured(model_path)
    except (OSError, ValueError, TypeError) as exc:
        errors.append(str(exc))
        model = {}
    if not isinstance(contract, dict):
        contract = {}
    if not isinstance(model, dict):
        errors.append("model_contract must be an object")
        model = {}

    source = contract.get("source", {})
    source_path = resolve_path(str(source.get("path", "")), root).resolve() if isinstance(source, dict) else None
    if source_path is None or not source_path.is_file():
        errors.append(f"data source does not exist: {source.get('path') if isinstance(source, dict) else None}")
    elif source.get("sha256") != sha256_file(source_path):
        errors.append(f"data source hash drift: {source.get('path')}")

    model_sources = {
        row.get("data_id"): row
        for row in model.get("data_sources", [])
        if isinstance(row, dict) and isinstance(row.get("data_id"), str)
    }
    model_source = model_sources.get(contract.get("data_id"))
    if model_source is None:
        errors.append(f"data_id {contract.get('data_id')!r} is absent from model_contract")
    elif isinstance(source, dict):
        if model_source.get("path") != source.get("path") or model_source.get("sha256") != source.get("sha256"):
            errors.append("data_contract source path/hash differs from model_contract data source")

    table = contract.get("table", {}) if isinstance(contract.get("table"), dict) else {}
    profile = contract.get("profile", {}) if isinstance(contract.get("profile"), dict) else {}
    columns = [row for row in contract.get("columns", []) if isinstance(row, dict)]
    names = [row.get("name") for row in columns]
    if len(names) != len(set(names)):
        errors.append("data_contract column names must be unique")
    if table.get("column_count") != len(columns):
        errors.append("table.column_count does not equal the number of column contracts")
    if table.get("row_count") != profile.get("row_count"):
        errors.append("table.row_count differs from profile.row_count")
    row_count = table.get("row_count")
    if isinstance(row_count, int):
        for column in columns:
            missing = column.get("missing_count")
            if isinstance(missing, int) and missing > row_count:
                errors.append(f"column {column.get('name')} missing_count exceeds row_count")

    failed_invariants = [
        row.get("invariant_id") for row in contract.get("invariants", [])
        if isinstance(row, dict) and row.get("status") != "pass"
    ]
    if failed_invariants:
        errors.append(f"data invariants are not PASS: {failed_invariants}")
    leakage = contract.get("leakage_policy", {}) if isinstance(contract.get("leakage_policy"), dict) else {}
    if leakage.get("status") not in {"pass", "not_applicable"}:
        errors.append(f"leakage_policy.status is not promotable: {leakage.get('status')}")
    column_by_name = {row.get("name"): row for row in columns if isinstance(row, dict)}
    target_columns = leakage.get("target_columns", []) if isinstance(leakage.get("target_columns"), list) else []
    for target in target_columns:
        if target not in column_by_name:
            errors.append(f"leakage_policy.target_columns references missing column: {target}")
        elif column_by_name[target].get("role") != "target":
            errors.append(f"leakage_policy.target_columns column is not role=target: {target}")
    forbidden_features = leakage.get("forbidden_features", []) if isinstance(leakage.get("forbidden_features"), list) else []
    for feature in forbidden_features:
        if feature not in column_by_name:
            errors.append(f"leakage_policy.forbidden_features references missing column: {feature}")
        elif feature in target_columns:
            errors.append(f"leakage_policy.forbidden_features must name a feature, not target: {feature}")
    if leakage.get("status") == "pass" and not (leakage.get("split_keys") or leakage.get("time_boundary")):
        errors.append("leakage_policy.status=pass requires split_keys or time_boundary")
    if contract.get("status") != "validated":
        errors.append("data_contract.status must be validated")
    if not table.get("primary_key"):
        warnings.append("no primary key declared; duplicate entity/time joins require manual review")

    _check_observation_structure(
        contract,
        model,
        require=args.require_observation_structure,
        require_decision_context=args.require_decision_context,
        require_statistical_design=args.require_statistical_design,
        errors=errors,
        warnings=warnings,
    )

    ok = not errors and (not args.strict or not warnings)
    print(json.dumps({
        "ok": ok,
        "data_contract": rel_path(contract_path, root),
        "model_contract": rel_path(model_path, root),
        "data_id": contract.get("data_id"),
        "errors": errors,
        "warnings": warnings,
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
