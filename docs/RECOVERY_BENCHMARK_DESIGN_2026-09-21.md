# Recovery Benchmark 设计（C0，2026-09-21 目标稿）

> 状态：设计 + C1 slim fixture 落地中。**在任何 C4b（agent 驱动）真实运行之前，本文件不产生任何 recovery 数字**；所有指标列一律 `NOT_RUN`（`evaluation/PREREGISTRATION.md` 仍是评测协议唯一真源）。

## 0. 问题定义

red-team（`evaluation/redteam.py`）回答"Harness 能否阻止错误状态被接受"；recovery benchmark 回答下一个问题：

> Harness 报出 blocker 之后，能否按最小代价修回来？

三个条件（对照 `evaluation/PREREGISTRATION.md` 的 3-condition 能力评测）：

| 条件 | 含义 |
| --- | --- |
| C4a scripted repairer | 只验证恢复**通道**：确定性脚本按 `minimal_repair_set` 修复，证明"检测→修复→复检"管线可走通。不产生能力数字。 |
| C4b agent 驱动 | Agent 通过 MCP/runtime 只读面自行 localize 并修复，产生 recovery 指标。 |
| C4c no-harness 基线 | 无 blocker 反馈时的盲目重跑，用于计算 `unnecessary_rerun_ratio` 的分母参照。 |

## 1. Recovery Loop（注入 → 检测 → 修复 → 复检）

```text
inject fault (faults/F0X/inject.py --project-root <P>)
    ↓
detect: harness status --json   (blocker 定位：first_blocked_gate /
        failures_summary.items / dag.stale_artifacts / receipts.errors)
    ↓  或 harness check <GATE> --json（errors 文本）
plan: scripts/qa/plan_selective_rerun.py --json-output（拓扑 rerun_steps）
    ↓
repair: 最小修复集，每步经 harness execute / freeze 留 receipt
    ↓  （恢复编排经 scripts/runtime/ 只读面取状态，不另起第二实现）
re-check: harness status / harness check <GATE> 必须回到 PASS
```

## 2. 故障清单（F01–F10）

来源：`docs/math_modeling_evidence_harness_upgrade_roadmap_updated.md` §5.1。每个故障一个目录 `evaluation/recovery/faults/<F0X>_<slug>/`，含：

- `fault.json`：`fault_id`、`name`、`attack_surface`（被篡改的文件/字段）、`mutation`（动作描述）、`expected_detection`（工具、gate、error 子串）、`minimal_repair_set`（最少需重建/重登记的 artifact）。
- `inject.py`：`--project-root` 幂等注入，stdout 输出 `{"ok": true, "fault_id": ..., "mutations": [...]}`。

| ID | 故障 | 期望检测点 | slim fixture 可注入 |
| --- | --- | --- | --- |
| F01 | model_contract 被编辑 | `harness check M1`：artifact SHA-256 drift | 是 |
| F02 | 上游 artifact hash drift | `harness check M1/P2`：`{role} artifact SHA-256 drift` | 是 |
| F03 | frozen result 删除 | `harness check P2`：frozen digest/存在性错误 | 是 |
| F04 | receipt/result 绑定错配 | `harness check P2`：`frozen_results is not bound to the selected full receipt` | 是 |
| F05 | stale review | `harness validate`（W2）：stale/invalidated artifacts | 是（fixture 走到 W2） |
| F06 | sensitivity run timeout | check_sensitivity_experiment | 需扩展 fixture（sensitivity 产物），暂记 gap |
| F07 | implementation_map drift | check_implementation_map | 需扩展 fixture，暂记 gap |
| F08 | 无证据数值 claim | W2 claim↔evidence 检查 | 是（redteam 已证 blocked，注入器复用同一攻击面） |
| F09 | citation 来源失效 | check_citations | 是（若 fixture paper 含引用；否则记 gap） |
| F10 | 错误参数 provenance | M1 model contract 语义检查 | 视 fixture contract 字段而定 |

**规则**：注入后 `harness status` / `harness validate` 检不出 blocker 就是发现——把 gap 回写本文件 §6，**不得**放宽检测断言、不得为了让测试通过而跳过故障。

## 3. 指标定义

| 指标 | 定义 | 数据来源 |
| --- | --- | --- |
| Recovery Success Rate | 复检回到 PASS 的故障比例 | re-check 退出码 |
| Mean Repair Steps | 每个故障的实际修复动作数 | 恢复编排日志（每步 receipt） |
| Mean Tool Calls | agent 侧工具调用次数（仅 C4b） | agent 运行日志 |
| Recovery Token Cost | 修复消耗 token（仅 C4b） | agent 运行日志 |
| Recovery Wall Time | 注入→复检 PASS 墙钟时间 | 编排日志时间戳 |
| Unnecessary Rerun Ratio | (实际重跑 artifact − minimal_repair_set 必需 artifact) / 实际重跑 artifact | rerun_steps ∩ 重跑 receipt argv vs `fault.json.minimal_repair_set` |
| Wrong Repair Rate | 修复后引入新 blocker 的比例 | re-check 时新增 errors |
| Regression Introduced Rate | 修复后此前 PASS 的 gate 变 FAIL 的比例 | 全 gate 复检对比 |

PASS/FAIL 判定（单故障）：

