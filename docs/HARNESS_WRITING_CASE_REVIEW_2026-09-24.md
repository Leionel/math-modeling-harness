# 真实 C 题写作案例：论文与 Harness 修改意见

日期：2026-09-24。对象：`2026c_qwen3.8f/result/`。本次为只读审阅；未修改赛题项目、合同、Gate 或收据。当前项目的 M1 阻断是真实状态，自动代理不能代替人的 checkpoint；下述写作问题也不能靠把 M1 强行放行解决。

## 总判断

这份 TeX 有模型、计算和大量检验，但成稿更像**求解与验证的技术报告**，不像围绕赛题逐问给出方案、结果、解释和建议的数模论文。更严重的是，部分从公式推到结论的论证不成立。编译成功、宏值可追溯、交付表回读通过，只覆盖工程一致性，不能为写作和数学判断背书。

Harness 已有完整的 Gate、确定性 QA 与独立 review 设计。本项目在 M1 被挡住后，用户仍可在 Gate 外直接写 TeX、编译探索稿；这本身不构成 Gate 绕过，但当前草稿缺少统一、及时的诊断，`paper_plan` 与最终版面也没有闭环。因此修改重点是**让真实草稿及其 PDF 暴露可审阅的问题，并让正式语义审稿收到完整成稿**，而不是增设一个自动打分的“论文质量 PASS”。

## 一、先修论证与结论

| 优先级 | 本例证据 | 论文修改意见 | Harness 修改意见 |
|---|---|---|---|
| P0 | `paper/sections/body.tex:316-336,448-453`：由结算函数在承诺量两侧对 $a$ 的斜率为 $0.5\pi/1.5\pi$，直接推出“最优日前计划系统性低于无偏预报”。但对固定实际承诺量 $a$ 求**计划量** $p$ 的导数，两侧分别是 $+0.5\pi$ 与 $-0.5\pi$；简化随机模型下最优 $p$ 是 $a$ 的中位数，不能仅凭 3:1 的斜率断定必须降额。储能、紧急购电可能改变联合最优，须另行证明或只称“在本次扫描中降额有益”。 | 删除“数学依据”“天然偏保守”等一般性推论；给出针对所用目标函数和信息集的推导，或把降额明确定位为经验策略。 | W2 数学审稿增加“被优化的变量是否与求导变量一致”“从局部结算式到全局策略是否跨越未证前提”的反例检查；保留人工/独立 reviewer 判定，不用关键词代替代数审查。 |
| P0 | `body.tex:57-63,219-279`，题面 `problem/C_problem_text.md:74-80`：题目要求每天 0:00 制定当天计划；正文把当天实际负载、光伏和全年 365 天数据视作 0:00 完全预知，并将全年耦合 LP 放在主答案位置。历史附件可用于事后回放，但“可执行的日前策略”与“事后全知下界”不是同一声明。 | 在 Q2 开头写清信息边界；分别报告可在 0:00 执行的方案和完全预知的参考下界。若把附件 2 当作赛题允许的全知输入，明确依据和局限，避免把全年耦合最优写成日常决策策略。Q4-Q2 同步修订。 | 先复用 `model_contract.decision_context`、数据列可用性和 `required_answer.reporting_semantics`，标清操作策略与事后 oracle。W2 reviewer 核对“计划时是否读取未来实际值”；不能仅检查程序没有访问越界数组。 |
| P0 | `body.tex:404-465,769-774`：15 对嵌套报文子集里 14 对“多用报文更贵”，正文却用它归纳“加密报文不是省钱的主要手段”。多一个报文时策略总可选择忽略它，因此**最优策略**的费用不应上升；反常结果说明现有滚动启发式和结算/执行口径需要解释。正文局限承认“非策略最优”，主结论仍外推过宽。 | 把结论改成“在本启发式、当前年度与结算口径下，新增/使用报文未带来稳定收益”；展示与同窗口、同可行动作的对照，并把违反信息单调性的实验列为算法局限。 | 为信息价值类 claim 设置审稿问题：比较的策略集合是否嵌套、额外信息是否允许忽略、比较时执行窗口是否相同；出现反常单调性时必须有专门解释或降级 claim。 |
| P1 | `body.tex:184-195,574-577`：命题 3 写价格比“锁定为 $\eta^2$”，随后消元写的是 $1/\eta^2$；其 KKT 等式还隐含充/放电功率未卡上界、边际外购为正等条件。另“只要存在价差最优解必须调用储能”遗漏可行充放电对及容量/状态条件。 | 改正比值，并补全命题成立前提；无法给出严谨条件时，把“必须”降为本算例的观察，将完整对偶推导移至附录。 | 数学审稿加入命题前提、约束活跃性及“必要/充分”措辞检查；以本例的反例构造为回归材料。 |

