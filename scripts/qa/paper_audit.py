"""Read-only diagnostics for a draft TeX paper outside the Gate sequence."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from _common import load_structured, rel_path, sha256_file
from latex.safe_build import tree_hash
from qa.audit_paper_length import evaluate_length_audit
from qa.check_citations import extract_citations
from qa.tex_source import TexSource, load_tex_source


SECTION_RE = re.compile(r"\\(?:chapter|section)\*?\s*\{([^{}]+)\}", re.IGNORECASE)
BIBLIO_RE = re.compile(r"参考文献|References", re.IGNORECASE)
CONCLUSION_RE = re.compile(r"结论|总结|建议|conclusions?|recommendations?", re.IGNORECASE)
OVERFULL_RE = re.compile(r"Overfull \\hbox \(([0-9]+(?:\.[0-9]+)?)pt too wide\)")
PLACEHOLDER_RE = re.compile(r"\\baominghao\{(?:20\d{2}0{6,}|0{6,}|(?:TODO|TBD|PLACEHOLDER))\}", re.IGNORECASE)
ABSTRACT_TITLE_RE = re.compile(r"(?m)^\s*(?:摘\s*要|Abstract)\s*$", re.IGNORECASE)
KEYWORDS_RE = re.compile(r"(?m)^\s*(?:关键字|关键词|Keywords?)\s*[:：]", re.IGNORECASE)


def _inside(root: Path, raw: str) -> Path:
    path = (root / raw).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"input escapes project root: {raw}") from exc
    if not path.is_file():
        raise ValueError(f"input file does not exist: {raw}")
    return path


def _finding(check: str, severity: str, message: str, root: Path, source: TexSource | None = None, offset: int | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"check": check, "severity": severity, "message": message}
    if source is not None and offset is not None:
        location = source.location(offset)
        if location is not None:
            row["location"] = {"path": rel_path(location[0], root), "line": location[1]}
    return row


def _pdf_pages(path: Path) -> tuple[list[str] | None, str | None]:
    if shutil.which("pdftotext") is None:
        return None, "pdftotext is unavailable"
    result = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if result.returncode != 0:
        return None, f"pdftotext exited {result.returncode}: {result.stderr.strip()}"
    text = result.stdout.rstrip("\r\n")
    pages = text.split("\f")
    if text.endswith("\f"):
        pages.pop()
    return pages, None


def _source_binding(root: Path, tex: Path, pdf: Path | None, receipt: Path | None) -> dict[str, str]:
    if receipt is None:
        return {"status": "unverified", "reason": "no build receipt supplied"}
    value = load_structured(receipt)
    if not isinstance(value, dict):
        raise ValueError("build receipt must be an object")
    if pdf is None:
        return {"status": "unverified", "reason": "no PDF supplied"}
    source_root = value.get("source_root")
    entrypoint = value.get("entrypoint")
    if not isinstance(source_root, str) or not isinstance(entrypoint, str):
        return {"status": "unverified", "reason": "build receipt lacks source root or entrypoint"}
    declared_root = (root / source_root).resolve()
    try:
        declared_root.relative_to(root)
        tex.relative_to(declared_root)
    except ValueError:
        return {"status": "unverified", "reason": "build receipt source root does not contain the TeX entrypoint"}
    entrypoint_path = Path(entrypoint)
    if entrypoint_path.is_absolute() or ".." in entrypoint_path.parts:
        return {"status": "unverified", "reason": "build receipt entrypoint has unsafe path components"}
    if (declared_root / entrypoint).resolve() != tex:
        return {"status": "unverified", "reason": "build receipt names a different TeX entrypoint"}
    output = value.get("output")
    if not isinstance(output, dict) or output.get("path") != rel_path(pdf, root):
        return {"status": "unverified", "reason": "build receipt names a different PDF"}
    expected_tree = value.get("source_tree_sha256_after")
    expected_pdf = output.get("sha256")
    if not isinstance(expected_tree, str) or not isinstance(expected_pdf, str):
        return {"status": "unverified", "reason": "build receipt lacks source-tree or PDF digest"}
    if tree_hash(declared_root) != expected_tree or sha256_file(pdf) != expected_pdf:
        return {"status": "stale", "reason": "build receipt digest differs from current source or PDF"}
    if value.get("ok") is not True or value.get("source_unchanged") is not True:
        return {"status": "unverified", "reason": "build receipt was not a successful unchanged-source build"}
    return {"status": "verified", "reason": "source tree and PDF match the build receipt"}


def audit_paper(
    project_root: Path,
    *,
    tex: str,
    pdf: str | None = None,
    log: str | None = None,
    plan: str | None = None,
    build_receipt: str | None = None,
) -> dict[str, Any]:
    root = project_root.resolve()
    tex_path = _inside(root, tex)
    pdf_path = _inside(root, pdf) if pdf else None
    log_path = _inside(root, log) if log else None
    plan_path = _inside(root, plan) if plan else None
    receipt_path = _inside(root, build_receipt) if build_receipt else None
    source = load_tex_source(tex_path, root)
    findings: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    inputs = [{"path": rel_path(path, root), "sha256": sha256_file(path)} for path in source.files]
    for path in (pdf_path, log_path, plan_path, receipt_path):
        if path is not None:
            inputs.append({"path": rel_path(path, root), "sha256": sha256_file(path)})

    sections = [(match.group(1), match.start()) for match in SECTION_RE.finditer(source.text)]
    bibliography = next(((title, offset) for title, offset in sections if BIBLIO_RE.search(title)), None)
    if bibliography is not None and not extract_citations(source.text):
        findings.append(_finding("bibliography_unmapped", "high", "bibliography is present but the visible TeX has no in-text citations", root, source, bibliography[1]))
    placeholder = PLACEHOLDER_RE.search(source.text)
    if placeholder:
        findings.append(_finding("metadata_placeholder", "warning", "registration number resembles a template placeholder; verify the intended submission identity", root, source, placeholder.start()))

    plan_value = load_structured(plan_path) if plan_path else None
    if plan_path and not isinstance(plan_value, dict):
        raise ValueError("paper plan must be an object")
    if isinstance(plan_value, dict):
        planned_conclusion = any(
            isinstance(row, dict) and row.get("section_id") == "conclusion"
            for row in plan_value.get("sections", [])
        )
        if planned_conclusion and not any(CONCLUSION_RE.search(title) for title, _ in sections):
            findings.append(_finding("missing_conclusion", "high", "paper plan declares a conclusion, but no standalone conclusion section is visible", root))
    else:
        skipped.append({"check": "plan_alignment", "reason": "no paper plan supplied"})

    if log_path is None:
        skipped.append({"check": "overfull_boxes", "reason": "no TeX log supplied"})
    else:
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        widths = [(float(match.group(1)), log_text.count("\n", 0, match.start()) + 1) for match in OVERFULL_RE.finditer(log_text)]
        if widths:
            width, line = max(widths)
            severity = "high" if width >= 50 else "warning"
            findings.append({"check": "overfull_boxes", "severity": severity, "message": f"TeX log reports {len(widths)} overfull box(es); widest is {width:g} pt", "location": {"path": rel_path(log_path, root), "line": line}})

    pages, pdf_error = _pdf_pages(pdf_path) if pdf_path else (None, "no PDF supplied")
    if pages is None:
        skipped.append({"check": "pdf_layout", "reason": str(pdf_error)})
    else:
        starts = [index for index, page in enumerate(pages[:4], start=1) if ABSTRACT_TITLE_RE.search(page)]
        ends = [index for index, page in enumerate(pages[:4], start=1) if KEYWORDS_RE.search(page)]
        if starts and ends and min(ends) >= min(starts):
            span = min(ends) - min(starts) + 1
            if span > 1:
                findings.append(_finding("abstract_spans_pages", "high", f"abstract occupies {span} PDF pages (pages {min(starts)}–{min(ends)})", root))
        else:
            skipped.append({"check": "abstract_page_span", "reason": "abstract or keyword boundary cannot be located in extracted PDF text"})

    if isinstance(plan_value, dict):
        profile_path = root / "competition_profile.json"
        profile_value = load_structured(profile_path) if profile_path.is_file() else None
        if isinstance(profile_value, dict):
            length = evaluate_length_audit(plan_value, profile_value, source.text, page_count=len(pages) if pages is not None else None)
            for row in length["triage"]:
                if row["kind"] == "PAGE_LIMIT_EXCEEDED":
                    severity = "high" if profile_value.get("status") == "verified" else "warning"
                    findings.append(_finding("page_limit", severity, f"PDF has {len(pages)} pages; declared limit is {length['summary']['page_limit']} (profile={profile_value.get('status')})", root))
        else:
            skipped.append({"check": "length_audit", "reason": "no competition profile supplied by project"})

    return {
        "ok": not any(row["severity"] == "high" for row in findings),
        "schema_version": "1.0",
        "gate_effect": "none",
        "project": str(root),
        "inputs": inputs,
        "source_binding": _source_binding(root, tex_path, pdf_path, receipt_path),
        "pdf_pages": len(pages) if pages is not None else None,
        "findings": findings,
        "skipped_checks": skipped,
    }
