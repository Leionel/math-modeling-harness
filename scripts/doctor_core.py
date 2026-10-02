"""Shared, read-only capability probes for both doctor entry points.

The evaluator reports facts about the current machine and repository.  It does
not install tools, alter a project, or decide a Gate.  ``harness doctor`` uses
the broad compatibility view while the legacy ``scripts/doctor.py`` can ask
for the historical strict command set.
"""

from __future__ import annotations

import importlib
from importlib import metadata
import shutil
import subprocess
import sys
import shlex
from pathlib import Path
from typing import Any, Mapping


STAGES = ("S0", "M1", "P1", "P2", "W1", "W2", "S1", "F1")
PYTHON_DEPENDENCIES = ("yaml", "jsonschema", "numpy", "pandas", "scipy", "matplotlib")
COMMANDS = ("git", "latexmk", "xelatex", "lualatex", "pdflatex", "pdfinfo", "pdffonts", "pdftoppm", "drawio")
LEGACY_STRICT_COMMANDS = ("git", "latexmk", "xelatex", "lualatex", "pdfinfo", "pdffonts", "pdftoppm")
COMMAND_ALIASES: Mapping[str, tuple[str, ...]] = {
    "drawio": ("drawio", "draw.io"),
}
STAGE_REQUIREMENTS: Mapping[str, tuple[str, ...]] = {
    "S0": ("git", "yaml", "jsonschema"),
    "M1": ("yaml", "jsonschema"),
    "P1": ("yaml", "jsonschema"),
    "P2": ("yaml", "jsonschema"),
    "W1": ("yaml", "jsonschema"),
    "W2": ("yaml", "jsonschema", "latexmk", "pdfinfo", "pdffonts", "pdftoppm"),
    "S1": ("yaml", "jsonschema", "pdfinfo", "pdffonts", "pdftoppm"),
    "F1": ("yaml", "jsonschema", "pdfinfo", "pdffonts", "pdftoppm"),
}
STAGE_ALTERNATIVES: Mapping[str, tuple[tuple[str, ...], ...]] = {
    "W2": (("xelatex", "lualatex", "pdflatex"),),
}
COMMAND_REQUIRED_STAGES: Mapping[str, tuple[str, ...]] = {
    "git": ("S0",),
    "latexmk": ("W2",),
    "xelatex": ("W2",),
    "lualatex": ("W2",),
    "pdflatex": ("W2",),
    "pdfinfo": ("W2", "S1", "F1"),
    "pdffonts": ("W2", "S1", "F1"),
    "pdftoppm": ("W2", "S1", "F1"),
    "drawio": (),
}
DEPENDENCY_REQUIRED_STAGES: Mapping[str, tuple[str, ...]] = {
    name: tuple(stage for stage in STAGES if name in STAGE_REQUIREMENTS[stage])
    for name in ("yaml", "jsonschema")
}
DEPENDENCY_REQUIRED_STAGES = {
    **DEPENDENCY_REQUIRED_STAGES,
    "numpy": (),
    "pandas": (),
    "scipy": (),
    "matplotlib": (),
}
GUIDANCE: Mapping[str, str] = {
    "yaml": "Install the development dependencies before authoring contracts: python -m pip install -r requirements-dev.txt",
    "jsonschema": "Install the development dependencies before running contract checks: python -m pip install -r requirements-dev.txt",
    "git": "Install Git and make it available on PATH before the S0 safety snapshot.",
    "latexmk": "Install the competition-approved TeX distribution and expose latexmk on PATH before W2.",
    "xelatex": "Install XeLaTeX and expose xelatex on PATH before W2.",
    "lualatex": "Install LuaLaTeX and expose lualatex on PATH when the selected template needs it.",
    "pdflatex": "Install pdfLaTeX and expose pdflatex on PATH when the selected template needs it.",
    "pdfinfo": "Install Poppler and expose pdfinfo on PATH before W2/S1/F1.",
    "pdffonts": "Install Poppler and expose pdffonts on PATH before W2/S1/F1.",
    "pdftoppm": "Install Poppler and expose pdftoppm on PATH before W2/S1/F1.",
    "drawio": "Install Draw.io Desktop or expose its executable on PATH when the selected figure route requires it.",
}


def _version_line(value: str | None) -> str | None:
    if not value:
        return None
    return next((line.strip() for line in value.splitlines() if line.strip()), None)


