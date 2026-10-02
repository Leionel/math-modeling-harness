# 用户工作流实施记录（2026-10-02）

实施依据：`HARNESS_USER_WORKFLOW_PLAN_2026-10-02.md`。仅修改 Harness、教学示例、
文档与测试；真实赛题项目、论文、用户未跟踪路线图保持原状。提交仅保留本地。

## 已实现

- doctor 普通输出列实际 Python 路径、当前阶段缺项、逐项错误和处理命令；
  `--verbose` 展开后续/可选工具。保持原有检测与退出码语义。
- 公共 CLI 教程有 PowerShell/bash 两个入口。从仓库外的临时项目完成初始化、
  YAML 作者编译、带 figure_id 的图约、实际求解、解析检验、验证报告与完整冻结。
  回执和摘要均由实际 producer 产生；正式 M1 仍阻断，人工 checkpoint 未代填。
- 控制台提供中文诊断解释、目标作者源、完整双 shell 复查命令、producer 编译
  命令、日志尾部和待审版本摘要。没有字段定位依据时不猜字段。
  编译命令保留当前索引的 source/output，以及模型的独立 research-source；
  自定义作者路径不会被复制命令中的默认路径替换。
- `harness questions`、status、既有 MCP get_run_state 与页面共用逐问投影。
  任务、明确关联的模型/执行产物、验证义务、冻结结果和写作资格分别展示。
  跨小问共享模型只采用 argument unit 明确声明的 model_ids。
- 实际 TeX 输入树的定位符给出文件/行、缺失或多处匹配；源码/PDF 绑定复用
  paper audit。源、测量或输出摘要漂移后，旧验证不再显示为当前通过。

## 投影与接口边界

没有变更持久化 JSON 契约或 Gate checker；新增数据为按请求重算的只读投影。
`question_workbench` 包含 `questions/errors/source_paths/writing_spine/paper_binding`。
每问给出 `models/executed_outputs/validation_obligations/registered_frozen_results/`
`writer_claims/writer_eligibility/writer_limits/argument_units/paper_locations`。
`current_package` 只说明当前包与来源绑定，不代表数学、论文质量或 Gate 通过。

`GET /api/source?id=...` 只接受目录内的命名来源，限制项目路径、最多读取 128 KiB
并遮盖敏感文本。日志读取尾部。待审摘要不匹配或没有历史字节时不展示当前文本
冒充待审版本。图像/PDF 只显示版本信息，预览仍走登记产物端点。页面拒绝 POST。

## 验证与必要偏离

- targeted unittest 验证真实 CLI/HTTP、退出码、产物、陈旧验证、审阅版本、
  日志限制、路径边界、共享模型和嵌套 TeX 唯一/缺失/多处定位。
- 本机 PowerShell、Windows Git Bash 教程实际成功；浏览器检查实际教学 Q2、
  当前验证、源内容、日志、复制命令与 390 px 窄屏。预览保存在系统临时目录。
- Ubuntu bash 教程已加入 CI，但本机 Linux 环境不可用，尚无真实 Linux 执行
  证据。Git Bash 成功不替代 Linux；没有改变现有摘要算法。
- 教学冻结文件未自动登记为 active manifest 的正式冻结根。视图保持其实际
  执行证据，不把文件存在提升为已登记写作证据。这一缺项在教学说明中明确。
- 完整正式交付依赖实际比赛规则、真实论文、构建回执、独立评审与人工决定。
  教程覆盖可自动验证的 producer 路径；没有制造演示审批或虚构交付完成。

全量验证须在最终固定 HEAD 上执行；期间不得提交，以免 benchmark 的 revision
绑定断言受污染。最终通过/失败数量以本次运行输出和交付报告为准。

## 最终验证记录

代码验证版本：`95f2070`。全量运行期间 HEAD 保持固定；后续提交仅补本文记录。

| 验证 | 实际结果 |
| --- | --- |
| `python -m unittest discover -s tests -q` | 908 项，907 通过、1 跳过；1260.518 秒 |
| `python evaluation/redteam.py --output <临时报告>` | ok=true，13 个场景符合预期；保留既有 documented gaps |
| `python scripts/harness.py agents check --json` | ok=true，7 个 agent 契约 |
| Ruff（本轮改动 Python 及相关测试） | All checks passed |
| 两组 Edge/Playwright 页面回归 | 导航/成果/错误状态，以及实际 Q2/源文件/日志/命令复制/窄屏均通过 |
| PowerShell 与 Windows Git Bash 教程 | 实际求解、检验、冻结完成；正式 M1 保持阻断 |
| 最终 HEAD 的 `git archive` 导出教程 | Windows 上成功，验证 Git blob 字节；不替代 Linux |
| 凭据模式扫描与 `git diff --check` | 27 个本轮跟踪文件无所查凭据模式命中；diff 检查通过 |

本机完整日志：`%TEMP%\harness-full-final-20261002.log`；红队报告：
`%TEMP%\harness-redteam-final-20261002.json`。最终归档教程日志位于
`%TEMP%\harness-final-archive-822205feaf154778aed480524a599ea1\tutorial.log`。
本轮不含 Linux 实测或陌生用户易用性测试；没有推送远端。
