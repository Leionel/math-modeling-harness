"""Build a disposable UI fixture; pending figure declarations grant no Gate PASS."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from _common import write_json_atomic  # noqa: E402
from tests.test_illustration_execution import BRIEF  # noqa: E402


def build() -> Path:
    project = Path(tempfile.mkdtemp(prefix="harness-atlas-preview-")) / "project"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "examples/user_walkthrough/run.py"),
            "--project",
            str(project),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    chart = project / "figures/FIG-Q2-CURVE/curve.png"
    chart.parent.mkdir(parents=True)
    values = [(x, (x - 3) ** 2) for x in range(9)]
    fig, ax = plt.subplots(figsize=(6, 4), layout="constrained")
    ax.plot(
        [v[0] for v in values],
        [v[1] for v in values],
        "o-",
        color="#1c658c",
        linewidth=2,
    )
    ax.set(
        xlabel="Integer candidate x",
        ylabel="Quadratic score (x - 3)^2",
        xticks=range(9),
    )
    ax.grid(axis="y", color="#dce6ee")
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(chart, dpi=180)
    plt.close(fig)
    brief = project / "figures/FIG-Q2-MECHANISM/brief.md"
    brief.parent.mkdir(parents=True)
    brief.write_text(BRIEF.replace("FIG-MECH", "FIG-Q2-MECHANISM"), encoding="utf-8")
    manifest_path = project / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    plan = {
        "run_id": manifest["run_id"],
        "claims": [
            {"claim_id": "C-Q2", "question_id": "q2", "text": "Teaching result only"}
        ],
        "figures": [
            {
                "figure_id": "FIG-Q2-CURVE",
                "kind": "data",
                "claim_ids": ["C-Q2"],
                "message": "Quadratic score across integer candidates",
                "purpose": "Inspect the teaching domain",
                "data_artifacts": [],
                "data_lineage": {"output_artifact": "figures/FIG-Q2-CURVE/curve.png"},
                "qa_status": "pending",
            },
            {
                "figure_id": "FIG-Q2-MECHANISM",
                "kind": "illustration",
                "claim_ids": ["C-Q2"],
                "message": "Mechanism illustration prompt · UI test fixture",
                "purpose": "Exercise manual generation handoff",
                "qa_status": "pending",
            },
        ],
    }
    write_json_atomic(project / "atlas_plan.json", plan)
    manifest["roots"]["paper_plan"] = {"path": "atlas_plan.json"}
    write_json_atomic(manifest_path, manifest)
    return project


if __name__ == "__main__":
    print(build())
