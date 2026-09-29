"""Canonical v2 gate runtime evaluation and thin checker dispatch."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent / "qa"
sys.path.insert(0, str(SCRIPT_DIR.parent))

from _common import child_env, confirmed_checkpoints, human_confirmed_checkpoints, load_structured, rel_path, resolve_path, sha256_file  # noqa: E402
from artifact_dag_projector import project_artifact_dag  # noqa: E402
from qa.smoke_coverage import smoke_coverage_errors  # noqa: E402

def _v2_root_artifacts(state: Any, role: str) -> list[tuple[dict[str, Any], Path]]:
    """Return canonical DAG nodes for a role; manifest artifacts are not read."""

    dag_path = state.root_path("artifact_dag")
    if dag_path is None or not dag_path.is_file():
        return []
    try:
        dag = load_structured(dag_path)
    except (OSError, ValueError, TypeError):
        return []
    nodes = dag.get("nodes", []) if isinstance(dag, dict) else []
    result: list[tuple[dict[str, Any], Path]] = []
    for node in nodes if isinstance(nodes, list) else []:
        if isinstance(node, dict) and node.get("role") == role and isinstance(node.get("path"), str):
            result.append((node, resolve_path(node["path"], state.root).resolve()))
    return result


def _v2_receipt_projection(state: Any) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]], list[str]]:
    errors: list[str] = []
    index_path = state.root_path("run_index")
    if index_path is None or not index_path.is_file():
        errors.append("v2 run_index root is missing")
        return None, {}, errors
    try:
        index = load_structured(index_path)
    except (OSError, ValueError, TypeError) as exc:
        errors.append(f"cannot read v2 run_index: {exc}")
        return None, {}, errors
    if not isinstance(index, dict) or index.get("schema_version") != "2.0" or index.get("projection") != "receipt_selection":
        errors.append("run_index must be the v2 receipt_selection projection")
        return None, {}, errors
    rows = index.get("receipts")
    selection = index.get("selection")
    if not isinstance(rows, list) or not isinstance(selection, dict):
        errors.append("v2 run_index requires receipts and selection")
        return index, {}, errors
    selected_ids = selection.get("selected_receipt_ids")
    if not isinstance(selected_ids, list) or len(selected_ids) > 1:
        errors.append("run_index selection must contain at most one selected receipt")
        selected_ids = []
    receipts: dict[str, dict[str, Any]] = {}
    for row_index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("receipt_id"), str) or not isinstance(row.get("receipt_path"), str):
            errors.append(f"run_index.receipts[{row_index}] is not a valid receipt projection")
            continue
        receipt_id = row["receipt_id"]
        receipt_path = resolve_path(row["receipt_path"], state.root).resolve()
        if not receipt_path.is_file():
            errors.append(f"run_index receipt does not exist: {row['receipt_path']}")
            continue
        try:
            receipt = load_structured(receipt_path)
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"cannot read receipt {receipt_id}: {exc}")
            continue
        if not isinstance(receipt, dict) or receipt.get("schema_version") != "2.0":
            errors.append(f"run_index receipt {receipt_id} is not a v2 receipt")
            continue
        if receipt.get("receipt_id") != receipt_id:
            errors.append(f"receipt identity mismatch for {receipt_id}")
            continue
        if receipt.get("run_id") != row.get("run_id", receipt.get("run_id")):
            errors.append(f"run_index run_id mismatch for receipt {receipt_id}")
        # A copied exit_code in a projection is deliberately ignored.  The
        # process-captured receipt owns the execution outcome.
        receipts[receipt_id] = receipt
    projected_selected = {str(row.get("receipt_id")) for row in rows if isinstance(row, dict) and row.get("selected") is True}
    declared_selected = {str(value) for value in selected_ids}
    if projected_selected != declared_selected:
        errors.append("run_index selected flags do not match selection.selected_receipt_ids")
    return index, receipts, errors


def _v2_profile_errors(state: Any, *, require_verified: bool = False) -> list[str]:
    profile = state.profile
    errors: list[str] = []
    if profile.get("schema_version") != "2.0":
        errors.append("standalone competition profile must be schema_version=2.0")
    if require_verified and profile.get("status") != "verified":
        errors.append("submission profile must have status=verified; seed/unresolved profiles are not official rules")
    rules = profile.get("official_rules")
    endpoints = profile.get("official_submission_endpoints")
    submission = profile.get("submission")
    if not isinstance(rules, list) or not rules:
        errors.append("canonical competition profile requires at least one official_rules snapshot")
    if not isinstance(endpoints, list) or not endpoints:
        errors.append("canonical competition profile requires at least one official_submission_endpoint")
    if require_verified:
        if not isinstance(submission, dict):
            errors.append("canonical competition profile has no submission rules")
        else:
            required_submission_keys = (
                "paper_extensions",
                "max_paper_bytes",
                "max_pages",
                "max_pages_excludes_ai_report",
                "page_count_scope",
                "support_policy",
                "max_support_bytes",
                "ai_disclosure_policy",
                "ai_disclosure_format",
                "ai_manual_checks",
                "required_manual_checks",
            )
            for key in required_submission_keys:
                if key not in submission:
                    errors.append(f"canonical submission rule {key} is missing; do not guess an official limit or policy")
                    continue
                value = submission.get(key)
                # Nullable size/page limits are explicit declarations of no
                # limit.  Missing keys are unresolved; they are not equivalent
                # to null and must block S1/F1 promotion.
                if key not in {"max_paper_bytes", "max_pages", "max_support_bytes"} and (
                    value in (None, "", []) or (isinstance(value, list) and not value)
                ):
                    errors.append(f"canonical submission rule {key} is empty")
    return errors


_V2_ROLE_ALIASES: dict[str, tuple[str, ...]] = {
    "model_contract": ("model_contract", "model"),
    "implementation_map": ("implementation_map",),
    "evidence_registry": ("evidence_registry", "evidence"),
    "paper_plan": ("paper_plan",),
    "frozen_results": ("frozen_results", "freeze"),
    "abstract": ("abstract", "abstract_text", "paper_abstract"),
    "paper": ("paper", "paper_body", "draft", "paper_source", "latex"),
    "conclusion": ("conclusion", "conclusion_text", "paper_conclusion"),
    "writer_package": ("writer_package",),
    "pdf": ("final_pdf", "pdf"),
    "pdf_source": ("pdf_source", "paper_source", "tex", "latex"),
    "presentation_contract": ("presentation_contract",),
    "tex": ("tex", "latex", "paper_source"),
    "bib": ("bib", "bibliography"),
    "support": ("support", "support_file", "support_package"),
    "ai_disclosure": ("ai_disclosure", "ai_report"),
}


def _v2_dag_nodes(state: Any) -> list[dict[str, Any]]:
    dag_path = state.root_path("artifact_dag")
    if dag_path is None or not dag_path.is_file():
        return []
    try:
        dag = load_structured(dag_path)
    except (OSError, ValueError, TypeError):
        return []
    nodes = dag.get("nodes", []) if isinstance(dag, dict) else []
    return [node for node in nodes if isinstance(node, dict) and isinstance(node.get("path"), str)] if isinstance(nodes, list) else []


def _v2_role_entries(state: Any, role: str) -> list[tuple[dict[str, Any], Path]]:
    """Resolve checker inputs from canonical roots/DAG roles only.

    The DAG is a projector, not a new registry: this helper only reads its
    already-declared nodes and never creates or mutates identity records.
    """

    aliases = set(_V2_ROLE_ALIASES.get(role, (role,)))
    entries: list[tuple[dict[str, Any], Path]] = []
    root_path = state.root_path(role)
    if root_path is not None:
        entries.append(({"role": role, "path": rel_path(root_path, state.root), "metadata": {}}, root_path.resolve()))
    for node in _v2_dag_nodes(state):
        if node.get("role") not in aliases:
            continue
        path = resolve_path(str(node["path"]), state.root).resolve()
        if not any(existing_path == path for _, existing_path in entries):
            entries.append((node, path))
    return entries


def _v2_role_path(state: Any, role: str) -> tuple[dict[str, Any] | None, Path | None]:
    entries = _v2_role_entries(state, role)
    if not entries:
        return None, None
    for node, path in entries:
        if path.is_file():
            return node, path
    return entries[0]


def _v2_require_role(
    state: Any,
    role: str,
    errors: list[str],
    *,
    required: bool = True,
) -> tuple[dict[str, Any] | None, Path | None]:
    node, path = _v2_role_path(state, role)
    if node is None or path is None:
        if required:
            errors.append(f"{role} canonical artifact is not declared in roots or artifact DAG")
        return node, path
    if required and not path.is_file():
        errors.append(f"{role} canonical artifact does not exist: {rel_path(path, state.root)}")
    return node, path


def _v2_run_checker(
    state: Any,
    label: str,
    checker_args: list[str],
    evidence: dict[str, Any],
    errors: list[str],
    *,
    report_path: Path | None = None,
) -> bool:
    """Dispatch one existing checker and preserve its raw failure evidence."""

    result = subprocess.run(
        [sys.executable, *checker_args],
        cwd=str(state.root),
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=child_env(),
        check=False,
    )
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    try:
        report = json.loads(stdout)
    except json.JSONDecodeError:
        report = {
            "ok": False,
            "errors": [
                f"checker did not emit a JSON report (exit_code={result.returncode})",
                *(line for line in (stdout.strip(), stderr.strip()) if line),
            ],
        }
    if report_path is not None and report_path.is_file():
        try:
            generated = load_structured(report_path)
        except (OSError, ValueError, TypeError):
            generated = None
        if isinstance(generated, dict):
            report = generated
    checker_record = {
        "label": label,
        "exit_code": result.returncode,
        "report": report,
        "stdout": stdout,
        "stderr": stderr,
    }
    evidence.setdefault("checkers", []).append(checker_record)
    ok = result.returncode == 0 and isinstance(report, dict) and report.get("ok") is True
    if not ok:
        reported = report.get("errors") if isinstance(report, dict) else None
        if isinstance(reported, list) and reported:
            errors.extend(f"{label}: {message}" for message in reported)
        else:
            nested: list[str] = []
            checks = report.get("checks") if isinstance(report, dict) else None
            if isinstance(checks, list):
                for check in checks:
                    if not isinstance(check, dict) or check.get("ok") is True:
                        continue
                    check_label = str(check.get("label") or "check")
                    child_report = check.get("report")
                    child_errors = child_report.get("errors") if isinstance(child_report, dict) else None
                    if isinstance(child_errors, list) and child_errors:
                        nested.extend(f"{check_label}: {message}" for message in child_errors)
                    else:
                        nested.append(f"{check_label} failed")
            if nested:
                errors.extend(f"{label}: {message}" for message in nested)
            else:
                errors.append(f"{label}: checker exited {result.returncode}; raw output retained in generated report")
    return ok


def _v2_contract_paths(state: Any, errors: list[str]) -> dict[str, Path] | None:
    paths: dict[str, Path] = {}
    for role in ("model_contract", "frozen_results", "evidence_registry", "paper_plan"):
        _, path = _v2_require_role(state, role, errors)
        if path is None or not path.is_file():
            continue
        paths[role] = path
    return paths if len(paths) == 4 else None


def _v2_dispatch_contracts(state: Any, evidence: dict[str, Any], errors: list[str]) -> bool:
    paths = _v2_contract_paths(state, errors)
    if paths is None:
        return False
    return _v2_run_checker(
        state,
        "validate_contracts",
        [
            str(SCRIPT_DIR / "validate_contracts.py"),
            "--project-root", str(state.root),
            "--model-contract", str(paths["model_contract"]),
            "--run-manifest", str(state.manifest_path),
            "--frozen-results", str(paths["frozen_results"]),
            "--evidence-registry", str(paths["evidence_registry"]),
            "--paper-plan", str(paths["paper_plan"]),
            "--strict",
        ],
        evidence,
        errors,
    )


def _v2_io_digest_errors(
    receipt: dict[str, Any],
    *,
    root: Path,
    owner: str,
    require_hash: bool,
    fields: tuple[str, ...] = ("input_refs", "output_refs"),
) -> list[str]:
    errors: list[str] = []
    if not require_hash:
        return errors
    for field in fields:
        refs = receipt.get(field)
        if not isinstance(refs, list):
            errors.append(f"{owner}.{field} must be an array")
            continue
        for index, ref in enumerate(refs):
            if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
                errors.append(f"{owner}.{field}[{index}] must contain a path")
                continue
            expected = ref.get("sha256")
            if not isinstance(expected, str):
                errors.append(f"{owner}.{field}[{index}] is missing its SHA-256 binding")
                continue
            path = resolve_path(ref["path"], root).resolve()
            if not path.is_file():
                errors.append(f"{owner}.{field}[{index}] does not exist: {ref['path']}")
            elif sha256_file(path) != expected:
                errors.append(f"{owner}.{field}[{index}] SHA-256 drift: {ref['path']}")
    return errors


def _v2_receipt_success(receipt: dict[str, Any]) -> bool:
    if receipt.get("exit_code") != 0:
        return False
    metadata = receipt.get("metadata")
    return not (isinstance(metadata, dict) and metadata.get("outcome") == "failed")


def _v2_require_dag_digests(state: Any, roles: tuple[str, ...], errors: list[str]) -> None:
    """Require and recompute the one declared SHA-256 owner for risky roles.

    The DAG owns an artifact digest only when ``digest_owner=artifact_dag``.
    A command-produced artifact may instead point at its immutable producer
    receipt.  In that case the DAG keeps identity/dependency metadata and does
    not copy the digest.  Declaring both owners is a blocking contract error.
    """

    nodes = _v2_dag_nodes(state)
    receipts: dict[str, dict[str, Any]] | None = None

    def receipt_digest(node: dict[str, Any]) -> tuple[str | None, str | None]:
        nonlocal receipts
        if receipts is None:
            _, receipts, receipt_errors = _v2_receipt_projection(state)
            errors.extend(receipt_errors)
        receipt_id = node.get("producer_receipt_id")
        owner = str(node.get("digest_owner") or "")
        if not isinstance(receipt_id, str) and owner.startswith("command_receipt:"):
            receipt_id = owner.split(":", 1)[1]
        if not isinstance(receipt_id, str) or not receipt_id:
            return None, "has command_receipt ownership but no producer_receipt_id"
        if receipts is not None:
            seen_lineage = set()
            while True:
                successor = next(
                    (
                        str(r["receipt_id"]) for r in receipts.values()
                        if isinstance(r, dict)
                        and r.get("stage") == "freeze"
                        and (
                            r.get("supersedes_receipt_id") == receipt_id
                            or (isinstance(r.get("metadata"), dict) and r["metadata"].get("supersedes_receipt_id") == receipt_id)
                        )
                        and _v2_receipt_success(r)
                    ),
                    None,
                )
                if not successor or successor in seen_lineage:
                    break
                seen_lineage.add(successor)
                receipt_id = successor
        receipt = receipts.get(receipt_id) if receipts is not None else None
        if receipt is None:
            return None, f"references missing digest owner receipt {receipt_id}"
        artifact_id = node.get("artifact_id")
        raw_path = node.get("path")
        matches = [
            ref for ref in receipt.get("output_refs", [])
            if isinstance(ref, dict)
            and (
                (isinstance(artifact_id, str) and ref.get("artifact_id") == artifact_id)
                or (isinstance(raw_path, str) and ref.get("path") == raw_path)
            )
        ]
        if len(matches) != 1:
            return None, f"does not resolve to exactly one output in owner receipt {receipt_id}"
        ref = matches[0]
        if ref.get("digest_owner") != "command_receipt":
            return None, f"owner receipt {receipt_id} does not declare command_receipt ownership"
        expected = ref.get("sha256")
        if not isinstance(expected, str):
            return None, f"owner receipt {receipt_id} has no SHA-256 binding"
        return expected, None

    for role in roles:
        aliases = set(_V2_ROLE_ALIASES.get(role, (role,)))
        matches = [node for node in nodes if node.get("role") in aliases]
        if not matches:
            errors.append(f"{role} requires a canonical artifact and digest owner")
            continue
        for node in matches:
            raw_path = node.get("path")
            path = resolve_path(str(raw_path), state.root).resolve() if isinstance(raw_path, str) else None
            owner = str(node.get("digest_owner") or "")
            expected: str | None
            if owner == "artifact_dag":
                expected = node.get("sha256") or node.get("digest")
                producer_receipt_id = node.get("producer_receipt_id")
                if isinstance(producer_receipt_id, str):
                    receipt_expected, _ = receipt_digest({**node, "digest_owner": f"command_receipt:{producer_receipt_id}"})
                    if isinstance(receipt_expected, str):
                        errors.append(
                            f"{role} artifact {node.get('artifact_id')} has multiple digest owners: artifact_dag and command_receipt:{producer_receipt_id}"
                        )
                if not isinstance(expected, str):
                    errors.append(f"{role} artifact {node.get('artifact_id')} is missing its DAG-owned SHA-256")
                    continue
                if node.get("digest_algorithm") != "sha256":
                    errors.append(f"{role} artifact {node.get('artifact_id')} must declare digest_algorithm=sha256")
            elif owner == "command_receipt" or owner.startswith("command_receipt:"):
                if isinstance(node.get("sha256") or node.get("digest"), str):
                    errors.append(
                        f"{role} artifact {node.get('artifact_id')} copies a receipt-owned digest into the DAG"
                    )
                expected, owner_error = receipt_digest(node)
                if owner_error is not None:
                    errors.append(f"{role} artifact {node.get('artifact_id')} {owner_error}")
                    continue
            else:
                errors.append(f"{role} artifact {node.get('artifact_id')} has unsupported digest owner {owner!r}")
                continue
            if path is None or not path.is_file():
                errors.append(f"{role} artifact does not exist: {raw_path}")
            elif sha256_file(path) != expected:
                errors.append(f"{role} artifact SHA-256 drift: {raw_path}")


def _v2_registry_entry_scripts(errors: list[str]) -> dict[str, str]:
    """Resolve M1's registry-declared checker entrypoints (fail closed).

    The verifier declarations own the path of every check M1 dispatches; a
    registry that cannot load, or a declaration that went missing, is an M1
    error rather than a silently skipped check.
    """

    from verifiers import registry as verifier_registry

    try:
        loaded = verifier_registry.load_registry()
    except (OSError, ValueError, TypeError) as exc:
        errors.append(f"verifier registry: {exc}")
        return {}
    scripts: dict[str, str] = {}
    for verifier_id in ("unit-consistency", "artifact-freshness"):
        declaration = loaded.get(verifier_id)
        script = declaration.get("entrypoint", {}).get("script") if isinstance(declaration, dict) else None
        if not isinstance(script, str) or not script:
            errors.append(f"verifier registry: no declaration for {verifier_id}")
            continue
        resolved = (SCRIPT_DIR.parent.parent / script).resolve()
        scripts[verifier_id] = str(resolved)
    return scripts


def _v2_checkpoint_required(state: Any, capabilities: Any, gate: str, errors: list[str]) -> None:
    if not capabilities.require_human_checkpoints:
        return
    rows = state.manifest.get("human_checkpoints", [])
    if human_confirmed_checkpoints(rows, gate):
        return
    if confirmed_checkpoints(rows, gate):
        errors.append(
            f"{gate.upper()} has only agent-recorded checkpoints; a human must confirm it with "
            f"`harness checkpoint approve {gate} --role <role> --decision approve`"
        )
        return
    errors.append(f"{gate.upper()} requires a confirmed {gate.upper()} human checkpoint")


def _v2_run_safety_checker(state: Any, capabilities: Any, evidence: dict[str, Any], errors: list[str]) -> None:
    if not capabilities.require_contest_safety:
        return
    _v2_run_checker(
        state,
        "contest_safety",
        [
            str(SCRIPT_DIR / "check_contest_safety.py"),
            "--project-root", str(state.root),
            "--manifest", str(state.manifest_path),
            "--strict",
        ],
        evidence,
        errors,
    )


def _v2_gate_m1(state: Any, capabilities: Any, errors: list[str], evidence: dict[str, Any]) -> None:
    errors.extend(_v2_profile_errors(state))
    registry_scripts = _v2_registry_entry_scripts(errors)
    _, model_contract = _v2_require_role(state, "model_contract", errors)
    _, evidence_registry = _v2_require_role(state, "evidence_registry", errors)
    if model_contract is not None and evidence_registry is not None and model_contract.is_file() and evidence_registry.is_file():
        modeling_args = [
            str(SCRIPT_DIR / "check_modeling_plan.py"),
            "--project-root", str(state.root),
            "--model-contract", str(model_contract),
            "--evidence-registry", str(evidence_registry),
            "--strict",
        ]
        if state.preset != "sprint":
            modeling_args.append("--formal")
        if capabilities.require_scope_contract:
            modeling_args.append("--require-scope-contract")
        _v2_run_checker(state, "check_modeling_plan", modeling_args, evidence, errors)
    units_script = registry_scripts.get("unit-consistency")
    if model_contract is not None and model_contract.is_file():
        if units_script is not None:
            _v2_run_checker(
                state,
                "check_units",
                [
                    units_script,
                    "--project-root", str(state.root),
                    "--model-contract", str(model_contract),
                    "--strict",
                ],
                evidence,
                errors,
            )
    dag_path = state.root_path("artifact_dag")
    dag_script = registry_scripts.get("artifact-freshness")
    if dag_path is not None and dag_path.is_file():
        if dag_script is not None:
            _v2_run_checker(
                state,
                "check_artifact_dag",
                [dag_script, "--project-root", str(state.root), "--dag", str(dag_path), "--strict"],
                evidence,
                errors,
            )
    _v2_checkpoint_required(state, capabilities, "m1", errors)
    _v2_run_safety_checker(state, capabilities, evidence, errors)
    evidence["capabilities"] = state.capabilities.to_dict()

def _v2_gate_p1(state: Any, capabilities: Any, errors: list[str], evidence: dict[str, Any]) -> None:
    _, receipts, receipt_errors = _v2_receipt_projection(state)
    errors.extend(receipt_errors)
    smoke = [
        row for row in receipts.values()
        if row.get("stage") == "smoke"
        and row.get("run_id") == state.run_id
        and _v2_receipt_success(row)
    ]
    if not smoke:
        errors.append("P1 requires at least one successful process-captured smoke receipt")
    evidence["smoke_receipt_ids"] = [row.get("receipt_id") for row in smoke]
    if capabilities.require_full_evidence_chain and smoke:
        # Enhanced P1: at least one successful smoke receipt must have
        # exercised the contracted math. Earlier exploratory receipts may
        # remain in history; coverage stays bound to the qualifying receipt.
        contract_path = state.root_path("model_contract")
        contract = None
        if contract_path is not None and contract_path.is_file():
            try:
                contract = load_structured(contract_path)
            except (OSError, ValueError, TypeError) as exc:
                errors.append(f"cannot inspect model_contract for P1 coverage: {exc}")
        coverage_failures: list[tuple[str, list[str]]] = []
        qualified_ids: list[str] = []
        for receipt in smoke:
            metadata = receipt.get("metadata") if isinstance(receipt.get("metadata"), dict) else {}
            coverage_errors = smoke_coverage_errors(metadata.get("smoke_coverage"), contract)
            receipt_id = str(receipt.get("receipt_id"))
            if coverage_errors:
                coverage_failures.append((receipt_id, coverage_errors))
            else:
                qualified_ids.append(receipt_id)
        if not qualified_ids:
            errors.append("P1 has no successful smoke receipt with complete smoke_coverage")
            for receipt_id, messages in coverage_failures:
                errors.extend(f"P1 receipt {receipt_id}: {message}" for message in messages)
        evidence["smoke_coverage_receipt_ids"] = qualified_ids

def _v2_resolve_active_freeze_lineage(
    freeze: list[dict[str, Any]],
    run_id: str,
    errors: list[str],
) -> list[dict[str, Any]]:
    if not freeze:
        errors.append("P2 requires exactly one successful freeze receipt")
        return []
    by_id = {str(row.get("receipt_id")): row for row in freeze if row.get("receipt_id")}
    superseded_by: dict[str, str] = {}
    lineage_errors: list[str] = []

    for row in freeze:
        receipt_id = str(row.get("receipt_id"))
        parent_id = row.get("supersedes_receipt_id") or (
            row.get("metadata", {}).get("supersedes_receipt_id")
            if isinstance(row.get("metadata"), dict) else None
        )
        if not parent_id:
            continue
        parent_id = str(parent_id)
        if parent_id == receipt_id:
            lineage_errors.append(f"freeze receipt {receipt_id} cannot supersede itself")
            continue
        if parent_id not in by_id:
            lineage_errors.append(
                f"freeze receipt {receipt_id} supersedes unknown or unsuccessful freeze receipt {parent_id}"
            )
            continue
        parent_gen = by_id[parent_id].get("generation")
        curr_gen = row.get("generation")
        if parent_gen is not None and curr_gen is not None:
            try:
                if int(curr_gen) <= int(parent_gen):
                    lineage_errors.append(
                        f"freeze receipt {receipt_id} generation {curr_gen} is not strictly greater than predecessor generation {parent_gen}"
                    )
            except (ValueError, TypeError):
                pass
        if parent_id in superseded_by:
            lineage_errors.append(
                f"conflicting supersession: freeze receipts {superseded_by[parent_id]} and {receipt_id} both supersede {parent_id}"
            )
            continue
        superseded_by[parent_id] = receipt_id

    # Check for cycles
    for start_id in by_id:
        visited = set()
        curr = start_id
        while curr in superseded_by:
            if curr in visited:
                lineage_errors.append(f"cycle detected in freeze receipt supersession lineage at {curr}")
                break
            visited.add(curr)
            curr = superseded_by[curr]

    if lineage_errors:
        errors.extend(lineage_errors)
        return []

    active = [row for row in freeze if str(row.get("receipt_id")) not in superseded_by]
    if len(active) != 1:
        errors.append(f"P2 requires exactly one active freeze lineage, found {len(active)}")
        return []
    return active


def _v2_gate_p2(state: Any, capabilities: Any, errors: list[str], evidence: dict[str, Any]) -> None:
    index, receipts, receipt_errors = _v2_receipt_projection(state)
    errors.extend(receipt_errors)
    selected_ids = index.get("selection", {}).get("selected_receipt_ids", []) if isinstance(index, dict) else []
    if not isinstance(selected_ids, list) or len(selected_ids) != 1:
        errors.append("P2 requires exactly one selected receipt in the run_index projection")
        selected_ids = selected_ids if isinstance(selected_ids, list) else []
    selected = [receipts[str(value)] for value in selected_ids if str(value) in receipts]
    full = [
        row for row in selected
        if row.get("stage") == "full"
        and row.get("run_id") == state.run_id
        and _v2_receipt_success(row)
    ]
    if len(full) != 1:
        errors.append("P2 requires exactly one selected successful full receipt")
    if full:
        selected_receipt = full[0]
        if selected_receipt.get("selection", {}).get("selected") is not True:
            errors.append("P2 selected full receipt must carry its own selected execution fact")
        errors.extend(
            _v2_io_digest_errors(
                selected_receipt,
                root=state.root,
                owner=f"selected receipt {selected_receipt.get('receipt_id')}",
                require_hash=bool(capabilities.require_selected_io_hash),
            )
        )
    all_freeze = [
        row for row in receipts.values()
        if row.get("stage") == "freeze"
        and row.get("run_id") == state.run_id
        and _v2_receipt_success(row)
    ]
    freeze = _v2_resolve_active_freeze_lineage(all_freeze, state.run_id, errors)
    frozen_nodes = _v2_root_artifacts(state, "frozen_results")
    if len(frozen_nodes) != 1:
        errors.append("P2 requires exactly one canonical frozen_results artifact")
    frozen_value: dict[str, Any] = {}
    if len(frozen_nodes) == 1:
        _, frozen_path = frozen_nodes[0]
        if not frozen_path.is_file():
            errors.append("canonical frozen_results artifact does not exist")
        else:
            try:
                loaded = load_structured(frozen_path)
                frozen_value = loaded if isinstance(loaded, dict) else {}
            except (OSError, ValueError, TypeError) as exc:
                errors.append(f"cannot inspect frozen_results: {exc}")
    if frozen_value.get("status") != "frozen":
        errors.append("P2 requires frozen_results.status=frozen")
    if frozen_value.get("claimable") is not True or frozen_value.get("validation_verdict") != "PASS":
        errors.append("P2 requires frozen_results.claimable=true and validation_verdict=PASS")
    if full and frozen_value.get("run_id") != full[0].get("run_id"):
        errors.append("frozen_results.run_id does not match selected full receipt")
    if full:
        expected_receipt = f"receipt:{full[0].get('receipt_id')}"
        if frozen_value.get("command") != expected_receipt:
            errors.append("frozen_results is not bound to the selected full receipt")
    if len(frozen_nodes) == 1 and len(freeze) == 1:
        frozen_node, frozen_path = frozen_nodes[0]
        matching = [
            ref for ref in freeze[0].get("output_refs", [])
            if isinstance(ref, dict)
            and isinstance(ref.get("path"), str)
            and resolve_path(ref["path"], state.root).resolve() == frozen_path.resolve()
        ]
        if len(matching) != 1:
            errors.append("freeze receipt must bind exactly one canonical frozen_results path")
        else:
            expected = matching[0].get("sha256")
            if capabilities.require_frozen_result_hash:
                if not isinstance(expected, str):
                    errors.append("freeze receipt canonical frozen_results output is missing its SHA-256 binding")
                elif frozen_path.is_file() and sha256_file(frozen_path) != expected:
                    errors.append("freeze receipt canonical frozen_results SHA-256 drift")
            elif isinstance(expected, str) and frozen_path.is_file() and sha256_file(frozen_path) != expected:
                errors.append("freeze receipt canonical frozen_results SHA-256 drift")
    if capabilities.require_frozen_result_hash:
        _v2_require_dag_digests(state, ("frozen_results",), errors)
    if capabilities.require_full_evidence_chain:
        _, implementation_map = _v2_require_role(state, "implementation_map", errors)
        _, model_contract = _v2_require_role(state, "model_contract", errors)
        if (
            implementation_map is not None
            and model_contract is not None
            and implementation_map.is_file()
            and model_contract.is_file()
        ):
            implementation_args = [
                str(SCRIPT_DIR / "check_implementation_map.py"),
                "--project-root", str(state.root),
                "--implementation-map", str(implementation_map),
                "--model-contract", str(model_contract),
                "--strict",
            ]
            if capabilities.require_strict_math:
                implementation_args.append("--require-objective-binding")
            _v2_run_checker(
                state,
                "check_implementation_map",
                implementation_args,
                evidence,
                errors,
            )
        if model_contract is not None and model_contract.is_file():
            _v2_run_checker(
                state,
                "check_units",
                [
                    str(SCRIPT_DIR / "check_units.py"),
                    "--project-root", str(state.root),
                    "--model-contract", str(model_contract),
                    "--strict",
                ],
                evidence,
                errors,
            )
    evidence["selected_full_receipt_ids"] = [row.get("receipt_id") for row in full]
    evidence["freeze_receipt_ids"] = [row.get("receipt_id") for row in all_freeze]
    evidence["active_freeze_receipt_ids"] = [row.get("receipt_id") for row in freeze]
    _v2_checkpoint_required(state, capabilities, "p2", errors)

def _v2_gate_w1(state: Any, capabilities: Any, errors: list[str], evidence: dict[str, Any]) -> None:
    frozen_nodes = _v2_root_artifacts(state, "frozen_results")
    if len(frozen_nodes) != 1 or not frozen_nodes[0][1].is_file():
        errors.append("W1 requires a current frozen_results artifact")
    else:
        try:
            frozen = load_structured(frozen_nodes[0][1])
            if not isinstance(frozen, dict) or frozen.get("claimable") is not True or frozen.get("status") != "frozen":
                errors.append("W1 requires a claimable frozen_results.status=frozen artifact")
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"cannot inspect frozen_results: {exc}")
    paths = _v2_contract_paths(state, errors)
    if paths is not None:
        _v2_run_checker(
            state,
            "check_paper_readiness",
            [
                str(SCRIPT_DIR / "check_paper_readiness.py"),
                "--project-root", str(state.root),
                "--paper-plan", str(paths["paper_plan"]),
                "--evidence-registry", str(paths["evidence_registry"]),
                "--minimum-stage", "technical_draft",
                "--strict",
            ],
            evidence,
            errors,
        )
        _v2_dispatch_contracts(state, evidence, errors)
    _v2_checkpoint_required(state, capabilities, "w1", errors)

def _v2_gate_w2(state: Any, capabilities: Any, errors: list[str], evidence: dict[str, Any]) -> None:
    dag_path = state.root_path("artifact_dag")
    if dag_path is None or not dag_path.is_file():
        errors.append("W2 requires the canonical artifact DAG")
    else:
        try:
            dag = load_structured(dag_path)
            if not isinstance(dag, dict) or dag.get("schema_version") != "2.0":
                errors.append("W2 artifact DAG must be v2")
            else:
                projection, dag_errors, events = project_artifact_dag(dag, project_root=state.root)
                errors.extend(dag_errors)
                if events:
                    errors.append("W2 artifact DAG has stale or invalidated artifacts")
                evidence["dag_freshness"] = {str(node.get("artifact_id")): node.get("freshness") for node in projection.get("nodes", []) if isinstance(node, dict)}
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"cannot inspect artifact DAG: {exc}")
    # W2 rechecks frozen truth from bytes/JSON rather than trusting an
    # upstream ``hash_verified`` or human status field.
    for _, frozen_path in _v2_root_artifacts(state, "frozen_results"):
        try:
            frozen = load_structured(frozen_path)
            if not isinstance(frozen, dict):
                raise ValueError("frozen_results must be an object")
            if frozen.get("results_sha256") != __import__("hashlib").sha256(
                __import__("json").dumps(frozen.get("results", []), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest():
                errors.append("W2 frozen_results.results_sha256 drift")
            for field in ("model_contract_snapshot", "source_snapshot", "input_snapshot", "code_snapshot", "validation_snapshot"):
                refs = frozen.get(field, []) if field.endswith("_snapshot") and field not in {"model_contract_snapshot", "source_snapshot"} else [frozen.get(field)]
                if not isinstance(refs, list):
                    refs = []
                for ref in refs:
                    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
                        continue
                    path = resolve_path(ref["path"], state.root).resolve()
                    if not path.is_file() or ref.get("sha256") != sha256_file(path):
                        errors.append(f"W2 frozen_results {field} SHA-256 drift: {ref.get('path')}")
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f"cannot recheck frozen_results evidence: {exc}")
    contract_paths = _v2_contract_paths(state, errors)
    required_roles = ("abstract", "paper", "conclusion")
    role_paths: dict[str, Path] = {}
    role_nodes: dict[str, dict[str, Any]] = {}
    for role in required_roles:
        node, path = _v2_require_role(state, role, errors)
        if node is not None and path is not None and path.is_file():
            role_nodes[role] = node
            role_paths[role] = path
    writer_node, writer_path = _v2_role_path(state, "writer_package")
    if capabilities.require_full_evidence_chain:
        if writer_node is None or writer_path is None or not writer_path.is_file():
            errors.append("W2 requires canonical writer_package for the selected capability profile")
        else:
            role_paths["writer_package"] = writer_path
    pdf_node, pdf_path = _v2_role_path(state, "pdf")
    pdf_source_node, pdf_source_path = _v2_role_path(state, "pdf_source")
    presentation_node, presentation_path = _v2_role_path(state, "presentation_contract")
    tex_node, tex_path = _v2_role_path(state, "tex")
    bib_node, bib_path = _v2_role_path(state, "bib")
    if capabilities.require_strict_math:
        if pdf_path is None or not pdf_path.is_file():
            errors.append("W2 strict math requires a canonical final PDF artifact")
        if pdf_source_path is None or not pdf_source_path.is_file():
            errors.append("W2 strict math requires a canonical PDF source artifact")
    if capabilities.require_verified_bibliography and (tex_path is None or bib_path is None):
        errors.append("W2 requires canonical tex and bib artifacts for verified bibliography")
    if capabilities.require_canonical_paper_evidence_hash:
        _v2_require_dag_digests(state, ("paper", "evidence_registry"), errors)
    if capabilities.require_final_pdf_hash:
        _v2_require_dag_digests(state, ("pdf",), errors)
    if contract_paths is not None and len(role_paths) >= 3:
        temp_output: Path | None = None
        try:
            handle, raw_temp = tempfile.mkstemp(prefix="v2-deterministic-qa-", suffix=".json")
            os.close(handle)
            Path(raw_temp).unlink(missing_ok=True)
            temp_output = Path(raw_temp)
            deterministic_args = [
                str(SCRIPT_DIR / "run_deterministic_qa.py"),
                "--project-root", str(state.root),
                "--model-contract", str(contract_paths["model_contract"]),
                "--run-manifest", str(state.manifest_path),
                "--frozen-results", str(contract_paths["frozen_results"]),
                "--evidence-registry", str(contract_paths["evidence_registry"]),
                "--paper-plan", str(contract_paths["paper_plan"]),
                "--abstract", str(role_paths["abstract"]),
                "--paper", str(role_paths["paper"]),
                "--conclusion", str(role_paths["conclusion"]),
                "--output", str(temp_output),
                "--force",
                "--profile", "strict" if capabilities.require_strict_math else ("enhanced" if capabilities.require_full_evidence_chain else "baseline"),
            ]
            if "writer_package" in role_paths:
                deterministic_args.extend(["--writer-package", str(role_paths["writer_package"])])
            if dag_path.is_file():
                deterministic_args.extend(["--artifact-dag", str(dag_path), "--require-canonical-source"])
            if capabilities.require_full_evidence_chain:
                deterministic_args.extend(["--require-first-draft-coverage", "--require-math-writing-coverage", "--require-derivation-integrity"])
            if capabilities.require_scope_contract:
                deterministic_args.append("--require-scope-contract")
            if capabilities.require_formula_replay:
                deterministic_args.append("--require-formula-replay")
            if capabilities.require_figure_result_lineage:
                deterministic_args.append("--require-figure-lineage")
            if capabilities.require_strict_math:
                deterministic_args.extend([
                    "--require-replay-bindings", "--require-pdf-math-consistency",
                    "--require-objective-contract", "--require-inference-role-consistency",
                ])
                if pdf_path is not None and pdf_path.is_file():
                    deterministic_args.extend(["--pdf", str(pdf_path)])
                if pdf_source_path is not None and pdf_source_path.is_file():
                    deterministic_args.extend(["--pdf-source", str(pdf_source_path)])
            if capabilities.require_strict_editorial:
                deterministic_args.append("--style-check")
            if presentation_path is not None and presentation_path.is_file():
                deterministic_args.extend(["--presentation-contract", str(presentation_path)])
            if tex_path is not None and bib_path is not None and tex_path.is_file() and bib_path.is_file():
                deterministic_args.extend(["--tex", str(tex_path), "--bib", str(bib_path)])
                if capabilities.require_verified_bibliography:
                    deterministic_args.append("--require-verified-bibliography")
            _v2_run_checker(
                state,
                "run_deterministic_qa",
                deterministic_args,
                evidence,
                errors,
                report_path=temp_output,
            )
        finally:
            if temp_output is not None:
                try:
                    temp_output.unlink(missing_ok=True)
                except OSError:
                    pass
    _v2_dispatch_contracts(state, evidence, errors)
    # Review Execution Plane: W2 consumes real review reports only. The
    # manifest stores no review status, so nothing is self-reported here.
    try:
        from qa.review_evidence import evaluate_w2_review  # type: ignore

        review_summary, review_errors = evaluate_w2_review(state.root, state.preset, run_id=state.run_id)
    except ImportError:  # pragma: no cover - direct-script import edge
        from review_evidence import evaluate_w2_review  # type: ignore

        review_summary, review_errors = evaluate_w2_review(state.root, state.preset, run_id=state.run_id)
    errors.extend(review_errors)
    evidence["review"] = review_summary
    _v2_checkpoint_required(state, capabilities, "w2", errors)
    _v2_run_safety_checker(state, capabilities, evidence, errors)

def _v2_gate_s1(state: Any, capabilities: Any, errors: list[str], evidence: dict[str, Any]) -> None:
    errors.extend(_v2_profile_errors(state, require_verified=True))
    if state.preset != "submission":
        errors.append("S1 requires preset=submission")
    if capabilities.require_final_pdf_hash:
        # check_submission also records the PDF bytes, but the canonical
        # digest owner remains the DAG.  Recompute it here so a stale or
        # hand-edited final_pdf node cannot make S1 appear current.
        _v2_require_dag_digests(state, ("pdf",), errors)
    _v2_checkpoint_required(state, capabilities, "s1", errors)
    paper_node, paper_path = _v2_require_role(state, "pdf", errors)
    if paper_path is not None and paper_path.is_file():
        page_meta = paper_node.get("metadata", {}) if isinstance(paper_node, dict) else {}
        if not isinstance(page_meta, dict):
            page_meta = {}
        report_handle, report_temp = tempfile.mkstemp(prefix="v2-s1-", suffix=".json")
        os.close(report_handle)
        Path(report_temp).unlink(missing_ok=True)
        report_path = Path(report_temp)
        submission_args = [
            str(SCRIPT_DIR / "check_submission.py"),
            "--project-root", str(state.root),
            "--run-manifest", str(state.manifest_path),
            "--paper", str(paper_path),
            "--output", str(report_path),
            "--force",
        ]
        pages = page_meta.get("pages", page_meta.get("total_pages"))
        page_method = page_meta.get("page_count_method", page_meta.get("method"))
        if isinstance(pages, int):
            submission_args.extend(["--paper-pages", str(pages)])
        if isinstance(page_method, str):
            submission_args.extend(["--page-count-method", page_method])
        ai_pages = page_meta.get("ai_report_pages")
        if isinstance(ai_pages, int):
            submission_args.extend(["--ai-report-pages", str(ai_pages)])
        for _, support_path in _v2_role_entries(state, "support"):
            if support_path.is_file():
                submission_args.extend(["--support", str(support_path)])
        _, ai_path = _v2_role_path(state, "ai_disclosure")
        if ai_path is not None and ai_path.is_file():
            submission_args.extend(["--ai-disclosure", str(ai_path)])
        try:
            _v2_run_checker(
                state,
                "check_submission",
                submission_args,
                evidence,
                errors,
                report_path=report_path,
            )
        finally:
            try:
                report_path.unlink(missing_ok=True)
            except OSError:
                pass
    submission_path = state.root_path("submission_manifest")
    if submission_path is not None:
        if not submission_path.is_file():
            errors.append("S1 submission_manifest root does not exist")
        else:
            _v2_run_checker(
                state,
                "check_submission_manifest",
                [str(SCRIPT_DIR / "check_submission_manifest.py"), "--project-root", str(state.root), "--submission-manifest", str(submission_path)],
                evidence,
                errors,
            )
    _v2_run_safety_checker(state, capabilities, evidence, errors)
    evidence["profile_status"] = state.profile.get("status")

_V2_GATE_BRANCHES = {
    "m1": _v2_gate_m1,
    "p1": _v2_gate_p1,
    "p2": _v2_gate_p2,
    "w1": _v2_gate_w1,
    "w2": _v2_gate_w2,
    "s1": _v2_gate_s1,
}


def _v2_gate(state: Any, gate: str) -> tuple[bool, list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    evidence: dict[str, Any] = {"manifest": rel_path(state.manifest_path, state.root), "profile": rel_path(state.profile_path, state.root)}
    branch = _V2_GATE_BRANCHES.get(gate)
    if branch is None:
        errors.append(f"unsupported v2 gate: {gate}")
    else:
        branch(state, state.capabilities, errors, evidence)
    return not errors, errors, warnings, evidence
