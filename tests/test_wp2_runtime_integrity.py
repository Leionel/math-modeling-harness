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
FIXTURE = ROOT / "tests" / "fixtures" / "wp2_runtime"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class WP2RuntimeIntegrityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="wp2-runtime-")
        self.project = Path(self.temp.name)
        shutil.copy2(FIXTURE / "competition_profile.json", self.project / "competition_profile.json")
        shutil.copy2(FIXTURE / "rules.txt", self.project / "rules.txt")
        model = {
            "schema_version": "1.3",
            "project_id": "wp2-project",
            "run_id": "run-1",
            "status": "ready",
            "questions": [{"question_id": "q1"}],
            "models": [{
                "model_id": "M1",
                "question_id": "q1",
                "plan_details": {"equation_plan": [{"equation_id": "EQ1"}]},
                "constraints": [],
                "validation_obligations": [],
            }],
        }
        (self.project / "model.json").write_text(json.dumps(model), encoding="utf-8")
        (self.project / "solver.py").write_text("def solve():\n    return 1\n", encoding="utf-8")
        (self.project / "test_solver.py").write_text("def test_solve():\n    assert True\n", encoding="utf-8")
        implementation_map = {
            "schema_version": "1.0",
            "run_id": "run-1",
            "model_contract": {"path": "model.json", "sha256": sha256(self.project / "model.json")},
            "symbols": [{
                "symbol_id": "S-X", "latex": "x", "meaning": "state", "unit": "1",
                "scope": "q1", "model_id": "M1",
            }],
            "equations": [{
                "equation_id": "EQ1", "model_id": "M1", "question_id": "q1", "kind": "identity",
                "latex": "x=x", "symbol_ids": ["S-X"], "contract_item_ids": ["EQ1"],
                "code_refs": [{
                    "path": "solver.py", "sha256": sha256(self.project / "solver.py"), "symbol": "solve",
                }],
                "tests": [{
                    "test_id": "TEST-EQ1", "path": "test_solver.py",
                    "sha256": sha256(self.project / "test_solver.py"), "purpose": "unit", "status": "pass",
                }],
                "status": "verified",
            }],
            "status": "verified",
        }
        (self.project / "implementation_map.json").write_text(json.dumps(implementation_map), encoding="utf-8")
        self._write_manifest()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_manifest(self, *, preset: str = "research", profile_id: str = "wp2-fixture") -> None:
        manifest = {
            "schema_version": "2.0", "project_id": "wp2-project", "run_id": "run-1", "status": "active",
            "stage": "results", "preset": preset, "profile_overrides": {},
            "competition_profile_ref": {"path": "competition_profile.json", "profile_id": profile_id},
            "roots": {
                "model_contract": {"path": "model.json"},
                "implementation_map": {"path": "implementation_map.json"},
                "run_index": {"path": "run_index.json"},
                "artifact_dag": {"path": "artifact_dag.json"},
            },
            "control": {"selection_policy": {"owner": "run_manifest.control", "rule": "exactly one selected receipt", "version": "2.0"}},
            "safety": {}, "ai_usage": [], "human_checkpoints": [],
        }
        (self.project / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def run_script(self, script: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), *args], cwd=self.project,
            text=True, capture_output=True, encoding="utf-8", errors="replace", check=False,
        )

    def run_record(
        self,
        *,
        stage: str,
        receipt: str,
        selected: bool = False,
        mode: str = "research",
        output: str | None = None,
        input_path: str | None = None,
        coverage: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        args = ["--v2", "--integrity-mode", mode, "--run-id", "run-1", "--stage", stage,
                "--receipt", receipt, "--index", "run_index.json", "--project-root", str(self.project)]
        if selected:
            args.append("--selected")
        if output:
            args.extend(["--output-artifact", output])
        if input_path:
            args.extend(["--input", input_path])
        if coverage:
            args.extend([
                "--covers-model", "M1",
                "--covers-question", "q1",
                "--covers-contract-item", "EQ1",
            ])
        code = "from pathlib import Path; Path('result.txt').write_text('result', encoding='utf-8')" if output else "print('ok')"
        args.extend(["--", sys.executable, "-c", code])
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "run_and_record.py"), *args], cwd=self.project,
                              text=True, capture_output=True, encoding="utf-8", errors="replace", check=False)

    def gate(self, name: str) -> subprocess.CompletedProcess[str]:
        return self.run_script("qa/check_gates.py", "--manifest", "run_manifest.json", "--project-root", str(self.project), "--gate", name)

    def _set_roots(self, **roles: str) -> None:
        manifest = json.loads((self.project / "run_manifest.json").read_text(encoding="utf-8"))
        for role, path in roles.items():
            manifest["roots"][role] = {"path": path}
        (self.project / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def _write_dag_roles(self, roles: list[tuple[str, str, dict[str, object] | None]]) -> None:
        nodes = []
        for index, (role, path, metadata) in enumerate(roles, start=1):
            nodes.append({
                "artifact_id": f"ART-{index}", "role": role, "path": path,
                "producer_id": f"producer-{role}", "dependencies": [],
                "lifecycle": "frozen" if role == "frozen_results" else "mutable",
                "freshness": "current", "digest_owner": "artifact_dag",
                "version": "1", "created_at": "2026-08-17T00:00:00Z",
                **({"metadata": metadata} if metadata is not None else {}),
            })
        (self.project / "artifact_dag.json").write_text(json.dumps({
            "schema_version": "2.0", "run_id": "run-1", "projection": "artifact_identity_dependency", "nodes": nodes,
        }), encoding="utf-8")

    def test_v2_fake_manifest_success_cannot_pass_p1(self) -> None:
        # No self-reported gates exist in v2; a fake status is irrelevant.
        result = self.gate("p1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("smoke receipt", result.stdout)

    def test_index_copy_tamper_does_not_change_verdict_but_receipt_tamper_does(self) -> None:
        run = self.run_record(stage="smoke", receipt="smoke.json", selected=True, coverage=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        index_path = self.project / "run_index.json"
        index = json.loads(index_path.read_text(encoding="utf-8"))
        index["receipts"][0]["exit_code"] = 99  # projection-only tamper
        index_path.write_text(json.dumps(index), encoding="utf-8")
        self.assertEqual(self.gate("p1").returncode, 0)
        receipt_path = self.project / "smoke.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["exit_code"] = 7
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        self.assertNotEqual(self.gate("p1").returncode, 0)

    def test_p2_recomputes_selected_receipt_io_digests_from_capabilities(self) -> None:
        (self.project / "input.txt").write_text("before", encoding="utf-8")
        full = self.run_record(stage="full", receipt="full-io.json", selected=True, mode="research", output="result.txt", input_path="input.txt")
        self.assertEqual(full.returncode, 0, full.stdout + full.stderr)
        (self.project / "input.txt").write_text("tampered", encoding="utf-8")
        result = self.gate("p2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("selected receipt", result.stdout)
        self.assertIn("SHA-256 drift", result.stdout)

    def test_research_p2_requires_the_verified_implementation_map_root(self) -> None:
        manifest = json.loads((self.project / "run_manifest.json").read_text(encoding="utf-8"))
        manifest["roots"].pop("implementation_map")
        (self.project / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        result = self.gate("p2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("implementation_map", result.stdout)

    def test_p2_recomputes_freeze_receipt_binding_digest(self) -> None:
        full = self.run_record(stage="full", receipt="full.json", selected=True, mode="research")
        self.assertEqual(full.returncode, 0, full.stdout + full.stderr)
        full_value = json.loads((self.project / "full.json").read_text(encoding="utf-8"))
        frozen = {
            "schema_version": "1.2", "run_id": "run-1", "status": "frozen", "claimable": True,
            "validation_verdict": "PASS", "results": [],
            "results_sha256": hashlib.sha256(b"[]").hexdigest(),
            "command": f"receipt:{full_value['receipt_id']}",
        }
        frozen_path = self.project / "frozen.json"
        frozen_path.write_text(json.dumps(frozen), encoding="utf-8")
        freeze_value = {
            "schema_version": "2.0", "receipt_id": "REC-FREEZE", "command_id": "CMD-FREEZE",
            "run_id": "run-1", "stage": "freeze", "argv": ["freeze"], "cwd": str(self.project),
            "exit_code": 0, "started_at": "2026-08-17T00:00:00Z", "finished_at": "2026-08-17T00:00:01Z",
            "stdout_path": "freeze.stdout", "stderr_path": "freeze.stderr", "input_refs": [],
            "output_refs": [{"path": "frozen.json", "artifact_id": "ART-FROZEN", "sha256": sha256(frozen_path), "digest_owner": "command_receipt", "critical": True}],
        }
        (self.project / "freeze.json").write_text(json.dumps(freeze_value), encoding="utf-8")
        index = json.loads((self.project / "run_index.json").read_text(encoding="utf-8"))
        index["receipts"].append({"receipt_id": "REC-FREEZE", "receipt_path": "freeze.json", "run_id": "run-1", "stage": "freeze", "selected": False, "projected_from": "command_receipt:REC-FREEZE"})
        (self.project / "run_index.json").write_text(json.dumps(index), encoding="utf-8")
        manifest = json.loads((self.project / "run_manifest.json").read_text(encoding="utf-8"))
        manifest["human_checkpoints"] = [{"checkpoint_id": "CP-P2", "stage": "p2", "decision": "pass"}]
        (self.project / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self._write_dag_roles([("frozen_results", "frozen.json", None)])
        dag = json.loads((self.project / "artifact_dag.json").read_text(encoding="utf-8"))
        dag["nodes"][0].update({
            "artifact_id": "ART-FROZEN",
            "producer_receipt_id": "REC-FREEZE",
            "digest_owner": "command_receipt:REC-FREEZE",
        })
        (self.project / "artifact_dag.json").write_text(json.dumps(dag), encoding="utf-8")
        self.assertEqual(self.gate("p2").returncode, 0)
        freeze_value["output_refs"][0]["sha256"] = "0" * 64
        (self.project / "freeze.json").write_text(json.dumps(freeze_value), encoding="utf-8")
        drift = self.gate("p2")
        self.assertNotEqual(drift.returncode, 0)
        self.assertIn("freeze receipt canonical frozen_results SHA-256 drift", drift.stdout)

    def test_p2_rejects_duplicate_digest_ownership_across_dag_and_receipt(self) -> None:
        full = self.run_record(stage="full", receipt="full.json", selected=True, mode="research")
        self.assertEqual(full.returncode, 0, full.stdout + full.stderr)
        full_value = json.loads((self.project / "full.json").read_text(encoding="utf-8"))
        frozen_path = self.project / "frozen.json"
        frozen_path.write_text(json.dumps({
            "schema_version": "1.2", "run_id": "run-1", "status": "frozen", "claimable": True,
            "validation_verdict": "PASS", "results": [], "results_sha256": hashlib.sha256(b"[]").hexdigest(),
            "command": f"receipt:{full_value['receipt_id']}",
        }), encoding="utf-8")
        freeze_value = {
            "schema_version": "2.0", "receipt_id": "REC-FREEZE", "command_id": "CMD-FREEZE",
            "run_id": "run-1", "stage": "freeze", "argv": ["freeze"], "cwd": str(self.project),
            "exit_code": 0, "started_at": "2026-08-17T00:00:00Z", "finished_at": "2026-08-17T00:00:01Z",
            "stdout_path": "freeze.stdout", "stderr_path": "freeze.stderr", "input_refs": [],
            "output_refs": [{"path": "frozen.json", "artifact_id": "ART-FROZEN", "sha256": sha256(frozen_path), "digest_owner": "command_receipt", "critical": True}],
        }
        (self.project / "freeze.json").write_text(json.dumps(freeze_value), encoding="utf-8")
        index = json.loads((self.project / "run_index.json").read_text(encoding="utf-8"))
        index["receipts"].append({"receipt_id": "REC-FREEZE", "receipt_path": "freeze.json", "run_id": "run-1", "stage": "freeze", "selected": False, "projected_from": "command_receipt:REC-FREEZE"})
        (self.project / "run_index.json").write_text(json.dumps(index), encoding="utf-8")
        manifest = json.loads((self.project / "run_manifest.json").read_text(encoding="utf-8"))
        manifest["human_checkpoints"] = [{"checkpoint_id": "CP-P2", "stage": "p2", "decision": "pass"}]
        (self.project / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self._write_dag_roles([("frozen_results", "frozen.json", None)])
        dag = json.loads((self.project / "artifact_dag.json").read_text(encoding="utf-8"))
        dag["nodes"][0].update({
            "artifact_id": "ART-FROZEN", "producer_receipt_id": "REC-FREEZE",
            "sha256": sha256(frozen_path), "digest_algorithm": "sha256",
        })
        (self.project / "artifact_dag.json").write_text(json.dumps(dag), encoding="utf-8")

        result = self.gate("p2")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("multiple digest owners", result.stdout)

    def test_failure_receipt_is_retained_when_declared_output_is_missing(self) -> None:
        result = self.run_record(stage="smoke", receipt="missing.json", mode="sprint", output="never/result.txt")
        self.assertEqual(result.returncode, 3)
        self.assertTrue((self.project / "missing.json").is_file())
        index = json.loads((self.project / "run_index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(index["receipts"]), 1)
        receipt = json.loads((self.project / "missing.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["metadata"]["failure_reason"], "declared_output_missing")

    def test_sprint_and_research_hash_policies(self) -> None:
        (self.project / "input.txt").write_text("input", encoding="utf-8")
        sprint = self.run_record(stage="full", receipt="sprint.json", mode="sprint", input_path="input.txt")
        self.assertEqual(sprint.returncode, 0)
        sprint_receipt = json.loads((self.project / "sprint.json").read_text(encoding="utf-8"))
        self.assertNotIn("sha256", sprint_receipt["input_refs"][0])
        research = self.run_record(stage="full", receipt="research.json", mode="research", selected=True, input_path="input.txt")
        self.assertEqual(research.returncode, 0)
        research_receipt = json.loads((self.project / "research.json").read_text(encoding="utf-8"))
        self.assertEqual(research_receipt["input_refs"][0]["sha256"], sha256(self.project / "input.txt"))

    def test_v2_rejects_unresolved_legacy_index_notes_without_illegal_metadata(self) -> None:
        legacy = {
            "schema_version": "1.0", "selection_policy": "first successful run", "run_id_scope": "run-1",
            "runs": [{"command_id": "old", "run_id": "run-1", "stage": "smoke", "receipt_path": "old.json", "selected": False, "recorded_at": "legacy"}],
        }
        (self.project / "run_index.json").write_text(json.dumps(legacy), encoding="utf-8")
        result = self.run_record(stage="smoke", receipt="new.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("explicit migration", result.stdout)
        value = json.loads((self.project / "run_index.json").read_text(encoding="utf-8"))
        self.assertEqual(value["schema_version"], "1.0")
        self.assertNotIn("metadata", value)

    def test_v2_m1_preserves_model_schema_and_obligation_failure(self) -> None:
        (self.project / "evidence.json").write_text("{}", encoding="utf-8")
        self._set_roots(evidence_registry="evidence.json")
        result = self.gate("m1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("check_modeling_plan", result.stdout)
        self.assertIn("model_contract schema", result.stdout)

    def test_v2_w1_preserves_paper_plan_evidence_failure(self) -> None:
        (self.project / "evidence.json").write_text("{}", encoding="utf-8")
        (self.project / "paper_plan.json").write_text("{}", encoding="utf-8")
        (self.project / "frozen.json").write_text(json.dumps({
            "schema_version": "1.2", "run_id": "run-1", "status": "frozen", "claimable": True,
            "validation_verdict": "PASS", "results": [], "results_sha256": sha256(self.project / "model.json"),
        }), encoding="utf-8")
        self._set_roots(evidence_registry="evidence.json", paper_plan="paper_plan.json")
        self._write_dag_roles([("frozen_results", "frozen.json", None)])
        result = self.gate("w1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("check_paper_readiness", result.stdout)
        self.assertIn("paper_plan schema", result.stdout)

    def _set_checkpoints(self, *rows: dict[str, object]) -> None:
        manifest = json.loads((self.project / "run_manifest.json").read_text(encoding="utf-8"))
        manifest["human_checkpoints"] = list(rows)
        (self.project / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    def test_v2_w1_agent_recorded_checkpoint_does_not_satisfy_the_human_requirement(self) -> None:
        self._set_checkpoints({
            "checkpoint_id": "CHK-W1-001", "stage": "w1", "decision": "pass",
            "actor_class": "agent", "decided_by": "orchestrator",
        })
        blocked = self.gate("w1")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("only agent-recorded checkpoints", blocked.stdout + blocked.stderr)

        # Rows written before actor_class existed predate the distinction, so an
        # existing run must not lose the checkpoints it already recorded.
        self._set_checkpoints({
            "checkpoint_id": "CHK-W1-001", "stage": "w1", "decision": "pass", "decided_by": "team lead",
        })
        legacy = self.gate("w1")
        self.assertNotIn("only agent-recorded checkpoints", legacy.stdout)
        self.assertNotIn("requires a confirmed w1 human checkpoint", legacy.stdout)

        self._set_checkpoints({
            "checkpoint_id": "CHK-W1-001", "stage": "w1", "decision": "pass",
            "actor_class": "agent", "decided_by": "orchestrator",
        }, {
            "checkpoint_id": "CHK-W1-002", "stage": "w1", "decision": "pass",
            "actor_class": "human", "decided_by": "team lead",
        })
        after_human = self.gate("w1")
        self.assertNotIn("only agent-recorded checkpoints", after_human.stdout)

    def test_v2_w2_deterministic_qa_failure_is_not_reduced_to_dag_presence(self) -> None:
        files = {
            "evidence.json": "{}", "paper_plan.json": "{}", "frozen.json": "{}",
            "abstract.txt": "unsupported claim", "paper.txt": "unsupported claim",
            "conclusion.txt": "unsupported claim", "writer.json": "{}",
        }
        for name, value in files.items():
            (self.project / name).write_text(value, encoding="utf-8")
        self._set_roots(evidence_registry="evidence.json", paper_plan="paper_plan.json")
        self._write_dag_roles([
            ("model_contract", "model.json", None), ("evidence_registry", "evidence.json", None),
            ("paper_plan", "paper_plan.json", None), ("frozen_results", "frozen.json", None),
            ("abstract", "abstract.txt", None), ("paper", "paper.txt", None),
            ("conclusion", "conclusion.txt", None), ("writer_package", "writer.json", None),
        ])
        result = self.gate("w2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("run_deterministic_qa", result.stdout)
        self.assertIn("validate_contracts", result.stdout)

    def test_v2_s1_recomputes_submission_pdf_chain_and_rejects_drift(self) -> None:
        paper = self.project / "paper.pdf"
        old = b"%PDF-1.4 old"
        paper.write_bytes(old)
        profile = json.loads((self.project / "competition_profile.json").read_text(encoding="utf-8"))
        manifest = json.loads((self.project / "run_manifest.json").read_text(encoding="utf-8"))
        manifest["preset"] = "submission"
        checkpoint = {
            "checkpoint_id": "CP-S1", "stage": "s1", "decision": "pass",
            "checked_at": "2026-08-17T00:00:00Z", "manual_checks": ["human_review"],
            "artifacts": [{"path": "paper.pdf", "sha256": sha256(paper)}],
        }
        manifest["human_checkpoints"] = [checkpoint]
        (self.project / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self._write_dag_roles([("final_pdf", "paper.pdf", {"pages": 1, "page_count_method": "manual_verified"})])
        paper_record = {"path": "paper.pdf", "sha256": sha256(paper), "bytes": len(old), "pages": 1, "page_count_method": "manual_verified", "limited_pages": 1, "ai_report_pages": 0}
        profile_hash = hashlib.sha256(json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        (self.project / "s1.json").write_text(json.dumps({"ok": False}), encoding="utf-8")
        submission = {
            "schema_version": "1.1", "project_id": "wp2-project", "run_id": "run-1", "status": "final_frozen",
            "frozen_at": "2026-08-17T00:00:00Z",
            "competition": {"profile_id": "wp2-fixture", "competition": "WP2 fixture", "season": "2026", "profile_sha256": profile_hash, "rule_snapshots": [{"path": "rules.txt", "sha256": sha256(self.project / "rules.txt")}]},
            "deadline": {"closes_at": "2026-09-01T00:00:00Z", "timezone": "Asia/Hong_Kong"},
            "paper": paper_record, "support_files": [], "ai_disclosure": None,
            "s1_report": {"path": "s1.json", "sha256": sha256(self.project / "s1.json")},
            "run_manifest": {"path": "run_manifest.json", "sha256": sha256(self.project / "run_manifest.json")},
            "package_sha256": hashlib.sha256(json.dumps({"paper": paper_record, "support_files": [], "ai_disclosure": None}, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
            "builder": {"name": "fixture", "version": "2.0"},
        }
        (self.project / "submission.json").write_text(json.dumps(submission), encoding="utf-8")
        manifest = json.loads((self.project / "run_manifest.json").read_text(encoding="utf-8"))
        manifest["roots"]["submission_manifest"] = {"path": "submission.json"}
        (self.project / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        paper.write_bytes(b"%PDF-1.4 drifted")
        result = self.gate("s1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("check_submission", result.stdout)
        self.assertIn("check_submission_manifest", result.stdout)
        self.assertIn("paper sha256 drift", result.stdout)

    def test_p2_closure_rejects_selected_full_freeze_run_mismatch(self) -> None:
        full = self.run_record(stage="full", receipt="full.json", selected=True, mode="research")
        self.assertEqual(full.returncode, 0)
        freeze = self.run_record(stage="freeze", receipt="freeze.json", mode="research")
        self.assertEqual(freeze.returncode, 0)
        (self.project / "frozen.json").write_text(json.dumps({"run_id": "other-run", "claimable": True}), encoding="utf-8")
        dag = {"schema_version": "2.0", "run_id": "run-1", "projection": "artifact_identity_dependency", "nodes": [{
            "artifact_id": "FROZEN-1", "role": "frozen_results", "path": "frozen.json", "producer_id": "freeze",
            "dependencies": [], "lifecycle": "frozen", "freshness": "current", "digest_owner": "artifact_dag",
            "version": "1", "created_at": "2026-08-17T00:00:00Z", "sha256": sha256(self.project / "frozen.json"), "digest_algorithm": "sha256",
        }]}
        (self.project / "artifact_dag.json").write_text(json.dumps(dag), encoding="utf-8")
        result = self.gate("p2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("frozen_results.run_id", result.stdout)

    def test_dag_stale_is_recomputed_from_bytes(self) -> None:
        path = self.project / "artifact.txt"
        path.write_text("v1", encoding="utf-8")
        dag = {"schema_version": "2.0", "run_id": "run-1", "projection": "artifact_identity_dependency", "nodes": [{
            "artifact_id": "A-1", "role": "table", "path": "artifact.txt", "producer_id": "writer", "dependencies": [],
            "lifecycle": "immutable", "freshness": "current", "digest_owner": "artifact_dag", "version": "1",
            "created_at": "2026-08-17T00:00:00Z", "sha256": sha256(path), "digest_algorithm": "sha256",
        }]}
        dag_path = self.project / "artifact_dag.json"
        dag_path.write_text(json.dumps(dag), encoding="utf-8")
        self.assertEqual(self.run_script("qa/check_artifact_dag.py", "--dag", "artifact_dag.json", "--project-root", str(self.project)).returncode, 0)
        path.write_text("v2", encoding="utf-8")
        stale = self.run_script("qa/check_artifact_dag.py", "--dag", "artifact_dag.json", "--project-root", str(self.project))
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("stale", stale.stdout)

    def test_canonical_profile_id_conflict_is_blocking(self) -> None:
        self._write_manifest(profile_id="wrong-profile")
        result = self.gate("p1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("profile_id", result.stdout)

    def test_s1_blocks_missing_critical_submission_rule_instead_of_guessing(self) -> None:
        profile_path = self.project / "competition_profile.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        del profile["submission"]["max_paper_bytes"]
        profile_path.write_text(json.dumps(profile), encoding="utf-8")
        manifest = json.loads((self.project / "run_manifest.json").read_text(encoding="utf-8"))
        manifest["preset"] = "submission"
        (self.project / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        result = self.gate("s1")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("max_paper_bytes is missing", result.stdout)
        self.assertIn("do not guess", result.stdout)

    def test_utf8_resource_report_is_machine_readable(self) -> None:
        baseline = {"run_id": "a", "results": [{"result_id": "A", "value": 2}]}
        superset = {"run_id": "b", "results": [{"result_id": "B", "value": 1}]}
        (self.project / "base.json").write_text(json.dumps(baseline), encoding="utf-8")
        (self.project / "super.json").write_text(json.dumps(superset), encoding="utf-8")
        (self.project / "spec.json").write_text(json.dumps({"pairs": [{"baseline": "base.json", "baseline_metric": "A", "superset": "super.json", "superset_metric": "B", "reason": "中文诊断"}]}), encoding="utf-8")
        result = self.run_script("qa/check_resource_monotonicity.py", "--spec", "spec.json", "--project-root", str(self.project))
        self.assertIsNotNone(result.stdout)
        json.loads(result.stdout)

    def test_submission_manifest_recomputes_final_pdf_hash(self) -> None:
        # Build the smallest complete F1 chain around the canonical v2
        # profile; the checker must report a changed PDF even if all stored
        # manifest/projection fields still claim success.
        paper = self.project / "paper.pdf"
        paper.write_bytes(b"%PDF-1.4 fixture")
        profile = json.loads((self.project / "competition_profile.json").read_text(encoding="utf-8"))
        checkpoint = {"checkpoint_id": "CP-S1", "stage": "s1", "decision": "pass", "checked_at": "2026-08-17T00:00:00Z", "artifacts": []}
        manifest = json.loads((self.project / "run_manifest.json").read_text(encoding="utf-8"))
        manifest["preset"] = "submission"
        manifest["human_checkpoints"] = [checkpoint]
        manifest["ai_usage_state"] = "none"
        manifest["ai_usage_declaration"] = {
            "status": "none", "confirmed_by": "team", "confirmed_at": "2026-08-17T00:00:00Z", "reason": "fixture declaration",
        }
        (self.project / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        ai_snapshot = {"state": "none", "records": [], "declaration": manifest["ai_usage_declaration"]}
        report = {
            "ok": True, "competition_profile_sha256": hashlib.sha256(json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
            "submission_rules_sha256": hashlib.sha256(json.dumps(profile["submission"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
            "ai_usage_sha256": hashlib.sha256(json.dumps(ai_snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
            "s1_checkpoint": {"checkpoint_id": "CP-S1", "sha256": hashlib.sha256(json.dumps(checkpoint, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()},
            "page_count": {"total_pages": 1, "page_count_method": "manual_verified", "limited_pages": 1, "ai_report_pages": 0},
        }
        report_path = self.project / "s1.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        paper_record = {"path": "paper.pdf", "sha256": sha256(paper), "bytes": paper.stat().st_size, "pages": 1, "page_count_method": "manual_verified", "limited_pages": 1, "ai_report_pages": 0}
        profile_hash = hashlib.sha256(json.dumps(profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        package_hash = hashlib.sha256(json.dumps({"paper": paper_record, "support_files": [], "ai_disclosure": None}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        submission = {
            "schema_version": "1.1", "project_id": "wp2-project", "run_id": "run-1", "status": "final_frozen", "frozen_at": "2026-08-17T00:00:00Z",
            "competition": {"profile_id": "wp2-fixture", "competition": "WP2 fixture", "season": "2026", "profile_sha256": profile_hash, "rule_snapshots": [{"path": "rules.txt", "sha256": sha256(self.project / "rules.txt")}]},
            "deadline": {"closes_at": "2026-09-01T00:00:00Z", "timezone": "Asia/Hong_Kong"}, "paper": paper_record, "support_files": [], "ai_disclosure": None,
            "s1_report": {"path": "s1.json", "sha256": sha256(report_path)}, "run_manifest": {"path": "run_manifest.json", "sha256": sha256(self.project / "run_manifest.json")},
            "package_sha256": package_hash, "builder": {"name": "fixture", "version": "2.0"},
        }
        sub_path = self.project / "submission_manifest.json"
        sub_path.write_text(json.dumps(submission), encoding="utf-8")
        good = self.run_script("qa/check_submission_manifest.py", "--submission-manifest", sub_path.name, "--project-root", str(self.project))
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        paper.write_bytes(b"%PDF-1.4 changed")
        drift = self.run_script("qa/check_submission_manifest.py", "--submission-manifest", sub_path.name, "--project-root", str(self.project))
        self.assertNotEqual(drift.returncode, 0)
        self.assertIn("paper sha256 drift", drift.stdout)

    def test_v2_freeze_requires_selected_receipt_and_binds_it(self) -> None:
        # Reuse the established solve-stage fixture for validation semantics;
        # only the execution/freeze boundary is under test here.
        from tests.test_p0_harness import P0HarnessTest

        harness = P0HarnessTest()
        legacy = self.project / "legacy-solve-fixture"
        legacy.mkdir()
        built = harness.build_fixture(legacy)
        for source in legacy.iterdir():
            if source.is_file() and source.name != "run_manifest.json":
                shutil.copy2(source, self.project / source.name)
        paths = {key: self.project / path.name for key, path in built.items()}
        run = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "run_and_record.py"), "--v2", "--integrity-mode", "research",
             "--run-id", "demo-run", "--stage", "full", "--receipt", "receipt-v2.json", "--index", "index-v2.json",
             "--selected", "--project-root", str(self.project), "--", sys.executable, "-c", "print('full')"],
            cwd=self.project, text=True, capture_output=True, encoding="utf-8", errors="replace", check=False,
        )
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        frozen = self.run_script(
            "freeze_results.py", "--project-root", str(self.project), "--source", paths["raw"].name,
            "--output", "frozen-v2.json", "--run-id", "demo-run", "--model-contract", paths["model"].name,
            "--receipt", "receipt-v2.json", "--run-index", "index-v2.json", "--code", paths["code"].name, "--validation", paths["validation"].name,
        )
        self.assertEqual(frozen.returncode, 0, frozen.stdout + frozen.stderr)
        value = json.loads((self.project / "frozen-v2.json").read_text(encoding="utf-8"))
        self.assertTrue(value["command"].startswith("receipt:"))
        self.assertEqual(value["command_receipt"]["path"], "receipt-v2.json")


if __name__ == "__main__":
    unittest.main()
