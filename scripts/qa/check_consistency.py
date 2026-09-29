#!/usr/bin/env python3
"""Run deterministic checks over frozen numbers, evidence, and paper references."""

from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from _common import load_structured, rel_path, resolve_path, sha256_file  # noqa: E402
from qa.presentation_semantics import (  # noqa: E402
    evaluate_figure_semantics,
    evaluate_required_answer_coverage,
    evaluate_terminology_consistency,
)
from qa.validate_contracts import _validate_document  # noqa: E402
from qa.tex_source import read_visible_text  # noqa: E402


FIGURE_ROLE_SEMANTIC_TYPES = {
    "methodology_overview": {"methodology_overview", "model_flow", "model_structure", "pipeline"},
    "data_flow": {"data_flow", "data_overview", "data_distribution"},
    "model_structure": {"model_structure", "model_flow", "optimization_structure"},
    "result_comparison": {"result_comparison", "comparison", "bar_comparison", "line_comparison"},
    "sensitivity": {"sensitivity", "sensitivity_curve", "tornado"},
    "validation": {"validation", "residual", "diagnostic", "validation_curve"},
    "recommendation": {"recommendation", "decision_boundary", "comparison"},
}

COUNT_SCOPE_TOKENS = {
    "raw_records": ("raw record", "raw records", "raw sample", "原始记录", "原始样本"),
    "valid_records": ("valid record", "valid records", "valid sample", "有效记录", "有效样本"),
    "included_records": ("included record", "included records", "included sample", "纳入记录", "纳入样本"),
    "excluded_records": ("excluded record", "excluded records", "excluded sample", "排除记录", "排除样本"),
}

PRIMARY_INFERENCE_TOKENS = (
    "primary inference", "main inference", "primary analysis", "main analysis", "main model",
    "主要推断", "主要分析", "主要模型", "首要推断",
)
SECONDARY_INFERENCE_TOKENS = (
    "sensitivity", "sensitivity analysis", "robustness", "secondary analysis", "secondary model",
    "敏感性", "敏感性分析", "稳健性", "次要分析", "次要模型",
)
ORDINARY_INFERENCE_TOKENS = (
    "ordinary least squares", "ordinary ols", "ordinary regression", "ols", "普通最小二乘", "普通ols", "普通回归",
)
INFERENCE_METHOD_TOKENS = {
    "mixed_effects": ("mixed effects", "mixed-effects", "mixed model", "mixedlm", "mixed linear", "混合效应", "混合模型"),
    "GEE": ("generalized estimating equation", "gee", "广义估计方程"),
    "cluster_robust_SE": ("cluster-robust", "cluster robust", "clustered standard error", "聚类稳健"),
    "subject_level_aggregation": ("subject-level aggregation", "entity-level aggregation", "subject-level", "个体层面", "实体层面"),
    "grouped_bootstrap": ("grouped bootstrap", "cluster bootstrap", "分组bootstrap", "分层自助法"),
}

CAPTION_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9_.])[-+]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d*)?|\.\d+)"
    r"(?:[eE][-+]?\d+)?%?(?![A-Za-z0-9_.])"
)


def _numeric_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for match in CAPTION_NUMBER_RE.finditer(text.replace(r"\%", "%")):
        raw = match.group(0).replace(",", "")
        suffix = "%" if raw.endswith("%") else ""
        core = raw[:-1] if suffix else raw
        try:
            decimal = Decimal(core)
        except InvalidOperation:
            continue
        normalized = format(decimal.normalize(), "f")
        if normalized == "-0":
            normalized = "0"
        tokens.add(normalized + suffix)
    return tokens


def canonical_display(value: Any, precision: int) -> str | None:
    try:
        decimal = Decimal(str(value))
        quantum = Decimal(1).scaleb(-precision)
        rounded = decimal.quantize(quantum, rounding=ROUND_HALF_UP)
        return f"{rounded:.{precision}f}"
    except (InvalidOperation, ValueError, TypeError):
        return None


def read_text(path: Path, label: str, errors: list[str], project_root: Path | None = None) -> str | None:
    try:
        return read_visible_text(path, project_root or path.parent)
    except (OSError, ValueError) as exc:
        errors.append(f"{label} cannot be read: {exc}")
        return None


def _sentence_rows(text: str) -> list[str]:
    return [row.casefold() for row in re.split(r"(?<=[.!?。！？])\s*", text) if row.strip()]


