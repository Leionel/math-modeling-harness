# Math Modeling Evidence Harness

[![harness-ci](https://github.com/Leionel/math-model-skill/actions/workflows/ci.yml/badge.svg)](https://github.com/Leionel/math-model-skill/actions/workflows/ci.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![python: 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
[![schemas: 37](https://img.shields.io/badge/JSON%20schemas-37-lightgrey)](schemas)

[跳到中文说明](#公共主流程中文) · [给人看的 Harness 使用说明](references/usage/harness_walkthrough.md)

**A MCP-compatible multi-agent execution framework with deterministic
verification, artifact provenance, and human oversight.**

![How the Harness bounds an AI-assisted modeling run: analysis, modeling,
experiment, writing and review, with every result traceable to a receipt](assets/poster_v1.png)

Mathematical modeling is the first domain-specific testbed. What the project
actually builds is infrastructure for long-running agents: any agent — Codex,
Claude Code, Cursor, or your own loop — reaches the same verified runtime through
MCP, and a human watches the identical read path in a console.

```text
   Agent layer            Problem Analyst · Modeling · Experiment · Paper
   (reasoning)            Reviewer · Compliance        + Orchestrator
                             │                       │
   MCP interface      scripts/mcp_server.py    (JSON-RPC/stdio)
   (one door)         13 read-only tools · 1 opt-in mutating tool
                             │                       │
   Harness runtime    harness CLI — 32 commands, one project root
                             │                       │
   Evidence layer     Gate Engine · Artifact DAG · Execution Receipts
   (deterministic)    Hash/Freshness · Evidence Registry · Validation
                      · Review Plane · Freeze / Submission Guard
                             │
   Human console      dashboard/ — read-only trace: gates, timeline,
                      lineage, receipts, reviews. No write path.
```

Agents reason, plan, generate and review. The Harness decides what is a fact.
No agent, and no agent conversation, can write a Gate PASS, a receipt, a hash,
a frozen result or a review verdict — and neither can the dashboard.

### Core capabilities

| | |
| --- | --- |
| **Deterministic Gates** | `S0 → M1 → P1 → P2 → W1 → W2 → S1 → F1`. Each verdict is recomputed from files on disk at read time; v2 control state has no field that could hold a hand-written PASS. |
| **Execution receipts** | `harness execute` runs a real subprocess and captures argv, cwd, exit code, timestamps and optional input/output digests. A number with no receipt behind it cannot reach a frozen result. |
| **Artifact DAG with hash-driven freshness** | Editing a reviewed artifact invalidates the review; `W2` refuses a stale review, and the selective-rerun plan names the downstream work. |
| **Fresh review with enforced independence** | `harness review` materializes an allow-listed bundle, runs a backend from that directory, and refuses a report that self-declares its independence level. |
| **Auditable AI usage** | Three-state declaration, per-use records that must point at a stored interaction transcript, and human verification before strict promotion. |
| **Agent-agnostic access** | 13 read-only MCP tools (`get_run_state`, `check_gate`, `verify_artifact`, …) with a fail-closed root allowlist, plus a read-only console that renders the *same* tool calls. Agent and human cannot see two different worlds. |

### Why this is not another multi-agent chat

LangGraph-style demos prove that agents can *talk*. They do not prove the
output is true, traceable, or recoverable after a failure. Here the value is
not the number of agents — it is that the deterministic layer bounds them:

- **Agents cannot bypass a Gate.** A hand-written `gates.m1.status = "pass"` is
  rejected as forbidden duplicated state, and the Gate still fails on its facts.
  Verified by `evaluation/redteam.py`, not by an `if` in a prompt.
- **Results come from execution.** Re-freezing the same numbers from a
  free-text command produces a result that `P2` refuses as unbound.
- **Claims need evidence.** An unevidenced figure in the abstract is refused by
  deterministic QA even after a fresh re-review.
- **Role scope is machine-checked.** `harness agents check` fails if any of the
  seven `agents/*/agent.yaml` contracts names a tool, artifact role, output
  schema, reference file or Gate that this repository does not actually have.
- **Limits are published, not hidden.** The evaluation records what is *not*
  enforced today (see [Known boundaries](#known-boundaries-read-this)).

### 60-second demo

```bash
python -m pip install -r requirements-dev.txt
python -m pip install --no-deps -e .
python examples/end_to_end/run_demo.py --out tmp/demo-run
python dashboard/server.py --project tmp/demo-run --port 8765   # http://127.0.0.1:8765/
```

The driver builds a real project, runs real processes, freezes a real result,
has a fresh-context reviewer review it, and then attempts five concrete
bypasses plus one positive traceability check. Each row is decided by the
Harness's own exit code:

```text
  [    HELD] an agent cannot pass a Gate by editing state
  [    HELD] a frozen result must come from a captured execution
  [    HELD] an upstream edit makes the downstream review stale
  [    HELD] review independence is bound by the Harness, not claimed
  [    HELD] a claim without evidence is blocked
  [    HELD] the final artifact traces to a real execution and the AI call is on record
  6/6 probe outcomes held
```

<!-- DEMO_GIF: tmp/demo-run plus the probe table above; record when hosting. -->

### Evaluation

```bash
python evaluation/redteam.py          # reliability probes, no API key needed
python evaluation/ablation.py plan    # A/B/C design: reports NOT_RUN until real runs exist
```

12 scenarios across 9 classes (gate bypass, fabricated evidence, stale
acceptance, unsupported claim, reviewer independence, AI disclosure, lineage,
human attention, traceability). Two outcomes are recorded as **documented gaps**
rather than wins. The A/B/C ablation that would compare single-prompt,
multi-agent-without-harness and multi-agent-with-harness is
[pre-registered](evaluation/PREREGISTRATION.md) and **NOT RUN**; nothing here
claims a capability benchmark.

### Known boundaries — read this

Honest limits of the current implementation:

- **Receipts prove bytes, not provenance.** There is no signature or external
  witness, so a rewrite that keeps every digest consistent is accepted:
  `argv` inside a bound receipt is not attested. Closing this needs an external
  trust anchor, not more prompts.
- **A human checkpoint is unattested.** `decided_by` is free text; the Harness
  requires that a decision exist, not that a specific person typed it.
- **`--fresh` is not an OS sandbox.** It binds bundle, working directory,
  receipt and report. A submission-grade reviewer still has to run in a
  genuinely separate context or model.
- **Regression tests are not capability evidence.** 738 tests prove the code
  paths and negative guards work. They prove nothing about real-contest
  generalization.
- **Full threat model.** `docs/THREAT_MODEL.md` lists the threat actors, every
  blocked attempt with the scenario that replays it in CI, the two attestation
  gaps above, and the wording this README may and may not use.

### Documentation map

| Start here | For |
| --- | --- |
| [`SKILL.md`](SKILL.md) | the agent-facing workflow, Gate order and principles |
| [`agents/*/agent.yaml`](agents) | the seven role contracts and their prohibitions |
| [`docs/AGENT_CONTRACT.md`](docs/AGENT_CONTRACT.md) | what the contract checker enforces, and what it does not |
| [`docs/MCP_ARCHITECTURE.md`](docs/MCP_ARCHITECTURE.md) | how an external agent reaches the Harness |
| [`docs/DASHBOARD_DESIGN.md`](docs/DASHBOARD_DESIGN.md) | the read-only console and why it has no approve button |
| [`examples/end_to_end/`](examples/end_to_end/README.md) | the runnable demo and its probe table |
| [`evaluation/PREREGISTRATION.md`](evaluation/PREREGISTRATION.md) | the ablation design written before results |
| [`references/router.md`](references/router.md) | progressively disclosed method detail |
| [`references/usage/harness_walkthrough.md`](references/usage/harness_walkthrough.md) | 给人看的中文使用说明:该敲哪条命令、按什么顺序、它会留下什么 |
| [Chinese operating guide](#公共主流程中文) | 命令、Gate、preset、迁移与排障 |

---

<a id="公共主流程中文"></a>

## 中文：定位与运行手册

以下中文内容是操作面：命令、Gate 语义、preset、迁移、排障与 Agent 分阶段
Prompt。英文第一屏讲的架构与边界，以本节命令为准。

这是一个证据、验证与竞赛合规 Harness。正常使用只需要一个 paper project
root、一个比赛 seed/competition 和一个 preset；底层脚本仍保留为 debug
appendix。Harness 不替用户猜题、伪造结果、上传比赛门户或把测试当成奖项
能力证明。

## 5–10 分钟上手：公共主流程

公共操作面收敛为 `init`、`status`、`prepare`、`execute`、`check`、`submit`
六类动作。Gate 仍按比赛阶段推进，而不是把六条命令机械地只跑一遍；每一步都在
同一个独立 `PROJECT_ROOT` 中工作。机器消费者请加 `--json`，命令返回码仍表示事实状态。

在仓库根目录运行：

```powershell
python scripts/harness.py init `
  --project C:\work\math-q1 `
  --competition cumcm `
  --preset research

python scripts/harness.py status --project C:\work\math-q1 --json
python scripts/harness.py prepare M1 --project C:\work\math-q1 --json
python scripts/harness.py check M1 --project C:\work\math-q1 --json
python scripts/harness.py prepare P1 --project C:\work\math-q1 --json
python scripts/harness.py execute --project C:\work\math-q1 --stage smoke `
  --covers-model M-Q1 --covers-question q1 --covers-contract-item EQ-Q1-OBJ `
  -- python model.py
python scripts/harness.py check P1 --project C:\work\math-q1 --json
python scripts/harness.py submit check --project C:\work\math-q1 --json
```

`execute` 会捕获真实进程的 receipt；`check` 重新计算 Gate，`submit check`
只做提交前事实核验，不会上传。W1/W2/S1 与 F1 仍按 Gate 顺序推进；具体
阶段在 `prepare` 和 `check` 中选择。`status --json` 与 `context --json` 会返回
`ruleset_id` 及命中文件范围；id 相同只表示可复用已有规则理解，Gate 和合同
freshness 仍照常检查。

### 需要人点头的两条动作

上面的循环全是可重算的事实，机器自己就能跑。只有两处必须人参与，它们不在这六类
动作里：

```powershell
# 记一次人工确认。需要人工 checkpoint 的 Gate 只认 --actor human 的行
python scripts/harness.py checkpoint approve w1 --project C:\work\math-q1 `
  --role "队长" --decision approve

# 声明这一程 agent 可以替你走多远
python scripts/harness.py mode auto --project C:\work\math-q1 --set-by "你的名字"
```

`checkpoint approve` 追加一份哈希链化的决策 artifact，并在 `run_manifest` 里追加一行
控制真相；`--actor agent` 表示这一条是 agent 代答的，它**不会**清掉任何需要人工确认的
Gate。`mode` 有 `auto`（非 Gate 动作不必逐条问）和 `accept-edits`（改动逐条批）两种，
只写入 `control.operator_mode` 及其只追加的变更史，**不放宽任何 Gate**——它的作用是让
"全程无人监督跑完"这件事在事后无法被说成有人看过。

给人看的完整顺序、每个 preset 的边界和排障路径，见
[使用说明](references/usage/harness_walkthrough.md)；跑起来之后用只读控制台
`dashboard/` 看，它没有写入路径。

## Advanced/compat

以下入口用于分阶段 authoring、调试、审查、冻结和迁移；公共主流程仍只保留上面的
六类动作。旧入口不会被删除，`run` 是 `execute` 的兼容别名。

如果希望使用短命令，在本地 checkout 做 editable 安装：

```powershell
python -m pip install -r requirements-dev.txt
python -m pip install --no-deps -e .
harness --help
```

当前 `harness` console entry 支持本地 editable checkout；尚未承诺把 schemas、
references、assets 和模板打入可独立分发的 wheel。发布型 wheel 属未来平台化
范围，不能用一次 `pip install .` 的成功替代资源完整性验证。

`init` 只写四个最小 **machine-state** 文件：`competition_profile.json`、
`run_manifest.json`、`artifact_dag.json`、`run_index.json`。它不创建几十个空
JSON，也不生成不存在的 model、result、paper 或 receipt。同时它只在缺失时
建立作者工作面：`00_PROJECT_BRIEF.md`、`01_RESEARCH_NOTES.md`、
`02_MODEL_DECISION.md`、`03_SOLUTION_REPORT.md`、`paper/00_PAPER_PLAN.md`
和空的 `.harness/` 分层目录；这些是待填写的工作文档，不是已经完成的研究。
新项目会停在 M1，直到用户提供真实题面、数据边界、模型合同、验证计划和人工确认。

### 可选：迁移 v2 control state 到隐藏目录

为保留旧脚本兼容性，`init` 目前仍从根目录建立这四个控制文件。已有 v2 项目可先
生成只读迁移计划，再显式执行移动：

```powershell
python scripts/harness.py migrate --project C:\work\math-q1 --layout hidden --json
python scripts/harness.py migrate --project C:\work\math-q1 --layout hidden --apply --json
```

它只移动并重写这四份 mutable control document 的内部路径；不会改写 receipts、冻结
结果、evidence 或作者文档。迁移完成后根目录不能残留同名控制文件，避免双真源；
`status`、`prepare`、`run`、`review` 与 `model --compile` 会自动解析 `.harness/state/`。

`init` 还把 AI 使用状态设为 `unknown`。它不会根据空数组猜测“未使用”。由人
明确确认未使用时运行：

```powershell
python scripts/harness.py ai confirm-none --project C:\work\math-q1 `
  --confirmed-by team-lead --reason "已核对团队工具记录"
```

使用过外部 AI 时，每次用 `harness ai record` 登记工具、模型、阶段、用途、交互
记录、采纳方式、人工修改和核验方式。Harness 自己通过 `--backend-cmd` 触发的
review 会自动登记为 `pending`，人审后运行 `harness ai verify --usage-id ...`。
`record` / `verify` / `confirm-none` 会同步刷新
`.harness/views/AI_USAGE_LEDGER.md`。
`prepare S1` 前状态必须从 `unknown` 解析为 `none` 或 `used`；未知状态或未完成人工
核验的自动记录会阻断正式 Gate。

### Human Working Surface：先写研究，再投影机器状态

`validate`、`review`、`freeze`、`doctor`、`setup`、`profile`、`migrate` 以及
`research/model/solve/paper` 等入口也继续保留。

作者和 Agent 日常只需要阅读根目录的 `00_PROJECT_BRIEF.md`、
`01_RESEARCH_NOTES.md`、`02_MODEL_DECISION.md`、`03_SOLUTION_REPORT.md`，
以及 `paper/` 与 `figures/`。它们不会被 `prepare` 覆盖。需要 JSON 消费者时，
将明确的 YAML source block 编译为 IR，例如：

```powershell
python scripts/harness.py research --project C:\work\math-q1 --json
python scripts/harness.py model --project C:\work\math-q1 --json
python scripts/harness.py model --project C:\work\math-q1 --compile --json
python scripts/harness.py solve --project C:\work\math-q1 --stage smoke `
  --covers-model M-Q1 --covers-question q1 --covers-contract-item EQ-Q1-OBJ `
  -- python model.py
python scripts/harness.py paper plan --project C:\work\math-q1 --json
python scripts/harness.py paper plan --project C:\work\math-q1 --compile --json
python scripts/harness.py paper section create results.q1 --role results --project C:\work\math-q1 --json
python scripts/harness.py paper write results.q1 --project C:\work\math-q1 --json
python scripts/harness.py figure FIG-01 --semantic-type workflow --prepare-pptx --project C:\work\math-q1 --json
python scripts/harness.py context --stage paper:results.q1 --project C:\work\math-q1 --json
```

`model --compile` creates validated JSON IR only; it does not pass M1. `solve`
without a command reports that no computation ran. Section commands scaffold
only the named section. The figure router selects a locally inspected PPTX
source slide for conceptual diagrams and can stage a non-overwriting editable
copy; use `--diagram-backend drawio` only for an explicit native-XML fallback.
Data figures remain deterministic Python, and illustrations use image generation.
每次成功路由还会返回与 `semantic_type` 对齐的 `figure_reference_cards`；卡片只指导
布局/编码机制，不能替代 Figure Contract 的当前题数据与证据。

`setup` 只生成 `.harness/views/SETUP_CARD.md`，用于核对 DSH 的 project、profile
和阶段能力；它不会执行命令、写 Gate 或新增人工审批点。`doctor --stage` 只把当前
阶段真正需要的缺失能力列为阻断，其他缺失工具保留为可见诊断。`status --json`
中的 `failures_summary` 是由 Gate、receipt、DAG 和 review 状态即时派生的修复清单，
不是新的事实源。


## Machine Views：给人核对的确定性投影

```powershell
python scripts/harness.py prepare M1 --project C:\work\math-q1 --json
python scripts/harness.py prepare W1 --project C:\work\math-q1 --json
python scripts/harness.py prepare W2 --project C:\work\math-q1 --json
python scripts/harness.py prepare S1 --project C:\work\math-q1 --json
```

这些命令在 `.harness/views/` 中生成或刷新 `M1_STATE.md`、`W1_STATE.md`、
`W2_STATE.md`、`PROJECT_BRIEF.md`、`APPENDIX_PLAN.md`、`AI_USAGE_LEDGER.md`
和 `SUBMISSION_STATE.md`。每份文档都列出源文件 SHA-256，并明确自己只是
projection；手改 Markdown 不会让 Gate 通过。`prepare S1` 只创建 mutable
`submission/staging/` 与 disclosure draft，不复制到 `submission/final/`、
不上传，也不声称 submission ready。

继续执行时，使用同一个 project root：

```powershell
# 真正运行并捕获 receipt；命令的 stdout/stderr/exit code 保留
python scripts/harness.py run --project C:\work\math-q1 --stage smoke `
  --covers-model M-Q1 --covers-question q1 --covers-contract-item EQ-Q1-OBJ `
  -- python model.py

# 无 backend 时只生成 bundle 与人工路由说明；报告写好后用 --recheck 导入
python scripts/harness.py review --project C:\work\math-q1 --json
python scripts/harness.py review --project C:\work\math-q1 --recheck --json

# 可选的局部编辑审阅：只产生现有 finding，不计入 W2 独立性或必需 perspective
python scripts/harness.py review --project C:\work\math-q1 `
  --human-prose --section results.q1 --json

# 实际 fresh reviewer：子进程从 bundle 目录启动，执行事实写入 receipt
python scripts/harness.py review --project C:\work\math-q1 --fresh `
  --backend-cmd "python C:\tools\reviewer.py" `
  --backend-kind ai --ai-tool-name Codex --ai-model gpt-5 --ai-provider OpenAI --json

# review evidence current 后，再跑完整 W2 Gate（复用既有 deterministic QA）
python scripts/harness.py validate --project C:\work\math-q1 --strict

# 在对应人审点刷新可读投影；prepare 不等于 Gate PASS
python scripts/harness.py prepare W1 --project C:\work\math-q1 --json
python scripts/harness.py prepare W2 --project C:\work\math-q1 --json
python scripts/harness.py prepare S1 --project C:\work\math-q1 --json

# 结果与提交冻结仍由既有 producer 负责
python scripts/harness.py freeze --project C:\work\math-q1 --kind results `
  --source results.json --output frozen_results.json --run-id <run-id> `
  --model-contract model_contract.json --code model.py --validation validation.json

python scripts/harness.py profile --project C:\work\math-q1 --json
python scripts/harness.py doctor --project C:\work\math-q1 --json

# 人工完成门户提交后，只读核验门户回执与 F1 文件/官方端点绑定；不会上传
python scripts/harness.py submit receipt --project C:\work\math-q1 `
  --receipt submission_receipt.json --json
```

对 Agent/CI 使用 `--json`；无 `--json` 时 review 会在 stderr 流式显示阶段
进度，其他命令给出人类摘要。命令返回码是事实状态：无 backend 的 review
会在等待人工报告时返回非零，这是 pending，不是已完成。`--fresh` 证明的是
bundle、工作目录、receipt 与报告的绑定；它不是 OS 级沙箱。submission 使用
者仍须把 backend 放在真正的新上下文/独立模型中运行。

`check/validate --profile` 是兼容性断言：它只能与 manifest 已绑定的 preset
一致，不能在检查时临时覆盖 Gate policy。正常情况下可省略该参数。

Reviewer 的证据范围与独立性是两条不同轴。报告可以主动缩小
`available_evidence_scope`，但不能超过实际绑定 artifact 所支持的范围；超出范围的
blocker/high/medium finding 必须标为 `requires_external_check`。当前 review bundle
最高只能确定到 `result_artifacts`；自由文本里的 `receipt`/`command` 和 reviewer
自身的执行收据都不能证明模型可复跑。

## 给指挥 Agent 的分阶段 Prompt

先把“公共执行约束”和当前阶段 Prompt 一起交给 Codex、Claude 或其他执行 Agent。
三个阶段可以由不同 Agent 执行；后继 Agent 必须从 Harness 状态和落盘 artifact
接班，不能只相信上一位的文字总结。`PROJECT_ROOT` 必须是当前赛题的独立绝对路径。

### 公共执行约束

这段约束适用于三个阶段。先替换开头 5 个变量，再追加一个阶段 Prompt。

```text
你要使用现有 Math Modeling Evidence Harness 完成当前阶段的证据约束任务。

固定参数：
- HARNESS_ROOT = D:\Projects\随便做做\math-modeling-skill-sion
- PROJECT_ROOT = 当前赛题的绝对路径
- COMPETITION = cumcm             # 可改为 mcm_icm / apmcm
- PRESET = research               # sprint / research / submission
- INPUTS = 题面、附件数据及用户给定参考资料的绝对路径

执行规则：
1. 先完整读取 HARNESS_ROOT\SKILL.md，再从 references\router.md 只加载当前
   Gate 需要的 reference；不要一次性加载所有材料。
2. 所有 Harness 命令从 HARNESS_ROOT 执行，所有比赛 artifact 写入
   PROJECT_ROOT。不要把论文项目写进 Harness 仓库，也不要修改 HARNESS_ROOT
   的代码、schema 或测试。
3. 先显式切换到 Harness 根目录：
   Set-Location "HARNESS_ROOT"
   若 "PROJECT_ROOT\run_manifest.json" 与 "PROJECT_ROOT\.harness\state\run_manifest.json"
   都不存在，先运行：
   python scripts\harness.py init --project "PROJECT_ROOT" --competition COMPETITION --preset PRESET --json
   然后始终运行：
   python scripts\harness.py doctor --project "PROJECT_ROOT" --offline --json
   python scripts\harness.py status --project "PROJECT_ROOT" --json
   已初始化项目的 doctor/status 非零表示真实阻断；不要吞掉退出码。若需迁移旧
   v2 control state，必须先运行不带 `--apply` 的迁移计划，再取得明确授权执行。
4. 只执行当前阶段 Prompt 指定的 Gate 区间，并保持
   S0 -> M1 -> P1 -> P2 -> W1 -> W2 -> S1 -> F1 的先后关系。每次先读
   status 的 first blocker，只修当前阶段内的 blocker；不得通过手改 manifest、receipt、
   hash、DAG freshness、review verdict 或 Gate 状态来跳关。
   在 M1/W1/W2/S1 人审前运行对应的 `python scripts\harness.py prepare <STAGE> --project "PROJECT_ROOT" --json`，
   优先阅读 `.harness/views/PROJECT_BRIEF.md` 和阶段投影；这些 Markdown 只能帮助审阅，不能作为 PASS 证据。
   研究和写作使用作者工作面，需机器消费时才编译或运行，并始终绑定同一 project root：
   `python scripts\harness.py research --project "PROJECT_ROOT" --json`、
   `python scripts\harness.py context --stage research --project "PROJECT_ROOT" --json`、
   `python scripts\harness.py model --project "PROJECT_ROOT" --json`、
   `python scripts\harness.py model --project "PROJECT_ROOT" --compile --json`、
   `python scripts\harness.py solve --project "PROJECT_ROOT" --stage smoke --covers-model <MODEL_ID> --covers-question <QUESTION_ID> --covers-contract-item <EQUATION_OR_OBLIGATION_ID> -- <真实命令>`、
   `python scripts\harness.py paper plan --project "PROJECT_ROOT" --json`、
   `python scripts\harness.py paper write <section> --project "PROJECT_ROOT" --json` 和
   `python scripts\harness.py context --stage paper:<section> --project "PROJECT_ROOT" --json`。
   `model --compile` 只生成经校验的 JSON IR，不等于 M1 通过；没有真实命令的
   `solve` 不得声称完成计算。
   receipt、run index、stdout/stderr sidecar 与声明的输出工件必须留在 PROJECT_ROOT；
   既有 receipt 不可覆盖。上游文件变化后可运行
   `python scripts\harness.py solve --project "PROJECT_ROOT" --rerun-plan --changed <ARTIFACT_ID_OR_PATH> --json`
   生成最小重跑投影；它不执行命令也不直接改 Gate，必须按计划真实重跑。
5. 概念流程图/框架图默认走 PPTX：先用
   `python scripts\harness.py figure FIG-01 --semantic-type workflow --prepare-pptx --project "PROJECT_ROOT" --json`
   选择并复制仓库内已检查的参考页，再在
   `PROJECT_ROOT\figures\FIG-01\FIG-01.pptx` 中编辑，导出并做最终纸面尺寸审查。
   选择前先阅读 `assets\pptx_workflow\README.md` 的逐页结构/预览 catalog；如有新
   deck，先提取每页的形状、连接关系、文字层级并生成预览，不得只凭文件名选页。
   不得照搬参考 deck 的
   题目文字、数据或结论。Draw.io 只在明确指定 `--diagram-backend drawio` 并说明
   fallback 理由时使用。数据图和结果图仍必须用真实数据的确定性绘图生成；PPTX
   图文件本身不产生 claim、receipt 或 Gate 结果。若完整 Figure Contract 路由为
   `illustration`，且当前原生生图能力与比赛规则均已显式确认允许，Agent 应主动运行
   `harness figure ... --request-illustration --capability available --ai-policy allowed`，
   使用生成的 request 调宿主原生生图工具，再 `--collect-illustration` 回收；无需等待
   用户再次提醒。能力或规则为 `unknown` 时必须停止，不得猜测许可。
6. 遇到缺失题面/数据、官方规则未确认、命令 FAIL/ERROR、pending human
   checkpoint、哈希漂移或证据不足，立即停止下游阶段并报告。不得编造数据、
   文献、运行结果、最优性、因果解释、获奖概率或测试通过状态。
7. 所有模型/代码结论必须走真实运行与 receipt；关键数字必须能从 paper claim
   反向追到 evidence_registry -> frozen_results -> receipt/code -> raw data。
   frozen artifact 如需改变，回到上游 Gate 生成新版本，不得原地改写。
8. W2 的 review 命令会先运行 deterministic QA；只有 QA 通过才 dispatch reviewer：
   - 同上下文自审：运行 `python scripts\harness.py review --project "PROJECT_ROOT" --json` 获取 routing instructions，按
     review_report.schema.json 产出 L0 报告，再运行 `python scripts\harness.py review --project "PROJECT_ROOT" --recheck --json`；不得声称独立。
   - 真正 fresh review：只有在独立新上下文/模型 backend 已提供时，才运行
     python scripts\harness.py review --project "PROJECT_ROOT" --fresh
       --backend-cmd "<独立 reviewer 命令>" --ai-tool-name "<工具>"
       --backend-kind ai --ai-model "<模型>" --ai-provider "<提供方>" --json
   `--fresh` 绑定 bundle/cwd/receipt/report，但不是 OS 沙箱。submission 至少
   需要一个 current L1+ 或人工 L3 报告。open blocker/high/medium 未解决时
   不得通过 W2；论文改动后旧报告 stale，必须重新审查。
9. `run_manifest.ai_usage_state` 初始为 unknown。若完全未使用 AI，必须由人运行
   `python scripts\harness.py ai confirm-none --project "PROJECT_ROOT" --confirmed-by <role> --reason "<reason>"`。
   若使用过外部 AI，必须逐次运行 `python scripts\harness.py ai record --project "PROJECT_ROOT"`，完整填写
   tool/model/provider、stage、purpose、prompt-summary、output-use、human-changes、
   interaction-record、checked-by-role 和 verification-method，并绑定交互记录和人工核验。
   Harness 触发的 reviewer 会自动写 pending 记录，人审后运行
   `python scripts\harness.py ai verify --project "PROJECT_ROOT" --usage-id <usage-id> --checked-by-role <role> --verification-method "<method>" --human-changes "<changes>"` 完成核验。
   不得仅因 ai_usage 为空就写“未使用”。
10. review evidence current 后，运行：
    python scripts\harness.py validate --project "PROJECT_ROOT" --strict
    然后再次运行 `python scripts\harness.py status --project "PROJECT_ROOT" --json`。没有用户明确授权时，不 commit、不 push、不上传，
    也不执行 Final Freeze。

最终汇报必须包含：
- 当前 preset、stage、first blocker、各 Gate 的事实状态；
- 实际执行的完整命令及 exit code；
- 新增/更新 artifact 的绝对路径；
- receipt ID、selected run、frozen result、review report 与关键 hash；
- 已通过的检查、未通过/未运行的检查、人工待办和剩余风险；
- 概念图的 PPTX 源页、项目内编辑副本、导出文件和纸面尺寸审查状态；若使用
  Draw.io，说明 fallback 理由；若使用原生生图，列出 request、AI 使用记录、
  回收 hash 与科学/视觉/最终尺寸复核状态；
- 明确区分“研究草稿完成”“W2 通过”“submission ready”“F1 已冻结”，
  不得把前一种状态宣传成后一种。
```

### 阶段一：研究建模（S0 → M1）

把这段追加到公共执行约束后。这个阶段只确定问题、证据和模型，不编程、不写论文正文。

```text
当前任务是“研究建模”，工作范围止于 M1。

1. 读取题面、附件和已核验的比赛 profile，拆解子问题、输入输出、数据边界与验收目标。
2. 在 competition profile 允许的来源范围内调研真实文献。分别记录
   metadata_verified、content_verified 和 publication_status_checked；原文未支持的
   论断不得写入模型依据。
3. 比较少量可行模型，说明选择理由、假设、适用边界、失败条件和备选方案。
4. 通过作者工作面形成可编码、可证伪的 model contract：明确符号、方程、单位、
   参数来源、约束、目标函数、输入输出和 validation obligations。
5. 运行
   `python scripts\harness.py prepare M1 --project "PROJECT_ROOT" --json`，核对建模投影；
   完成人工确认后运行
   `python scripts\harness.py check M1 --project "PROJECT_ROOT" --profile PRESET --json`。
   不要为了通过检查编造实现结果、receipt 或验证结论。

阶段结束时交付：问题分析、来源登记、模型合同、验证计划、M1 状态，以及编码阶段的
实现清单。最后用三段话回答：为什么选这些模型、如何证伪、编码 Agent 下一步做什么。
```

### 阶段二：建模实现（M1 → P1 → P2）

把这段追加到公共执行约束后。这个阶段消费已确认的模型合同，产出可复现结果，不写论文正文。

```text
当前任务是“建模实现”，从已通过的 M1 接班，工作范围止于 P2 和 Results Freeze。

1. 读取 status、model contract、validation obligations 和实现清单。建立
   “方程/假设 → 模块/函数 → 输入输出 → 测试/诊断”的逐项映射。
2. 实现最小可运行版本，用
   `python scripts\harness.py solve --project "PROJECT_ROOT" --stage smoke --covers-model <MODEL_ID> --covers-question <QUESTION_ID> --covers-contract-item <CONTRACT_ITEM_ID> -- <真实命令>`
   生成 receipt。先修复真实 smoke 失败，再运行 P1 检查；不得用 mock 输出代替运行证据。
3. 执行 full experiments、基线、边界和失败案例，并完成独立重算。按题型补充样本外、
   数据泄漏、敏感性、稳健性或极值验证；每个关键指标都要有单位和计算口径。
4. 只选择可复现的 full run。完成独立验证后，先用 Harness producer 冻结结果并
   建立 evidence registry，再运行 P2 检查；P2 要求 selected full receipt、freeze
   receipt 和 canonical frozen results 相互绑定。上游变化必须生成新 run、receipt
   和冻结版本。

阶段结束时交付：源代码、运行环境、smoke/full receipts、验证报告、selected run、
frozen results、evidence registry 和失败边界。明确列出 P1/P2 状态，以及论文阶段
可以声称和不能声称的内容。
```

### 阶段三：论文写作（P2 → W1 → W2）

把这段追加到公共执行约束后。这个阶段只能消费冻结证据；提交与 F1 需要另行授权。

```text
当前任务是“论文写作”，从已通过的 P2 和冻结结果接班，工作范围止于 W2。

1. 运行 `python scripts\harness.py prepare W1 --project "PROJECT_ROOT" --json`。
   先建立整篇论文的 argument spine：每个子问题按
   “问题 → 方法选择 → 结果 → 验证 → 局限”闭环，并完成 claim-evidence map、
   篇幅预算、图表计划和 section brief，再检查 W1。
2. 由一个 Paper Writer 统一写作，按需加载 writing micro-guidelines。摘要关键数字
   只能来自 evidence registry；摘要、正文、结论和图表统一符号、单位、有效数字和术语。
3. 主动执行 Figure Contract。每幅图先声明要证明的 claim、所用冻结数据、选择该
   图型的理由和对应子问题。数据图走确定性绘图，机制图走 PPTX/Draw.io；只有不承载
   定量证据的概念插图才可在规则允许时调用 Agent 原生生图。图数由 evidence coverage 决定。
4. 删除面向机器的写作痕迹。终稿不得出现 `ANCHOR-*`、`LOC-*`、内部 claim ID、
   TODO、Gate 名称、路由说明或给 Agent 的指令；这些标识只能留在审计 artifact 中。
5. 初稿完成后先做 Reverse Outline；需要减少低信息复述、机械 CEEL 或重复段落节奏时，
   可按 section 运行 `harness review --human-prose --section <id>`，只处理现有 finding
   指定的局部范围。它不改变事实、数学、evidence scope 或 W2 independence。随后运行
   consistency sweep、deterministic QA、数学/引用/PDF/视觉检查，再执行
   `python scripts\harness.py prepare W2 --project "PROJECT_ROOT" --json` 和
   `python scripts\harness.py review --project "PROJECT_ROOT" --json`。作者同上下文
   自审只能记为 L0；论文修改后旧 review 变为 stale，必须重新检查。
6. review evidence current 后运行
   `python scripts\harness.py validate --project "PROJECT_ROOT" --strict`，并重新读取 status。

阶段结束时交付：论文源文件与 PDF、paper plan、claim-evidence map、figure contracts、
QA/review 报告和未解决问题。明确区分“论文写完”“W2 通过”和“submission ready”；
本阶段不执行 S1、上传或 Final Freeze。
```

## 目录与三层模型

```text
project-root/
├── 00_PROJECT_BRIEF.md         # 人类/Agent 的项目工作源
├── 01_RESEARCH_NOTES.md        # 调研、候选与排除理由
├── 02_MODEL_DECISION.md        # 模型决策；可显式编译为 JSON IR
├── 03_SOLUTION_REPORT.md       # 真实运行后的求解和失败记录
├── competition_profile.json   # 独立比赛规则合同（seed/unresolved/verified）
├── run_manifest.json           # v2 control plane：preset、roots、policy、人审/安全
├── artifact_dag.json           # artifact_id、依赖、生命周期、现场 freshness
├── run_index.json              # 可重建 projection：receipt IDs 与 selection
├── .harness/
│   ├── contracts/               # 新编译合同的默认位置
│   ├── receipts/ evidence/ results/ reports/ indexes/ cache/
│   └── views/                   # prepare 产生的机器投影，不是作者文档
├── receipts/                   # 真实进程生成；不要手写
├── figures/                    # 每图先有 brief.md，再选择工具
└── paper/                      # 包含 00_PAPER_PLAN.md 与 section-local drafts
```

三层 ownership 固定如下：

| 层 | 真源 | 不能做什么 |
|---|---|---|
| execution fact | `command_receipt` | 不能用 manifest command/复制 exit code 代替 |
| projection | `run_index` | 不能复制 argv、变成执行真源或第二 digest registry |
| control decision | `run_manifest.control` | 不能写平铺 Gate PASS 或内嵌比赛 profile |

### 主链与 Gate

```text
S0 -> M1 -> P1 -> P2 -> W1 -> W2 -> S1 -> F1
```

每个 Gate 只推进一个决策。M1 是可编码且可证伪的模型/验证计划；P1 是
最小真实 smoke；P2 是 full + 独立重算 + freeze；W1 是 claim/evidence
计划；W2 是确定性、数学、写作、PDF/视觉检查加上真实执行的 review plane
（`harness review` 产出 `reports/review/` 下的 generated evidence；open
blocker/high/medium 阻断 W2，除非 medium 被有理由地接受；论文改动使旧
review stale）；S1 是当届规则和提交包；
F1 是不可覆盖交付绑定。详细最低 I/O 见
[Gate policy](references/workflow/gate_policy.md) 与
[Review Execution Design](docs/REVIEW_EXECUTION_DESIGN.md)。

概念流程图/框架图默认使用仓库内已检查的 PPTX 参考页：
[`assets/pptx_workflow`](assets/pptx_workflow/README.md)。
`harness figure ... --prepare-pptx` 会选择参考页并只复制一次源 deck 到
项目的 `figures/<FIG-ID>/`，后续在 PPTX 内编辑并导出/人审；它不替代
Figure Contract、source evidence 或最终纸面尺寸检查。

五种 Draw.io archetype（`research_framework`、`computational_pipeline`、
`parallel_integration`、`method_architecture`、`iterative_optimization`）及其
[原生 XML 样例](assets/drawio/archetypes/README.md) 保留为明确选择的 fallback，
适用于需要 native topology/XML QA 的场景。数据图仍走确定性绘图，图数仍由
evidence coverage 决定。

选择 Draw.io 后可运行真实交付链黑盒检查：

```powershell
python scripts/qa/check_drawio_delivery.py --project-root C:\work\math-q1 `
  --source figures\FIG-01\FIG-01.drawio
```

它只验证 `.drawio -> PDF -> pdfinfo -> PNG render`。缺少 Draw.io 或 Poppler
时返回 `status: not_available`，不会冒充 PASS；即使通过，也不代表图的语义、
数据、版式或论文内最终尺寸正确。

## 三个 preset

| preset | 用途 | 哈希/检查姿态 |
|---|---|---|
| `sprint` | 快速探索与最小 smoke | 保留身份、安全、人审、独立验证和显式结果 freeze；避免全量哈希 |
| `research` | 默认正式研究链 | selected run、独立验证、完整 evidence chain、关键 I/O 选择性哈希 |
| `submission` | 当前比赛交付 | strict math/editorial、current template/bibliography、最终 source/PDF/package 不可变 |

override 只能是 allow-list capability adjustment，不能关闭 Contest Safety、
human checkpoint、independent validation、result freeze 或 submission
immutability，也不会形成第四种 preset。

## Profile 与比赛规则

`competition_profiles/*.yaml` 是维护者 seed，不是官方规则证据。`harness
init` 产生 standalone profile，明确为 `status: seed`；它没有 verified
official snapshot 时，S1/submission 必须阻塞。请附上真实官方快照、URL、
retrieval time、endpoint 和 page/AI/support/manual-check 语义，再走验证。

不要把上一届 profile、博客、聊天内容或本地保守策略冒充当届官方规则。
local policy 可以更严格，但必须和 official rule 分开记录。

## v1 migration

迁移是显式且非破坏性的：

```powershell
python scripts/harness.py migrate --project C:\work\legacy --json
```

默认输出 `C:\work\legacy\migration_v2\`，不覆盖源 manifest、旧
`frozen_results`、`submission_manifest` 或历史 receipts。读取报告中的
`migrated`、`inferred`、`unresolved`、`deprecated`、
`manual_review_required`；出现 unresolved/manual review 时不能宣传研究或
提交 ready。旧 command declaration 没有真实 receipt 时仍是 unresolved。

原始入口仍可用于 debug：

```powershell
python scripts/migrate_v1_to_v2.py --project C:\work\legacy --no-write --json
```

## Hash policy 与 generated evidence

只使用 SHA-256，并让每个 artifact 只有一个 digest owner：DAG/metadata、
command receipt、`frozen_results.results_sha256` 或最终 submission manifest。
Status/index 可以展示 projection，但不能成为第二真源。

哈希只证明字节身份，不证明 leakage、objective semantics、数学正确性、
统计单位、因果关系或图的结论。正确顺序是：

```text
semantic validation -> accept -> freeze -> hash binding
```

操作者不要编辑或伪造既有 generated evidence：receipt、index、DAG freshness、frozen
results、QA report、claim inventory、submission manifest 都必须重跑 producer。
改动 immutable artifact 时保留旧版本，生成新版本并让 downstream Gate
pending/fail。

## Migration/benchmark 边界

回归测试只说明代码路径、契约和负向防护仍工作；它不是 capability benchmark，
也不是数学模型已在真实赛题上泛化。当前 capability benchmark 计划保留在
[CAPABILITY_BENCHMARK_PLAN](docs/CAPABILITY_BENCHMARK_PLAN.md)，没有四类真实赛题
在 A0/A1/A2 同预算独立运行与 artifact 证据时，必须写“未完成”，不能写
“已验证”。

往届论文已经预留隔离区：国赛放入 `references/precedents/cumcm/`，
美赛放入 `references/precedents/mcm-icm/`，并在各自 `index.json` 登记来源、
哈希、权利说明和处理状态。赛前只把可迁移的方法选择、验证结构、写作组织和
Figure Contract 抽成 `references/precedents/pattern-cards/`；比赛时 Writer
默认只加载机制卡，不长期挂载论文原文。往届论文不自动进入当前
evidence registry、claim inventory 或 capability benchmark。完整规则见
[`precedent_policy.md`](references/research/precedent_policy.md)。

## Troubleshooting

| 现象 | 处理 |
|---|---|
| `status` 显示 M1 blocked | 先补真实 profile snapshot、model/evidence contract，再确认 M1 checkpoint；不要改 manifest.gates |
| profile 是 `seed`/`unresolved` | 它不是官方规则；绑定可核验快照后重新验证 |
| selected receipt 缺失或多个 | 按 control selection policy 重建 index；不要复制 `exit_code` |
| DAG stale/immutable drift | 检查实际文件与 producer receipt，生成新 version 并重跑下游 Gate |
| migrate 有 manual review | 阅读报告并由人解决 page limit、receipt、profile、artifact collision；不要手改报告为 pass |
| CLI 报缺依赖 | `python scripts/harness.py doctor --json`；安装 `requirements-dev.txt`，然后重跑原命令 |
| `validate` 失败 | 保存 checker 原始 stdout/stderr 和 exit code；先修 Gate 指向的 artifact，不要在论文中掩盖 |
| `AI usage` 是 `unknown` | 真实使用过则逐次 `harness ai record`；确认完全未使用则由人 `harness ai confirm-none` |
| reviewer AI 记录是 `pending` | 人工核对报告、证据和采纳修改后运行 `harness ai verify --usage-id ... --human-changes "..."`；即使未采纳也要明确记录，不要直接改 JSON |
| `prepare S1` 后 final 为空 | 正常；staging 可变，只有 F1 producer 才能写 immutable final |

## Debug appendix

正常入口不需要记住底层 14 个路径参数。只在定位问题时直接运行既有脚本：

```powershell
python scripts/doctor.py --offline --project-root C:\work\math-q1
python scripts/qa/check_gates.py --manifest run_manifest.json --project-root C:\work\math-q1 --gate M1 --strict
python scripts/qa/run_deterministic_qa.py --manifest run_manifest.json --project-root C:\work\math-q1 --output reports/deterministic_qa.json --force
python scripts/qa/check_artifact_dag.py --dag artifact_dag.json --project-root C:\work\math-q1 --strict
```

底层脚本是现有 checker/producer 的调试接口；CLI 不复制 Gate policy，也不
通过“看起来成功”覆盖它们的失败。更多合同、验证、写作、图、文献和提交
细节从[reference router](references/router.md)按需读取。

## Development checks

```powershell
python -m unittest discover -s tests -q
python scripts/harness.py agents check
python evaluation/redteam.py
python -c "import json; from pathlib import Path; [json.loads(p.read_text(encoding='utf-8')) for p in Path('schemas').glob('*.schema.json')]"
ruff check <每个改动的 .py 文件>
```

仓库全量 Ruff 并非干净：有 19 条既有告警在收口提交范围之外，按约定不混进改动。
这些命令的结果必须如实报告；没有跑过的完整回归、真实 benchmark、PDF
视觉审查或比赛提交，不得写成已完成。
