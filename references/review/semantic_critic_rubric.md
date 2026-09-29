# Semantic Critic Rubric

Semantic Critic 是证据-aware 的语义审查者，负责 research correctness / semantic
integrity；不是 formatting beautifier，不做文件存在性或哈希检查，也不输出
deterministic PASS/FAIL 来替代确定性 checker。

## 执行契约

- 入口：`harness review`（编排、bundle、校验由 Harness 负责；本 rubric 只定义
  审查内容）。报告按 `schemas/review_report.schema.json` 落盘到
  `reports/review/semantic_critic-<runid>-<ts>.json`。
- `review_mode` 与 `independence_level` 一一对应（self_critic→L0、
  fresh_context→L1、independent_model→L2、human→L3），不得跨级声明；
  research 下 L0 fallback 必须显式 `degraded_independence: true`。
- `reviewed_artifacts` 只使用 bundle manifest 中同时具有非空 `artifact_id` 和
  `source_path` 的 canonical rows：`path=source_path`，并复制
  `artifact_id/role/sha256`；rules/structural seed 只供审查，不登记为 reviewed
  artifact。freshness 由 Gate 对项目真源字节重算。
- fresh review（L1+）只读取 review bundle 内材料；Writer reasoning、旧
  reviewer 结论、上一轮 verdict、修订讨论一律不读、不进 bundle。
- 报告至少绑定 `model_contract`、`frozen_results`、`evidence_registry` 和
  `paper|pdf`；缺一类即为不完整审查，不能通过 W2。
- `available_evidence_scope` 与 independence 分开声明，只能等于或低于 bundle
  artifact 所支持的范围。需要更强证据的 blocker/high/medium finding 必须写
  `required_evidence_scope` 与 `requires_external_check: true`，不能靠 confidence
  或自由文本 locator 自行升级。当前 bundle 最高支持 `result_artifacts`；reviewer
  进程收据不等于模型复跑证据，不能据此声明 `rerunnable`。

## 检查面

1. 题目每个子问题是否有明确 conclusion type。
2. model_contract 的假设、变量、单位、目标和约束是否兑现到代码和结果。
3. 每个关键 claim 是否有足够的 evidence，且 evidence 的边界没有被扩大。
4. 比较/提升/最优等表述是否明确 baseline、指标和统计口径。
5. Figure Contract 是否真正支撑 claim，是否存在装饰性或重复图。
6. 摘要、正文、结论和推荐方案是否引用同一批冻结结果。
7. 结论是否承认敏感性、稳健性、数据范围和其他限制。
8. central thesis 是否只综合少量 decisive claim，而不是按题号堆数字；argument units 是否区分 model choice、结果观察、比较、验证、解释与边界。
9. Observation 是否被误写为因果解释；Inference/Recommendation 是否有支持、替代解释和前置 claim；强评价词是否与 comparison contract 一致。
10. problem → model 对齐、decision-time information set、objective identity、
    constraint semantics、leakage、validation sufficiency、baseline 比较与
    unsupported optimality / causal overclaim 的结论边界。

对高影响的“最优/必须/单调”结论，进一步核对求导或比较的变量与论文结论是否一致；
局部成本式是否足以推出联合优化结论；额外信息是否可以被策略忽略；KKT 或等价
推导是否遗漏约束活跃性和可行域前提。给出能定位的源行、反例或缺失前提；
启发式数值观察不能被当作一般性定理。若判断需要重跑模型代码，使用既有
`requires_external_check` 标记，不能凭 bundle 自称已经复算。

## 回执格式

只输出符合 `review_report.schema.json` 的正式报告，不使用另一个简化回执。
顶层必须包括 schema/report/run identity、mode/independence、reviewed_at、
reviewed_artifacts、findings 和 verdict；fresh/backend 路径还必须绑定
bundle_ref 与 execution_receipt_ref。finding 使用 finding_id / perspective /
severity / summary / evidence_locator / affected_artifact / affected_claim_id /
required_fix / confidence / status；需要越出当前 bundle 核验时再写
required_evidence_scope / requires_external_check。只有 `verdict=pass`
且没有 open blocker/high/medium 时，W2 review 条件才可能满足；verdict 由报告声明、
由确定性校验复核。

严重度：`blocker` 影响正确性/规则/复现安全；`high` 很可能改变结论可信度；
`medium` 应在本轮修复或明确接受（accepted_risk 需写明理由）；`low` 只影响润色。

## Prose-semantic pass

For each drafted section, also review reasoning quality rather than repeating
schema, hash, path, bibliography, or registered-number checks. Report findings
in the normal `review_report` contract; a section-local `review.md` may be a
working projection, never a Gate substitute.

Look specifically for:

1. 100–200 word paragraphs that add no mechanism, constraint, result boundary,
   comparison, or decision;
2. formula narration that names an equation without explaining what its terms
   mean or why the relation fits the problem;
3. figure/table narration that only says what is displayed rather than why the
   evidence changes the reader's conclusion;
4. repeated template phrasing such as “为了…/本文…/由此可见…/具有较好…”, where
   replacing the topic would leave the paragraph unchanged;
5. a logical jump between paragraphs, an unexplained numerical change, or a
   circular claim that a model works because it is powerful; and
6. an observation promoted to mechanism, causal statement, optimality claim,
   or recommendation without the necessary comparison and boundary.

Give particular attention to these logic gaps:

7. **Information gain** — if removing a paragraph would leave the paper's
   facts, mechanism, reasoning, or boundary unchanged, report
   `LOW_INFORMATION_PARAGRAPH` and name the missing contribution;
8. **Mechanism bridge** — if a real-world problem jumps directly to equations
   without the mechanism, variable relationship, or constraint that connects
   them, report `MISSING_MECHANISM_BRIDGE`; and
9. **Cross-section repetition** — report duplicated assumptions, definitions,
   model introductions, abstract/conclusion restatements, or figure-caption
   narration that adds no new decision-relevant information.

These are semantic reviewer judgments, not lexical regex Gates. Do not infer a
finding merely from a short paragraph, repeated noun, or equation count; explain
the affected reasoning and the smallest revision that would restore it.

For every finding, name the exact section/paragraph or figure, why it impairs
reasoning, and the minimum revision required. Do not emit a synthetic numeric
score such as `87/100`.
