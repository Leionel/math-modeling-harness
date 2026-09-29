#!/usr/bin/env python3
"""Execute the Review Execution Plane: QA, bundle, reviewers, evidence.

``harness review`` dispatches here.  This orchestrator is deterministic: it
runs the existing deterministic QA, materializes the allow-listed review
bundle, routes each required perspective to a reviewer execution path, and
validates the produced reports against the review contract.  It never writes
semantic findings itself and never edits author artifacts, frozen results, or
Gate truth.  Its only control-plane mutation is a producer-owned AI usage
record when an explicitly declared AI backend is actually invoked.  Review reports are generated evidence under
``reports/review/`` and are optionally registered as DAG nodes with
``role=review_report``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from _common import append_ai_usage_record, child_env, load_structured, rel_path, resolve_path, sha256_file, write_json  # noqa: E402
from runtime_state import RuntimeStateError, load_runtime_state  # noqa: E402
from project_layout import resolve_control_path, resolve_manifest_path  # noqa: E402
from redaction import redact_text  # noqa: E402
from v2_gate_runtime import _v2_dag_nodes, _v2_role_entries, _v2_role_path  # noqa: E402
from qa.tex_source import load_tex_source  # noqa: E402
try:  # Package import in tests versus direct script execution.
    from qa.review_evidence import (  # type: ignore  # noqa: E402
        REVIEW_DIR, REVIEW_MODE_LEVEL, evaluate_w2_review, required_perspectives,
        review_freshness, summarize_review, validate_bundle_boundary,
        validate_execution_binding, validate_review_report,
        _reverse_outline_excerpt, _writing_spine_excerpt,
    )
except ModuleNotFoundError:  # pragma: no cover - direct CLI path
    from review_evidence import (  # type: ignore  # noqa: E402
        REVIEW_DIR, REVIEW_MODE_LEVEL, evaluate_w2_review, required_perspectives,
        review_freshness, summarize_review, validate_bundle_boundary,
        validate_execution_binding, validate_review_report,
        _reverse_outline_excerpt, _writing_spine_excerpt,
    )

REPO_ROOT = SCRIPT_DIR.parents[1]
BUNDLE_ALLOW_ROLES = (
    "problem_snapshot", "data_contract", "model_contract", "validation_report",
    "frozen_results", "evidence_registry",
    "paper_plan", "abstract", "paper", "conclusion", "presentation_contract",
    "writer_package", "pdf", "figure", "table",
)
RUBRICS = {
    "semantic_critic": "references/review/semantic_critic_rubric.md",
    "judge_lens": "references/review/judge_lens.md",
    "human_prose": "references/writing/human_prose_revision.md",
}
SECTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9][A-Za-z0-9_-]*)*$")


def _now() -> str:
    # Microseconds prevent two fast review runs from overwriting the same
    # generated-evidence path on filesystems with coarse timestamp handling.
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _safe_run_component(run_id: str) -> str:
    """Encode a logical run id as one collision-resistant path component."""

    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", run_id).strip(".") or "run"
    if cleaned != run_id:
        suffix = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:8]
        cleaned = f"{cleaned[:48]}-{suffix}"
    return cleaned[:64]


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=str(cwd), text=True, capture_output=True,
        encoding="utf-8", errors="replace", env=env or child_env(), check=False,
    )


# ---------------------------------------------------------------------------
# Phase 1 — deterministic QA (existing runner, no copied policy)
# ---------------------------------------------------------------------------

def run_deterministic_phase(state: Any, root: Path, ts: str) -> tuple[bool, dict[str, Any], str]:
    output = root / REVIEW_DIR / f"deterministic_qa-{ts}.json"
    command = [
        sys.executable, str(SCRIPT_DIR / "run_deterministic_qa.py"),
        "--manifest", str(state.manifest_path), "--project-root", str(root),
        "--output", str(output), "--force",
    ]
    result = _run(command, cwd=root)
    report: dict[str, Any] = {}
    if result.returncode == 0:
        try:
            loaded = load_structured(output)
            report = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError, TypeError):
            report = {}
    errors: list[str] = []
    if result.returncode != 0:
        try:
            loaded = json.loads(result.stdout)
            errors = [str(item) for item in loaded.get("errors", [])] if isinstance(loaded, dict) else []
        except json.JSONDecodeError:
            errors = [f"qa runner exited {result.returncode}"]
    ok = result.returncode == 0 and report.get("ok") is True
    return ok, report, "; ".join(errors[:8]) or ("" if ok else "deterministic QA did not produce ok=true")


# ---------------------------------------------------------------------------
# Phase 2 — materialize the allow-listed review bundle
# ---------------------------------------------------------------------------

def build_bundle(
    state: Any,
    root: Path,
    ts: str,
    perspectives: list[str],
    *,
    focus_section: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    bundle_dir = root / REVIEW_DIR / "bundle" / f"{_safe_run_component(state.run_id)}-{ts}"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    dag_by_path = {
        resolve_path(str(node["path"]), root).resolve(): node
        for node in _v2_dag_nodes(state)
        if isinstance(node.get("path"), str)
    }
    seen: set[tuple[str, Path]] = set()
    source_dependencies: list[dict[str, str]] = []
    role_order = () if perspectives == ["human_prose"] else BUNDLE_ALLOW_ROLES
    for role in role_order:
        for item_index, (candidate, path) in enumerate(_v2_role_entries(state, role), start=1):
            path = path.resolve()
            if not path.is_file() or (role, path) in seen:
                continue
            seen.add((role, path))
            node = dag_by_path.get(path, candidate)
            suffix = path.suffix or ".bin"
            destination = bundle_dir / f"{role}-{item_index}{suffix}"
            shutil.copy2(path, destination)
            files.append({
                "role": role,
                "artifact_id": node.get("artifact_id") if isinstance(node, dict) else None,
                # source_path preserves the project identity used by the report
                # while the backend receives only the materialized copy.
                "source_path": rel_path(path, root),
                "path": destination.name,
                "sha256": sha256_file(destination),
            })
            if role == "paper" and path.suffix.casefold() == ".tex":
                source = load_tex_source(path, root)
                context = bundle_dir / f"paper-source-context-{item_index}.tex"
                context.write_text(source.text, encoding="utf-8")
                files.append({
                    "role": "paper_source_context", "artifact_id": None,
                    "path": context.name, "sha256": sha256_file(context),
                })
                source_dependencies.extend(
                    {"path": rel_path(source_path, root), "sha256": sha256_file(source_path)}
                    for source_path in source.files
                )
    rules = root / "rules.txt"
    if rules.is_file() and perspectives != ["human_prose"]:
        destination = bundle_dir / "rules_ref.txt"
        shutil.copy2(rules, destination)
        files.append({"role": "rules_ref", "artifact_id": None, "path": destination.name, "sha256": sha256_file(destination)})
    if "human_prose" in perspectives:
        files.extend(_human_prose_context(root, bundle_dir, focus_section=focus_section))
        statistics = _human_prose_scan(state, root, bundle_dir, focus_section=focus_section)
        if statistics is not None:
            files.append(statistics)
        for index, relative in enumerate(
            (RUBRICS["human_prose"], "references/writing/editorial_style.md"),
            start=1,
        ):
            source = REPO_ROOT / relative
            destination = bundle_dir / f"rules_ref-human-prose-{index}.md"
            shutil.copy2(source, destination)
            files.append({
                "role": "rules_ref",
                "artifact_id": None,
                "path": destination.name,
                "sha256": sha256_file(destination),
            })
    else:
        structural = _judge_scan_structural(state, root, bundle_dir)
        if structural is not None:
            files.append(structural)
    context_policy = None
    if perspectives == ["human_prose"]:
        context_policy = {
            "default_roles": [
                "paper_section", "section_brief", "writing_spine", "reverse_outline",
                "human_prose_statistics", "rules_ref",
            ],
            "on_demand_roles": [],
            "excluded_roles": [
                "model_contract", "validation_report", "frozen_results", "evidence_registry",
                "abstract", "conclusion", "pdf", "figure", "table", "competition_rules",
                "previous_review_report",
            ],
        }
    manifest = {
        "schema_version": "1.0",
        "run_id": state.run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "perspectives": perspectives,
        "information_boundary": {
            "policy": "allow_list_only",
            "deny_by_default": [
                "writer private reasoning", "previous reviewer reasoning", "previous semantic/judge verdict",
                "revision negotiation", "unrelated drafts", "session logs", "hidden chain-of-thought",
            ],
        },
        "files": files,
    }
    if source_dependencies:
        manifest["source_dependencies"] = source_dependencies
    if context_policy is not None:
        manifest["focus_section"] = focus_section
        manifest["context_policy"] = context_policy
        manifest["bindings"] = _review_bindings(state, root, ("paper",))
    manifest_path = bundle_dir / "bundle_manifest.json"
    write_json(manifest_path, manifest, overwrite=True)
    return manifest_path, manifest


def _review_bindings(state: Any, root: Path, roles: tuple[str, ...]) -> list[dict[str, Any]]:
    """Expose canonical identity for report binding without copying source content."""

    rows: list[dict[str, Any]] = []
    dag_by_path = {
        resolve_path(str(node["path"]), root).resolve(): node
        for node in _v2_dag_nodes(state)
        if isinstance(node.get("path"), str)
    }
    for role in roles:
        for candidate, path in _v2_role_entries(state, role):
            canonical = dag_by_path.get(path.resolve(), candidate)
            if not path.is_file() or not isinstance(canonical.get("artifact_id"), str):
                continue
            rows.append({
                "role": role,
                "artifact_id": canonical["artifact_id"],
                "source_path": rel_path(path, root),
                "sha256": sha256_file(path),
            })
    return rows


def _human_prose_context(root: Path, bundle_dir: Path, *, focus_section: str | None) -> list[dict[str, Any]]:
    """Copy only regenerable, section-local editorial context into a review bundle."""

    context: list[dict[str, Any]] = []
    spine = root / ".harness/views/WRITING_SPINE.md"
    if spine.is_file():
        destination = bundle_dir / "writing_spine.md"
        content = spine.read_text(encoding="utf-8")
        if focus_section:
            content = _writing_spine_excerpt(content, focus_section)
        if content:
            destination.write_text(content, encoding="utf-8")
            context.append({
                "role": "writing_spine",
                "artifact_id": None,
                "source_path": rel_path(spine, root),
                "source_sha256": sha256_file(destination),
                "path": destination.name,
                "sha256": sha256_file(destination),
            })
    reverse_outline = root / "reports/reverse_outline.md"
    if reverse_outline.is_file():
        destination = bundle_dir / "reverse_outline.md"
        content = reverse_outline.read_text(encoding="utf-8")
        if focus_section:
            content = _reverse_outline_excerpt(content, focus_section)
        if content:
            destination.write_text(content, encoding="utf-8")
            context.append({
                "role": "reverse_outline",
                "artifact_id": None,
                "source_path": rel_path(reverse_outline, root),
                "source_sha256": sha256_file(destination),
                "path": destination.name,
                "sha256": sha256_file(destination),
            })
    candidates: list[tuple[str, Path]] = []
    if focus_section:
        candidates.extend([
            ("section_brief", root / f".harness/views/sections/{focus_section}_brief.md"),
            ("paper_section", root / f"paper/sections/{focus_section}/draft.md"),
        ])
    for role, source in candidates:
        if not source.is_file():
            continue
        destination = bundle_dir / f"{role}{source.suffix or '.txt'}"
        shutil.copy2(source, destination)
        context.append({
            "role": role,
            "artifact_id": None,
            "source_path": rel_path(source, root),
            "source_sha256": sha256_file(source),
            "path": destination.name,
            "sha256": sha256_file(destination),
        })
    return context


def _paper_plan_sections(state: Any) -> set[str]:
    _, plan_path = _v2_role_path(state, "paper_plan")
    if plan_path is None or not plan_path.is_file():
        return set()
    plan = load_structured(plan_path)
    if not isinstance(plan, dict):
        return set()
    return {
        str(row["section_id"])
        for row in plan.get("sections", [])
        if isinstance(row, dict) and isinstance(row.get("section_id"), str)
    }


def _human_prose_scan(
    state: Any,
    root: Path,
    bundle_dir: Path,
    *,
    focus_section: str | None,
) -> dict[str, Any] | None:
    """Materialize non-verdict prose statistics without result/model inputs."""

    _, plan = _v2_role_path(state, "paper_plan")
    _, paper = _v2_role_path(state, "paper")
    if plan is None or paper is None or not plan.is_file() or not paper.is_file():
        return None
    draft = paper
    if focus_section:
        focused_draft = root / f"paper/sections/{focus_section}/draft.md"
        if not focused_draft.is_file():
            return None
        draft = focused_draft
    command = [
        sys.executable, str(SCRIPT_DIR / "check_paper_style.py"),
        "--paper-plan", str(plan), "--draft", str(draft), "--human-prose-stats",
        "--project-root", str(root),
    ]
    result = _run(command, cwd=root)
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    statistics = report.get("human_prose_statistics") if isinstance(report, dict) else None
    if not isinstance(statistics, dict):
        return None
    destination = bundle_dir / "human_prose_statistics.md"
    lines = [
        "# Human-Prose Statistics",
        "",
        "> Non-verdict signals; the reviewer decides whether a clustered pattern impairs the argument.",
        "",
        f"- paragraph count: {statistics.get('paragraph_count')}",
        f"- paragraph lengths: {statistics.get('paragraph_lengths')}",
        f"- sentence lengths: {statistics.get('sentence_lengths')}",
        f"- transition counts: {statistics.get('transition_counts')}",
        f"- same result-frame count: {statistics.get('same_result_frame_count')}",
        f"- recap-frame count: {statistics.get('recap_frame_count')}",
        f"- signal candidates: {statistics.get('signals')}",
        "",
    ]
    destination.write_text("\n".join(lines), encoding="utf-8")
    return {
        "role": "human_prose_statistics",
        "artifact_id": None,
        "path": destination.name,
        "sha256": sha256_file(destination),
    }


def _judge_scan_structural(state: Any, root: Path, bundle_dir: Path) -> dict[str, Any] | None:
    """Seed the Judge Lens with the existing deterministic judge scan output."""

    def role_path(role: str) -> Path | None:
        _, path = _v2_role_path(state, role)
        return path if path is not None and path.is_file() else None

    plan = role_path("paper_plan")
    paper = role_path("paper")
    if plan is None or paper is None:
        return None
    command = [
        sys.executable, str(SCRIPT_DIR / "check_paper_style.py"),
        "--paper-plan", str(plan), "--draft", str(paper), "--judge-scan",
        "--project-root", str(root),
    ]
    for role, flag in (("abstract", "--abstract"), ("model_contract", "--model-contract"), ("frozen_results", "--frozen-results")):
        path = role_path(role)
        if path is not None:
            command.extend([flag, str(path)])
    result = _run(command, cwd=root)
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(report, dict) or not isinstance(report.get("judge_scan"), dict):
        return None
    destination = bundle_dir / "judge_scan_structural.json"
    write_json(destination, report["judge_scan"], overwrite=True)
    return {"role": "judge_scan_structural", "artifact_id": None, "path": destination.name, "sha256": sha256_file(destination)}


# ---------------------------------------------------------------------------
# Phase 3 — reviewer execution paths
# ---------------------------------------------------------------------------

PROTECTED_REVIEW_ROLES = (
    "problem_snapshot", "data_contract", "model_contract", "validation_report",
    "frozen_results", "evidence_registry", "paper_plan", "abstract", "paper",
    "conclusion", "writer_package", "pdf", "figure", "table",
)


def _protected_snapshot(
    state: Any,
    root: Path,
    *,
    focus_section: str | None = None,
) -> dict[Path, str | None]:
    """Snapshot author/control artifacts that a reviewer may not mutate."""

    paths: set[Path] = {state.manifest_path.resolve(), state.profile_path.resolve()}
    dag_path = state.root_path("artifact_dag")
    if dag_path is not None:
        paths.add(dag_path.resolve())
    rules = root / "rules.txt"
    if rules.exists():
        paths.add(rules.resolve())
    for role in PROTECTED_REVIEW_ROLES:
        for _, path in _v2_role_entries(state, role):
            paths.add(path.resolve())
    if focus_section:
        paths.update({
            (root / f"paper/sections/{focus_section}/draft.md").resolve(),
            (root / f".harness/views/sections/{focus_section}_brief.md").resolve(),
            (root / ".harness/views/WRITING_SPINE.md").resolve(),
            (root / "reports/reverse_outline.md").resolve(),
        })
    return {path: sha256_file(path) if path.is_file() else None for path in paths}


def _snapshot_mutations(before: dict[Path, str | None]) -> list[str]:
    changed: list[str] = []
    for path, digest in before.items():
        after = sha256_file(path) if path.is_file() else None
        if after != digest:
            changed.append(str(path))
    return changed


def _split_backend_command(command: str) -> list[str]:
    values = shlex.split(command, posix=os.name != "nt")
    if os.name == "nt":
        values = [
            value[1:-1]
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}
            else value
            for value in values
        ]
    return values

def run_backend_reviewer(
    state: Any,
    root: Path,
    backend_cmd: str,
    perspective: str,
    bundle_manifest_path: Path,
    report_path: Path,
    review_mode: str,
    *,
    focus_section: str | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Execute one reviewer through the process-captured receipt seam."""

    receipt_id = f"REC-{uuid.uuid4().hex[:16]}"
    receipt = root / "receipts" / f"review-{_now()}-{uuid.uuid4().hex[:6]}.json"
    env = child_env()
    env.update({
        "MATH_REVIEW_PERSPECTIVE": perspective,
        "MATH_REVIEW_BUNDLE": str(bundle_manifest_path),
        "MATH_REVIEW_BUNDLE_REL": rel_path(bundle_manifest_path, root),
        "MATH_REVIEW_OUTPUT": str(report_path),
        "MATH_REVIEW_RUBRIC": str(REPO_ROOT / RUBRICS[perspective]),
        "MATH_REVIEW_MODE": review_mode,
        "MATH_REVIEW_INDEPENDENCE": REVIEW_MODE_LEVEL[review_mode],
        "MATH_REVIEW_RECEIPT_ID": receipt_id,
        "MATH_REVIEW_RECEIPT_REL": rel_path(receipt, root),
    })
    note = f"review:{perspective}:{review_mode}:{REVIEW_MODE_LEVEL[review_mode]}"
    command = [
        sys.executable, str(SCRIPT_DIR.parent / "run_and_record.py"),
        "--manifest", str(state.manifest_path),
        "--run-id", state.run_id, "--stage", "review",
        "--receipt", rel_path(receipt, root), "--receipt-id", receipt_id,
        "--index", rel_path(state.root_path("run_index", required=True), root), "--freeze", "--note", note,
        "--input", rel_path(bundle_manifest_path, root),
        "--output-artifact", rel_path(report_path, root),
        "--project-root", str(root),
        "--command-cwd", rel_path(bundle_manifest_path.parent, root),
        "--", *_split_backend_command(backend_cmd),
    ]
    protected = _protected_snapshot(state, root, focus_section=focus_section)
    result = _run(command, cwd=root, env=env)
    mutations = _snapshot_mutations(protected)
    execution: dict[str, Any] = {
        "backend_command": backend_cmd,
        "receipt_id": receipt_id,
        "receipt_path": rel_path(receipt, root) if receipt.is_file() else None,
        "exit_code": result.returncode,
        "stderr_tail": redact_text(result.stderr[-400:]),
        "protected_artifact_mutations": [rel_path(Path(path), root) for path in mutations],
    }
    ok = result.returncode == 0 and report_path.is_file() and not mutations
    return ok, execution