## 二、按数模论文重新组织

1. **重写摘要。** `paper/sections/abstract.tex` 的内容在当前 27 页 PDF 中占第 1–2 页；`paper_plan.json:402-405` 明定“1 页内”，`precision_policy.abstract_max_numeric_claims=6`，实际摘要塞进大量审计数字、参数扫描、DP/MILP 细节。摘要应以“问题—模型—各问关键结果—主要建议—边界”组织，原则上让评委在第一页看完；误差对齐、收据式检验细节进入正文/附录。当前检查器 `scripts/qa/check_consistency.py:406-409` 只数计划中的 `abstract_results[]` 条目，不数最终摘要的数字，也不看 PDF 页数。
2. **每问先回答，再证明。** Q1 主结果到 `body.tex:198` 才出现，前面已连续陈述三条命题；Q2 把紧急购电退化证明放在策略与四日期结果之前；Q3 对照实验和启发式细节远多于可执行策略。每问建议固定阅读路径：信息与目标 → 模型/算法（必要公式）→ 指定日期或年度结果 → 决策解释 → 一项最能推翻结论的验证。保留关键推导，网格公度、全量扰动、调试史和大量过程表移到附录或支撑材料。
3. **补真正的结论与建议。** `paper_plan.json:490-495` 要求结论收束四问并给可执行建议；实际 `body.tex` 在“模型的评价与推广”后直接进入参考文献和附录，没有独立结论节。末段应明确：采用哪一种日前/滚动策略、何时调整、哪些费用是全知下界、哪些收益只适用于该启发式、题目数据不能确定什么。
4. **删“自我审计式”正文。** 七条命题的长证明、随机小样本差分、破平局成本、回读工作簿、开发阶段符号错误等可以支撑可信度，却不该占据叙事中心。`body.tex:745-753` 的“模型的优点”以模型自评取代读者可核对的决策解释。图表优先展示负载/PV/购电/储能的关键关系和四问结果；不要让“验证了多少项”成为摘要的结尾。
5. **处理引文。** `body.tex:796-819` 手列八条文献，整篇 `body.tex` 未发现 `\cite`，读者无法知道每条文献支撑哪个假设或方法；项目报告又注明全文均未核验。保留真正使用且可核验的来源，并在相关论述处引用；未核验文献不能作为已验证方法依据。`run_deterministic_qa.py:595-608` 只有同时提供 TeX 和 Bib 才调用 citation checker，手写 `enumerate` 参考文献可绕开它。

## 三、文件夹其余位置暴露的质量闭环缺口

