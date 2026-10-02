"""Dashboard console tests.

Two properties matter more than the rendering: the console must show what the
Harness recomputes (not what a manifest claims), and it must have no write path.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "dashboard"))

import server as console  # noqa: E402


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


class DashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(prefix="dashboard-")
        cls.project = Path(cls.temp.name) / "proj"
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "harness.py"), "init",
             "--project", str(cls.project), "--competition", "cumcm", "--preset", "sprint", "--json"],
            text=True, capture_output=True, encoding="utf-8", errors="replace", check=False,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def setUp(self) -> None:
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), console.Handler)
        console.Handler.root = self.project.resolve()
        thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.httpd.shutdown(), self.httpd.server_close()))
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def get(self, path: str) -> tuple[int, bytes]:
        with urllib.request.urlopen(self.base + path, timeout=20) as response:
            return response.status, response.read()

    def test_snapshot_is_recomputed_and_names_its_sources(self) -> None:
        snapshot = console.snapshot(self.project)
        self.assertTrue(snapshot["read_only"])
        self.assertEqual(snapshot["gate_status"], "BLOCKED")
        states = {row["gate"]: row["state"] for row in snapshot["gates"]}
        self.assertEqual(states["M1"], "blocked")
        # S0 and F1 are boundary stages, not recomputable Gates: they must not
        # be rendered as if a Gate were pending.
        self.assertEqual(states["S0"], "boundary")
        self.assertEqual(states["F1"], "boundary")
        self.assertTrue(any("mcp:" in source for source in snapshot["sources"]))
        self.assertTrue(snapshot["blockers"])
        self.assertTrue(all(row.get("next_action") for row in snapshot["blockers"]))

    def test_api_serves_the_snapshot_and_index(self) -> None:
        code, body = self.get("/api/snapshot")
        self.assertEqual(code, 200)
        payload = json.loads(body)
        self.assertEqual(payload["project_root"], str(self.project.resolve()))
        self.assertEqual(len(payload["gates"]), 8)
        status, page = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Harness Console", page)
        self.assertIn(b"/api/snapshot", page)

    def test_status_failure_makes_all_gate_states_unknown(self) -> None:
        def tool(root, name, **kwargs):
            return {"gate_status": "ERROR", "errors": ["bad manifest"], "status_exit_code": 2} if name == "get_run_state" else {"artifacts": []}
        with patch.object(console, "_tool", side_effect=tool):
            payload = json.loads(self.get("/api/snapshot")[1])
        self.assertEqual(payload["status_errors"], ["bad manifest"])
        self.assertTrue(all(row["state"] == "unknown" for row in payload["gates"]))

    def test_artifact_download_uses_registered_identity_and_actual_bytes(self) -> None:
        path = self.project / "preview.png"
        path.write_bytes(b"actual artifact bytes")
        self.addCleanup(path.unlink)
        with patch.object(console, "_tool", return_value={"artifacts": [{"artifact_id": "FIG 1", "path": "preview.png"}]}):
            with urllib.request.urlopen(self.base + "/api/artifact?id=FIG%201", timeout=20) as response:
                self.assertEqual(response.read(), b"actual artifact bytes")
                self.assertEqual(response.headers["Content-Type"], "image/png")
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            with urllib.request.urlopen(self.base + "/api/artifact?id=FIG%201&download=1", timeout=20) as response:
                self.assertEqual(response.headers["Content-Disposition"], "attachment")

    def test_artifact_route_rejects_unregistered_missing_and_escaping_files(self) -> None:
        for nodes, wanted, expected in [
            ([], "anything", 404),
            ([{"artifact_id": "missing", "path": "absent.pdf"}], "missing", 404),
            ([{"artifact_id": "escape", "path": "../outside.pdf"}], "escape", 403),
        ]:
            with self.subTest(wanted=wanted), patch.object(console, "_tool", return_value={"artifacts": nodes}):
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    self.get("/api/artifact?id=" + wanted)
                self.assertEqual(raised.exception.code, expected)

    def test_active_content_is_downloaded_instead_of_rendered(self) -> None:
        path = self.project / "unsafe.html"
        path.write_text("<script>alert(1)</script>", encoding="utf-8")
        self.addCleanup(path.unlink)
        with patch.object(console, "_tool", return_value={"artifacts": [{"artifact_id": "page", "path": "unsafe.html"}]}):
            with urllib.request.urlopen(self.base + "/api/artifact?id=page", timeout=20) as response:
                self.assertEqual(response.headers["Content-Type"], "application/octet-stream")
                self.assertEqual(response.headers["Content-Disposition"], "attachment")

    def test_author_source_is_readable_by_named_identity_only(self) -> None:
        source = self.project / ".harness/authoring/model_contract.yaml"
        payload = json.loads(self.get("/api/source?id=authoring%3Amodel_contract")[1])
        self.assertEqual(payload["text"], source.read_bytes().decode("utf-8"))
        self.assertEqual(payload["kind"], "authoring")
        for identifier, expected in [("../../secret", 404), ("escape", 403)]:
            rows = [{"source_id": "escape", "path": "../outside.txt", "kind": "log", "freshness": "unknown"}]
            with self.subTest(identifier=identifier), patch("workflow_sources.source_catalog", return_value=rows):
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    self.get("/api/source?id=" + identifier)
                self.assertEqual(raised.exception.code, expected)
                raised.exception.close()

    def test_serving_never_mutates_the_project(self) -> None:
        before = _tree_digest(self.project)
        self.get("/api/snapshot")
        self.get("/")
        artifact_id = json.loads(self.get("/api/snapshot")[1])["artifacts"][0]["artifact_id"]
        console.snapshot(self.project)
        self.assertIsNotNone(artifact_id)
        self.assertEqual(_tree_digest(self.project), before, "the console wrote to the project")

    def test_post_is_refused_with_the_producer_command_instead(self) -> None:
        request = urllib.request.Request(self.base + "/api/approve", data=b"{}", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=20)
        self.assertEqual(raised.exception.code, 405)
        body = json.loads(raised.exception.read())
        self.assertIn("read-only", body["error"])
        self.assertIn("harness check", body["instead"])

    def test_snapshot_surfaces_the_declared_mode_and_who_recorded_a_checkpoint(self) -> None:
        manifest_path = console.resolve_control_path(self.project, "run_manifest.json")
        original = manifest_path.read_bytes()
        self.addCleanup(manifest_path.write_bytes, original)
        manifest = json.loads(original.decode("utf-8"))
        control = manifest.setdefault("control", {})
        control["operator_mode"] = "auto"
        control["operator_mode_history"] = [
            {"mode": "auto", "set_by": "shengxin", "set_at": "2026-09-19T00:00:00+00:00"},
        ]
        manifest["human_checkpoints"] = [{
            "checkpoint_id": "CHK-M1-001", "stage": "m1", "decision": "pass",
            "actor_class": "agent", "decided_by": "orchestrator",
        }]
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

        snapshot = console.snapshot(self.project)
        self.assertEqual(snapshot["operator_mode"], "auto")
        self.assertEqual([row["kind"] for row in snapshot["timeline"]], ["mode"])
        m1 = next(row for row in snapshot["gates"] if row["gate"] == "M1")
        self.assertEqual(m1["checkpoint_actor"], "agent")
        self.assertEqual(m1["checkpoint_by"], "orchestrator")

    def test_unknown_route_is_a_404_not_a_stack_trace(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.get("/api/evaluations")
        self.assertEqual(raised.exception.code, 404)

    def test_serve_refuses_a_project_outside_the_allowlist(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "dashboard" / "server.py"), "--project", str(self.project), "--port", "0"],
            text=True, capture_output=True, encoding="utf-8", errors="replace", check=False,
            env={**os.environ, "DASHBOARD_ALLOWED_ROOTS": str(Path(self.temp.name) / "elsewhere")},
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("refusing to serve", result.stderr)


if __name__ == "__main__":
    unittest.main()
