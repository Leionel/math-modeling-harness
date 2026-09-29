#!/usr/bin/env python3
"""Create the immutable F1 submission manifest after a passing S1 report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _common import ai_usage_hash_matches, confirmed_checkpoints, human_confirmed_checkpoints, load_structured, rel_path, resolve_path, sha256_file, sha256_json, write_json  # noqa: E402
from runtime_state import load_runtime_state  # noqa: E402


def submission_file(
    path: Path,
    root: Path,
    *,
    pages: int | None = None,
    method: str | None = None,
    limited_pages: int | None = None,
    ai_report_pages: int | None = None,
    body_pages: int | None = None,
) -> dict[str, Any]:
    return {
        "path": rel_path(path, root),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        **({"pages": pages, "page_count_method": method} if pages is not None or method is not None else {}),
        **({"limited_pages": limited_pages} if limited_pages is not None else {}),
        **({"ai_report_pages": ai_report_pages} if ai_report_pages is not None else {}),
        **({"body_pages": body_pages} if body_pages is not None else {}),
    }


def _freeze_submission_v2(
    *,
    root: Path,
    manifest_path: Path,
    report_path: Path,
    paper_path: Path,
    support_paths: list[Path],
    ai_path: Path | None,
    deadline: str,
    timezone_name: str,
    output_path: Path,
) -> int:
    """Build F1 from the standalone profile and rehashed final chain."""

    state = load_runtime_state(manifest_path, project_root=root, allow_legacy=False)
    manifest = state.manifest
    profile = state.profile
    errors: list[str] = []
    gate_check = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "qa" / "check_gates.py"), "--project-root", str(root), "--manifest", str(manifest_path), "--gate", "s1"],
        text=True, capture_output=True, encoding="utf-8", errors="replace", check=False,
    )
    if gate_check.returncode != 0:
        errors.append("F1 requires a factually passing S1 gate")
    if state.preset != "submission":
        errors.append("F1 requires preset=submission")
    if profile.get("status") != "verified":
        errors.append("F1 requires canonical competition profile status=verified")
    if not isinstance(profile.get("official_rules"), list) or not profile.get("official_rules"):
        errors.append("F1 requires non-empty canonical official_rules")
    if not isinstance(profile.get("official_submission_endpoints"), list) or not profile.get("official_submission_endpoints"):
        errors.append("F1 requires non-empty canonical official_submission_endpoints")
    rules = profile.get("submission")
    if not isinstance(rules, dict):
        errors.append("F1 requires canonical submission rules")
        rules = {}
    if not report_path.is_file() or not isinstance(load_structured(report_path), dict):
        errors.append("S1 report does not exist or is not an object")
    else:
        report = load_structured(report_path)
        if report.get("ok") is not True:
            errors.append("S1 report does not have ok=true")
        if report.get("competition_profile_sha256") != sha256_json(profile):
            errors.append("S1 report competition profile hash is stale")
        if report.get("submission_rules_sha256") != sha256_json(rules):
            errors.append("S1 report submission rules hash is stale")
        if not ai_usage_hash_matches(report.get("ai_usage_sha256"), manifest):
            errors.append("S1 report AI usage hash is stale")
        report_inputs = {(row.get("role"), row.get("path")): row.get("sha256") for row in report.get("inputs", []) if isinstance(row, dict)}
        for role, path in [("paper", paper_path), *(('support', value) for value in support_paths), *(('ai_disclosure', ai_path) for _ in [0] if ai_path is not None)]:
            if not path.is_file():
                errors.append(f"final submission artifact does not exist: {path}")
                continue
            if report_inputs.get((role, rel_path(path, root))) != sha256_file(path):
                errors.append(f"S1 report does not cover current {role} artifact: {rel_path(path, root)}")
    for path in [paper_path, *support_paths, *([ai_path] if ai_path else [])]:
        if path is None or not path.is_file():
            errors.append(f"final submission artifact does not exist: {path}")
    if errors:
        raise ValueError("; ".join(errors))
    report = load_structured(report_path)
    paper_input = next((row for row in report.get("inputs", []) if isinstance(row, dict) and row.get("role") == "paper"), None)
    page_count = report.get("page_count")
    if not isinstance(paper_input, dict) or not isinstance(page_count, dict):
        raise ValueError("S1 report lacks auditable paper/page_count inputs")
    total_pages, ai_report_pages, limited_pages = page_count.get("total_pages"), page_count.get("ai_report_pages"), page_count.get("limited_pages")
    body_pages = page_count.get("body_pages")
    counted_pages = body_pages if rules.get("page_count_scope") == "paper_body" else total_pages
    if (not all(isinstance(value, int) for value in (total_pages, ai_report_pages, limited_pages, counted_pages))
            or total_pages < 1 or counted_pages < 1 or counted_pages > total_pages
            or ai_report_pages < 0 or ai_report_pages >= counted_pages
            or limited_pages != counted_pages - ai_report_pages):
        raise ValueError("S1 report page-count relation is invalid")
    max_pages = rules.get("max_pages")
    if isinstance(max_pages, int) and limited_pages > max_pages:
        raise ValueError("S1 report limited_pages exceeds canonical maximum")
    if not rules.get("max_pages_excludes_ai_report") and ai_report_pages != 0:
        raise ValueError("S1 report excludes AI pages but profile does not allow it")
    paper_record = submission_file(paper_path, root, pages=paper_input.get("pages"), method=paper_input.get("page_count_method"), limited_pages=limited_pages, ai_report_pages=ai_report_pages, body_pages=body_pages)
    support_records = [submission_file(path, root) for path in support_paths]
    ai_record = submission_file(ai_path, root) if ai_path else None
    package_hash = sha256_json({"paper": paper_record, "support_files": support_records, "ai_disclosure": ai_record})
    try:
        datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("--deadline must be ISO-8601") from exc
    if not timezone_name.strip():
        raise ValueError("--timezone must be non-empty")
    rule_refs: list[dict[str, str]] = []
    for rule in profile.get("official_rules", []):
        snapshot = rule.get("snapshot") if isinstance(rule, dict) else None
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("path"), str):
            raise ValueError("canonical rule snapshot must have a path")
        snapshot_path = resolve_path(snapshot["path"], root).resolve()
        if not snapshot_path.is_file():
            raise ValueError(f"official rule snapshot does not exist: {snapshot['path']}")
        rule_refs.append({"path": rel_path(snapshot_path, root), "sha256": sha256_file(snapshot_path)})
    submission = {
        "schema_version": "1.1", "project_id": manifest["project_id"], "run_id": manifest["run_id"],
        "status": "final_frozen", "frozen_at": datetime.now(timezone.utc).isoformat(),
        "competition": {
            "profile_id": profile["profile_id"],
            "competition": profile.get("competition", {}).get("name", profile.get("profile_id")) if isinstance(profile.get("competition"), dict) else profile.get("competition"),
            "season": profile.get("competition", {}).get("season", "unknown") if isinstance(profile.get("competition"), dict) else str(profile.get("season", "unknown")),
            "profile_sha256": sha256_json(profile), "rule_snapshots": rule_refs,
        },
        "deadline": {"closes_at": deadline, "timezone": timezone_name}, "paper": paper_record,
        "support_files": support_records, "ai_disclosure": ai_record,
        "s1_report": {"path": rel_path(report_path, root), "sha256": sha256_file(report_path)},
        "run_manifest": {"path": rel_path(manifest_path, root), "sha256": sha256_file(manifest_path)},
        "package_sha256": package_hash, "builder": {"name": "freeze_submission.py", "version": "2.0"},
    }
    write_json(output_path, submission)
    print(json.dumps({"status": "final_frozen", "output": rel_path(output_path, root), "package_sha256": package_hash,
                      "profile_status": profile.get("status"), "warning": "F1 rehashed the canonical final PDF/package chain"}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-manifest", required=True)
    parser.add_argument("--s1-report", required=True)
    parser.add_argument("--paper", required=True)
    parser.add_argument("--support", action="append", default=[])
    parser.add_argument("--ai-disclosure")
    parser.add_argument("--deadline", required=True)
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    manifest_path = resolve_path(args.run_manifest, root).resolve()
    report_path = resolve_path(args.s1_report, root).resolve()
    output_path = resolve_path(args.output, root).resolve()
    try:
        manifest = load_structured(manifest_path)
        report = load_structured(report_path)
        if not isinstance(manifest, dict) or not isinstance(report, dict):
            raise ValueError("run manifest and S1 report must be objects")
        if manifest.get("schema_version") == "2.0":
            return _freeze_submission_v2(
                root=root,
                manifest_path=manifest_path,
                report_path=report_path,
                paper_path=resolve_path(args.paper, root).resolve(),
                support_paths=[resolve_path(value, root).resolve() for value in args.support],
                ai_path=resolve_path(args.ai_disclosure, root).resolve() if args.ai_disclosure else None,
                deadline=args.deadline,
                timezone_name=args.timezone,
                output_path=output_path,
            )
        gate_check = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "qa" / "check_gates.py"),
                "--project-root", str(root),
                "--manifest", str(manifest_path),
                "--strict",
            ],
            text=True,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        if gate_check.returncode != 0:
            raise ValueError(f"current run manifest does not pass all gates: {gate_check.stdout.strip()}")
        if manifest.get("status") != "submission_ready" or manifest.get("phase") != "submission":
            raise ValueError("F1 requires run_manifest status=submission_ready and phase=submission")
        gates = manifest.get("gates", {})
        if gates.get("w2", {}).get("status") != "pass" or gates.get("s1", {}).get("status") != "pass":
            raise ValueError("F1 requires W2 and S1 pass")
        if report.get("ok") is not True:
            raise ValueError("S1 report does not have ok=true")
        submission_reports = [
            row for row in manifest.get("artifacts", [])
            if isinstance(row, dict) and row.get("role") == "submission_qa"
        ]
        if len(submission_reports) != 1:
            raise ValueError("run manifest must register exactly one submission_qa artifact")
        expected_report = submission_reports[0]
        if (
            resolve_path(expected_report.get("path", ""), root).resolve() != report_path
            or expected_report.get("sha256") != sha256_file(report_path)
        ):
            raise ValueError("supplied S1 report is not the current submission_qa artifact")
        profile = manifest.get("competition_profile")
        if not isinstance(profile, dict):
            raise ValueError("run manifest has no competition profile")
        if report.get("competition_profile_sha256") != sha256_json(profile):
            raise ValueError("S1 report competition profile hash is stale")
        rules = profile.get("submission")
        if not isinstance(rules, dict) or report.get("submission_rules_sha256") != sha256_json(rules):
            raise ValueError("S1 report submission rules hash is stale")
        if not ai_usage_hash_matches(report.get("ai_usage_sha256"), manifest):
            raise ValueError("S1 report AI usage hash is stale")
        s1_checkpoints = [
            row for row in human_confirmed_checkpoints(manifest.get("human_checkpoints", []), "s1")
            if row.get("decision") == "pass"
        ]
        if not s1_checkpoints:
            if any(
                row.get("decision") == "pass"
                for row in confirmed_checkpoints(manifest.get("human_checkpoints", []), "s1")
            ):
                raise ValueError("current S1 human checkpoint was recorded by an agent; a human must confirm it")
            raise ValueError("current run manifest has no passing S1 human checkpoint")
        current_checkpoint = s1_checkpoints[-1]
        report_checkpoint = report.get("s1_checkpoint")
        if not isinstance(report_checkpoint, dict) or (
            report_checkpoint.get("checkpoint_id") != current_checkpoint.get("checkpoint_id")
            or report_checkpoint.get("sha256") != sha256_json(current_checkpoint)
        ):
            raise ValueError("S1 report human checkpoint hash is stale")

        paper_path = resolve_path(args.paper, root).resolve()
        support_paths = [resolve_path(value, root).resolve() for value in args.support]
        ai_path = resolve_path(args.ai_disclosure, root).resolve() if args.ai_disclosure else None
        for path in [paper_path, *support_paths, *([ai_path] if ai_path else [])]:
            if path is None or not path.is_file():
                raise ValueError(f"final submission artifact does not exist: {path}")
        report_inputs = {
            (row.get("role"), row.get("path")): row.get("sha256")
            for row in report.get("inputs", [])
            if isinstance(row, dict)
        }
        expected = [
            ("paper", paper_path),
            *(("support", path) for path in support_paths),
            *(("ai_disclosure", ai_path) for _ in [0] if ai_path is not None),
        ]
        for role, path in expected:
            key = (role, rel_path(path, root))
            if report_inputs.get(key) != sha256_file(path):
                raise ValueError(f"S1 report does not cover current {role} artifact: {key[1]}")

        paper_input = next(row for row in report["inputs"] if row.get("role") == "paper")
        page_count = report.get("page_count")
        if not isinstance(page_count, dict):
            raise ValueError("S1 report has no auditable page_count record")
        if (
            page_count.get("total_pages") != paper_input.get("pages")
            or page_count.get("page_count_method") != paper_input.get("page_count_method")
        ):
            raise ValueError("S1 report page_count record does not match its paper input")
        if (
            page_count.get("max_pages") != rules.get("max_pages")
            or page_count.get("max_pages_excludes_ai_report")
            != bool(rules.get("max_pages_excludes_ai_report"))
        ):
            raise ValueError("S1 report page_count policy does not match current submission rules")
        total_pages = page_count.get("total_pages")
        ai_report_pages = page_count.get("ai_report_pages")
        limited_pages = page_count.get("limited_pages")
        body_pages = page_count.get("body_pages")
        counted_pages = body_pages if rules.get("page_count_scope") == "paper_body" else total_pages
        if not all(isinstance(value, int) for value in (total_pages, ai_report_pages, limited_pages, counted_pages)):
            raise ValueError("S1 report page_count values must be integers")
        if total_pages < 1 or counted_pages < 1 or counted_pages > total_pages or ai_report_pages < 0 or ai_report_pages >= counted_pages:
            raise ValueError("S1 report AI page count is outside the valid range")
        if limited_pages != counted_pages - ai_report_pages:
            raise ValueError("S1 report limited_pages does not equal counted_pages - ai_report_pages")
        max_pages = rules.get("max_pages")
        if isinstance(max_pages, int) and limited_pages > max_pages:
            raise ValueError("S1 report limited_pages exceeds the current competition maximum")
        if not rules.get("max_pages_excludes_ai_report") and ai_report_pages != 0:
            raise ValueError("S1 report excludes AI pages but the current profile does not allow it")
        paper_record = submission_file(
            paper_path,
            root,
            pages=paper_input.get("pages"),
            method=paper_input.get("page_count_method"),
            limited_pages=limited_pages,
            ai_report_pages=ai_report_pages,
            body_pages=body_pages,
        )
        support_records = [submission_file(path, root) for path in support_paths]
        ai_record = submission_file(ai_path, root) if ai_path else None
        package_hash = sha256_json({
            "paper": paper_record,
            "support_files": support_records,
            "ai_disclosure": ai_record,
        })
        try:
            datetime.fromisoformat(args.deadline.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("--deadline must be ISO-8601") from exc
        if not args.timezone.strip():
            raise ValueError("--timezone must be non-empty")
        submission = {
            "schema_version": "1.1",
            "project_id": manifest["project_id"],
            "run_id": manifest["run_id"],
            "status": "final_frozen",
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "competition": {
                "profile_id": profile["profile_id"],
                "competition": profile["competition"],
                "season": profile["season"],
                "profile_sha256": sha256_json(profile),
                "rule_snapshots": [rule["snapshot"] for rule in profile["official_rules"]],
            },
            "deadline": {"closes_at": args.deadline, "timezone": args.timezone},
            "paper": paper_record,
            "support_files": support_records,
            "ai_disclosure": ai_record,
            "s1_report": {"path": rel_path(report_path, root), "sha256": sha256_file(report_path)},
            "run_manifest": {"path": rel_path(manifest_path, root), "sha256": sha256_file(manifest_path)},
            "package_sha256": package_hash,
            "builder": {"name": "freeze_submission.py", "version": "1.1"},
        }
        write_json(output_path, submission)
    except (OSError, ValueError, KeyError, StopIteration, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"status": "final_frozen", "output": rel_path(output_path, root), "package_sha256": package_hash}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