- **作者计划与成稿脱节。** `paper/00_PAPER_PLAN.md` 仍是空模板，`00_PROJECT_BRIEF.md`、`03_SOLUTION_REPORT.md` 同样未填写；机器 `paper_plan.yaml/json` 虽有内容，却没有让作者先决定叙事取舍。`paper_plan.json` 甚至明确有独立结论和摘要预算，但 `main.tex` 只输入 `abstract.tex` 与 `body.tex`。Harness 应展示“机器计划已就绪、作者导演稿未形成、渲染版与计划不一致”三种不同状态，不能将 `status: ready` 解释为写作已准备充分。
- **报告漂移。** `reports/competition_compliance.md:25-27` 写“21 页”且称作者字段已隐去；当前 `main.pdf` 为 27 页，`paper/metadata.tex:4-7` 则硬编码了虚构的队号、学校和成员名。旧 `reports/final_run_report.md:101-104` 的 Q3/Q4 数值也不同于当前摘要；`reports/round2_status.md` 说旧报告数字作废。应把这些自由文本报告标成历史快照，并生成当前状态投影；凡对外复述当前费用、页数、身份/匿名状况，须从当前冻结结果和 TeX/PDF 重算。不要按未核验 seed 的 25 页上限直接宣称违规。
- **编译成功不等于版面合格。** `paper/main.log` 在命题段有多处 `Overfull \hbox`，最大约 465 pt；当前 PDF 摘要跨页。对正式稿，扫描 log 的严重越界、关键节是否缺失、摘要页数和截图可读性；普通 `h` 浮动体警告不需与内容错误同级。
- **TeX 元数据缺少内容核对。** `scripts/latex/template_usage.py:42-114` 检查 document class、输入路径及模板资产，但未核查实际 `metadata.tex` 中的占位/虚构身份，也未交叉核对合规报告。这里需要一条 source-tree 级别的报告核验，而非只检查入口文件 `main.tex`。
- **选中运行的输出也有字节漂移。** `run_index.json` 选择 `REC-20b1c6e69b484270`，其 receipt 对 `results/selected_full.json` 记录的 SHA-256 为 `030e9028…`；2026-09-24 实际文件为 `759a7c7f…`，且 `artifact_dag.json` 目前仅登记一个 competition profile 节点。这说明“已经有选中 receipt”和“当前文件仍对应那次运行”必须分开呈现；不能据此推断某个后续 Gate 曾放行。现有 P2 检查会重算选中输出，但 M1 先阻断时用户难以从首个 Gate 摘要看到此项。
- **M1/W2 状态必须诚实。** 当前 `.harness/views/W2_STATE.md:20-24,40-50` 显示最早阻断仍在 M1、正式 semantic/judge review 未执行。已经生成 PDF 只是探索性草稿。用户要求代理自动跑而代理拒绝替人审批，是边界按设计生效；本案的写作问题发生在 Gate 外的探索稿中，正式写作 QA 和 review 尚未运行。

## 四、先核对现有能力，定位需要改的接线

| 已有机制 | 已确认的边界 | 本轮改动落点 |
|---|---|---|
| `harness paper plan/write/review` 生成作者表面和 section brief；`writer_package`、`reverse_outline` 已存在 | `scripts/harness.py` 的 `paper review` 仍是准备 section 表面，并不调用正式 `harness review`。作者可直接写 TeX；空 `00_PAPER_PLAN.md` 与有内容的机器 YAML/JSON 没有清楚的状态提示 | 在作者路径上增加草稿诊断入口和“下一步需要什么”的提示，不把空 Markdown 自动提升为 Gate 错误 |
| `audit_paper_length.py` 会展开 `\input` 并读取 PDF 总页数；`check_pdf.py` 可做渲染 QA | 长度审计没有判定摘要跨页或独立结论；`check_paper_style.py`、`check_math_writing.py` 与部分一致性检查按传入单文件读取，入口 `main.tex` 可能只含 `\input` | 抽取安全的共享 TeX 树读取器，令相关检查和审稿看到同一份可见正文；版面问题结合已存在的 PDF/log 核查 |
| W2 要求 canonical `abstract/paper/conclusion`，按 profile 要求 writer package、PDF、文献和 review；`semantic_critic` 与 `judge_lens` rubric 已覆盖信息时点、最优性和评委阅读 | 本案没有登记完整 W2 角色，M1 先阻断；正式 review **未运行**。即使将 `main.tex` 作为 `paper` 角色登记，`run_review.py::build_bundle` 当前也是逐角色复制单个文件，子 TeX 未必进入 reviewer 的阅读材料 | 先保证材料完整、绑定当前字节，再用现有 rubric 做针对性审查；不能把当前问题说成 W2 曾错误放行 |
| `check_citations.py` 可核对 TeX/Bib 引用及核验过的来源；`run_deterministic_qa.py` 有 citation 检查 | 两个路径同时提供才运行；手列参考文献、无 `\cite` 时为 `not_applicable`，不等于已核验。`check_consistency.py` 的摘要数字上限只数计划条目 | 输出“手列文献缺正文定位”“最终摘要数字与版面待审”等明确的诊断，不推断所有无 `\cite` 文献均造假 |
| `harness status` 投影 receipt/DAG，Gate 顺序保持 fail closed | `harness_status.py::_v2_status` 在首个 blocked Gate 停止；receipt 摘要不核算选中输出字节，用户需等到 P2 才见对应错误 | 加独立的只读预诊断，按“外部规则/人工决策/合同缺件/字节漂移/写作草稿”分组，不更改 Gate 的首阻断语义 |

