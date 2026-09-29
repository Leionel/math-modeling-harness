"""A fresh reviewer sees and remains bound to included TeX source."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _common import sha256_file  # noqa: E402
from qa.review_evidence import review_freshness, validate_bundle_boundary  # noqa: E402
from qa.run_review import build_bundle  # noqa: E402


class ReviewTexSourceTest(unittest.TestCase):
    def test_style_checker_reads_included_body(self) -> None:
        with tempfile.TemporaryDirectory(prefix="style-tex-") as temp:
            root = Path(temp)
            (root / "paper" / "sections").mkdir(parents=True)
            (root / "paper" / "main.tex").write_text("\\input{sections/body}\n", encoding="utf-8")
            (root / "paper" / "sections" / "body.tex").write_text("这是最优方案。\n", encoding="utf-8")
            (root / "plan.json").write_text('{"claims": []}\n', encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "qa" / "check_paper_style.py"),
                 "--project-root", str(root), "--paper-plan", "plan.json", "--draft", "paper/main.tex"],
                text=True, encoding="utf-8", capture_output=True, check=False,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            self.assertEqual(result.returncode, 1)
            self.assertTrue(any("最优" in error for error in json.loads(result.stdout)["errors"]))

    def test_child_tex_is_visible_and_its_change_stales_the_review(self) -> None:
        with tempfile.TemporaryDirectory(prefix="review-tex-") as temp:
            root = Path(temp)
            (root / "paper" / "sections").mkdir(parents=True)
            main = root / "paper" / "main.tex"
            child = root / "paper" / "sections" / "body.tex"
            main.write_text("\\input{sections/body}\n", encoding="utf-8")
            child.write_text("\\section{结果} 错误的最优结论。\n", encoding="utf-8")
            roles = {
                "paper": main,
                "model_contract": root / "model.json",
                "frozen_results": root / "frozen.json",
                "evidence_registry": root / "evidence.json",
            }
            for role, path in roles.items():
                if role != "paper":
                    path.write_text("{}\n", encoding="utf-8")
            nodes = [
                {"artifact_id": role, "role": role, "path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}
                for role, path in roles.items()
            ]
            (root / "artifact_dag.json").write_text(json.dumps({"nodes": nodes}), encoding="utf-8")

            def entries(_state: object, role: str) -> list[tuple[dict, Path]]:
                return [(next(row for row in nodes if row["role"] == role), roles[role])] if role in roles else []

            with (
                patch("qa.run_review._v2_dag_nodes", return_value=nodes),
                patch("qa.run_review._v2_role_entries", side_effect=entries),
                patch("qa.run_review._judge_scan_structural", return_value=None),
            ):
                bundle_path, bundle = build_bundle(SimpleNamespace(run_id="run-1"), root, "20260925T000000Z", ["semantic_critic"])
            context = next(row for row in bundle["files"] if row["role"] == "paper_source_context")
            self.assertIn("错误的最优结论", (bundle_path.parent / context["path"]).read_text(encoding="utf-8"))
            self.assertIsNone(context["artifact_id"])
            self.assertEqual(len(bundle["source_dependencies"]), 2)
            self.assertFalse(validate_bundle_boundary({"bundle_ref": {"path": bundle_path.relative_to(root).as_posix(), "sha256": sha256_file(bundle_path)}}, root))

            report = {
                "perspective": "semantic_critic",
                "bundle_ref": {"path": bundle_path.relative_to(root).as_posix(), "sha256": sha256_file(bundle_path)},
                "reviewed_artifacts": [
                    {"artifact_id": role, "role": role, "path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}
                    for role, path in roles.items()
                ],
            }
            self.assertEqual(review_freshness(report, root), ("current", []))
            child.write_text("\\section{结果} 更改后的结论。\n", encoding="utf-8")
            freshness, errors = review_freshness(report, root)
            self.assertEqual(freshness, "stale")
            self.assertTrue(any("paper/sections/body.tex" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
