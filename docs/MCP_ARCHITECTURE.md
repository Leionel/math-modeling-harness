# MCP architecture

How an external agent (Codex, Claude Code, Cursor, or a home-grown loop) reaches
this Harness, and what it can and cannot do through that door.

```text
External agent
      │  JSON-RPC 2.0 over stdio (newline delimited)
      ▼
scripts/mcp_server.py          transport + authority
      │  • per-call project_root
      │  • MATH_HARNESS_ALLOWED_ROOTS (fail closed)
      │  • path containment, cwd pinning, 55 s timeout, redaction
      ▼
scripts/mcp_tools/             the tool answers
      │  state.py     get_run_state · check_gate
      │  artifacts.py list_artifacts · verify_artifact
      │  review.py    request_review (opt-in)
      ▼
scripts/harness.py + scripts/qa/* + scripts/artifact_dag_projector.py
                         deterministic truth
```

## Where the logic lives

The MCP layer is an interface, not an implementation. Two shapes exist:

- **argv facades** (`TOOL_BUILDERS`) map a tool call onto one `harness`
  subcommand and pass the child's stdout, stderr and exit code through
  verbatim. Nine tools work this way.
- **computed tools** (`scripts/mcp_tools/`) reshape a Harness answer into a
  structure an agent can plan with — for example `get_run_state` turns
  `harness status --json` into `{stage, gate_status, blockers[], next_actions[]}`.

A computed tool never implements a verdict itself. It calls the same
deterministic entry point the CLI calls, so an MCP answer and a
`harness check` answer cannot drift apart. If they ever disagree, that is a bug
in this layer, not a policy choice.

`get_run_state` also forwards the read-only `question_workbench` from status.
Blockers carry `action` with exact diagnostics, a Chinese explanation, explicit
author-source identity where available, and argv plus PowerShell/POSIX display
commands. A missing field locator remains null. These are planning aids, not
new MCP tools, mutation authority or additional Gate verdicts.

## Tool surface

Read-only by default:

| Tool | Answers | Backed by |
| --- | --- | --- |
| `get_run_state` | stage, Gate readiness, blockers with repair actions, pending human checkpoints, stale artifacts | `harness status --json` |
| `check_gate` | "may I advance?" plus the first reason not to | `harness check <GATE>` |
| `list_artifacts` | every DAG node with recomputed freshness and drift reason | `artifact_dag_projector` |
| `verify_artifact` | one artifact: identity, digest drift, dependency and producer-receipt state, schema validity | DAG + schemas |
| `research_status`, `research_context`, `model_status`, `solve_status`, `paper_status`, `validate_current_stage`, `submission_check`, `doctor`, `ai_status` | the pre-existing facades | `harness` subcommands |

Opt-in mutating:

| Tool | Condition | Why it is gated |
| --- | --- | --- |
| `request_review` | server sets `MATH_HARNESS_ALLOW_REVIEW_TOOL=1` | it writes review evidence |
| — | reviewer command comes from `MATH_HARNESS_REVIEW_BACKEND` on the **server** | an agent-supplied argv would be remote code execution behind a friendly tool name |

`tools/list` does not advertise a mutating tool while it is disabled, so an
agent cannot discover a capability and try it.

## What is deliberately absent

**There is no `register_artifact`.** A tool that minted `artifact_id`, SHA-256,
timestamps and provenance on request is a receipt-and-hash forgery endpoint; the
name does not change what it is. Provenance is a by-product of producing:

| Want | Real path |
| --- | --- |
| a contract | author Markdown → `harness model --compile` → validated IR |
| an execution fact | `harness execute --stage smoke\|full\|freeze -- <cmd>` → process receipt |
| a claimable number | `harness freeze --kind results --receipt …` → `frozen_results` bound to that receipt |
| review evidence | `harness review` → reports registered into the DAG by the Harness |

Agents *propose* by writing author-plane files; only producer commands create
execution facts, and only the Gate engine decides whether they are enough.

## Authority model

- Every call carries an explicit `project_root`. The server never assumes its
  working directory is the project.
- `MATH_HARNESS_ALLOWED_ROOTS` unset or empty denies **everything**.
- A checker `FAIL` is returned as a normal result: `isError` marks transport
  failures only, never a negative verdict. An agent cannot read "the call
  succeeded" as "the Gate passed".
- Output is redacted before it leaves the server.
- Agent contracts may name MCP tools as `mcp:<tool>`; `harness agents check`
  validates those names against this live registry and treats
  `mcp:request_review` as truth-mutating, so the orchestrator contract is
  refused if it holds it.

## Extending it

Add a handler in the right `scripts/mcp_tools/` module with
`"mutating": True|False`, and it appears in `FACADE_TOOLS`, `tool_surface()`,
`visible_tools()` and the contract checker automatically. Rules:

1. Read-only is the default. A mutating tool needs an env opt-in and a
   `tests/test_mcp_server.py` case asserting it is absent by default.
2. Never compute a verdict locally that a Gate already computes.
3. Never accept a command, path or script from tool arguments that the operator
   has not configured server-side.
4. `harness agents check` and `tests/test_mcp_server.py` must both stay green.
# Status projection outcomes

`get_run_state` reports `ERROR` when the status process fails, emits non-object
JSON, or reports `ok: false`. Its `errors` and `status_exit_code` preserve the
failure; it cannot infer READY from an empty response. Deprecated v1 status is
`LEGACY`, not a recomputed v2 readiness verdict. A valid v2 report may be
`BLOCKED`, `PENDING_HUMAN`, or `READY`; these describe observed evidence, not
mathematical correctness. Gate blockers retain their `failures_summary` gate
identity. Current Gate work takes priority over future human checkpoints.

