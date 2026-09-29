#!/usr/bin/env python3
"""Reverse-outline and repetition sweep for a drafted paper section tree.

Deterministic post-draft writing checks that complement numeric provenance QA:
- claim-location: every planned claim is located in the draft through at least
  one anchored argument unit;
- handoff order: every prerequisite anchor appears before its dependent anchor
  (cross-question handoffs included);
- repetition sweep: identical long n-grams repeated across anchor spans are
  reported so a human can compress them;
- reverse outline: the topic sentence and word count of every anchor span,
  emitted as a review artifact.

It finds missing argument wiring; it does not judge style or mathematics.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from _common import load_structured, rel_path, resolve_path  # noqa: E402
from qa.check_writer_package import CJK_CHAR_RE, WORD_RE, _load_tex_tree  # noqa: E402

# Repetition sweep windows: CJK runs of 12+ chars and English runs of 8+ words
# repeated across distinct anchor spans are flagged for human compression.
_CJK_NGRAM = 12
_WORD_NGRAM = 8
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？.!?\n])\s+")
_CJK_RUN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _first_sentence(text: str, limit: int = 120) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    parts = [part for part in _SENTENCE_SPLIT_RE.split(stripped) if part.strip()]
    sentence = parts[0].strip() if parts else stripped
    return sentence[:limit]


def _count_words(text: str) -> int:
    return len(WORD_RE.findall(text)) + len(CJK_CHAR_RE.findall(text))


def _anchor_spans(draft: str, anchors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Locate each anchor span in document order, mirroring first-draft coverage."""

    folded = draft.casefold()
    cursor = 0
    spans: list[dict[str, Any]] = []
    positions: list[tuple[int, int] | None] = []
    for anchor in anchors:
        patterns = [pattern for pattern in anchor.get("patterns", []) if isinstance(pattern, str) and pattern]
        candidate = next(
            (
                (folded.find(pattern.casefold(), cursor), len(pattern))
                for pattern in patterns
                if folded.find(pattern.casefold(), cursor) >= 0
            ),
            None,
        )
        positions.append(candidate)
        if candidate is not None:
            cursor = candidate[0] + candidate[1]
    for index, anchor in enumerate(anchors):
        match = positions[index]
        if match is None:
            spans.append({**anchor, "position": None, "content": ""})
            continue
        next_positions = [row[0] for row in positions[index + 1:] if row is not None]
        end = min(next_positions) if next_positions else len(draft)
        spans.append({**anchor, "position": match[0], "content": draft[match[0] + match[1]:end]})
    return spans


def _prose_paragraphs(draft: str) -> list[dict[str, Any]]:
    """Return rough paragraph offsets for mapping, not for a style verdict."""

    paragraphs: list[dict[str, Any]] = []
    for match in re.finditer(r"(?s)(?<!\S)(.+?)(?=\n\s*\n|\Z)", draft):
        raw = match.group(1).strip()
        if not raw:
            continue
        # Preamble, standalone TeX commands, and locator-only blocks are not
        # reader paragraphs.  Mapping remains deliberately conservative: a
        # paragraph that contains prose but no unit anchor is surfaced for a
        # human to retain, move, or support.
        visible = re.sub(r"(?s)\\[A-Za-z]+(?:\s*\[[^]]*\])?\s*(?:\{[^{}]*\})?", " ", raw)
        visible = re.sub(r"<!--.*?-->|(?<!\\)%[^\r\n]*", " ", visible, flags=re.DOTALL)
        visible = re.sub(r"[{}$\\]", " ", visible)
        if not re.search(r"[A-Za-z\u3400-\u9fff]", visible):
            continue
        if raw.lstrip().startswith(("\\documentclass", "\\usepackage", "\\begin", "\\end")):
            continue
        if all(line.strip().startswith("#") for line in raw.splitlines() if line.strip()):
            continue
        paragraphs.append({"position": match.start(), "content": raw})
    return paragraphs


