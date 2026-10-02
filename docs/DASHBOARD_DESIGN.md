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
GET /api/source?id=SOURCE_ID   bounded named author source, log or reviewed version
GET /api/artifact?id=ID        actual registered in-root artifact bytes
GET /api/artifact?id=ID&download=1   attachment
POST /*                       405
```

## Action and question workflow

Diagnostics retain their exact text and add a Chinese corrective explanation.
An explicit contract role identifies its authoring source; no field pointer is
guessed. The inspector copies complete PowerShell/bash recheck commands or a
producer compile command. Producers run through the existing CLI; the browser
does not approve, edit, compile or execute a project.

The named source catalog includes authoring YAML, reasoning Markdown, statically
included TeX, receipt stdout/stderr and reviewed artifact references. Paths must
resolve inside the project. Previews redact sensitive text and read at most
128 KiB; logs show their tail. Reviewed bytes are shown only when their recorded
digest matches. Missing historical bytes are reported, not reconstructed from
the current file. Binary sources retain version metadata and use the artifact
preview where registered. Source catalog errors appear as errors in the page.

The question workbench is the same read-only projection as `harness questions`.
It joins explicit question/model/claim/argument-unit ids; filenames never supply
missing links. It separates executed outputs, recomputed validation obligations,
registered frozen results and bound writer claims. Changed model sources or
measurement bindings invalidate displayed validation. A current writer package
is evidence availability, not Gate approval or mathematical/writing quality.
TeX locators report missing, unique or ambiguous source-file/line matches;
source/PDF binding comes from the existing paper audit, without inferred PDF pages.

Run `tests/dashboard_workflow_browser.cjs` against a retained public tutorial
project for source/log/question interaction checks. The existing
`tests/dashboard_browser.cjs` covers navigation, themes, errors and artifact search
against a freshly initialized disposable project. Screenshots belong outside
the repository; they are UI verification, not competition evidence.

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
claim evidence. The artifact ledger lists registered evidence; the question atlas
also previews explicit paper-plan references, labelled as unregistered. Artifact
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

## Question outcomes atlas

The Question outcomes page starts with a question switch and three views: figures,
results and validation. The sidebar uses a slate-blue surface; the content area
uses spacious white cards, a result table and a two-column figure gallery. Themes,
keyboard focus and narrow-screen layouts remain available.

Figure membership comes from `paper_plan.json` figure claim IDs and claim question
IDs, including explicit argument-unit scopes. A brief without those links appears
under Unlinked; filenames never establish question membership. Select a figure to
open its brief, inspect its provenance, download it or preview an actual raster/PDF.
SVG is download-only. `/api/figure?id=<FIGURE_ID>&file=<INDEX>` serves only named,
contained project files from this catalog, never arbitrary paths.

Result rows show actual receipt-bound JSON values (including zero), units,
statistical definitions, boundaries and sources. Modified/unbound result files
lose their displayed values. Model-source changes mark historical outputs.
Exploratory results and writer-package references have separate labels; neither
the table nor a thumbnail grants paper eligibility or a Gate PASS.

For an illustration with a complete brief, the inspector displays and copies the
full prompt produced by the existing illustration producer. Changed briefs are
labelled as drafts/stale requests. Data figures must be plotted from data and do
not receive image-generation prompts. The expandable handoff shows full request
and collection commands. Only after confirming contest AI policy and actual tool
availability should the user record a request, generate externally, save the image
and collect it. Collection still requires disclosure and the existing scientific,
visual and final-size reviews. The dashboard itself never generates or approves.

Reproduce the UI fixture and start a local preview (the fixture prints its root):

```powershell
python tests/_dashboard_atlas_fixture.py
python dashboard/server.py --project '<printed project root>' --port 8771
```

`tests/dashboard_atlas_browser.cjs` covers actual numerical output, question and
view filters, real image previews, full prompt clipboard content, data-figure
routing, dark theme and mobile overflow. This is a disposable teaching fixture,
not evidence of a completed competition project.
