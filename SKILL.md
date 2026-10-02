---
name: math-modeling-skill-sion
description: 面向 CUMCM、MCM/ICM、APMCM 等数学建模竞赛的证据与合规 Harness。用于新建或迁移比赛项目、题意与模型选型、数据/验证合同、真实运行、结果冻结、证据追溯、技术写作、确定性 QA、提交检查与不可变交付；也覆盖论文科研示意图/机制图/场景图/概念图的原生 image generation 执行与回收。普通数学题且不涉及竞赛交付链时不要使用。
---

# Math Modeling Evidence Harness

## Trigger and scope

Use this skill when a user asks to build, audit, migrate, run, validate, write,
or submit a mathematical-modeling competition project. Start from the project
root and use the thin `harness` CLI; keep the paper project separate from the
Harness repository.

Resolve the requested stage from the user's task and current project status.
Do not run the normal path end to end unless the user explicitly requests the
whole lifecycle; finish the requested stage and hand off its persisted state.

Do not use it for a one-off textbook solution, an informal plot, or a generic
Python experiment with no evidence or competition-delivery obligations.

## Core principles

1. Treat `competition_profile.json` as the only competition-rules contract.
2. Treat receipts as execution facts, the run index as a rebuildable
   projection, and the normalized manifest as the control plane.
3. Resolve exactly one preset: `sprint`, `research`, or `submission`.
   Overrides are allow-listed capability adjustments, not new presets.
4. Keep Contest Safety, independent validation, human checkpoints, result
   freeze, and submission immutability non-bypassable.
5. Never hand-write gate PASS values, receipts, hashes, freshness, claim
   inventories, or validation verdicts. A reviewer/human may create a new
   schema-valid review report; operators must not rewrite an existing report
   to manufacture PASS.
6. Preserve failed runs and failure evidence. A failed run is evidence, not a
   reason to delete a counterexample.
7. Hashes prove byte identity only. They do not prove leakage safety, objective
   semantics, mathematical correctness, units, statistics, or figure claims.
8. Use the order `semantic validation -> accept -> freeze -> hash binding`.
9. Stop on missing inputs, `FAIL`, `ERROR`, unresolved official rules, or a
   pending human decision. Do not promote a plan, demo, or regression as a
   benchmark result.
10. Treat `.harness/views/` (including `M1_STATE.md`, `W1_STATE.md`,
    `PROJECT_BRIEF.md`, and `SUBMISSION_STATE.md`) as deterministic projections
    only. They never replace contracts, receipts, Gate reports, or frozen
    artifacts. `00_PROJECT_BRIEF.md`, `01_RESEARCH_NOTES.md`,
    `02_MODEL_DECISION.md`, `03_SOLUTION_REPORT.md`, and `paper/` are the
    human authoring surface and must never be overwritten by `prepare`.
11. Write reasoning in author Markdown and structured compiler input in
    `.harness/authoring/*.yaml`. Existing fenced Markdown sources remain a
    legacy input; follow the command's reported source path. Use the explicit
    `research/model/solve/paper plan/figure --compile` commands only when a
    machine consumer needs IR; never hand-edit those generated JSON files. A
    compile creates IR, not research evidence or a Gate result.
12. AI usage starts as `unknown`. Before S1, record each use or obtain an
    explicit human `none` declaration; an empty registry is not proof of no
    use. Harness-observable AI backends must log automatically as `pending`;
    a human must run `harness ai verify` before strict promotion.

## Normal path

```text
harness init -> S0 -> M1 -> P1 -> P2 -> W1 -> W2 -> S1 -> F1
```

Only advance after the current Gate has a factual report and its required
human checkpoint. A later status value in a stale manifest cannot override an
earlier factual failure.

### S0 — scope and safety

Resolve a standalone competition-profile seed and inspect the current rule
snapshot, endpoints, AI policy, page scope, and human checks. A maintainer
seed is `status: seed` or `unresolved`; it is not an official verified rule.
Keep official rules separate from a stricter local policy.

Minimum I/O: project root, `competition_profile.json`, `run_manifest.json`,
`artifact_dag.json`, and `run_index.json`.

### M1 — model and validation contract

