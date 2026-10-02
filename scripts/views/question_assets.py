"""Read-only figure atlas with explicit question links and manual prompt handoff."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from _common import sha256_file
from command_display import render_command
from figures.illustration_execution import build_generation_prompt
from project_layout import resolve_manifest_path
from redaction import redact_text
from runtime_state import load_runtime_state
from workflow_sources import project_file, read_object

PREVIEW_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}


def figure_catalog(
    root: Path, artifacts: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    root = root.resolve()
    state = load_runtime_state(
        resolve_manifest_path(root), project_root=root, allow_legacy=False
    )
    plan_path = state.root_path("paper_plan")
    plan = read_object(root, str(plan_path)) if plan_path else {}
    if plan and plan.get("run_id") != state.run_id:
        raise ValueError("paper plan belongs to a different run")
    declared = {row["figure_id"]: row for row in plan.get("figures", [])}
    # A brief alone declares no question or route. Keep it in the unlinked group.
    for brief in sorted((root / "figures").glob("*/brief.md")):
        declared.setdefault(
            brief.parent.name, {"figure_id": brief.parent.name, "kind": "unknown"}
        )
    artifact_paths = {project_file(root, row["path"]): row for row in artifacts or []}
    claims = {row["claim_id"]: row for row in plan.get("claims", [])}
    rows = []
    for identifier, figure in declared.items():
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", identifier):
            raise ValueError("figure id cannot name a project path")
        question_ids = {
            claims[c]["question_id"]
            for c in figure.get("claim_ids", [])
            if c in claims and claims[c].get("question_id")
        }
        for unit in plan.get("argument_units", []):
            if set(figure.get("claim_ids", [])).intersection(unit.get("claim_ids", [])):
                question_ids.update((unit.get("scope") or {}).get("question_ids", []))
        brief_path = project_file(root, f"figures/{identifier}/brief.md")
        request_path = (
            f".harness/views/figures/{identifier}_image_generation_request.json"
        )
        request = read_object(root, request_path)
        record = read_object(root, f"figures/{identifier}/illustration.json")
        if record and record.get("figure_id") != identifier:
            raise ValueError("illustration record belongs to a different figure")
        illustration = figure.get("illustration") or {}
        paths = [
            *figure.get("data_artifacts", []),
            *(figure.get("diagram") or {}).get("rendered_paths", []),
        ]
        if (figure.get("data_lineage") or {}).get("output_artifact"):
            paths.append(figure["data_lineage"]["output_artifact"])
        generated = record.get("generated") or {}
        if generated.get("path"):
            paths.append(generated["path"])
        previews = []
        for raw in dict.fromkeys(paths):
            path = project_file(root, raw)
            if path.suffix.lower() not in {*PREVIEW_TYPES, ".svg"}:
                continue
            registered = artifact_paths.get(path)
            expected = generated.get("sha256") if raw == generated.get("path") else None
            freshness = registered.get("freshness") if registered else "unverified"
            if expected and path.is_file():
                freshness = "current" if sha256_file(path) == expected else "stale"
            previews.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "exists": path.is_file(),
                    "freshness": freshness,
                    "registered": registered is not None,
                    "inline": path.suffix.lower() in PREVIEW_TYPES,
                    "raster": path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"},
                }
            )
        prompt = None
        prompt_state = "not_applicable"
        prompt_source = None
        prompt_error = None
        if figure.get("kind") != "data" and (
            figure.get("kind") == "illustration" or illustration
        ):
            try:
                text = brief_path.read_text(encoding="utf-8")
                prompt = redact_text(build_generation_prompt(text, identifier))
                prompt_source = brief_path.relative_to(root).as_posix()
                prompt_state = "brief_draft"
                if request:
                    if request.get("figure_id") != identifier:
                        raise ValueError(
                            "generation request belongs to a different figure"
                        )
                    prompt_state = (
                        "recorded_current"
                        if request.get("prompt") == prompt
                        else "request_stale"
                    )
            except (OSError, ValueError) as exc:
                prompt_error = str(exc)
                prompt_state = "incomplete_brief"
            # Explicitly recorded prompts may be viewed even before a full brief exists.
            # They establish recorded text only, not brief freshness or generation permission.
            if prompt is None and illustration.get("prompt_path"):
                path = project_file(root, illustration["prompt_path"])
                if path.is_file() and path.stat().st_size <= 131072:
                    prompt = redact_text(path.read_text(encoding="utf-8"))
                    prompt_source = path.relative_to(root).as_posix()
                    prompt_state = "recorded_only"
        rows.append(
            {
                "figure_id": identifier,
                "question_ids": sorted(question_ids),
                "kind": figure.get("kind", "unknown"),
                "purpose": figure.get("purpose"),
                "message": figure.get("message"),
                "caption": figure.get("caption_claim"),
                "qa_status": figure.get("qa_status", "not_reviewed"),
                "brief_path": brief_path.relative_to(root).as_posix(),
                "brief_exists": brief_path.is_file(),
                "previews": previews,
                "prompt": prompt,
                "prompt_state": prompt_state,
                "prompt_source": prompt_source,
                "prompt_error": prompt_error,
                "request_path": request_path if request else None,
                "request_command": render_command(
                    [
                        "harness",
                        "figure",
                        identifier,
                        "--project",
                        str(root),
                        "--kind",
                        "illustration",
                        "--request-illustration",
                        "--capability",
                        "available",
                        "--ai-policy",
                        "allowed",
                    ]
                )
                if prompt
                else None,
                "collect_command": render_command(
                    [
                        "harness",
                        "figure",
                        identifier,
                        "--project",
                        str(root),
                        "--kind",
                        "illustration",
                        "--collect-illustration",
                        f"figures/{identifier}/generated.png",
                    ]
                )
                if prompt
                else None,
                "review_status": record.get(
                    "review_status", illustration.get("review_status", "not_reviewed")
                ),
                "prompt_boundary": "Prompt handoff only. Confirm competition AI policy and record an executable request before collection; scientific, visual and final-size review plus AI disclosure remain required.",
            }
        )
    return rows
