#!/usr/bin/env python3
"""Name a coherent v2 run state so a model branch can be forked from it.

A checkpoint records the identity (path + sha256) of every file the control
plane depends on: the manifest, the manifest roots, the receipt files the run
index projects and the artifact files the DAG names with a digest.  It is
evidence, not control truth: ``.harness/checkpoints/<name>.json`` never changes
a Gate, and a fork copies exactly the recorded bytes — refuses to run when the
source has drifted since the checkpoint, and refuses a destination that already
holds files.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _common import load_structured, rel_path, sha256_file, write_json  # noqa: E402
from project_layout import resolve_manifest_path  # noqa: E402
from runtime_state import RuntimeStateError, load_runtime_state  # noqa: E402

CHECKPOINT_DIR = Path(".harness") / "checkpoints"
ROOT_ROLES = ("model_contract", "evidence_registry", "artifact_dag", "run_index")
FORK_RECORD = "fork.json"


def checkpoint_path(root: Path, name: str) -> Path:
    return root / CHECKPOINT_DIR / f"{name}.json"


def _validate_name(name: str) -> str:
    if not name or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for character in name):
        raise ValueError("checkpoint names may contain only lowercase letters, digits, dot, underscore and dash")
    return name


def _checkpoint_file(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute():
        raise ValueError(f"checkpoint file path must be relative: {relative}")
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"checkpoint file path escapes project root: {relative}") from exc
    return resolved


def _snapshot_files(root: Path, state: Any) -> dict[str, str]:
    """Map every file the run depends on to its digest, relative to the root."""

    files: dict[str, str] = {}

    def record(path: Path) -> None:
        path = _checkpoint_file(root, rel_path(path, root))
        relative = rel_path(path, root)
        if relative in files:
            return
        if not path.is_file():
            raise ValueError(f"checkpoint requires every recorded file to exist: {relative}")
        files[relative] = sha256_file(path)

    record(state.manifest_path)
    for role in ROOT_ROLES:
        path = state.root_path(role)
        if path is not None:
            record(path)
            if role == "run_index":
                index = load_structured(path)
                for row in index.get("receipts", []) if isinstance(index, Mapping) else []:
                    if isinstance(row, Mapping) and isinstance(row.get("receipt_path"), str):
                        record((root / str(row["receipt_path"])).resolve())
            if role == "artifact_dag":
                dag = load_structured(path)
                for node in dag.get("nodes", []) if isinstance(dag, Mapping) else []:
                    if isinstance(node, Mapping) and isinstance(node.get("path"), str):
                        candidate = (root / str(node["path"])).resolve()
                        if candidate.is_file():
                            record(candidate)
    comp_ref = state.manifest.get("competition_profile_ref")
    if isinstance(comp_ref, Mapping) and isinstance(comp_ref.get("path"), str):
        comp_path = (root / comp_ref["path"]).resolve()
        if comp_path.is_file():
            record(comp_path)
            try:
                prof_doc = load_structured(comp_path)
                for rule in prof_doc.get("official_rules", []) if isinstance(prof_doc, Mapping) else []:
                    snap = rule.get("snapshot", {}).get("path") if isinstance(rule, Mapping) else None
                    if isinstance(snap, str):
                        snap_p = (root / snap).resolve()
                        if snap_p.is_file():
                            record(snap_p)
            except Exception:
                pass
    return dict(sorted(files.items()))


def create_checkpoint(root: Path, name: str, *, force: bool = False) -> dict[str, Any]:
    """Write ``.harness/checkpoints/<name>.json`` for the current run state."""

    name = _validate_name(name)
    target = checkpoint_path(root, name)
    if target.exists() and not force:
        raise ValueError(f"refusing to overwrite existing checkpoint: {rel_path(target, root)}; pass --force")
    manifest_path = resolve_manifest_path(root)
    try:
        state = load_runtime_state(manifest_path, project_root=root, allow_legacy=False)
    except (OSError, ValueError, TypeError, RuntimeStateError) as exc:
        raise ValueError(f"cannot checkpoint this project: {exc}") from exc
    files = _snapshot_files(root, state)
    document = {
        "schema_version": "1.0",
        "checkpoint_id": f"ckpt-{name}",
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_id": state.manifest.get("project_id"),
        "run_id": state.manifest.get("run_id"),
        "manifest": rel_path(state.manifest_path, root),
        "files": files,
    }
    write_json(target, document, overwrite=force)
    return document


def load_checkpoint(root: Path, name: str) -> dict[str, Any]:
    name = _validate_name(name)
    path = checkpoint_path(root, name)
    if not path.is_file():
        raise ValueError(f"unknown checkpoint: {rel_path(path, root)}")
    document = load_structured(path)
    if not isinstance(document, Mapping) or not isinstance(document.get("files"), Mapping):
        raise ValueError(f"checkpoint is not readable: {rel_path(path, root)}")
    return dict(document)


def verify_checkpoint(root: Path, name: str) -> tuple[bool, list[str]]:
    """Recompute every recorded digest; a moved byte is a failure."""

    document = load_checkpoint(root, name)
    errors: list[str] = []
    for relative, expected in sorted(document["files"].items()):
        try:
            path = _checkpoint_file(root, relative)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not path.is_file():
            errors.append(f"missing file: {relative}")
            continue
        actual = sha256_file(path)
        if actual != expected:
            errors.append(f"digest drift: {relative}")
    return (not errors), errors


def list_checkpoints(root: Path) -> list[dict[str, Any]]:
    directory = root / CHECKPOINT_DIR
    rows: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            document = load_structured(path)
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(document, Mapping):
            rows.append({
                "name": document.get("name", path.stem),
                "checkpoint_id": document.get("checkpoint_id"),
                "created_at": document.get("created_at"),
                "files": len(document.get("files", {})) if isinstance(document.get("files"), Mapping) else 0,
            })
    return rows


def fork_project(
    root: Path,
    name: str,
    destination: Path,
    *,
    branch: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Copy exactly the checkpointed bytes into a new project root."""

    document = load_checkpoint(root, name)
    ok, errors = verify_checkpoint(root, name)
    if not ok:
        raise ValueError(
            "refusing to fork from a checkpoint that no longer matches this run: " + "; ".join(errors)
        )
    if destination.exists() and any(destination.iterdir()) and not force:
        raise ValueError(f"refusing to fork into a non-empty destination: {destination}")
    paths = {
        relative: (_checkpoint_file(root, relative), _checkpoint_file(destination, relative))
        for relative in document["files"]
    }
    destination.mkdir(parents=True, exist_ok=True)
    for relative in sorted(paths):
        source, target = paths[relative]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    copied = {
        relative: sha256_file((destination / relative).resolve())
        for relative in sorted(document["files"])
    }
    drifted = [
        relative for relative, digest in copied.items() if digest != document["files"][relative]
    ]
    if drifted:
        raise ValueError("fork copy failed its own digest check: " + "; ".join(drifted))
    branch_name = branch or destination.name
    record = {
        "schema_version": "1.0",
        "fork_id": f"fork-{branch_name}",
        "branch": branch_name,
        "parent_root": str(root),
        "parent_checkpoint": document["checkpoint_id"],
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": sorted(copied),
    }
    write_json(destination / FORK_RECORD, record, overwrite=force)
    child_checkpoint = checkpoint_path(destination, name)
    child_checkpoint.parent.mkdir(parents=True, exist_ok=True)
    write_json(child_checkpoint, document, overwrite=force)
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("create")
    create.add_argument("--project-root", default=".")
    create.add_argument("--name", required=True)
    create.add_argument("--force", action="store_true")
    verify = sub.add_parser("verify")
    verify.add_argument("--project-root", default=".")
    verify.add_argument("--name", required=True)
    listing = sub.add_parser("list")
    listing.add_argument("--project-root", default=".")
    fork = sub.add_parser("fork")
    fork.add_argument("--project-root", default=".")
    fork.add_argument("--name", required=True)
    fork.add_argument("--output", required=True)
    fork.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.project_root).resolve()
    try:
        if args.action == "create":
            document = create_checkpoint(root, args.name, force=args.force)
            print(json.dumps({"ok": True, "checkpoint": document["checkpoint_id"], "files": len(document["files"])}, ensure_ascii=False))
            return 0
        if args.action == "verify":
            ok, errors = verify_checkpoint(root, args.name)
            print(json.dumps({"ok": ok, "checkpoint": f"ckpt-{args.name}", "errors": errors}, ensure_ascii=False))
            return 0 if ok else 1
        if args.action == "fork":
            record = fork_project(root, args.name, Path(args.output).resolve(), force=args.force)
            print(json.dumps({"ok": True, "fork": record["fork_id"], "files": len(record["files"])}, ensure_ascii=False))
            return 0
        print(json.dumps({"ok": True, "checkpoints": list_checkpoints(root)}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
