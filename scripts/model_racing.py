#!/usr/bin/env python3
"""Minimal factual Model Racing harness.

Core principle:
    same problem snapshot
           ↓
    multiple falsifiable model hypotheses
           ↓
    common base checkpoint
           ↓
    fork branch A / B / C
           ↓
    independent execute -> validate -> freeze
           ↓
    factual side-by-side comparison (no subjective LLM ranking)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import checkpoints  # noqa: E402
from _common import child_env, load_structured, write_json  # noqa: E402
from runtime import check_gate  # noqa: E402

CHILD_ENV = child_env()


def load_race_spec(spec_path: Path) -> dict[str, Any]:
    data = load_structured(spec_path)
    if not isinstance(data, dict):
        raise ValueError("Race spec must be a structured dictionary")
    if "candidate_models" not in data or not isinstance(data["candidate_models"], list):
        raise ValueError("Race spec requires a non-empty candidate_models list")
    if len(data["candidate_models"]) < 2:
        raise ValueError("Model racing requires at least 2 candidate models")
    ids: set[str] = set()
    for candidate in data["candidate_models"]:
        cid = candidate.get("id") if isinstance(candidate, dict) else None
        if not isinstance(cid, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", cid):
            raise ValueError(f"invalid candidate id: {cid!r}")
        if cid.lower() in ids:
            raise ValueError(f"duplicate candidate id: {cid}")
        ids.add(cid.lower())
    return data


def extract_candidate_facts(branch_root: Path, candidate_meta: dict[str, Any]) -> dict[str, Any]:
    """Collect factual execution, gate, validation, and result metrics from a branch."""
    cid = candidate_meta.get("id", branch_root.name)
    facts: dict[str, Any] = {
        "candidate_id": cid,
        "name": candidate_meta.get("name", cid),
        "method_cards": candidate_meta.get("method_cards", []),
        "hypothesis": candidate_meta.get("hypothesis", ""),
        "assumptions": candidate_meta.get("assumptions", []),
        "branch_root": str(branch_root),
        "gates": {},
        "validations": {},
        "results": {},
        "receipts": [],
        "errors": [],
        "passed_all_gates": False,
    }

    # Check key gates (M1, P1, P2)
    gate_outcomes = {}
    for g in ("M1", "P1", "P2"):
        try:
            view = check_gate(branch_root, g)
            gate_outcomes[g] = {
                "exit_code": view.exit_code,
                "passed": view.exit_code == 0,
                "blockers": [str(b) for b in (view.payload.get("blockers") or view.payload.get("errors") or [])],
            }
        except Exception as exc:
            gate_outcomes[g] = {"exit_code": -1, "passed": False, "blockers": [str(exc)]}
    facts["gates"] = gate_outcomes
    facts["passed_all_gates"] = all(item["passed"] for item in gate_outcomes.values())

    # Load frozen results if available
    frozen_path = branch_root / "frozen_results.json"
    if frozen_path.is_file():
        try:
            frozen = load_structured(frozen_path)
            if isinstance(frozen, dict):
                facts["validation_verdict"] = frozen.get("validation_verdict")
                facts["claimable"] = frozen.get("claimable", False)
                for res in frozen.get("results", []):
                    if isinstance(res, dict) and "name" in res and "value" in res:
                        facts["results"][res["name"]] = {
                            "value": res["value"],
                            "unit": res.get("unit", ""),
                            "precision": res.get("precision"),
                        }
        except Exception as exc:
            facts["errors"].append(f"Failed to read frozen_results.json: {exc}")
    else:
        # Check raw_results.json fallback
        raw_path = branch_root / "raw_results.json"
        if raw_path.is_file():
            try:
                raw = load_structured(raw_path)
                if isinstance(raw, dict):
                    for res in raw.get("results", []):
                        if isinstance(res, dict) and "name" in res and "value" in res:
                            facts["results"][res["name"]] = {"value": res["value"]}
            except Exception as exc:
                facts["errors"].append(f"Failed to read raw_results.json: {exc}")

    # Inspect receipts in branch
    receipt_dir = branch_root / "receipts"
    if receipt_dir.is_dir():
        for rpath in sorted(receipt_dir.glob("*.json")):
            try:
                rcpt = load_structured(rpath)
                if isinstance(rcpt, dict):
                    facts["receipts"].append({
                        "receipt_id": rcpt.get("receipt_id", rpath.stem),
                        "stage": rcpt.get("stage"),
                        "exit_code": rcpt.get("exit_code"),
                        "duration_s": rcpt.get("duration_s"),
                    })
            except Exception:
                pass

    return facts


def build_racing_comparison(race_spec: dict[str, Any], candidate_facts: list[dict[str, Any]]) -> dict[str, Any]:
    """Assemble purely factual comparison matrix without subjective ranking."""
    all_metrics: set[str] = set()
    for cand in candidate_facts:
        all_metrics.update(cand.get("results", {}).keys())

    comparison_rows = []
    for cand in candidate_facts:
        gates_summary = {g: info["passed"] for g, info in cand.get("gates", {}).items()}
        total_duration = sum(float(r.get("duration_s") or 0.0) for r in cand.get("receipts", []))
        row = {
            "candidate_id": cand["candidate_id"],
            "name": cand["name"],
            "hypothesis": cand["hypothesis"],
            "method_cards": cand["method_cards"],
            "gates_passed": gates_summary,
            "validation_verdict": cand.get("validation_verdict", "N/A"),
            "claimable": cand.get("claimable", False),
            "results": {m: cand.get("results", {}).get(m, {}).get("value") for m in sorted(all_metrics)},
            "receipt_count": len(cand.get("receipts", [])),
            "total_execution_duration_s": round(total_duration, 3),
            "blockers": [b for g in cand.get("gates", {}).values() for b in g.get("blockers", [])],
        }
        comparison_rows.append(row)

    return {
        "schema_version": "1.0",
        "race_id": race_spec.get("race_id", "unnamed_race"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "problem_snapshot": race_spec.get("problem_snapshot"),
        "candidates": comparison_rows,
        "selection_guidance": "Selection must be determined by verified gate pass and domain validation criteria. No automated LLM verdict applied.",
    }


def render_comparison_markdown(comparison: dict[str, Any]) -> str:
    lines = [
        f"# Model Racing Comparison: {comparison['race_id']}",
        "",
        f"- **Generated At**: {comparison['generated_at']}",
        f"- **Problem Snapshot**: `{comparison.get('problem_snapshot')}`",
        "",
        "## Candidate Summary & Factual Matrix",
        "",
        "| Candidate | Method Cards | Gate M1/P1/P2 | Validation | Metrics | Duration | Status |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for cand in comparison.get("candidates", []):
        gates = cand.get("gates_passed", {})
        gate_str = "/".join(["PASS" if gates.get(g) else "FAIL" for g in ("M1", "P1", "P2")])
        metrics_str = ", ".join(f"{k}={v}" for k, v in cand.get("results", {}).items() if v is not None) or "None"
        status_str = "CLAIMABLE" if cand.get("claimable") else ("BLOCKERS" if cand.get("blockers") else "UNFROZEN")
        cards_str = "<br>".join(cand.get("method_cards", []))
        lines.append(
            f"| **{cand['candidate_id']}** ({cand['name']}) | {cards_str} | {gate_str} | {cand['validation_verdict']} | {metrics_str} | {cand['total_execution_duration_s']}s | {status_str} |"
        )

    lines.extend([
        "",
        "## Detailed Hypotheses & Assumptions",
        "",
    ])

    for cand in comparison.get("candidates", []):
        lines.append(f"### {cand['candidate_id']}: {cand['name']}")
        lines.append(f"- **Hypothesis**: {cand['hypothesis']}")
        if cand.get("blockers"):
            lines.append("- **Gate Blockers / Errors**:")
            for b in cand["blockers"]:
                lines.append(f"  - `{b}`")
        lines.append("")

    return "\n".join(lines)


def run_model_race(
    spec_path: Path,
    base_project: Path,
    output_dir: Path,
    *,
    execute_runners: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute full model race workflow."""
    spec = load_race_spec(spec_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_name = spec.get("base_checkpoint", "baseline")

    # 1. Verify or create checkpoint on base project
    ckpt_file = base_project / ".harness" / "checkpoints" / f"{checkpoint_name}.json"
    if not ckpt_file.is_file():
        checkpoints.create_checkpoint(base_project, checkpoint_name, force=True)

    branches_dir = output_dir / "branches"
    branches_dir.mkdir(parents=True, exist_ok=True)

    candidate_facts = []

    for cand in spec["candidate_models"]:
        cid = cand["id"]
        branch_root = branches_dir / cid
        if branch_root.is_symlink():
            raise ValueError(f"candidate branch must not be a symlink: {cid}")
        if branch_root.exists():
            shutil.rmtree(branch_root)

        # Fork branch from common checkpoint
        checkpoints.fork_project(base_project, checkpoint_name, branch_root, force=True)

        # If custom runner provided, run it on the branch
        if execute_runners and cid in execute_runners:
            runner_fn = execute_runners[cid]
            runner_fn(branch_root, cand)

        # Extract facts from branch
        facts = extract_candidate_facts(branch_root, cand)
        candidate_facts.append(facts)

    comparison = build_racing_comparison(spec, candidate_facts)
    md_content = render_comparison_markdown(comparison)

    write_json(output_dir / "race_summary.json", comparison, overwrite=True)
    (output_dir / "comparison.md").write_text(md_content, encoding="utf-8")
    return comparison


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, help="Path to race spec (JSON/YAML)")
    parser.add_argument("--base-project", required=True, help="Path to base project holding checkpoint")
    parser.add_argument("--output-dir", required=True, help="Output directory for race branches and comparison")
    args = parser.parse_args()

    spec_path = Path(args.spec).resolve()
    base_project = Path(args.base_project).resolve()
    output_dir = Path(args.output_dir).resolve()

    try:
        comparison = run_model_race(spec_path, base_project, output_dir)
        print(json.dumps({"ok": True, "race_id": comparison["race_id"], "output_dir": str(output_dir)}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
