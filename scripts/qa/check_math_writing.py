#!/usr/bin/env python3
"""Check mathematical traceability and argumentative order in a paper draft.

This checker does not prove algebra.  It checks the cheaper, necessary
preconditions for a trustworthy mathematical section:

* every formulation unit points to the model/equation/constraint that it
  explains;
* every validation unit points to a declared validation obligation;
* result units point to frozen or derived results rather than invented prose;
* prerequisite units form an acyclic, forward-moving argument graph;
* a formal draft contains stable locators for the referenced mathematics.

Algebraic correctness, dimensional reasoning, and whether the chosen model is
reasonable still require an independent W2 mathematical review.  The manual
checkpoint is deliberately retained instead of treating string matching as a
theorem prover.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from _common import load_structured, rel_path, resolve_path  # noqa: E402
from qa.validate_contracts import _validate_document  # noqa: E402
from qa.tex_source import read_visible_text  # noqa: E402


FORMULATION_ROLES = {"model_choice", "mechanism_derivation", "parameter_evidence"}
RESULT_ROLES = {"result_observation", "comparison"}
VALIDATION_ROLES = {"validation"}
INTERPRETATION_ROLES = {"interpretation", "boundary", "recommendation"}
CORE_ROLES = FORMULATION_ROLES | RESULT_ROLES | VALIDATION_ROLES | INTERPRETATION_ROLES
ROLE_RANK = {
    "problem_tension": 0,
    "model_choice": 1,
    "mechanism_derivation": 1,
    "parameter_evidence": 1,
    "result_observation": 2,
    "comparison": 2,
    "validation": 3,
    "interpretation": 4,
    "boundary": 4,
    "recommendation": 4,
}
MATH_FIELDS = (
    "model_ids",
    "equation_ids",
    "replay_case_ids",
    "constraint_ids",
    "validation_obligation_ids",
    "result_ids",
    "derived_result_ids",
    "math_locators",
)


def _id_map(rows: Any, key: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    values: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    if not isinstance(rows, list):
        return values, errors
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = row.get(key)
        if not isinstance(value, str) or not value:
            continue
        if value in values:
            errors.append(f"duplicate {key}: {value}")
        values[value] = row
    return values, errors


def _question_ids(unit: dict[str, Any], claims: dict[str, dict[str, Any]]) -> set[str]:
    return {
        str(claims[claim_id].get("question_id"))
        for claim_id in unit.get("claim_ids", [])
        if claim_id in claims and isinstance(claims[claim_id].get("question_id"), str)
    }


def _contains_token(text: str, token: str) -> bool:
    """Match an ID without treating C1 as present inside C10."""

    return re.search(
        rf"(?<![A-Za-z0-9_-]){re.escape(token)}(?![A-Za-z0-9_-])",
        text,
        flags=re.IGNORECASE,
    ) is not None


def _first_locator(text: str, locators: list[str]) -> int | None:
    positions = [text.casefold().find(locator.casefold()) for locator in locators if locator]
    positions = [position for position in positions if position >= 0]
    return min(positions) if positions else None


def _check_reference(
    errors: list[str],
    unit_id: str,
    field: str,
    reference: str,
    selected_models: dict[str, dict[str, Any]],
    model_items: dict[str, dict[str, set[str]]],
) -> None:
    owners = [
        model_id
        for model_id in selected_models
        if reference in model_items.get(model_id, {}).get(field, set())
    ]
    if not owners:
        errors.append(
            f"argument unit {unit_id} references unknown {field} {reference} "
            f"within model_ids={sorted(selected_models)}"
        )
    elif len(owners) > 1:
        errors.append(f"argument unit {unit_id} has ambiguous {field} {reference}: {owners}")


def evaluate_math_writing(
    contract: dict[str, Any],
    plan: dict[str, Any],
    draft: str,
    *,
    frozen: dict[str, Any] | None = None,
    derived: dict[str, Any] | None = None,
    writer_package: dict[str, Any] | None = None,
    require_coverage: bool = False,
    require_replay_bindings: bool = False,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []

    claims, duplicate_claims = _id_map(plan.get("claims"), "claim_id")
    errors.extend(duplicate_claims)
    units, duplicate_units = _id_map(plan.get("argument_units"), "unit_id")
    errors.extend(duplicate_units)
    models, duplicate_models = _id_map(contract.get("models"), "model_id")
    errors.extend(duplicate_models)
    frozen_results, duplicate_results = _id_map((frozen or {}).get("results"), "result_id")
    errors.extend(duplicate_results)
    derived_results, duplicate_derived = _id_map((derived or {}).get("derived"), "derived_result_id")
    errors.extend(duplicate_derived)

    model_items: dict[str, dict[str, set[str]]] = {}
    obligations_by_id: dict[str, list[str]] = {}
    for model_id, model in models.items():
        details = model.get("plan_details") if isinstance(model.get("plan_details"), dict) else {}
        equations = {
            str(row.get("equation_id"))
            for row in details.get("equation_plan", [])
            if isinstance(row, dict) and isinstance(row.get("equation_id"), str)
        }
        replay_case_ids = {
            str(case.get("case_id"))
            for row in details.get("equation_plan", [])
            if isinstance(row, dict)
            and isinstance(row.get("verification"), dict)
            for case in row["verification"].get("numeric_replay", [])
            if isinstance(case, dict) and isinstance(case.get("case_id"), str)
        }
        constraints = {
            str(row.get("constraint_id"))
            for row in model.get("constraints", [])
            if isinstance(row, dict) and isinstance(row.get("constraint_id"), str)
        }
        obligations = {
            str(row.get("obligation_id"))
            for row in model.get("validation_obligations", [])
            if isinstance(row, dict) and isinstance(row.get("obligation_id"), str)
        }
        model_items[model_id] = {
            "equation_ids": equations,
            "replay_case_ids": replay_case_ids,
            "constraint_ids": constraints,
            "validation_obligation_ids": obligations,
        }
        for obligation_id in obligations:
            obligations_by_id.setdefault(obligation_id, []).append(model_id)

    if frozen is not None:
        if frozen.get("claimable") is not True or frozen.get("validation_verdict") != "PASS":
            errors.append("math writing requires a claimable PASS frozen_results artifact")
        frozen_obligations = {
            row.get("obligation_id"): row
            for row in frozen.get("validation_obligations", [])
            if isinstance(row, dict) and isinstance(row.get("obligation_id"), str)
        }
    else:
        frozen_obligations = {}
        if require_coverage:
            errors.append("formal math writing coverage requires --frozen-results")

    if derived is not None and derived.get("status") != "frozen":
        errors.append("derived results supplied to math writing must have status=frozen")

    # The writer package is a second binding point.  A formal run must not let
    # the Writer receive a silently changed argument plan.
    if writer_package is not None:
        package_units, package_duplicate_units = _id_map(writer_package.get("argument_units"), "unit_id")
        errors.extend(f"writer_package: {message}" for message in package_duplicate_units)
        if set(package_units) != set(units):
            errors.append(
                "writer_package.argument_units must contain exactly the paper_plan argument units: "
                f"missing={sorted(set(units) - set(package_units))}, "
                f"extra={sorted(set(package_units) - set(units))}"
            )
        for unit_id in sorted(set(units) & set(package_units)):
            for field in MATH_FIELDS:
                plan_values = set(units[unit_id].get(field, []))
                package_values = set(package_units[unit_id].get(field, []))
                if plan_values != package_values:
                    errors.append(
                        f"writer_package unit {unit_id} changed {field}: "
                        f"plan={sorted(plan_values)} package={sorted(package_values)}"
                    )

    # Argument dependency graph: reject cycles and dependencies that move the
    # reader backwards (e.g. interpretation before validation).
    graph = {
        unit_id: [item for item in unit.get("prerequisite_unit_ids", []) if isinstance(item, str)]
        for unit_id, unit in units.items()
    }
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(unit_id: str) -> None:
        if state.get(unit_id) == 1:
            cycle_start = stack.index(unit_id) if unit_id in stack else 0
            errors.append("argument unit prerequisite cycle: " + " -> ".join(stack[cycle_start:] + [unit_id]))
            return
        if state.get(unit_id) == 2:
            return
        state[unit_id] = 1
        stack.append(unit_id)
        for prerequisite_id in graph.get(unit_id, []):
            if prerequisite_id not in units:
                errors.append(f"argument unit {unit_id} references unknown prerequisite_unit_id {prerequisite_id}")
            else:
                visit(prerequisite_id)
        stack.pop()
        state[unit_id] = 2

    for unit_id in units:
        visit(unit_id)

    coverage_order: list[str] = []
    readiness = plan.get("readiness") if isinstance(plan.get("readiness"), dict) else {}
    for coverage in readiness.get("question_coverage", []):
        if not isinstance(coverage, dict):
            continue
        for field in (
            "formulation_unit_ids",
            "result_unit_ids",
            "validation_unit_ids",
            "interpretation_unit_ids",
        ):
            for unit_id in coverage.get(field, []):
                if unit_id in units:
                    if unit_id in coverage_order:
                        errors.append(f"argument unit {unit_id} appears more than once in readiness.question_coverage")
                    else:
                        coverage_order.append(unit_id)
    coverage_position = {unit_id: index for index, unit_id in enumerate(coverage_order)}

    reference_counts = {field: 0 for field in MATH_FIELDS}
    locator_positions: dict[str, int] = {}
    for unit_id, unit in units.items():
        role = unit.get("rhetorical_role")
        unit_questions = _question_ids(unit, claims)
        if len(unit_questions) != 1:
            errors.append(f"argument unit {unit_id} must resolve to exactly one question_id")
        selected_model_ids = [item for item in unit.get("model_ids", []) if isinstance(item, str)]
        selected_models = {model_id: models[model_id] for model_id in selected_model_ids if model_id in models}
        for model_id in selected_model_ids:
            if model_id not in models:
                errors.append(f"argument unit {unit_id} references unknown model_id {model_id}")
        for model_id, model in selected_models.items():
            model_question = model.get("question_id")
            if unit_questions and model_question not in unit_questions:
                errors.append(
                    f"argument unit {unit_id} binds model {model_id} from {model_question}, "
                    f"but its claim belongs to {sorted(unit_questions)}"
                )

        for field in MATH_FIELDS:
            reference_counts[field] += len(unit.get(field, [])) if isinstance(unit.get(field), list) else 0

        if role in FORMULATION_ROLES and not selected_model_ids:
            errors.append(f"formulation unit {unit_id} must declare model_ids")
        if role == "mechanism_derivation" and not (
            unit.get("equation_ids") or unit.get("constraint_ids")
        ):
            errors.append(f"mechanism_derivation unit {unit_id} must declare equation_ids or constraint_ids")
        if require_replay_bindings and role == "mechanism_derivation":
            required_replay_ids = {
                replay_id
                for model_id in selected_model_ids
                for replay_id in model_items.get(model_id, {}).get("replay_case_ids", set())
            }
            declared_replay_ids = set(unit.get("replay_case_ids", []))
            missing_replay_ids = sorted(required_replay_ids - declared_replay_ids)
            if missing_replay_ids:
                errors.append(
                    f"mechanism_derivation unit {unit_id} must bind numeric replay case(s): {missing_replay_ids}"
                )
        if role in RESULT_ROLES and not (unit.get("result_ids") or unit.get("derived_result_ids")):
            errors.append(f"result unit {unit_id} must declare result_ids or derived_result_ids")
        if role in VALIDATION_ROLES and not unit.get("validation_obligation_ids"):
            errors.append(f"validation unit {unit_id} must declare validation_obligation_ids")
        if role in INTERPRETATION_ROLES and not unit.get("prerequisite_unit_ids"):
            errors.append(f"interpretation unit {unit_id} must depend on an earlier result or validation unit")

        for equation_id in unit.get("equation_ids", []):
            _check_reference(errors, unit_id, "equation_ids", equation_id, selected_models, model_items)
        for replay_case_id in unit.get("replay_case_ids", []):
            _check_reference(errors, unit_id, "replay_case_ids", replay_case_id, selected_models, model_items)
        for constraint_id in unit.get("constraint_ids", []):
            _check_reference(errors, unit_id, "constraint_ids", constraint_id, selected_models, model_items)
        for obligation_id in unit.get("validation_obligation_ids", []):
            _check_reference(
                errors, unit_id, "validation_obligation_ids", obligation_id, selected_models, model_items
            )
            if frozen is not None:
                row = frozen_obligations.get(obligation_id)
                if row is None:
                    errors.append(f"validation obligation {obligation_id} is absent from frozen_results")
                elif row.get("status") != "PASS":
                    errors.append(
                        f"math writing cannot cite validation obligation {obligation_id} with status {row.get('status')!r}"
                    )

        for result_id in unit.get("result_ids", []):
            result = frozen_results.get(result_id)
            if result is None:
                if frozen is None:
                    message = f"result unit {unit_id} cannot be resolved without frozen_results: {result_id}"
                    (errors if require_coverage else warnings).append(message)
                else:
                    errors.append(f"result unit {unit_id} references unknown result_id {result_id}")
            else:
                if result.get("claimable") is not True or result.get("validation_status") != "passed":
                    errors.append(f"result unit {unit_id} references non-claimable result {result_id}")
                if unit_questions and result.get("question_id") not in unit_questions:
                    errors.append(f"result {result_id} belongs to {result.get('question_id')}, not {sorted(unit_questions)}")

        for derived_id in unit.get("derived_result_ids", []):
            result = derived_results.get(derived_id)
            if result is None:
                if derived is None:
                    message = f"derived result unit {unit_id} cannot be resolved without derived_results: {derived_id}"
                    (errors if require_coverage else warnings).append(message)
                else:
                    errors.append(f"result unit {unit_id} references unknown derived_result_id {derived_id}")
            elif unit_questions and result.get("question_id") not in unit_questions:
                errors.append(
                    f"derived result {derived_id} belongs to {result.get('question_id')}, not {sorted(unit_questions)}"
                )

        # A formal draft must carry a stable locator for every core argument
        # unit.  For math-bearing references, the IDs themselves must also be
        # present (LaTeX \label{} is a safe way to do this without visible text).
        locators = [item for item in unit.get("math_locators", []) if isinstance(item, str) and item]
        if require_coverage and role in CORE_ROLES:
            if not locators:
                errors.append(f"formal math writing coverage requires math_locators for unit {unit_id}")
            else:
                position = _first_locator(draft, locators)
                if position is None:
                    errors.append(f"draft is missing math locator(s) for argument unit {unit_id}: {locators}")
                else:
                    locator_positions[unit_id] = position
            for reference in (
                list(unit.get("equation_ids", []))
                + list(unit.get("replay_case_ids", []))
                + list(unit.get("constraint_ids", []))
                + list(unit.get("validation_obligation_ids", []))
            ):
                if not _contains_token(draft, reference):
                    errors.append(f"draft is missing stable mathematical reference {reference} for unit {unit_id}")

        for prerequisite_id in graph.get(unit_id, []):
            if prerequisite_id not in units:
                continue
            prerequisite_role = units[prerequisite_id].get("rhetorical_role")
            if ROLE_RANK.get(prerequisite_role, -1) > ROLE_RANK.get(role, -1):
                errors.append(
                    f"argument unit {unit_id} depends on later rhetorical role {prerequisite_id}:{prerequisite_role}"
                )
            if (
                prerequisite_id in coverage_position
                and unit_id in coverage_position
                and coverage_position[prerequisite_id] >= coverage_position[unit_id]
            ):
                errors.append(
                    f"argument unit {unit_id} is ordered before prerequisite {prerequisite_id} in readiness coverage"
                )
            if (
                require_coverage
                and prerequisite_id in locator_positions
                and unit_id in locator_positions
                and locator_positions[prerequisite_id] >= locator_positions[unit_id]
            ):
                errors.append(f"draft writes {unit_id} before its prerequisite {prerequisite_id}")

    if require_coverage:
        missing_coverage_units = sorted(set(units) - set(coverage_order))
        if missing_coverage_units:
            errors.append(f"formal math writing coverage is missing readiness placement for units: {missing_coverage_units}")
    if require_coverage and not writer_package:
        errors.append("formal math writing coverage requires a bound writer_package")

    if not require_coverage:
        warnings.append("math writing coverage was not required; rerun with --require-coverage before W2")

    details = {
        "coverage_required": require_coverage,
        "argument_unit_count": len(units),
        "coverage_order": coverage_order,
        "math_reference_counts": reference_counts,
        "locator_units_found": sorted(locator_positions),
        "algebra_proof": "not_automated_manual_w2_required",
    }
    return errors, warnings, details


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-contract", required=True)
    parser.add_argument("--paper-plan", required=True)
    parser.add_argument("--draft", required=True)
    parser.add_argument("--frozen-results")
    parser.add_argument("--derived-results")
    parser.add_argument("--writer-package")
    parser.add_argument("--require-coverage", action="store_true")
    parser.add_argument("--require-replay-bindings", action="store_true")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    contract_path = resolve_path(args.model_contract, root).resolve()
    plan_path = resolve_path(args.paper_plan, root).resolve()
    draft_path = resolve_path(args.draft, root).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {}
    frozen: dict[str, Any] | None = None
    derived: dict[str, Any] | None = None
    writer_package: dict[str, Any] | None = None
    try:
        contract, contract_schema_errors, _ = _validate_document(
            contract_path, Path(__file__).resolve().parents[2] / "schemas" / "model_contract.schema.json"
        )
        plan, plan_schema_errors, _ = _validate_document(
            plan_path, Path(__file__).resolve().parents[2] / "schemas" / "paper_plan.schema.json"
        )
        errors.extend(f"model_contract schema: {message}" for message in contract_schema_errors)
        errors.extend(f"paper_plan schema: {message}" for message in plan_schema_errors)
        if args.frozen_results:
            frozen_path = resolve_path(args.frozen_results, root).resolve()
            frozen, frozen_schema_errors, _ = _validate_document(
                frozen_path, Path(__file__).resolve().parents[2] / "schemas" / "frozen_results.schema.json"
            )
            errors.extend(f"frozen_results schema: {message}" for message in frozen_schema_errors)
        if args.derived_results:
            derived_path = resolve_path(args.derived_results, root).resolve()
            derived, derived_schema_errors, _ = _validate_document(
                derived_path, Path(__file__).resolve().parents[2] / "schemas" / "derived_results.schema.json"
            )
            errors.extend(f"derived_results schema: {message}" for message in derived_schema_errors)
        if args.writer_package:
            writer_package = load_structured(resolve_path(args.writer_package, root).resolve())
            if not isinstance(writer_package, dict) or writer_package.get("schema_version") != "1.0":
                errors.append("writer_package must have schema_version=1.0")
        draft = read_visible_text(draft_path, root)
        if not isinstance(contract, dict) or not isinstance(plan, dict):
            raise ValueError("model contract and paper plan must be objects")
        if frozen is not None and not isinstance(frozen, dict):
            raise ValueError("frozen results must be an object")
        if derived is not None and not isinstance(derived, dict):
            raise ValueError("derived results must be an object")
        if args.require_coverage and not args.writer_package:
            errors.append("--require-coverage requires --writer-package")
        math_errors, math_warnings, details = evaluate_math_writing(
            contract,
            plan,
            draft,
            frozen=frozen,
            derived=derived,
            writer_package=writer_package,
            require_coverage=args.require_coverage,
            require_replay_bindings=args.require_replay_bindings,
        )
        errors.extend(math_errors)
        warnings.extend(math_warnings)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        errors.append(str(exc))

    ok = not errors and (not args.strict or not warnings)
    print(json.dumps({
        "ok": ok,
        "model_contract": rel_path(contract_path, root),
        "paper_plan": rel_path(plan_path, root),
        "draft": rel_path(draft_path, root),
        "coverage_required": args.require_coverage,
        "details": details,
        "errors": errors,
        "warnings": warnings,
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
