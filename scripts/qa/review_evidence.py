"""Deterministic review-evidence boundary for the Review Execution Plane.

This module owns no state and mutates nothing.  It discovers review reports,
validates them against the review contract (schema, mode/level mapping,
artifact binding, freshness, verdict/finding consistency, fresh-context bundle
boundary), and derives the per-preset W2 review requirements.  ``run_review``,
the W2 gate runtime, and ``harness status`` all read review truth through this
single boundary so there is exactly one interpretation of "a current review".

Review reports are GENERATED_EVIDENCE: they live under ``reports/review/`` and
are optionally registered as DAG nodes with ``role=review_report``.  The
manifest never stores review status.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

try:  # Support both direct CLI execution and package-level test imports.
    from _common import load_structured, rel_path, resolve_path, sha256_file  # type: ignore  # noqa: E402
except ModuleNotFoundError:  # pragma: no cover - exercised by package imports.
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from _common import load_structured, rel_path, resolve_path, sha256_file  # type: ignore  # noqa: E402

from project_layout import resolve_control_path  # type: ignore  # noqa: E402
REVIEW_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "review_report.schema.json"
REVIEW_DIR = "reports/review"
REVIEW_PERSPECTIVES = ("semantic_critic", "judge_lens", "human_prose")
REVIEW_MODE_LEVEL: Mapping[str, str] = {
    "self_critic": "L0_same_context",
    "fresh_context": "L1_fresh_context",
    "independent_model": "L2_independent_model",
    "human": "L3_human",
}
INDEPENDENCE_RANK: Mapping[str, int] = {
    "L0_same_context": 0,
    "L1_fresh_context": 1,
    "L2_independent_model": 2,
    "L3_human": 3,
}
L1_LEVELS = ("L1_fresh_context", "L2_independent_model", "L3_human")
BLOCKING_SEVERITIES = ("blocker", "high")
SEVERITIES = ("blocker", "high", "medium", "low")
GATE_SEVERITIES = ("blocker", "high", "medium")

# Evidence scopes are ordered by what can be established, not by reviewer
# seniority.  A paper-only pass cannot become a rerunnable conclusion merely
# because a reviewer used stronger language.
EVIDENCE_SCOPES = ("paper_only", "paper_source", "result_artifacts", "rerunnable")
EVIDENCE_SCOPE_RANK: Mapping[str, int] = {
    scope: rank for rank, scope in enumerate(EVIDENCE_SCOPES)
}
SOURCE_SCOPE_ROLES = frozenset({
    "problem_snapshot", "data_contract", "model_contract", "paper_plan",
    "writer_package", "rules_ref",
})
RESULT_SCOPE_ROLES = frozenset({
    "validation_report", "frozen_results", "evidence_registry", "figure", "table",
})
# A perspective is not a real review of the paper if it binds only an
# arbitrary convenient file. Each group means "at least one of these roles".
REQUIRED_BINDING_ROLE_GROUPS: Mapping[str, tuple[frozenset[str], ...]] = {
    "semantic_critic": (
        frozenset({"model_contract"}),
        frozenset({"frozen_results"}),
        frozenset({"evidence_registry"}),
        frozenset({"paper", "pdf"}),
    ),
    "judge_lens": (
        frozenset({"paper", "pdf"}),
        frozenset({"abstract"}),
        frozenset({"conclusion"}),
    ),
    "human_prose": (
        frozenset({"paper", "pdf"}),
    ),
}

# What a fresh review bundle may physically contain.  Everything else —
# writer reasoning, previous verdicts, revision negotiation, session logs —
# is denied by simply never being copied into the bundle.
BUNDLE_ALLOW_ROLES = frozenset({
    "problem_snapshot", "data_contract", "model_contract", "validation_report",
    "frozen_results", "evidence_registry",
    "paper_plan", "abstract", "paper", "conclusion", "presentation_contract",
    "writer_package", "pdf", "figure", "table", "rules_ref", "judge_scan_structural",
    "writing_spine", "section_brief", "paper_section", "reverse_outline", "human_prose_statistics",
    "paper_source_context",
})
# Roles that, if found inside a bundle, prove the information boundary was
# broken and void any L1+ independence claim.
BUNDLE_DENY_ROLES = frozenset({
    "review_report", "previous_verdict", "writer_reasoning",
    "revision_discussion", "session_log",
})
HUMAN_PROSE_BUNDLE_ROLES = frozenset({
    "paper_section", "section_brief", "writing_spine", "reverse_outline",
    "human_prose_statistics", "rules_ref",
})
HUMAN_SECTION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*(?:\.[A-Za-z0-9][A-Za-z0-9_-]*)*$")


def required_perspectives(preset: str) -> tuple[str, ...]:
    """Derive required review perspectives from the preset; no review matrix."""

    if preset == "sprint":
        return ("semantic_critic",)
    if preset in {"research", "submission"}:
        return ("semantic_critic", "judge_lens")
    raise ValueError(f"unknown preset: {preset!r}")


def requires_l1_review(preset: str) -> bool:
    return preset == "submission"


def _writing_spine_excerpt(content: str, section_id: str) -> str:
    """Keep the spine header and one exact section block."""

    lines = content.splitlines()
    section_start = next(
        (index for index, line in enumerate(lines) if line.startswith(f"### {section_id} (")),
        None,
    )
    if section_start is None:
        return ""
    section_end = next(
        (
            index for index in range(section_start + 1, len(lines))
            if lines[index].startswith("### ") or lines[index].startswith("## ")
        ),
        len(lines),
    )
    header_end = next(
        (index for index, line in enumerate(lines) if line == "## Section order and argument units"),
        0,
    )
    excerpt = [*lines[:header_end], "## Focused section", "", *lines[section_start:section_end]]
    return "\n".join(excerpt).rstrip() + "\n"


def _reverse_outline_excerpt(content: str, section_id: str) -> str:
    """Keep only outline rows explicitly mapped to the focused section."""

    rows = [line for line in content.splitlines() if f"-> {section_id} ->" in line]
    if not rows:
        return ""
    return "\n".join(["# Reverse Outline — Focused Section", "", *rows, ""])


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _dag_review_paths(root: Path) -> list[Path]:
    dag_path = resolve_control_path(root, "artifact_dag.json")
    paths: list[Path] = []
    if not dag_path.is_file():
        return paths
    try:
        dag = load_structured(dag_path)
    except (OSError, ValueError, TypeError):
        return paths
    nodes = dag.get("nodes", []) if isinstance(dag, dict) else []
    for node in nodes if isinstance(nodes, list) else []:
        if isinstance(node, dict) and node.get("role") == "review_report" and isinstance(node.get("path"), str):
            path = resolve_path(node["path"], root).resolve()
            try:
                path.relative_to(root.resolve())
            except ValueError:
                continue
            paths.append(path)
    return paths


def discover_review_reports(root: Path) -> list[tuple[dict[str, Any], Path]]:
    """Return parseable review reports from the DAG declaration and the
    conventional ``reports/review/`` directory, deduplicated by path.

    Invalid JSON or non-review files are silently skipped here; per-report
    contract validation happens in :func:`validate_review_report` so callers
    can report precise errors instead of hiding broken evidence.
    """

    root = root.resolve()
    candidates: list[Path] = []
    for path in _dag_review_paths(root):
        candidates.append(path)
    review_dir = root / REVIEW_DIR
    if review_dir.is_dir():
        for path in sorted(review_dir.glob("*.json")):
            candidates.append(path.resolve())
    seen: set[Path] = set()
    reports: list[tuple[dict[str, Any], Path]] = []
    for path in candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            value = load_structured(path)
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(value, dict) and value.get("schema_version") == "1.0" and isinstance(value.get("perspective"), str):
            reports.append((value, path))
    return reports


def _current_run_scan_errors(root: Path, run_id: str | None) -> list[str]:
    """Surface malformed current-run evidence instead of silently falling
    back to an older passing report."""

    if not run_id:
        return []
    review_dir = root.resolve() / REVIEW_DIR
    if not review_dir.is_dir():
        return []
    errors: list[str] = []
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", run_id).strip(".") or "run"
    if cleaned != run_id:
        cleaned = f"{cleaned[:48]}-{hashlib.sha256(run_id.encode('utf-8')).hexdigest()[:8]}"
    marker = f"-{cleaned[:64]}-"
    for path in sorted(review_dir.glob("*.json")):
        if not path.name.startswith(REVIEW_PERSPECTIVES):
            continue
        try:
            value = load_structured(path)
        except (OSError, ValueError, TypeError) as exc:
            if marker in path.name:
                errors.append(f"current-run review evidence is unreadable: {rel_path(path, root)}: {exc}")
            continue
        if isinstance(value, Mapping) and str(value.get("run_id")) != run_id:
            continue
        if marker not in path.name and not isinstance(value, Mapping):
            continue
        if not isinstance(value, dict) or value.get("schema_version") != "1.0" or value.get("perspective") not in REVIEW_PERSPECTIVES:
            errors.append(f"current-run review evidence is not a review report: {rel_path(path, root)}")
    return errors


# ---------------------------------------------------------------------------
# Contract validation
# ---------------------------------------------------------------------------

def _schema_errors(report: Mapping[str, Any]) -> list[str]:
    try:
        from validate_contracts import _validate_document  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover - package import edge
        from qa.validate_contracts import _validate_document  # type: ignore
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False)
        temp_path = Path(handle.name)
    try:
        _, errors, _ = _validate_document(temp_path, REVIEW_SCHEMA_PATH)
        return list(errors)
    finally:
        temp_path.unlink(missing_ok=True)


def _inferred_evidence_scope(report: Mapping[str, Any]) -> str:
    """Infer the strongest scope established by the current review bundle.

    The current bundle can establish paper, source-contract, and result-level
    inspection.  It cannot establish ``rerunnable``: that future scope needs
    structured bindings to code, data, environment, and a model-run receipt.
    Reviewer-process receipts and free-text locators do not satisfy it.
    """

    roles = {
        str(ref.get("role"))
        for ref in report.get("reviewed_artifacts", [])
        if isinstance(ref, Mapping) and isinstance(ref.get("role"), str)
    }
    if roles & RESULT_SCOPE_ROLES:
        return "result_artifacts"
    if roles & SOURCE_SCOPE_ROLES:
        return "paper_source"
    return "paper_only"


def _available_evidence_scope(report: Mapping[str, Any]) -> str:
    declared = report.get("available_evidence_scope")
    return str(declared) if declared in EVIDENCE_SCOPE_RANK else _inferred_evidence_scope(report)


def _finding_scope_state(report: Mapping[str, Any], finding: Mapping[str, Any]) -> tuple[str, str, bool]:
    """Return ``(available, required, insufficient)`` for one finding."""

    available = _available_evidence_scope(report)
    required_raw = finding.get("required_evidence_scope", "paper_only")
    required = str(required_raw) if required_raw in EVIDENCE_SCOPE_RANK else "paper_only"
    insufficient = EVIDENCE_SCOPE_RANK[required] > EVIDENCE_SCOPE_RANK[available]
    return available, required, insufficient


def _scope_limited_finding(report: Mapping[str, Any], finding: Mapping[str, Any]) -> bool:
    return _finding_scope_state(report, finding)[2]


def validate_review_report(report: Mapping[str, Any]) -> list[str]:
    """Deterministic contract checks that do not touch the filesystem."""

    errors = _schema_errors(report)
    if errors:
        return errors
    inferred_scope = _inferred_evidence_scope(report)
    declared_scope = report.get("available_evidence_scope")
    if declared_scope is not None and EVIDENCE_SCOPE_RANK[str(declared_scope)] > EVIDENCE_SCOPE_RANK[inferred_scope]:
        errors.append(
            f"available_evidence_scope {declared_scope!r} exceeds the bound artifact scope "
            f"{inferred_scope!r}; a review cannot self-upgrade its evidence boundary"
        )
    mode = str(report.get("review_mode"))
    level = str(report.get("independence_level"))
    if REVIEW_MODE_LEVEL.get(mode) != level:
        errors.append(
            f"review_mode {mode!r} cannot claim independence_level {level!r}; "
            f"the only legal level for this mode is {REVIEW_MODE_LEVEL.get(mode)!r}"
        )
    if level == "L0_same_context" and report.get("degraded_independence") not in (None, False, True):
        errors.append("degraded_independence must be a boolean")
    if level in {"L1_fresh_context", "L2_independent_model"} and not isinstance(report.get("bundle_ref"), dict):
        errors.append(f"independence_level {level!r} requires a bundle_ref to a materialized review bundle")
    if report.get("perspective") == "human_prose":
        if mode != "self_critic" or level != "L0_same_context":
            errors.append("human_prose is editorial only and must use self_critic/L0_same_context")
        if not isinstance(report.get("bundle_ref"), dict):
            errors.append("human_prose review requires bundle_ref for local-context freshness")
    try:
        reviewed_at = datetime.fromisoformat(str(report.get("reviewed_at", "")).replace("Z", "+00:00"))
        if reviewed_at.tzinfo is None:
            raise ValueError("timezone missing")
    except ValueError:
        errors.append("reviewed_at must be an ISO-8601 timestamp with timezone")
    findings = report.get("findings", [])
    if not isinstance(findings, list):
        return errors
    for row in findings:
        if not isinstance(row, dict):
            continue
        if row.get("perspective") == "human_prose":
            missing = [
                field for field in ("finding_type", "quoted_passage", "protected_content", "required_recheck")
                if not row.get(field)
            ]
            if missing:
                errors.append(
                    f"human_prose finding {row.get('finding_id')} requires: {', '.join(missing)}"
                )
            if row.get("severity") == "blocker":
                errors.append(
                    f"human_prose finding {row.get('finding_id')} cannot use blocker severity"
                )
        available, required_scope, insufficient = _finding_scope_state(report, row)
        if insufficient:
            if row.get("severity") in GATE_SEVERITIES and row.get("requires_external_check") is not True:
                errors.append(
                    f"finding {row.get('finding_id')} requires {required_scope} evidence but report only exposes "
                    f"{available}; set requires_external_check=true or lower the finding severity"
                )
    gate_open = [
        row for row in findings
        if isinstance(row, dict)
        and row.get("severity") in GATE_SEVERITIES
        and row.get("status") == "open"
        and not _scope_limited_finding(report, row)
    ]
    raw_gate_open = [
        row for row in findings
        if isinstance(row, dict) and row.get("severity") in GATE_SEVERITIES and row.get("status") == "open"
    ]
    if report.get("verdict") == "pass" and gate_open:
        errors.append(
            "verdict=pass conflicts with open blocker/high/medium finding(s): "
            + ", ".join(str(row.get("finding_id")) for row in gate_open)
        )
    if report.get("verdict") == "fail" and not raw_gate_open:
        errors.append("verdict=fail requires at least one open blocker/high/medium finding")
    accepted = [
        row for row in findings
        if isinstance(row, dict) and row.get("status") == "accepted_risk" and not row.get("accepted_risk_justification")
    ]
    if accepted:
        errors.append("accepted_risk findings require accepted_risk_justification")
    unsafe_acceptance = [
        row for row in findings
        if isinstance(row, dict)
        and row.get("status") == "accepted_risk"
        and row.get("severity") in BLOCKING_SEVERITIES
        and mode != "human"
    ]
    if unsafe_acceptance:
        errors.append("only an L3 human review may accept blocker/high risk")
    finding_ids = [str(row.get("finding_id")) for row in findings if isinstance(row, dict)]
    if len(finding_ids) != len(set(finding_ids)):
        errors.append("finding_id values must be unique within a report")
    for row in findings:
        if isinstance(row, dict) and row.get("perspective") != report.get("perspective"):
            errors.append(f"finding {row.get('finding_id')} perspective does not match the report perspective")
            break
    return errors


def review_freshness(report: Mapping[str, Any], root: Path) -> tuple[str, list[str]]:
    """Recompute freshness from bytes: a report is current only while every
    reviewed artifact still hashes to the digest recorded at review time."""

    root = root.resolve()
    errors: list[str] = []
    artifacts = report.get("reviewed_artifacts", [])
    if not isinstance(artifacts, list) or not artifacts:
        return "stale", ["review report binds no reviewed artifacts"]
    current = True
    dag_by_id: dict[str, Mapping[str, Any]] = {}
    dag_path = resolve_control_path(root, "artifact_dag.json")
    if dag_path.is_file():
        try:
            dag = load_structured(dag_path)
            nodes = dag.get("nodes", []) if isinstance(dag, dict) else []
            dag_by_id = {
                str(node.get("artifact_id")): node
                for node in nodes if isinstance(node, Mapping) and isinstance(node.get("artifact_id"), str)
            }
        except (OSError, ValueError, TypeError):
            dag_by_id = {}
    roles = {str(ref.get("role")) for ref in artifacts if isinstance(ref, Mapping)}
    perspective = str(report.get("perspective"))
    for group in REQUIRED_BINDING_ROLE_GROUPS.get(perspective, ()):
        if roles.isdisjoint(group):
            errors.append(f"{perspective} review does not bind required artifact role group {sorted(group)}")
            current = False
    for index, ref in enumerate(artifacts):
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
            errors.append(f"reviewed_artifacts[{index}] is not a valid artifact ref")
            current = False
            continue
        path = resolve_path(ref["path"], root).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            errors.append(f"reviewed_artifacts[{index}] escapes project root: {ref['path']}")
            current = False
            continue
        if not path.is_file():
            errors.append(f"reviewed artifact no longer exists: {ref['path']}")
            current = False
            continue
        actual = sha256_file(path)
        if actual != ref.get("sha256"):
            errors.append(f"reviewed artifact changed since review: {ref['path']}")
            current = False
        artifact_id = ref.get("artifact_id")
        if not isinstance(artifact_id, str) or not artifact_id:
            errors.append(f"reviewed_artifacts[{index}] has no canonical artifact_id")
            current = False
            continue
        node = dag_by_id.get(artifact_id)
        if node is None:
            errors.append(f"reviewed_artifacts[{index}] references unknown artifact_id {artifact_id!r}")
            current = False
            continue
        node_path = resolve_path(str(node.get("path", "")), root).resolve()
        if node_path != path:
            errors.append(f"reviewed_artifacts[{index}] artifact_id/path binding mismatch")
            current = False
        node_digest = node.get("sha256") or node.get("digest")
        if isinstance(node_digest, str) and node_digest.lower() != str(ref.get("sha256", "")).lower():
            errors.append(f"reviewed_artifacts[{index}] does not match the canonical DAG digest")
            current = False
    source_errors = _source_dependency_freshness(report, root)
    errors.extend(source_errors)
    current = current and not source_errors
    if perspective == "human_prose":
        context_errors = _human_context_freshness(report, root)
        errors.extend(context_errors)
        current = current and not context_errors
    return ("current" if current else "stale"), errors


def _source_dependency_freshness(report: Mapping[str, Any], root: Path) -> list[str]:
    """A TeX child that changed after review invalidates its source snapshot."""

    bundle_ref = report.get("bundle_ref")
    if not isinstance(bundle_ref, Mapping):
        return []
    bundle_path = resolve_path(str(bundle_ref.get("path", "")), root).resolve()
    try:
        bundle_path.relative_to(root)
    except ValueError:
        return ["review bundle manifest escapes project root"]
    if not bundle_path.is_file() or sha256_file(bundle_path) != bundle_ref.get("sha256"):
        return ["review bundle manifest is missing or changed"]
    try:
        manifest = load_structured(bundle_path)
    except (OSError, ValueError, TypeError) as exc:
        return [f"cannot inspect review source dependencies: {exc}"]
    if not isinstance(manifest, Mapping):
        return ["review bundle manifest must be an object"]
    rows = manifest.get("source_dependencies", [])
    tex_review = any(
        isinstance(row, Mapping) and str(row.get("path", "")).lower().endswith(".tex")
        for row in report.get("reviewed_artifacts", [])
    ) or any(
        isinstance(row, Mapping) and row.get("role") == "paper_source_context"
        for row in manifest.get("files", [])
    )
    if tex_review and not rows:
        return ["TeX review bundle has no source_dependencies"]
    if not isinstance(rows, list):
        return ["review source_dependencies must be an array"]
    errors: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("path"), str) or not isinstance(row.get("sha256"), str):
            errors.append("review source dependency has no path or digest")
            continue
        path = resolve_path(row["path"], root).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            errors.append(f"review source dependency escapes project root: {row['path']}")
            continue
        if not path.is_file() or sha256_file(path) != row["sha256"]:
            errors.append(f"review source dependency changed since review: {row['path']}")
    return errors


def _human_context_freshness(report: Mapping[str, Any], root: Path) -> list[str]:
    """Bind an editorial report to the local derived context it actually saw."""

    root = root.resolve()
    bundle_ref = report.get("bundle_ref")
    if not isinstance(bundle_ref, Mapping):
        return ["human_prose review has no bundle_ref for local-context freshness"]
    bundle_path = resolve_path(str(bundle_ref.get("path", "")), root).resolve()
    try:
        bundle_path.relative_to(root)
    except ValueError:
        return ["human_prose bundle_ref escapes project root"]
    if not bundle_path.is_file():
        return ["human_prose bundle manifest no longer exists"]
    try:
        manifest = load_structured(bundle_path)
    except (OSError, ValueError, TypeError) as exc:
        return [f"cannot inspect human_prose bundle manifest: {exc}"]
    if not isinstance(manifest, Mapping):
        return ["human_prose bundle manifest must be an object"]
    errors: list[str] = []
    focus_section = manifest.get("focus_section")
    if not isinstance(focus_section, str) or not HUMAN_SECTION_ID.fullmatch(focus_section):
        return ["human_prose bundle has no valid focus_section"]
    local_roles = {"paper_section", "section_brief", "writing_spine", "reverse_outline"}
    local_rows = [
        row for row in manifest.get("files", [])
        if isinstance(row, Mapping) and row.get("role") in local_roles
    ]
    expected_sources = {
        "paper_section": f"paper/sections/{focus_section}/draft.md",
        "section_brief": f".harness/views/sections/{focus_section}_brief.md",
        "writing_spine": ".harness/views/WRITING_SPINE.md",
        "reverse_outline": "reports/reverse_outline.md",
    }
    for required_role in ("paper_section", "section_brief", "writing_spine"):
        if sum(row.get("role") == required_role for row in local_rows) != 1:
            errors.append(f"human_prose bundle requires exactly one {required_role}")
    for row in local_rows:
        role = str(row.get("role"))
        source_path = row.get("source_path")
        if not isinstance(source_path, str):
            errors.append(f"human_prose {role} has no source_path")
            continue
        if source_path.replace("\\", "/") != expected_sources[role]:
            errors.append(f"human_prose {role} source does not match focus_section {focus_section}")
            continue
        source = resolve_path(source_path, root).resolve()
        try:
            source.relative_to(root)
        except ValueError:
            errors.append(f"human_prose context source escapes project root: {source_path}")
            continue
        if not source.is_file():
            errors.append(f"human_prose context source no longer exists: {source_path}")
        elif not isinstance(row.get("source_sha256"), str):
            errors.append(f"human_prose {role} has no source_sha256")
        else:
            if role == "writing_spine":
                projected = _writing_spine_excerpt(source.read_text(encoding="utf-8"), focus_section)
                source_digest = hashlib.sha256(projected.encode("utf-8")).hexdigest()
            elif role == "reverse_outline":
                projected = _reverse_outline_excerpt(source.read_text(encoding="utf-8"), focus_section)
                source_digest = hashlib.sha256(projected.encode("utf-8")).hexdigest()
            else:
                source_digest = sha256_file(source)
            if source_digest != row.get("source_sha256"):
                errors.append(f"human_prose context source changed since review: {source_path}")
        member_path = row.get("path")
        member = (bundle_path.parent / str(member_path)).resolve()
        if not isinstance(member_path, str) or not member.is_file():
            continue
        content = member.read_text(encoding="utf-8")
        if role == "writing_spine":
            headings = re.findall(r"^### ([^\r\n]+?) \(", content, flags=re.MULTILINE)
            if headings != [focus_section]:
                errors.append("human_prose writing_spine excerpt is not limited to focus_section")
        if role == "reverse_outline":
            mapped_sections = re.findall(r"->\s*([^\s]+)\s*->", content)
            if any(section != focus_section for section in mapped_sections):
                errors.append("human_prose reverse_outline excerpt contains another section")
    return errors


def validate_bundle_boundary(report: Mapping[str, Any], root: Path) -> list[str]:
    """Verify the fresh-context information boundary of one L1+ report.

    The bundle manifest must exist, hash-match, list only allow-listed roles,
    and every listed file must still match its recorded digest.  A denied role
    inside the bundle voids the independence claim outright.
    """

    root = root.resolve()
    bundle_ref = report.get("bundle_ref")
    if not isinstance(bundle_ref, dict):
        return ["fresh review requires bundle_ref with path and sha256"]
    bundle_path = resolve_path(str(bundle_ref.get("path", "")), root).resolve()
    try:
        bundle_path.relative_to(root)
    except ValueError:
        return [f"review bundle manifest escapes project root: {bundle_ref.get('path')}"]
    if not bundle_path.is_file():
        return [f"review bundle manifest does not exist: {bundle_ref.get('path')}"]
    if sha256_file(bundle_path) != bundle_ref.get("sha256"):
        return ["review bundle manifest sha256 drift"]
    try:
        manifest = load_structured(bundle_path)
    except (OSError, ValueError, TypeError) as exc:
        return [f"cannot inspect review bundle manifest: {exc}"]
    if not isinstance(manifest, dict):
        return ["review bundle manifest must be an object"]
    errors: list[str] = []
    is_human_bundle = manifest.get("perspectives") == ["human_prose"]
    files = manifest.get("files", [])
    if not isinstance(files, list) or not files:
        return ["review bundle manifest lists no files"]
    for index, ref in enumerate(files):
        if not isinstance(ref, dict) or not isinstance(ref.get("role"), str):
            errors.append(f"bundle file entry[{index}] has no role")
            continue
        role = str(ref["role"])
        if role in BUNDLE_DENY_ROLES:
            errors.append(f"bundle contains denied input role {role!r}; independence claim is void")
        elif is_human_bundle and role not in HUMAN_PROSE_BUNDLE_ROLES:
            errors.append(f"human_prose bundle contains out-of-scope role {role!r}")
        elif role not in BUNDLE_ALLOW_ROLES:
            errors.append(f"bundle contains unlisted input role {role!r}; not on the review allow list")
        raw_path = ref.get("path")
        if not isinstance(raw_path, str):
            continue
        member = (bundle_path.parent / raw_path).resolve()
        try:
            member.relative_to(bundle_path.parent)
        except ValueError:
            errors.append(f"bundle member escapes the materialized bundle: {raw_path}")
            continue
        if not member.is_file():
            errors.append(f"bundle member missing: {raw_path}")
        elif sha256_file(member) != ref.get("sha256"):
            errors.append(f"bundle member sha256 drift: {raw_path}")
    if is_human_bundle:
        policy = manifest.get("context_policy")
        if not isinstance(policy, Mapping):
            errors.append("human_prose bundle requires context_policy")
        bindings = manifest.get("bindings")
        if not isinstance(bindings, list) or not bindings:
            errors.append("human_prose bundle requires a canonical paper binding")
        else:
            for binding in bindings:
                if not isinstance(binding, Mapping) or binding.get("role") != "paper":
                    errors.append("human_prose bundle bindings may contain only canonical paper identity")
    return errors


def validate_execution_binding(
    report: Mapping[str, Any],
    report_path: Path,
    root: Path,
    *,
    require_registration: bool = True,
) -> list[str]:
    """Bind a report to its producer receipt and canonical DAG node.

    L1/L2 claims require a process-captured receipt. Human L3 and manually
    routed L0 reports may be registered with the DAG as digest owner instead.
    """

    root = root.resolve()
    report_path = report_path.resolve()
    errors: list[str] = []
    try:
        report_path.relative_to(root)
    except ValueError:
        return ["review report path escapes project root"]

    receipt_ref = report.get("execution_receipt_ref")
    level = str(report.get("independence_level"))
    if level in {"L1_fresh_context", "L2_independent_model"} and not isinstance(receipt_ref, Mapping):
        errors.append(f"{level} review requires process-captured execution_receipt_ref")

    receipt: Mapping[str, Any] | None = None
    if isinstance(receipt_ref, Mapping):
        receipt_path = resolve_path(str(receipt_ref.get("path", "")), root).resolve()
        try:
            receipt_path.relative_to(root)
        except ValueError:
            errors.append("execution receipt escapes project root")
            receipt_path = root / "__invalid_receipt__"
        if not receipt_path.is_file():
            errors.append(f"execution receipt does not exist: {receipt_ref.get('path')}")
        else:
            try:
                value = load_structured(receipt_path)
                receipt = value if isinstance(value, Mapping) else None
            except (OSError, ValueError, TypeError) as exc:
                errors.append(f"cannot read execution receipt: {exc}")
            if receipt is None:
                errors.append("execution receipt must be an object")
            else:
                receipt_id = str(receipt_ref.get("receipt_id", ""))
                if receipt.get("receipt_id") != receipt_id:
                    errors.append("execution_receipt_ref receipt_id mismatch")
                if receipt.get("stage") != "review" or receipt.get("run_id") != report.get("run_id"):
                    errors.append("execution receipt stage/run_id does not match the review report")
                metadata = receipt.get("metadata") if isinstance(receipt.get("metadata"), Mapping) else {}
                if receipt.get("exit_code") != 0 or metadata.get("outcome") != "success":
                    errors.append("review execution receipt does not record a successful process")
                expected_note = (
                    f"review:{report.get('perspective')}:{report.get('review_mode')}:"
                    f"{report.get('independence_level')}"
                )
                if metadata.get("note") != expected_note:
                    errors.append("execution receipt does not bind the claimed perspective/mode/independence")
                bundle_ref = report.get("bundle_ref")
                if isinstance(bundle_ref, Mapping):
                    expected_cwd = resolve_path(str(bundle_ref.get("path", "")), root).resolve().parent
                    try:
                        receipt_cwd = Path(str(receipt.get("cwd", ""))).resolve()
                    except (OSError, ValueError):
                        receipt_cwd = root / "__invalid_review_cwd__"
                    if receipt_cwd != expected_cwd:
                        errors.append("review execution cwd is not the materialized bundle directory")
                relative = rel_path(report_path, root)
                outputs = [
                    ref for ref in receipt.get("output_refs", [])
                    if isinstance(ref, Mapping) and ref.get("path") == relative
                ]
                if len(outputs) != 1:
                    errors.append("execution receipt must bind exactly one review-report output")
                else:
                    output = outputs[0]
                    if output.get("digest_owner") != "command_receipt" or output.get("sha256") != sha256_file(report_path):
                        errors.append("execution receipt review-report SHA-256 drift")
                if isinstance(bundle_ref, Mapping):
                    inputs = [
                        ref for ref in receipt.get("input_refs", [])
                        if isinstance(ref, Mapping) and ref.get("path") == bundle_ref.get("path")
                    ]
                    if len(inputs) != 1 or inputs[0].get("sha256") != bundle_ref.get("sha256"):
                        errors.append("execution receipt does not bind the exact review bundle input")

    dag_path = resolve_control_path(root, "artifact_dag.json")
    nodes: list[Mapping[str, Any]] = []
    if dag_path.is_file():
        try:
            dag = load_structured(dag_path)
            nodes = [node for node in dag.get("nodes", []) if isinstance(node, Mapping)] if isinstance(dag, Mapping) else []
        except (OSError, ValueError, TypeError):
            nodes = []
    relative = rel_path(report_path, root)
    matches = [node for node in nodes if node.get("role") == "review_report" and node.get("path") == relative]
    if require_registration and len(matches) != 1:
        errors.append("review report is not registered exactly once in the canonical artifact DAG")
    if len(matches) == 1:
        node = matches[0]
        if node.get("producer_id") != "harness.review":
            errors.append("review report DAG producer_id must be harness.review")
        if isinstance(receipt_ref, Mapping):
            receipt_id = str(receipt_ref.get("receipt_id", ""))
            if node.get("producer_receipt_id") != receipt_id:
                errors.append("review report DAG node is not bound to its execution receipt")
            if node.get("digest_owner") != f"command_receipt:{receipt_id}" or node.get("sha256") is not None:
                errors.append("receipt-produced review report must keep digest ownership in the command receipt only")
        else:
            if node.get("digest_owner") != "artifact_dag" or node.get("sha256") != sha256_file(report_path):
                errors.append("manual review report must be SHA-256 bound by the artifact DAG")
    return errors


# ---------------------------------------------------------------------------
# Summary and W2 adjudication
# ---------------------------------------------------------------------------

@dataclass
class PerspectiveSummary:
    perspective: str
    executed: bool = False
    report_path: str | None = None
    verdict: str | None = None
    independence_level: str | None = None
    degraded_independence: bool = False
    available_evidence_scope: str = "paper_only"
    freshness: str = "missing"
    severity_counts: dict[str, int] = field(default_factory=lambda: {name: 0 for name in SEVERITIES})
    open_blocking_ids: list[str] = field(default_factory=list)
    open_medium_ids: list[str] = field(default_factory=list)
    scope_limited_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    next_finding: dict[str, Any] | None = None


def _finding_sort_key(row: Mapping[str, Any]) -> tuple[int, int]:
    severity = str(row.get("severity", "low"))
    return (SEVERITIES.index(severity) if severity in SEVERITIES else len(SEVERITIES), 0)


def summarize_review(
    root: Path,
    preset: str,
    *,
    run_id: str | None = None,
    require_registration: bool = True,
    human_focus_section: str | None = None,
) -> dict[str, Any]:
    """One factual view of review state for a preset; used by status and CLI.

    This never raises on broken evidence: broken reports surface as errors on
    their perspective so `harness status` can still render the project.
    """

    root = root.resolve()
    required = required_perspectives(preset)
    summaries: dict[str, PerspectiveSummary] = {name: PerspectiveSummary(name) for name in REVIEW_PERSPECTIVES}
    reports = discover_review_reports(root)
    # Latest-first ordering: a perspective's newest non-superseded report wins.
    def report_sort_key(item: tuple[dict[str, Any], Path]) -> tuple[str, str]:
        return (str(item[0].get("reviewed_at", "")), str(item[1]))

    by_perspective: dict[str, list[tuple[dict[str, Any], Path]]] = {name: [] for name in REVIEW_PERSPECTIVES}
    for report, path in reports:
        perspective = str(report.get("perspective"))
        if perspective == "human_prose" and human_focus_section is not None:
            bundle_ref = report.get("bundle_ref")
            bundle_path = (
                resolve_path(str(bundle_ref.get("path", "")), root).resolve()
                if isinstance(bundle_ref, Mapping)
                else None
            )
            try:
                bundle = load_structured(bundle_path) if bundle_path and bundle_path.is_file() else None
            except (OSError, ValueError, TypeError):
                bundle = None
            if not isinstance(bundle, Mapping) or bundle.get("focus_section") != human_focus_section:
                continue
        if (
            perspective in by_perspective
            and report.get("superseded_by") is None
            and (run_id is None or str(report.get("run_id")) == str(run_id))
        ):
            by_perspective[perspective].append((report, path))
    for perspective, rows in by_perspective.items():
        rows.sort(key=report_sort_key, reverse=True)
        summary = summaries[perspective]
        if not rows:
            continue
        report, path = rows[0]
        summary.executed = True
        summary.report_path = rel_path(path, root)
        summary.verdict = str(report.get("verdict"))
        summary.independence_level = str(report.get("independence_level"))
        summary.degraded_independence = bool(report.get("degraded_independence"))
        summary.available_evidence_scope = _available_evidence_scope(report)
        summary.errors.extend(validate_review_report(report))
        if not summary.errors:
            freshness, freshness_errors = review_freshness(report, root)
            summary.freshness = freshness
            summary.errors.extend(freshness_errors)
            if summary.independence_level in {"L1_fresh_context", "L2_independent_model"} or perspective == "human_prose":
                summary.errors.extend(validate_bundle_boundary(report, root))
            summary.errors.extend(
                validate_execution_binding(report, path, root, require_registration=require_registration)
            )
        findings = [row for row in report.get("findings", []) if isinstance(row, dict)]
        for row in findings:
            severity = str(row.get("severity"))
            if severity in summary.severity_counts:
                summary.severity_counts[severity] += 1
            scope_limited = _scope_limited_finding(report, row)
            if row.get("status") == "open" and scope_limited and severity in GATE_SEVERITIES:
                summary.scope_limited_ids.append(str(row.get("finding_id")))
            if row.get("status") == "open" and severity in BLOCKING_SEVERITIES and not scope_limited:
                summary.open_blocking_ids.append(str(row.get("finding_id")))
            if row.get("status") == "open" and severity == "medium" and not scope_limited:
                summary.open_medium_ids.append(str(row.get("finding_id")))
        open_findings = [row for row in findings if row.get("status") == "open"]
        if open_findings:
            summary.next_finding = sorted(open_findings, key=_finding_sort_key)[0]

    perspective_view: dict[str, Any] = {}
    for perspective in REVIEW_PERSPECTIVES:
        summary = summaries[perspective]
        perspective_view[perspective] = {
            "required": perspective in required,
            "executed": summary.executed,
            "verdict": summary.verdict,
            "freshness": summary.freshness,
            "independence_level": summary.independence_level,
            "degraded_independence": summary.degraded_independence,
            "available_evidence_scope": summary.available_evidence_scope,
            "severity_counts": dict(summary.severity_counts),
            "open_blocking_ids": list(summary.open_blocking_ids),
            "open_medium_ids": list(summary.open_medium_ids),
            "scope_limited_ids": list(summary.scope_limited_ids),
            "errors": list(summary.errors),
            "report_path": summary.report_path,
            "next_finding": summary.next_finding,
        }
    current_reports = [
        perspective_view[name] for name in required
        if perspective_view[name]["executed"]
        and perspective_view[name]["freshness"] == "current"
        and not perspective_view[name]["errors"]
    ]
    has_l1 = any(
        INDEPENDENCE_RANK.get(str(row.get("independence_level")), 0) >= 1
        for row in current_reports
    )
    return {
        "preset": preset,
        "required_perspectives": list(required),
        "requires_l1_review": requires_l1_review(preset),
        "perspectives": perspective_view,
        "has_current_l1_review": has_l1,
        "next_finding": next(
            (summaries[name].next_finding for name in required if summaries[name].next_finding is not None),
            None,
        ),
    }


def evaluate_w2_review(root: Path, preset: str, *, run_id: str | None = None) -> tuple[dict[str, Any], list[str]]:
    """Adjudicate the W2 review requirement from real reports only.

    Returns the summary plus gate errors.  Missing, stale, contract-invalid,
    or unbound reports each produce explicit errors; nothing is trusted from
    the manifest.
    """

    root = root.resolve()
    summary = summarize_review(root, preset, run_id=run_id, require_registration=True)
    errors: list[str] = _current_run_scan_errors(root, run_id)
    for perspective in summary["required_perspectives"]:
        view = summary["perspectives"][perspective]
        if not view["executed"]:
            errors.append(f"W2 review requires a {perspective} report; none was found under {REVIEW_DIR}/")
            continue
        errors.extend(f"{perspective} review: {message}" for message in view["errors"])
        if view["freshness"] != "current":
            errors.append(f"{perspective} review is {view['freshness']}; a stale or unbound review cannot pass W2")
        if view.get("scope_limited_ids"):
            errors.append(
                f"{perspective} review has finding(s) requiring external evidence check: "
                + ", ".join(str(item) for item in view["scope_limited_ids"])
            )
        if view["open_blocking_ids"]:
            errors.append(
                f"{perspective} review has open blocker/high finding(s): {', '.join(view['open_blocking_ids'])}"
            )
        if view["open_medium_ids"]:
            errors.append(
                f"{perspective} review has open medium finding(s) requiring resolution or accepted risk: "
                f"{', '.join(view['open_medium_ids'])}"
            )
        if view.get("verdict") != "pass":
            errors.append(f"{perspective} review verdict is not pass")
    if summary["requires_l1_review"] and not summary["has_current_l1_review"]:
        errors.append(
            "submission W2 requires at least one current review with independence_level >= L1_fresh_context; "
            "a same-context self-critic cannot satisfy it"
        )
    if preset == "research":
        semantic = summary["perspectives"].get("semantic_critic", {})
        if (
            semantic.get("executed")
            and semantic.get("independence_level") == "L0_same_context"
            and semantic.get("freshness") == "current"
            and semantic.get("degraded_independence") is not True
        ):
            errors.append(
                "research semantic review fell back to L0_same_context without marking degraded_independence=true; "
                "a same-context critic must not pose as an independent review"
            )
    return summary, errors


__all__ = [
    "REVIEW_DIR", "REVIEW_PERSPECTIVES", "REVIEW_MODE_LEVEL", "INDEPENDENCE_RANK",
    "BUNDLE_ALLOW_ROLES", "BUNDLE_DENY_ROLES", "BLOCKING_SEVERITIES",
    "EVIDENCE_SCOPES", "EVIDENCE_SCOPE_RANK",
    "required_perspectives", "requires_l1_review", "discover_review_reports",
    "validate_review_report", "review_freshness", "validate_bundle_boundary", "validate_execution_binding",
    "summarize_review", "evaluate_w2_review",
]