**判定边界：** 本文的 P0 是改进“草稿可观察性”和“审稿材料完整性”；它并不允许在 M1 未过时写 P2/W2 PASS，也不替人执行 `checkpoint approve`。自动代理可以跑只读诊断、整理待办和继续 Gate 外探索，但不能把探索稿称作已通过的论文。

## 五、改造包 A：只读草稿审阅入口（P0，第一优先）

**对外契约。** 增加 `harness paper audit --project <root> --tex paper/main.tex [--pdf paper/main.pdf] [--log paper/main.log] [--plan .harness/contracts/paper_plan.json] --json`。命令不编译、不建目录、不修改项目或 Gate；JSON 写到标准输出。退出码约定为：`0` 完成且无高严重度问题，`1` 完成且发现高严重度问题，`2` 输入不存在、TeX 树不完整或参数错误。输出必须含 `gate_effect: none`、输入路径和摘要哈希、`findings[]`、`skipped_checks[]`、`source_binding`（已由构建回执证明/未经证明）。仅当构建回执的源树和 PDF 字节摘要都与现物相符时才写“已绑定”；现有 `safe_build` 的 dev/research 收据无源树哈希，仍记“未经证明”。缺 PDF 时仍可做源文本检查，版面检查列为 `skipped`；缺计划则只做独立检查，不补造计划。

**实现路径。**

1. 把 `check_writer_package.py`、`audit_paper_length.py` 和 `check_citations.py` 各自的 `\input/\include` 遍历收敛成一个有文件/行号映射的读取器，保留原检查器对可见文本的语义。对缺失的子文件、循环引用、项目外引用报告明确错误；不能悄悄当作空正文。复杂宏生成的动态输入无法静态展开时给 `unknown`，不写“已审完整”。所有读取只发生在用户指定的项目根内；review bundle 后续也复用同一清单。
2. 借用 `audit_paper_length.evaluate_length_audit` 和 `pdfinfo`，检查总页数与 profile 中**已核验**的规则。摘要跨页通过现有 PDF 的逐页文字/可见标题定位；无法明确定位摘要起止页时输出“需人工查看”，不能凭 TeX 行数断定。`check_pdf.py` 的正式渲染与视觉回执仍归原流程，不为只读命令再跑构建。
3. 对照 `paper_plan.sections` 和 TeX 可见标题，报告“计划有结论，但当前正文无可定位结论”；对各问先问后答和证明压过结果，仅提供候选线索给作者/评委 reviewer，不用章节关键词计数直接定性写作质量。复用 `reverse_outline` 的顺序与重复扫描，检查的是正文内容，不是只有 `\input` 的入口文件。
4. 扫描现有 log 的明确 `Overfull \hbox` 幅度及源行；大的越界列为版面高优先级候选，最终以 PDF 截图核实。识别固定的空值、模板占位符及源码与既有**结构化**提交声明的冲突；若比赛规则/身份声明未核验，只报风险，不自行断言“违反匿名规定”。手列参考文献却无正文定位则报“引用映射缺失”，后续由文献证据链验证具体条目。
5. 只核对有机器身份的数字（claim/result ID、冻结值、PDF 页数、构建收据）。旧自由文本报告不做模糊数字抽取，也不因文字碰巧一致而视作 current；见改造包 E。摘要“数字太密”属于评委可读性候选，不拿计划的 `abstract_results[]` 数量冒充实际可见数字数。

**最小验收。** 匿名缩小夹具保留 `main.tex → abstract/body/metadata.tex`、缺结论、2 页摘要、明显 overfull、手列无正文引文。命令必须定位这些源文件/页、返回 `1`，且执行前后项目树的内容哈希不变。给出修正版本应返回 `0` 或只剩明确的人工候选；缺 PDF 应为成功的源文本诊断并列出跳过项。包含项目外 `\input` 的负例必须返回 `2`，不能读入项目外文件。

