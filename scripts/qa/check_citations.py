#!/usr/bin/env python3
"""Deterministically check LaTeX citations, labels, references, and figures."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

from _common import load_structured, rel_path, resolve_path  # noqa: E402
from qa.tex_source import load_tex_source  # noqa: E402


def unique_duplicates(items: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return {key: count for key, count in counts.items() if count > 1}


def strip_comments(text: str) -> str:
    return re.sub(r"(?m)(?<!\\)%.*$", "", text)


def extract_citations(text: str) -> list[str]:
    values: list[str] = []
    pattern = r"\\(?:cite|parencite|textcite|autocite)[a-zA-Z]*\*?\s*(?:\[[^]]*\]\s*)*\{([^}]*)\}"
    for match in re.findall(pattern, text):
        values.extend(key.strip() for key in match.split(",") if key.strip())
    return values


def extract_bib_keys(text: str) -> list[str]:
    return [key.strip() for key in re.findall(r"@\w+\s*[\{(]\s*([^,\s]+)\s*,", text)]


def extract_labels(text: str) -> list[str]:
    return re.findall(r"\\label\{([^}]*)\}", text)


def extract_refs(text: str) -> list[str]:
    return re.findall(r"\\(?:ref|cref|Cref|autoref|eqref)\{([^}]*)\}", text)


def extract_figures(text: str) -> list[str]:
    return re.findall(r"\\includegraphics(?:\[[^]]*\])?\{([^}]*)\}", text)


def load_tex_tree(main_path: Path, project_root: Path | None = None) -> tuple[list[Path], list[str]]:
    source = load_tex_source(main_path, project_root or main_path.parent)
    return list(source.files), [source.text]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--tex")
    source.add_argument("--tex-dir")
    parser.add_argument("--bib", required=True)
    parser.add_argument("--check-figures", action="store_true")
    parser.add_argument("--figures-dir")
    parser.add_argument("--evidence-registry")
    parser.add_argument("--require-verified-bibliography", action="store_true")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    if args.require_verified_bibliography and not args.evidence_registry:
        errors.append("--require-verified-bibliography requires --evidence-registry")
    if args.tex:
        main_tex = resolve_path(args.tex, root).resolve()
        try:
            tex_files, tex_parts = load_tex_tree(main_tex, root)
        except (OSError, ValueError) as exc:
            tex_files, tex_parts = [main_tex], []
            errors.append(f"cannot read LaTeX tree from {main_tex}: {exc}")
    else:
        tex_dir = resolve_path(args.tex_dir, root).resolve()
        tex_files = sorted(tex_dir.rglob("*.tex")) if tex_dir.is_dir() else []
        tex_parts = []
    if not tex_files:
        errors.append("no .tex files found")

    if not args.tex:
        for path in tex_files:
            try:
                tex_parts.append(strip_comments(path.read_text(encoding="utf-8", errors="replace")))
            except OSError as exc:
                errors.append(f"cannot read {path}: {exc}")
    tex = "\n".join(tex_parts)

    bib_path = resolve_path(args.bib, root).resolve()
    try:
        bib = bib_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        errors.append(f"cannot read bib file {bib_path}: {exc}")
        bib = ""
    embedded = re.findall(r"\\begin\{filecontents\}(?:\{[^}]+\})?(.*?)\\end\{filecontents\}", tex, re.DOTALL)
    if embedded:
        bib = bib + "\n" + "\n".join(embedded)

    cite_keys = extract_citations(tex)
    bib_keys = extract_bib_keys(bib)
    labels = extract_labels(tex)
    refs = extract_refs(tex)
    figure_refs = extract_figures(tex)
    cite_set = set(cite_keys)
    bib_set = set(bib_keys)
    label_set = set(labels)

    missing_citations = sorted(cite_set - bib_set)
    if missing_citations:
        errors.append("missing citation keys: " + ", ".join(missing_citations))
    duplicate_bib = unique_duplicates(bib_keys)
    if duplicate_bib:
        errors.append("duplicate BibTeX keys: " + ", ".join(sorted(duplicate_bib)))
    undefined_refs = sorted(set(refs) - label_set)
    if undefined_refs:
        errors.append("undefined LaTeX refs: " + ", ".join(undefined_refs))
    duplicate_labels = unique_duplicates(labels)
    if duplicate_labels:
        errors.append("duplicate LaTeX labels: " + ", ".join(sorted(duplicate_labels)))
    unused_bib = sorted(bib_set - cite_set)
    if unused_bib:
        warnings.append("unused BibTeX entries: " + ", ".join(unused_bib))

    verified_citation_count = 0
    if args.evidence_registry:
        registry_path = resolve_path(args.evidence_registry, root).resolve()
        try:
            registry = load_structured(registry_path)
        except (OSError, ValueError, TypeError) as exc:
            registry = None
            errors.append(f"cannot read evidence registry: {exc}")
        evidence_rows = registry.get("evidence", []) if isinstance(registry, dict) else []
        cited_registry: dict[str, list[dict]] = {}
        for row in evidence_rows:
            if not isinstance(row, dict) or row.get("type") != "citation":
                continue
            citation = row.get("citation") if isinstance(row.get("citation"), dict) else {}
            bib_key = citation.get("bib_key")
            if isinstance(bib_key, str):
                cited_registry.setdefault(bib_key, []).append(row)
        if args.require_verified_bibliography:
            placeholders = re.compile(r"赵某某|张三|李四|placeholder|todo|unknown author|test citation", re.IGNORECASE)
            for key in sorted(cite_set):
                rows = cited_registry.get(key, [])
                verified = [
                    row for row in rows
                    if row.get("verification_status") == "verified"
                    and isinstance(row.get("citation"), dict)
                    and row["citation"].get("metadata_verified") is True
                    and row["citation"].get("content_verified") is True
                    and row["citation"].get("publication_status_checked") is True
                    and isinstance(row["citation"].get("locator"), str)
                    and bool(row["citation"].get("locator").strip())
                ]
                if not verified:
                    errors.append(f"citation {key} has no verified, locator-backed evidence_registry record")
                else:
                    verified_citation_count += 1
            for key in sorted(cite_set & bib_set):
                entry_match = re.search(
                    rf"@\w+\s*[{{(]\s*{re.escape(key)}\s*,(.*?)(?=\n@\w+\s*[{{(]|\Z)",
                    bib,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                if entry_match and placeholders.search(entry_match.group(1)):
                    errors.append(f"BibTeX entry {key} contains placeholder author/title text")

    if args.check_figures:
        figure_dir = resolve_path(args.figures_dir, root).resolve() if args.figures_dir else (tex_files[0].parent if tex_files else root)
        for figure in figure_refs:
            figure_path = figure_dir / figure
            candidates = [figure_path]
            if figure_path.suffix == "":
                candidates.extend(figure_dir / f"{figure}{suffix}" for suffix in (".pdf", ".png", ".jpg", ".jpeg", ".svg"))
            if not any(candidate.is_file() for candidate in candidates):
                errors.append(f"missing figure file: {figure}")
        duplicate_figures = unique_duplicates(figure_refs)
        if duplicate_figures:
            warnings.append("duplicate figure references: " + ", ".join(sorted(duplicate_figures)))

    report = {
        "ok": not errors,
        "tex_files": [rel_path(path, root) for path in tex_files],
        "bib_file": rel_path(bib_path, root),
        "citations_used": len(cite_set),
        "bib_entries": len(bib_set),
        "labels_defined": len(label_set),
        "references_used": len(set(refs)),
        "figure_references": len(figure_refs),
        "verified_citations": verified_citation_count,
        "errors": errors,
        "warnings": warnings,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
