#!/usr/bin/env python3
"""Run a subprocess and capture an immutable execution receipt.

The historical invocation remains available for v1 projects.  A v2
invocation (``--v2`` or ``--manifest`` pointing at a v2 manifest) writes a
v2 receipt and a rebuildable run-index projection.  The receipt owns argv,
exit code, timestamps and any selected I/O digests; the index never copies
execution facts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import socket
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _common import load_structured, rel_path, require_within, write_json  # noqa: E402
from profiles.artifact_projection import normalize_run_index  # noqa: E402
from runtime_state import RuntimeStateError, load_runtime_state  # noqa: E402
from project_layout import manifest_policy_ref  # noqa: E402
from qa.validate_contracts import validate_value  # noqa: E402


COMMAND_RECEIPT_SCHEMA = SCRIPT_DIR.parent / "schemas" / "command_receipt.schema.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_id(role: str, path: str, digest: str | None = None) -> str:
    token = hashlib.sha256(f"{role}|{path}|{digest or 'identity'}".encode("utf-8")).hexdigest()[:20].upper()
    return f"ART-{token}"


def _read_manifest_schema(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        value = load_structured(path)
    except (OSError, ValueError, TypeError):
        return None
    return str(value.get("schema_version")) if isinstance(value, dict) else None


def _v2_policy(args: argparse.Namespace, manifest_path: Path | None, root: Path) -> tuple[str, str]:
    preset = "research"
    rule = args.selection_policy
    if manifest_path is not None:
        try:
            state = load_runtime_state(manifest_path, project_root=root, allow_legacy=False)
            preset = state.preset
            policy = state.manifest.get("control", {}).get("selection_policy", {})
            if isinstance(policy, dict) and isinstance(policy.get("rule"), str) and policy["rule"].strip():
                rule = policy["rule"]
        except (OSError, ValueError, TypeError, RuntimeStateError) as exc:
            raise ValueError(f"v2 manifest runtime boundary failed: {exc}") from exc
    if manifest_path is not None and args.integrity_mode and args.integrity_mode != preset:
        raise ValueError(
            "--integrity-mode conflicts with the v2 manifest preset; "
            "resolve capabilities from preset+overrides at the runtime boundary"
        )
    mode = preset if manifest_path is not None else (args.integrity_mode or preset)
    if mode not in {"sprint", "research", "submission"}:
        raise ValueError(f"integrity mode must be sprint, research, or submission, got {mode!r}")
    return mode, rule


def _v2_ref(path: Path, root: Path, *, role: str, digest: str | None, critical: bool) -> dict[str, Any]:
    relative = rel_path(path, root)
    ref: dict[str, Any] = {
        "path": relative,
        "artifact_id": _artifact_id(role, relative, digest),
        "critical": bool(critical),
    }
    if digest:
        ref["sha256"] = digest
        ref["digest_owner"] = "command_receipt"
    return ref


def execution_host_identity() -> dict[str, str]:
    return {"hostname": socket.gethostname(), "platform": platform.platform()}


def _receipt_target(root: Path, receipt_path: str) -> Path:
    resolved = Path(receipt_path)
    return (root / receipt_path).resolve() if not resolved.is_absolute() else resolved.resolve()


def _previous_receipt_hash(root: Path, index_path: Path | None) -> str | None:
    """Hash the previous receipt file bytes in run_index order, or None for a fresh index."""

    if index_path is None or not index_path.is_file():
        return None
    index = load_structured(index_path)
    rows = index.get("receipts") if isinstance(index, dict) else None
    if not isinstance(rows, list) or not rows:
        return None
    last = rows[-1]
    if not isinstance(last, dict) or not isinstance(last.get("receipt_path"), str):
        raise ValueError("run_index's last receipt row has no receipt_path; refusing to chain onto it")
    previous = _receipt_target(root, last["receipt_path"])
    if not previous.is_file():
        raise ValueError(
            f"receipt history is broken: the previous receipt file is missing ({last['receipt_path']}); "
            "run --verify-chain and repair the history before recording more receipts"
        )
    return sha256_file(previous)


def verify_receipt_chain(root: Path, index_path: Path) -> list[str]:
    """Recompute the receipt hash chain in run_index order and return the errors."""

    index = load_structured(index_path)
    rows = index.get("receipts") if isinstance(index, dict) else None
    if not isinstance(rows, list):
        return ["run_index is not a v2 receipt projection; nothing to chain-verify"]
    errors: list[str] = []
    previous_path: Path | None = None
    for position, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("receipt_path"), str):
            errors.append(f"receipts[{position}] has no receipt_path")
            previous_path = None
            continue
        path = _receipt_target(root, row["receipt_path"])
        if not path.is_file():
            errors.append(f"receipts[{position}] receipt file is missing: {row['receipt_path']}")
            previous_path = None
            continue
        document = load_structured(path)
        if not isinstance(document, dict):
            errors.append(f"receipts[{position}] receipt is not a JSON object: {row['receipt_path']}")
            previous_path = None
            continue
        declared = document.get("previous_receipt_hash")
        if previous_path is not None and isinstance(declared, str):
            actual = sha256_file(previous_path)
            if declared != actual:
                errors.append(
                    f"receipts[{position}] ({row['receipt_path']}) previous_receipt_hash does not match the bytes of "
                    f"{rel_path(previous_path, root)}: receipt history was modified, reordered, or deleted"
                )
        previous_path = path
    return errors


def _append_v2_index(
    index_path: Path,
    *,
    root: Path,
    run_id: str,
    receipt_id: str,
    receipt_path: Path,
    stage: str,
    selected: bool,
    finished_at: str,
    policy_rule: str,
    policy_path: str,
    supersedes_receipt_id: str | None = None,
    generation: int | None = None,
) -> None:
    if index_path.is_file():
        raw = load_structured(index_path)
        if not isinstance(raw, dict):
            raise ValueError("run_index must be an object")
        if raw.get("schema_version") == "2.0":
            index = raw
        else:
            index, notes = normalize_run_index(raw)
            if index is None:
                raise ValueError("legacy run_index cannot be projected")
            # A v1 projection is only safe when its selection is already
            # unambiguous.  ``run_index.schema.json`` deliberately has no
            # metadata extension, and notes are not execution evidence.  Do
            # not smuggle migration debt into a v2 projection; require the
            # caller to perform the explicit migration instead.
            unresolved = [
                *notes.get("unresolved", []),
                *notes.get("manual_review_required", []),
            ]
            if unresolved:
                detail = "; ".join(str(item) for item in unresolved)
                raise ValueError(
                    "legacy run_index requires explicit migration before v2 append: "
                    f"{detail}"
                )
    else:
        index = {
            "schema_version": "2.0",
            "projection": "receipt_selection",
            "run_id_scope": run_id,
            "receipts": [],
            "selection": {
                "policy_ref": {
                    "owner": "run_manifest.control",
                    "path": policy_path,
                    "version": "2.0",
                },
                "selected_receipt_ids": [],
            },
        }
    receipts = index.setdefault("receipts", [])
    if not isinstance(receipts, list):
        raise ValueError("v2 run_index.receipts must be an array")
    if any(isinstance(row, dict) and row.get("receipt_id") == receipt_id for row in receipts):
        raise ValueError(f"run_index already contains receipt_id {receipt_id}")
    entry: dict[str, Any] = {
        "receipt_id": receipt_id,
        "receipt_path": rel_path(receipt_path, root),
        "run_id": run_id,
        "stage": stage,
        "selected": bool(selected),
        "recorded_at": finished_at,
        "projected_from": f"command_receipt:{receipt_id}",
    }
    if supersedes_receipt_id:
        entry["supersedes_receipt_id"] = supersedes_receipt_id
    if generation:
        entry["generation"] = generation
    receipts.append(entry)
    selection = index.setdefault("selection", {})
    if not isinstance(selection, dict):
        raise ValueError("v2 run_index.selection must be an object")
    selection.setdefault("policy_ref", {
        "owner": "run_manifest.control",
        "path": policy_path,
        "version": "2.0",
    })
    selected_ids = selection.setdefault("selected_receipt_ids", [])
    if not isinstance(selected_ids, list):
        raise ValueError("v2 run_index.selection.selected_receipt_ids must be an array")
    if selected and receipt_id not in selected_ids:
        selected_ids.append(receipt_id)
    index["schema_version"] = "2.0"
    index["projection"] = "receipt_selection"
    index["generated_at"] = finished_at
    write_json(index_path, index, overwrite=True)


def _run_v2(args: argparse.Namespace, root: Path, manifest_path: Path | None, argv: list[str]) -> int:
    mode, policy_rule = _v2_policy(args, manifest_path, root)
    coverage_declared = bool(args.covers_model or args.covers_question or args.covers_contract_item)
    if coverage_declared and args.stage != "smoke":
        raise ValueError("--covers-* arguments are only valid for a smoke receipt")
    if coverage_declared and not (args.covers_model and args.covers_question and args.covers_contract_item):
        raise ValueError(
            "smoke coverage requires --covers-model, --covers-question, and --covers-contract-item"
        )
    policy_path = manifest_policy_ref(root, manifest_path) if manifest_path is not None else "run_manifest.json#/control/selection_policy"
    receipt_path = require_within(root / args.receipt if not Path(args.receipt).is_absolute() else Path(args.receipt), root, label="--receipt")
    receipt_id = args.receipt_id or f"REC-{uuid.uuid4().hex[:16]}"
    if re.fullmatch(r"REC-[A-Za-z0-9._-]+", receipt_id) is None:
        raise ValueError("--receipt-id must match REC-[A-Za-z0-9._-]+")
    command_id = f"CMD-{uuid.uuid4().hex[:12]}"
    stdout_path = receipt_path.with_suffix(receipt_path.suffix + ".stdout")
    stderr_path = receipt_path.with_suffix(receipt_path.suffix + ".stderr")
    occupied = [path for path in (receipt_path, stdout_path, stderr_path) if path.exists()]
    if occupied:
        raise ValueError(f"refusing to overwrite immutable receipt file: {occupied[0]}")
    index_path = None
    if args.index:
        raw_index = root / args.index if not Path(args.index).is_absolute() else Path(args.index)
        index_path = require_within(raw_index, root, label="--index")
    selected = bool(args.selected)
    hash_io = mode == "submission" or (mode == "research" and selected) or bool(args.freeze)
    input_targets: list[Path] = []
    for raw in args.input:
        path = (root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        if not path.is_file():
            raise ValueError(f"input does not exist: {raw}")
        input_targets.append(path)
    # Bind inputs before the child starts. Hashing them afterwards would let
    # a mutating command rewrite its own evidence and make the receipt attest
    # to post-execution bytes rather than the bytes it actually received.
    input_refs = [
        _v2_ref(path, root, role="run_input", digest=sha256_file(path) if hash_io else None, critical=hash_io)
        for path in input_targets
    ]
    output_targets: list[tuple[Path, bool]] = []
    for raw in args.output_artifact:
        unresolved = root / raw if not Path(raw).is_absolute() else Path(raw)
        path = require_within(unresolved, root, label="--output-artifact")
        output_targets.append((path, path.is_file()))
    command_cwd = (root / args.command_cwd).resolve() if args.command_cwd else root
    try:
        command_cwd.relative_to(root)
    except ValueError as exc:
        raise ValueError("--command-cwd must stay within --project-root") from exc
    if not command_cwd.is_dir():
        raise ValueError(f"--command-cwd is not a directory: {command_cwd}")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    result = subprocess.run(argv, cwd=str(command_cwd), text=True, capture_output=True, encoding="utf-8", errors="replace", check=False)
    finished = datetime.now(timezone.utc)
    stdout_path.write_text(result.stdout or "", encoding="utf-8")
    stderr_path.write_text(result.stderr or "", encoding="utf-8")
    missing_outputs: list[str] = []
    output_refs: list[dict[str, Any]] = []
    for path, existed_before in output_targets:
        digest = sha256_file(path) if hash_io and path.is_file() else None
        output_refs.append(_v2_ref(path, root, role="run_output", digest=digest, critical=hash_io))
        if not path.is_file():
            missing_outputs.append(str(path))
    receipt: dict[str, Any] = {
        "schema_version": "2.0", "receipt_id": receipt_id, "command_id": command_id,
        "run_id": args.run_id, "stage": args.stage, "argv": argv, "cwd": str(command_cwd),
        "exit_code": result.returncode, "started_at": started.isoformat(), "finished_at": finished.isoformat(),
        "duration_s": round((finished - started).total_seconds(), 3), "seed": args.seed,
        "stdout_path": rel_path(stdout_path, root), "stderr_path": rel_path(stderr_path, root),
        "input_refs": input_refs, "output_refs": output_refs,
        "selection": {"selected": selected, "policy": policy_rule} if selected else {"selected": False},
        "env_note": "environment inherited from parent process; not captured",
        "metadata": {"integrity_mode": mode, "io_hashes_bound": hash_io},
    }
    if args.note:
        receipt["metadata"]["note"] = args.note
    if coverage_declared:
        receipt["metadata"]["smoke_coverage"] = {
            "model_ids": list(dict.fromkeys(args.covers_model)),
            "question_ids": list(dict.fromkeys(args.covers_question)),
            "covered_contract_item_ids": list(dict.fromkeys(args.covers_contract_item)),
        }
    if hash_io:
        receipt["stdout_sha256"] = sha256_file(stdout_path)
        receipt["stderr_sha256"] = sha256_file(stderr_path)
    previous_hash = _previous_receipt_hash(root, index_path)
    if previous_hash is not None:
        receipt["previous_receipt_hash"] = previous_hash
    if getattr(args, "supersedes_receipt", None):
        predecessor_id = str(args.supersedes_receipt)
        predecessor_receipt = None
        if index_path and index_path.is_file():
            index_data = load_structured(index_path)
            if isinstance(index_data, dict):
                for row in index_data.get("receipts", []):
                    if isinstance(row, dict) and str(row.get("receipt_id")) == predecessor_id:
                        if row.get("run_id") != args.run_id or row.get("stage") != args.stage:
                            raise ValueError(
                                f"--supersedes-receipt {predecessor_id} stage/run mismatch (expected stage={args.stage}, run_id={args.run_id})"
                            )
                        raw_p = Path(row["receipt_path"])
                        p_path = raw_p if raw_p.is_absolute() else (root / raw_p).resolve()
                        if p_path.is_file():
                            predecessor_receipt = load_structured(p_path)
                        break
        if predecessor_receipt is None:
            candidate = root / "receipts" / f"{predecessor_id}.json"
            if candidate.is_file():
                predecessor_receipt = load_structured(candidate)
                if predecessor_receipt.get("run_id") != args.run_id or predecessor_receipt.get("stage") != args.stage:
                    raise ValueError(
                        f"--supersedes-receipt {predecessor_id} stage/run mismatch"
                    )
        if predecessor_receipt is None:
            raise ValueError(f"--supersedes-receipt {predecessor_id} does not exist in run_index or receipts")
        prev_gen = predecessor_receipt.get("generation", 1) if isinstance(predecessor_receipt, dict) else 1
        generation = int(prev_gen) + 1
        receipt["supersedes_receipt_id"] = predecessor_id
        receipt["generation"] = generation
    receipt["execution_host_identity"] = execution_host_identity()
    if missing_outputs:
        receipt["metadata"].update({"outcome": "failed", "failure_reason": "declared_output_missing", "missing_outputs": missing_outputs})
    else:
        receipt["metadata"]["outcome"] = "success" if result.returncode == 0 else "failed"
    schema_errors = validate_value(receipt, COMMAND_RECEIPT_SCHEMA)
    if schema_errors:
        raise ValueError("generated command receipt violates schema: " + "; ".join(schema_errors))
    write_json(receipt_path, receipt)
    if index_path is not None:
        _append_v2_index(index_path, root=root, run_id=args.run_id, receipt_id=receipt_id,
                          receipt_path=receipt_path, stage=args.stage, selected=selected,
                           finished_at=finished.isoformat(), policy_rule=policy_rule,
                           policy_path=policy_path,
                           supersedes_receipt_id=receipt.get("supersedes_receipt_id"),
                           generation=receipt.get("generation"))
    if missing_outputs:
        print(json.dumps({"ok": False, "command_id": command_id, "receipt_id": receipt_id, "exit_code": result.returncode,
                          "receipt": str(receipt_path), "index_entry": bool(args.index),
                          "errors": [f"declared output was not produced: {path}" for path in missing_outputs]}, ensure_ascii=False))
        return 3
    print(json.dumps({"ok": result.returncode == 0, "command_id": command_id, "receipt_id": receipt_id,
                      "exit_code": result.returncode, "receipt": str(receipt_path), "index_entry": bool(args.index)}, ensure_ascii=False))
    return result.returncode


def _run_v1(args: argparse.Namespace, root: Path, argv: list[str]) -> int:
    """Historical writer retained solely for v1 compatibility projects."""

    receipt_path = require_within(root / args.receipt if not Path(args.receipt).is_absolute() else Path(args.receipt), root, label="--receipt")
    command_id = f"CMD-{uuid.uuid4().hex[:12]}"
    stdout_path = receipt_path.with_suffix(receipt_path.suffix + ".stdout")
    stderr_path = receipt_path.with_suffix(receipt_path.suffix + ".stderr")
    occupied = [path for path in (receipt_path, stdout_path, stderr_path) if path.exists()]
    if occupied:
        raise ValueError(f"refusing to overwrite immutable receipt file: {occupied[0]}")
    index_path = None
    if args.index:
        raw_index = root / args.index if not Path(args.index).is_absolute() else Path(args.index)
        index_path = require_within(raw_index, root, label="--index")
    input_refs = []
    for raw in args.input:
        path = (root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        if not path.is_file():
            print(json.dumps({"ok": False, "errors": [f"input does not exist: {raw}"]}, ensure_ascii=False))
            return 2
        input_refs.append({"path": str(path), "sha256": sha256_file(path)})
    output_targets = []
    for raw in args.output_artifact:
        unresolved = root / raw if not Path(raw).is_absolute() else Path(raw)
        path = require_within(unresolved, root, label="--output-artifact")
        output_targets.append((path, path.is_file()))
    command_cwd = (root / args.command_cwd).resolve() if args.command_cwd else root
    try:
        command_cwd.relative_to(root)
    except ValueError as exc:
        raise ValueError("--command-cwd must stay within --project-root") from exc
    if not command_cwd.is_dir():
        raise ValueError(f"--command-cwd is not a directory: {command_cwd}")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    result = subprocess.run(argv, cwd=str(command_cwd), text=True, capture_output=True, encoding="utf-8", errors="replace", check=False)
    finished = datetime.now(timezone.utc)
    stdout_path.write_text(result.stdout or "", encoding="utf-8")
    stderr_path.write_text(result.stderr or "", encoding="utf-8")
    output_refs = []
    missing_outputs: list[Path] = []
    for path, existed_before in output_targets:
        if path.is_file():
            output_refs.append({"path": str(path), "sha256": sha256_file(path), "existed_before": existed_before})
        else:
            missing_outputs.append(path)
    receipt = {
        "schema_version": "1.0", "command_id": command_id, "run_id": args.run_id, "stage": args.stage,
        "argv": argv, "cwd": str(command_cwd), "exit_code": result.returncode,
        "started_at": started.isoformat(), "finished_at": finished.isoformat(),
        "duration_s": round((finished - started).total_seconds(), 3), "seed": args.seed,
        "stdout_path": str(stdout_path), "stderr_path": str(stderr_path),
        "stdout_sha256": sha256_file(stdout_path), "stderr_sha256": sha256_file(stderr_path),
        "input_refs": input_refs, "output_refs": output_refs,
        "env_note": "environment inherited from parent process; not captured",
    }
    schema_errors = validate_value(receipt, COMMAND_RECEIPT_SCHEMA)
    if schema_errors:
        raise ValueError("generated command receipt violates schema: " + "; ".join(schema_errors))
    write_json(receipt_path, receipt)
    if index_path is not None:
        if index_path.is_file():
            index = json.loads(index_path.read_text(encoding="utf-8"))
        else:
            index = {"schema_version": "1.0", "run_id_scope": args.run_id, "selection_policy": args.selection_policy, "runs": []}
        index["runs"].append({"command_id": command_id, "run_id": args.run_id, "stage": args.stage, "argv": argv,
                              "exit_code": result.returncode, "receipt_path": str(receipt_path), "selected": bool(args.selected),
                              "note": args.note, "recorded_at": finished.isoformat()})
        write_json(index_path, index, overwrite=True)
    if missing_outputs:
        print(json.dumps({"ok": False, "command_id": command_id, "exit_code": result.returncode,
                          "receipt": str(receipt_path), "index_entry": bool(args.index),
                          "errors": [f"declared output was not produced: {path}" for path in missing_outputs]}, ensure_ascii=False))
        return 3
    print(json.dumps({"ok": result.returncode == 0, "command_id": command_id, "exit_code": result.returncode,
                      "receipt": str(receipt_path), "index_entry": bool(args.index)}, ensure_ascii=False))
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id")
    parser.add_argument("--stage", choices=("safety", "smoke", "full", "freeze", "evidence", "qa", "review", "submission"))
    parser.add_argument("--receipt")
    parser.add_argument("--receipt-id", help="predeclared v2 receipt id for producer/output binding")
    parser.add_argument("--index")
    parser.add_argument("--manifest", help="v2 run_manifest; activates the normalized receipt path")
    parser.add_argument("--v2", action="store_true", help="write a v2 receipt without requiring a manifest")
    parser.add_argument("--integrity-mode", choices=("sprint", "research", "submission"))
    parser.add_argument("--freeze", action="store_true", help="bind critical I/O for an explicit freeze even in sprint mode")
    parser.add_argument("--supersedes-receipt", help="receipt id of an earlier run superseded by this command")
    parser.add_argument("--selection-policy", default="first successful run of this stage is selected")
    parser.add_argument("--selected", action="store_true")
    parser.add_argument("--note", default="")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--input", action="append", default=[])
    parser.add_argument("--output-artifact", action="append", default=[])
    parser.add_argument("--covers-model", action="append", default=[], help="model id exercised by this smoke command")
    parser.add_argument("--covers-question", action="append", default=[], help="question id exercised by this smoke command")
    parser.add_argument("--covers-contract-item", action="append", default=[], help="equation, constraint, or validation-obligation id exercised by this smoke command")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--command-cwd", help="child working directory, relative to project root")
    parser.add_argument("--verify-chain", action="store_true", help="verify the receipt hash chain of --index and exit without running a command")
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    if args.verify_chain:
        try:
            if not args.index:
                raise ValueError("--verify-chain requires --index <run_index.json>")
            index_path = require_within(root / args.index if not Path(args.index).is_absolute() else Path(args.index), root, label="--index")
            if not index_path.is_file():
                raise ValueError(f"run_index does not exist: {args.index}")
            errors = verify_receipt_chain(root, index_path)
            payload = load_structured(index_path)
            receipt_count = len(payload.get("receipts", [])) if isinstance(payload, dict) else 0
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            print(json.dumps({"ok": False, "errors": [str(exc)]}, ensure_ascii=False))
            return 2
        print(json.dumps({"ok": not errors, "receipts": receipt_count, "errors": errors}, ensure_ascii=False))
        return 0 if not errors else 1
    missing = [
        name for name, value in (("--run-id", args.run_id), ("--stage", args.stage), ("--receipt", args.receipt))
        if not value
    ]
    if missing:
        print(json.dumps({"ok": False, "errors": [f"{name} is required unless --verify-chain is used" for name in missing]}, ensure_ascii=False))
        return 2
    argv = [part for part in args.argv if part != "--"]
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        print(json.dumps({"ok": False, "errors": ["no command given after '--'"]}, ensure_ascii=False))
        return 2
    manifest_path = None
    if args.manifest:
        manifest_path = (root / args.manifest).resolve() if not Path(args.manifest).is_absolute() else Path(args.manifest).resolve()
    use_v2 = bool(args.v2 or (manifest_path is not None and _read_manifest_schema(manifest_path) == "2.0"))
    try:
        return _run_v2(args, root, manifest_path, argv) if use_v2 else _run_v1(args, root, argv)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)]}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