def probe_command(name: str) -> dict[str, Any]:
    """Probe one executable without invoking a shell or changing state."""

    aliases = COMMAND_ALIASES.get(name, (name,))
    path: str | None = None
    for alias in aliases:
        path = shutil.which(alias)
        if path:
            break
    result: dict[str, Any] = {
        "name": name,
        "kind": "command",
        "status": "missing" if path is None else "available",
        "source": "PATH",
        "version": None,
        "path": path,
        "required_for_stages": list(COMMAND_REQUIRED_STAGES.get(name, ())),
        "guidance": GUIDANCE.get(name, ""),
    }
    if path is None:
        return result
    # Draw.io Desktop may open a GUI for a version probe. Doctor only records
    # discovery; the selected figure route uses the black-box export check.
    if name == "drawio":
        return result
    for flag in ("--version", "-version"):
        try:
            completed = subprocess.run(
                [path, flag], text=True, capture_output=True, encoding="utf-8",
                errors="replace", check=False, timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if completed.returncode == 0:
            result["version"] = _version_line(completed.stdout or completed.stderr)
            break
    if result["version"] is None:
        result["guidance"] = f"{name} is on PATH but did not return a version; verify it can run non-interactively."
    return result


def probe_dependency(name: str) -> dict[str, Any]:
    """Probe one Python import and expose its path/version for diagnostics."""

    result: dict[str, Any] = {
        "name": name,
        "kind": "python_dependency",
        "status": "missing",
        "source": "python import",
        "version": None,
        "path": None,
        "required_for_stages": list(DEPENDENCY_REQUIRED_STAGES.get(name, ())),
        "guidance": GUIDANCE.get(name, "Install the dependency used by the selected stage."),
    }
    try:
        module = importlib.import_module(name)
    except (ImportError, ModuleNotFoundError) as exc:
        result["error"] = str(exc)
        return result
    result["status"] = "available"
    try:
        result["version"] = metadata.version(name)
    except metadata.PackageNotFoundError:
        result["version"] = getattr(module, "__version__", None)
    module_path = getattr(module, "__file__", None)
    result["path"] = str(module_path) if module_path else None
    return result


def _python_capability() -> dict[str, Any]:
    return {
        "name": "python",
        "kind": "runtime",
        "status": "available",
        "source": "sys.executable",
        "version": sys.version.split()[0],
        "path": sys.executable,
        "required_for_stages": list(STAGES),
        "guidance": "",
    }


def _repository_report(repo_root: Path) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    schemas: list[str] = []
    schema_dir = repo_root / "schemas"
    for path in sorted(schema_dir.glob("*.schema.json")):
        try:
            import json

            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, Mapping):
                raise ValueError("schema root is not an object")
            schemas.append(path.name)
        except (OSError, ValueError, TypeError):
            errors.append(f"schema parse failed: {path.name}")
    if not schemas:
        errors.append("no schemas found")
    critical = [
        "scripts/harness.py", "scripts/harness_status.py", "scripts/run_and_record.py",
        "scripts/qa/check_gates.py", "scripts/qa/run_deterministic_qa.py",
    ]
    missing = [item for item in critical if not (repo_root / item).is_file()]
    errors.extend(f"critical file missing: {item}" for item in missing)
    return errors, schemas, {"checked": critical, "missing": missing}


def _normalize_stage(stage: str | None) -> str | None:
    if stage is None:
        return None
    normalized = str(stage).upper()
    if normalized not in STAGES:
        raise ValueError(f"stage must be one of {', '.join(STAGES)}")
    return normalized


