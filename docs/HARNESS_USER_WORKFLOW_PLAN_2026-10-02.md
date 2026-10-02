# Harness 用户工作流：四项后续实现方案

## 1. 当前基线与本轮范围

基线为本地 `c20f28e`，包含 `772ea87` 状态投影修复、`0652dd7` 看板与成果浏览、
`c20f28e` 作者源和使用说明修正。以下是下一批实现计划，不能视为已实现能力。
只修改 Harness、测试及其说明；真实赛题项目、论文、用户未跟踪路线图不进入修改范围。

| 需求 | 已落地 | 尚需实现 |
|---|---|---|
| 可执行说明 | figure id 修正；冻结参数完整示意；Markdown/YAML 分工说明 | 无占位符的可复制教程、双 shell 临时项目执行、自动校验 |
| 控制台行动入口 | 含项目路径的复查命令复制；诊断/回执详情；产物筛选、下载、预览 | 作者文件阅读/定位、日志查看、待审版本绑定、中文行动解释 |
| 按小问组织 | 保留现有 question_id 与 writing spine 数据 | 小问任务投影、模型与验证闭环、正文位置及当前 PDF 绑定 |
| doctor 排障 | 内部 capabilities、stages、guidance 和解释器路径已有 | 普通终端摘要直接展示当前缺项与处理步骤 |

这四项共用现有事实源。第一批验证一条最小用户路径：初始化临时项目 → doctor →
查看某一小问 → 找到作者源 → 编译 → 执行示例程序 → 查看回执/日志 → 查看结果边界。
完整论文交付路径作为第二条教程；独立验证、评审和人工决定必须真实产生。

## 2. 可复制流程：从修正文案提升为可执行文档

### 2.1 三种内容明确区分

- **可直接执行**：脚本自动创建唯一临时目录，含完整初始化、输入文件与命令；无
  `<ROOT>`、`<RUN_ID>` 或省略号。Python 使用实际选定解释器。
- **真实项目操作**：先读取运行器产生的 receipt id、run id 和产物路径，再组装命令；
  缺少前置产物时明确停在哪一步。不能让用户猜应填什么。
- **接口示意**：保留占位符，但标为“参数说明，不能直接执行”，不混入快速开始。

### 2.2 实现位置和数据

新增 `examples/user_walkthrough/`，保留同一 Python 示例程序/数据；分别提供
`run.ps1` 与 `run.sh`。两个入口只负责解释器和 shell 参数传递，通过公共 CLI 完成
作者源编译、执行、验证和冻结。使用说明引用可审计脚本并提供小段逐步操作。

步骤先保存真实输出 JSON，再读取 run_id、receipt_id 和路径。对退出码逐步断言。
教程期望 M1 因 seed 官方规则未核验而阻断时，应检查该退出码及原因，不能把它伪装
成完整数模验收。教学数学例题的独立检验使用单独 checker；人工 checkpoint 是显式
人工步骤，CI 不 impersonate 用户。无人值守测试到人工节点即验收正确停下。

figure 步骤必须有实际 `figure_id`。冻结步骤必须明确 results source、output、run_id、
model contract、code、validation、selected full receipt，并使用当前 active manifest。
`--receipt` 接文件路径，`--selected-receipt` 接 receipt id，不可混写。

### 2.3 验收

- Windows CI 使用 PowerShell；Linux CI 使用 bash。执行教程脚本，不只测 argparse。
- 工作目录使用带空格路径；Windows 加中文路径。从 Harness 仓库之外启动一次。
- 用进程传入的 argv 验证路径分词，不能把一条命令字符串拼给 shell 执行。
- 检查真实产物、回执中的 argv/cwd/exit、独立验证输出和允许达到的状态。
- 重跑使用新临时目录；失败保留工作目录路径与最后一条命令供排障。
- 说明中的执行块与脚本具有明确对应关系；测试不能仅证明另一个隐藏 helper 可运行。

## 3. 行动型控制台：先打通一个诊断的处理过程

### 3.1 当前诊断的行动详情

在只读状态投影中增加共享的 action detail，CLI/MCP/看板使用同一结果：

```text
gate / diagnostic_code / raw_message
summary_zh / corrective_action_zh
target: source_role, relative_path, optional field_pointer
command: argv, cwd, effect(read_only/producer), preconditions
expected_artifacts / verification_argv
evidence_sources / unavailable_reason
```

这是派生视图，不是第二套 Gate 规则。读取现有 roots、authoring specs、检查器诊断
和编译器修复命令；不能靠正则猜出一个“精确字段”。先覆盖可稳定定位的诊断类型：
缺作者源、缺已编译合同、作者源改变、缺执行回执、选中输出漂移、review 过期。
若现有 checker 只输出字符串，先增加兼容的结构化 diagnostic code，保留原文。

