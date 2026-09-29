from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "harness.py"
DEMO = ROOT / "examples" / "end_to_end" / "run_demo.py"
sys.path.insert(0, str(ROOT / "scripts"))

import checkpoints  # noqa: E402
import run_diff  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def project_snapshot(root: Path, *, include_checkpoint_records: bool = True) -> dict[str, str]:
    """Digest every file in the run; checkpoint records can be excluded when the
    test is asserting that recording a checkpoint leaves the run itself alone."""

    def included(path: Path) -> bool:
        relative = str(path.relative_to(root))
        return include_checkpoint_records or not relative.startswith((".harness/checkpoints", ".harness\\checkpoints"))

    return {
        str(path.relative_to(root)): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and included(path)
    }


def bump_first_number(path: Path) -> bool:
    document = json.loads(path.read_text(encoding="utf-8"))

    def walk(node: object) -> bool:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    node[key] = value + 1
                    return True
                if walk(value):
                    return True
        elif isinstance(node, list):
            for item in node:
                if walk(item):
                    return True
        return False

    changed = walk(document)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return changed


class CheckpointAndDiffTest(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="checkpoint-diff-")
        cls.demo = Path(cls.temp.name) / "demo"
        built = subprocess.run(
            [sys.executable, str(DEMO), "--out", str(cls.demo), "--quiet", "--skip-probes"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if built.returncode != 0:
            raise AssertionError(f"demo build failed: {built.stdout}\n{built.stderr}")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def clone_demo(self, name: str) -> Path:
        target = Path(self.temp.name) / name
        shutil.copytree(self.demo, target)
        return target

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def test_checkpoint_records_control_receipts_and_artifacts(self) -> None:
        project = self.clone_demo("record")
        before = project_snapshot(project, include_checkpoint_records=False)
        document = checkpoints.create_checkpoint(project, "base")
        self.assertEqual(
            before,
            project_snapshot(project, include_checkpoint_records=False),
            "checkpointing must not touch the run",
        )
        recorded = set(document["files"])
        self.assertIn("run_manifest.json", recorded)
        self.assertIn("artifact_dag.json", recorded)
        self.assertTrue(any(name.startswith("receipts/") for name in recorded))
        self.assertIn("model_contract.json", recorded)
        for relative, digest in document["files"].items():
            self.assertEqual(digest, sha256(project / relative), relative)

    def test_verify_detects_drift_and_missing_files(self) -> None:
        project = self.clone_demo("verify")
        checkpoints.create_checkpoint(project, "base")
        ok, errors = checkpoints.verify_checkpoint(project, "base")
        self.assertTrue(ok, errors)
        bump_first_number(project / "frozen_results.json")
        (project / "paper.txt").unlink()
        ok, errors = checkpoints.verify_checkpoint(project, "base")
        self.assertFalse(ok)
        self.assertIn("digest drift: frozen_results.json", errors)
        self.assertIn("missing file: paper.txt", errors)

    def test_fork_copies_digest_identical_files_and_records_parent(self) -> None:
        project = self.clone_demo("fork-source")
        document = checkpoints.create_checkpoint(project, "base")
        destination = Path(self.temp.name) / "fork-child"
        record = checkpoints.fork_project(project, "base", destination, branch="branch-b")
        self.assertEqual(record["parent_checkpoint"], "ckpt-base")
        self.assertEqual(record["branch"], "branch-b")
        for relative, digest in document["files"].items():
            self.assertEqual(digest, sha256(destination / relative), relative)
        ok, errors = checkpoints.verify_checkpoint(destination, "base")
        self.assertTrue(ok, errors)

    def test_fork_refuses_a_drifted_source(self) -> None:
        project = self.clone_demo("fork-drifted")
        checkpoints.create_checkpoint(project, "base")
        bump_first_number(project / "frozen_results.json")
        with self.assertRaises(ValueError) as caught:
            checkpoints.fork_project(project, "base", Path(self.temp.name) / "fork-never")
        self.assertIn("no longer matches", str(caught.exception))
        self.assertFalse((Path(self.temp.name) / "fork-never").exists())

    def test_fork_rejects_checkpoint_path_outside_project(self) -> None:
        project = self.clone_demo("fork-path-source")
        checkpoints.create_checkpoint(project, "base")
        outside_source = Path(self.temp.name) / "payload.txt"
        outside_source.write_text("source bytes", encoding="utf-8")
        checkpoint_file = checkpoints.checkpoint_path(project, "base")
        document = json.loads(checkpoint_file.read_text(encoding="utf-8"))
        document["files"]["../payload.txt"] = sha256(outside_source)
        checkpoint_file.write_text(json.dumps(document), encoding="utf-8")
        destination = Path(self.temp.name) / "fork-path-output" / "child"
        destination.parent.mkdir()
        outside_target = destination.parent / "payload.txt"
        outside_target.write_text("keep me", encoding="utf-8")

        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "checkpoints.py"), "fork",
             "--project-root", str(project), "--name", "base", "--output", str(destination)],
            text=True, capture_output=True, encoding="utf-8", errors="replace", check=False,
        )
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        self.assertIn("escapes project root", completed.stderr)
        self.assertEqual(outside_target.read_text(encoding="utf-8"), "keep me")
        self.assertFalse(destination.exists())

    def test_fork_refuses_a_non_empty_destination(self) -> None:
        project = self.clone_demo("fork-occupied")
        checkpoints.create_checkpoint(project, "base")
        destination = Path(self.temp.name) / "fork-occupied-child"
        destination.mkdir()
        (destination / "leftover.txt").write_text("occupied\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            checkpoints.fork_project(project, "base", destination)

    def test_create_refuses_overwrite_and_uncheckpointable_projects(self) -> None:
        project = self.clone_demo("create-guards")
        checkpoints.create_checkpoint(project, "base")
        with self.assertRaises(ValueError):
            checkpoints.create_checkpoint(project, "base")
        empty = Path(self.temp.name) / "empty"
        empty.mkdir()
        with self.assertRaises(ValueError):
            checkpoints.create_checkpoint(empty, "base")

    def test_diff_reports_artifact_content_change_and_gate_shift(self) -> None:
        project = self.clone_demo("diff-source")
        checkpoints.create_checkpoint(project, "base")
        child = Path(self.temp.name) / "diff-child"
        checkpoints.fork_project(project, "base", child, branch="branch-b")
        self.assertTrue(bump_first_number(child / "frozen_results.json"))
        before = project_snapshot(project)
        document = run_diff.diff_runs(project, child)
        self.assertEqual(before, project_snapshot(project), "diff must be read-only")
        changed_ids = [row["artifact_id"] for row in document["artifacts"]["content_changed"]]
        self.assertTrue(any("FROZEN" in artifact_id for artifact_id in changed_ids), changed_ids)
        self.assertEqual(document["gates"]["changed"].get("p2"), {"a": "pass", "b": "blocked"})
        self.assertEqual(document["a"]["fork"] if "fork" in document["a"] else None, None)
        self.assertEqual(document["b"]["fork"]["parent_checkpoint"], "ckpt-base")

    def test_compare_reports_checkpoint_truth_and_exit_codes(self) -> None:
        project = self.clone_demo("compare-source")
        checkpoints.create_checkpoint(project, "base")
        child = Path(self.temp.name) / "compare-child"
        checkpoints.fork_project(project, "base", child, branch="clean")
        document, code = run_diff.compare_runs(project, child)
        self.assertEqual(code, 0, document["checkpoint_problems"])
        self.assertTrue(all(row["ok"] for row in document["a"]["checkpoints"]))
        bump_first_number(child / "frozen_results.json")
        document, code = run_diff.compare_runs(project, child)
        self.assertEqual(code, 1)
        self.assertIn("digest drift: frozen_results.json", " ".join(document["checkpoint_problems"]))

    def test_cli_exit_codes_for_the_branching_commands(self) -> None:
        project = self.clone_demo("cli-source")
        created = self.run_cli("checkpoint", "create", "--project", str(project), "--name", "base", "--json")
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        self.assertTrue(json.loads(created.stdout)["ok"])

        verified = self.run_cli("checkpoint", "verify", "--project", str(project), "--name", "base", "--json")
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)

        child = Path(self.temp.name) / "cli-child"
        forked = self.run_cli(
            "fork", "--project", str(project), "--from", "base", "--name", "branch-b",
            "--output", str(child), "--json",
        )
        self.assertEqual(forked.returncode, 0, forked.stdout + forked.stderr)

        diffed = self.run_cli("diff", str(project), str(child), "--json")
        self.assertEqual(diffed.returncode, 0, diffed.stdout + diffed.stderr)
        self.assertTrue(json.loads(diffed.stdout)["ok"])

        compared = self.run_cli("compare", str(project), str(child), "--json")
        self.assertEqual(compared.returncode, 0, compared.stdout + compared.stderr)

        bump_first_number(project / "frozen_results.json")
        drifted = self.run_cli("checkpoint", "verify", "--project", str(project), "--name", "base", "--json")
        self.assertEqual(drifted.returncode, 1, drifted.stdout + drifted.stderr)
        self.assertFalse(json.loads(drifted.stdout)["ok"])

        compared = self.run_cli("compare", str(project), str(child), "--json")
        self.assertEqual(compared.returncode, 1)

        # A refused operation is a CLI error (exit 2 with the error envelope),
        # not a failed verdict; `checkpoint verify` above is the verdict path.
        refused = self.run_cli(
            "fork", "--project", str(project), "--from", "base", "--name", "again",
            "--output", str(child), "--json",
        )
        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
        self.assertFalse(json.loads(refused.stdout)["ok"])

    def test_checkpoint_list_reports_recorded_names(self) -> None:
        project = self.clone_demo("listing")
        checkpoints.create_checkpoint(project, "alpha")
        checkpoints.create_checkpoint(project, "beta")
        self.assertEqual(
            [row["name"] for row in checkpoints.list_checkpoints(project)],
            ["alpha", "beta"],
        )


if __name__ == "__main__":
    unittest.main()
