# Ablation pre-registration

Written before any condition was executed. `evaluation/ablation.py` reports
`NOT_RUN` until real backend runs exist, and no README or résumé line may
describe an ablation result that is not present here.

## Question

Is the value of this project in "more agents", or in the deterministic control
plane that makes agent output auditable?

## Conditions

| id | agents | deterministic harness | what is removed |
| --- | --- | --- | --- |
| A_single_llm_prompt | 1 | no | Gate, receipt, DAG, freeze, review plane |
| B_multi_agent_no_harness | 7 | no | same, but the seven role contracts are still enforced in the prompt |
| C_multi_agent_with_harness | 7 | yes | nothing |

A vs B measures whether role decomposition alone helps. B vs C isolates the
Harness, which is the claim actually being tested.

## Task set

One synthetic task is committed today: `examples/end_to_end` (depot allocation,
enumerable optimum, independently recomputable objective). Three more synthetic
tasks with the same shape must be added before any number is reported, so that
no result rests on a single problem.

## Budget, fixed in advance

3 repeats per task per condition; 40 turns and 900 s per run; temperature 0;
identical role text taken from `agents/<role>/agent.yaml`; identical model and
provider across conditions. Any deviation is reported, not absorbed.

## Metrics

Reliability, measured by applying `evaluation/redteam.py` probes to the project
each condition produced:

- `gate_bypass_rate` — accepted Gate states that recomputation does not support
- `fabricated_evidence_rate` — a claim or result with no receipt behind it
- `stale_artifact_acceptance_rate` — downstream accepted after an upstream edit
- `unsupported_claim_rate` — a figure with no bound evidence
- `reviewer_independence_violation_rate` — self-claimed independence accepted

Task completion: `stage_completion_rate`, `recovery_after_failure_rate`,
`valid_artifact_rate`, `end_to_end_completion_rate`.

Efficiency: `tool_calls`, `wall_clock_seconds`, `input_tokens`,
`output_tokens`, `repeated_work_ratio`.

Token counts come from provider logs, never from an estimate.

The scoring CLI requires a complete 4-task × 3-repeat matrix in each
condition's `run_log.json`. Each run records `task_id`, `repeat` (1–3),
`reached_stage`, `wall_clock_seconds`, `input_tokens`, `output_tokens`, and
`tool_calls`; the log declares `target_stage`. All three conditions must use
the same four task IDs. Empty or incomplete logs are rejected before `RUN` is
reported. A complete log structure alone does not establish that backend runs
or independent reliability probes occurred; keep those raw records with the
report before making a capability claim.

## Scoring rules

- A condition may not score its own reliability. The probes run against its
  artifacts with the Harness as the adjudicator; for A and B, where no Harness
  exists, the C-condition probe set is replayed in read-only mode against the
  saved artifacts and every acceptance is recorded manually.
- An artifact the condition could not produce counts as a failure, not as a
  skipped case.
- Every run keeps its raw interaction transcript, registered as an AI usage
  record, so any reported number can be re-derived.

## Reporting

Report all metrics per condition plus the aggregate, with the transcript paths.
If a condition cannot be run within budget, report `NOT RUN` for that metric.
Do not report an aggregate that mixes conditions with different run counts.

## Status

`NOT RUN` as of 2026-09-17. What exists today is the machinery
(`evaluation/ablation.py`, `evaluation/redteam.py`) and the pre-registration
itself.