Record the problem mechanism, data boundary, at least two candidate models (or
a documented reason for an exception), assumptions, typed parameter
provenance, formulas, an implementation plan, and falsifiable validation duties.
Use `assumption_forks` for ambiguous question semantics and declare objective
and risk semantics before coding.
Run `harness prepare M1` before the M1 human checkpoint; review its modeling
plan, but never infer M1 PASS from that Markdown projection.

Minimum I/O: ready `model_contract.json`, evidence registry, current profile,
M1 human checkpoint, and a current DAG. In `research`/`submission`, formal
literature linkage and scope checks are required.

### P1 — smoke execution

Run the smallest real process through `run_and_record.py`. The receipt must be
process-captured, tied to this run, and successful; copied command text or an
exit code in a projection is not a receipt.
Receipt, index, stdout/stderr sidecars, and declared outputs must remain inside
the contest project root. Existing receipt files are immutable: choose a new
receipt ID/path before rerunning, never overwrite the old execution record.

Minimum I/O: one successful smoke receipt and the v2 run-index projection.
In `research`/`submission`, that receipt also carries the exercised model,
question, and contract-item IDs; mutable manifest claims are not execution
evidence.

### P2 — full run, independent validation, and result freeze

Run the selected full computation and an independent evaluator. Recompute each
declared obligation, including sensitivity/OOS/failure evidence when triggered.
Freeze the result only after semantic validation. Only `status: frozen`,
`validation_verdict: PASS`, and `claimable: true` results may enter evidence.
The unit checker parses declared unit expressions into scale and dimensional
signatures. It recognizes common SI base/derived units and composite or custom
units, so `J` and `kg*m^2/s^2` are dimensionally equivalent. It does not infer
units from equation text or convert numeric values: reusing one symbol as
`m/s` and `km/h` remains a blocking scale contradiction, while an equation
balance with different scales requires an explicit conversion warning. A
sensitivity sweep point is valid only when its real output contains the
declared metric as a finite number; a successful process exit alone is
insufficient.

Minimum I/O: exactly one selected full receipt, one successful freeze receipt,
one frozen-results artifact, required input/output bindings, and P2 human
checkpoint. `research`/`submission` additionally require a verified
implementation map bound to the current model contract and code/tests.

### W1 — evidence and paper plan

Build one incremental evidence registry and a paper plan mapping each claim to
verified evidence. Keep result definitions, population, units, and rounding
consistent. Do not fill missing evidence with prose.
Run `harness prepare W1` to project the machine IR into a paper outline and
deliverables/appendix plan. Missing evidence must remain visibly missing.

Minimum I/O: ready `paper_plan.json`, verified evidence references, current
frozen result, and W1 human checkpoint.

### W2 — deterministic content QA

Generate the writer package and draft, then run deterministic QA, mathematical
semantic checks, consistency checks, template/build checks, PDF checks, and
visual review required by the resolved capabilities. Semantic Critic and
human review are separate from mechanical QA.

Review is executable, not declarative: run `harness review` after the draft.
It runs deterministic QA, materializes the allow-listed review bundle, and
routes the required perspectives (sprint: semantic critic; research:
semantic + judge; submission: research set plus one review with
independence_level >= L1). Reports land under `reports/review/` as generated
evidence; W2 recomputes verdict, artifact binding, and freshness from those
reports — never from manifest self-reports. Open blocker/high/medium findings
block W2 unless a medium finding is explicitly accepted with justification;
a paper change makes the old review stale. `--fresh` binds the bundle, child
working directory, receipt, and report, but is not an OS sandbox: submission
still needs a genuinely separate context/model. Load the review references
via the router before acting as a reviewer.

Human-prose review is an optional editorial perspective inside this existing
review plane (`harness review --human-prose --section <id>`). It diagnoses
clustered low-information, repetitive, or mechanically regular prose and
proposes finding-local bounded revisions. It is not a required W2 perspective,
does not increase review independence, and has no authority to alter facts,
mathematics, evidence scope, author files, or Gate status.

Keep evidence scope separate from reviewer independence. A report may narrow
its `available_evidence_scope`, but bound artifact roles determine the upper
limit. If a gate-severity finding needs a stronger scope, set
`requires_external_check: true`; it cannot become established merely through
reviewer confidence or a free-text receipt/command locator. The current bundle
supports at most `result_artifacts`; `rerunnable` is reserved until code, data,
environment, and model-run evidence receive structured bindings.