- **PASS**：复检目标 gate PASS，且无新增 blocker，且重跑集合 ⊇ minimal_repair_set。
- **FAIL**：复检未回 PASS，或修复引入新 blocker。
- 指标汇总只在 C4a 通道验证 + C4b 真实运行后写入 `evaluation/PREREGISTRATION.md` 修订版；README 不得引用。

## 4. C1 slim fixture（每轮生成，不入库）

- 形状取自 `battle/2026-08-17` 的 v2 项目结构，**不含任何竞赛原文**；由 `evaluation/recovery/fixtures/build_slim_fixture.py` 调 `examples/end_to_end/run_demo.py` 的同一套 helpers（`Demo`/`build`/`refresh_dag`/`add_checkpoint`）生成，不设第二实现。
- **生成而非提交**，与 `evaluation/redteam.py::built_project` 同一约定，原因有两条（都是 CI 实测教训，见 §6 GAP-R3）：
  1. receipt 的 I/O 摘要与 DAG 摘要是对**确切文件字节**求值，Git 的行尾归一化（Windows `core.autocrlf=true`）会让 Linux checkout 后每个 artifact 都读成 stale；
  2. review 证据绑定生成时的**绝对路径**，任何重定位都会让 W2 因路径而非故障失败——那会让"检出"变成假绿。
- `tests/_recovery_baseline.py` 每轮构建一次并缓存，故障/修复测试各自 `copytree` 克隆。
- 覆盖生命周期：S0 init → M1（contract + registry + checkpoint）→ P1 smoke → P2 full + freeze → W1/W2（paper + review），即全 gate PASS 的最小项目。
- 回归锁：`tests/test_recovery_fixture.py`（逐文件 schema 校验 + 全 gate/validate 绿）；`tests/test_recovery_faults.py` 在注入前先断言**该克隆自身**在 M1/P1/P2（validate 类故障还含 W2，需先做一次 scripted 重审以复位搬迁噪声）为绿，再断言注入后报出预期 blocker——保证 delta 可归因。

## 5. 恢复执行端（GAP-08）

已实现 `evaluation/recovery/repair.py`：

1. 输入：项目根 + 目标 gate + `--changed`（透传给 planner；或直接给 `--plan`）。planner 拒绝出计划时（如 artifact 文件已删除），从其 stdout 载荷仍取 `rerun_steps`。
2. 步骤分类（不新增第二套读取/判定实现，状态经 `scripts/runtime/` 的 `check_gate` 取回）：
   - `rerun`：产物有 producer receipt（经 run_index 的 `output_refs` 反查）且 stage ∈ {smoke, full, freeze}——用 `harness execute` 重放记录的 argv（重写旧项目根拼写，含 Windows 8.3 短名两种形态），每步留新 receipt；freeze stage 带有 `--freeze` 与 `--supersedes-receipt` 声明新 generation；
   - `contract_blocked`：无 automated rerun 通道的产物（如 review 阶段）；
   - `author_plane`：作者平面产物无 producer receipt——记录为需重做/重审。
3. 复检目标 gate，写 `.harness/recovery/<fault_id>.json`（步骤、receipt 路径、gate 报告、repaired 判定）；`repaired` = gate PASS 且目标 gate 所需的重跑步骤均已成功执行。
4. 修复器自身绝不手写改写 artifact、receipt、hash 或 verdict。

## 6. 已知 gap（动态回写）

- **GAP-R1 [已闭合 2026-09-22]：freeze 产物合规修复通道。** 通过引入最小可行 receipt supersession 机制（`supersedes_receipt_id` 与自增 `generation`），历史 freeze receipt 保持不可变并继续可审计；P2 门禁校验当前状态下 active valid freeze lineage 恰好为 1 条。F03（deleted frozen results）和 F04（binding mismatch）均已走通合法 `repair.py` 恢复通道并使 P2 真实 PASS。
- **GAP-R2 [已闭合 2026-09-22]：slim fixture 增加 receipt-backed DAG 产物。** 在 `examples/end_to_end/run_demo.py` 中为 `full` 阶段显式绑定 `raw_results.json` DAG 节点及其 producer receipt。当 upstream 数据被篡改时，`repair.py` 能端到端联动 selective rerun full execution → freeze execution → P2 PASS。
- **GAP-R3（2026-09-18 CI 实测）：按字节固化的证据不能进版本库。** 初版把 fixture 提交在 `evaluation/recovery/fixtures/slim_v2/`，Linux CI 上 8 个 DAG artifact 全部读成 `digest_drift`（`core.autocrlf` 把 CRLF 存成 LF），且 review 证据绑死生成时的绝对路径。现改为每轮生成（§4）。**遗留事实**：v2 的 review 平面整体不可搬迁——重定位后 W2 必红，除非重跑 `harness review`；任何需要跨机比对 W2 的评测都必须先重建 review 证据。
- F06 sensitivity、F07 implementation_map 所需产物不在 slim fixture 中——恢复矩阵以 §2 表格"可注入"列为准。

## 7. 不做什么

- 不在本文件出现任何 recovery 数字（C4b 未跑）。
- scripted repairer（C4a）只用于验证通道，其运行结果不进入 README/论文叙述。
- 不修改 Gate 判定逻辑来"让修复变容易"。