def record_backend_ai_use(
    state: Any,
    root: Path,
    perspective: str,
    bundle_manifest_path: Path,
    execution: dict[str, Any],
    *,
    tool_name: str,
    model: str,
    provider: str,
    output_accepted: bool,
) -> dict[str, Any]:
    """Register an observable backend call before any S1 disclosure is built."""

    receipt_value = execution.get("receipt_path")
    if not isinstance(receipt_value, str):
        raise ValueError(f"{perspective} backend use has no process receipt to bind")
    receipt_path = resolve_path(receipt_value, root).resolve()
    if not receipt_path.is_file():
        raise ValueError(f"{perspective} backend receipt does not exist: {receipt_value}")
    now = datetime.now(timezone.utc).isoformat()
    receipt_id = str(execution.get("receipt_id", "UNRECORDED"))
    usage_id = f"AI-REVIEW-{receipt_id.removeprefix('REC-')}"
    record = {
        "usage_id": usage_id,
        "tool_name": tool_name,
        "model": model,
        "provider": provider,
        "used_at": now,
        "stage": "review",
        "purpose": f"Run the {perspective} reviewer on the allow-listed review bundle",
        "prompt_summary": (
            f"Apply the {perspective} rubric to {rel_path(bundle_manifest_path, root)} "
            "and write a schema-bound review report"
        ),
        "output_use": (
            "candidate review report produced; acceptance remains subject to schema and human verification"
            if output_accepted
            else "no accepted review output; failed execution retained as audit evidence"
        ),
        "human_changes": "pending human verification",
        "interaction_record": {
            "path": rel_path(receipt_path, root),
            "sha256": sha256_file(receipt_path),
        },
        "verification": {
            "status": "pending",
            "checked_by_role": "unassigned",
            "method": "pending human verification",
            "checked_at": now,
        },
    }
    count = append_ai_usage_record(state.manifest_path, record)
    from prepare_project import refresh_ai_ledger

    refreshed = load_runtime_state(state.manifest_path, project_root=root, allow_legacy=False)
    ledger_path, _ = refresh_ai_ledger(refreshed)
    return {
        "usage_id": usage_id,
        "verification_status": "pending",
        "record_count": count,
        "ledger": rel_path(ledger_path, root),
    }


