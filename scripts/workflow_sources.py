"""Read-only user sources and action details derived from producer references."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from _common import sha256_file
from command_display import render_command
from human_surface import AUTHORING_SPECS
from project_layout import resolve_control_path
from redaction import redact_text
from qa.tex_source import load_tex_source


def project_file(root: Path, raw: str) -> Path:
    path = (root / raw).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("source escapes project root")
    return path


def read_object(root: Path, raw: str) -> dict[str, Any]:
    path = project_file(root, raw)
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{raw} must contain an object")
    return value


def source_catalog(root: Path) -> list[dict[str, Any]]:
    """Only named author sources and paths already referenced by receipts/reviews."""
    sources: list[dict[str, Any]] = []

    def add(identifier: str, raw: str, kind: str, expected: str | None = None) -> None:
        path = project_file(root, raw)
        exists = path.is_file()
        current = (
            "missing"
            if not exists
            else "unknown"
            if not expected
            else "current"
            if sha256_file(path) == expected
            else "stale"
        )
        sources.append(
            {
                "source_id": identifier,
                "path": path.relative_to(root.resolve()).as_posix(),
                "kind": kind,
                "exists": exists,
                "freshness": current,
                "expected_sha256": expected,
            }
        )

    compile_index = read_object(root, ".harness/authoring/compile_index.json")
    indexed = {
        row.get("role"): row.get("source_path")
        for row in compile_index.get("entries", [])
        if isinstance(row, dict)
    }
    for role, spec in AUTHORING_SPECS.items():
        add(f"authoring:{role}", indexed.get(role) or spec["source"], "authoring")
        add(f"reasoning:{role}", spec["legacy_source"], "reasoning")
    for brief in sorted((root / "figures").glob("*/brief.md")):
        add(f"figure:{brief.parent.name}:brief", str(brief), "figure_brief")
    tex = root / "paper/main.tex"
    if tex.is_file():
        for path in load_tex_source(tex, root).files:
            raw = path.relative_to(root.resolve()).as_posix()
            add(f"paper:{raw}", raw, "paper_source")
    index_path = resolve_control_path(root, "run_index.json")
    index = read_object(root, str(index_path))
    for entry in index.get("receipts", []):
        if not isinstance(entry, dict) or not entry.get("receipt_path"):
            continue
        receipt = read_object(root, str(entry["receipt_path"]))
        if receipt.get("receipt_id") != entry.get("receipt_id"):
            continue
        for stream in ("stdout", "stderr"):
            if isinstance(receipt.get(f"{stream}_path"), str):
                add(
                    f"receipt:{receipt['receipt_id']}:{stream}",
                    receipt[f"{stream}_path"],
                    "log",
                    receipt.get(f"{stream}_sha256"),
                )
    for path in sorted((root / "reports/review").glob("*.json")):
        report = read_object(root, str(path))
        if not report.get("perspective"):
            continue
        for i, ref in enumerate(report.get("reviewed_artifacts", [])):
            if isinstance(ref, dict) and isinstance(ref.get("path"), str):
                add(
                    f"review:{path.stem}:{i}",
                    ref["path"],
                    "reviewed_version",
                    ref.get("sha256"),
                )
    return sources


def read_source(root: Path, identifier: str, *, limit: int = 131072) -> dict[str, Any]:
    source = next(
        (row for row in source_catalog(root) if row["source_id"] == identifier), None
    )
    if source is None:
        raise KeyError(
            "source is not referenced by the authoring/receipt/review catalog"
        )
    path = project_file(root, source["path"])
    if not path.is_file():
        raise FileNotFoundError("referenced source has not been produced")
    if source["kind"] == "reviewed_version" and source["freshness"] != "current":
        return {
            **source,
            "text": "",
            "truncated": False,
            "unavailable_reason": "Historical reviewed bytes are unavailable; current bytes do not establish the reviewed version.",
        }
    if path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        return {
            **source,
            "text": "",
            "truncated": False,
            "unavailable_reason": "Binary/visual source: inspect the version binding here and use registered artifact preview for the file.",
        }
    with path.open("rb") as handle:
        size = path.stat().st_size
        if source["kind"] == "log" and size > limit:
            handle.seek(size - limit)
        raw = handle.read(limit)
    return {
        **source,
        "text": redact_text(raw.decode("utf-8", errors="replace")),
        "truncated": size > limit,
        "byte_limit": limit,
        "tail": source["kind"] == "log",
    }


def action_details(root: Path, gate: str, message: str) -> dict[str, Any]:
    """Locate declared contract sources; never infer a field from prose."""
    matched = [
        role
        for role in AUTHORING_SPECS
        if re.search(r"(?<![\w])" + re.escape(role) + r"(?![\w])", message)
    ]
    target = matched[0] if len(matched) == 1 else None
    names = {
        "model_contract": "模型契约",
        "research_basis": "调研依据",
        "implementation_map": "实现映射",
        "paper_plan": "论文计划",
    }
    argv = [
        "harness",
        "check",
        gate.upper(),
        "--project",
        str(root.resolve()),
        "--json",
    ]
    source = AUTHORING_SPECS[target]["source"] if target else None
    entry = None
    if target:
        index = read_object(root, ".harness/authoring/compile_index.json")
        entry = next(
            (row for row in index.get("entries", []) if row.get("role") == target), None
        )
        if entry:
            source = (
                project_file(root, entry["source_path"])
                .relative_to(root.resolve())
                .as_posix()
            )
    compile_commands = {
        "model_contract": ["model"],
        "research_basis": ["research"],
        "implementation_map": ["solve"],
        "paper_plan": ["paper", "plan"],
    }
    compile_argv = (
        [
            "harness",
            *compile_commands[target],
            "--project",
            str(root.resolve()),
            "--compile",
            "--source",
            source,
        ]
        if target
        else None
    )
    if compile_argv and entry:
        output = (
            project_file(root, entry["output_path"])
            .relative_to(root.resolve())
            .as_posix()
        )
        compile_argv.extend(["--output", output])
        if target == "model_contract" and len(entry.get("sources", [])) > 1:
            research = (
                project_file(root, entry["sources"][1]["path"])
                .relative_to(root.resolve())
                .as_posix()
            )
            compile_argv.extend(["--research-source", research])
    return {
        "summary_zh": f"当前 {gate.upper()} 的{names[target]}证据需要处理"
        if target
        else f"当前 {gate.upper()} 尚未满足检查要求",
        "corrective_action_zh": "先查看对应作者源和诊断原文，修正后通过编译器生成契约，再运行复查命令。"
        if target
        else "请按诊断原文补充证据；尚无准确的源文件定位信息。",
        "target_source_id": f"authoring:{target}" if target else None,
        "target_path": source,
        "field_pointer": None,
        "raw_message": message,
        "command": {
            "argv": argv,
            "cwd": str(root.resolve()),
            "effect": "read_only",
            **render_command(argv),
        },
        "compile_command": {
            "argv": compile_argv,
            "cwd": str(root.resolve()),
            "effect": "producer",
            "preconditions": "fill and review the explicit authoring source first",
            **render_command(compile_argv),
        }
        if compile_argv
        else None,
        "locator_basis": "explicit contract role in diagnostic; no field inferred"
        if target
        else "unavailable",
    }
