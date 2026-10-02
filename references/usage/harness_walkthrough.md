# Harness 使用说明

这份文档讲**怎么用这个工具**,不讲怎么建模。怎么分析题目、怎么建模型、怎么写论文,
看 [references/router.md](../router.md);这里只回答一件事:从空文件夹到能交上去的
材料,中间每一步该敲什么、它会留下什么。

下面每条命令都是真实接口。如果对不上,以 `python scripts/harness.py <命令> --help`
为准。装好包之后(`python -m pip install --no-deps -e .`)可以直接写 `harness`。

先记住一句话:**Agent 负责想,负责写,负责改;Harness 负责判定什么算事实。**
你后面看到的每一条规则,都是这句话的具体化。

## 装好,然后确认环境

```bash
python -m pip install -r requirements-dev.txt
python -m pip install --no-deps -e .
python scripts/harness.py --help
```

开跑之前先看一眼环境:

```bash
python scripts/harness.py doctor --project <项目根目录> --offline --json
```

`doctor` 报告的是 Harness **实际能用到**的东西:解释器、可选后端、当前 preset 的要求。
它不联网下载任何东西,`--offline` 就是把这件事说在明面上。
普通输出显示解释器路径、当前缺项与处理动作。加 `--stage M1` 聚焦当前阶段；
`--verbose` 展开后续或可选工具。未指定阶段时保留基础能力检查，不代表所有 Gate 可运行。

## 开一个 run

```bash
python scripts/harness.py init --project <项目根目录> --competition cumcm --preset research
```

`init` 写四个控制 JSON：`run_manifest.json`、`competition_profile.json`、
`artifact_dag.json`、`run_index.json`，并建立作者 Markdown、结构化 YAML 模板与工作目录。
模板不代表研究完成，也不是 Gate 结论。先在 Markdown 解释决策，再填
`.harness/authoring/*.yaml` 并用对应 `--compile` 生成机器契约；不要手改生成的 JSON。

三个 preset 是**能力集合**,不是难度档位:

- `sprint` —— 最小链条;
- `research` —— 加上校验和评审;
- `submission` —— 加上完整的编辑、参考文献和不可变性链条。

preset 可以收紧某个 Gate 的要求,但**永远关不掉**这几样:安全约束、人工确认、
独立校验、结果冻结、提交不可变性。

## 主流程:一个 Gate 一个 Gate 往前走

| 你要做的事 | 命令 | 留下什么 |
| --- | --- | --- |
| 写模型决策 | `harness model --project <ROOT>` | 可编辑的模型契约源,改完再编译 |
| 拆成实现任务 | `harness solve --project <ROOT> --tasks` | 从契约投影出来的任务清单 |
| 真的跑一次 | `harness execute --project <ROOT> --stage smoke -- <命令>` | 一条回执:argv、cwd、退出码、时间戳 |
| 覆盖契约条目 | 同上,加 `--covers-model` / `--covers-question` / `--covers-contract-item` | P1/P2 能核验的覆盖率 |
| 冻结数字 | 见下方完整参数示例 | 绑定到**被选中回执**的冻结结果 |
| 起草论文 | `harness paper plan --project <ROOT>`,再 `harness figure FIG-01 --project <ROOT>` | 论文计划、分节草稿、图约 |
| 草稿诊断 | `harness paper audit --project <ROOT> --tex paper/main.tex --pdf paper/main.pdf --log paper/main.log --plan .harness/contracts/paper_plan.json --json` | 只读的 TeX/PDF 问题清单，`gate_effect=none` |
| 评审 | `harness review --project <ROOT> --semantic` | `reports/review/*.json`,带结论和独立性等级 |
| 重算某个 Gate | `harness check --project <ROOT> W1` | 结论,或者"为什么没有结论" |
| 跑整条 W2 确定性 QA | `harness validate --project <ROOT>` | 过 Gate 检查器的结果 |
| 提交包检查 | `harness submit check --project <ROOT>` | S1 的事实性结论 |

有两条规矩值得在第一次运行之前就记住,因为它们决定了你为什么要这样用工具。

结果冻结的参数示例如下（路径与 run id 必须替换为本次真实执行产生的值；不是可直接
执行的演示数据）。验证报告必须来自独立验证，选中回执必须已存在：

```powershell
harness freeze --project '<ROOT>' --kind results --source '<RESULTS_JSON>' --output '<FROZEN_RESULTS_JSON>' --run-id '<RUN_ID>' --model-contract '<MODEL_CONTRACT_JSON>' --code '<SOLVER_FILE>' --validation '<VALIDATION_JSON>' --receipt '<FULL_RECEIPT_JSON>' --manifest '<ACTIVE_MANIFEST_JSON>'
```

**没有回执的数字,进不了冻结结果。** `freeze` 不会替你编造一次执行,它只绑定到一条
已经存在的回执上。想验证"当时真的跑过",用 `harness reproduce <回执.json>`:它按回执里
记的那条命令重跑一遍,再逐字节比对。这就是"我跑过了"和"这是可复现的"之间的区别。

**投影不是真相。** `harness prepare M1|W1|W2|S1` 把磁盘上已有的东西渲染成人看的视图
(状态文本、清单)。它不写结论,你去改投影也改变不了任何事实。