def _map_outline_rows(
    plan: dict[str, Any],
    spans: list[dict[str, Any]],
    draft: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Map paragraph claims to existing section and central theses.

    The mapping is a derived review view.  It does not infer new claims: an
    anchor contributes only the claim IDs and section already declared by its
    argument unit.  Paragraphs outside all located spans are listed with a
    human action instead of being silently assigned to a unit.
    """

    sections = {
        row.get("section_id"): row
        for row in plan.get("sections", [])
        if isinstance(row, dict) and isinstance(row.get("section_id"), str)
    }
    units = {
        row.get("unit_id"): row
        for row in plan.get("argument_units", [])
        if isinstance(row, dict) and isinstance(row.get("unit_id"), str)
    }
    central = plan.get("central_thesis") if isinstance(plan.get("central_thesis"), dict) else {}
    central_text = central.get("text")
    rows: list[dict[str, Any]] = []
    located = sorted(
        [row for row in spans if row.get("position") is not None],
        key=lambda row: row["position"],
    )
    for span in spans:
        unit = units.get(span.get("unit_id"), {})
        section_id = unit.get("section_id")
        section = sections.get(section_id, {})
        claim_ids = [
            claim_id for claim_id in unit.get("claim_ids", [])
            if isinstance(claim_id, str)
        ]
        mapped = span.get("position") is not None and bool(unit)
        paragraphs = _prose_paragraphs(span.get("content", "")) or [{"content": span.get("content", "")}]
        for index, paragraph in enumerate(paragraphs, start=1):
            content = paragraph["content"]
            rows.append({
                "anchor_id": span.get("anchor_id"),
                "paragraph_index": index,
                "unit_id": span.get("unit_id"),
                "paragraph_claims": claim_ids,
                "section_id": section_id,
                "section_thesis": section.get("purpose"),
                "central_thesis": central_text,
                "topic_sentence": _first_sentence(content),
                "words": _count_words(content),
                "mapping_status": "mapped" if mapped else "unmapped",
                "action": "retain" if mapped else "locate anchor, then retain/move or add evidence",
            })

    # A paragraph is mapped to the span whose anchor starts its block.  This
    # prevents an ordinary prose paragraph between two labels from being
    # misclassified as a new, unplanned argument unit.
    ranges: list[tuple[int, int]] = []
    for index, span in enumerate(located):
        end = located[index + 1]["position"] if index + 1 < len(located) else len(draft)
        ranges.append((span["position"], end))
    unmapped: list[dict[str, Any]] = []
    for paragraph in _prose_paragraphs(draft):
        position = paragraph["position"]
        if any(start <= position < end for start, end in ranges):
            continue
        unmapped.append({
            "topic_sentence": _first_sentence(paragraph["content"]),
            "words": _count_words(paragraph["content"]),
            "mapping_status": "unmapped",
            "action": "delete, move to an existing argument unit, or add the evidence needed to keep it",
        })
    return rows, unmapped


def _repetition_findings(spans: list[dict[str, Any]]) -> list[str]:
    """Report identical long n-grams that appear in two or more anchor spans."""

    seen: dict[str, str] = {}  # n-gram -> first anchor_id
    findings: dict[str, list[str]] = {}
    for span in spans:
        if span.get("position") is None or not span.get("content"):
            continue
        anchor_id = str(span.get("anchor_id"))
        normalized = _norm(span["content"])
        word_tokens = WORD_RE.findall(span["content"])
        grams: set[str] = set()
        for run in _CJK_RUN_RE.findall(normalized):
            for start in range(0, max(1, len(run) - _CJK_NGRAM + 1)):
                grams.add(run[start:start + _CJK_NGRAM])
        for start in range(0, max(1, len(word_tokens) - _WORD_NGRAM + 1)):
            grams.add(" ".join(word_tokens[start:start + _WORD_NGRAM]).casefold())
        for gram in grams:
            first = seen.get(gram)
            if first is None:
                seen[gram] = anchor_id
            elif first != anchor_id:
                findings.setdefault(first, []).append(anchor_id)
    return [
        f"anchor {first} and anchor {', '.join(sorted(set(others)))} repeat the same long passage; compress instead of restating"
        for first, others in sorted(findings.items())
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-plan", required=True)
    parser.add_argument("--writer-package")
    parser.add_argument("--draft", required=True)
    parser.add_argument("--outline-report", help="optional markdown reverse-outline report path")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    try:
        plan = load_structured(resolve_path(args.paper_plan, root).resolve())
        draft = _load_tex_tree(resolve_path(args.draft, root).resolve(), root)
        package = None
        if args.writer_package:
            package = load_structured(resolve_path(args.writer_package, root).resolve())
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)], "warnings": []}, ensure_ascii=False, indent=2))
        return 1
    if not isinstance(plan, dict):
        print(json.dumps({"ok": False, "errors": ["paper plan must be an object"], "warnings": []}, ensure_ascii=False, indent=2))
        return 1

    coverage = plan.get("draft_coverage") if isinstance(plan.get("draft_coverage"), dict) else None
    if package is not None and isinstance(package.get("draft_coverage"), dict):
        coverage = package["draft_coverage"]
    if coverage is None:
        print(json.dumps({
            "ok": False,
            "errors": ["reverse outline requires paper_plan.draft_coverage anchors"],
            "warnings": [],
        }, ensure_ascii=False, indent=2))
        return 1
    anchors = [row for row in coverage.get("anchors", []) if isinstance(row, dict)]
    if not anchors:
        print(json.dumps({
            "ok": False,
            "errors": ["draft_coverage.anchors is empty; nothing to reverse-outline"],
            "warnings": [],
        }, ensure_ascii=False, indent=2))
        return 1

    spans = _anchor_spans(draft, anchors)
    for span in spans:
        if span.get("position") is None:
            errors.append(f"anchor {span.get('anchor_id')} (unit {span.get('unit_id')}) cannot be located in the draft")

    units = {
        row.get("unit_id"): row
        for row in plan.get("argument_units", [])
        if isinstance(row, dict)
    }
    span_by_unit = {
        span.get("unit_id"): span
        for span in spans
        if span.get("unit_id") is not None
    }

    # Handoff order: a prerequisite anchor must appear before its dependent.
    for unit in units.values():
        dependent = span_by_unit.get(unit.get("unit_id"))
        if dependent is None or dependent.get("position") is None:
            continue
        for prerequisite in unit.get("prerequisite_unit_ids", []):
            source = span_by_unit.get(prerequisite)
            if source is None or source.get("position") is None:
                continue
            if source["position"] >= dependent["position"]:
                source_section = units.get(prerequisite, {}).get("section_id")
                dependent_section = unit.get("section_id")
                scope = "cross-section handoff" if source_section != dependent_section else "in-section dependency"
                errors.append(
                    f"{scope} reversed: unit {prerequisite} appears at or after dependent unit "
                    f"{unit.get('unit_id')} in the draft"
                )

    # Claim-location: every planned claim must be anchored somewhere.
    for claim in plan.get("claims", []):
        if not isinstance(claim, dict):
            continue
        claim_id = claim.get("claim_id")
        anchored = any(
            isinstance(unit, dict) and claim_id in unit.get("claim_ids", [])
            and span_by_unit.get(unit.get("unit_id"), {}).get("position") is not None
            for unit in units.values()
        )
        if not anchored:
            errors.append(f"claim {claim_id} has no located argument anchor in the draft")

    warnings.extend(_repetition_findings(spans))

    outline, unmapped_paragraphs = _map_outline_rows(plan, spans, draft)
    ok = not errors and (not args.strict or not warnings)
    if args.outline_report:
        report_path = resolve_path(args.outline_report, root).resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# Reverse Outline", ""]
        for row in outline:
            lines.append(
                f"- `{row['anchor_id']}` ({row['words']} words; {row['mapping_status']}): "
                f"{row['topic_sentence']} -> {row.get('section_id')} -> {row.get('central_thesis')}"
            )
        lines.append("")
        if unmapped_paragraphs:
            lines.append("## Unmapped paragraphs")
            lines.append("")
            lines.extend(
                f"- ({row['words']} words; action: {row['action']}): {row['topic_sentence']}"
                for row in unmapped_paragraphs
            )
            lines.append("")
        if warnings:
            lines.append("## Repetition findings")
            lines.append("")
            lines.extend(f"- {warning}" for warning in warnings)
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "ok": ok,
        "paper_plan": rel_path(resolve_path(args.paper_plan, root).resolve(), root),
        "draft": rel_path(resolve_path(args.draft, root).resolve(), root),
        "anchors_located": sum(1 for span in spans if span.get("position") is not None),
        "anchors_total": len(spans),
        "claims_located": sum(
            1
            for claim in plan.get("claims", [])
            if isinstance(claim, dict)
            and any(
                isinstance(unit, dict) and claim.get("claim_id") in unit.get("claim_ids", [])
                and span_by_unit.get(unit.get("unit_id"), {}).get("position") is not None
                for unit in units.values()
            )
        ),
        "claims_total": len([row for row in plan.get("claims", []) if isinstance(row, dict)]),
        "reverse_outline": outline,
        "unmapped_paragraphs": unmapped_paragraphs,
        "errors": errors,
        "warnings": warnings,
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