def evaluate_metric_semantics(
    results: list[dict[str, Any]],
    text_sources: dict[str, str],
) -> tuple[list[str], dict[str, Any]]:
    """Reject a count whose population is changed in prose.

    This extends the existing frozen-result/display-value binding.  It is not
    a general NLP claim parser: only an explicitly declared record-count
    population is checked, and only when the displayed count occurs in a
    sentence containing a conflicting population label.
    """

    errors: list[str] = []
    details: dict[str, Any] = {"checked": [], "mismatches": []}
    for result in results:
        semantics = result.get("metric_semantics") if isinstance(result, dict) else None
        if not isinstance(semantics, dict) or semantics.get("metric_type") != "record_count":
            continue
        result_id = str(result.get("result_id", ""))
        display = str(result.get("display_value", "")).strip()
        population = semantics.get("population")
        expected_tokens = COUNT_SCOPE_TOKENS.get(str(population), ())
        if not result_id or not display or not expected_tokens:
            continue
        details["checked"].append({"result_id": result_id, "population": population})
        conflicting_populations = {
            other_population: tokens
            for other_population, tokens in COUNT_SCOPE_TOKENS.items()
            if other_population != population
        }
        for label, text in text_sources.items():
            for sentence in _sentence_rows(text):
                if display.casefold() not in sentence:
                    continue
                for other_population, tokens in conflicting_populations.items():
                    if any(token.casefold() in sentence for token in tokens):
                        message = (
                            f"METRIC_SEMANTIC_MISMATCH: {label} assigns result {result_id} "
                            f"population={other_population} although frozen metric_semantics.population={population}"
                        )
                        errors.append(message)
                        details["mismatches"].append({"result_id": result_id, "label": label, "sentence": sentence})
                        break
    return errors, details


