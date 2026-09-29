#!/usr/bin/env python3
"""Audit a completed draft after PDF build; emit concise, actionable length triage."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from _common import load_structured, rel_path, resolve_path, write_json  # noqa: E402
from qa.tex_source import load_tex_source  # noqa: E402


WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
COMMENT_RE = re.compile(r"(?<!\\)%[^\r\n]*")
COMMAND_RE = re.compile(r"\\[A-Za-z@]+(?:\[[^\]]*\])?(?:\{[^{}]*\})?")


def _load_tex_tree(path: Path, project_root: Path | None = None) -> str:
    return load_tex_source(path, project_root or path.parent).text


def _count_words(text: str) -> int:
    visible = COMMAND_RE.sub(" ", COMMENT_RE.sub("", text))
    return len(WORD_RE.findall(visible)) + len(CJK_RE.findall(visible))


def _unit_priority(unit: dict[str, Any]) -> str:
    priority = unit.get("depth_priority")
    if isinstance(priority, dict) and priority.get("level") in {
        "core",
        "supporting",
        "compact",
    }:
        return str(priority["level"])
    legacy = unit.get("expected_depth")
    if legacy == "expanded":
        return "core"
    if legacy == "compact":
        return "compact"
    return "supporting"


def _anchor_rows(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    coverage = plan.get("draft_coverage")
    rows = coverage.get("anchors", []) if isinstance(coverage, dict) else []
    return {
        str(row["unit_id"]): row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("unit_id"), str)
    }


def _anchor_spans(
    draft: str, anchors: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    found: list[tuple[int, int, str]] = []
    folded = draft.casefold()
    for unit_id, row in anchors.items():
        patterns = [
            value
            for value in row.get("patterns", [])
            if isinstance(value, str) and value
        ]
        candidate = next(
            (
                (folded.find(pattern.casefold()), len(pattern))
                for pattern in patterns
                if folded.find(pattern.casefold()) >= 0
            ),
            None,
        )
        if candidate is not None:
            found.append((candidate[0], candidate[1], unit_id))
    found.sort()
    spans: dict[str, dict[str, Any]] = {}
    for index, (start, length, unit_id) in enumerate(found):
        end = found[index + 1][0] if index + 1 < len(found) else len(draft)
        spans[unit_id] = {
            "anchor_found": True,
            "word_like_tokens": _count_words(draft[start + length : end]),
        }
    for unit_id in anchors:
        spans.setdefault(unit_id, {"anchor_found": False, "word_like_tokens": 0})
    return spans


def _page_limit(profile: dict[str, Any]) -> int | None:
    submission = profile.get("submission")
    if isinstance(submission, dict) and isinstance(submission.get("max_pages"), int):
        return int(submission["max_pages"])
    rules = profile.get("rules")
    if isinstance(rules, dict) and isinstance(rules.get("page_limit"), int):
        return int(rules["page_limit"])
    return None


def _pdf_page_count(path: Path) -> tuple[int | None, str | None]:
    if shutil.which("pdfinfo") is None:
        return None, "pdfinfo is unavailable; cannot inspect the completed PDF"
    result = subprocess.run(
        ["pdfinfo", str(path)],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return None, result.stderr.strip() or "pdfinfo failed"
    match = re.search(r"^Pages:\s+(\d+)", result.stdout, flags=re.MULTILINE)
    return (
        (int(match.group(1)), None)
        if match
        else (None, "pdfinfo did not report a page count")
    )


def _question_ids(unit: dict[str, Any], claim_questions: dict[str, str]) -> list[str]:
    scope = unit.get("scope")
    if isinstance(scope, dict) and isinstance(scope.get("question_ids"), list):
        ids = [value for value in scope["question_ids"] if isinstance(value, str)]
        if ids:
            return ids
    return sorted(
        {
            claim_questions[claim_id]
            for claim_id in unit.get("claim_ids", [])
            if isinstance(claim_id, str) and claim_id in claim_questions
        }
    )


def evaluate_length_audit(
    plan: dict[str, Any],
    profile: dict[str, Any],
    draft: str,
    *,
    page_count: int | None,
) -> dict[str, Any]:
    """Return post-draft triage without a synthetic allocation score or rank gate."""

    claims = {
        str(row["claim_id"]): str(row["question_id"])
        for row in plan.get("claims", [])
        if isinstance(row, dict)
        and isinstance(row.get("claim_id"), str)
        and isinstance(row.get("question_id"), str)
    }
    anchors = _anchor_rows(plan)
    spans = _anchor_spans(draft, anchors)
    units = [row for row in plan.get("argument_units", []) if isinstance(row, dict)]
    by_question: dict[str, int] = {}
    by_unit: list[dict[str, Any]] = []
    triage: list[dict[str, str]] = []
    errors: list[str] = []
    warnings: list[str] = []

    for unit in units:
        unit_id = str(unit.get("unit_id", "UNIDENTIFIED"))
        priority = _unit_priority(unit)
        span = spans.get(unit_id)
        row = {
            "unit_id": unit_id,
            "section_id": unit.get("section_id"),
            "depth_priority": priority,
            "anchor_declared": unit_id in anchors,
            "anchor_found": span.get("anchor_found") if span else None,
            "word_like_tokens": span.get("word_like_tokens") if span else None,
        }
        by_unit.append(row)
        if span:
            for question_id in _question_ids(unit, claims):
                by_question[question_id] = by_question.get(question_id, 0) + int(
                    span["word_like_tokens"]
                )
        if priority != "core":
            continue
        if unit_id not in anchors:
            warnings.append(
                f"core unit {unit_id} has no draft anchor; its final presence needs human review"
            )
            triage.append(
                {
                    "severity": "HIGH",
                    "kind": "CORE_ARGUMENT_NOT_LOCATABLE",
                    "target": unit_id,
                    "action": "Add a stable draft anchor or inspect the rendered section before W2.",
                }
            )
        elif not span or not span["anchor_found"] or not span["word_like_tokens"]:
            errors.append(
                f"core argument unit {unit_id} is missing or has no visible draft content"
            )
            triage.append(
                {
                    "severity": "HARD",
                    "kind": "CORE_ARGUMENT_MISSING",
                    "target": unit_id,
                    "action": "Restore the planned formulation/comparison/validation argument before length compression.",
                }
            )

    max_pages = _page_limit(profile)
    profile_status = profile.get("status")
    if page_count is None:
        warnings.append(
            "no completed PDF page count was supplied; no approximate page estimate was used"
        )
        triage.append(
            {
                "severity": "HIGH",
                "kind": "PDF_REQUIRED",
                "target": "paper",
                "action": "Build the paper, then rerun this audit with --pdf for actual page and layout review.",
            }
        )
    elif max_pages is None:
        warnings.append("competition profile has no declared page limit")
    elif page_count > max_pages:
        message = f"completed PDF has {page_count} pages; declared limit is {max_pages}"
        if profile_status == "verified":
            errors.append(message)
            severity = "HARD"
        else:
            warnings.append(message + " (profile is not verified)")
            severity = "HIGH"
        triage.append(
            {
                "severity": severity,
                "kind": "PAGE_LIMIT_EXCEEDED",
                "target": "paper",
                "action": "Compress repeated assumptions or move supporting derivations/tables to the appendix, then rebuild the PDF.",
            }
        )

    manual_checks = [
        "Review the rendered PDF for section page spans, figure-heavy pages, orphan headings, and large blank areas.",
        "Confirm any appendix or disclosure page exclusion against the verified competition profile.",
        "Use the triage items to revise argument placement; do not reduce a core argument merely to lower a word count.",
    ]
    if errors:
        verdict = "fail"
    elif page_count is None:
        verdict = "needs_pdf"
    else:
        verdict = "pass_with_manual_layout_review"

    return {
        "schema_version": "1.0",
        "summary": {
            "word_like_tokens": _count_words(draft),
            "pdf_page_count": page_count,
            "page_limit": max_pages,
            "profile_status": profile_status,
            "verdict": verdict,
        },
        "by_question": [
            {"question_id": question_id, "word_like_tokens": count}
            for question_id, count in sorted(by_question.items())
        ],
        "by_unit": by_unit,
        "triage": triage,
        "manual_checks_required": manual_checks,
        "warnings": warnings,
        "errors": errors,
    }


def _human_summary(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        f"Length audit: {summary['verdict']}",
        f"Word-like tokens: {summary['word_like_tokens']}",
        f"PDF pages: {summary['pdf_page_count']}",
        f"Declared limit: {summary['page_limit']}",
    ]
    lines.extend(
        f"{row['severity']}: {row['kind']} — {row['action']}"
        for row in report["triage"]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-plan", required=True)
    parser.add_argument("--competition-profile", required=True)
    parser.add_argument("--draft", required=True, help="LaTeX root or plain-text draft")
    parser.add_argument("--pdf", help="Completed PDF; required for a final page audit")
    parser.add_argument("--output", required=True)
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--format", choices=("json", "human"), default="json")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    plan_path = resolve_path(args.paper_plan, root).resolve()
    profile_path = resolve_path(args.competition_profile, root).resolve()
    draft_path = resolve_path(args.draft, root).resolve()
    output_path = resolve_path(args.output, root).resolve()
    errors: list[str] = []
    try:
        plan = load_structured(plan_path)
        profile = load_structured(profile_path)
        if not isinstance(plan, dict) or not isinstance(profile, dict):
            raise ValueError("paper plan and competition profile must be objects")
        draft = (
            _load_tex_tree(draft_path, root)
            if draft_path.suffix.casefold() == ".tex"
            else draft_path.read_text(encoding="utf-8")
        )
        page_count: int | None = None
        if args.pdf:
            pdf_path = resolve_path(args.pdf, root).resolve()
            if not pdf_path.is_file():
                raise ValueError(f"PDF does not exist: {args.pdf}")
            page_count, pdf_error = _pdf_page_count(pdf_path)
            if pdf_error:
                raise ValueError(pdf_error)
        report = evaluate_length_audit(plan, profile, draft, page_count=page_count)
        report["paper_plan"] = rel_path(plan_path, root)
        report["competition_profile"] = rel_path(profile_path, root)
        report["draft"] = rel_path(draft_path, root)
        report["pdf"] = (
            rel_path(resolve_path(args.pdf, root), root) if args.pdf else None
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
        report = {
            "schema_version": "1.0",
            "summary": {"verdict": "error"},
            "errors": errors,
            "warnings": [],
            "triage": [],
        }

    write_json(output_path, report, overwrite=True)
    print(
        json.dumps(report, ensure_ascii=False, indent=2)
        if args.format == "json"
        else _human_summary(report)
    )
    return 0 if report["summary"]["verdict"] == "pass_with_manual_layout_review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
