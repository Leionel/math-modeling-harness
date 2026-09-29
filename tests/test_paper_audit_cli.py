"""Draft diagnostics must see included TeX and stay outside Gate state."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from qa.paper_audit import _pdf_pages, audit_paper  # noqa: E402
from latex.safe_build import tree_hash  # noqa: E402
from _common import sha256_file  # noqa: E402


class PaperAuditCliTest(unittest.TestCase):
    def test_pdf_page_count_includes_blank_pages(self) -> None:
        completed = subprocess.CompletedProcess(["pdftotext"], 0, "first\f\fthird\f", "")
        with patch("qa.paper_audit.shutil.which", return_value="pdftotext"), patch(
            "qa.paper_audit.subprocess.run", return_value=completed,
        ):
            pages, error = _pdf_pages(Path("unused.pdf"))
        self.assertIsNone(error)
        self.assertEqual(pages, ["first", "", "third"])

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="paper-audit-")
        self.project = Path(self.temp.name) / "中文项目"
        (self.project / "paper" / "sections").mkdir(parents=True)
        (self.project / "paper" / "main.tex").write_text(
            "\\input{metadata}\n\\begin{document}\n\\input{sections/body}\n\\end{document}\n",
            encoding="utf-8",
        )
        (self.project / "paper" / "metadata.tex").write_text("\\baominghao{202600000000}\n", encoding="utf-8")
        (self.project / "paper" / "sections" / "body.tex").write_text(
            "\\section{结果}\n正文。\n\\section*{参考文献}\n\\begin{enumerate}\n\\item 来源\n\\end{enumerate}\n",
            encoding="utf-8",
        )
        (self.project / "paper" / "main.log").write_text(
            "Overfull \\hbox (65.5pt too wide) in paragraph at lines 3--4\n", encoding="utf-8",
        )
        (self.project / "plan.json").write_text(json.dumps({"sections": [{"section_id": "conclusion"}]}), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self, *extra: str) -> tuple[int, dict]:
        process = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "harness.py"), "paper", "audit",
             "--project", str(self.project), "--tex", "paper/main.tex", "--json", *extra],
            text=True, encoding="utf-8", capture_output=True, check=False,
        )
        return process.returncode, json.loads(process.stdout)

    def _snapshot(self) -> dict[str, bytes]:
        return {path.relative_to(self.project).as_posix(): path.read_bytes() for path in self.project.rglob("*") if path.is_file()}

    def test_cli_findings_and_clean_draft_leave_project_unchanged(self) -> None:
        before = self._snapshot()
        code, report = self._run("--plan", "plan.json", "--log", "paper/main.log")
        self.assertEqual(code, 1)
        self.assertEqual(report["gate_effect"], "none")
        self.assertEqual(self._snapshot(), before)
        checks = {row["check"]: row for row in report["findings"]}
        self.assertEqual(checks["bibliography_unmapped"]["location"], {"path": "paper/sections/body.tex", "line": 3})
        self.assertIn("missing_conclusion", checks)
        self.assertIn("overfull_boxes", checks)
        self.assertIn("metadata_placeholder", checks)
        self.assertTrue(any(row["check"] == "pdf_layout" for row in report["skipped_checks"]))

        (self.project / "paper" / "metadata.tex").write_text("\\baominghao{123456789012}\n", encoding="utf-8")
        (self.project / "paper" / "sections" / "body.tex").write_text(
            "\\section{结果}\n\\cite{source}\n\\section{结论}\n正文。\n", encoding="utf-8",
        )
        (self.project / "paper" / "main.log").write_text("Build complete.\n", encoding="utf-8")
        code, clean = self._run("--plan", "plan.json", "--log", "paper/main.log")
        self.assertEqual(code, 0)
        self.assertTrue(clean["ok"])
        self.assertEqual(clean["findings"], [])

    def test_cli_rejects_missing_and_project_external_input(self) -> None:
        (self.project / "paper" / "main.tex").write_text("\\input{missing}\n", encoding="utf-8")
        code, report = self._run()
        self.assertEqual(code, 2)
        self.assertIn("missing TeX input", report["errors"][0])
        (self.project / "paper" / "main.tex").write_text("\\input{../../outside}\n", encoding="utf-8")
        code, report = self._run()
        self.assertEqual(code, 2)
        self.assertIn("escapes project root", report["errors"][0])

    def test_nested_crlf_source_and_dynamic_input_fail_closed(self) -> None:
        (self.project / "paper" / "sections" / "body.tex").write_bytes(
            b"\\input{sections/deep}\r\n"
        )
        (self.project / "paper" / "sections" / "deep.tex").write_bytes(
            "\\section{参考文献}\r\n正文。\r\n".encode("utf-8")
        )
        code, report = self._run()
        self.assertEqual(code, 1)
        self.assertEqual(
            next(row["location"] for row in report["findings"] if row["check"] == "bibliography_unmapped"),
            {"path": "paper/sections/deep.tex", "line": 1},
        )
        (self.project / "paper" / "sections" / "body.tex").write_text("\\input\\jobname\n", encoding="utf-8")
        code, report = self._run()
        self.assertEqual(code, 2)
        self.assertIn("dynamic or unbraced TeX input", report["errors"][0])

    def test_pdf_span_uses_rendered_pages_when_available(self) -> None:
        (self.project / "paper" / "main.pdf").write_bytes(b"test-only PDF input")
        with patch("qa.paper_audit._pdf_pages", return_value=(["摘要\n内容", "续文\n关键词：示例"], None)):
            report = audit_paper(self.project, tex="paper/main.tex", pdf="paper/main.pdf")
        self.assertIn("abstract_spans_pages", {row["check"] for row in report["findings"]})
        self.assertEqual(report["pdf_pages"], 2)

    def test_build_binding_requires_matching_entrypoint_tree_and_pdf(self) -> None:
        pdf = self.project / "paper" / "main.pdf"
        pdf.write_bytes(b"test-only PDF input")
        receipt = self.project / "build.json"
        payload = {
            "source_root": "paper", "entrypoint": "main.tex",
            "source_tree_sha256_after": tree_hash(self.project / "paper"),
            "output": {"path": "paper/main.pdf", "sha256": sha256_file(pdf)},
            "source_unchanged": True, "ok": True,
        }
        receipt.write_text(json.dumps(payload), encoding="utf-8")
        with patch("qa.paper_audit._pdf_pages", return_value=(["摘要\n关键词：测试"], None)):
            verified = audit_paper(self.project, tex="paper/main.tex", pdf="paper/main.pdf", build_receipt="build.json")
            self.assertEqual(verified["source_binding"]["status"], "verified")
            payload["entrypoint"] = "other.tex"
            receipt.write_text(json.dumps(payload), encoding="utf-8")
            wrong = audit_paper(self.project, tex="paper/main.tex", pdf="paper/main.pdf", build_receipt="build.json")
            self.assertEqual(wrong["source_binding"]["status"], "unverified")
            payload["entrypoint"] = "main.tex"
            receipt.write_text(json.dumps(payload), encoding="utf-8")
            (self.project / "paper" / "sections" / "body.tex").write_text("changed", encoding="utf-8")
            stale = audit_paper(self.project, tex="paper/main.tex", pdf="paper/main.pdf", build_receipt="build.json")
            self.assertEqual(stale["source_binding"]["status"], "stale")


if __name__ == "__main__":
    unittest.main()