## 六、改造包 B：W2 看完整论文、审真实论证（P0，依赖 A）

**材料闭环。** 在 `run_review.py::build_bundle` 中，保持现有 allow-list 与 reviewer 隔离策略，同时提供由 canonical `paper` 入口解析出的 TeX 依赖清单和可阅读的正文快照；已登记的 canonical PDF 也进入 bundle，供 Judge Lens 看真实版面。依赖文件作为 *context*，不伪装成独立的 reviewed artifact。清单逐项记录项目内相对路径和 SHA-256；W2 在接受 review 前重新核对这些子文件，任一变更使 review 过期。需要把这一校验接入 `review_evidence.py` 的现有 bundle/freshness 路径，并补 CLI 与 runtime 同判定测试；不能只在生成 bundle 时算一次哈希。

`check_paper_style.py`、`check_math_writing.py`、`check_consistency.py` 中针对正文的检查，也要在同一 TeX 树快照上执行。特别校验 `paper` 角色若指向 `main.tex`，不能因正文只写在 `body.tex` 而出现“零处强词/零处未定义结果”的假绿。对于只交 PDF 而无源树的受支持模式，reviewer 可审可见内容，但源级结论应记 `unverified`，依当前 profile 的 W2 要求判定是否足够。现有 `check_gates.py` 对 build receipt 有进一步要求；实施时需核对它与 `v2_gate_runtime.py` 的路径是否同口径，并以已有 Gate/API 持平测试锁定。

**语义审稿。** `semantic_critic_rubric.md` 已列 decision-time、objective identity、unsupported optimality；`judge_lens.md` 已列 30 秒摘要和“工作量大但重点不清”。在它们收到完整材料后，增加本例可复用的提问样例：

- 公式对谁求导，论文的结论却指向谁？结算式的局部斜率能否推出联合优化的全局策略？
- 决策时可见的是预报、历史还是当日/全年真实值？所谓最优是可执行策略值、启发式值，还是全知下界？
- “更多信息更贵”的比较是否允许忽略新信息？策略集合、窗口、结算口径是否相同？
- 命题写“必须/总是”时，互补松弛、边界约束、可行正负方向等前提是否齐全？
- 每一问是否先有可定位的答案，表/图是否帮助评委解释决策而非仅展示计算量？

review finding 继续使用现有 `review_report.schema.json`，必须指向正文页/源行、能定位的 claim、反例或缺失前提及最小修复。bundle 不含模型代码，reviewer 无法由此验证求解器复跑；需要代码证据的 finding 用既有 `required_evidence_scope`/`requires_external_check`，不能自行把 scope 升为 `rerunnable`。**验收**：`main.tex` 自身只有 `\input` 而 `body.tex` 有错误结论时，确定性正文检查与独立 reviewer 都实际看到正文；改动 `body.tex` 后旧 review 在 W2 判 stale；隔离测试仍证明旧 verdict、私有推理、无关草稿没有进入 bundle。语义反例采用至少一真一假的成对夹具，防止 reviewer 机械地见“最优”就判错。

## 七、改造包 C：把决策时信息边界前移（P1）

**先用现有字段，不平行造契约。** `model_contract.schema.json` 已有 `decision_context`（决策时刻、特征策略、目标时域、禁用未来特征），`data_contract.schema.json` 已有可用性与派生特征来源，`required_answer.reporting_semantics` 可说明答案口径，`paper_plan` 已有 claim 的证据和边界。先写一条跨合同核验：以模型声明的决策时点为基准，逐项核对模型**直接输入**及派生输入的可用性；`check_data_contract.py` 目前重点检查 `derived_feature_lineage`，原始实际值直接进入优化输入时可能漏报。实际数据已知、竞赛明确允许离线全知计算的场景仍可使用，但产物和论文必须标作事后 oracle 或赛题特定假设，不能无依据标“0:00 可执行”。