中文解释从 diagnostic code 的静态表得到；未知类型显示原文和“尚无定位信息”。
解释与正式错误并排展示；中文解释不改变诊断严重度、退出码或事实。

### 3.2 文件、日志与待审版本

- **目标文件**：浏览器先支持只读源码面板、相对路径和复制路径。普通浏览器没有
  通用本地编辑器打开能力，不能把下载按钮叫作“打开编辑器”。桌面宿主的打开能力
  如要接入，应有独立明确协议；网页原型先完成可工作的查看与定位。
- **来源索引**：可浏览集合来自 authoring specs、manifest roots、DAG、receipt log refs
  和 review source refs。以来源标识选文件；不提供任意文件路径 GET 接口。
- **日志**：receipt 投影保留 stdout_path/stderr_path 及哈希引用；按 receipt id + stream
  查询，服务器重读该回执并检查项目内路径。展示尾部、截断标记、退出码与整份下载。
  文本做 HTML 转义及现有 redaction，预览设置字节上限；大日志不阻塞 snapshot。
- **待审版本**：展示 review 实际绑定的源码依赖与 PDF 摘要、当前文件的匹配状态、
  review 时间和 actor/independence 原始值。找不到历史字节时写“历史版本不可取回”，
  不能把当前 PDF 命名为当时待审版本。不同版本没有保存就没有版本切换器。

所有读取复用现有根目录许可与 resolved path containment，包括 symlink 越界。
源码和日志可在 DOM 文本节点显示；HTML/SVG 不能直接注入页面执行。

### 3.3 命令复制与后续写操作

共享事实保存 argv 和 cwd；PowerShell 与 POSIX 分别渲染复制文本。显示命令用途、
预期产生的文件和前置条件。复查命令与执行 producer 的命令必须区分。

本阶段复制命令给用户终端执行。若后续增加网页“执行”，只能选择确定 producer
及受约束参数，通过现有 CLI/运行器产生真实回执；运行完成后重算 status/artifacts。
执行、checkpoint 与 freeze 授权需要另行设计，不能让只读 HTTP GET 产生副作用。

### 3.4 验收

选一个真实缺失/过期合同：页面显示中文原因和准确作者源 → 查看文件 → 复制命令
到临时项目终端执行 → 新产物产生 → 刷新反映重算结果。补充缺日志、历史版本缺失、
日志含 HTML、路径含空格、状态失败与路径越界用例。不能用仅含模拟快照的 UI 测试
替代这一条真实 API/CLI 路径。

## 4. 小问工作台：从论文投影贯通研究过程

### 4.1 第一张 Q2 卡片

采用明确 question_id 构建如下投影：

| 用户问题 | 现有事实来源 | 展示规则 |
|---|---|---|
| Q2 求什么 | problem snapshot / model contract questions 的 task、inputs、outputs | 显示任务及应交付输出；缺源就标未知 |
| 用什么模型 | models.question_id 与明确 selection 的 candidate id | 区分候选、选定、已实现；无 selection 不擅自挑选 |
| 结果在哪里 | 实际 receipt 覆盖项、output refs、frozen results、DAG | 分开显示试跑输出、选中 full 输出和冻结结果 |
| 缺哪项验证 | models.validation_obligations 与独立 validation report | 按 obligation id 关联；列缺失、失败、未覆盖及来源 |
| 哪些能进论文 | evidence registry 与 writer package 的 claimable 事实 | 沿用现有消费者的资格判定；只有数字文件不够 |
| 论文写在哪里 | paper plan 的 question/section/argument units 与实际 TeX locator | 声明位置和实际匹配结果分开；缺 locator 不猜页码 |

小问来源以显式标识为准，支持共享模型和多问 section。未知、不适用与缺证据不能
混成“完成”。不生成一个掩盖细节的总百分比。

### 4.2 模块划分与接入

新增一个只读 question workbench projector，输入规范化的现有合同与事实，返回
带来源引用的 JSON。复用 `validation/obligations.py`、writer package 和
`views/writing_spine.py` 的纯函数；不要解析生成 Markdown 再恢复结构。
CLI 增加只读小问查询，MCP 与 snapshot 暴露同一投影，再接看板卡片。
planning、model、execution、validation、writing 各区域均围绕同一 question_id 过滤。

