"""End-to-end demo driver: problem input to review-validated evidence.

Run it against an empty directory::

    python examples/end_to_end/run_demo.py --out tmp/demo-run

Every step shells out to the real ``harness`` CLI, so the printed commands,
exit codes and artifact paths are the same ones an operator would see. Nothing
here writes a Gate verdict, a receipt, a hash or a review conclusion by hand:
the Harness recomputes all of them.

The driver finishes with a property table. Each row is produced by actually
attempting the corresponding bypass, not by asserting that the design intends
to prevent it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
SCRIPTS = REPO_ROOT / "scripts"
STUB_REVIEWER = REPO_ROOT / "tests" / "fixtures" / "review_stub" / "stub_reviewer.py"

DEMAND = [10, 20, 30]
CAPACITY = [40, 30, 20]
UNIT_COST = [[5, 8, 4], [6, 3, 7], [9, 5, 6]]
OPTIMAL_COST = 230

ABSTRACT = (
    "The three products are supplied from the candidate depots under the declared "
    f"capacities. The selected assignment costs {OPTIMAL_COST} CNY, which is the "
    "minimum of the enumerated feasible assignments and was recomputed "
    "independently by summation order.\n"
)
PAPER = (
    "Question 1 assigns each product to one depot. Demand, capacity and unit cost "
    "are read from input.json and nothing else is assumed. Enumerating every "
    "capacity-feasible assignment and taking the cheapest gives "
    f"{OPTIMAL_COST} CNY. Feasibility was checked by recomputing the capacity "
    "surplus of each depot, and the objective was recomputed by summing over "
    "depots instead of over products; both recomputations agree with the frozen "
    "result. The conclusion is limited to the declared demand and capacities: no "
    "stochastic demand, no substitution between products, and no second delivery "
    "period is represented.\n"
)
CONCLUSION = f"Under the declared demand and capacities the selected assignment costs {OPTIMAL_COST} CNY.\n"
OVERCLAIM = "Our plan dominates all possible plans and is provably the best in every scenario."


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class Demo:
    """One project root plus the recorded command evidence of what happened."""

    def __init__(self, root: Path, *, verbose: bool = True) -> None:
        self.root = root
        self.verbose = verbose
        self.log: list[dict[str, object]] = []

    def harness(self, *args: str, name: str) -> subprocess.CompletedProcess[str]:
        command = [sys.executable, str(SCRIPTS / "harness.py"), *args]
        completed = subprocess.run(
            command, cwd=REPO_ROOT, text=True, capture_output=True,
            encoding="utf-8", errors="replace", check=False,
        )
        self.log.append({
            "step": name,
            "command": " ".join(["harness", *args]),
            "exit_code": completed.returncode,
        })
        if self.verbose:
            marker = "ok  " if completed.returncode == 0 else "FAIL"
            print(f"  [{marker}] {name}: harness {' '.join(args)}")
        return completed

    def script(self, script: str, *args: str, name: str) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / script), *args], cwd=self.root,
            text=True, capture_output=True, encoding="utf-8", errors="replace", check=False,
        )
        self.log.append({"step": name, "command": f"python scripts/{script} ...", "exit_code": completed.returncode})
        if self.verbose:
            marker = "ok  " if completed.returncode == 0 else "FAIL"
            print(f"  [{marker}] {name}")
        return completed

    def expect_ok(self, completed: subprocess.CompletedProcess[str], name: str) -> dict:
        if completed.returncode != 0:
            raise SystemExit(
                f"{name} failed with exit {completed.returncode}\n"
                f"--- stdout ---\n{completed.stdout[-4000:]}\n--- stderr ---\n{completed.stderr[-4000:]}"
            )
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError:
            return {}


# ---------------------------------------------------------------------------
# Author-plane artifacts (what the problem_analyst / modeler agents produce)
# ---------------------------------------------------------------------------

def model_contract() -> dict:
    return {
        "schema_version": "1.3",
        "project_id": "harness-demo",
        "run_id": "run-1",
        "unit_system": "SI counts with CNY for cost",
        "questions": [{
            "question_id": "q1",
            "task": "minimize total procurement cost subject to depot capacities",
            "conclusion_type": "numeric minimum",
            "inputs": ["demand", "capacity", "unit_cost"],
            "outputs": ["optimal_cost"],
        }],
        "data_sources": [{
            "data_id": "problem_input",
            "path": "input.json",
            "read_only": True,
            "sha256": "<filled>",
            "origin": "synthetic demo statement attachment",
            "license_or_terms": "demo use",
            "transformations": [],
            "quality_checks": ["shape, range and unit checks on demand, capacity and unit_cost"],
        }],
        "assumptions": [{
            "assumption_id": "A1",
            "text": "each product is covered by exactly one depot and demand is fixed",
            "basis": "demo statement",
            "sensitivity_plan": "rerun with +/-10% demand per product",
        }],
        "research_basis": {
            "status": "verified",
            "research_questions": [{
                "research_id": "RES-Q1", "question_ids": ["q1"],
                "purpose": "compare exact enumeration with greedy assignment for small capacitated allocation",
                "chinese_keywords": ["容量约束 指派 枚举"],
                "english_keywords": ["capacitated assignment enumeration optimum"],
            }],
            "searches": [
                {
                    "search_id": "S-LLM", "research_ids": ["RES-Q1"],
                    "query": "standard formulations for small capacitated single-source assignment",
                    "language": "en", "source": "llm_knowledge",
                    "searched_at": "2026-09-17T00:00:00Z", "candidate_count": 2,
                },
                {
                    "search_id": "S-WEB", "research_ids": ["RES-Q1"],
                    "query": "exact enumeration versus greedy for capacitated single-source assignment",
                    "language": "en", "source": "openalex",
                    "searched_at": "2026-09-17T00:01:00Z", "candidate_count": 4,
                    "evidence_ids": ["E-CITE-PLAN"],
                },
            ],
            "candidate_models": [
                {
                    "candidate_id": "CM-ENUM", "question_id": "q1",
                    "name": "exhaustive enumeration of feasible assignments",
                    "mechanism_fit": "the feasible set is 3^3 assignments, so the exact minimum is enumerable",
                    "assumptions": ["one depot per product", "demand is fixed"],
                    "data_requirements": ["demand", "capacity", "unit_cost"],
                    "strengths": ["exact and auditable", "objective recomputable by a second summation order"],
                    "weaknesses": ["does not scale to many products"],
                    "evidence_ids": ["E-CITE-PLAN"],
                    "rejection_conditions": ["the feasible set becomes too large to enumerate"],
                    "decision": "selected", "model_id": "M-Q1",
                },
                {
                    "candidate_id": "CM-GREEDY", "question_id": "q1",
                    "name": "greedy cheapest-depot-first",
                    "mechanism_fit": "cheap to compute but ignores capacity interaction",
                    "assumptions": ["cheapest local choice remains globally feasible"],
                    "data_requirements": ["demand", "capacity", "unit_cost"],
                    "strengths": ["linear in products"],
                    "weaknesses": ["can miss the minimum when capacities bind"],
                    "evidence_ids": ["E-CITE-PLAN"],
                    "rejection_conditions": ["capacities can force a non-cheapest depot"],
                    "decision": "rejected",
                },
            ],
            "decisions": [{
                "question_id": "q1", "selected_candidate_id": "CM-ENUM",
                "alternatives_considered": ["CM-GREEDY"],
                "selection_criteria": ["exactness", "recomputability", "auditability"],
                "rationale": "With 27 candidate assignments enumeration is cheap, exact, and lets the objective be recomputed independently.",
                "decisive_evidence_ids": ["E-CITE-PLAN"],
                "unresolved_risks": ["the enumeration assumption breaks if products grow"],
            }],
            "unresolved_questions": [],
        },
        "models": [{
            "model_id": "M-Q1",
            "question_id": "q1",
            "name": "enumerated depot allocation",
            "problem_type": "optimization",
            "characteristics": ["deterministic"],
            "rationale": "the feasible set is small enough to enumerate exactly",
            "variables": [{
                "symbol": "x", "meaning": "depot chosen for a product", "unit": "index",
                "domain": "x in {0,1,2}", "role": "decision",
            }],
            "objective": "minimize total procurement cost",
            "constraints": [{
                "constraint_id": "C1",
                "expression": "sum(demand[p] for p assigned to depot d) <= capacity[d]",
                "meaning": "no depot exceeds its capacity",
            }],
            "algorithm": "exhaustive enumeration of capacity-feasible assignments",
            "inputs": ["demand", "capacity", "unit_cost"],
            "outputs": ["optimal_cost"],
            "validation": [{
                "check_id": "V1", "stage": "both",
                "method": "recompute capacity surplus and the objective by an independent summation order",
                "acceptance": "violation is zero and both objective recomputations agree",
            }],
            "validation_obligations": [
                {
                    "obligation_id": "VAL-FEASIBILITY", "category": "feasibility",
                    "method": "recompute every capacity constraint",
                    "acceptance": {
                        "left_metric_id": "max_violation", "operator": "<=",
                        "right": {"kind": "literal", "value": 0}, "unit": "item",
                    },
                    "required_stage": "both",
                },
                {
                    "obligation_id": "VAL-OBJECTIVE", "category": "objective_recomputation",
                    "method": "sum the objective per depot instead of per product",
                    "acceptance": {
                        "left_metric_id": "solver_objective", "operator": "==",
                        "right": {"kind": "metric", "metric_id": "independent_objective"},
                        "unit": "CNY", "tolerance": 0.000001,
                    },
                    "required_stage": "full",
                },
            ],
            "risks": ["fixed-demand assumption"],
            "fallback": "report the cheapest feasible assignment found and its violation",
            "plan_details": {
                "selected_candidate_id": "CM-ENUM",
                "mechanism": "Cover each product from one depot while respecting depot capacities.",
                "equation_plan": [{
                    "equation_id": "EQ-Q1-OBJ", "purpose": "define the objective",
                    "expression_or_derivation": "min C(x) = sum over products of demand[p] * unit_cost[x[p]][p]",
                    "variables": ["x", "demand", "unit_cost"], "assumptions": ["one depot per product"],
                }],
                "parameter_plan": [
                    {
                        "parameter": "demand", "provenance": {
                            "type": "GIVEN", "source_locator": "input.json demand field",
                        }, "unit": "item", "uncertainty_or_range": "+/-10% sensitivity",
                    },
                    {
                        "parameter": "capacity", "provenance": {
                            "type": "GIVEN", "source_locator": "input.json capacity field",
                        }, "unit": "item", "uncertainty_or_range": "fixed by the statement",
                    },
                    {
                        "parameter": "unit_cost", "provenance": {
                            "type": "GIVEN", "source_locator": "input.json unit_cost matrix",
                        }, "unit": "CNY/item", "uncertainty_or_range": "fixed by the statement",
                    },
                ],
                "implementation_steps": [
                    "load and validate the input table",
                    "enumerate capacity-feasible assignments",
                    "recompute feasibility and objective independently",
                ],
                "output_artifacts": ["raw_results.json", "validation_measurements.json"],
                "validation_strategy": ["feasibility recomputation and objective recomputation"],
                "failure_modes": ["no capacity-feasible assignment exists"],
            },
        }],
        "terminology": [{"canonical": "selected assignment cost", "forbidden_variants": ["best cost ever"]}],
        "status": "ready",
    }


def paper_plan() -> dict:
    return {
        "schema_version": "1.2",
        "run_id": "run-1",
        "central_thesis": {
            "text": "The selected depot assignment meets every capacity and costs the least of the enumerated feasible assignments.",
            "claim_ids": ["C1"], "boundary": "Under the declared demand, capacities and unit costs.",
        },
        "requirements": [{"requirement_id": "RQ1", "text": "answer question 1", "claim_ids": ["C1"]}],
        "claims": [{
            "claim_id": "C1", "claim_type": "observation",
            "text": f"the selected assignment costs {OPTIMAL_COST} CNY", "question_id": "q1",
            "evidence_ids": ["E-R-Q1-01"], "result_ids": ["R-Q1-01"],
            "section": "results.q1", "boundary": "under the frozen run", "support_level": "direct",
        }],
        "sections": [{"section_id": "results.q1", "purpose": "answer question 1", "claim_ids": ["C1"]}],
        "argument_units": [
            {
                "unit_id": "AU-Q1-FORM", "section_id": "results.q1",
                "rhetorical_role": "mechanism_derivation", "claim_ids": ["C1"],
                "evidence_ids": ["E-R-Q1-01"], "prerequisite_unit_ids": [],
                "expected_reader_judgment": "The formulation matches the one-depot-per-product mechanism.",
                "boundary": "One depot per product.", "target_words": 60,
            },
            {
                "unit_id": "AU-Q1-RESULT", "section_id": "results.q1",
                "rhetorical_role": "result_observation", "claim_ids": ["C1"],
                "evidence_ids": ["E-R-Q1-01"], "prerequisite_unit_ids": ["AU-Q1-FORM"],
                "expected_reader_judgment": "The reported cost comes from the frozen run.",
                "boundary": "Under the frozen run.", "target_words": 60,
            },
            {
                "unit_id": "AU-Q1-VALID", "section_id": "results.q1",
                "rhetorical_role": "validation", "claim_ids": ["C1"],
                "evidence_ids": ["E-R-Q1-01"], "prerequisite_unit_ids": ["AU-Q1-RESULT"],
                "expected_reader_judgment": "Feasibility and objective were recomputed independently.",
                "boundary": "Declared constraints only.", "target_words": 60,
            },
            {
                "unit_id": "AU-Q1-INTERP", "section_id": "results.q1",
                "rhetorical_role": "boundary", "claim_ids": ["C1"],
                "evidence_ids": ["E-R-Q1-01"], "prerequisite_unit_ids": ["AU-Q1-VALID"],
                "expected_reader_judgment": "The result is not extrapolated beyond the stated data.",
                "boundary": "No stochastic-demand claim.", "target_words": 60,
            },
        ],
        "depth_budget": [{"question_id": "q1", "target_words": 180, "rationale": "One validated allocation result."}],
        "precision_policy": {
            "audit_source": "frozen_display_value", "prose_source": "frozen_display_value",
            "table_source": "frozen_display_value", "abstract_max_numeric_claims": 2,
        },
        "abstract_results": [{
            "result_id": "R-Q1-01", "priority": "primary",
            "selection_reason": "The decision-defining validated cost.",
            "claim_ids": ["C1"], "word_budget": 24,
        }],
        "terminology": [{"canonical": "selected assignment cost", "forbidden_variants": ["best cost ever"]}],
        "figures": [], "tables": [],
        "readiness": {
            "stage": "technical_draft",
            "question_coverage": [{
                "question_id": "q1",
                "formulation_unit_ids": ["AU-Q1-FORM"], "result_unit_ids": ["AU-Q1-RESULT"],
                "validation_unit_ids": ["AU-Q1-VALID"], "interpretation_unit_ids": ["AU-Q1-INTERP"],
                "display_ids": [], "display_waiver": "One scalar result; prose is clearer than a display.",
            }],
        },
        "status": "ready",
    }


def seed_registry(root: Path) -> dict:
    """Evidence that exists before any run: the verified method source.

    Result evidence is appended by ``register_evidence`` after the freeze; a
    registry written here can never carry a number, which is the point.
    """
    return {
        "schema_version": "1.1",
        "run_id": "run-1",
        "source_snapshots": [{
            "kind": "manual_seed", "path": "problem.md", "sha256": sha256(root / "problem.md"),
        }],
        "evidence": [{
            "evidence_id": "E-CITE-PLAN", "type": "citation", "result_ids": [], "artifacts": [],
            "supports": "enumeration is exact and auditable for a small capacitated assignment",
            "boundary": "method choice only; it does not validate this run's numerical result",
            "verification_status": "verified",
            "citation": {
                "bib_key": "demomethod2026", "title": "Exact enumeration for small capacitated assignment",
                "authors": ["Demo Author"], "year": 2026,
                "canonical_url": "https://example.invalid/demo/enumeration",
                "venue": "Demo Methods Note", "source_tier": "publisher",
                "metadata_sources": ["https://example.invalid/demo/enumeration"],
                "access_level": "full_text", "locator": "Section 2",
                "metadata_verified": True, "content_verified": True,
                "publication_status_checked": True,
                "verified_at": "2026-09-17T00:00:00Z",
            },
        }],
    }


def synthetic_profile() -> dict:
    """A verified profile for a synthetic competition, so S1 has real rules.

    The snapshot is the demo statement itself. A real contest run must bind the
    organizer's page instead; a seed profile is never an official rule.
    """
    return {
        "schema_version": "2.0",
        "profile_id": "harness-demo",
        "status": "verified",
        "competition": {
            "family": "other", "name": "Harness end-to-end demo (synthetic)",
            "season": "2026", "mode": "practice", "language": "en",
        },
        "official_rules": [{
            "rule_id": "DEMO-RULES",
            "title": "Synthetic demo competition rules",
            "url": "https://example.invalid/harness-demo/rules",
            "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "snapshot": {"path": "rules.md"},
        }],
        "official_submission_endpoints": [{
            "name": "synthetic demo portal",
            "url": "https://example.invalid/harness-demo/submit",
            "kind": "portal",
        }],
        "submission": {
            "paper_extensions": [".txt", ".pdf"],
            "max_paper_bytes": None,
            "max_pages": 25,
            "max_pages_excludes_ai_report": False,
            "page_count_scope": "paper_body",
            "support_policy": "optional",
            "max_support_bytes": None,
            "ai_disclosure_policy": "required_when_used",
            "ai_disclosure_format": "separate_file",
            "ai_manual_checks": {
                "when_used": ["ai_generated_content_marked"],
                "when_not_used": ["no_ai_declaration_after_references"],
            },
            "required_manual_checks": ["ai_generated_content_marked"],
        },
        "template_id": None,
        "visual_profile_id": None,
        "metadata": {"source": "examples/end_to_end", "official_verified": True},
    }


RULES_TEXT = """# Synthetic demo competition rules