**比较口径。** 在写作计划或现有比较合同中绑定“被比较策略、可见信息集、动作集合、评估窗口、指标”。Q3 的信息单调性是审稿反例，不宜做一条“更多报文时费用必须下降”的硬规则；启发式可以表现更差，错误发生在把其结果外推成信息无价值或最优策略结论。若现有 `reporting_semantics` 自由文本不足以稳定连接结果与论文 claim，再提出一个最小枚举字段及迁移方案，届时同改 schema、checker、`references/contracts/` 与测试；本轮不先把 `operational_policy` 等新字段强加给所有旧项目。

**验收**：构造两条相同数值的运行，一条声明“当天实际值在 0:00 已知”，另一条声明“仅有日前预报”；前者如果没有规则依据，不得被核验为可执行策略，后者应通过；若标作 oracle 且论文明确边界，应允许其作为参考下界。还需一个信息比较负例，确保系统要求解释策略集合差异，而不是强制判启发式费用序列单调。报告区分“合同缺信息”“已确认未来泄漏”“论文口径过强”三个原因。

## 八、改造包 D：关键数学结论的反例与复算证据（P1）

现有 `model_contract.objective_contract`、`plan_details.derivation_graph`、公式前提、`validation_obligations`、`check_derivation_integrity.py` 和 `check_formula_replay.py` 已能表达并检查相当一部分推导结构。这些检查不能证明“对 $a$ 的斜率足以推出 $p$ 的最优方向”，也不能替代对 KKT 活跃约束的判断。改动应把**容易推翻主结论的最小反例**列为高风险 claim 的验证义务，而非增加一个声称自动证明定理的 checker。

在 M1 计划里，对含“最优、必须、系统性、单调”的核心结论明确登记：优化变量、对照目标、适用域、边界情形、可能使其失败的一组输入、对应 equation/claim ID。P1/P2 用可复算的微型输入或性质测试执行这些义务，结果通过既有进程 receipt、测量和 frozen result 链进入证据；Gate 外草稿可以先试反例，但试验日志不自动成为正式证据。W1 检查 claim 是否引用正确的验证与反证；W2 判断文字力度是否超出该验证覆盖的范围。

本案的三种回归形状：①固定实际量 $a$、扫描计划量 $p$ 的左右差分，与正文所用的导数方向对照；②对同一窗口的嵌套信息集，区分“允许忽略新报文的最优策略”与“本启发式的费用”，防止把启发式反常上升归咎于信息本身；③在储能功率上界活跃/不活跃的两种微型实例中检查命题 3 的价格比和 KKT 前提。每种都要有一个预期成立的正例和一个有意破坏前提的负例；若不满足前提，可以降级为数值观察并写明范围，不能维持一般性定理措辞。选中运行输出已漂移时，复算证据与它的数字引用应先标为 stale，不能靠补写论文文字掩盖。

**验收**：至少一条微型负例能给出被推翻的 claim ID、输入、计算差值/约束状态和可复跑命令；正例不被泛化规则误伤。检查器只核对可重算数值和证据连接，数学解释仍由独立 reviewer 作出。这个包可与 C1 并行设计，但正式验收依赖 A/B 的完整正文及 review 材料。

## 九、改造包 E：当前状态与历史报告（P1）

`harness status` 保留“遇到首个 blocked Gate 停止”的现有安全语义；另提供独立、只读的准备度诊断，不把未运行的 W2 显示成失败或成功。准备度按外部规则、待人决定、合同/角色缺失、选中输出字节漂移、草稿/版面候选分组，给出具体文件和下一条可执行命令。本案应同时显示“M1 正式阻断”“选中 receipt 输出 SHA 与当前文件不符”“未具备 W2 输入”“草稿 PDF 有版面问题”；后面三项是预诊断，不能冒充 Gate verdict。摘要不重复实现 P2 的 receipt 校验，应调用其已验证的选中输出核对逻辑或抽取同一函数。

历史 Markdown 报告保持原样并视为当时快照。新“当前摘要”只从现行 `run_index`、receipt、frozen results、DAG、paper/PDF 构建证据、review 报告投影，显示每项的 `run_id`、源路径、SHA 与检查时刻；缺任何绑定就写 `unverified`/`stale`，不能用旧报告的“21 页”等自由文字填空。允许人读历史报告，不允许把未绑定的自然语言声明自动升格为当前合规事实。元数据与官方规则未知时只能报待核，不给“匿名已通过”。

