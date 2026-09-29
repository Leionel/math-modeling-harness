#!/usr/bin/env python3
"""Validate a final package against the pinned competition submission profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from _common import ai_usage_snapshot, confirmed_checkpoints, human_confirmed_checkpoints, load_structured, rel_path, resolve_ai_usage_state, resolve_path, sha256_file, sha256_json, write_json  # noqa: E402
from runtime_state import load_runtime_state  # noqa: E402


def file_record(path: Path, root: Path, role: str, *, pages: int | None = None, method: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "role": role,
        "path": rel_path(path, root),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }
    if role == "paper":
        record["pages"] = pages
        record["page_count_method"] = method
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-manifest", required=True)
    parser.add_argument("--paper", required=True)
    parser.add_argument("--paper-pages", type=int)
    parser.add_argument("--body-pages", type=int, help="manually verified body pages when profile page_count_scope is paper_body")
    parser.add_argument("--page-count-method", choices=["pdfinfo", "pypdf", "manual_verified", "not_applicable"])
    parser.add_argument("--ai-report-pages", type=int, help="pages of the AI report section excluded from page limit")
    parser.add_argument("--support", action="append", default=[])
    parser.add_argument("--ai-disclosure")
    parser.add_argument("--output", required=True)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    manifest_path = resolve_path(args.run_manifest, root).resolve()
    output_path = resolve_path(args.output, root).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    try:
        manifest = load_structured(manifest_path)
        if not isinstance(manifest, dict):
            raise ValueError("run_manifest must be an object")
        v2 = manifest.get("schema_version") == "2.0"
        if v2:
            state = load_runtime_state(manifest_path, project_root=root, allow_legacy=False)
            manifest = state.manifest
            profile = state.profile
            if profile.get("status") != "verified":
                errors.append("submission profile must have status=verified; seed/unresolved profiles are blocked")
            if not isinstance(profile.get("official_rules"), list) or not profile.get("official_rules"):
                errors.append("submission profile requires non-empty official_rules")
            if not isinstance(profile.get("official_submission_endpoints"), list) or not profile.get("official_submission_endpoints"):
                errors.append("submission profile requires non-empty official_submission_endpoints")
            submission_rules = profile.get("submission")
            if not isinstance(submission_rules, dict):
                raise ValueError("canonical competition profile has no submission rules")
            required_keys = (
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
            for key in required_keys:
                if key not in submission_rules:
                    errors.append(f"submission profile rule {key} is missing; official limits and policies must not be guessed")
                elif key not in {"max_paper_bytes", "max_pages", "max_support_bytes"} and submission_rules.get(key) in (None, "", []):
                    errors.append(f"submission profile rule {key} is empty")
        else:
            profile = manifest.get("competition_profile")
            if not isinstance(profile, dict):
                raise ValueError("run_manifest has no competition_profile")
        rules = profile.get("submission")
        if not isinstance(rules, dict):
            raise ValueError("competition_profile has no submission rules")
        if v2:
            w2_check = subprocess.run(
                [sys.executable, str(SCRIPT_DIR / "check_gates.py"), "--project-root", str(root), "--manifest", str(manifest_path), "--gate", "w2"],
                text=True, capture_output=True, encoding="utf-8", errors="replace", check=False,
            )
            if w2_check.returncode != 0:
                errors.append("submission QA requires a factually passing W2 gate")
        elif manifest.get("gates", {}).get("w2", {}).get("status") != "pass":
            errors.append("submission QA requires W2 pass")

        ai_policy = rules.get("ai_disclosure_policy")
        ai_format = rules.get("ai_disclosure_format", "separate_file")
        ai_rows = manifest.get("ai_usage", [])
        ai_rows = ai_rows if isinstance(ai_rows, list) else []
        ai_state = resolve_ai_usage_state(manifest)
        if v2 and ai_state == "unknown":
            errors.append("S1 requires an explicit AI usage declaration; run `harness ai record` or `harness ai confirm-none`")
        if ai_state == "used" and not ai_rows:
            errors.append("ai_usage_state=used requires at least one AI usage record")
        if ai_state in {"unknown", "none"} and ai_rows:
            errors.append(f"ai_usage_state={ai_state} conflicts with non-empty ai_usage")
        if v2 and ai_state == "none" and not isinstance(manifest.get("ai_usage_declaration"), dict):
            errors.append("ai_usage_state=none requires an explicit ai_usage_declaration")
        if ai_state != "none" and manifest.get("ai_usage_declaration") is not None:
            errors.append(f"ai_usage_declaration conflicts with ai_usage_state={ai_state}")
        ai_used = ai_state == "used"
        ai_required = ai_policy == "required_always" or (ai_policy == "required_when_used" and ai_used)
        needs_separate_file = ai_format in ("separate_file", "both")
        needs_in_paper = ai_format in ("in_paper_section", "both")
        required_manual = set(rules.get("required_manual_checks", []))
        ai_manual_checks = rules.get("ai_manual_checks", {})
        if not isinstance(ai_manual_checks, dict):
            errors.append("submission.ai_manual_checks must be an object")
            ai_manual_checks = {}
        conditional_key = "when_used" if ai_used else "when_not_used"
        conditional_manual = ai_manual_checks.get(conditional_key, [])
        if not isinstance(conditional_manual, list):
            errors.append(f"submission.ai_manual_checks.{conditional_key} must be an array")
            conditional_manual = []
        required_manual.update(conditional_manual)

        s1_checkpoints = human_confirmed_checkpoints(manifest.get("human_checkpoints", []), "s1")
        selected_checkpoint: dict[str, Any] | None = None
        if not s1_checkpoints:
            if confirmed_checkpoints(manifest.get("human_checkpoints", []), "s1"):
                errors.append("submission QA S1 checkpoints are all agent-recorded; a human must confirm S1")
            else:
                errors.append("submission QA requires a passing S1 human checkpoint")
            completed_manual: set[str] = set()
            checkpoint_refs: set[tuple[Any, Any]] = set()
        else:
            selected_checkpoint = s1_checkpoints[-1]
            checkpoint = selected_checkpoint
            completed_manual = set(checkpoint.get("manual_checks", []))
            missing_manual = sorted(required_manual - completed_manual)
            if missing_manual:
                errors.append("S1 human checkpoint is missing manual check(s): " + ", ".join(missing_manual))
            checkpoint_refs = {
                (ref.get("path"), ref.get("sha256"))
                for ref in checkpoint.get("artifacts", [])
                if isinstance(ref, dict)
            }

        paper = resolve_path(args.paper, root).resolve()
        if not paper.is_file():
            raise ValueError(f"paper does not exist: {args.paper}")
        paper_record = file_record(paper, root, "paper", pages=args.paper_pages, method=args.page_count_method)
        allowed_extensions = {str(value).lower() for value in rules.get("paper_extensions", [])}
        if paper.suffix.lower() not in allowed_extensions:
            errors.append(f"paper extension {paper.suffix!r} is not allowed by profile")
        max_paper_bytes = rules.get("max_paper_bytes")
        if isinstance(max_paper_bytes, int) and paper_record["bytes"] > max_paper_bytes:
            errors.append(f"paper exceeds max_paper_bytes: {paper_record['bytes']}")
        max_pages = rules.get("max_pages")
        excludes_ai_report = bool(rules.get("max_pages_excludes_ai_report"))
        page_scope = rules.get("page_count_scope")
        body_pages = args.body_pages if page_scope == "paper_body" else None
        effective_pages = body_pages if page_scope == "paper_body" else args.paper_pages
        recorded_ai_report_pages = 0
        if not isinstance(args.paper_pages, int) or args.paper_pages < 1:
            errors.append("paper page count is required for an auditable S1 report")
            effective_pages = None
        elif args.page_count_method not in {"pdfinfo", "pypdf", "manual_verified"}:
            errors.append("page_count_method must describe how the page count was verified")
        if page_scope == "paper_body":
            if not isinstance(args.paper_pages, int) or not isinstance(body_pages, int) or not 1 <= body_pages <= args.paper_pages:
                errors.append("--body-pages must be a manually verified count within total PDF pages for paper_body scope")
                effective_pages = None
        elif args.body_pages is not None:
            errors.append("--body-pages is only valid for paper_body scope")
        if isinstance(args.paper_pages, int) and args.paper_pages >= 1 and args.page_count_method in {"pdfinfo", "pypdf", "manual_verified"} and max_pages is not None:
            base_pages = effective_pages
            if excludes_ai_report:
                if not isinstance(args.ai_report_pages, int) or args.ai_report_pages < 0:
                    errors.append("ai_report_pages is required when max_pages_excludes_ai_report is true")
                elif args.ai_report_pages >= args.paper_pages:
                    errors.append("ai_report_pages must be smaller than the total paper page count")
                elif base_pages is not None and args.ai_report_pages >= base_pages:
                    errors.append("ai_report_pages must be smaller than the counted page scope")
                else:
                    recorded_ai_report_pages = args.ai_report_pages
                    effective_pages = base_pages - args.ai_report_pages if base_pages is not None else None
                    if args.ai_report_pages > 0 and "ai_report_position" not in completed_manual:
                        errors.append("S1 human checkpoint must include 'ai_report_position' manual check when AI report pages are excluded")
                    if args.ai_report_pages > 0 and not ai_used:
                        errors.append("ai_report_pages is non-zero but AI usage is not declared as used")
                    if args.ai_report_pages > 0 and not needs_in_paper:
                        errors.append("ai_report_pages can only be excluded when ai_disclosure_format includes an in-paper report")
                    if ai_required and needs_in_paper and args.ai_report_pages == 0:
                        errors.append("an in-paper AI report is required, so ai_report_pages must be greater than zero")
            elif args.ai_report_pages is not None:
                errors.append("ai_report_pages was provided but max_pages_excludes_ai_report is not enabled")
            if isinstance(effective_pages, int) and effective_pages > max_pages:
                label = f"{effective_pages} counted pages (PDF total {args.paper_pages})"
                errors.append(f"paper has {label}; profile maximum is {max_pages}")
        elif max_pages is None:
            if excludes_ai_report:
                errors.append("max_pages_excludes_ai_report requires a numeric max_pages")
            if args.ai_report_pages is not None:
                errors.append("ai_report_pages cannot be used when the profile has no max_pages limit")

        support_records: list[dict[str, Any]] = []
        support_paths: list[Path] = []
        for raw_path in args.support:
            path = resolve_path(raw_path, root).resolve()
            if not path.is_file():
                raise ValueError(f"support file does not exist: {raw_path}")
            support_paths.append(path)
            support_records.append(file_record(path, root, "support"))
        support_policy = rules.get("support_policy")
        if support_policy == "prohibited" and support_records:
            errors.append("support files are prohibited by this profile")
        if support_policy == "required" and not support_records:
            errors.append("at least one support file is required by this profile")
        max_support = rules.get("max_support_bytes")
        support_bytes = sum(row["bytes"] for row in support_records)
        if max_support is not None and support_bytes > max_support:
            errors.append(f"support files total {support_bytes} bytes; profile maximum is {max_support}")
        for archive_path in (path for path in support_paths if path.suffix.lower() == ".zip"):
            if not zipfile.is_zipfile(archive_path):
                errors.append(f"support ZIP is invalid: {rel_path(archive_path, root)}")
                continue
            with zipfile.ZipFile(archive_path) as archive:
                members = archive.infolist()
                if len(members) > 10000:
                    errors.append(f"support ZIP has too many members ({len(members)}): {rel_path(archive_path, root)}")
                uncompressed = sum(member.file_size for member in members)
                if max_support is not None and uncompressed > max_support * 20:
                    errors.append(
                        f"support ZIP uncompressed size {uncompressed} is suspicious relative to profile limit {max_support}"
                    )
                for member in members:
                    member_path = PurePosixPath(member.filename.replace("\\", "/"))
                    if member_path.is_absolute() or ".." in member_path.parts:
                        errors.append(
                            f"support ZIP contains path traversal member: {member.filename}"
                        )
                    unix_mode = (member.external_attr >> 16) & 0o170000
                    if unix_mode == 0o120000:
                        errors.append(f"support ZIP contains symbolic link: {member.filename}")

        ai_record: dict[str, Any] | None = None
        ai_path: Path | None = None
        if args.ai_disclosure:
            ai_path = resolve_path(args.ai_disclosure, root).resolve()
            if not ai_path.is_file():
                raise ValueError(f"AI disclosure does not exist: {args.ai_disclosure}")
            ai_record = file_record(ai_path, root, "ai_disclosure")
        if ai_required and ai_format == "none":
            errors.append("profile is inconsistent: AI disclosure is required but ai_disclosure_format is none")
        if ai_policy == "prohibited" and ai_used:
            errors.append("run_manifest records AI use but the pinned profile prohibits AI disclosure/use")
        if ai_required:
            if needs_separate_file and ai_record is None:
                errors.append("AI disclosure file is required by the pinned profile and recorded AI usage")
            if needs_in_paper and "ai_report_in_paper" not in completed_manual:
                errors.append("S1 human checkpoint must include 'ai_report_in_paper' manual check for in-paper AI disclosure")
        if ai_policy == "prohibited" and ai_record is not None:
            errors.append("AI disclosure file is prohibited by this profile")
        if ai_record is not None and not ai_used:
            errors.append("AI disclosure file was provided but AI usage is not declared as used")
        if ai_record is not None and not needs_separate_file and ai_format != "none":
            errors.append(f"AI disclosure file provided but profile requires ai_disclosure_format={ai_format}, not a separate file")
        if ai_used and "ai_disclosure_in_support" in required_manual and ai_path is not None:
            zip_paths = [path for path in support_paths if path.suffix.lower() == ".zip"]
            if zip_paths:
                expected_hash = sha256_file(ai_path)
                matched = False
                for archive_path in zip_paths:
                    with zipfile.ZipFile(archive_path) as archive:
                        for member in archive.infolist():
                            if member.is_dir() or PurePosixPath(member.filename).name != ai_path.name:
                                continue
                            archived_hash = hashlib.sha256(archive.read(member)).hexdigest()
                            if archived_hash == expected_hash:
                                matched = True
                                break
                    if matched:
                        break
                if not matched:
                    errors.append("support ZIP does not contain the current AI disclosure file with matching SHA-256")
            else:
                warnings.append("AI disclosure support-package containment was not auto-verified; keep the S1 manual check for non-ZIP archives")

        final_records = [paper_record, *support_records, *([ai_record] if ai_record else [])]
        for record in final_records:
            checkpoint_paths = {path for path, _ in checkpoint_refs}
            checkpoint_artifact_ids = {
                ref.get("artifact_id") for ref in (selected_checkpoint or {}).get("artifacts", [])
                if isinstance(ref, dict) and isinstance(ref.get("artifact_id"), str)
            }
            if (record["path"], record["sha256"]) not in checkpoint_refs and record["path"] not in checkpoint_paths and not (record.get("artifact_id") and record["artifact_id"] in checkpoint_artifact_ids):
                errors.append(f"S1 human checkpoint does not cover final artifact: {record['path']}")

        inputs = [
            paper_record,
            *support_records,
            *([ai_record] if ai_record else []),
        ]
        report = {
            "schema_version": "1.1",
            "ok": not errors,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "competition_profile_id": profile.get("profile_id"),
            "competition_profile_sha256": sha256_json(profile),
            "submission_rules_sha256": sha256_json(rules),
            "ai_usage_sha256": sha256_json(ai_usage_snapshot(manifest)),
            "ai_usage_state": ai_state,
            "s1_checkpoint": (
                {
                    "checkpoint_id": selected_checkpoint.get("checkpoint_id"),
                    "sha256": sha256_json(selected_checkpoint),
                }
                if selected_checkpoint is not None
                else None
            ),
            "page_count_scope": rules.get("page_count_scope"),
            "page_count": {
                "total_pages": args.paper_pages,
                "body_pages": body_pages,
                "page_count_method": args.page_count_method,
                "max_pages": max_pages,
                "max_pages_excludes_ai_report": excludes_ai_report,
                "ai_report_pages": recorded_ai_report_pages,
                "limited_pages": effective_pages,
            },
            "inputs": inputs,
            "errors": errors,
            "warnings": warnings,
        }
        write_json(output_path, report, overwrite=args.force)
    except (OSError, ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": report["ok"], "output": rel_path(output_path, root)}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
