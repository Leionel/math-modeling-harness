"""Read-only question tasks from explicit contracts and current producer evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from _common import sha256_file
from human_surface import check_authoring_freshness
from project_layout import resolve_manifest_path
from runtime_state import load_runtime_state
from workflow_sources import project_file, read_object
from qa.tex_source import load_tex_source
from qa.paper_audit import audit_paper
from qa.check_paper_readiness import evaluate_readiness
from validation.obligations import file_ref, verify_validation_report
from views.writing_spine import build_writing_spine


def _current_ref(root: Path, ref: dict[str, Any]) -> bool:
    path = project_file(root, str(ref.get("path", "")))
    return (
        path.is_file()
        and isinstance(ref.get("sha256"), str)
        and sha256_file(path) == ref["sha256"]
    )


def question_workbench(root: Path) -> dict[str, Any]:
    """Do not infer question ids from filenames or promote unbound output values."""
    root = root.resolve()
    errors: list[str] = []
    state = load_runtime_state(
        resolve_manifest_path(root), project_root=root, allow_legacy=False
    )

    def document(role: str) -> tuple[dict[str, Any], str | None]:
        path = state.root_path(role)
        if path is None:
            return {}, None
        value = read_object(root, str(path))
        if value and value.get("run_id") != state.run_id:
            errors.append(f"{role} run_id differs from current run")
            return {}, path.relative_to(root).as_posix()
        return value, path.relative_to(root).as_posix()

    model, model_path = document("model_contract")
    plan, plan_path = document("paper_plan")
    frozen, frozen_path = document("frozen_results")
    registry, registry_path = document("evidence_registry")
    index = read_object(root, str(state.root_path("run_index", required=True)))
    package, package_path = document("writer_package")
    freshness = check_authoring_freshness(root)
    model_stale = any(
        row.get("role") == "model_contract" and row.get("status") != "current"
        for row in freshness.get("entries", [])
    )
    validation: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    selected = set((index.get("selection") or {}).get("selected_receipt_ids", []))
    for entry in index.get("receipts", []):
        if not isinstance(entry, dict) or not entry.get("receipt_path"):
            continue
        receipt = read_object(root, str(entry["receipt_path"]))
        if (
            receipt.get("receipt_id") != entry.get("receipt_id")
            or receipt.get("run_id") != state.run_id
        ):
            continue
        for ref in receipt.get("output_refs", []):
            if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
                continue
            path = project_file(root, ref["path"])
            if path.suffix.lower() != ".json" or not path.is_file():
                continue
            output = read_object(root, ref["path"])
            current = _current_ref(root, ref)
            if (
                output.get("schema_version") == "1.0"
                and output.get("run_id") == state.run_id
                and output.get("evaluator_version")
            ):
                try:
                    model_ref = output["model_contract_snapshot"]
                    measurement_ref = output["measurement_snapshot"]
                    if (
                        receipt.get("exit_code") != 0
                        or model_path is None
                        or project_file(root, model_ref["path"])
                        != project_file(root, model_path)
                        or not current
                    ):
                        raise ValueError(
                            "validation output is not bound to the current model/receipt"
                        )
                    measurements = read_object(root, measurement_ref["path"])
                    verify_validation_report(
                        output,
                        model,
                        measurements,
                        file_ref(project_file(root, model_path), root),
                        file_ref(project_file(root, measurement_ref["path"]), root),
                    )
                    for obligation in output.get("obligations", []):
                        validation[obligation["obligation_id"]] = {
                            **obligation,
                            "path": ref["path"],
                            "receipt_id": receipt["receipt_id"],
                        }
                except (KeyError, ValueError) as exc:
                    errors.append(f"validation {ref['path']}: {exc}")
            if receipt.get("stage") in {"smoke", "full"}:
                for result in output.get("results", []):
                    if isinstance(result, dict) and isinstance(
                        result.get("question_id"), str
                    ):
                        outputs.append(
                            {
                                "question_id": result["question_id"],
                                "path": ref["path"],
                                "receipt_id": receipt["receipt_id"],
                                "stage": receipt["stage"],
                                "selected": receipt["receipt_id"] in selected,
                                "freshness": "current" if current else "unverified",
                                "exit_code": receipt.get("exit_code"),
                            }
                        )
    package_errors = []
    if package:
        refs = package.get("source_snapshots", {})
        for role, path in [
            ("paper_plan", plan_path),
            ("frozen_results", frozen_path),
            ("evidence_registry", registry_path),
        ]:
            ref = refs.get(role)
            if (
                not isinstance(ref, dict)
                or path is None
                or project_file(root, str(ref.get("path", "")))
                != project_file(root, path)
                or not _current_ref(root, ref)
            ):
                package_errors.append(f"{role} snapshot missing or stale")
        if package.get("package_mode") != "technical_draft":
            package_errors.append("writer package is a preview, not a technical draft")
        readiness_errors, readiness_warnings, _ = evaluate_readiness(plan, registry)
        package_errors.extend([*readiness_errors, *readiness_warnings])
    else:
        package_errors.append("no registered writer package")
    if model_stale:
        package_errors.append("model authoring source changed")
    declared_ids = {
        obligation["obligation_id"]
        for row in model.get("models", [])
        for obligation in row.get("validation_obligations", [])
    }
    if not declared_ids or any(
        validation.get(identifier, {}).get("status") != "PASS"
        for identifier in declared_ids
    ):
        package_errors.append(
            "current independent validation does not cover every declared obligation with PASS"
        )
    if (
        frozen
        and frozen.get("claimable") is True
        and frozen.get("validation_verdict") == "PASS"
    ):
        for ref in [
            frozen.get("model_contract_snapshot", {}),
            frozen.get("source_snapshot", {}),
            *frozen.get("validation_snapshot", []),
        ]:
            if not _current_ref(root, ref):
                package_errors.append(
                    "frozen source/model/validation binding is missing or stale"
                )
        results = [row for row in frozen.get("results", []) if isinstance(row, dict)]
    else:
        package_errors.append("no registered claimable PASS frozen results")
    tex = root / "paper/main.tex"
    source = load_tex_source(tex, root) if tex.is_file() else None
    paper_binding = {"status": "unverified", "reason": "no paper source"}
    if source:
        build_receipt = state.root_path("build_receipt")
        paper_binding = audit_paper(
            root,
            tex="paper/main.tex",
            pdf="paper/main.pdf" if (root / "paper/main.pdf").is_file() else None,
            build_receipt=str(build_receipt)
            if build_receipt and build_receipt.is_file()
            else None,
        )["source_binding"]
    questions = []
    for question in model.get("questions", []):
        if not isinstance(question, dict):
            continue
        qid = question["question_id"]
        models = [
            row for row in model.get("models", []) if row.get("question_id") == qid
        ]
        obligations = []
        for row in models:
            for obligation in row.get("validation_obligations", []):
                observed = validation.get(obligation["obligation_id"])
                obligations.append(
                    {
                        **obligation,
                        "status": observed["status"]
                        if observed and not model_stale
                        else "unknown",
                        "evidence": observed if not model_stale else None,
                    }
                )
        claims = [
            claim for claim in plan.get("claims", []) if claim.get("question_id") == qid
        ]
        claim_ids = {claim["claim_id"] for claim in claims}
        units = [
            unit
            for unit in plan.get("argument_units", [])
            if qid in (unit.get("scope") or {}).get("question_ids", [])
            or claim_ids.intersection(unit.get("claim_ids", []))
        ]
        shared_ids = {
            identifier for unit in units for identifier in unit.get("model_ids", [])
        }
        for shared in model.get("models", []):
            if shared.get("model_id") in shared_ids and shared not in models:
                models.append(shared)
                for obligation in shared.get("validation_obligations", []):
                    observed = validation.get(obligation["obligation_id"])
                    obligations.append(
                        {
                            **obligation,
                            "status": observed["status"]
                            if observed and not model_stale
                            else "unknown",
                            "evidence": observed if not model_stale else None,
                        }
                    )
        locations = []
        for unit in units:
            for marker in unit.get("math_locators", []):
                matches = []
                if source:
                    offset = source.text.find(marker)
                    while offset >= 0:
                        loc = source.location(offset)
                        if loc:
                            matches.append(
                                {
                                    "path": loc[0].relative_to(root).as_posix(),
                                    "line": loc[1],
                                }
                            )
                        offset = source.text.find(marker, offset + len(marker))
                locations.append(
                    {
                        "unit_id": unit["unit_id"],
                        "marker": marker,
                        "state": "matched"
                        if len(matches) == 1
                        else "ambiguous"
                        if matches
                        else "missing",
                        "matches": matches,
                    }
                )
        questions.append(
            {
                "question_id": qid,
                "task": question.get("task"),
                "inputs": question.get("inputs", []),
                "outputs": question.get("outputs", []),
                "source_path": model_path,
                "model_source_stale": model_stale,
                "models": models,
                "validation_obligations": obligations,
                "executed_outputs": [
                    row for row in outputs if row["question_id"] == qid
                ],
                "registered_frozen_results": [
                    row for row in results if row.get("question_id") == qid
                ],
                "writer_claims": [
                    row
                    for row in package.get("claims", [])
                    if row.get("claim_id") in claim_ids
                ]
                if not package_errors
                else [],
                "writer_eligibility": "current_package"
                if not package_errors
                else "unverified",
                "writer_limits": package_errors,
                "argument_units": units,
                "paper_locations": locations,
            }
        )
    spine = build_writing_spine(plan, package or None) if plan.get("sections") else None
    return {
        "ok": not errors,
        "projection": "question_workbench",
        "read_only": True,
        "run_id": state.run_id,
        "questions": questions,
        "errors": errors,
        "writing_spine": spine,
        "paper_binding": paper_binding,
        "source_paths": {
            "model_contract": model_path,
            "paper_plan": plan_path,
            "frozen_results": frozen_path,
            "writer_package": package_path,
        },
        "boundary": "Question projection does not grant Gate authority or evaluate mathematical/paper quality.",
    }