`paper audit` 可在 M1 阻断时检查已有草稿，不执行编译或正式评审。退出码 0 表示完成且无高严重度发现，1 表示完成但有高严重度发现，2 表示输入错误；未提供 PDF、log 或计划时，相应检查会列在 `skipped_checks`。只有构建回执的源树和 PDF 哈希都与当前文件相符，`source_binding` 才是 `verified`。正式 W2 仍要求已登记的论文产物、确定性 QA、独立 review 和相应人工 checkpoint。

`harness status --project <ROOT> --json` 的 `readiness_diagnostics` 是只读预诊断：分组显示未核验的外部规则、待人工决定、首个正式 Gate 阻断、选中回执输出字节漂移，以及当前草稿候选问题。输出漂移复用 P2 的摘要核对函数；后续 Gate 尚未执行时不会在此伪造 PASS 或 FAIL。

## 什么时候必须你亲自点头

有些判断没法从文件里推出来——模型选型是不是有人真的看过、论文里的说法是不是
人工核过、最终 PDF 是不是确认过。这些要显式记一笔:

```bash
python scripts/harness.py checkpoint approve w1 --project <ROOT> \
  --role "队长" --decision approve
```

这条命令会追加一份证据 artifact 到 `.harness/human_decisions/`(和上一条决策哈希链起来),
同时在 `run_manifest.human_checkpoints` 追加一行。manifest 那行是控制真相,artifact 是证据。

同一个命令还有个 `--actor human|agent`,默认 `human`:

```bash
python scripts/harness.py checkpoint approve w1 --project <ROOT> \
  --role "编排器" --decision approve --actor agent
```

**需要人工确认的 Gate,只认 `actor_class` 是 `human` 的行。** 这个字段出现之前记的旧行
按 `human` 读,所以已有 run 不会因为升级就丢掉自己的 checkpoint。

要说清楚这条挡住了什么、没挡住什么:它挡住的是"agent 顺手把人工 Gate 清了"这种
事故;它**挡不住**谎报 `--actor human`,因为 `role` 和 `actor_class` 都是调用者的自我
声明,不是已验证身份。闭合那一步需要预共享角色密钥或外部身份 token,目前没做,
`docs/THREAT_MODEL.md` §5.2 把这条列为仍然存在的缺口。

## 运行模式:agent 可以替你走多远

```bash
python scripts/harness.py mode auto --project <ROOT> --set-by "你的名字"
```

两种模式,记在 `run_manifest.control.operator_mode`,每次变更都追加进
`operator_mode_history`(只追加,不改写):

- **`accept-edits`** —— agent 提改动,你逐条批。Gate 决策一定问你。
- **`auto`** —— 所有**可重算**的环节都不用问:执行命令、落回执、起草并编译产物。
  但走到需要人工确认的 Gate 时它必须停下来,因为没人能替你记那一条并让它生效。

模式是关于 agent 行为的声明,发生在 Harness 看不见的地方,所以 Harness 无法验证你
有没有照做。它保证的是另一件事:**模式永远不放宽任何 Gate。** `harness mode` 存在的
意义是——一整程无人监督跑下来的 run,事后不能被说成有人看过;中途改过模式,记录会留着。
控制台会显示当前模式,并把每次变更画在运行时间线上。

## 被 Gate 挡住时先看这一条

不要先改文件,先读阻塞原因:

```bash
python scripts/harness.py status --project <ROOT> --json
```

`status` 给你 `first_blocked_gate`、每条阻塞项和它自带的 `next_action`、过期产物、
以及还等谁确认。按提示补证据,然后重跑它点名的命令。`harness check` 每次都在读文件时
重算,所以没有缓存要清、没有状态要手动复位。

如果上游产物在某次评审之后变了,下游评审会过期、受影响的 Gate 重新变成待处理。
**这是设计要它发生的,不是要你去绕的 bug。**

## 看着它跑

```bash
python dashboard/server.py --project <ROOT> --port 8765
```

一个只读控制台,读的是和 agent 走的同一套 MCP 工具:Gate 链、阻塞项、时间线、
产物谱系、回执、评审。它没有写入路径——`POST` 一律回 405,并告诉你该跑哪条生产者
命令。可服务的根目录由 `DASHBOARD_ALLOWED_ROOTS` 限制。

侧栏按当前工作、模型、实验、论文和成果组织页面；详情栏显示原因、生产者和依赖。
成果中心可筛选、搜索、下载已登记的项目内文件，并按需预览 PDF/栅格图。
登记数不代表文件已经生成或验收通过。未登记文件不展示；缺失文件返回 404。
页面右上角可以暂停刷新、切换主题和中英文；**阻塞信息、`next_action`、各种 id 保持 Harness 输出的原文**,不翻译
——把证据改写成另一种语言,等于往证据里塞它没说过的话。

## Harness 不会替你做的事

- 不会伪造 Gate PASS、回执、哈希、冻结结果或评审结论。
- 不会验证 `--role` 是谁。它记的是声明,不是身份。
- 不会证明你的数学是对的。一条通过的回归测试只证明某条实现路径跑通了,
  它不是数学证明,不是能力基准,也不能当作泛化能力的证据。