Minimum I/O: paper source/draft, abstract, conclusion, deterministic QA report,
current review reports, current evidence chain, and W2 human checkpoint.
`research` requires the full evidence chain; `submission` additionally
requires strict math/editorial and current template/bibliography evidence.
Run `harness prepare W2` to refresh the project brief and targeted revision
view; it does not run or replace deterministic QA/review.
Internal authoring tokens such as `ANCHOR-*`, `LOC-*`, argument-unit IDs, and
review routing labels must never appear in reader-facing prose or the PDF.
Use invisible `\label{harness:...}` locators or TeX comments for traceability.

### S1 — current submission checks

Check the current verified profile, page scope, support package, AI disclosure,
required manual checks, and final PDF. A seed profile cannot pass submission.
The Harness never uploads on a user's behalf.
Run `harness prepare S1` to generate the AI ledger/disclosure draft,
submission checklist, and mutable staging directories. It must not populate
immutable `submission/final/` or claim readiness.

Minimum I/O: verified profile, current PDF/support/disclosure artifacts, S1
report, and S1 human checkpoint.

### F1 — immutable delivery

Freeze the submission package and bind the final source/PDF/package identities
in the submission manifest. Any changed immutable input requires a new version,
new digest binding, downstream invalidation, and rerun of affected Gates.

Minimum I/O: immutable submission manifest and receipt. F1 is not a mutable
`run_manifest.gates` flag.

After a human portal submission, validate the separately recorded portal
receipt with `harness submit receipt --receipt <path>`. It must bind an
immutable F1 file, current hashes, an official profile endpoint, portal
evidence, and `portal_status=accepted`; this command never uploads anything.

## Presets

| Preset | Use | Integrity posture |
|---|---|---|
| `sprint` | fast exploratory/model smoke work | identity boundaries; explicit result freeze |
| `research` | default formal research run | selected-run lineage, independent validation, selective critical hashes |
| `submission` | current contest delivery | strict math/editorial checks and final-chain immutability |

Never disable Contest Safety, human checkpoints, independent validation,
result freeze, or submission immutability with an override.

## CLI quick start

The public operation surface uses six action families:
`init`, `status`, `prepare`, `execute`, `check`, and `submit`. Gate stages still
determine the real order; do not treat the six names as a one-pass checklist.
Use `--json` for agent consumers. `status --json` and `context --json` expose the current `ruleset_id`
and its matched source scope; an unchanged ID only permits reusing the prior
rule understanding, while Gate and contract freshness checks still run.

```powershell
python scripts/harness.py init --project C:\work\q1 --competition cumcm --preset research
python scripts/harness.py status --project C:\work\q1 --json
python scripts/harness.py prepare M1 --project C:\work\q1 --json
python scripts/harness.py check M1 --project C:\work\q1 --json
python scripts/harness.py prepare P1 --project C:\work\q1 --json
python scripts/harness.py execute --project C:\work\q1 --stage smoke `
  --covers-model M-Q1 --covers-question q1 --covers-contract-item EQ-Q1-OBJ `
  -- python model.py
python scripts/harness.py check P1 --project C:\work\q1 --json
python scripts/harness.py submit check --project C:\work\q1 --json
```

The remaining specialized authoring, review, freeze, migration, and diagnostic
commands are advanced/compatibility entry points; use them only when the
current stage requires their explicit behavior.

### Advanced/compatibility details

Classify every Figure Brief as `data`, `diagram`, or `illustration` before choosing
a tool. An undeclared or unrecognized semantic type is `unresolved`: stop and fix
the brief rather than silently choosing a backend. Data/result figures remain
deterministic; illustrations use the Figure Contract illustration route.

For a simple `diagram` process/framework, default to the inspected PPTX route:
`harness figure FIG-01 --semantic-type workflow --prepare-pptx`. The selector
uses declared semantic type plus topology metadata (nodes, depth, branches,
feedback, lanes, density, aspect ratio, native-QA need) to present 2–3 candidates.
Read only the selected catalog entry, copy the source deck once, and edit it in
PowerPoint (or the presentation template-following workflow), not with manually
positioned Python boxes. Preserve the source deck and manually adjusted arrows;
render a paper-scale export for human review. This creates an editable visual
source, never a visual claim, receipt, or Gate outcome.

