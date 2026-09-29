#!/usr/bin/env python3
# ruff: noqa: E402
"""Regression and Unit Tests for Math Modeling Skill Enhancements.

Tests:
1. Competition profile inheritance and override resolution.
2. Auto-EDA data profiling, anomaly detection, data contract generation.
3. Bounded reflexion error classification and guardrails against constraint relaxation.
4. Execution runner and timeout diagnosis.
5. Optimization, ODE, Metaheuristics, and Evaluation metrics scaffolds.
6. Publication plot generation and LaTeX figure snippet formatting.
7. MCM/ICM LaTeX project initializer.
8. Problem decomposer and Socratic Assumption Fork assistant.
9. Verification of all Method, Problem, and Failure knowledge cards.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "profiles"))
sys.path.insert(0, str(ROOT / "scripts" / "eda"))
sys.path.insert(0, str(ROOT / "scripts" / "reflexion"))
sys.path.insert(0, str(ROOT / "scripts" / "scaffold"))
sys.path.insert(0, str(ROOT / "scripts" / "figures"))
sys.path.insert(0, str(ROOT / "scripts" / "ideation"))
sys.path.insert(0, str(ROOT / "scripts" / "latex"))

from profile_engine import resolve_profile_chain, validate_profile
from auto_eda import analyze_dataframe, audit_leakage
from profile_generator import generate_data_contract
from error_classifier import ErrorCategory, classify_error, assert_no_constraint_relaxation
from runner import run_bounded_reflexion
from eval_metrics import (
    recompute_constraint_violation,
    compute_relative_improvement,
    calculate_regression_metrics,
    entropy_weight_method,
    topsis_score,
)
from opt_milp import solve_lp_scipy
from ode_system import solve_ode_system, sir_model_deriv
from metaheuristics import run_genetic_algorithm
from publication_plots import plot_bar_comparison, generate_latex_figure_snippet
from check_diagram_spec import audit_diagram_spec
from generate_drawio import write_drawio
from problem_decomposer import decompose_problem


class EnhancementsTest(unittest.TestCase):
    # --- 1. Competition Profile Engine Tests ---

    def test_cumcm_profile_inheritance_and_validation(self) -> None:
        profile = resolve_profile_chain("cumcm", ROOT / "competition_profiles")
        self.assertEqual(profile["competition_family"], "cumcm")
        self.assertEqual(profile["language"], "zh-CN")
        self.assertEqual(profile["rules"]["page_limit"], 30)
        self.assertEqual(profile["rules"]["page_count_scope"], "paper_body")
        self.assertNotIn("deadline", profile)
        self.assertEqual(profile["ai_disclosure"]["format"], "support_material_pdf")
        errors = validate_profile(profile)
        self.assertEqual(errors, [], f"Validation errors: {errors}")

    def test_mcm_icm_profile_inheritance_and_validation(self) -> None:
        profile = resolve_profile_chain("mcm_icm", ROOT / "competition_profiles")
        self.assertEqual(profile["competition_family"], "mcm_icm")
        self.assertEqual(profile["language"], "en-US")
        self.assertTrue(profile["rules"]["max_pages_excludes_ai_report"])
        self.assertEqual(profile["ai_disclosure"]["format"], "in_paper_section")
        errors = validate_profile(profile)
        self.assertEqual(errors, [], f"Validation errors: {errors}")

    def test_apmcm_profile_overrides(self) -> None:
        profile = resolve_profile_chain("apmcm", ROOT / "competition_profiles")
        self.assertEqual(profile["language"], "en-US")
        self.assertEqual(profile["ai_disclosure"]["format"], "in_paper_section")
        self.assertEqual(profile["rules"]["cover_page"], "apmcm_cover")

    # --- 2. Auto-EDA and Data Contract Tests ---

    def test_auto_eda_detection_and_metrics(self) -> None:
        df = pd.DataFrame({
            "id": range(100),
            "date": pd.date_range("2026-01-01", periods=100, freq="D"),
            "temp": np.linspace(10.0, 35.0, 100) + np.random.normal(0, 0.5, 100),
            "cost": np.linspace(100.0, 500.0, 100),
            "category": ["A", "B", "C", "D"] * 25,
            "missing_col": [None] * 40 + list(range(60)),
        })
        eda = analyze_dataframe(df, "test_df")
        self.assertEqual(eda["row_count"], 100)
        self.assertEqual(eda["column_count"], 6)
        self.assertTrue(eda["time_series_info"]["has_time_series"])
        self.assertTrue(any("High missing rate" in " ".join(c["warnings"]) for c in eda["columns"]))

    def test_data_contract_generator(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-eda-") as temp:
            temp_dir = Path(temp)
            csv_path = temp_dir / "sample.csv"
            df = pd.DataFrame({
                "item_id": range(50),
                "demand": np.random.uniform(10, 100, 50),
                "price": np.random.uniform(5, 50, 50),
            })
            df.to_csv(csv_path, index=False)
            contract = generate_data_contract(csv_path, run_id="run-test", target_columns=["demand"])
            self.assertEqual(contract["table"]["row_count"], 50)
            self.assertEqual(contract["table"]["column_count"], 3)
            self.assertEqual(contract["status"], "draft")
            target_cols = [c["name"] for c in contract["columns"] if c["role"] == "target"]
            self.assertIn("demand", target_cols)
            self.assertEqual(contract["leakage_policy"]["status"], "not_run")

    def test_auto_eda_does_not_use_y_as_a_substring_target_heuristic(self) -> None:
        df = pd.DataFrame({"city": ["A", "B", "C"], "quality": [1.0, 2.0, 3.0], "value": [4.0, 5.0, 6.0]})
        eda = analyze_dataframe(df, "substring-check")
        roles = {row["name"]: row["role"] for row in eda["columns"]}
        self.assertNotEqual(roles["city"], "target")
        self.assertNotEqual(roles["quality"], "target")

    def test_leakage_audit_is_conservative_and_detects_exact_copy(self) -> None:
        df = pd.DataFrame({"group": [1, 1, 2], "target": [3.0, 4.0, 5.0], "feature": [8.0, 9.0, 10.0]})
        not_run = audit_leakage(df, ["target"])
        self.assertEqual(not_run["status"], "not_run")
        failed = audit_leakage(
            df.assign(copied_target=df["target"]), ["target"], split_keys=["group"]
        )
        self.assertEqual(failed["status"], "fail")
        self.assertIn("copied_target", failed["forbidden_features"])

    # --- 3. Bounded Reflexion & Error Classifier Tests ---

    def test_error_classifier_code_error(self) -> None:
        diag = classify_error("NameError: name 'x_opt' is not defined", exit_code=1)
        self.assertEqual(diag.category, ErrorCategory.CODE_ERROR)
        self.assertTrue(diag.can_auto_fix)
        self.assertFalse(diag.requires_human_or_m1_review)

    def test_error_classifier_model_infeasible_guardrail(self) -> None:
        diag = classify_error("PulpSolverError: SolverStatus.INFEASIBLE - model has no feasible solution", exit_code=1)
        self.assertEqual(diag.category, ErrorCategory.MODEL_INFEASIBLE)
        self.assertFalse(diag.can_auto_fix)
        self.assertTrue(diag.requires_human_or_m1_review)
        self.assertIn("CRITICAL GUARDRAIL", diag.remediation_advice)

    def test_error_classifier_separates_semantics_and_validation(self) -> None:
        semantic = classify_error("model contract semantic mismatch: target column mismatch", exit_code=1)
        self.assertEqual(semantic.category, ErrorCategory.SEMANTIC_MISMATCH)
        self.assertTrue(semantic.requires_human_or_m1_review)
        validation = classify_error("independent objective recomputation failed", exit_code=1)
        self.assertEqual(validation.category, ErrorCategory.VALIDATION_FAIL)
        self.assertFalse(validation.can_auto_fix)

    def test_bounded_reflexion_needs_explicit_repair_callback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-reflexion-") as temp:
            script = Path(temp) / "fail.py"
            script.write_text("raise NameError('broken')\n", encoding="utf-8")
            blocked = run_bounded_reflexion(script, max_rounds=3)
            self.assertEqual(blocked["termination"], "blocked_for_explicit_repair_callback")
            self.assertEqual(len(blocked["rounds"]), 1)

    def test_constraint_relaxation_guardrail(self) -> None:
        orig = ["x + y <= 10", "x >= 0", "y >= 0", "demand_met: sum(x) >= 50"]
        # Unauthorized removal of constraint
        relaxed = ["x + y <= 10", "x >= 0", "y >= 0"]
        self.assertFalse(assert_no_constraint_relaxation(orig, relaxed))

        # Valid modification adding an extra bound
        tightened = ["x + y <= 10", "x >= 0", "y >= 0", "demand_met: sum(x) >= 50", "x <= 8"]
        self.assertTrue(assert_no_constraint_relaxation(orig, tightened))

    # --- 4. Algorithmic Scaffolds and Metrics Tests ---

    def test_milp_solver_scipy(self) -> None:
        # Maximize z = 3x1 + 2x2 s.t. x1 + x2 <= 4, x1 - x2 <= 2, x1,x2 >= 0
        res = solve_lp_scipy(
            c=[3.0, 2.0],
            A_ub=[[1.0, 1.0], [1.0, -1.0]],
            b_ub=[4.0, 2.0],
            bounds=[(0, None), (0, None)],
            maximize=True,
        )
        self.assertTrue(res["success"])
        self.assertAlmostEqual(res["objective_value"], 11.0, places=4)
        self.assertAlmostEqual(res["variables"][0], 3.0, places=4)
        self.assertAlmostEqual(res["variables"][1], 1.0, places=4)

    def test_ode_sir_simulation(self) -> None:
        t_eval = np.linspace(0, 30, 31)
        res = solve_ode_system(
            deriv_fn=sir_model_deriv,
            t_span=(0, 30),
            y0=[990, 10, 0],
            t_eval=t_eval,
            params=(0.3, 0.1),
        )
        self.assertTrue(res["success"])
        self.assertEqual(len(res["t"]), 31)
        # Conservation of total population N = S + I + R
        for t_idx in range(len(res["t"])):
            total_n = sum(res["y"][state_idx][t_idx] for state_idx in range(3))
            self.assertAlmostEqual(total_n, 1000.0, places=2)

    def test_metaheuristics_ga(self) -> None:
        res = run_genetic_algorithm(
            fitness_fn=lambda x: float(np.sum(x ** 2)),
            bounds=[(-5.0, 5.0)] * 3,
            pop_size=30,
            generations=30,
            seed=42,
        )
        self.assertTrue(res["success"])
        self.assertLess(res["best_fitness"], 0.2)

    def test_eval_metrics_recomputation(self) -> None:
        # Constraint violation
        viol = recompute_constraint_violation(
            lhs_values=[12.0, 5.0, 3.0],
            rhs_values=[10.0, 5.0, 4.0],
            operators=["<=", "==", ">="],
        )
        self.assertEqual(viol["max_violation"], 2.0)
        self.assertEqual(viol["violation_count"], 2)

        # Improvement
        imp = compute_relative_improvement(baseline_val=100.0, optimized_val=85.0, minimize=True)
        self.assertAlmostEqual(imp, 15.0, places=2)

        # Regression metrics
        reg = calculate_regression_metrics(y_true=[10.0, 20.0, 30.0], y_pred=[11.0, 19.0, 31.0])
        self.assertAlmostEqual(reg["mae"], 1.0, places=2)
        self.assertAlmostEqual(reg["rmse"], 1.0, places=2)

        # TOPSIS
        decision_matrix = np.array([
            [8.0, 7.0, 9.0],
            [5.0, 9.0, 6.0],
            [9.0, 6.0, 8.0],
        ])
        weights = entropy_weight_method(decision_matrix)
        self.assertEqual(len(weights), 3)
        self.assertAlmostEqual(float(np.sum(weights)), 1.0, places=4)

        scores = topsis_score(decision_matrix, weights=weights)
        self.assertEqual(len(scores), 3)
        self.assertTrue(all(0.0 <= s <= 1.0 for s in scores))

    # --- 5. Publication Visualization Tests ---

    def test_publication_plot_and_latex_snippet(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-fig-") as temp:
            out_pdf = Path(temp) / "test_fig.pdf"
            plot_bar_comparison(
                categories=["Cat1", "Cat2"],
                values_dict={"Model A": [10.0, 20.0], "Model B": [12.0, 18.0]},
                title="Test Plot",
                xlabel="Category",
                ylabel="Metric Value",
                output_path=out_pdf,
            )
            self.assertTrue(out_pdf.exists())
            self.assertGreater(out_pdf.stat().st_size, 0)

            snippet = generate_latex_figure_snippet(
                relative_fig_path="figures/test_fig.pdf",
                caption_title="Comparison Test",
                message="Model B achieves lower error than Model A in Category 2.",
                label="comp-test",
            )
            self.assertIn("\\begin{figure}", snippet)
            self.assertIn("\\label{fig:comp-test}", snippet)

    def test_editable_diagram_spec_supports_vector_and_raster_delivery(self) -> None:
        with tempfile.TemporaryDirectory(prefix="math-diagram-spec-") as temp:
            project = Path(temp)
            (project / "diagram.svg").write_text("<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>", encoding="utf-8")
            spec = {
                "schema_version": "1.0", "diagram_id": "FIG-01", "kind": "overview",
                "message": "The modeling pipeline links data, model, validation, and result.",
                "layout": "left_to_right", "style_profile": "academic-minimal",
                "source_format": "drawio", "source_artifact": "diagram.drawio",
                "delivery_mode": "vector_preferred", "output_formats": ["svg"],
                "rendered_artifacts": ["diagram.svg"], "text_policy": "native_text",
                "source_editability": "editable_source", "human_review_required": True,
                "status": "reviewed",
                "nodes": [
                    {"node_id": "input", "label": "Input data", "role": "input", "source_refs": ["problem"], "emphasis": "core"},
                    {"node_id": "model", "label": "Model", "role": "model", "source_refs": ["M1"], "emphasis": "core"},
                    {"node_id": "result", "label": "Validated result", "role": "result", "source_refs": ["R1"], "emphasis": "core"},
                ],
                "edges": [
                    {"edge_id": "e1", "from": "input", "to": "model", "relation": "data", "source_refs": ["problem"]},
                    {"edge_id": "e2", "from": "model", "to": "result", "relation": "data", "source_refs": ["R1"]},
                ],
            }
            write_drawio(spec, project / "diagram.drawio")
            report = audit_diagram_spec(spec, root=project, strict=True, require_reviewed=True)
            self.assertTrue(report["ok"], report)
            spec["delivery_mode"] = "raster_only"
            spec["output_formats"] = ["png"]
            spec["rendered_artifacts"] = ["diagram.png"]
            spec["text_policy"] = "raster_text"
            spec["raster_dpi"] = 600
            (project / "diagram.png").write_bytes(b"preview")
            report = audit_diagram_spec(spec, root=project, strict=True, require_reviewed=True)
            self.assertTrue(report["ok"], report)
            spec["raster_dpi"] = 150
            report = audit_diagram_spec(spec, root=project, strict=True, require_reviewed=True)
            self.assertFalse(report["ok"])
            self.assertTrue(any("raster_dpi" in error for error in report["errors"]))

    # --- 6. Problem Decomposer & Assumption Fork Tests ---

    def test_problem_decomposer_and_assumption_forks(self) -> None:
        sample_problem = (
            "某园区建立多能互补系统。问题 1：预测未来负荷与光伏出力；"
            "问题 2：考虑新能源消纳比例与储能调度，在满足负荷需求的前提下最小化总运行成本；"
            "问题 3：评估不同电价政策对系统鲁棒性的影响。"
        )
        res = decompose_problem(sample_problem, contest_name="CUMCM 2026")
        self.assertEqual(res["total_subproblems"], 3)
        self.assertEqual(res["subproblems"][0]["question_id"], "q1")
        self.assertIn("time_series", res["subproblems"][0]["detected_patterns"])
        self.assertEqual(res["subproblems"][1]["question_id"], "q2")
        self.assertEqual(res["subproblems"][1]["display_question_id"], "Q2")
        self.assertEqual(res["subproblems"][1]["model_selection"]["status"], "pending_research_and_comparison")
        self.assertIn("optimization", res["subproblems"][1]["detected_patterns"])
        self.assertTrue(len(res["subproblems"][1]["assumption_forks"]) > 0)
        self.assertEqual(res["subproblems"][1]["assumption_forks"][0]["phrase"], "消纳")
        self.assertIn("checks", res["subproblems"][1]["assumption_forks"][0])
        self.assertNotIn("selected", res["subproblems"][1]["assumption_forks"][0])

    # --- 7. Knowledge Cards Completeness & Structure Check ---

    def test_knowledge_cards_presence_and_structure(self) -> None:
        methods_dir = ROOT / "references" / "cards" / "methods"
        problems_dir = ROOT / "references" / "cards" / "problems"
        failures_dir = ROOT / "references" / "cards" / "failures"

        self.assertTrue(methods_dir.is_dir())
        self.assertTrue(problems_dir.is_dir())
        self.assertTrue(failures_dir.is_dir())

        method_cards = list(methods_dir.glob("*.md"))
        problem_cards = list(problems_dir.glob("*.md"))
        failure_cards = list(failures_dir.glob("*.md"))

        # We must have extensive card coverage
        self.assertGreaterEqual(len(method_cards), 8, f"Found {len(method_cards)} method cards")
        self.assertGreaterEqual(len(problem_cards), 6, f"Found {len(problem_cards)} problem cards")
        self.assertGreaterEqual(len(failure_cards), 7, f"Found {len(failure_cards)} failure cards")

        # Each method card must have essential sections
        for mc in method_cards:
            text = mc.read_text(encoding="utf-8")
            self.assertIn("## 1. 解决什么问题", text, f"Missing section in {mc.name}")
            self.assertIn("## 4. 核心数学结构", text, f"Missing section in {mc.name}")
            self.assertIn("## 7. 必须验证的东西", text, f"Missing section in {mc.name}")


if __name__ == "__main__":
    unittest.main()
