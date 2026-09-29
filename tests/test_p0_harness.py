from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_ref(path: Path) -> dict[str, str]:
    return {"path": path.name, "sha256": sha256(path)}


class P0HarnessTest(unittest.TestCase):
    def run_script(self, script: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / script), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

    def build_fixture(self, project: Path) -> dict[str, Path]:
        names = {
            "input": "input.json",
            "code": "model.py",
            "rule": "official_rules.html",
            "ai_record": "ai_interaction.md",
            "validation": "full_validation.json",
            "measurements": "validation_measurements.json",
            "raw": "raw_results.json",
            "frozen": "frozen_results.json",
            "evidence": "evidence_registry.json",
            "model": "model_contract.json",
            "plan": "paper_plan.json",
            "tex": "paper_source/main.tex",
            "template_contract": "paper_source/template_contract.json",
            "build_log": "build.log",
            "build_receipt": "build_receipt.json",
            "paper": "solution.pdf",
            "abstract": "abstract.txt",
            "conclusion": "conclusion.txt",
            "support": "support.zip",
            "ai_disclosure": "AI_use_report.pdf",
            "qa_report": "deterministic_qa.json",
            "critic_report": "semantic_critic.json",
            "blind_report": "blind_a.json",
            "submission_report": "submission_qa.json",
            "submission_manifest": "submission_manifest.json",
            "manifest": "run_manifest.json",
        }
        paths = {key: project / value for key, value in names.items()}
        paths["input"].write_text('{"demand": [10, 20, 30]}\n', encoding="utf-8")
        paths["code"].write_text("# deterministic fixture\n", encoding="utf-8")
        paths["rule"].write_text("official rule snapshot\n", encoding="utf-8")
        paths["ai_record"].write_text("prompt summary and checked response\n", encoding="utf-8")
        paths["paper"].write_bytes(b"%PDF-1.4\n% fixture solution\n")
        with zipfile.ZipFile(paths["support"], "w") as archive:
            archive.writestr("README.txt", "fixture support\n")
        paths["ai_disclosure"].write_bytes(b"%PDF-1.4\n% AI use report\n")

        write_json(
            paths["model"],
            {
                "schema_version": "1.3",
                "project_id": "demo",
                "run_id": "demo-run",
                "unit_system": "SI with CNY for cost",
                "questions": [
                    {"question_id": "q1", "task": "minimize cost", "conclusion_type": "numeric optimum", "inputs": ["demand"], "outputs": ["optimal_cost"]}
                ],
                "data_sources": [
                    {
                        "data_id": "demand",
                        "path": "input.json",
                        "read_only": True,
                        "sha256": sha256(paths["input"]),
                        "origin": "contest attachment",
                        "license_or_terms": "competition use",
                        "transformations": [],
                        "quality_checks": ["schema, missing values, range and unit checks"],
                    }
                ],
                "assumptions": [
                    {"assumption_id": "A1", "text": "demand is fixed during the run", "basis": "problem statement", "sensitivity_plan": "rerun with +/-10% demand"}
                ],
                "research_basis": {
                    "status": "verified",
                    "research_questions": [{
                        "research_id": "RES-Q1", "question_ids": ["q1"],
                        "purpose": "compare transparent optimization formulations for fixed demand",
                        "chinese_keywords": ["固定需求 成本优化"],
                        "english_keywords": ["fixed demand cost optimization"],
                    }],
                    "searches": [
                        {"search_id": "S-LLM", "research_ids": ["RES-Q1"], "query": "candidate formulations for fixed-demand cost optimization", "language": "en", "source": "llm_knowledge", "searched_at": "2026-08-08T00:00:00Z", "candidate_count": 2},
                        {"search_id": "S-WEB", "research_ids": ["RES-Q1"], "query": "fixed demand cost minimization linear optimization", "language": "en", "source": "openalex", "searched_at": "2026-08-08T00:01:00Z", "candidate_count": 4, "evidence_ids": ["E-CITE-PLAN"]},
                    ],
                    "candidate_models": [
                        {"candidate_id": "CM-LP", "question_id": "q1", "name": "enumerated linear cost model", "mechanism_fit": "directly represents the fixed demand and non-negativity constraints", "assumptions": ["cost is additive"], "data_requirements": ["demand and unit cost"], "strengths": ["transparent optimum"], "weaknesses": ["does not represent stochastic demand"], "evidence_ids": ["E-CITE-PLAN"], "rejection_conditions": ["nonlinear path dependence is material"], "decision": "selected", "model_id": "M1"},
                        {"candidate_id": "CM-SIM", "question_id": "q1", "name": "stochastic simulation", "mechanism_fit": "can represent uncertain demand", "assumptions": ["a demand distribution is identifiable"], "data_requirements": ["repeated demand observations"], "strengths": ["represents uncertainty"], "weaknesses": ["unsupported by the fixed fixture data"], "evidence_ids": ["E-CITE-PLAN"], "rejection_conditions": ["no repeated observations are available"], "decision": "rejected"},
                    ],
                    "decisions": [{"question_id": "q1", "selected_candidate_id": "CM-LP", "alternatives_considered": ["CM-SIM"], "selection_criteria": ["mechanism fit", "data sufficiency", "auditability"], "rationale": "CM-LP, the deterministic formulation, matches the supplied data while retaining exact feasibility and objective checks.", "decisive_evidence_ids": ["E-CITE-PLAN"], "unresolved_risks": ["demand misspecification"]}],
                    "unresolved_questions": []
                },
                "models": [
                    {
                        "model_id": "M1",
                        "question_id": "q1",
                        "name": "baseline optimization",
                        "problem_type": "optimization",
                        "characteristics": ["deterministic"],
                        "rationale": "matches the stated objective",
                        "variables": [
                            {"symbol": "x", "meaning": "selected production amount", "unit": "item", "domain": "x >= 0", "role": "decision"}
                        ],
                        "objective": "minimize total cost",
                        "constraints": [{"constraint_id": "C1", "expression": "x >= 0", "meaning": "non-negative production"}],
                        "algorithm": "enumeration",
                        "inputs": ["demand"],
                        "outputs": ["optimal_cost"],
                        "validation": [{"check_id": "V1", "stage": "both", "method": "check feasibility and objective", "acceptance": "all constraints pass"}],
                        "validation_obligations": [
                            {
                                "obligation_id": "VAL-FEASIBILITY", "category": "feasibility",
                                "method": "recompute all constraints",
                                "acceptance": {"left_metric_id": "max_violation", "operator": "<=", "right": {"kind": "literal", "value": 0}, "unit": "item"},
                                "required_stage": "both",
                            },
                            {
                                "obligation_id": "VAL-OBJECTIVE", "category": "objective_recomputation",
                                "method": "independent objective function",
                                "acceptance": {"left_metric_id": "solver_objective", "operator": "==", "right": {"kind": "metric", "metric_id": "independent_objective"}, "unit": "CNY", "tolerance": 0.000001},
                                "required_stage": "full",
                            },
                        ],
                        "risks": ["fixed-demand assumption"],
                        "fallback": "use the best feasible enumerated solution",
                        "plan_details": {
                            "selected_candidate_id": "CM-LP",
                            "mechanism": "Choose a non-negative production decision that covers fixed demand while minimizing additive cost.",
                            "equation_plan": [{"equation_id": "EQ-Q1-OBJ", "purpose": "define the optimization objective", "expression_or_derivation": "min C(x) subject to x >= demand", "variables": ["x", "demand"], "assumptions": ["additive cost"]}],
                            "parameter_plan": [{"parameter": "demand", "provenance": {"type": "GIVEN", "source_locator": "contest attachment input.json demand field"}, "unit": "item", "uncertainty_or_range": "+/-10% sensitivity"}],
                            "implementation_steps": ["load and validate demand", "enumerate feasible decisions", "recompute objective and constraints independently"],
                            "output_artifacts": ["raw_results.json", "validation_measurements.json"],
                            "validation_strategy": ["feasibility and independent objective recomputation"],
                            "failure_modes": ["fixed demand is misspecified"]
                        }
                    }
                ],
                "terminology": [{"canonical": "optimal cost", "forbidden_variants": ["optimium cost"]}],
                "status": "ready",
            },
        )
        write_json(
            paths["measurements"],
            {
                "schema_version": "1.0",
                "run_id": "demo-run",
                "observations": [
                    {
                        "obligation_id": "VAL-FEASIBILITY",
                        "metrics": [{"metric_id": "max_violation", "value": 0, "unit": "item", "locator": "checks/constraints.max_violation"}],
                    },
                    {
                        "obligation_id": "VAL-OBJECTIVE",
                        "metrics": [
                            {"metric_id": "solver_objective", "value": 123.45, "unit": "CNY", "locator": "solver.objective"},
                            {"metric_id": "independent_objective", "value": 123.45, "unit": "CNY", "locator": "recompute.objective"},
                        ],
                    },
                ],
            },
        )
        validation = self.run_script(
            "validation/evaluate_obligations.py",
            "--project-root", str(project),
            "--model-contract", paths["model"].name,
            "--measurements", paths["measurements"].name,
            "--output", paths["validation"].name,
        )
        self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)
        write_json(
            paths["raw"],
            {"results": [{
                "result_id": "R-Q1-01", "question_id": "q1", "name": "optimal_cost", "value": 123.45,
                "unit": "CNY", "precision": 2, "statistical_definition": "objective at selected optimum",
                "boundary": "fixed demand and declared constraints", "validation_status": "passed",
            }]},
        )
        freeze = self.run_script(
            "freeze_results.py",
            "--project-root", str(project),
            "--source", "raw_results.json",
            "--output", "frozen_results.json",
            "--run-id", "demo-run",
            "--model-contract", "model_contract.json",
            "--command", "python model.py --seed 7",
            "--seed", "7",
            "--input", "input.json",
            "--code", "model.py",
            "--validation", "full_validation.json",
        )
        self.assertEqual(freeze.returncode, 0, freeze.stdout + freeze.stderr)

        register = self.run_script(
            "register_evidence.py",
            "--project-root", str(project),
            "--frozen-results", "frozen_results.json",
            "--output", "evidence_registry.json",
        )
        self.assertEqual(register.returncode, 0, register.stdout + register.stderr)
        registry = read_json(paths["evidence"])
        registry["evidence"].append({
            "evidence_id": "E-CITE-PLAN", "type": "citation", "result_ids": [], "artifacts": [],
            "supports": "transparent optimization formulation and explicit assumptions",
            "boundary": "method choice only; it does not validate this run's numerical result",
            "verification_status": "verified",
            "citation": {
                "bib_key": "fixture2026", "title": "Fixture optimization method", "authors": ["A. Author"], "year": 2026,
                "canonical_url": "https://example.org/fulltext", "venue": "Fixture Journal", "source_tier": "publisher",
                "metadata_sources": ["https://example.org/metadata"], "access_level": "full_text",
                "locator": "Methods, section 2", "metadata_verified": True, "content_verified": True,
                "publication_status_checked": True, "verified_at": "2026-08-08T00:02:00Z"
            }
        })
        write_json(paths["evidence"], registry)
        write_json(
            paths["plan"],
            {
                "schema_version": "1.2",
                "run_id": "demo-run",
                "central_thesis": {"text": "The selected feasible plan minimizes cost under the frozen demand.", "claim_ids": ["C1"], "boundary": "Under the frozen demand and declared constraints."},
                "requirements": [{"requirement_id": "RQ1", "text": "answer question 1", "claim_ids": ["C1"]}],
                "claims": [{"claim_id": "C1", "claim_type": "observation", "text": "the selected plan has the minimum cost", "question_id": "q1", "evidence_ids": ["E-R-Q1-01"], "result_ids": ["R-Q1-01"], "section": "results.q1", "boundary": "under the frozen run", "support_level": "direct"}],
                "sections": [{"section_id": "results.q1", "purpose": "answer question 1", "claim_ids": ["C1"]}],
                "argument_units": [
                    {"unit_id": "AU-Q1-FORM", "section_id": "results.q1", "rhetorical_role": "mechanism_derivation", "claim_ids": ["C1"], "evidence_ids": ["E-CITE-PLAN"], "prerequisite_unit_ids": [], "expected_reader_judgment": "The formulation matches the fixed-demand mechanism.", "boundary": "Additive cost and fixed demand.", "target_words": 70},
                    {"unit_id": "AU-Q1-RESULT", "section_id": "results.q1", "rhetorical_role": "result_observation", "claim_ids": ["C1"], "evidence_ids": ["E-R-Q1-01"], "prerequisite_unit_ids": ["AU-Q1-FORM"], "expected_reader_judgment": "The reported value is directly supported by the frozen run.", "boundary": "Under the frozen run.", "target_words": 70},
                    {"unit_id": "AU-Q1-VALID", "section_id": "results.q1", "rhetorical_role": "validation", "claim_ids": ["C1"], "evidence_ids": ["E-R-Q1-01"], "prerequisite_unit_ids": ["AU-Q1-RESULT"], "expected_reader_judgment": "The optimum is feasible and independently recomputed.", "boundary": "Declared constraints only.", "target_words": 70},
                    {"unit_id": "AU-Q1-INTERP", "section_id": "results.q1", "rhetorical_role": "boundary", "claim_ids": ["C1"], "evidence_ids": ["E-R-Q1-01"], "prerequisite_unit_ids": ["AU-Q1-VALID"], "expected_reader_judgment": "The result is not extrapolated beyond fixed demand.", "boundary": "No stochastic-demand claim.", "target_words": 70}
                ],
                "depth_budget": [{"question_id": "q1", "target_words": 180, "rationale": "This fixture has one validated optimization result."}],
                "precision_policy": {"audit_source": "frozen_display_value", "prose_source": "frozen_display_value", "table_source": "frozen_display_value", "abstract_max_numeric_claims": 2},
                "abstract_results": [{"result_id": "R-Q1-01", "priority": "primary", "selection_reason": "This is the decision-defining validated result for the only requirement.", "claim_ids": ["C1"], "word_budget": 24}],
                "terminology": [{"canonical": "optimal cost", "forbidden_variants": ["optimium cost"]}],
                "figures": [], "tables": [],
                "readiness": {"stage": "technical_draft", "question_coverage": [{"question_id": "q1", "formulation_unit_ids": ["AU-Q1-FORM"], "result_unit_ids": ["AU-Q1-RESULT"], "validation_unit_ids": ["AU-Q1-VALID"], "interpretation_unit_ids": ["AU-Q1-INTERP"], "display_ids": [], "display_waiver": "The fixture has one scalar result; prose and equation are clearer than a display."}]},
                "status": "ready",
            },
        )
        paths["tex"].parent.mkdir(parents=True, exist_ok=True)
        paths["tex"].write_text("\\documentclass{article}\n\\begin{document}fixture\\end{document}\n", encoding="utf-8")
        write_json(paths["template_contract"], {
            "schema_version": "1.0", "template_id": "fixture-template", "competition_profile_id": "demo-2026",
            "source_kind": "local", "source_locator": "tests/test_p0_harness.py", "status": "verified",
            "document_class": "article", "entrypoint": "main.tex", "required_files": ["main.tex"],
            "required_commands": ["\\begin{document}"], "forbidden_document_classes": [], "allowed_engines": ["xelatex"]
        })
        paths["build_log"].write_text("fixture build log\n", encoding="utf-8")
        write_json(paths["build_receipt"], {
            "schema_version": "1.1", "generated_at": "2026-08-08T00:00:00Z", "integrity_mode": "submission",
            "engine": "xelatex", "source_root": "paper_source", "entrypoint": "main.tex",
            "template": {"contract": "paper_source/template_contract.json", "template_id": "fixture-template", "document_class": "article", "verified": True, "sha256": sha256(paths["template_contract"])},
            "source_tree_sha256_before": "0" * 64, "source_tree_sha256_after": "0" * 64,
            "command": ["latexmk", "-xelatex", "main.tex"], "shell_escape": False,
            "output": {"path": paths["paper"].name, "sha256": sha256(paths["paper"])},
            "log": {"path": paths["build_log"].name, "sha256": sha256(paths["build_log"])},
            "exit_code": 0, "source_unchanged": True, "ok": True
        })
        paths["abstract"].write_text("The optimal cost is 123.45 CNY.\n", encoding="utf-8")
        paths["conclusion"].write_text("The optimal cost is 123.45 CNY.\n", encoding="utf-8")
        qa_inputs = [
            {"role": role, "path": path.name, "sha256": sha256(path)}
            for role, path in (
                ("model_contract", paths["model"]), ("frozen_results", paths["frozen"]),
                ("evidence_registry", paths["evidence"]), ("paper_plan", paths["plan"]),
                ("abstract", paths["abstract"]), ("paper", paths["paper"]), ("conclusion", paths["conclusion"]),
            )
        ]
        write_json(paths["qa_report"], {"ok": True, "inputs": qa_inputs, "checks": [
            {"label": "contracts", "ok": True}, {"label": "contest_safety", "ok": True},
            {"label": "consistency", "ok": True}, {"label": "citations", "ok": True, "status": "not_applicable"},
        ]})
        write_json(paths["critic_report"], {"verdict": "pass", "issues": []})
        write_json(paths["blind_report"], {"reviewer_id": "blind-a", "verdict": "pass", "issues": []})

        policy = {
            "interactive_human_help": "allow", "current_problem_discussion": "allow",
            "public_posting": "allow", "external_write": "allow",
            "static_reference_search": "allow", "ai_tool_use": "allow",
        }
        checkpoints = [
            {"checkpoint_id": "HC-M1", "stage": "m1", "scope": "research, model choice and obligations", "artifacts": [file_ref(paths["model"]), file_ref(paths["evidence"])], "manual_checks": ["problem_mechanism_fit", "candidate_comparison_fairness", "data_sufficiency", "mathematical_consistency", "literature_support_fit", "validation_can_falsify"], "reviewed_by_role": "team", "decision": "pass", "checked_at": "2026-08-08T00:00:00Z"},
            {"checkpoint_id": "HC-P2", "stage": "p2", "scope": "code validation and results", "artifacts": [file_ref(paths["frozen"])], "manual_checks": ["result plausibility"], "reviewed_by_role": "team", "decision": "pass", "checked_at": "2026-08-08T00:00:00Z"},
            {"checkpoint_id": "HC-W2", "stage": "w2", "scope": "claims citations figures and AI", "artifacts": [file_ref(paths["paper"])], "manual_checks": ["claim boundary"], "reviewed_by_role": "team", "decision": "pass", "checked_at": "2026-08-08T00:00:00Z"},
            {"checkpoint_id": "HC-S1", "stage": "s1", "scope": "final package", "artifacts": [file_ref(paths["paper"]), file_ref(paths["support"]), file_ref(paths["ai_disclosure"])], "manual_checks": ["anonymity", "final_render", "support_contents", "page_count"], "reviewed_by_role": "team", "decision": "pass", "checked_at": "2026-08-08T00:00:00Z"},
        ]
        gate_evidence = {
            "m1": ["model_contract.json"], "p1": ["command:smoke"], "p2": ["frozen_results.json"],
            "w1": ["evidence_registry.json", "paper_plan.json"],
            "w2": ["solution.pdf", "deterministic_qa.json", "semantic_critic.json"], "s1": [],
        }
        manifest = {
            "schema_version": "1.2", "project_id": "demo", "run_id": "demo-run", "enhanced_integrity_profile": False,
            "integrity_mode": "submission",
            "status": "content_ready", "phase": "review",
            "competition_profile": {
                "profile_id": "demo-2026", "competition": "other", "season": "2026", "mode": "pre_contest",
                "retrieved_at": "2026-08-08T00:00:00Z",
                "official_rules": [{"rule_id": "RULE-1", "title": "Demo rules", "url": "https://example.org/rules", "retrieved_at": "2026-08-08T00:00:00Z", "snapshot": file_ref(paths["rule"])}],
                "official_submission_endpoints": ["https://submit.example.org/"],
                "submission": {
                    "paper_extensions": [".pdf"], "max_paper_bytes": 1000000, "max_pages": 25,
                    "page_count_scope": "entire PDF", "support_policy": "required", "max_support_bytes": 1000000,
                    "ai_disclosure_policy": "required_when_used",
                    "required_manual_checks": ["anonymity", "final_render", "support_contents", "page_count"],
                },
            },
            "safety": {"official_rule": policy, "local_conservative_policy": policy, "events": []},
            "ai_usage": [{
                "usage_id": "AI-1", "tool_name": "Codex", "model": "fixture-model", "provider": "OpenAI",
                "used_at": "2026-08-08T00:00:00Z", "stage": "coding", "purpose": "fixture assistance",
                "prompt_summary": "review fixture", "output_use": "suggestion adopted", "human_changes": "manually checked",
                "interaction_record": file_ref(paths["ai_record"]),
                "verification": {"status": "verified", "checked_by_role": "team", "method": "manual rerun", "checked_at": "2026-08-08T00:00:00Z"},
            }],
            "human_checkpoints": checkpoints,
            "model_contract": file_ref(paths["model"]),
            "commands": [
                {"command_id": "smoke", "stage": "smoke", "command": "python model.py --smoke", "exit_code": 0},
                {"command_id": "full", "stage": "full", "command": "python model.py --full", "exit_code": 0},
                {"command_id": "freeze", "stage": "freeze", "command": "freeze_results.py", "exit_code": 0},
            ],
            "artifacts": [
                {**file_ref(paths["frozen"]), "role": "frozen_results"},
                {**file_ref(paths["evidence"]), "role": "evidence_registry"},
                {**file_ref(paths["plan"]), "role": "paper_plan"},
                {"path": "paper_source/template_contract.json", "sha256": sha256(paths["template_contract"]), "role": "template_contract"},
                {**file_ref(paths["build_receipt"]), "role": "build_receipt"},
                {**file_ref(paths["paper"]), "role": "paper"},
            ],
            "gates": {name: {"status": ("pending" if name == "s1" else "pass"), "checked_at": "2026-08-08T00:00:00Z", "evidence": gate_evidence[name]} for name in ("m1", "p1", "p2", "w1", "w2", "s1")},
            "revision": {"loop": 0, "cap": 2, "open_issue_ids": []},
            "reviewer": {
                "profile": "final_submission",
                "deterministic_qa": {"status": "pass", "report": paths["qa_report"].name, "report_sha256": sha256(paths["qa_report"])},
                "semantic_critic": {"status": "pass", "report": paths["critic_report"].name, "report_sha256": sha256(paths["critic_report"])},
                "blind_reviewers": [{"status": "pass", "reviewer_id": "blind-a", "report": paths["blind_report"].name, "report_sha256": sha256(paths["blind_report"])}],
            },
        }
        write_json(paths["manifest"], manifest)
        submission = self.run_script(
            "qa/check_submission.py", "--project-root", str(project), "--run-manifest", paths["manifest"].name,
            "--paper", paths["paper"].name, "--paper-pages", "12", "--page-count-method", "manual_verified",
            "--support", paths["support"].name, "--ai-disclosure", paths["ai_disclosure"].name,
            "--output", paths["submission_report"].name,
        )
        self.assertEqual(submission.returncode, 0, submission.stdout + submission.stderr)
        manifest = read_json(paths["manifest"])
        manifest["status"] = "submission_ready"
        manifest["phase"] = "submission"
        manifest["gates"]["s1"] = {"status": "pass", "checked_at": "2026-08-08T00:00:00Z", "evidence": [paths["submission_report"].name]}
        manifest["artifacts"].append({**file_ref(paths["submission_report"]), "role": "submission_qa"})
        write_json(paths["manifest"], manifest)
        return paths

    def validate_fixture(self, project: Path) -> subprocess.CompletedProcess[str]:
        return self.run_script(
            "qa/validate_contracts.py", "--project-root", str(project),
            "--model-contract", "model_contract.json", "--run-manifest", "run_manifest.json",
            "--frozen-results", "frozen_results.json", "--evidence-registry", "evidence_registry.json",
            "--paper-plan", "paper_plan.json", "--strict",
        )

    def make_peak_failure(self, project: Path, paths: dict[str, Path], output_name: str) -> Path:
        """Create the Q3 counterexample: proposed 550 MW versus baseline 498 MW."""

        model = read_json(paths["model"])
        acceptance = model["models"][0]["validation_obligations"][0]["acceptance"]
        acceptance.update({
            "left_metric_id": "proposed_peak_mw",
            "operator": "<=",
            "right": {"kind": "metric", "metric_id": "baseline_peak_mw"},
            "unit": "MW",
        })
        write_json(paths["model"], model)
        measurements = read_json(paths["measurements"])
        measurements["observations"][0]["metrics"] = [
            {"metric_id": "proposed_peak_mw", "value": 550, "unit": "MW", "locator": "q3.proposed_peak"},
            {"metric_id": "baseline_peak_mw", "value": 498, "unit": "MW", "locator": "q3.baseline_peak"},
        ]
        write_json(paths["measurements"], measurements)
        report_path = project / output_name
        evaluate = self.run_script(
            "validation/evaluate_obligations.py",
            "--project-root", str(project),
            "--model-contract", paths["model"].name,
            "--measurements", paths["measurements"].name,
            "--output", report_path.name,
        )
        self.assertEqual(evaluate.returncode, 0, evaluate.stdout + evaluate.stderr)
        report = read_json(report_path)
        self.assertEqual(report["verdict"], "FAIL")
        self.assertEqual(report["obligations"][0]["status"], "FAIL")
        self.assertIn("550 MW <= 498 MW", report["obligations"][0]["message"])
        return report_path

    def test_happy_path_contracts_safety_and_gates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-p0-") as temp:
            project = Path(temp)
            self.build_fixture(project)
            validate = self.validate_fixture(project)
            self.assertEqual(validate.returncode, 0, validate.stdout + validate.stderr)
            safety = self.run_script("qa/check_contest_safety.py", "--project-root", str(project), "--manifest", "run_manifest.json", "--strict")
            self.assertEqual(safety.returncode, 0, safety.stdout + safety.stderr)
            gates = self.run_script("qa/check_gates.py", "--project-root", str(project), "--manifest", "run_manifest.json", "--strict")
            self.assertEqual(gates.returncode, 0, gates.stdout + gates.stderr)

    def test_freeze_rejects_placeholder_validation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-validation-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            paths["frozen"].unlink()
            write_json(paths["validation"], {"ok": True})
            result = self.run_script(
                "freeze_results.py", "--project-root", str(project), "--source", paths["raw"].name,
                "--output", paths["frozen"].name, "--run-id", "demo-run", "--model-contract", paths["model"].name,
                "--command", "python model.py", "--code", paths["code"].name, "--validation", paths["validation"].name,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("measurement_snapshot.path", result.stderr)

    def test_failed_run_is_frozen_but_cannot_enter_evidence_registry(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-failed-run-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            failed_report = self.make_peak_failure(project, paths, "peak_failure.json")
            raw = read_json(paths["raw"])
            raw["results"][0]["validation_status"] = "failed"
            write_json(paths["raw"], raw)
            failed_frozen = project / "failed_frozen.json"
            freeze = self.run_script(
                "freeze_results.py", "--project-root", str(project), "--source", paths["raw"].name,
                "--output", failed_frozen.name, "--run-id", "demo-run", "--model-contract", paths["model"].name,
                "--command", "python model.py", "--code", paths["code"].name, "--validation", failed_report.name,
            )
            self.assertEqual(freeze.returncode, 0, freeze.stdout + freeze.stderr)
            frozen = read_json(failed_frozen)
            self.assertEqual(frozen["validation_verdict"], "FAIL")
            self.assertFalse(frozen["claimable"])
            self.assertEqual(frozen["results"][0]["validation_status"], "failed")
            self.assertFalse(frozen["results"][0]["claimable"])
            register = self.run_script(
                "register_evidence.py", "--project-root", str(project),
                "--frozen-results", failed_frozen.name, "--output", "failed_evidence.json",
            )
            self.assertNotEqual(register.returncode, 0)
            self.assertIn("not claimable", register.stderr)

    def test_freeze_rejects_hand_edited_fail_as_pass(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-tampered-verdict-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            failed_report = self.make_peak_failure(project, paths, "tampered_validation.json")
            report = read_json(failed_report)
            report["ok"] = True
            report["verdict"] = "PASS"
            report["obligations"][0]["status"] = "PASS"
            write_json(failed_report, report)
            result = self.run_script(
                "freeze_results.py", "--project-root", str(project), "--source", paths["raw"].name,
                "--output", "tampered_frozen.json", "--run-id", "demo-run", "--model-contract", paths["model"].name,
                "--command", "python model.py", "--code", paths["code"].name, "--validation", failed_report.name,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not match independent recomputation", result.stderr)

    def test_p2_rejects_a_non_claimable_frozen_artifact(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-p2-claimable-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            frozen = read_json(paths["frozen"])
            frozen["claimable"] = False
            write_json(paths["frozen"], frozen)
            manifest = read_json(paths["manifest"])
            for artifact in manifest["artifacts"]:
                if artifact.get("role") == "frozen_results":
                    artifact.update(file_ref(paths["frozen"]))
            write_json(paths["manifest"], manifest)
            gates = self.run_script(
                "qa/check_gates.py", "--project-root", str(project), "--manifest", paths["manifest"].name, "--strict",
            )
            self.assertNotEqual(gates.returncode, 0)
            self.assertIn("claimable=true", gates.stdout)

    def test_writer_package_blocks_new_number_and_causal_explanation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-writer-package-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            package = project / "writer_package.json"
            compile_result = self.run_script(
                "claims/compile_writer_package.py", "--project-root", str(project),
                "--paper-plan", paths["plan"].name, "--frozen-results", paths["frozen"].name,
                "--evidence-registry", paths["evidence"].name, "--output", package.name,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stdout + compile_result.stderr)
            draft = project / "draft.txt"
            draft.write_text("The cost is 123.45 CNY and therefore causes a 20% improvement.\n", encoding="utf-8")
            checked = self.run_script(
                "qa/check_writer_package.py", "--project-root", str(project),
                "--writer-package", package.name, "--draft", draft.name, "--strict",
            )
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn("numeric token", checked.stdout)
            self.assertIn("causal/explanatory", checked.stdout)

    def test_modeling_plan_requires_external_research_and_candidate_comparison(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-model-plan-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            model = read_json(paths["model"])
            model["research_basis"]["searches"] = [model["research_basis"]["searches"][0]]
            model["research_basis"]["candidate_models"] = [
                model["research_basis"]["candidate_models"][0]
            ]
            model["research_basis"]["decisions"][0]["alternatives_considered"] = []
            model["models"][0]["characteristics"] = ["scenario_based", "multi_stage"]
            write_json(paths["model"], model)
            result = self.run_script(
                "qa/check_modeling_plan.py", "--project-root", str(project),
                "--model-contract", paths["model"].name,
                "--evidence-registry", paths["evidence"].name,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("external literature/web search", result.stdout)
            self.assertIn("at least two candidate models", result.stdout)
            self.assertIn("nonanticipativity", result.stdout)
            self.assertIn("scenario_generalization", result.stdout)

    def test_paper_readiness_rejects_result_only_first_draft_plan(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-paper-readiness-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            plan = read_json(paths["plan"])
            plan["argument_units"][0]["rhetorical_role"] = "result_observation"
            write_json(paths["plan"], plan)
            result = self.run_script(
                "qa/check_paper_readiness.py", "--project-root", str(project),
                "--paper-plan", paths["plan"].name,
                "--evidence-registry", paths["evidence"].name,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("invalid for formulation_unit_ids", result.stdout)

    def test_paper_plan_keeps_legacy_depth_budget_out_of_gate_logic_and_requires_observation_result(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-paper-plan-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            plan = read_json(paths["plan"])
            plan["depth_budget"][0]["question_id"] = "q2"
            del plan["claims"][0]["result_ids"]
            write_json(paths["plan"], plan)
            validate = self.validate_fixture(project)
            self.assertNotEqual(validate.returncode, 0)
            self.assertNotIn("depth_budget", validate.stdout)
            self.assertIn("observation claim", validate.stdout)

    def test_verified_citation_requires_full_content_and_status_checks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-literature-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            registry = read_json(paths["evidence"])
            registry["evidence"].append({
                "evidence_id": "E-CITE-1", "type": "citation", "result_ids": [], "artifacts": [],
                "supports": "a method choice", "boundary": "abstract only", "verification_status": "verified",
                "citation": {
                    "bib_key": "demo2026", "title": "Demo", "authors": ["A. Author"], "year": 2026,
                    "canonical_url": "https://example.org/paper", "source_tier": "trusted_index",
                    "metadata_sources": ["https://api.crossref.org/works/demo"], "access_level": "metadata_only",
                    "locator": "metadata record", "metadata_verified": True, "content_verified": False,
                    "publication_status_checked": False, "verified_at": "2026-08-08T00:00:00Z",
                },
            })
            write_json(paths["evidence"], registry)
            manifest = read_json(paths["manifest"])
            next(row for row in manifest["artifacts"] if row["role"] == "evidence_registry")["sha256"] = sha256(paths["evidence"])
            write_json(paths["manifest"], manifest)
            validate = self.validate_fixture(project)
            self.assertNotEqual(validate.returncode, 0)
            self.assertIn("content_verified", validate.stdout)

    def test_live_contest_blocks_public_write(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-safety-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            manifest = read_json(paths["manifest"])
            manifest["competition_profile"]["mode"] = "live_contest"
            for policy_name in ("official_rule", "local_conservative_policy"):
                for action in ("interactive_human_help", "current_problem_discussion", "public_posting", "external_write"):
                    manifest["safety"][policy_name][action] = "deny"
            manifest["safety"]["events"] = [{
                "event_id": "EV-1", "action": "public_posting", "direction": "write", "channel": "github",
                "target": "https://github.com/example/repo", "decision": "executed",
                "recorded_at": "2026-08-08T00:00:00Z", "reason": "test",
            }]
            write_json(paths["manifest"], manifest)
            safety = self.run_script("qa/check_contest_safety.py", "--project-root", str(project), "--manifest", paths["manifest"].name, "--strict")
            self.assertNotEqual(safety.returncode, 0)
            self.assertIn("not permitted", safety.stdout)

    def test_submission_freeze_is_immutable_and_hashes_package(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-submission-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            freeze = self.run_script(
                "freeze_submission.py", "--project-root", str(project), "--run-manifest", paths["manifest"].name,
                "--s1-report", paths["submission_report"].name, "--paper", paths["paper"].name,
                "--support", paths["support"].name, "--ai-disclosure", paths["ai_disclosure"].name,
                "--deadline", "2026-09-01T20:00:00+08:00", "--timezone", "Asia/Hong_Kong",
                "--output", paths["submission_manifest"].name,
            )
            self.assertEqual(freeze.returncode, 0, freeze.stdout + freeze.stderr)
            submission = read_json(paths["submission_manifest"])
            self.assertEqual(submission["status"], "final_frozen")
            self.assertEqual(submission["schema_version"], "1.1")
            self.assertEqual(submission["paper"]["limited_pages"], 12)
            self.assertEqual(submission["paper"]["ai_report_pages"], 0)
            final_check = self.run_script(
                "qa/check_submission_manifest.py", "--project-root", str(project),
                "--submission-manifest", paths["submission_manifest"].name,
            )
            self.assertEqual(final_check.returncode, 0, final_check.stdout + final_check.stderr)
            overwrite = self.run_script(
                "freeze_submission.py", "--project-root", str(project), "--run-manifest", paths["manifest"].name,
                "--s1-report", paths["submission_report"].name, "--paper", paths["paper"].name,
                "--support", paths["support"].name, "--ai-disclosure", paths["ai_disclosure"].name,
                "--deadline", "2026-09-01T20:00:00+08:00", "--timezone", "Asia/Hong_Kong",
                "--output", paths["submission_manifest"].name,
            )
            self.assertNotEqual(overwrite.returncode, 0)

    def test_legacy_submission_accepts_historical_ai_list_hash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-legacy-ai-hash-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            manifest = read_json(paths["manifest"])
            report = read_json(paths["submission_report"])
            payload = json.dumps(
                manifest["ai_usage"], ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
            report["ai_usage_sha256"] = hashlib.sha256(payload).hexdigest()
            write_json(paths["submission_report"], report)
            submission_artifact = next(row for row in manifest["artifacts"] if row["role"] == "submission_qa")
            submission_artifact["sha256"] = sha256(paths["submission_report"])
            write_json(paths["manifest"], manifest)

            freeze = self.run_script(
                "freeze_submission.py", "--project-root", str(project),
                "--run-manifest", paths["manifest"].name,
                "--s1-report", paths["submission_report"].name,
                "--paper", paths["paper"].name, "--support", paths["support"].name,
                "--ai-disclosure", paths["ai_disclosure"].name,
                "--deadline", "2026-09-01T20:00:00+08:00", "--timezone", "Asia/Hong_Kong",
                "--output", paths["submission_manifest"].name,
            )
            self.assertEqual(freeze.returncode, 0, freeze.stdout + freeze.stderr)
            checked = self.run_script(
                "qa/check_submission_manifest.py", "--project-root", str(project),
                "--submission-manifest", paths["submission_manifest"].name,
            )
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

    def test_deterministic_qa_includes_contest_safety(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-qa-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            paths["qa_report"].unlink()
            qa = self.run_script(
                "qa/run_deterministic_qa.py", "--project-root", str(project),
                "--model-contract", paths["model"].name, "--run-manifest", paths["manifest"].name,
                "--frozen-results", paths["frozen"].name, "--evidence-registry", paths["evidence"].name,
                "--paper-plan", paths["plan"].name, "--abstract", paths["abstract"].name,
                "--paper", paths["paper"].name, "--conclusion", paths["conclusion"].name,
                "--output", paths["qa_report"].name,
            )
            self.assertEqual(qa.returncode, 0, qa.stdout + qa.stderr)
            labels = {row["label"] for row in read_json(paths["qa_report"])["checks"]}
            self.assertEqual(labels, {"contracts", "scope_consistency", "formula_replay", "math_semantics", "units", "contest_safety", "consistency", "citations"})

    def test_s1_rejects_missing_manual_check(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-s1-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            manifest = read_json(paths["manifest"])
            checkpoint = next(row for row in manifest["human_checkpoints"] if row["stage"] == "s1")
            checkpoint["manual_checks"].remove("anonymity")
            write_json(paths["manifest"], manifest)
            report = self.run_script(
                "qa/check_submission.py", "--project-root", str(project), "--run-manifest", paths["manifest"].name,
                "--paper", paths["paper"].name, "--paper-pages", "12", "--page-count-method", "manual_verified",
                "--support", paths["support"].name, "--ai-disclosure", paths["ai_disclosure"].name,
                "--output", "submission_qa_2.json",
            )
            self.assertNotEqual(report.returncode, 0)
            self.assertIn("missing manual", read_json(project / "submission_qa_2.json")["errors"][0].lower())

    def test_strict_abstract_gate_rejects_unregistered_number(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-abstract-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            paths["abstract"].write_text("The optimal cost is 123.45 CNY with score 999.\n", encoding="utf-8")
            consistency = self.run_script(
                "qa/check_consistency.py", "--project-root", str(project), "--paper-plan", paths["plan"].name,
                "--frozen-results", paths["frozen"].name, "--evidence-registry", paths["evidence"].name,
                "--abstract", paths["abstract"].name, "--strict",
            )
            self.assertNotEqual(consistency.returncode, 0)
            self.assertIn("not registered", consistency.stdout)

    def test_citation_checker_ignores_comments(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-cite-") as temp:
            project = Path(temp)
            (project / "main.tex").write_text("% \\cite{missing}\nA citation \\citep{demo2026}.\n", encoding="utf-8")
            (project / "references.bib").write_text("@article{demo2026, title={Demo}, year={2026}}\n", encoding="utf-8")
            result = self.run_script("qa/check_citations.py", "--project-root", str(project), "--tex", "main.tex", "--bib", "references.bib")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_ai_disclosure_in_paper_section_skips_separate_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-ai-fmt-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            manifest = read_json(paths["manifest"])
            manifest["competition_profile"]["submission"]["ai_disclosure_format"] = "in_paper_section"
            manifest["competition_profile"]["submission"]["required_manual_checks"].append("ai_report_in_paper")
            checkpoint = next(row for row in manifest["human_checkpoints"] if row["stage"] == "s1")
            checkpoint["manual_checks"].append("ai_report_in_paper")
            write_json(paths["manifest"], manifest)
            report = self.run_script(
                "qa/check_submission.py", "--project-root", str(project), "--run-manifest", paths["manifest"].name,
                "--paper", paths["paper"].name, "--paper-pages", "12", "--page-count-method", "manual_verified",
                "--support", paths["support"].name,
                "--output", "submission_qa_fmt.json",
            )
            self.assertEqual(report.returncode, 0, report.stdout + report.stderr)

    def test_ai_disclosure_in_paper_section_requires_manual_check(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-ai-fmt-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            manifest = read_json(paths["manifest"])
            manifest["competition_profile"]["submission"]["ai_disclosure_format"] = "in_paper_section"
            write_json(paths["manifest"], manifest)
            report = self.run_script(
                "qa/check_submission.py", "--project-root", str(project), "--run-manifest", paths["manifest"].name,
                "--paper", paths["paper"].name, "--paper-pages", "12", "--page-count-method", "manual_verified",
                "--support", paths["support"].name,
                "--output", "submission_qa_fmt.json",
            )
            self.assertNotEqual(report.returncode, 0)
            self.assertIn("ai_report_in_paper", read_json(project / "submission_qa_fmt.json")["errors"][0])

    def test_ai_disclosure_both_requires_file_and_manual_check(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-ai-fmt-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            manifest = read_json(paths["manifest"])
            manifest["competition_profile"]["submission"]["ai_disclosure_format"] = "both"
            manifest["competition_profile"]["submission"]["required_manual_checks"].append("ai_report_in_paper")
            write_json(paths["manifest"], manifest)
            report = self.run_script(
                "qa/check_submission.py", "--project-root", str(project), "--run-manifest", paths["manifest"].name,
                "--paper", paths["paper"].name, "--paper-pages", "12", "--page-count-method", "manual_verified",
                "--support", paths["support"].name, "--ai-disclosure", paths["ai_disclosure"].name,
                "--output", "submission_qa_fmt.json",
            )
            self.assertNotEqual(report.returncode, 0)
            self.assertIn("ai_report_in_paper", read_json(project / "submission_qa_fmt.json")["errors"][0])

    def test_max_pages_excludes_ai_report_accepts_excess(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-pages-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            manifest = read_json(paths["manifest"])
            manifest["competition_profile"]["submission"]["max_pages_excludes_ai_report"] = True
            manifest["competition_profile"]["submission"]["max_pages"] = 20
            manifest["competition_profile"]["submission"]["ai_disclosure_format"] = "both"
            manifest["competition_profile"]["submission"]["required_manual_checks"].append("ai_report_position")
            checkpoint = next(row for row in manifest["human_checkpoints"] if row["stage"] == "s1")
            checkpoint["manual_checks"].append("ai_report_position")
            checkpoint["manual_checks"].append("ai_report_in_paper")
            write_json(paths["manifest"], manifest)
            report = self.run_script(
                "qa/check_submission.py", "--project-root", str(project), "--run-manifest", paths["manifest"].name,
                "--paper", paths["paper"].name, "--paper-pages", "22", "--page-count-method", "manual_verified",
                "--ai-report-pages", "3",
                "--support", paths["support"].name, "--ai-disclosure", paths["ai_disclosure"].name,
                "--output", "submission_qa_pages.json",
            )
            self.assertEqual(report.returncode, 0, report.stdout + report.stderr)
            page_count = read_json(project / "submission_qa_pages.json")["page_count"]
            self.assertEqual(page_count["total_pages"], 22)
            self.assertEqual(page_count["ai_report_pages"], 3)
            self.assertEqual(page_count["limited_pages"], 19)

    def test_paper_body_limit_uses_verified_body_pages(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-body-pages-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            manifest = read_json(paths["manifest"])
            rules = manifest["competition_profile"]["submission"]
            rules["page_count_scope"] = "paper_body"
            rules["max_pages"] = 30
            write_json(paths["manifest"], manifest)
            common = (
                "qa/check_submission.py", "--project-root", str(project),
                "--run-manifest", paths["manifest"].name, "--paper", paths["paper"].name,
                "--paper-pages", "42", "--page-count-method", "manual_verified",
                "--support", paths["support"].name,
                "--ai-disclosure", paths["ai_disclosure"].name,
            )
            missing = self.run_script(*common, "--output", "submission_missing_body.json")
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("--body-pages", read_json(project / "submission_missing_body.json")["errors"][0])
            accepted = self.run_script(
                *common, "--body-pages", "29", "--output", "submission_body.json",
            )
            self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)
            page_count = read_json(project / "submission_body.json")["page_count"]
            self.assertEqual(page_count["total_pages"], 42)
            self.assertEqual(page_count["body_pages"], 29)
            self.assertEqual(page_count["limited_pages"], 29)
            manifest = read_json(paths["manifest"])
            report_path = project / "submission_body.json"
            submission_artifact = next(row for row in manifest["artifacts"] if row["role"] == "submission_qa")
            submission_artifact.update(file_ref(report_path))
            manifest["gates"]["s1"]["evidence"] = [report_path.name]
            write_json(paths["manifest"], manifest)
            frozen = self.run_script(
                "freeze_submission.py", "--project-root", str(project),
                "--run-manifest", paths["manifest"].name, "--s1-report", report_path.name,
                "--paper", paths["paper"].name, "--support", paths["support"].name,
                "--ai-disclosure", paths["ai_disclosure"].name,
                "--deadline", "2026-09-01T20:00:00+08:00", "--timezone", "Asia/Hong_Kong",
                "--output", "submission_body_manifest.json",
            )
            self.assertEqual(frozen.returncode, 0, frozen.stdout + frozen.stderr)
            frozen_paper = read_json(project / "submission_body_manifest.json")["paper"]
            self.assertEqual(read_json(project / "submission_body_manifest.json")["schema_version"], "1.2")
            self.assertEqual(frozen_paper["body_pages"], 29)
            self.assertEqual(frozen_paper["limited_pages"], 29)
            checked = self.run_script(
                "qa/check_submission_manifest.py", "--project-root", str(project),
                "--submission-manifest", "submission_body_manifest.json",
            )
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            tampered = read_json(project / "submission_body_manifest.json")
            tampered["paper"].pop("body_pages")
            write_json(project / "submission_body_manifest.json", tampered)
            rejected = self.run_script(
                "qa/check_submission_manifest.py", "--project-root", str(project),
                "--submission-manifest", "submission_body_manifest.json",
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("requires body_pages", rejected.stdout)
            exceeded = self.run_script(
                *common, "--body-pages", "31", "--output", "submission_excess_body.json",
            )
            self.assertNotEqual(exceeded.returncode, 0)
            self.assertTrue(any("maximum is 30" in item for item in read_json(project / "submission_excess_body.json")["errors"]))

    def test_max_pages_excludes_ai_report_fails_over_limit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-pages-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            manifest = read_json(paths["manifest"])
            manifest["competition_profile"]["submission"]["max_pages_excludes_ai_report"] = True
            manifest["competition_profile"]["submission"]["max_pages"] = 20
            manifest["competition_profile"]["submission"]["ai_disclosure_format"] = "both"
            manifest["competition_profile"]["submission"]["required_manual_checks"].append("ai_report_position")
            checkpoint = next(row for row in manifest["human_checkpoints"] if row["stage"] == "s1")
            checkpoint["manual_checks"].append("ai_report_position")
            checkpoint["manual_checks"].append("ai_report_in_paper")
            write_json(paths["manifest"], manifest)
            report = self.run_script(
                "qa/check_submission.py", "--project-root", str(project), "--run-manifest", paths["manifest"].name,
                "--paper", paths["paper"].name, "--paper-pages", "25", "--page-count-method", "manual_verified",
                "--ai-report-pages", "3",
                "--support", paths["support"].name, "--ai-disclosure", paths["ai_disclosure"].name,
                "--output", "submission_qa_pages.json",
            )
            self.assertNotEqual(report.returncode, 0)
            self.assertIn("maximum is 20", read_json(project / "submission_qa_pages.json")["errors"][0])

    def test_ai_report_pages_cannot_exceed_total_pages(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-pages-bound-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            manifest = read_json(paths["manifest"])
            rules = manifest["competition_profile"]["submission"]
            rules["max_pages_excludes_ai_report"] = True
            rules["max_pages"] = 20
            rules["ai_disclosure_format"] = "both"
            checkpoint = next(row for row in manifest["human_checkpoints"] if row["stage"] == "s1")
            checkpoint["manual_checks"].extend(["ai_report_position", "ai_report_in_paper"])
            write_json(paths["manifest"], manifest)
            report = self.run_script(
                "qa/check_submission.py", "--project-root", str(project), "--run-manifest", paths["manifest"].name,
                "--paper", paths["paper"].name, "--paper-pages", "22", "--page-count-method", "manual_verified",
                "--ai-report-pages", "30", "--support", paths["support"].name,
                "--ai-disclosure", paths["ai_disclosure"].name, "--output", "submission_qa_bad_pages.json",
            )
            self.assertNotEqual(report.returncode, 0)
            self.assertIn("smaller than the total", read_json(project / "submission_qa_bad_pages.json")["errors"][0])

    def test_freeze_rejects_ai_usage_added_after_s1(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-stale-ai-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            manifest = read_json(paths["manifest"])
            added_usage = dict(manifest["ai_usage"][0])
            added_usage["usage_id"] = "AI-2"
            added_usage["stage"] = "writing"
            manifest["ai_usage"].append(added_usage)
            write_json(paths["manifest"], manifest)
            freeze = self.run_script(
                "freeze_submission.py", "--project-root", str(project), "--run-manifest", paths["manifest"].name,
                "--s1-report", paths["submission_report"].name, "--paper", paths["paper"].name,
                "--support", paths["support"].name, "--ai-disclosure", paths["ai_disclosure"].name,
                "--deadline", "2026-09-01T20:00:00+08:00", "--timezone", "Asia/Hong_Kong",
                "--output", paths["submission_manifest"].name,
            )
            self.assertNotEqual(freeze.returncode, 0)
            self.assertIn("AI usage hash is stale", freeze.stderr)

    def test_freeze_rejects_tampered_page_audit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-stale-pages-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            report = read_json(paths["submission_report"])
            report["page_count"]["limited_pages"] = 10
            write_json(paths["submission_report"], report)
            manifest = read_json(paths["manifest"])
            submission_artifact = next(row for row in manifest["artifacts"] if row["role"] == "submission_qa")
            submission_artifact["sha256"] = sha256(paths["submission_report"])
            write_json(paths["manifest"], manifest)
            freeze = self.run_script(
                "freeze_submission.py", "--project-root", str(project), "--run-manifest", paths["manifest"].name,
                "--s1-report", paths["submission_report"].name, "--paper", paths["paper"].name,
                "--support", paths["support"].name, "--ai-disclosure", paths["ai_disclosure"].name,
                "--deadline", "2026-09-01T20:00:00+08:00", "--timezone", "Asia/Hong_Kong",
                "--output", paths["submission_manifest"].name,
            )
            self.assertNotEqual(freeze.returncode, 0)
            self.assertIn("limited_pages does not equal", freeze.stderr)

    def test_ai_conditional_manual_checks_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-ai-checks-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            manifest = read_json(paths["manifest"])
            manifest["competition_profile"]["submission"]["ai_manual_checks"] = {
                "when_used": ["ai_inline_citations"],
                "when_not_used": ["no_ai_declaration"],
            }
            write_json(paths["manifest"], manifest)
            report = self.run_script(
                "qa/check_submission.py", "--project-root", str(project), "--run-manifest", paths["manifest"].name,
                "--paper", paths["paper"].name, "--paper-pages", "12", "--page-count-method", "manual_verified",
                "--support", paths["support"].name, "--ai-disclosure", paths["ai_disclosure"].name,
                "--output", "submission_qa_ai_checks.json",
            )
            self.assertNotEqual(report.returncode, 0)
            self.assertIn("ai_inline_citations", read_json(project / "submission_qa_ai_checks.json")["errors"][0])

    def test_s1_rejects_stale_ai_disclosure_inside_support_zip(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-ai-support-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            with zipfile.ZipFile(paths["support"], "w") as archive:
                archive.writestr(paths["ai_disclosure"].name, b"stale AI disclosure")
            manifest = read_json(paths["manifest"])
            manifest["competition_profile"]["submission"]["ai_manual_checks"] = {
                "when_used": ["ai_disclosure_in_support"],
                "when_not_used": [],
            }
            checkpoint = next(row for row in manifest["human_checkpoints"] if row["stage"] == "s1")
            checkpoint["manual_checks"].append("ai_disclosure_in_support")
            checkpoint["artifacts"] = [file_ref(paths["paper"]), file_ref(paths["support"]), file_ref(paths["ai_disclosure"])]
            write_json(paths["manifest"], manifest)
            report = self.run_script(
                "qa/check_submission.py", "--project-root", str(project), "--run-manifest", paths["manifest"].name,
                "--paper", paths["paper"].name, "--paper-pages", "12", "--page-count-method", "manual_verified",
                "--support", paths["support"].name, "--ai-disclosure", paths["ai_disclosure"].name,
                "--output", "submission_qa_ai_support.json",
            )
            self.assertNotEqual(report.returncode, 0)
            self.assertIn("matching SHA-256", read_json(project / "submission_qa_ai_support.json")["errors"][0])

    def test_modeling_ai_requires_team_led_confirmation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-ai-model-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            manifest = read_json(paths["manifest"])
            manifest["ai_usage"][0]["stage"] = "modeling"
            write_json(paths["manifest"], manifest)
            safety = self.run_script(
                "qa/check_contest_safety.py", "--project-root", str(project),
                "--manifest", paths["manifest"].name, "--strict",
            )
            self.assertNotEqual(safety.returncode, 0)
            self.assertIn("team_led_core_modeling", safety.stdout)

    def test_modeling_ai_passes_with_team_led_confirmation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-harness-ai-model-") as temp:
            project = Path(temp)
            paths = self.build_fixture(project)
            manifest = read_json(paths["manifest"])
            manifest["ai_usage"][0]["stage"] = "modeling"
            m1_checkpoint = next(row for row in manifest["human_checkpoints"] if row["stage"] == "m1")
            m1_checkpoint["manual_checks"].append("team_led_core_modeling")
            write_json(paths["manifest"], manifest)
            safety = self.run_script(
                "qa/check_contest_safety.py", "--project-root", str(project),
                "--manifest", paths["manifest"].name, "--strict",
            )
            self.assertEqual(safety.returncode, 0, safety.stdout + safety.stderr)


if __name__ == "__main__":
    unittest.main()