def evaluate_capabilities(
    root: Path,
    *,
    stage: str | None = None,
    repo_root: Path | None = None,
    strict_commands: bool = False,
) -> dict[str, Any]:
    """Return one normalized capability report for a project and stage."""

    project_root = root.resolve()
    repository_root = (repo_root or Path(__file__).resolve().parents[1]).resolve()
    selected_stage = _normalize_stage(stage)
    dependency_rows = [probe_dependency(name) for name in PYTHON_DEPENDENCIES]
    command_rows = [probe_command(name) for name in COMMANDS]
    capabilities = [_python_capability(), *dependency_rows, *command_rows]
    by_name = {str(row["name"]): row for row in capabilities}
    errors, schemas, critical_files = _repository_report(repository_root)
    warnings: list[str] = []
    for row in dependency_rows:
        if row["status"] != "available":
            message = f"Python dependency unavailable: {row['name']}"
            (errors if row["name"] in {"yaml", "jsonschema"} else warnings).append(message)
    stage_views: dict[str, dict[str, Any]] = {}
    for name in STAGES:
        missing = [
            requirement for requirement in STAGE_REQUIREMENTS[name]
            if by_name.get(requirement, {}).get("status") != "available"
        ]
        missing_alternatives = [
            list(group) for group in STAGE_ALTERNATIVES.get(name, ())
            if not any(by_name.get(candidate, {}).get("status") == "available" for candidate in group)
        ]
        missing.extend("one of: " + ", ".join(group) for group in missing_alternatives)
        stage_views[name] = {
            "status": "ready" if not missing else "blocked",
            "required_capabilities": list(STAGE_REQUIREMENTS[name]),
            "alternative_capabilities": [list(group) for group in STAGE_ALTERNATIVES.get(name, ())],
            "missing": missing,
            "guidance": [
                str(by_name[item].get("guidance", ""))
                for item in missing if item in by_name
            ] + [
                "Install the TeX engine selected by the competition template: " + ", ".join(group)
                for group in missing_alternatives
            ],
        }
    if strict_commands:
        missing = [name for name in LEGACY_STRICT_COMMANDS if by_name[name]["status"] != "available"]
        errors.extend(f"required command missing: {name}" for name in missing)
    if selected_stage:
        errors.extend(
            f"{selected_stage} capability missing: {name}"
            for name in stage_views[selected_stage]["missing"]
            if name not in {"yaml", "jsonschema"} or not any(f"{name}" in error for error in errors)
        )
    return {
        "ok": not errors,
        "project_root": str(project_root),
        "stage": selected_stage,
        "python": {"path": sys.executable, "version": sys.version.split()[0]},
        "capabilities": capabilities,
        "stages": stage_views,
        "dependencies": {
            row["name"]: {
                "available": row["status"] == "available",
                "status": row["status"],
                "version": row["version"],
                "path": row["path"],
                **({"error": row["error"]} if "error" in row else {}),
            }
            for row in dependency_rows
        },
        "commands": {
            row["name"]: {
                "available": row["status"] == "available",
                "status": row["status"],
                "version": row["version"],
                "path": row["path"],
            }
            for row in command_rows
        },
        "schema_count": len(schemas),
        "schemas": schemas,
        "critical_files": critical_files,
        "warnings": warnings,
        "errors": errors,
    }


def format_capability_report(report: Mapping[str, Any], *, verbose: bool = False) -> str:
    """Render existing probe facts without changing their verdict or stage."""
    stage = report.get("stage")
    python = report["python"]
    lines = [
        f"doctor: {'OK' if report['ok'] else 'BLOCKED'}",
        f"Python: {python['path']} ({python['version']})",
        f"检查阶段: {stage or '未指定（基础能力检查）'}；不是 Gate 判定",
    ]
    for error in report.get("errors", []):
        lines.append(f"错误: {error}")
    missing = (report["stages"].get(stage) or {}).get("missing", [])
    lines.append("当前阶段缺项: " + (", ".join(missing) if missing else "无" if stage else "未选择阶段"))
    for row in report["capabilities"]:
        if row["status"] == "available":
            continue
        required = row["name"] in missing or row["name"] in {"yaml", "jsonschema"}
        if required or verbose:
            lines.append(f"{'必需' if required else '后续/可选'}: {row['name']} ({row.get('source', '')})")
            guidance = str(row.get("guidance") or "")
            if row["name"] in {"yaml", "jsonschema"}:
                package = "PyYAML" if row["name"] == "yaml" else "jsonschema"
                argv = [str(python["path"]), "-m", "pip", "install", package]
                command = "& " + " ".join("'" + value.replace("'", "''") + "'" for value in argv) if sys.platform == "win32" else shlex.join(argv)
                guidance = command
            if guidance:
                lines.append(f"  处理: {guidance}")
    if stage:
        for group in report["stages"][stage].get("alternative_capabilities", []):
            if "one of: " + ", ".join(group) in missing:
                lines.append("处理: 按当前论文模板安装一种 TeX 引擎: " + ", ".join(group))
    optional = [row for row in report["capabilities"] if row["status"] != "available" and row["name"] not in missing and row["name"] not in {"yaml", "jsonschema"}]
    if not verbose:
        lines.append(f"后续/可选缺项: {len(optional)}；使用 --verbose 查看")
    argv = ["harness", "doctor", "--project", str(report["project_root"]), "--offline"]
    if stage:
        argv.extend(["--stage", str(stage)])
    command = " ".join("'" + value.replace("'", "''") + "'" for value in argv) if sys.platform == "win32" else shlex.join(argv)
    # PowerShell needs the invocation operator when the executable is quoted.
    lines.append("复查: " + ("& " if sys.platform == "win32" else "") + command)
    return "\n".join(lines)


__all__ = [
    "COMMANDS", "LEGACY_STRICT_COMMANDS", "STAGES", "STAGE_REQUIREMENTS", "evaluate_capabilities",
    "probe_command", "probe_dependency", "format_capability_report",
]
