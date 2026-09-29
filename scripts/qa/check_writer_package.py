#!/usr/bin/env python3
"""Reject draft text that introduces research facts absent from a writer package."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from _common import load_structured, rel_path, resolve_path  # noqa: E402
from qa.reader_integrity import (  # noqa: E402
    collect_registered_internal_ids,
    evaluate_figure_reader_bindings,
    exposed_identifiers,
    source_issues,
)
from qa.tex_source import load_tex_source  # noqa: E402


NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?(?![A-Za-z0-9_])")
WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*")
CJK_CHAR_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
CAUSAL_MARKERS = ("导致", "造成", "使得", "证明", "表明", "because", "therefore", "causes", "demonstrates")
STRONG_CAUSAL_MARKERS = ("导致", "造成", "使得", "causes", "because")
STRENGTH_MARKERS = ("最优", "显著", "稳健", "提升", "optimal", "significant", "robust", "improve")


def _strip_latex_comments(text: str) -> str:
    """Remove TeX comments while retaining escaped percent signs."""
    return re.sub(r"(?<!\\)%[^\r\n]*", "", text)


def _strip_invisible_comments(text: str) -> str:
    """Remove TeX and Markdown/HTML comments that cannot reach rendered prose."""

    return re.sub(r"<!--.*?-->", "", _strip_latex_comments(text), flags=re.DOTALL)


def _load_tex_tree(path: Path, project_root: Path | None = None) -> str:
    """Expand the same project-contained source used by the other paper checks."""
    return load_tex_source(path, project_root or path.parent).text


def _strength_marker_is_qualified(text: str, marker: str) -> bool:
    """Allow explicit boundary language such as ``不宣称全局最优``."""
    if marker != "最优":
        return False
    folded = text.casefold()
    needle = marker.casefold()
    start = 0
    while True:
        position = folded.find(needle, start)
        if position < 0:
            return True
        context = text[max(0, position - 32):position + len(marker) + 8]
        if "全局最优" in context and any(token in context for token in ("不", "不能", "不是", "无")):
            start = position + len(marker)
            continue
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--writer-package", required=True)
    parser.add_argument("--draft", required=True)
    parser.add_argument(
        "--require-first-draft-coverage",
        action="store_true",
        help="Require every planned argument anchor; declared minimum word spans stay advisory by default.",
    )
    parser.add_argument("--project-root", default=".")
    parser.add_argument(
        "--enforce-minimum-words",
        action="store_true",
        help="Make declared minimum_words spans blocking for an explicitly requested legacy check.",
    )
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    if args.enforce_minimum_words and not args.require_first_draft_coverage:
        print("ERROR: --enforce-minimum-words requires --require-first-draft-coverage", file=sys.stderr)
        return 2


    root = Path(args.project_root).resolve()
    package_path = resolve_path(args.writer_package, root).resolve()
    draft_path = resolve_path(args.draft, root).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    advisories: list[str] = []
    try:
        package = load_structured(package_path)
        draft = draft_path.read_text(encoding="utf-8")
        coverage_draft = _load_tex_tree(draft_path, root)
        numeric_draft = _strip_latex_comments(draft)
        if not isinstance(package, dict) or package.get("schema_version") != "1.0":
            raise ValueError("writer package must have schema_version=1.0")
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)], "warnings": []}, ensure_ascii=False, indent=2))
        return 1
    registered_internal_ids = collect_registered_internal_ids(package)
    exposed_markers = exposed_identifiers(coverage_draft, registered_internal_ids)
    if exposed_markers:
        errors.append(
            "draft exposes internal authoring marker(s) in reader-facing text: "
            + ", ".join(exposed_markers)
        )
    errors.extend(
        issue for issue in source_issues(coverage_draft, registered_internal_ids)
        if "forbidden \\audit" in issue
    )
    figure_errors, figure_details = evaluate_figure_reader_bindings(package, coverage_draft)
    errors.extend(figure_errors)
    allowed_numbers = {
        str(result.get("display_value"))
        for claim in package.get("claims", [])
        if isinstance(claim, dict)
        for result in claim.get("results", [])
        if isinstance(result, dict) and result.get("display_value") is not None
    }
    # The root file contains Harness locator comments such as A-Q2 and R-Q2.
    # They are metadata, not research prose.  Numeric scope is therefore
    # checked on the comment-stripped root, while coverage is checked on the
    # recursively expanded TeX tree so \input sections count as draft text.
    unregistered = sorted({match.group(0) for match in NUMBER_RE.finditer(numeric_draft) if match.group(0) not in allowed_numbers})
    if unregistered:
        errors.append(f"draft contains research numeric token(s) absent from writer package: {', '.join(unregistered)}")
    claims = [claim for claim in package.get("claims", []) if isinstance(claim, dict)]
    has_non_observation = any(claim.get("claim_type") != "observation" for claim in claims)
    if not has_non_observation and any(marker.casefold() in coverage_draft.casefold() for marker in CAUSAL_MARKERS):
        errors.append("draft uses causal/explanatory language without an approved inference or recommendation claim")
    declared_strengths = {
        claim.get("inference_strength")
        for claim in claims
        if isinstance(claim.get("inference_strength"), str)
    }
    if any(marker.casefold() in coverage_draft.casefold() for marker in STRONG_CAUSAL_MARKERS) and "causal" not in declared_strengths:
        errors.append("draft uses strong causal language without an approved causal inference_strength")
    approved_strength = {
        marker
        for claim in claims
        if isinstance(claim.get("comparison"), dict)
        for marker in STRENGTH_MARKERS
        if marker.casefold() in str(claim.get("approved_text", "")).casefold()
    }
    for marker in STRENGTH_MARKERS:
        if marker.casefold() in coverage_draft.casefold() and marker not in approved_strength and not _strength_marker_is_qualified(coverage_draft, marker):
            warnings.append(f"draft uses strength marker {marker!r} without an approved comparative claim")
    if args.require_first_draft_coverage:
        coverage = package.get("draft_coverage")
        if not isinstance(coverage, dict):
            errors.append("formal first-draft QA requires writer_package.draft_coverage")
        else:
            anchors = [row for row in coverage.get("anchors", []) if isinstance(row, dict)]
            if coverage.get("status") not in {"planned", "verified"} or not anchors:
                errors.append("writer_package.draft_coverage must contain planned or verified anchors")
            else:
                folded_draft = coverage_draft.casefold()
                matches: list[tuple[int, int] | None] = []
                cursor = 0
                for anchor in anchors:
                    patterns = [pattern for pattern in anchor.get("patterns", []) if isinstance(pattern, str) and pattern]
                    # Patterns are ordered from the canonical section heading
                    # to fallbacks. Select the first matching pattern so a
                    # repeated result value in the abstract cannot steal the
                    # body span for this argument unit.
                    candidate = next(
                        (
                            (folded_draft.find(pattern.casefold(), cursor), len(pattern))
                            for pattern in patterns
                            if folded_draft.find(pattern.casefold(), cursor) >= 0
                        ),
                        None,
                    )
                    if candidate is None:
                        errors.append(
                            f"draft is missing first-draft anchor {anchor.get('anchor_id')} for unit {anchor.get('unit_id')}"
                        )
                        matches.append(None)
                        continue
                    position, length = candidate
                    matches.append((position, length))
                    cursor = position + length
                for index, match in enumerate(matches):
                    if match is None:
                        continue
                    anchor = anchors[index]
                    next_positions = [row[0] for row in matches[index + 1:] if row is not None]
                    end = min(next_positions) if next_positions else len(coverage_draft)
                    content = coverage_draft[match[0] + match[1]:end]
                    word_count = len(WORD_RE.findall(content)) + len(CJK_CHAR_RE.findall(content))
                    minimum_words = anchor.get("minimum_words", 0)
                    if word_count < minimum_words:
                        message = (
                            f"draft span for anchor {anchor.get('anchor_id')} has {word_count} words, "
                            f"below minimum_words={minimum_words}"
                        )
                        if args.enforce_minimum_words:
                            errors.append(message)
                        else:
                            advisories.append(message)
    ok = not errors and (not args.strict or not warnings)
    print(json.dumps({
        "ok": ok,
        "writer_package": rel_path(package_path, root),
        "draft": rel_path(draft_path, root),
        "first_draft_coverage_required": args.require_first_draft_coverage,
        "first_draft_coverage_verified": args.require_first_draft_coverage and ok,
        "errors": errors,
        "minimum_words_enforced": args.enforce_minimum_words,
        "advisories": advisories,
        "warnings": warnings,
        "reader_integrity": {
            "registered_internal_id_count": len(registered_internal_ids),
            "figure_bindings": figure_details,
        },
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
