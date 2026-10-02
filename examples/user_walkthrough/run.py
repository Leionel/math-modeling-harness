"""Execute documented public CLI steps in a fresh, retained teaching project."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "scripts" / "harness.py"
sys.path.insert(0, str(REPO / "scripts"))
from command_display import render_command  # noqa: E402


def run(project: Path) -> None:
    def command(argv: list[str], expected: int = 0) -> str:
        print(
            "$ "
            + render_command(argv)[
                "powershell" if sys.platform == "win32" else "posix"
            ],
            flush=True,
        )
        result = subprocess.run(
            argv,
            cwd=project,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        print(result.stdout, end="", flush=True)
        if result.returncode != expected:
            raise RuntimeError(
                f"exit={result.returncode}, expected={expected}\n{result.stderr}"
            )
        return result.stdout

    def harness(*args: str, expected: int = 0) -> str:
        return command(
            [sys.executable, str(CLI), *args, "--project", str(project)], expected
        )

    init = json.loads(
        harness("init", "--competition", "cumcm", "--preset", "sprint", "--json")
    )
    assert init["ok"]
    manifest = json.loads((project / "run_manifest.json").read_text(encoding="utf-8"))
    run_id = manifest["run_id"]
    harness("doctor", "--stage", "M1", "--offline")
    harness("model")
    contract = {
        "schema_version": "1.3",
        "project_id": manifest["project_id"],
        "run_id": run_id,
        "unit_system": "dimensionless",
        "status": "ready",
        "data_sources": [],
        "assumptions": [],
        "terminology": [],
        "questions": [
            {
                "question_id": "q2",
                "task": "minimize (x-3)^2 over integers 0..8",
                "conclusion_type": "minimum score",
                "inputs": [],
                "outputs": ["minimum_score"],
            }
        ],
        "models": [
            {
                "model_id": "MODEL-Q2",
                "question_id": "q2",
                "name": "finite enumeration",
                "problem_type": "optimization",
                "rationale": "nine candidates can be exhaustively inspected",
                "variables": [
                    {
                        "symbol": "x",
                        "meaning": "candidate integer",
                        "unit": "1",
                        "domain": "{0,..,8}",
                        "role": "decision",
                    }
                ],
                "objective": "minimize (x-3)^2",
                "constraints": [
                    {
                        "constraint_id": "C-Q2",
                        "expression": "x in {0,..,8}",
                        "meaning": "teaching domain",
                    }
                ],
                "algorithm": "enumeration",
                "inputs": [],
                "outputs": ["minimum_score"],
                "validation": [
                    {
                        "check_id": "V-Q2",
                        "stage": "both",
                        "method": "independent square nonnegativity",
                        "acceptance": "analytic error zero",
                    }
                ],
                "validation_obligations": [
                    {
                        "obligation_id": "VAL-Q2",
                        "category": "objective_recomputation",
                        "method": "compare with analytic minimum",
                        "required_stage": "both",
                        "acceptance": {
                            "left_metric_id": "analytic_error",
                            "operator": "==",
                            "right": {"kind": "literal", "value": 0},
                            "unit": "1",
                        },
                    }
                ],
                "risks": ["does not generalize to contest data"],
                "fallback": "inspect every candidate",
            }
        ],
    }
    (project / ".harness/authoring/model_contract.yaml").write_text(
        yaml.safe_dump({"model_contract": contract}, allow_unicode=True),
        encoding="utf-8",
    )
    harness("model", "--compile")
    harness("figure", "FIG-Q2", "--semantic-type", "trend")
    for name in ("solver.py", "verify.py"):
        shutil.copyfile(Path(__file__).with_name(name), project / name)

    # Execute uses a remainder argument: project options precede '--'.
    def execute(
        stage: str,
        receipt: str,
        argv: list[str],
        outputs: list[str],
        selected: bool = False,
    ) -> None:
        args = [
            sys.executable,
            str(CLI),
            "execute",
            "--project",
            str(project),
            "--stage",
            stage,
            "--receipt",
            receipt,
            "--freeze",
        ]
        if selected:
            args.append("--selected")
        for output in outputs:
            args.extend(["--output-artifact", output])
        args.extend(["--", *argv])
        command(args)

    execute(
        "full",
        "receipts/full.json",
        [sys.executable, "solver.py"],
        ["raw_results.json"],
        selected=True,
    )
    execute(
        "qa",
        "receipts/verify.json",
        [sys.executable, "verify.py", run_id],
        ["measurements.json"],
    )
    execute(
        "qa",
        "receipts/validation.json",
        [
            sys.executable,
            str(REPO / "scripts/validation/evaluate_obligations.py"),
            "--model-contract",
            ".harness/contracts/model_contract.json",
            "--measurements",
            "measurements.json",
            "--output",
            "validation.json",
        ],
        ["validation.json"],
    )
    freeze_argv = [
        sys.executable,
        str(CLI),
        "freeze",
        "--project",
        str(project),
        "--kind",
        "results",
        "--source",
        "raw_results.json",
        "--output",
        ".harness/results/frozen_results.json",
        "--run-id",
        run_id,
        "--model-contract",
        ".harness/contracts/model_contract.json",
        "--code",
        "solver.py",
        "--code",
        "verify.py",
        "--validation",
        "validation.json",
        "--receipt",
        "receipts/full.json",
        "--manifest",
        "run_manifest.json",
    ]
    execute(
        "freeze",
        "receipts/freeze.json",
        freeze_argv,
        [".harness/results/frozen_results.json"],
        selected=True,
    )
    full = json.loads((project / "receipts/full.json").read_text(encoding="utf-8"))
    assert full["exit_code"] == 0 and full["stage"] == "full"
    assert full["argv"] == [sys.executable, "solver.py"]
    assert (project / full["stdout_path"]).is_file()
    frozen = json.loads(
        (project / ".harness/results/frozen_results.json").read_text(encoding="utf-8")
    )
    assert frozen["validation_verdict"] == "PASS" and frozen["results"][0]["value"] == 0
    status = json.loads(harness("status", "--json"))
    assert status["first_blocked_gate"] == "m1"
    assert status["pending_human_checkpoints"]
    harness("check", "M1", "--json", expected=1)
    print(
        f"Teaching execution/validation/freeze completed; formal M1 remains blocked.\nProject retained: {project}"
    )


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project",
        type=Path,
        help="new or empty directory; defaults to a retained temporary directory",
    )
    args = parser.parse_args()
    project = (
        args.project.resolve()
        if args.project
        else Path(tempfile.mkdtemp(prefix="harness tutorial "))
    )
    if project.exists() and any(project.iterdir()):
        parser.error("tutorial requires a new or empty project directory")
    project.mkdir(parents=True, exist_ok=True)
    print(f"Project: {project}", flush=True)
    try:
        run(project)
    except (RuntimeError, AssertionError, OSError) as exc:
        print(f"ERROR: {exc}\nProject retained: {project}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
