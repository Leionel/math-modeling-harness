# Read-only modeling workspace

The dashboard organizes existing Harness evidence into current work, execution
records and deliverables. It uses no framework, bundler or frontend dependency.

```powershell
python dashboard/server.py --project '<PROJECT_ROOT>' --port 8765
```

## Layout and tasks

The left navigation contains Overview, Problem & models, Runs & reviews,
Paper & figures, Deliverables and Environment & sources. The central column
shows the selected task; the inspector shows diagnostics, full receipt/review
records, or an artifact's producer, receipt, lifecycle, freshness and dependencies.
Dependencies can be selected to inspect their actual registered records.

Overview prioritizes the first blocked Gate. Later pending human checkpoints
remain visible separately, without suggesting they should be approved now.
The six recomputable Gates have human-readable stage labels. S0/F1 remain
boundary entries in the machine snapshot; neither is counted as a checked Gate.
Copied check commands include the actual project root and use PowerShell literal
quoting. Diagnostic messages remain the exact Harness output, in either language.

Deliverables filters registered artifacts into paper, figures, code/evidence and
submission materials; it also supports path/role/id search. These are display
categories, not new artifact roles or verdicts. Counts mean **registered**, not
generated, validated or frozen. The inspector shows lifecycle and freshness
separately. A current seed profile is not a verified competition rule set.

## Read path and error handling

```text
GET /                         static UI
GET /api/snapshot             recomputed MCP state + artifact list + recorded trace
GET /api/artifact?id=ID        actual registered in-root artifact bytes
GET /api/artifact?id=ID&download=1   attachment
POST /*                       405
```

State comes from `get_run_state`; artifact identity and freshness come from
`list_artifacts`. Trace records come from the run index, receipts, reviews and
manifest. The snapshot names these sources. ERROR, legacy or unavailable state
makes all Gate cells unknown. A failed HTTP refresh shows an error and explicitly
labels the retained snapshot as previous data. No failed fetch can imply READY.

Only a registered artifact id can select a file. The server resolves the path
and checks project-root containment, including symlink resolution, at request
time. Unregistered and missing files return 404; escaping files return 403.
PDF and raster images may be previewed; HTML, SVG and other types download as
octet-stream with nosniff and sandbox headers. The page loads previews only when
requested and reports missing-file errors. It does not execute project code.

`MATH_HARNESS_ALLOWED_ROOTS` constrains MCP access. If absent, the dashboard
narrows it to the explicit served project. `DASHBOARD_ALLOWED_ROOTS`, when set,
adds a startup allowlist. The default bind address is loopback.

## Visual and interaction rules

Neutral white surfaces, blue actions, sans-serif Chinese text, mono paths and
subtle borders replace the previous graph-paper layout. Dark, light and system
themes and Chinese/English preferences persist in localStorage. Keyboard focus
is visible; small screens stack the inspector below the work area. Navigation
scrolls horizontally on narrow screens. No decorative animation is required.

Polling runs every ten seconds, pausing while an item is selected to preserve
reading/preview state. Manual refresh is always available; Pause only stops
automatic refresh. These controls do not write project state.

## Truth boundaries and remaining work

There is no approve, freeze or execution button. Auto is an operator authorization
declaration, not proof that a background executor is running. Human checkpoint
actor identity remains self-declared; see `THREAT_MODEL.md`.

Question-level deliverable summaries require explicit problem/model/validation/
paper links. This iteration does not guess these from filenames or create new
claim evidence. Unregistered PDFs or figures are intentionally absent. Artifact
freshness alone proves neither mathematical correctness nor acceptance. Browser
automation is not an unfamiliar-user usability study.

## Verification

`python -m unittest tests.test_dashboard tests.test_state_projection -q` verifies
status error projection, real HTTP outcomes, file containment, active content
handling and read-only snapshots. `tests/dashboard_browser.cjs` is an optional
Playwright regression against a disposable initialized project:

```text
node tests/dashboard_browser.cjs http://127.0.0.1:8765 <SCREENSHOT_DIRECTORY>
```

Make Playwright available through NODE_PATH; `PLAYWRIGHT_CHANNEL=msedge` selects
an installed Edge browser. It covers navigation, inspector, search, filters,
clipboard, theme/language cycles, pause, narrow-screen overflow, connection
failure and status ERROR. Synthetic failures are test inputs, never project
evidence. Screenshots need separate visual inspection.
