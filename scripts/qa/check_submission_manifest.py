#!/usr/bin/env python3
"""Validate an F1 submission manifest and all locally referenced final files."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from _common import ai_usage_hash_matches, confirmed_checkpoints, human_confirmed_checkpoints, load_structured, rel_path, resolve_path, sha256_file, sha256_json  # noqa: E402
from validate_contracts import _validate_document  # noqa: E402
from runtime_state import RuntimeStateError, load_runtime_state  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submission-manifest", required=True)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--schema-dir")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    path = resolve_path(args.submission_manifest, root).resolve()
    schema_dir = Path(args.schema_dir).resolve() if args.schema_dir else Path(__file__).resolve().parents[2] / "schemas"
    value, errors, engine = _validate_document(path, schema_dir / "submission_manifest.schema.json")
    warnings: list[str] = []
    if not isinstance(value, dict):
        value = {}

    def verify_ref(owner: str, ref: Any, *, sized: bool = False) -> None:
        if not isinstance(ref, dict):
            errors.append(f"{owner} must be a file reference")
            return
        raw_path = ref.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            errors.append(f"{owner}.path must be non-empty")
            return
        file_path = resolve_path(raw_path, root).resolve()
        if not file_path.is_file():
            errors.append(f"{owner} does not exist: {raw_path}")
            return
        if ref.get("sha256") != sha256_file(file_path):
            errors.append(f"{owner} sha256 drift: {raw_path}")
        if sized and ref.get("bytes") != file_path.stat().st_size:
            errors.append(f"{owner} byte size drift: {raw_path}")

    paper = value.get("paper")
    support = value.get("support_files", [])
    ai = value.get("ai_disclosure")
    verify_ref("paper", paper, sized=True)
    for index, ref in enumerate(support if isinstance(support, list) else []):
        verify_ref(f"support_files[{index}]", ref, sized=True)
    if ai is not None:
        verify_ref("ai_disclosure", ai, sized=True)
    verify_ref("s1_report", value.get("s1_report"))
    run_manifest_ref = value.get("run_manifest")
    verify_ref("run_manifest", run_manifest_ref)
    for index, ref in enumerate(value.get("competition", {}).get("rule_snapshots", [])):
        verify_ref(f"competition.rule_snapshots[{index}]", ref)

    if isinstance(paper, dict) and isinstance(support, list):
        expected_package = sha256_json({"paper": paper, "support_files": support, "ai_disclosure": ai})
        if value.get("package_sha256") != expected_package:
            errors.append("package_sha256 does not match final file records")
    run_manifest: dict[str, Any] = {}
    profile: dict[str, Any] = {}
    try:
        run_manifest_path = resolve_path(run_manifest_ref["path"], root).resolve()
        loaded_manifest = load_structured(run_manifest_path)
        if not isinstance(loaded_manifest, dict):
            errors.append("referenced run_manifest is not an object")
        else:
            run_manifest = loaded_manifest
            if run_manifest.get("project_id") != value.get("project_id"):
                errors.append("run_manifest project_id does not match submission manifest")
            if run_manifest.get("run_id") != value.get("run_id"):
                errors.append("run_manifest run_id does not match submission manifest")
            if run_manifest.get("schema_version") == "2.0":
                try:
                    state = load_runtime_state(run_manifest_path, project_root=root, allow_legacy=False)
                    profile = state.profile
                    if profile.get("status") != "verified":
                        errors.append("F1 requires canonical competition profile status=verified")
                    if not isinstance(profile.get("official_rules"), list) or not profile.get("official_rules"):
                        errors.append("F1 requires non-empty canonical official_rules")
                    if not isinstance(profile.get("official_submission_endpoints"), list) or not profile.get("official_submission_endpoints"):
                        errors.append("F1 requires non-empty canonical official_submission_endpoints")
                    submission_rules = profile.get("submission")
                    if not isinstance(submission_rules, dict):
                        errors.append("F1 requires canonical submission rules")
                    else:
                        for key in ("paper_extensions", "page_count_scope", "support_policy", "ai_disclosure_policy", "required_manual_checks"):
                            if submission_rules.get(key) in (None, "", []):
                                errors.append(f"F1 canonical submission rule {key} is empty")
                except (OSError, ValueError, TypeError, RuntimeStateError) as exc:
                    profile = {}
                    errors.append(f"cannot dereference canonical competition profile: {exc}")
            else:
                profile = run_manifest.get("competition_profile")
            if not isinstance(profile, dict) or sha256_json(profile) != value.get("competition", {}).get("profile_sha256"):
                errors.append("run_manifest competition profile does not match submission manifest")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors.append(f"cannot inspect run_manifest: {exc}")

    try:
        report_path = resolve_path(value["s1_report"]["path"], root).resolve()
        report = load_structured(report_path)
        if not isinstance(report, dict) or report.get("ok") is not True:
            errors.append("referenced S1 report does not have ok=true")
        else:
            if report.get("competition_profile_sha256") != value.get("competition", {}).get("profile_sha256"):
                errors.append("S1 report profile hash does not match submission manifest")
            rules = profile.get("submission") if isinstance(profile, dict) else None
            if not isinstance(rules, dict) or report.get("submission_rules_sha256") != sha256_json(rules):
                errors.append("S1 report submission rules hash does not match run_manifest")
            if not ai_usage_hash_matches(report.get("ai_usage_sha256"), run_manifest):
                errors.append("S1 report AI usage hash does not match run_manifest")
            s1_rows = run_manifest.get("human_checkpoints", [])
            s1_checkpoints = human_confirmed_checkpoints(s1_rows, "s1")
            report_checkpoint = report.get("s1_checkpoint")
            if not s1_checkpoints:
                errors.append(
                    "S1 report human checkpoint was recorded by an agent; a human must confirm S1"
                    if confirmed_checkpoints(s1_rows, "s1")
                    else "S1 report human checkpoint hash does not match run_manifest"
                )
            elif not isinstance(report_checkpoint, dict) or (
                report_checkpoint.get("checkpoint_id") != s1_checkpoints[-1].get("checkpoint_id")
                or report_checkpoint.get("sha256") != sha256_json(s1_checkpoints[-1])
            ):
                errors.append("S1 report human checkpoint hash does not match run_manifest")
            page_count = report.get("page_count")
            if not isinstance(page_count, dict):
                errors.append("S1 report has no auditable page_count record")
            elif isinstance(paper, dict):
                for report_key, paper_key in (
                    ("total_pages", "pages"),
                    ("page_count_method", "page_count_method"),
                    ("limited_pages", "limited_pages"),
                    ("ai_report_pages", "ai_report_pages"),
                    ("body_pages", "body_pages"),
                ):
                    if page_count.get(report_key) != paper.get(paper_key):
                        errors.append(f"S1 report {report_key} does not match frozen paper record")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        errors.append(f"cannot inspect S1 report: {exc}")

    if isinstance(paper, dict):
        pages = paper.get("pages")
        ai_pages = paper.get("ai_report_pages")
        limited_pages = paper.get("limited_pages")
        rules = profile.get("submission", {}) if isinstance(profile, dict) else {}
        body_pages = paper.get("body_pages")
        counted_pages = body_pages if isinstance(rules, dict) and rules.get("page_count_scope") == "paper_body" else pages
        if isinstance(pages, int) and isinstance(ai_pages, int) and isinstance(limited_pages, int):
            if not isinstance(counted_pages, int) or counted_pages < 1 or counted_pages > pages:
                errors.append("paper.body_pages must be within paper.pages for paper_body scope")
            elif ai_pages >= counted_pages:
                errors.append("paper.ai_report_pages must be smaller than counted pages")
            elif limited_pages != counted_pages - ai_pages:
                errors.append("paper.limited_pages must equal counted pages - ai_report_pages")
            max_pages = rules.get("max_pages") if isinstance(rules, dict) else None
            if isinstance(max_pages, int) and limited_pages > max_pages:
                errors.append("paper.limited_pages exceeds the pinned competition maximum")
            if isinstance(rules, dict) and not rules.get("max_pages_excludes_ai_report") and ai_pages != 0:
                errors.append("paper.ai_report_pages must be zero when the profile does not exclude AI report pages")
    closes_at = value.get("deadline", {}).get("closes_at")
    try:
        datetime.fromisoformat(str(closes_at).replace("Z", "+00:00"))
    except ValueError:
        errors.append("deadline.closes_at must be ISO-8601")

    ok = not errors
    print(json.dumps({
        "ok": ok,
        "engine": engine,
        "submission_manifest": rel_path(path, root),
        "errors": errors,
        "warnings": warnings,
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
