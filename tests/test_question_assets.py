"""Named figure HTTP previews and prompt handoff remain read-only evidence views."""

import json
import os
import sys
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from views.question_assets import figure_catalog  # noqa: E402
from tests import test_dashboard as dashboard  # noqa: E402
from tests.test_illustration_execution import BRIEF  # noqa: E402


class QuestionAssetsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        roots = patch.dict(os.environ, {"MATH_HARNESS_ALLOWED_ROOTS": ""})
        roots.start()
        cls.addClassCleanup(roots.stop)
        dashboard.DashboardTest.setUpClass.__func__(cls)

    tearDownClass = classmethod(dashboard.DashboardTest.tearDownClass.__func__)
    get = dashboard.DashboardTest.get

    def setUp(self):
        dashboard.DashboardTest.setUp(self)
        manifest_path = self.project / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.manifest_before = manifest_path.read_bytes()
        self.addCleanup(manifest_path.write_bytes, self.manifest_before)
        manifest["roots"]["paper_plan"] = {"path": "atlas_plan.json"}
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        plan = {
            "run_id": manifest["run_id"],
            "claims": [{"claim_id": "C2", "question_id": "q2"}],
            "argument_units": [
                {"claim_ids": ["C2"], "scope": {"question_ids": ["q2", "q3"]}}
            ],
            "figures": [
                {
                    "figure_id": "FIG-MECH",
                    "kind": "illustration",
                    "claim_ids": ["C2"],
                    "data_artifacts": ["atlas.png"],
                    "message": "test mechanism",
                },
                {
                    "figure_id": "FIG-DATA",
                    "kind": "data",
                    "claim_ids": ["C2"],
                    "data_artifacts": ["missing.png"],
                },
            ],
        }
        self.plan = self.project / "atlas_plan.json"
        self.plan.write_text(json.dumps(plan), encoding="utf-8")
        self.addCleanup(self.plan.unlink)
        self.image = self.project / "atlas.png"
        self.image.write_bytes(b"test preview bytes")
        self.addCleanup(self.image.unlink)
        self.brief = self.project / "figures/FIG-MECH/brief.md"
        self.brief.parent.mkdir(parents=True, exist_ok=True)
        self.brief.write_text(BRIEF, encoding="utf-8")
        self.addCleanup(
            lambda: self.brief.parent.rmdir() if self.brief.parent.is_dir() else None
        )
        self.addCleanup(self.brief.unlink)

    def test_question_links_are_explicit_and_data_has_no_generation_prompt(self):
        figures = figure_catalog(self.project)
        illustration = next(f for f in figures if f["figure_id"] == "FIG-MECH")
        self.assertEqual(illustration["question_ids"], ["q2", "q3"])
        self.assertIn("Required elements: two regions", illustration["prompt"])
        self.assertEqual(illustration["prompt_state"], "brief_draft")
        self.assertEqual(
            next(f for f in figures if f["figure_id"] == "FIG-DATA")["prompt"], None
        )
        self.assertFalse(illustration["previews"][0]["registered"])

    def test_preview_uses_figure_identity_not_arbitrary_paths(self):
        status, content = self.get("/api/figure?id=FIG-MECH&file=0")
        self.assertEqual(status, 200)
        self.assertEqual(content, b"test preview bytes")
        for query in ["id=../../secret", "id=FIG-MECH&file=-1", "id=FIG-DATA&file=0"]:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.get("/api/figure?" + query)
            self.assertEqual(error.exception.code, 404)
            error.exception.close()
        plan = json.loads(self.plan.read_text(encoding="utf-8"))
        plan["figures"][0]["data_artifacts"] = ["../outside.png"]
        self.plan.write_text(json.dumps(plan), encoding="utf-8")
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.get("/api/figure?id=FIG-MECH")
        self.assertEqual(error.exception.code, 403)
        error.exception.close()

    def test_changed_brief_exposes_current_draft_not_old_request_prompt(self):
        original = figure_catalog(self.project)[0]["prompt"]
        request = (
            self.project
            / ".harness/views/figures/FIG-MECH_image_generation_request.json"
        )
        request.parent.mkdir(parents=True, exist_ok=True)
        request.write_text(
            json.dumps({"figure_id": "FIG-MECH", "prompt": original}), encoding="utf-8"
        )
        self.addCleanup(request.unlink)
        self.brief.write_text(
            BRIEF.replace("load shifts to cheap regions", "only the declared flow"),
            encoding="utf-8",
        )
        figure = figure_catalog(self.project)[0]
        self.assertEqual(figure["prompt_state"], "request_stale")
        self.assertIn("only the declared flow", figure["prompt"])
        self.assertNotEqual(figure["prompt"], original)

    def test_incomplete_brief_generates_no_prompt(self):
        self.brief.write_text("# empty brief", encoding="utf-8")
        figure = figure_catalog(self.project)[0]
        self.assertIsNone(figure["prompt"])
        self.assertEqual(figure["prompt_state"], "incomplete_brief")

    def test_figure_reads_never_mutate_the_project(self):
        before = dashboard._tree_digest(self.project)
        self.get("/api/figure?id=FIG-MECH")
        figure_catalog(self.project)
        self.assertEqual(dashboard._tree_digest(self.project), before)

    def test_svg_is_an_attachment_not_an_active_inline_preview(self):
        svg = self.project / "atlas.svg"
        svg.write_text("<svg><script>alert(1)</script></svg>", encoding="utf-8")
        self.addCleanup(svg.unlink)
        plan = json.loads(self.plan.read_text(encoding="utf-8"))
        plan["figures"][0]["data_artifacts"] = [svg.name]
        self.plan.write_text(json.dumps(plan), encoding="utf-8")
        with urllib.request.urlopen(
            self.base + "/api/figure?id=FIG-MECH", timeout=20
        ) as response:
            self.assertEqual(response.headers["Content-Disposition"], "attachment")
            self.assertEqual(
                response.headers["Content-Type"], "application/octet-stream"
            )