def routing_instructions(
    state: Any,
    root: Path,
    perspective: str,
    bundle_manifest_path: Path,
    report_path: Path,
) -> str:
    lines = [
        f"  [{perspective}]",
        f"    rubric:   {RUBRICS[perspective]}",
        f"    bundle:   {rel_path(bundle_manifest_path, root)}",
        f"    output:   {rel_path(report_path, root)}",
        "    schema:   schemas/review_report.schema.json",
        "    contract: review_mode=self_critic, independence_level=L0_same_context",
        "              reviewed_artifacts use only bundle bindings with non-null artifact_id + source_path",
        "              map binding source_path -> path and copy artifact_id/role/sha256; omit files rows",
        "              copy bundle_manifest path/sha256 into bundle_ref",
        "              available_evidence_scope may narrow but never exceed the scope implied by reviewed_artifacts",
        "              each finding may declare required_evidence_scope; insufficient gate-severity evidence requires requires_external_check=true",
        "              rerunnable is not established by a reviewer-process receipt or free-text locator; route it to external checking",
        f"              findings use REV-* ids; verdict=pass requires zero effective open blocker/high/medium; run_id={state.run_id}",
    ]
    if perspective == "human_prose":
        lines.extend([
            "              use the bundle context_policy: read default_roles first and on_demand_roles only when needed",
            "              each finding requires finding_type, quoted_passage, protected_content, and required_recheck",
            "              blocker is forbidden; findings are local editorial proposals and do not change Gate status",
            "              do not alter facts, numbers, mathematics, evidence scope, citations, or competition semantics",
        ])
    return "\n".join(lines)