Use `--diagram-backend drawio` only for a complex DAG/feedback figure or when a
native XML/topology contract is actually needed. Draw.io archetypes may change
geometry and primitives only; they must preserve nodes, edges, source refs,
semantic roles, and palette policy.

### Illustration execution (native image generation)

When a completed Figure Contract routes a figure as `illustration` (physical
mechanism, system concept, scenario, energy-flow concept) AND the current
environment exposes a native image-generation tool AND the competition
profile allows generated imagery, call it proactively — do not wait for the
user to remind you. The trigger is the approved Figure Contract, not a verbal
request.

Execution protocol (provider-neutral; the harness never calls an image API):

```powershell
python scripts/harness.py figure FIG-02 --kind illustration --semantic-type "physical mechanism" `
  --request-illustration --capability available --ai-policy allowed
# -> emits .harness/views/figures/FIG-02_image_generation_request.json
#    with the full prompt composed from the approved brief
# (agent generates the image with its native tool)
python scripts/harness.py figure FIG-02 --collect-illustration figures/FIG-02/generated.png
# -> registers path + SHA-256 + review obligations in figures/FIG-02/illustration.json
```

Never generate: data/result figures (deterministic plotting only),
formula-dense or numeric-bearing structure diagrams (editable backend), or
decorative optional figures without a complete contract. When the native tool
is missing, pass `--capability missing` and report the factual status; when
the profile forbids it, pass `--ai-policy forbidden`; never pretend an image
was generated. A collected illustration has `review_status: pending` until
scientific, visual, and final-size review pass; it must also be registered in
`run_manifest.ai_usage` (then `harness ai verify`) before strict promotion.
The CLI defaults capability and policy to `unknown`; generation remains
blocked until both are explicitly resolved. Collection requires the matching
`status=requested` request record for that figure.

Use `--json` for agent consumption. Underlying checkers retain their stdout,
stderr, and exit code. Use their script-level flags only for debugging; the
normal path should require one project root plus stage/preset.

## Progressive disclosure

Read only the relevant router entry before a specialized task:

- [harness walkthrough](references/usage/harness_walkthrough.md) — the human-facing, Chinese guide to command order and operator modes; read it when a person, not an agent, is driving
- [reference router](references/router.md) for contracts, Gate policy,
  validation, writing, figures, literature, and submission details;
- [artifact contracts](references/contracts/artifact_contracts.md) for
  ownership, result semantics, and generated artifact boundaries;
- [Gate policy](references/workflow/gate_policy.md) for Gate-specific checks.

Detailed statistics, optimization, prediction, mechanism, writing, figure,
citation, template, and contest-submission rules stay in the existing
one-level routed references. Do not load all cards into the active context.

## Migration and safety reminders

Run `harness migrate --project <legacy-root>` to a separate `migration_v2/`
directory. Read `migrated`, `inferred`, `unresolved`, `deprecated`, and
`manual_review_required` before promotion. Migration never rewrites historical
frozen evidence and never upgrades a legacy command declaration to a receipt.

For an already-v2 flat project, `harness migrate --layout hidden` is a read-only
plan; add `--apply` only after inspecting it. It moves only the four mutable
control documents into `.harness/state/`, records a non-Gate migration report,
and preserves receipts, frozen artifacts, evidence, results and author files.
Never leave a root-level duplicate beside an active hidden layout.

Status is read-only and a v1 status is explicitly deprecated. A DAG freshness
projection is evidence for the next action, not permission to rewrite the DAG.
Regression tests prove stated code paths; they are not capability benchmarks.

For release work, report commands actually run, exit codes, artifact paths,
uncovered risks, and whether any real benchmark was run. Quarantine previous
national-contest papers under `references/precedents/cumcm/` and MCM/ICM papers
under `references/precedents/mcm-icm/`, register their provenance in the local
indexes, and extract reusable mechanisms into `pattern-cards/` before Writer
use. Raw precedent papers are not current evidence and must not silently enter
a new project.
