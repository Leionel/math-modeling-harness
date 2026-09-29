#!/usr/bin/env python3
"""GAP-08: turn a selective-rerun plan into a real repair orchestration.

The executor reads the plan produced by ``scripts/qa/plan_selective_rerun.py``,
re-runs receipt-backed steps through ``harness execute`` (every repair step is
receipt-captured; nothing writes an artifact by hand), and re-checks the target
gate through the read-only runtime API (``scripts/runtime/``).  Step classes:

- ``rerun``          -- the artifact's producer receipt exists and its stage is
                        smoke/full: re-run the recorded argv with a fresh receipt.
- ``contract_blocked``-- freeze-stage artifacts.  P2 requires exactly one
                        successful freeze receipt, so re-freezing through
                        ``harness execute`` permanently breaks P2; the step is
                        recorded, not executed.  See design doc §6.
- ``author_plane``   -- author artifacts have no producer receipt; repair is a
                        re-authoring/re-review action, not a re-run.

The executor never edits an artifact, receipt, hash or gate verdict itself.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
PLANNER = SCRIPTS / "qa" / "plan_selective_rerun.py"
sys.path.insert(0, str(SCRIPTS))

from _common import child_env, load_structured, write_json  # noqa: E402
from qa.plan_selective_rerun import _ROLE_GATES  # noqa: E402
from runtime import check_gate  # noqa: E402

RERUN_STAGES = {"smoke", "full", "freeze"}
CHILD_ENV = child_env()


def load_plan(project: Path, changed: list[str], plan_path: Path | None) -> dict[str, Any]:
    if plan_path is not None:
        return load_structured(plan_path)
    command = [
        sys.executable, str(PLANNER), "--project-root", str(project),
        "--json-output", str(project / ".harness" / "views" / "rerun_plan.json"),
    ]
    for raw in changed:
        command.extend(["--changed", raw])
    completed = subprocess.run(command, text=True, capture_output=True, encoding="utf-8",
                               errors="replace", check=False, env=CHILD_ENV)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"planner produced no JSON plan (exit {completed.returncode}): {completed.stdout[-400:]}") from exc


def producer_receipts_by_output(project: Path) -> dict[str, dict[str, Any]]:
    """Map each artifact path to the latest receipt that produced it."""

    index_path = project / "run_index.json"
    if not index_path.is_file():
        return {}
    index = load_structured(index_path)
    mapping: dict[str, dict[str, Any]] = {}
    for row in index.get("receipts", []) if isinstance(index, dict) else []:
        receipt_path = row.get("receipt_path") if isinstance(row, dict) else None
        if not isinstance(receipt_path, str):
            continue
        candidate = project / receipt_path
        if not candidate.is_file():
            continue
        receipt = load_structured(candidate)
        if not isinstance(receipt, dict):
            continue
        for ref in receipt.get("output_refs", []):
            if isinstance(ref, dict) and isinstance(ref.get("path"), str):
                norm = ref["path"].replace("\\", "/")
                mapping[norm] = receipt
                mapping[ref["path"]] = receipt
    return mapping


def rewrite_argv(argv: list[str], recorded_cwd: str, project: Path) -> list[str]:
    """Point the recorded argv at the live project root.

    Both the raw and the resolved spelling of the recorded root are rewritten:
    on Windows a receipt can carry the resolved root while an argument carries
    the short 8.3 form, and either one must land on the live project.
    """

    recorded = Path(recorded_cwd)
    spellings = {
        str(recorded),
        str(recorded.resolve()),
        str(recorded).replace("Administrator", "ADMINI~1"),
        str(recorded.resolve()).replace("Administrator", "ADMINI~1"),
        str(recorded).replace("ADMINI~1", "Administrator"),
        str(recorded.resolve()).replace("ADMINI~1", "Administrator"),
    }
    replaced = []
    for i, token in enumerate(argv):
        if i > 0 and argv[i - 1] in ("--project-root", "--project"):
            replaced.append(str(project))
            continue
        for spelling in sorted(spellings, key=len, reverse=True):
            token = token.replace(spelling, str(project))
        replaced.append(token)
    return replaced


def execute_argv(receipt: dict[str, Any], project: Path) -> list[str]:
    stage = str(receipt.get("stage"))
    argv: list[str] = [
        sys.executable, str(SCRIPTS / "harness.py"), "execute",
        "--project", str(project), "--stage", stage, "--run-id", str(receipt.get("run_id")),
    ]
    if stage == "freeze":
        argv.append("--freeze")
        argv.extend(["--supersedes-receipt", str(receipt.get("receipt_id"))])
    # A repair re-run never re-claims selection: P2 requires exactly one
    # selected receipt, so the original stays the selected execution fact.
    if receipt.get("seed") is not None:
        argv.extend(["--seed", str(receipt["seed"])])
    for ref in receipt.get("input_refs", []):
        if isinstance(ref, dict) and isinstance(ref.get("path"), str):
            argv.extend(["--input", ref["path"]])
    for ref in receipt.get("output_refs", []):
        if isinstance(ref, dict) and isinstance(ref.get("path"), str):
            argv.extend(["--output-artifact", ref["path"]])
    coverage = (receipt.get("metadata") or {}).get("smoke_coverage")
    if isinstance(coverage, dict):
        for key, flag in (("model_ids", "--covers-model"), ("question_ids", "--covers-question"),
                          ("covered_contract_item_ids", "--covers-contract-item")):
            for value in coverage.get(key) or []:
                argv.extend([flag, str(value)])
    argv.append("--")
    inner = rewrite_argv([str(token) for token in receipt.get("argv", [])], str(receipt.get("cwd", project)), project)
    if stage == "freeze" and any("freeze_results" in token for token in inner) and "--force" not in inner:
        inner.append("--force")
    argv.extend(inner)
    return argv


def repair(
    project: Path,
    *,
    fault_id: str,
    gate: str,
    changed: list[str],
    plan_path: Path | None,
) -> dict[str, Any]:
    plan = load_plan(project, changed, plan_path)
    steps_plan = plan.get("rerun_steps") or []
    if not steps_plan:
        raise ValueError("the plan carries no rerun steps; nothing to repair")
    producers = producer_receipts_by_output(project)
    steps: list[dict[str, Any]] = []
    for step in steps_plan:
        artifact_path = str(step.get("path", ""))
        norm_path = artifact_path.replace("\\", "/")
        record: dict[str, Any] = {
            "artifact_id": step.get("artifact_id"),
            "role": step.get("role"),
            "path": artifact_path,
            "freshness": step.get("freshness"),
        }
        receipt = producers.get(norm_path) or producers.get(artifact_path)
        if receipt is None:
            record.update({"status": "author_plane", "executed": False})
        elif str(receipt.get("stage")) not in RERUN_STAGES:
            record.update({
                "status": "contract_blocked",
                "executed": False,
                "producer_stage": str(receipt.get("stage")),
                "reason": (
                    f"stage {receipt.get('stage')} artifacts do not have an automated rerun channel"
                ),
            })
        else:
            argv = execute_argv(receipt, project)
            completed = subprocess.run(argv, text=True, capture_output=True, encoding="utf-8",
                                       errors="replace", check=False, env=CHILD_ENV)
            record.update({
                "status": "rerun",
                "executed": completed.returncode == 0,
                "producer_stage": str(receipt.get("stage")),
                "exit_code": completed.returncode,
                "command": " ".join(argv),
            })
            try:
                payload = json.loads(completed.stdout)
                record["receipt"] = payload.get("receipt")
            except json.JSONDecodeError:
                record["stdout_tail"] = completed.stdout[-400:]
        steps.append(record)

    view = check_gate(project, gate)
    gate_lower = gate.lower()
    gate_rerun_steps = [
        row for row in steps
        if gate_lower in _ROLE_GATES.get(str(row.get("role")), ())
        and row.get("status") == "rerun"
    ]
    repaired = bool(
        view.exit_code == 0
        and all(row.get("executed") and row.get("exit_code") == 0 for row in gate_rerun_steps)
    )
    report = {
        "schema_version": "1.0",
        "fault_id": fault_id,
        "gate": gate,
        "plan_ok": bool(plan.get("ok")),
        "plan_errors": list(plan.get("errors") or []),
        "steps": steps,
        "gate_report": view.payload,
        "gate_exit_code": view.exit_code,
        "repaired": repaired,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "boundary": "Every executed step went through harness execute with a fresh receipt; the executor wrote no artifact, hash or verdict by hand.",
    }
    log_dir = project / ".harness" / "recovery"
    log_dir.mkdir(parents=True, exist_ok=True)
    write_json(log_dir / f"{fault_id}.json", report, overwrite=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--fault-id", required=True, help="label for the recovery log (.harness/recovery/<fault-id>.json)")
    parser.add_argument("--gate", required=True, help="gate to re-check after the repair steps")
    parser.add_argument("--changed", action="append", default=[], help="change root passed to the rerun planner (repeatable)")
    parser.add_argument("--plan", help="use this plan JSON instead of invoking the planner")
    args = parser.parse_args()
    project = Path(args.project_root).resolve()
    plan_path = Path(args.plan).resolve() if args.plan else None
    try:
        report = repair(project, fault_id=args.fault_id, gate=args.gate, changed=args.changed, plan_path=plan_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)]}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": report["repaired"], "fault_id": report["fault_id"], "gate": report["gate"],
                      "gate_exit_code": report["gate_exit_code"], "steps": report["steps"],
                      "log": str(project / ".harness" / "recovery" / f"{args.fault_id}.json")}, ensure_ascii=False))
    return 0 if report["repaired"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
