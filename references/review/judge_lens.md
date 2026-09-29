# Judge Lens

Judge Lens 是"竞赛评委阅读质量"的 issue-only 审查视角：检查论文是否能让评委在
有限时间内找到完整、可信、可定位的答案。它不负责语义正确性（那是 Semantic
Critic 的职责），也不做任何确定性文件/哈希检查。

## 输入

只读取 review bundle 内的 allow-list 材料：当前论文（paper/abstract/conclusion）、
paper plan、model contract、frozen results、presentation contract，以及
`judge_scan_structural.json`（确定性结构扫描的 pre-seed candidate findings，
来自 `check_paper_style.py --judge-scan`）。结构扫描的启发式命中只作为候选
线索，Judge Lens 必须逐条核实后才能写入 findings。
报告至少绑定 `paper|pdf`、`abstract` 和 `conclusion` 三类 canonical artifact。

## 检查面

1. 题目每个小问是否都有明确、可定位的完整回答；缺答或含糊作答是 high。
2. 摘要是否在前 30 秒暴露：用什么模型、核心结果数字、主要结论与验证手段。
3. 关键贡献是否容易被找到（章节、图表、结论的位置是否可预期）。
4. 每处模型复杂度是否有可说明的收益；"复杂但无收益"记 medium 以上。
5. 图表是否降低而不是增加阅读成本（信息密度、位置、与正文距离）。
6. 结论是否容易定位，且与摘要核心结论一致；不一致记 high。
7. 创新点声明是否有 evidence 绑定；无证据的创新声明记 high。
8. 是否存在"工作量大但重点不清"的评委风险（堆砌模型/表格/图但主线模糊）。
9. 阅读顺序是否自然（符号先定义后使用、小问顺序与题目一致）。
10. 是否存在评委可见硬伤（未定义符号、单位缺失、表格断行、图不可读）。
11. figure/table 与 narrative 是否一致（图说与正文结论矛盾记 high）。
12. 明显的 competition-review 风险（超页风险、模板违规迹象、AI 声明缺失迹象）。

对多问题论文，在实际渲染页中逐问找“可执行方案/结果/解释/建议”；若主答案
藏在长证明或调试过程之后，指出页码与读者需要寻找的答案。区分可执行策略、
启发式实验和事后全知下界的版面标签；不可把草稿诊断或未核验的页数规则当作
官方评审判定。

## 边界

- 默认 issue-only：只输出 findings，不打分。
- 禁止生成官方评分、国一概率、获奖概率或任何虚构 judge score。
- 不得输出 deterministic PASS/FAIL 来替代确定性 checker。
- 不得修改论文；只描述问题、定位证据、要求修复。
- severity：`blocker` 表示明确违规或使提交不可用的风险；`high` 很可能改变评审印象；
  `medium` 应修复或明确接受；`low` 润色建议。

## 回执

按 `schemas/review_report.schema.json` 写报告：`perspective=judge_lens`，
findings 逐条带 `finding_id/evidence_locator/required_fix/status`，
`verdict=pass` 仅当无 open blocker/high/medium。`reviewed_artifacts` 只取 bundle
manifest 中具有非空 `artifact_id` 与 `source_path` 的 canonical rows：
`path=source_path` 并复制 `artifact_id/role/sha256`；rules/structural seed 不登记。