def evaluate_inference_role_consistency(
    model_contract: dict[str, Any],
    text_sources: dict[str, str],
    *,
    require: bool = False,
) -> tuple[list[str], list[str], dict[str, Any]]:
    """Keep the declared primary repeated-measure inference method primary in prose."""

    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {"checked_models": [], "role_conflicts": []}
    text = "\n".join(text_sources.get(label, "") for label in ("paper", "conclusion", "abstract"))
    sentences = _sentence_rows(text)
    if not sentences:
        return errors, warnings, details
    for model in model_contract.get("models", []):
        if not isinstance(model, dict):
            continue
        design = model.get("statistical_design")
        if not isinstance(design, dict) or design.get("role") != "primary_inference":
            continue
        methods = [str(method) for method in design.get("methods", [])]
        declared_tokens = tuple(
            token
            for method in methods
            for token in INFERENCE_METHOD_TOKENS.get(method, ())
        )
        if not declared_tokens:
            continue
        details["checked_models"].append({"model_id": model.get("model_id"), "methods": methods})
        ordinary_primary = any(
            any(token.casefold() in sentence for token in ORDINARY_INFERENCE_TOKENS)
            and any(token.casefold() in sentence for token in PRIMARY_INFERENCE_TOKENS)
            for sentence in sentences
        )
        declared_secondary = any(
            any(token.casefold() in sentence for token in declared_tokens)
            and any(token.casefold() in sentence for token in SECONDARY_INFERENCE_TOKENS)
            for sentence in sentences
        )
        if not ordinary_primary and not declared_secondary:
            continue
        conflict = (
            f"PRIMARY_INFERENCE_ROLE_DRIFT: model {model.get('model_id')} declares "
            f"{methods} as primary inference, but the paper assigns ordinary OLS/OLS "
            "the primary role or assigns the declared method only to sensitivity/secondary analysis"
        )
        details["role_conflicts"].append({"model_id": model.get("model_id"), "ordinary_primary": ordinary_primary, "declared_method_secondary": declared_secondary})
        (errors if require else warnings).append(conflict)
    return errors, warnings, details


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-plan", required=True)
    parser.add_argument("--model-contract")
    parser.add_argument("--frozen-results", required=True)
    parser.add_argument("--evidence-registry", required=True)
    parser.add_argument("--derived-results")
    parser.add_argument("--abstract")
    parser.add_argument("--paper")
    parser.add_argument("--conclusion")
    parser.add_argument("--figures-dir")
    parser.add_argument("--require-figure-lineage", action="store_true")
    parser.add_argument("--artifact-dag")
    parser.add_argument("--require-canonical-source", action="store_true")
    parser.add_argument("--require-answer-contract", action="store_true")
    parser.add_argument("--require-abstract-backcheck", action="store_true")
    parser.add_argument("--require-figure-semantics", action="store_true")
    parser.add_argument(
        "--require-inference-role-consistency",
        action="store_true",
        help="Reject prose that reverses a model contract's declared primary repeated-measure inference method.",
    )
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    plan_path = resolve_path(args.paper_plan, root).resolve()
    frozen_path = resolve_path(args.frozen_results, root).resolve()
    registry_path = resolve_path(args.evidence_registry, root).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    model_contract: dict[str, Any] = {}
    required_answer_details: dict[str, Any] = {}
    terminology_details: dict[str, Any] = {}
    figure_semantic_details: dict[str, Any] = {}
    figure_semantic_issues: list[dict[str, Any]] = []
    metric_semantic_details: dict[str, Any] = {}
    inference_role_details: dict[str, Any] = {}
    if args.model_contract:
        model_path = resolve_path(args.model_contract, root).resolve()
        try:
            loaded_model = load_structured(model_path)
            if not isinstance(loaded_model, dict):
                errors.append("model-contract must be an object")
            else:
                model_contract = loaded_model
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"model-contract cannot be loaded: {exc}")
    elif args.require_answer_contract or args.require_abstract_backcheck:
        errors.append("required answer coverage needs --model-contract")
    dag_nodes: dict[str, dict[str, Any]] = {}
    if args.artifact_dag:
        dag_path = resolve_path(args.artifact_dag, root).resolve()
        try:
            dag_doc = load_structured(dag_path)
        except (OSError, ValueError, TypeError) as exc:
            dag_doc = None
            errors.append(f"artifact DAG cannot be loaded: {exc}")
        if isinstance(dag_doc, dict):
            for node in dag_doc.get("nodes", []):
                if not isinstance(node, dict):
                    continue
                node_key = node.get("node_id")
                if not isinstance(node_key, str):
                    node_key = node.get("artifact_id")
                if isinstance(node_key, str):
                    dag_nodes[node_key] = node
    elif args.require_canonical_source:
        errors.append("--require-canonical-source requires --artifact-dag")
    try:
        plan = load_structured(plan_path)
        frozen = load_structured(frozen_path)
        registry = load_structured(registry_path)
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)], "warnings": []}, ensure_ascii=False, indent=2))
        return 1

    if not isinstance(plan, dict) or not isinstance(frozen, dict) or not isinstance(registry, dict):
        errors.append("paper-plan, frozen-results, and evidence-registry must all be objects")
        plan = plan if isinstance(plan, dict) else {}
        frozen = frozen if isinstance(frozen, dict) else {}
        registry = registry if isinstance(registry, dict) else {}

    if frozen.get("status") != "frozen":
        errors.append("frozen_results.status must be frozen")
    if frozen.get("claimable") is not True or frozen.get("validation_verdict") != "PASS":
        errors.append("frozen_results must be claimable with validation_verdict=PASS before consistency/W1")
    results = frozen.get("results", [])
    if not isinstance(results, list) or not results:
        errors.append("frozen_results.results must be a non-empty array")
        results = []
    result_by_id: dict[str, dict[str, Any]] = {}
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            errors.append(f"frozen_results.results[{index}] must be an object")
            continue
        result_id = result.get("result_id")
        if not isinstance(result_id, str) or not result_id:
            errors.append(f"frozen_results.results[{index}] has no result_id")
            continue
        if result_id in result_by_id:
            errors.append(f"duplicate result_id: {result_id}")
        result_by_id[result_id] = result
        if result.get("validation_status") != "passed" or result.get("claimable") is not True:
            errors.append(f"result {result_id} is not validated")
        precision = result.get("precision")
        if isinstance(precision, int) and precision >= 0:
            expected = canonical_display(result.get("value"), precision)
            if expected is not None and result.get("display_value") != expected:
                errors.append(f"result {result_id} display_value drift: expected {expected!r}, got {result.get('display_value')!r}")
        else:
            errors.append(f"result {result_id} precision must be a non-negative integer")
        if not isinstance(result.get("unit"), str) or not result["unit"].strip():
            errors.append(f"result {result_id} unit must be non-empty")

    registry_evidence = registry.get("evidence", [])
    if not isinstance(registry_evidence, list):
        errors.append("evidence_registry.evidence must be an array")
        registry_evidence = []
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for index, evidence in enumerate(registry_evidence):
        if not isinstance(evidence, dict) or not isinstance(evidence.get("evidence_id"), str):
            errors.append(f"evidence_registry.evidence[{index}] must contain evidence_id")
            continue
        evidence_id = evidence["evidence_id"]
        if evidence_id in evidence_by_id:
            errors.append(f"duplicate evidence_id: {evidence_id}")
        evidence_by_id[evidence_id] = evidence
        for result_id in evidence.get("result_ids", []):
            if result_id not in result_by_id:
                errors.append(f"evidence {evidence_id} references unknown result_id {result_id}")
        for artifact_index, artifact in enumerate(evidence.get("artifacts", [])):
            if not isinstance(artifact, dict):
                errors.append(f"evidence {evidence_id} artifact[{artifact_index}] must be an object")
                continue
            artifact_path = artifact.get("path")
            if not isinstance(artifact_path, str):
                errors.append(f"evidence {evidence_id} artifact[{artifact_index}].path must be a string")
                continue
            if artifact_path.startswith(("http://", "https://", "s3://", "artifact://")):
                warnings.append(f"evidence {evidence_id} uses external artifact path {artifact_path}")
                continue
            artifact_file = resolve_path(artifact_path, root).resolve()
            if not artifact_file.is_file():
                errors.append(f"evidence {evidence_id} artifact does not exist: {artifact_path}")
            elif artifact.get("sha256") != sha256_file(artifact_file):
                errors.append(f"evidence {evidence_id} artifact hash drift: {artifact_path}")

    matching_frozen_snapshot = False
    for snapshot in registry.get("source_snapshots", []):
        if not isinstance(snapshot, dict) or snapshot.get("kind") != "frozen_results":
            continue
        snapshot_path = resolve_path(str(snapshot.get("path", "")), root).resolve()
        if snapshot_path == frozen_path and snapshot.get("sha256") == sha256_file(frozen_path):
            matching_frozen_snapshot = True
    if not matching_frozen_snapshot:
        errors.append("evidence_registry has no current snapshot of the supplied frozen_results file")

    claims = plan.get("claims", [])
    claim_by_id = {claim.get("claim_id"): claim for claim in claims if isinstance(claim, dict)}
    if len(claim_by_id) != len([claim for claim in claims if isinstance(claim, dict)]):
        errors.append("paper_plan claim_id values must be unique")
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        for evidence_id in claim.get("evidence_ids", []):
            if evidence_id not in evidence_by_id:
                errors.append(f"claim {claim.get('claim_id')} references unknown evidence_id {evidence_id}")
            elif evidence_by_id[evidence_id].get("verification_status") != "verified":
                errors.append(f"claim {claim.get('claim_id')} references unverified evidence_id {evidence_id}")

    planned_derived_ids = {
        derived_id
        for claim in claims
        if isinstance(claim, dict)
        for derived_id in claim.get("derived_result_ids", [])
        if isinstance(derived_id, str)
    }
    if planned_derived_ids and not args.derived_results:
        errors.append(
            "paper_plan references derived_result_ids but no --derived-results artifact was supplied"
        )
    for requirement in plan.get("requirements", []):
        if isinstance(requirement, dict):
            for claim_id in requirement.get("claim_ids", []):
                if claim_id not in claim_by_id:
                    errors.append(f"requirement {requirement.get('requirement_id')} references unknown claim_id {claim_id}")
    abstract_results = [row for row in plan.get("abstract_results", []) if isinstance(row, dict)]
    abstract_result_ids = [row.get("result_id") for row in abstract_results]
    if len(abstract_result_ids) != len(set(abstract_result_ids)):
        errors.append("abstract_results result_id values must be unique")
    for row in abstract_results:
        result_id = row.get("result_id")
        if result_id not in result_by_id:
            errors.append(f"abstract_results references unknown result_id {result_id}")
        for claim_id in row.get("claim_ids", []):
            if claim_id not in claim_by_id:
                errors.append(f"abstract result {result_id} references unknown claim_id {claim_id}")
        if not str(row.get("selection_reason", "")).strip():
            errors.append(f"abstract result {result_id} has no selection_reason")
    maximum_abstract_results = plan.get("precision_policy", {}).get("abstract_max_numeric_claims")
    if isinstance(maximum_abstract_results, int) and len(abstract_results) > maximum_abstract_results:
        errors.append(
            f"abstract_results has {len(abstract_results)} entries; precision_policy allows {maximum_abstract_results}"
        )
    section_by_id = {section.get("section_id"): section for section in plan.get("sections", []) if isinstance(section, dict)}
    for claim in claims:
        if isinstance(claim, dict) and claim.get("section") not in section_by_id:
            errors.append(f"claim {claim.get('claim_id')} references unknown section {claim.get('section')}")
    for section_id, section in section_by_id.items():
        for claim_id in section.get("claim_ids", []):
            if claim_id not in claim_by_id:
                errors.append(f"section {section_id} references unknown claim_id {claim_id}")
    for collection_name in ("figures", "tables"):
        for item in plan.get(collection_name, []):
            if not isinstance(item, dict):
                continue
            item_id = item.get("figure_id", item.get("table_id", collection_name[:-1]))
            for claim_id in item.get("claim_ids", []):
                if claim_id not in claim_by_id:
                    errors.append(f"{collection_name[:-1]} {item_id} references unknown claim_id {claim_id}")
            for evidence_id in item.get("evidence_ids", []):
                if evidence_id not in evidence_by_id:
                    errors.append(f"{collection_name[:-1]} {item_id} references unknown evidence_id {evidence_id}")

    figures_by_id = {
        row.get("figure_id"): row
        for row in plan.get("figures", [])
        if isinstance(row, dict) and isinstance(row.get("figure_id"), str)
    }
    for reference in plan.get("figure_references", []):
        if not isinstance(reference, dict):
            continue
        figure = figures_by_id.get(reference.get("figure_id"))
        if not isinstance(figure, dict):
            continue
        role = reference.get("reference_role")
        semantic_type = figure.get("semantic_type")
        if semantic_type not in FIGURE_ROLE_SEMANTIC_TYPES.get(role, set()):
            errors.append(
                f"figure reference {reference.get('reference_id')} role={role!r} "
                f"does not match figure {figure.get('figure_id')} semantic_type={semantic_type!r}"
            )

    derived_by_id: dict[str, dict[str, Any]] = {}
    if args.derived_results:
        derived_path = resolve_path(args.derived_results, root).resolve()
        try:
            derived_doc = load_structured(derived_path)
        except (OSError, ValueError, TypeError) as exc:
            derived_doc = None
            errors.append(f"derived results cannot be loaded: {exc}")
        if isinstance(derived_doc, dict):
            _, schema_errors, _ = _validate_document(
                derived_path, Path(__file__).resolve().parents[2] / "schemas" / "derived_results.schema.json"
            )
            errors.extend(f"derived_results schema: {message}" for message in schema_errors)
            if derived_doc.get("run_id") != plan.get("run_id"):
                errors.append("derived_results.run_id does not match paper_plan.run_id")
            frozen_ref = derived_doc.get("frozen_results")
            if not isinstance(frozen_ref, dict) or frozen_ref.get("path") != rel_path(frozen_path, root):
                errors.append("derived_results were not computed from the supplied frozen_results file")
            elif frozen_ref.get("sha256") is not None and frozen_ref.get("sha256") != sha256_file(frozen_path):
                errors.append("derived_results were not computed from the supplied frozen_results file: sha256 drift")
            for row in derived_doc.get("derived", []):
                if not isinstance(row, dict) or not isinstance(row.get("derived_result_id"), str):
                    errors.append("derived_results rows must contain derived_result_id")
                    continue
                if row["derived_result_id"] in derived_by_id:
                    errors.append(f"duplicate derived_result_id: {row['derived_result_id']}")
                derived_by_id[row["derived_result_id"]] = row

    missing_derived_ids = sorted(planned_derived_ids - set(derived_by_id))
    if missing_derived_ids:
        errors.append(f"paper_plan references missing derived_result_ids: {missing_derived_ids}")

    text_sources: dict[str, str] = {}
    for label, raw_path in (("abstract", args.abstract), ("paper", args.paper), ("conclusion", args.conclusion)):
        if raw_path:
            path = resolve_path(raw_path, root).resolve()
            content = read_text(path, label, errors, root)
            if content is not None:
                text_sources[label] = content
    if args.abstract is None and abstract_results:
        warnings.append("abstract was not supplied; Abstract Gate numeric coverage was not checked")

    terminology = plan.get("terminology", [])
    for label, text in text_sources.items():
        for term in terminology:
            if not isinstance(term, dict):
                continue
            for variant in term.get("forbidden_variants", []):
                if isinstance(variant, str) and variant and variant.casefold() in text.casefold():
                    errors.append(f"{label} contains forbidden terminology variant {variant!r}; use {term.get('canonical')!r}")
        for result_id, result in result_by_id.items():
            display = str(result.get("display_value", ""))
            if result_id in text and display and display not in text:
                errors.append(f"{label} mentions result {result_id} without canonical display_value {display}")
        for derived_id, row in derived_by_id.items():
            display = str(row.get("display_value", ""))
            if derived_id in text and display and display not in text:
                errors.append(f"{label} mentions derived result {derived_id} without canonical display_value {display}")

    registered_caption_numbers: set[str] = set()
    for result in result_by_id.values():
        for key in ("display_value", "value"):
            if result.get(key) is not None:
                registered_caption_numbers.update(_numeric_tokens(str(result[key])))
    for row in derived_by_id.values():
        for key in ("display_value", "value"):
            if row.get(key) is not None:
                registered_caption_numbers.update(_numeric_tokens(str(row[key])))
    for figure in plan.get("figures", []):
        if not isinstance(figure, dict):
            continue
        caption = str(figure.get("caption_claim", ""))
        if not caption or any(token in caption for token in ("示意", "illustrative", "schematic", "非精确", "不承载")):
            continue
        for number in sorted(_numeric_tokens(caption)):
            if number not in registered_caption_numbers:
                warnings.append(
                    f"figure {figure.get('figure_id', 'figure')} caption claims {number}, which is absent from "
                    "frozen/derived results; body-text repetition alone is not evidence and this becomes blocking under --strict"
                )

    if "abstract" in text_sources:
        abstract = text_sources["abstract"]
        for row in abstract_results:
            result_id = row.get("result_id")
            result = result_by_id.get(result_id)
            if result is None:
                continue
            display = str(result.get("display_value", ""))
            if display and display not in abstract:
                errors.append(f"abstract is missing frozen result {result_id} display_value {display}")
                continue
            unit = str(result.get("unit", ""))
            if display and unit and unit != "dimensionless":
                position = abstract.find(display)
                context = abstract[max(0, position - 32):position + len(display) + 32]
                if unit not in context:
                    errors.append(f"abstract result {result_id} is missing unit {unit!r} near {display}")

    if model_contract:
        answer_errors, _, required_answer_details = evaluate_required_answer_coverage(
            model_contract,
            plan,
            frozen,
            abstract_text=text_sources.get("abstract"),
            require=args.require_answer_contract or args.require_abstract_backcheck,
        )
        errors.extend(answer_errors)
        terminology_errors, terminology_details = evaluate_terminology_consistency(
            model_contract,
            plan,
            text_sources,
        )
        errors.extend(terminology_errors)
    else:
        terminology_errors, terminology_details = evaluate_terminology_consistency(
            None,
            plan,
            text_sources,
        )
        errors.extend(terminology_errors)

    metric_semantic_errors, metric_semantic_details = evaluate_metric_semantics(results, text_sources)
    errors.extend(metric_semantic_errors)
    if model_contract:
        inference_errors, inference_warnings, inference_role_details = evaluate_inference_role_consistency(
            model_contract,
            text_sources,
            require=args.require_inference_role_consistency,
        )
        errors.extend(inference_errors)
        warnings.extend(inference_warnings)

    figure_semantic_errors, figure_semantic_issues, figure_semantic_details = evaluate_figure_semantics(
        plan,
        require=args.require_figure_semantics,
    )
    errors.extend(figure_semantic_errors)

    registered_numbers = {str(result.get("display_value")) for result in result_by_id.values()}
    registered_numbers.update(str(row.get("display_value")) for row in derived_by_id.values())
    number_pattern = re.compile(r"(?<![A-Za-z0-9_])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?(?![A-Za-z0-9_])")
    for label in ("abstract", "conclusion"):
        if label not in text_sources:
            continue
        unregistered = sorted({match.group(0) for match in number_pattern.finditer(text_sources[label]) if match.group(0) not in registered_numbers})
        if unregistered:
            warnings.append(f"{label} contains numeric token(s) not registered in frozen_results: {', '.join(unregistered)}")

    if "paper" in text_sources:
        paper_text = text_sources["paper"]
        for figure in plan.get("figures", []):
            figure_id = figure.get("figure_id")
            if figure_id and figure_id not in paper_text:
                warnings.append(f"paper does not reference planned figure_id {figure_id}")
        for reference in plan.get("figure_references", []):
            if isinstance(reference, dict) and reference.get("figure_id") not in paper_text:
                errors.append(f"paper is missing semantic figure reference {reference.get('figure_id')}")
        for table in plan.get("tables", []):
            table_id = table.get("table_id")
            if table_id and table_id not in paper_text:
                warnings.append(f"paper does not reference planned table_id {table_id}")

    figure_dir = resolve_path(args.figures_dir, root).resolve() if args.figures_dir else None
    for figure in plan.get("figures", []):
        if not isinstance(figure, dict):
            continue
        figure_id = figure.get("figure_id", "figure")
        for artifact in figure.get("data_artifacts", []):
            if not isinstance(artifact, str) or artifact.startswith(("http://", "https://", "s3://", "artifact://")):
                continue
            candidates = [root / artifact]
            if figure_dir:
                candidates.append(figure_dir / artifact)
            if not any(candidate.is_file() for candidate in candidates):
                message = f"figure {figure_id} data artifact does not exist: {artifact}"
                if figure.get("qa_status") == "passed":
                    errors.append(message)
                else:
                    warnings.append(message)
        if args.require_figure_lineage and figure.get("kind") == "data":
            lineage = figure.get("data_lineage")
            if not isinstance(lineage, dict):
                errors.append(f"data figure {figure_id} requires data_lineage before formal QA")
                continue
            if lineage.get("synthetic") is not False:
                errors.append(f"data figure {figure_id} must explicitly set data_lineage.synthetic=false")
            if lineage.get("status") != "verified":
                errors.append(f"data figure {figure_id} data_lineage.status must be verified")
            output_artifact = lineage.get("output_artifact")
            if output_artifact not in figure.get("data_artifacts", []):
                errors.append(f"data figure {figure_id} lineage output_artifact must be listed in data_artifacts")
            if isinstance(output_artifact, str) and not output_artifact.startswith(("http://", "https://", "s3://", "artifact://")):
                if not resolve_path(output_artifact, root).resolve().is_file():
                    errors.append(f"data figure {figure_id} lineage output artifact does not exist: {output_artifact}")
            for input_artifact in lineage.get("input_artifacts", []):
                if not isinstance(input_artifact, str) or input_artifact.startswith(("http://", "https://", "s3://", "artifact://")):
                    continue
                if not resolve_path(input_artifact, root).resolve().is_file():
                    errors.append(f"data figure {figure_id} lineage input artifact does not exist: {input_artifact}")
            command_text = " ".join(str(part) for part in lineage.get("generator_command", [])).casefold()
            if any(token in command_text for token in ("synthetic", "hardcoded", "fake_data", "demo_data")):
                errors.append(f"data figure {figure_id} generator command looks synthetic; use a real artifact-producing run")

        if figure.get("kind") == "illustration":
            illustration = figure.get("illustration")
            if not isinstance(illustration, dict):
                errors.append(
                    f"illustration figure {figure_id} requires an illustration block "
                    "(generator, prompt_path, raster_dpi>=300, text_policy=raster_text, review_status)"
                )
            else:
                for field in ("generator", "prompt_path"):
                    if not isinstance(illustration.get(field), str) or not illustration.get(field):
                        errors.append(f"illustration figure {figure_id} requires a non-empty {field}")
                dpi = illustration.get("raster_dpi")
                if not isinstance(dpi, (int, float)) or isinstance(dpi, bool) or dpi < 300:
                    errors.append(f"illustration figure {figure_id} raster_dpi must be >= 300")
                if illustration.get("text_policy") != "raster_text":
                    errors.append(f"illustration figure {figure_id} text_policy must be raster_text")
                if illustration.get("review_status") != "reviewed":
                    errors.append(f"illustration figure {figure_id} requires visual review (review_status=reviewed) before formal QA")
            caption = str(figure.get("caption_claim", ""))
            if not any(token in caption for token in ("示意", "illustrative", "schematic", "非精确", "不承载")):
                errors.append(
                    f"illustration figure {figure_id} caption must declare it is a schematic that carries no numeric conclusions"
                )

        if figure.get("kind") == "concept" and isinstance(figure.get("illustration"), dict):
            # AI 位图作为正式框架/流程图成品：仍必须保留可编辑源，并记录后端对比择优。
            illustration = figure["illustration"]
            if not isinstance(figure.get("diagram"), dict):
                errors.append(
                    f"concept figure {figure_id} rendered by an AI bitmap must keep its editable diagram block (spec + source)"
                )
            dpi = illustration.get("raster_dpi")
            if not isinstance(dpi, (int, float)) or isinstance(dpi, bool) or dpi < 300:
                errors.append(f"concept figure {figure_id} AI-rendered bitmap raster_dpi must be >= 300")
            if illustration.get("review_status") != "reviewed":
                errors.append(f"concept figure {figure_id} AI-rendered bitmap requires visual review (review_status=reviewed)")
            comparison = illustration.get("backend_comparison")
            if not isinstance(comparison, dict):
                errors.append(
                    f"concept figure {figure_id} AI-rendered bitmap requires backend_comparison "
                    "(at least the editable backend as an alternative, plus selection_reason)"
                )
            else:
                alternatives = comparison.get("alternatives")
                if not isinstance(alternatives, list) or len([a for a in alternatives if isinstance(a, str) and a]) < 2:
                    errors.append(f"concept figure {figure_id} backend_comparison must list at least two backends")
                elif not any("drawio" in a or "editable" in a or "svg" in a for a in alternatives):
                    errors.append(f"concept figure {figure_id} backend_comparison must include an editable-source backend")
                if not isinstance(comparison.get("selection_reason"), str) or not comparison.get("selection_reason").strip():
                    errors.append(f"concept figure {figure_id} backend_comparison requires a non-empty selection_reason")

    for table in plan.get("tables", []):
        if not isinstance(table, dict):
            continue
        table_id = table.get("table_id", "table")
        for artifact in table.get("data_artifacts", []):
            if not isinstance(artifact, str) or artifact.startswith(("http://", "https://", "s3://", "artifact://")):
                continue
            if not resolve_path(artifact, root).resolve().is_file():
                message = f"table {table_id} data artifact does not exist: {artifact}"
                if table.get("qa_status") == "passed":
                    errors.append(message)
                else:
                    warnings.append(message)

    canonical_claim_sources: dict[str, set[str]] = {}
    for collection_name in ("figures", "tables"):
        for item in plan.get(collection_name, []):
            if not isinstance(item, dict):
                continue
            item_id = item.get("figure_id", item.get("table_id", collection_name[:-1]))
            source_id = item.get("canonical_source_id")
            if args.require_canonical_source and item.get("data_artifacts") and not isinstance(source_id, str):
                errors.append(f"{collection_name[:-1]} {item_id} requires canonical_source_id")
                continue
            if not isinstance(source_id, str):
                continue
            node = dag_nodes.get(source_id)
            if not isinstance(node, dict):
                errors.append(f"{collection_name[:-1]} {item_id} canonical_source_id is absent from artifact DAG: {source_id}")
                continue
            node_status = node.get("status", node.get("freshness"))
            if node_status != "current":
                errors.append(f"{collection_name[:-1]} {item_id} canonical source is not current: {source_id}")
            output_paths = {
                str(ref.get("path")) for ref in node.get("outputs", [])
                if isinstance(ref, dict) and isinstance(ref.get("path"), str)
            }
            if not output_paths:
                node_path = node.get("path")
                if isinstance(node_path, str):
                    output_paths.add(node_path)
            if not output_paths.intersection(set(item.get("data_artifacts", []))):
                errors.append(f"{collection_name[:-1]} {item_id} canonical source does not produce a listed data artifact")
            for claim_id in item.get("claim_ids", []):
                canonical_claim_sources.setdefault(str(claim_id), set()).add(source_id)
    for claim_id, source_ids in canonical_claim_sources.items():
        if len(source_ids) > 1:
            errors.append(f"claim {claim_id} is rendered from multiple canonical sources: {sorted(source_ids)}")

    # Figure binding for LaTeX delivery: every image the paper actually
    # includes must be registered by a planned figure, and each formal
    # diagram/illustration's declared renders should be the ones included
    # (closes the "AI bitmap swapped in for the declared drawio render" hole).
    if getattr(args, "paper", None) and str(getattr(args, "paper", "")).endswith(".tex"):
        import re as _re

        tex_path = resolve_path(args.paper, root).resolve()
        if tex_path.is_file():
            collected: set[tuple[str, Path]] = set()
            visited: set[Path] = set()
            stack: list[Path] = [tex_path]
            while stack and len(visited) < 50:
                current = stack.pop()
                if current in visited or not current.is_file():
                    continue
                try:
                    current.relative_to(root)
                except ValueError:
                    errors.append(f"tex include escapes project root: {current}")
                    continue
                visited.add(current)
                try:
                    content = current.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    warnings.append(f"cannot read tex file for figure binding: {current} ({exc})")
                    continue
                for match in _re.finditer(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", content):
                    collected.add((match.group(1).strip(), current.parent))
                for match in _re.finditer(r"\\input\{([^}]+)\}", content):
                    target = match.group(1).strip()
                    if not target.endswith(".tex"):
                        target += ".tex"
                    include_target = (current.parent / target).resolve()
                    try:
                        include_target.relative_to(root)
                    except ValueError:
                        errors.append(f"tex input escapes project root: {target}")
                        continue
                    stack.append(include_target)
            registered: set[str] = set()
            planned_render_roots: dict[str, set[str]] = {}
            for figure in plan.get("figures", []):
                if not isinstance(figure, dict):
                    continue
                fig_id = str(figure.get("figure_id", "figure"))
                candidates: set[str] = set()
                diagram = figure.get("diagram")
                if isinstance(diagram, dict):
                    candidates.update(str(p) for p in diagram.get("rendered_paths", []) if isinstance(p, str))
                for artifact in figure.get("data_artifacts", []):
                    if isinstance(artifact, str):
                        candidates.add(artifact)
                planned_render_roots[fig_id] = candidates
                registered.update(candidates)

            def _path_variants(raw: str) -> set[str]:
                normalized = raw.replace("\\", "/").casefold()
                while normalized.startswith("./"):
                    normalized = normalized[2:]
                variants = {normalized}
                if Path(normalized).suffix in {".png", ".pdf", ".jpg", ".jpeg", ".eps", ".svg"}:
                    variants.add(normalized.rsplit(".", 1)[0])
                return variants

            def _suffix_matches(left: str, right: str) -> bool:
                for left_variant in _path_variants(left):
                    for right_variant in _path_variants(right):
                        if (
                            left_variant == right_variant
                            or left_variant.endswith("/" + right_variant)
                            or right_variant.endswith("/" + left_variant)
                        ):
                            return True
                return False

            def _matches_any_registered(image_path: str) -> bool:
                if image_path in registered:
                    return True
                return any(_suffix_matches(image_path, cand) for cand in registered)

            digest_by_path: dict[str, str] = {}
            for node in dag_nodes.values():
                node_path = node.get("path")
                node_digest = node.get("sha256")
                if isinstance(node_path, str) and isinstance(node_digest, str):
                    digest_by_path[node_path] = node_digest
                outputs = node.get("outputs")
                if isinstance(outputs, list):
                    for ref in outputs:
                        if isinstance(ref, dict) and isinstance(ref.get("path"), str) and isinstance(ref.get("sha256"), str):
                            digest_by_path[ref["path"]] = ref["sha256"]

            for image_path, source_dir in sorted(collected, key=lambda item: (item[0], item[1].as_posix())):
                if not _matches_any_registered(image_path):
                    warnings.append(
                        f"paper includes an image not registered by any planned figure: {image_path} "
                        "(register it in paper_plan.figures[].diagram.rendered_paths or data_artifacts); "
                        "this becomes blocking under --strict"
                    )
                    continue
                if not args.artifact_dag:
                    continue
                matching_digests = [
                    (cand_path, cand_digest)
                    for cand_path, cand_digest in digest_by_path.items()
                    if _suffix_matches(image_path, cand_path)
                ]
                if not matching_digests:
                    warnings.append(
                        f"included image {image_path} matches a registered artifact with no digest; "
                        "register its sha256 in artifact_dag so bitmap substitution is detectable"
                    )
                    continue
                probe_names = [image_path] + [image_path + ext for ext in (".png", ".pdf", ".jpg", ".jpeg", ".eps", ".svg")]
                resolved = None
                for name in probe_names:
                    probe = (source_dir / name).resolve()
                    try:
                        probe.relative_to(root)
                    except ValueError:
                        errors.append(f"included image path escapes project root: {image_path}")
                        break
                    if probe.is_file():
                        resolved = probe
                        break
                if resolved is None:
                    warnings.append(f"included image {image_path} could not be resolved on disk for digest verification")
                    continue
                actual_digest = sha256_file(resolved)
                expected_digests = {cand_digest for _, cand_digest in matching_digests}
                if len(expected_digests) > 1:
                    errors.append(
                        f"included image {image_path} ambiguously matches DAG artifacts with different digests; "
                        "use distinct project-relative rendered paths"
                    )
                elif actual_digest not in expected_digests:
                    candidates = ", ".join(cand_path for cand_path, _ in matching_digests)
                    errors.append(
                        f"included image {image_path} does not match the registered digest of DAG artifact {candidates}; "
                        "the rendered bytes changed after registration or a different bitmap was substituted"
                    )
            for fig_id, candidates in planned_render_roots.items():
                if not candidates:
                    continue
                if not any(
                    image_path in candidates or any(_suffix_matches(image_path, cand) for cand in candidates)
                    for image_path, _ in collected
                ):
                    warnings.append(
                        f"figure {fig_id} declares rendered artifacts but none appear in the paper's includegraphics set"
                    )
        else:
            warnings.append(f"--paper tex path does not exist, figure binding skipped: {getattr(args, 'paper', None)}")

    ok = not errors and (not args.strict or not warnings)
    report = {
        "ok": ok,
        "files": {
            "paper_plan": rel_path(plan_path, root),
            "frozen_results": rel_path(frozen_path, root),
            "evidence_registry": rel_path(registry_path, root),
        },
        "errors": errors,
        "warnings": warnings,
        "checked_texts": sorted(text_sources),
        "checked_results": len(result_by_id),
        "checked_evidence": len(evidence_by_id),
        "required_answer_coverage": required_answer_details,
        "terminology_semantics": terminology_details,
        "metric_semantics": metric_semantic_details,
        "inference_role_review": inference_role_details,
        "figure_semantic_review": {
            "issues": figure_semantic_issues,
            "details": figure_semantic_details,
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