**验收**：改动选中输出一个字节，准备度诊断立即指出路径、receipt ID 与 hash drift；M1/W2 Gate 顺序与退出码不变。旧报告仍可读，新摘要明确显示旧数字无当前绑定；恢复原字节后漂移项消失，但不会自动产生新 receipt、freeze 或 review。

## 十、实施顺序、回归矩阵与决策边界

| 批次 | 最小交付与依赖 | 必须锁住的回归 |
|---|---|---|
| A1：统一 TeX 读取与 `paper audit` | 先有源文件清单和行号，再接现有长度/正文/引用检查；不依赖 M1 PASS | CLI `0/1/2`、多层 `\input`、缺子文件、项目外引用、无 PDF、项目树零写入、中文路径和 Windows 行尾 |
| B1：review 材料与 W2 freshness | 依赖 A1；先绑定 TeX 子文件和 PDF，再细化 rubric | 子文件变动使旧 review 失效；正式 W2 仍须 canonical roles、独立性和 checkpoint；不向 bundle 泄漏旧审稿或私有信息 |
| C1：决策信息核验 | 复用现有合同；若必须改字段，先给旧项目兼容策略 | oracle 与可执行策略成对正负例，原始/派生输入两类反例，已知合法离线情形不过拦 |
| D1：数学反例与复算义务 | 基于已有 objective/derivation/validation 合同；正式评审依赖 B1 | 同一 claim 的正负微型例、真实进程回执与验证引用、过强结论的降级路径 |
| E1：准备度与当前摘要 | 复用 receipt/DAG 核对，不改变 Gate 顺序 | 本案选中输出漂移可见、旧报告不被改写、缺角色显示未运行而非伪造 W2 FAIL |

**测试材料。** 从 `2026c_qwen3.8f/result` 手工提取不含真实赛题全文、原始数据、身份信息的最小 TeX 和合同形状；各案例同时保留“注入前应绿”的基线锁。PDF/TeX 渲染检查只在有真实 `latexmk/xelatex/pdfinfo/pdftotext` 的 CI job 运行，其他 job 验证纯文本与 JSON；按 `docs/EXECUTION_PLAN_2026-09-18.md` §10.9 的经验，由测试生成 fixture，不提交会被 CRLF/LF 改写打穿 digest 的逐字节固化目录。若新测试涉及 Windows 路径语义，加入 `windows-light` 显式清单，并用 `git archive` 导出核对哈希行为。

**评估方式。** 本文案例用于问题发现和回归，不能把“能检出本例”写成 Harness 能提升获奖率。工程指标可量 `draft_issue_detection_recall/false_positive_rate`、`review_material_completeness`、`stale_review_acceptance_rate`、从 M1 阻断到可修待办的定位时间、额外执行耗时；样例真值由独立人工标注并给出争议项。若要做路线图 P0-A/P0-B 的能力对比，须等 `evaluation/PREREGISTRATION.md` 的触发条件、任务集和运行器就绪后另行预注册，不能把这次单例审阅包装成 A/B/C 结果。

**不随本方案擅改的边界。** M1 的人工 checkpoint、官方规则未核验时的阻断、远端分支与未跟踪 roadmap 均保持现状；§10.8 的 receipt 链入 Gate、决策 artifact 链校验、GAP-R1/R2 仍需单独设计与用户决策。这里的改动无需 GUI，也不依赖先解决这些开放项。将来任何行为改动按仓库规则做一个功能一个 commit，契约同时更新 schema/checker/`references/`/测试；全量 unittest、redteam、Ruff、`harness agents check` 与推送前安全扫描通过后才推送。

**方案自检。** 本文给出输入、输出、责任模块、正负例和停步条件；尚未证明的只有“哪些 TeX/PDF 文本边界可以稳定自动定位”以及“现有 `reporting_semantics` 是否足以容纳 oracle/操作策略”。两者在 A1/C1 的最小夹具中先实测，无法稳定自动判定时保留 `unknown` 与人工审阅，不扩张 Gate 规则。此方案是实施文档，不代表上述改动已实现或本案例已获正式 W2 review。