writing spine 是 W1/W2 的论证视图，不能成为前期全部研究事实的新 owner。
缺 paper plan 的 M1 项目仍可显示 task/model/validation 计划；缺 writer package 时
“可写入论文的结果”显示不可判定，不能据此造一份 package。

### 4.3 实际 TeX/PDF 的两类验收

复用 `qa/tex_source.py` 与 `paper audit` 读取真实根 TeX 和嵌套输入；对存在的
section marker/claim locator 标明命中、未命中、多处命中或对应源改变。
PDF 与源码绑定只有真实 build receipt 及当前摘要相符才标 verified。PDF 页码只有
确有构建映射或明确文本定位证据才显示；源码行号不等于 PDF 页码。

- **结构/证据验收**：声明覆盖、主张引用、验证关联、文件定位、版本绑定，由确定性
  检查器给出事实。这类通过不意味着数学或写作质量通过。
- **内容/呈现审阅**：是否回答小问、推导是否充分、结果是否有解释、假设边界是否
  清楚、图在最终尺寸下是否可读，由相应 reviewer / 人工审阅给出具体 issue。
  经验性数模指南保持软性建议；不设统一字数、模型数或图数硬配额。

### 4.4 验收

先打通只有 Q2 的项目，再覆盖共享模型、多问 section、未执行验证、旧 writer
package、没有 paper plan、未登记结果、TeX 嵌套输入变化与 PDF 绑定缺失。
每个可显示数字必须追到真实结果与证据引用；一次上游变化应使相关显示失效而不是
保留“可写入论文”的旧结论。仅修改 Harness fixture，不改用户真实论文。

## 5. doctor：用已有诊断直接支持排障

### 5.1 普通输出结构

`doctor_core.evaluate_capabilities` 已提供 python.path、各能力的 path/status/guidance
和 stages 的 missing/alternatives。先增加纯格式化层，不改检测或退出码语义：

```text
诊断阶段：M1（阶段能力检查，不是 Gate 判定）
Python：实际解释器路径 / 版本
当前必需缺项：名称 / 检测依据 / 具体处理动作
项目或 Harness 错误：逐条显示原因
后续或可选缺项：N 项；使用详细输出查看
复查：包含实际项目路径的 doctor --stage M1 --offline 命令
```

上例为设计字段，不是运行输出。显式 `--stage` 优先；默认行为保持现有 broad probe
兼容，标注“未指定阶段”，不把所有未来 TeX 能力当作当前阻断。后续若默认推断
阶段，可只依据有效 manifest/status 并显示来源；状态错误时提示不能推断。

增加 `--verbose` 展示后续阶段和可选能力。YAML 模块对应 PyYAML 安装名，不能生成
`pip install yaml`。Python 依赖处理使用报告中的实际解释器，避免装到另一个环境。
系统工具安装优先指向仓库已有平台说明；doctor 本身只读，不执行安装。

### 5.2 验收

缺 jsonschema 时普通输出含原因、实际解释器及安装动作并非只打印数量；M1 不缺
TeX 时不误报当前阻断；W2 缺 TeX/Poppler 时列当前缺项及 engine alternatives。
测试普通输出、JSON 和退出码，模拟 PATH/dependency probe 避免依赖测试机现状。

## 6. 推荐提交顺序与共同验收

1. **doctor 可读摘要**：复用已有字段，是最小独立收益；先让命令能排障。
2. **最小双 shell 教程**：由真实 CLI 跑通初始化、作者编译、执行和排障。
3. **一个诊断的行动闭环**：源定位、日志、中文解释、平台命令复制。
4. **Q2 只读工作台**：贯通题意、模型、结果、obligation、claimable 与论文位置。
5. **完整交付教程与待审版本视图**：依赖实际独立验证、评审及构建绑定能力。

每项一个短祈使句 commit，行为改动配 CLI/HTTP/产物回归。契约变化同步 schema、
checker、reference 与测试。实现记录另存
`docs/HARNESS_USER_WORKFLOW_IMPLEMENTATION_NOTES.md`，记录必要偏离及验证证据。

本地 Python targeted tests、双 shell 执行、浏览器真实交互之后，在固定 HEAD 上跑
全量 unittest、redteam、Ruff、agents check 与安全扫描。全量测试期间不提交代码：
benchmark 报告会记录当前 revision，运行中换 HEAD 会污染该项验收。
涉及字节/摘要语义时再用 git archive 的 Linux 导出复验。获得既有 push 授权且全绿
才可推送；当前三批提交仍只在本地。

若需要尚不存在的题目关联、历史版本字节、人工决定或外部规则核验，保留明确缺项，
不得通过新默认值、缓存 Gate、自动批准或制造产物绕过。