def evaluate_selected_review(
    root: Path,
    preset: str,
    run_id: str,
    perspectives: list[str],
    *,
    focus_section: str | None = None,
) -> tuple[dict[str, Any], list[str], bool | None]:
    """Evaluate this command without granting optional perspectives Gate authority."""

    if perspectives != ["human_prose"]:
        summary, errors = evaluate_w2_review(root, preset, run_id=run_id)
        return summary, errors, not errors
    summary = summarize_review(root, preset, run_id=run_id, human_focus_section=focus_section)
    view = summary["perspectives"]["human_prose"]
    errors: list[str] = []
    if not view["executed"]:
        errors.append("human_prose review report was not found")
    errors.extend(f"human_prose review: {message}" for message in view["errors"])
    if view["executed"] and view["freshness"] != "current":
        errors.append(f"human_prose review is {view['freshness']}")
    summary["next_finding"] = view.get("next_finding")
    return summary, errors, None


def validate_backend_output(
    state: Any,
    root: Path,
    perspective: str,
    review_mode: str,
    report_path: Path,
    execution: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Reject a backend report that self-asserts a different execution
    identity than the orchestrator actually requested."""

    try:
        value = load_structured(report_path)
    except (OSError, ValueError, TypeError) as exc:
        return None, [f"cannot read backend report: {exc}"]
    if not isinstance(value, dict):
        return None, ["backend report must be an object"]
    errors = validate_review_report(value)
    expected = {
        "run_id": state.run_id,
        "perspective": perspective,
        "review_mode": review_mode,
        "independence_level": REVIEW_MODE_LEVEL[review_mode],
    }
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            errors.append(
                f"backend report {field}={value.get(field)!r} does not match orchestrator-bound {expected_value!r}"
            )
    receipt_ref = value.get("execution_receipt_ref")
    if not isinstance(receipt_ref, dict):
        errors.append("backend report must include execution_receipt_ref")
    else:
        if receipt_ref.get("receipt_id") != execution.get("receipt_id"):
            errors.append("backend report execution_receipt_ref does not match the launched receipt id")
        if receipt_ref.get("path") != execution.get("receipt_path"):
            errors.append("backend report execution_receipt_ref does not match the launched receipt path")
    freshness, freshness_errors = review_freshness(value, root)
    errors.extend(freshness_errors)
    if freshness != "current":
        errors.append("backend report artifact binding is stale")
    if (
        value.get("independence_level") in {"L1_fresh_context", "L2_independent_model", "L3_human"}
        or perspective == "human_prose"
    ):
        errors.extend(validate_bundle_boundary(value, root))
    errors.extend(validate_execution_binding(value, report_path, root, require_registration=False))
    return value, errors


def quarantine_rejected_report(root: Path, report_path: Path) -> str | None:
    """Move backend output that failed the execution contract out of the
    discoverable evidence directory. It remains available for diagnosis but
    cannot outrank a later valid review or poison W2 as if it were evidence."""

    if not report_path.is_file():
        return None
    rejected_dir = root / REVIEW_DIR / "rejected"
    rejected_dir.mkdir(parents=True, exist_ok=True)
    destination = rejected_dir / report_path.name
    if destination.exists():
        destination = rejected_dir / f"{report_path.stem}-{uuid.uuid4().hex[:6]}{report_path.suffix}"
    report_path.replace(destination)
    return rel_path(destination, root)


# ---------------------------------------------------------------------------
# Phase 5 — register validated reports as generated evidence in the DAG
# ---------------------------------------------------------------------------

def register_review_report(root: Path, report: dict[str, Any], report_path: Path) -> bool:
    """Append one review_report node to the canonical DAG; idempotent by path."""

    dag_path = resolve_control_path(root, "artifact_dag.json")
    if not dag_path.is_file():
        return False
    try:
        dag = load_structured(dag_path)
    except (OSError, ValueError, TypeError):
        return False
    if not isinstance(dag, dict) or not isinstance(dag.get("nodes"), list):
        return False
    relative = rel_path(report_path, root)
    if any(isinstance(node, dict) and node.get("path") == relative for node in dag["nodes"]):
        return False
    digest = sha256_file(report_path)
    receipt_ref = report.get("execution_receipt_ref")
    receipt_id = str(receipt_ref.get("receipt_id")) if isinstance(receipt_ref, dict) else None
    artifact_ids = {
        str(node.get("artifact_id"))
        for node in dag["nodes"]
        if isinstance(node, dict) and isinstance(node.get("artifact_id"), str)
    }
    dependencies = [
        {"artifact_id": ref["artifact_id"], "relation": "reviewed"}
        for ref in report.get("reviewed_artifacts", [])
        if isinstance(ref, dict) and ref.get("artifact_id") in artifact_ids
    ]
    node: dict[str, Any] = {
        "artifact_id": f"REVIEW-{digest[:20].upper()}",
        "role": "review_report",
        "path": relative,
        "producer_id": "harness.review",
        "dependencies": dependencies,
        "lifecycle": "immutable",
        "freshness": "current",
        "digest_owner": f"command_receipt:{receipt_id}" if receipt_id else "artifact_dag",
        "digest_algorithm": "sha256",
        "version": "1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "perspective": report.get("perspective"),
            "review_mode": report.get("review_mode"),
            "independence_level": report.get("independence_level"),
            "verdict": report.get("verdict"),
            "generated_evidence": True,
            "execution_receipt_path": receipt_ref.get("path") if isinstance(receipt_ref, dict) else None,
        },
    }
    if receipt_id:
        node["producer_receipt_id"] = receipt_id
    else:
        node["sha256"] = digest
    dag["nodes"].append(node)
    dag_path.write_text(json.dumps(dag, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _severity_block(name: str, view: dict[str, Any]) -> list[str]:
    counts = {**{"blocker": 0, "high": 0, "medium": 0, "low": 0}, **view.get("severity_counts", {})}
    lines = [f"{name}_review:"]
    lines.append(f"    verdict: {view.get('verdict')}  freshness: {view.get('freshness')}")
    lines.append(
        f"    blocker: {counts['blocker']}  high: {counts['high']}  medium: {counts['medium']}  low: {counts['low']}"
    )
    lines.append(f"    evidence scope: {view.get('available_evidence_scope', 'paper_only')}")
    if view.get("scope_limited_ids"):
        lines.append("    external evidence check: " + ", ".join(str(item) for item in view["scope_limited_ids"]))
    lines.append(f"    independence: {view.get('independence_level')}")
    if view.get("degraded_independence"):
        lines.append("    degraded independence: same-context fallback")
    for error in view.get("errors", [])[:4]:
        lines.append(f"    error: {error}")
    return lines


def _human(result: dict[str, Any]) -> str:
    lines: list[str] = []
    if result.get("deterministic_qa"):
        qa = result["deterministic_qa"]
        lines.append(f"deterministic QA: {'PASS' if qa.get('ok') else 'FAIL'}")
        if qa.get("errors"):
            lines.extend(f"  - {error}" for error in qa["errors"][:6])
    for message in result.get("phases", []):
        lines.append(message)
    for perspective, view in result.get("review", {}).get("perspectives", {}).items():
        lines.extend(_severity_block(str(perspective), view))
    w2 = result.get("w2_preview")
    if w2 is not None:
        lines.append(f"W2: {'PASS' if w2 else 'FAIL'}")
    errors = result.get("errors", [])
    if errors:
        lines.append("errors:")
        lines.extend(f"  - {error}" for error in errors[:8])
    finding = result.get("review", {}).get("next_finding") if result.get("review") else None
    if isinstance(finding, dict):
        lines.append("Next:")
        lines.append(f"  {finding.get('finding_id')} — {finding.get('summary')}")
        lines.append(f"  fix: {finding.get('required_fix')}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=None)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--semantic", action="store_true", help="run only the semantic critic perspective")
    parser.add_argument("--judge", action="store_true", help="run only the judge lens perspective")
    parser.add_argument("--human-prose", action="store_true", help="run only the optional human-prose editorial perspective")
    parser.add_argument("--section", help="required focus section id for --human-prose")
    parser.add_argument("--fresh", action="store_true", help="require fresh-context (L1) execution via --backend-cmd")
    parser.add_argument("--recheck", action="store_true", help="revalidate existing reports without executing reviewers")
    parser.add_argument("--backend-cmd", help="reviewer backend command; executed per perspective with MATH_REVIEW_* env")
    parser.add_argument("--backend-kind", choices=("ai", "non_ai"), help="declare whether this backend invokes AI")
    parser.add_argument("--ai-tool-name", help="AI tool identity for automatic backend usage logging")
    parser.add_argument("--ai-model", help="AI model identity for automatic backend usage logging")
    parser.add_argument("--ai-provider", help="AI provider identity for automatic backend usage logging")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    selected = [args.semantic, args.judge, args.human_prose]
    if sum(bool(value) for value in selected) > 1:
        print(json.dumps({"ok": False, "errors": [
            "--semantic, --judge, and --human-prose are mutually exclusive",
        ]}, ensure_ascii=False))
        return 2
    if args.section and not args.human_prose:
        print(json.dumps({"ok": False, "errors": ["--section is only valid with --human-prose"]}, ensure_ascii=False))
        return 2
    if args.human_prose and not args.section:
        print(json.dumps({"ok": False, "errors": [
            "--human-prose requires --section so the editorial context remains local",
        ]}, ensure_ascii=False))
        return 2
    if args.human_prose and args.fresh:
        print(json.dumps({"ok": False, "errors": [
            "--human-prose is editorial L0 and cannot claim --fresh review independence",
        ]}, ensure_ascii=False))
        return 2
    if args.section and not SECTION_ID.fullmatch(args.section):
        print(json.dumps({"ok": False, "errors": [
            "--section must use letters, digits, dots, underscores, or hyphens and cannot contain a path",
        ]}, ensure_ascii=False))
        return 2

    root = Path(args.project_root).resolve()
    try:
        manifest_path = resolve_manifest_path(root, args.manifest)
        state = load_runtime_state(manifest_path, project_root=root, allow_legacy=False)
    except (OSError, ValueError, TypeError, RuntimeStateError) as exc:
        print(json.dumps({"ok": False, "errors": [f"v2 manifest resolution failed: {exc}"]}, ensure_ascii=False))
        return 2

    if args.section and args.section not in _paper_plan_sections(state):
        print(json.dumps({"ok": False, "errors": [
            f"--section {args.section!r} is not present in the current paper_plan",
        ]}, ensure_ascii=False))
        return 2
    if args.section and not (root / f"paper/sections/{args.section}/draft.md").is_file():
        print(json.dumps({"ok": False, "errors": [
            f"--section {args.section!r} has no current draft at paper/sections/{args.section}/draft.md",
        ]}, ensure_ascii=False))
        return 2
    if args.section:
        required_context = [
            root / f".harness/views/sections/{args.section}_brief.md",
            root / ".harness/views/WRITING_SPINE.md",
        ]
        missing_context = [rel_path(path, root) for path in required_context if not path.is_file()]
        if missing_context:
            print(json.dumps({"ok": False, "errors": [
                "--human-prose requires prepared local context: " + ", ".join(missing_context),
            ]}, ensure_ascii=False))
            return 2
    perspectives = list(required_perspectives(state.preset))
    if args.semantic:
        perspectives = ["semantic_critic"]
    if args.judge:
        perspectives = ["judge_lens"]
    if args.human_prose:
        perspectives = ["human_prose"]
    review_mode = "fresh_context" if args.fresh else "self_critic"
    if args.fresh and not args.backend_cmd and not args.recheck:
        print(json.dumps({"ok": False, "errors": [
            "--fresh requires --backend-cmd; a same-context self-critic cannot pose as a fresh-context reviewer",
        ]}, ensure_ascii=False))
        return 2
    if args.backend_cmd and not args.backend_kind:
        print(json.dumps({"ok": False, "errors": [
            "--backend-cmd requires --backend-kind=ai or --backend-kind=non_ai; backend type is never inferred",
        ]}, ensure_ascii=False))
        return 2
    if args.backend_cmd and args.backend_kind == "ai" and not all((args.ai_tool_name, args.ai_model, args.ai_provider)):
        print(json.dumps({"ok": False, "errors": [
            "--backend-cmd requires --ai-tool-name, --ai-model, and --ai-provider so observable AI use cannot go unlogged",
        ]}, ensure_ascii=False))
        return 2

    ts = _now()
    result: dict[str, Any] = {
        "ok": False,
        "run_id": state.run_id,
        "preset": state.preset,
        "perspectives": perspectives,
        "phases": [],
        "progress": [],
        "errors": [],
    }

    def progress(message: str) -> None:
        result["progress"].append(message)
        if not args.json:
            print(message, file=sys.stderr, flush=True)

    registered: list[str] = []

    if not args.recheck:
        # Phase 1 — deterministic QA must pass before semantic review runs.
        total_steps = 2 + len(perspectives)
        progress(f"[1/{total_steps}] Running deterministic QA...")
        qa_ok, qa_report, qa_error = run_deterministic_phase(state, root, ts)
        result["deterministic_qa"] = {"ok": qa_ok, "errors": [qa_error] if qa_error else []}
        if not qa_ok:
            result["errors"].append(f"deterministic QA failed; fix deterministic issues before semantic review: {qa_error}")
            print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else _human(result))
            return 1
        # Phase 2 — materialize the allow-listed bundle (integrity boundary;
        # this is not an OS filesystem sandbox).
        progress(f"[2/{total_steps}] Building allow-listed review bundle...")
        bundle_manifest_path, bundle = build_bundle(
            state,
            root,
            ts,
            perspectives,
            focus_section=args.section,
        )
        result["bundle"] = {
            "path": rel_path(bundle_manifest_path, root),
            "files": [row["role"] for row in bundle["files"]],
        }
        # Phase 3 — dispatch reviewers.
        pending: list[str] = []
        for step_index, perspective in enumerate(perspectives, start=3):
            progress(f"[{step_index}/{total_steps}] Running {perspective}...")
            report_path = root / REVIEW_DIR / f"{perspective}-{_safe_run_component(state.run_id)}-{ts}.json"
            if args.backend_cmd:
                ok, execution = run_backend_reviewer(
                    state, root, args.backend_cmd, perspective, bundle_manifest_path, report_path, review_mode,
                    focus_section=args.section,
                )
                result.setdefault("executions", {})[perspective] = execution
                if args.backend_kind == "ai":
                    try:
                        ai_record = record_backend_ai_use(
                            state, root, perspective, bundle_manifest_path, execution,
                            tool_name=args.ai_tool_name, model=args.ai_model,
                            provider=args.ai_provider, output_accepted=ok,
                        )
                        result.setdefault("ai_usage_records", {})[perspective] = ai_record
                    except (OSError, ValueError, TypeError, RuntimeStateError) as exc:
                        result["errors"].append(f"{perspective} backend AI use could not be registered: {exc}")
                if not ok:
                    mutations = execution.get("protected_artifact_mutations", [])
                    if mutations:
                        result["errors"].append(
                            f"{perspective} backend mutated protected author/control artifact(s): {', '.join(mutations)}"
                        )
                    result["errors"].append(
                        f"{perspective} backend reviewer did not produce a report at {rel_path(report_path, root)}"
                    )
                    rejected = quarantine_rejected_report(root, report_path)
                    if rejected:
                        execution["rejected_report_path"] = rejected
                else:
                    report, report_errors = validate_backend_output(
                        state, root, perspective, review_mode, report_path, execution,
                    )
                    if report_errors:
                        result["errors"].extend(
                            f"{perspective} backend report: {message}" for message in report_errors
                        )
                        rejected = quarantine_rejected_report(root, report_path)
                        if rejected:
                            execution["rejected_report_path"] = rejected
                    elif report is not None and register_review_report(root, report, report_path):
                        registered.append(rel_path(report_path, root))
            else:
                pending.append(routing_instructions(state, root, perspective, bundle_manifest_path, report_path))
        if pending:
            result["phases"].extend(pending)
            result["phases"].append(
                "after writing the report file(s), rerun with --recheck to validate and register review evidence"
            )
            print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else _human(result))
            return 1

    # Recheck imports/reregisters manually routed evidence. Backend reports
    # were already validated against their expected execution identity above.
    if args.recheck:
        summary_preview = summarize_review(
            root, state.preset, run_id=state.run_id, require_registration=False,
            human_focus_section=args.section if args.human_prose else None,
        )
        for perspective, view in summary_preview["perspectives"].items():
            if perspective not in perspectives or not view.get("executed"):
                continue
            report_path = view.get("report_path")
            if not report_path:
                continue
            if view.get("errors"):
                result["errors"].extend(f"{perspective} report {report_path}: {message}" for message in view["errors"])
                continue
            try:
                report = load_structured(root / report_path)
            except (OSError, ValueError, TypeError) as exc:
                result["errors"].append(f"{perspective} report {report_path} cannot be re-read: {exc}")
                continue
            if register_review_report(root, report, root / report_path):
                registered.append(report_path)
    if registered:
        result["phases"].append(f"registered review evidence in artifact DAG: {', '.join(registered)}")

    # Phase 6 — factual summary and W2 preview from real evidence.
    summary, w2_errors, w2_preview = evaluate_selected_review(
        root, state.preset, state.run_id, perspectives, focus_section=args.section,
    )
    result["review"] = summary
    result["errors"].extend(w2_errors)
    # W2 preview covers only the review plane here; full W2 re-checks QA too.
    if w2_preview is not None:
        result["w2_preview"] = w2_preview
    result["ok"] = not result["errors"]
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else _human(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