- One short paper answering question 1.
- Plain text or PDF; body limited to 25 pages.
- AI assistance must be disclosed when used.
This file is the rule snapshot for a synthetic demo; it is not a real
organizer's page.
"""


ROLE_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "evidence_registry": ("model_contract",),
    "raw_results": ("model_contract",),
    "frozen_results": ("model_contract", "raw_results"),
    "paper_plan": ("model_contract", "frozen_results", "evidence_registry"),
    "paper": ("paper_plan", "frozen_results"),
    "abstract": ("paper_plan", "frozen_results"),
    "conclusion": ("paper_plan",),
}


def refresh_dag(
    demo: Demo,
    roles: dict[str, str],
    *,
    frozen: bool = False,
    producer_receipt_ids: dict[str, str] | None = None,
) -> None:
    """Re-project the author artifacts into the canonical DAG with live digests."""
    ids_by_role = {
        role: f"ART-{role.upper().replace('_', '-')}-{index}"
        for index, role in enumerate(roles, start=1)
    }
    nodes = []
    receipt_ids = producer_receipt_ids or {}
    for index, (role, path) in enumerate(roles.items(), start=1):
        artifact_path = demo.root / path
        artifact_id = ids_by_role[role]
        producer_receipt_id = receipt_ids.get(role)
        node_data: dict[str, Any] = {
            "artifact_id": artifact_id,
            "role": role,
            "path": path,
            "producer_id": f"producer-{role}",
            "dependencies": [
                {"artifact_id": ids_by_role[dep], "relation": "consumes"}
                for dep in ROLE_DEPENDENCIES.get(role, ()) if dep in ids_by_role
            ],
            "lifecycle": "frozen" if (frozen and role == "frozen_results") else "mutable",
            "freshness": "current",
            "version": "1",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if producer_receipt_id:
            node_data["producer_receipt_id"] = producer_receipt_id
            node_data["digest_owner"] = f"command_receipt:{producer_receipt_id}"
        else:
            node_data["digest_owner"] = "artifact_dag"
            node_data["digest_algorithm"] = "sha256"
            node_data["sha256"] = sha256(artifact_path)
        nodes.append(node_data)
    dag = load_json(demo.root / "artifact_dag.json")
    dag["nodes"] = [node for node in dag["nodes"] if node["role"] == "competition_profile"] + nodes
    write_json(demo.root / "artifact_dag.json", dag)


def add_checkpoint(demo: Demo, stage: str, decided_by: str, *, actor_class: str = "human") -> None:
    """Record the operator's decision on one checkpoint stage.

    The Harness cannot attest who typed this; that boundary is stated in the
    demo report and probed by the red-team evaluation.  ``actor_class`` is the
    part a Gate does enforce: only a human row clears a human checkpoint.
    """
    manifest = load_json(demo.root / "run_manifest.json")
    manifest["human_checkpoints"] = [
        row for row in manifest.get("human_checkpoints", []) if row.get("stage") != stage
    ] + [{
        "checkpoint_id": f"CHK-{stage.upper()}",
        "stage": stage, "decision": "pass", "decided_by": decided_by,
        "actor_class": actor_class,
        "decided_at": datetime.now(timezone.utc).isoformat(),
        "note": f"operator confirmed the {stage.upper()} scope in the demo run",
    }]
    write_json(demo.root / "run_manifest.json", manifest)


# ---------------------------------------------------------------------------
# Chain
# ---------------------------------------------------------------------------

def latest_usage_record(demo: Demo) -> dict[str, object]:
    """The AI usage row the Harness wrote for the observed backend call."""

    records = load_json(demo.root / "run_manifest.json").get("ai_usage") or []
    if not records:
        raise SystemExit("the review backend wrote no AI usage record; the ledger is not observing calls")
    return records[-1]


def build(demo: Demo) -> dict[str, object]:
    root = demo.root
    print("S0  init and bind the rule snapshot")
    demo.expect_ok(demo.harness("init", "--project", str(root), "--competition", "cumcm", "--preset", "sprint", "--json", name="init"), "init")
    shutil.copy2(HERE / "model.py", root / "model.py")
    shutil.copy2(HERE / "input.json", root / "input.json")
    shutil.copy2(HERE / "problem.md", root / "problem.md")
    (root / "rules.md").write_text(RULES_TEXT, encoding="utf-8")
    write_json(root / "competition_profile.json", synthetic_profile())
    # Re-point the profile node at the live bytes, then declare run identity.
    dag = load_json(root / "artifact_dag.json")
    profile_node = next(node for node in dag["nodes"] if node["role"] == "competition_profile")
    profile_node.update({"sha256": sha256(root / "competition_profile.json"), "digest_algorithm": "sha256", "metadata": {"status": "verified"}})
    write_json(root / "artifact_dag.json", dag)
    manifest = load_json(root / "run_manifest.json")
    manifest["run_id"] = "run-1"
    manifest["project_id"] = "harness-demo"
    manifest["status"] = "active"
    manifest["stage"] = "paper"
    manifest["roots"]["model_contract"] = {"path": "model_contract.json"}
    manifest["roots"]["evidence_registry"] = {"path": "evidence_registry.json"}
    manifest["roots"]["paper_plan"] = {"path": "paper_plan.json"}
    manifest["competition_profile_ref"]["profile_id"] = "harness-demo"
    policy = {
        "interactive_human_help": "allow", "current_problem_discussion": "allow",
        "public_posting": "allow", "external_write": "allow",
        "static_reference_search": "allow", "ai_tool_use": "allow",
    }
    manifest["safety"] = {
        "official_rule": dict(policy), "local_conservative_policy": dict(policy), "events": [],
    }
    write_json(root / "run_manifest.json", manifest)
    index = load_json(root / "run_index.json")
    index["run_id_scope"] = "run-1"
    write_json(root / "run_index.json", index)

    print("M1  problem analyst and modeler contracts")
    contract = model_contract()
    contract["data_sources"][0]["sha256"] = sha256(root / "input.json")
    write_json(root / "model_contract.json", contract)
    write_json(root / "evidence_registry.json", seed_registry(root))
    refresh_dag(demo, {
        "model_contract": "model_contract.json",
        "evidence_registry": "evidence_registry.json",
    })
    add_checkpoint(demo, "m1", "demo-operator")
    m1 = demo.harness("check", "M1", "--project", str(root), "--json", name="check M1")
    demo.expect_ok(m1, "check M1")

    print("P1  one real smoke process")
    smoke = demo.harness(
        "execute", "--project", str(root), "--stage", "smoke",
        "--covers-model", "M-Q1", "--covers-question", "q1", "--covers-contract-item", "EQ-Q1-OBJ",
        "--", sys.executable, "model.py", "--smoke", "--results", "smoke_results.json",
        "--measurements", "smoke_measurements.json", name="execute smoke",
    )
    demo.expect_ok(smoke, "execute smoke")
    p1 = demo.harness("check", "P1", "--project", str(root), "--json", name="check P1")
    demo.expect_ok(p1, "check P1")

    print("P2  full run, independent recomputation, freeze")
    full = demo.harness(
        "execute", "--project", str(root), "--stage", "full", "--selected",
        "--output-artifact", "raw_results.json",
        "--", sys.executable, "model.py", name="execute full",
    )
    full_payload = demo.expect_ok(full, "execute full")
    full_receipt = Path(str(full_payload["receipt"])).resolve()
    full_receipt_ref = full_receipt.relative_to(root.resolve()).as_posix()
    full_receipt_id = str(full_payload.get("receipt_id") or load_json(full_receipt).get("receipt_id"))
    evaluated = demo.script(
        "validation/evaluate_obligations.py", "--project-root", str(root),
        "--model-contract", "model_contract.json", "--measurements", "validation_measurements.json",
        "--output", "full_validation.json", name="evaluate obligations",
    )
    demo.expect_ok(evaluated, "evaluate obligations")
    add_checkpoint(demo, "p2", "demo-operator")
    freeze = demo.harness(
        "execute", "--project", str(root), "--stage", "freeze", "--freeze",
        "--output-artifact", "frozen_results.json",
        "--", sys.executable, str(SCRIPTS / "freeze_results.py"),
        "--project-root", str(root), "--source", "raw_results.json", "--output", "frozen_results.json",
        "--receipt", full_receipt_ref,
        "--run-id", "run-1", "--model-contract", "model_contract.json",
        "--input", "input.json", "--code", "model.py", "--validation", "full_validation.json",
        name="execute freeze",
    )
    freeze_payload = demo.expect_ok(freeze, "execute freeze")
    freeze_receipt = Path(str(freeze_payload["receipt"])).resolve()
    freeze_receipt_id = str(freeze_payload.get("receipt_id") or load_json(freeze_receipt).get("receipt_id"))
    registered = demo.script(
        "register_evidence.py", "--project-root", str(root),
        "--frozen-results", "frozen_results.json",
        "--output", ".harness/registry_from_results.json",
        name="register evidence",
    )
    demo.expect_ok(registered, "register evidence")
    from_results = load_json(root / ".harness" / "registry_from_results.json")
    seed = seed_registry(root)
    known = {row["evidence_id"] for row in from_results["evidence"]}
    from_results["evidence"].extend(
        row for row in seed["evidence"] if row["evidence_id"] not in known
    )
    known_sources = {row["path"] for row in from_results.get("source_snapshots", [])}
    from_results["source_snapshots"].extend(
        row for row in seed["source_snapshots"] if row["path"] not in known_sources
    )
    write_json(root / "evidence_registry.json", from_results)
    refresh_dag(demo, {
        "model_contract": "model_contract.json",
        "evidence_registry": "evidence_registry.json",
        "raw_results": "raw_results.json",
        "frozen_results": "frozen_results.json",
    }, frozen=True, producer_receipt_ids={
        "raw_results": full_receipt_id,
        "frozen_results": freeze_receipt_id,
    })
    p2 = demo.harness("check", "P2", "--project", str(root), "--json", name="check P2")
    demo.expect_ok(p2, "check P2")

    print("W1  paper plan bound to claimable evidence")
    write_json(root / "paper_plan.json", paper_plan())
    (root / "abstract.txt").write_text(ABSTRACT, encoding="utf-8")
    (root / "paper.txt").write_text(PAPER, encoding="utf-8")
    (root / "conclusion.txt").write_text(CONCLUSION, encoding="utf-8")
    refresh_dag(demo, {
        "model_contract": "model_contract.json",
        "evidence_registry": "evidence_registry.json",
        "raw_results": "raw_results.json",
        "frozen_results": "frozen_results.json",
        "paper_plan": "paper_plan.json",
        "abstract": "abstract.txt",
        "paper": "paper.txt",
        "conclusion": "conclusion.txt",
    }, frozen=True, producer_receipt_ids={
        "raw_results": full_receipt_id,
        "frozen_results": freeze_receipt_id,
    })
    add_checkpoint(demo, "w1", "demo-operator")
    w1 = demo.harness("check", "W1", "--project", str(root), "--json", name="check W1")
    demo.expect_ok(w1, "check W1")

    print("W2  deterministic QA plus one fresh-context review")
    review = demo.harness(
        "review", "--project", str(root), "--fresh", "--backend-cmd",
        f'"{sys.executable}" "{STUB_REVIEWER}"', "--backend-kind", "ai",
        "--ai-tool-name", "demo-reviewer", "--ai-model", "fixture-model",
        "--ai-provider", "local-fixture", "--json", name="review --fresh",
    )
    demo.expect_ok(review, "review --fresh")
    # The Harness logged the observable AI call as pending; a human verifies it.
    usage = latest_usage_record(demo)
    verified = demo.harness(
        "ai", "verify", "--project", str(root), "--usage-id", str(usage["usage_id"]),
        "--checked-by-role", "demo-operator",
        "--verification-method", "compared the report against the frozen evidence",
        "--human-changes", "accepted no changes; findings already matched evidence",
        "--json", name="ai verify",
    )
    demo.expect_ok(verified, "ai verify")
    add_checkpoint(demo, "w2", "demo-operator")
    w2 = demo.harness("validate", "--project", str(root), "--json", name="validate W2")
    demo.expect_ok(w2, "validate W2")
    return {"review": review}


# ---------------------------------------------------------------------------
# Property probes: each one attempts a real violation on a copy and reports
# only what the Harness actually did.
# ---------------------------------------------------------------------------

def _clone(demo: Demo, name: str) -> Demo:
    target = demo.root.parent / f"{demo.root.name}-{name}"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(demo.root, target)
    return Demo(target, verbose=demo.verbose)


def _gate_errors(demo: Demo, gate: str) -> tuple[int, list[str]]:
    completed = demo.harness("check", gate, "--project", str(demo.root), "--json", name=f"check {gate}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {}
    return completed.returncode, list(payload.get("errors", []))


def _validate_errors(demo: Demo) -> tuple[int, list[str]]:
    completed = demo.harness("validate", "--project", str(demo.root), "--json", name="validate")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {}
    return completed.returncode, list(payload.get("errors", []))


def probe_gate_field_is_inert(demo: Demo) -> dict[str, object]:
    """Write a Gate PASS by hand and prove the Gate still fails on its facts."""
    probe = _clone(demo, "gate-inert")
    manifest = load_json(probe.root / "run_manifest.json")
    manifest["human_checkpoints"] = [
        row for row in manifest["human_checkpoints"] if row.get("stage") != "m1"
    ]
    manifest["gates"] = {"m1": {"status": "pass"}}
    write_json(probe.root / "run_manifest.json", manifest)
    code, errors = _gate_errors(probe, "M1")
    return {
        "property": "an agent cannot pass a Gate by editing state",
        "attempt": "hand-write gates.m1.status=pass and drop the M1 human checkpoint",
        "held": code != 0 and any("forbidden duplicated state: gates" in row for row in errors),
        "evidence": [row for row in errors if "checkpoint" in row or "gates" in row][:2],
    }


def probe_freeze_needs_execution(demo: Demo) -> dict[str, object]:
    """Freeze the same numbers without a receipt and prove P2 refuses them."""
    probe = _clone(demo, "freeze-claim")
    # An existing frozen artifact cannot be rewritten in place, so the attack
    # writes an unbacked substitute and repoints the DAG at it.
    refused = probe.script(
        "freeze_results.py", "--project-root", str(probe.root),
        "--source", "raw_results.json", "--output", "frozen_results.json",
        "--run-id", "run-1", "--model-contract", "model_contract.json",
        "--command", "python model.py", "--input", "input.json",
        "--code", "model.py", "--validation", "full_validation.json",
        name="in-place legacy freeze",
    )
    substitute = probe.script(
        "freeze_results.py", "--project-root", str(probe.root),
        "--source", "raw_results.json", "--output", "unbacked_frozen.json",
        "--run-id", "run-1", "--model-contract", "model_contract.json",
        "--command", "python model.py", "--input", "input.json",
        "--code", "model.py", "--validation", "full_validation.json",
        name="legacy freeze to a new path",
    )
    if substitute.returncode != 0:
        return {
            "property": "a frozen result must come from a captured execution",
            "attempt": "freeze the same numbers with only a free-text --command",
            "held": refused.returncode != 0 and "requires --receipt" in substitute.stderr,
            "evidence": [
                f"in-place overwrite refused: exit={refused.returncode}",
                f"unbacked substitute refused: exit={substitute.returncode}",
                substitute.stderr.strip(),
            ],
        }
    dag = load_json(probe.root / "artifact_dag.json")
    for node in dag["nodes"]:
        if node["role"] == "frozen_results":
            node["path"] = "unbacked_frozen.json"
            node["sha256"] = sha256(probe.root / "unbacked_frozen.json")
    write_json(probe.root / "artifact_dag.json", dag)
    code, errors = _gate_errors(probe, "P2")
    return {
        "property": "a frozen result must come from a captured execution",
        "attempt": "freeze the same numbers with only a free-text --command, then repoint the DAG",
        "held": code != 0 and any("receipt" in row for row in errors),
        "evidence": [
            f"in-place overwrite refused: exit={refused.returncode}",
            f"unbacked substitute written: exit={substitute.returncode}",
            *[row for row in errors if "receipt" in row][:2],
        ],
    }


def probe_downstream_goes_stale(demo: Demo) -> dict[str, object]:
    """Edit the reviewed paper after a passing review and re-validate."""
    probe = _clone(demo, "stale")
    text = (probe.root / "paper.txt").read_text(encoding="utf-8")
    (probe.root / "paper.txt").write_text(
        text + "A late sentence was added after the review.\n", encoding="utf-8",
    )
    dag = load_json(probe.root / "artifact_dag.json")
    for node in dag["nodes"]:
        if node["role"] == "paper":
            node["sha256"] = sha256(probe.root / "paper.txt")
    write_json(probe.root / "artifact_dag.json", dag)
    code, errors = _validate_errors(probe)
    return {
        "property": "an upstream edit makes the downstream review stale",
        "attempt": "append one sentence to the reviewed paper, then re-validate W2",
        "held": code != 0 and any("changed since review" in row for row in errors),
        "evidence": [row for row in errors if "changed since review" in row][:2],
    }


def probe_reviewer_cannot_self_promote(demo: Demo) -> dict[str, object]:
    """A backend that declares its own independence level must be refused."""
    probe = _clone(demo, "promote")
    completed = subprocess.run(
        [
            sys.executable, str(SCRIPTS / "harness.py"), "review",
            "--project", str(probe.root), "--fresh", "--backend-cmd",
            f'"{sys.executable}" "{STUB_REVIEWER}"', "--backend-kind", "non_ai", "--json",
        ],
        cwd=REPO_ROOT, text=True, capture_output=True,
        encoding="utf-8", errors="replace", check=False,
        env={**os.environ, "MATH_REVIEW_STUB_LEVEL_OVERRIDE": "L2_independent_model"},
    )
    payload = json.loads(completed.stdout or "{}")
    errors = list(payload.get("errors", []))
    return {
        "property": "review independence is bound by the Harness, not claimed",
        "attempt": "have the reviewer backend self-declare L2_independent_model",
        "held": completed.returncode != 0 and any("orchestrator-bound" in row for row in errors),
        "evidence": [row for row in errors if "orchestrator-bound" in row][:1],
    }


def probe_unsupported_claim_is_blocked(demo: Demo) -> dict[str, object]:
    """Add an unevidenced figure, re-review it, and see what still stands."""
    probe = _clone(demo, "claim")
    (probe.root / "abstract.txt").write_text(
        ABSTRACT + "The savings reach 40 percent against the industry average.\n",
        encoding="utf-8",
    )
    dag = load_json(probe.root / "artifact_dag.json")
    for node in dag["nodes"]:
        if node["role"] == "abstract":
            node["sha256"] = sha256(probe.root / "abstract.txt")
    write_json(probe.root / "artifact_dag.json", dag)
    # Re-review so a stale-review refusal cannot mask the claim verdict.
    reviewed = subprocess.run(
        [
            sys.executable, str(SCRIPTS / "harness.py"), "review",
            "--project", str(probe.root), "--fresh", "--backend-cmd",
            f'"{sys.executable}" "{STUB_REVIEWER}"', "--backend-kind", "non_ai", "--json",
        ],
        cwd=REPO_ROOT, text=True, capture_output=True,
        encoding="utf-8", errors="replace", check=False,
    )
    code, errors = _validate_errors(probe)
    # The claim is refused by deterministic content QA, not by the review
    # staleness that any edit also triggers; key on that independent signal.
    signals = [row for row in errors if any(key in row.lower() for key in (
        "deterministic_qa", "consistency", "claim", "unregistered", "numeric",
    ))]
    return {
        "property": "a claim without evidence is blocked",
        "attempt": "add an unevidenced 40 percent savings figure, re-review, then re-validate",
        "held": code != 0 and bool(signals),
        "evidence": [f"re-review exit={reviewed.returncode}", *signals[:3]],
    }


def run_probes(demo: Demo) -> list[dict[str, object]]:
    return [
        probe_gate_field_is_inert(demo),
        probe_freeze_needs_execution(demo),
        probe_downstream_goes_stale(demo),
        probe_reviewer_cannot_self_promote(demo),
        probe_unsupported_claim_is_blocked(demo),
        positive_checks(demo),
    ]


def positive_checks(demo: Demo) -> dict[str, object]:
    """Traceability and AI-usage recording are verified from bytes on disk.

    The digests that exist depend on the resolved preset: ``sprint`` is
    identity-only, so it proves the frozen result names one real receipt and
    that the snapshots the producer itself pinned still match the files.
    """
    frozen = load_json(demo.root / "frozen_results.json")
    receipt_id = str(frozen.get("command", "")).removeprefix("receipt:")
    index = load_json(demo.root / "run_index.json")
    entry = next(
        (row for row in index.get("receipts", []) if row.get("receipt_id") == receipt_id), None,
    )
    receipt_path = demo.root / str(entry["receipt_path"]) if entry else None
    detail: list[str] = [f"frozen_results.command -> {receipt_id}"]
    chain_ok = receipt_path is not None and receipt_path.is_file()
    if chain_ok:
        receipt = load_json(receipt_path)
        chain_ok = receipt.get("exit_code") == 0
        detail.append(f"argv={receipt.get('argv')}")
        detail.append(f"cwd={receipt.get('cwd')} exit={receipt.get('exit_code')}")
    pinned = 0
    for field in ("code_snapshot", "input_snapshot", "model_contract_snapshot", "validation_snapshot"):
        value = frozen.get(field)
        refs = value if isinstance(value, list) else [value]
        for ref in refs:
            if isinstance(ref, dict) and isinstance(ref.get("path"), str) and isinstance(ref.get("sha256"), str):
                target = demo.root / ref["path"]
                if target.is_file() and sha256(target) == ref["sha256"]:
                    pinned += 1
                else:
                    chain_ok = False
                    detail.append(f"digest mismatch: {ref['path']}")
    detail.append(f"{pinned} producer-pinned snapshot digests recomputed")
    manifest = load_json(demo.root / "run_manifest.json")
    records = manifest.get("ai_usage") or []
    statuses = [str(row.get("verification", {}).get("status")) for row in records]
    ai_ok = manifest.get("ai_usage_state") == "used" and bool(records) and set(statuses) == {"verified"}
    return {
        "property": "the final artifact traces to a real execution and the AI call is on record",
        "attempt": "recompute every pinned digest, then read the AI usage ledger",
        "held": chain_ok and ai_ok,
        "evidence": [*detail, f"ai_usage_state={manifest.get('ai_usage_state')} statuses={statuses}"],
    }


def report(demo: Demo, probes: list[dict[str, object]]) -> int:
    print("\nProperty probes (each row is a real attempt, judged by the Harness's own exit code)")
    failures = 0
    for row in probes:
        held = bool(row["held"])
        if not held:
            failures += 1
        print(f"  [{'HELD' if held else 'NOT HELD':>8}] {row['property']}")
        print(f"           attempt: {row['attempt']}")
        for line in row["evidence"]:
            print(f"           {line}")
    print(f"\n  {len(probes) - failures}/{len(probes)} probe outcomes held")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="empty directory for the demo project")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--skip-probes", action="store_true", help="build the chain only")
    args = parser.parse_args(argv)
    root = args.out.resolve()
    if root.exists() and any(root.iterdir()):
        raise SystemExit(f"--out must be absent or empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    demo = Demo(root, verbose=not args.quiet)
    build(demo)
    print("\nstatus snapshot")
    status = demo.harness("status", "--project", str(root), "--json", name="status")
    payload = json.loads(status.stdout or "{}")
    print(f"  first blocked gate: {payload.get('first_blocked_gate')}")
    print(f"  gates: {json.dumps(payload.get('gates'), ensure_ascii=False)}")
    failures = 0
    if not args.skip_probes:
        failures = report(demo, run_probes(demo))
    print(f"\ndemo project kept at: {root}")
    print(
        f"observe the trace: python dashboard/server.py --project {root} --port 8765"
        "  -> http://127.0.0.1:8765/"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
