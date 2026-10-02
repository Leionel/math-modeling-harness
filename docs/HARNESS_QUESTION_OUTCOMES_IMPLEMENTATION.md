# 每问成果工作台：实现与验证

日期：2026-10-02。范围仅为 Harness；真实赛题、论文、用户路线图均未修改。

## 已实现

- 更新蓝灰色工作台、深色导航、结果表与图册，保留主题、语言和手机布局。
- 新增“每问成果”：按小问切换结果、图册、验证与论文边界。
- 结果显示实际数值、单位、统计定义、使用边界、文件路径和执行回执。
  来源与回执不匹配时隐藏数值；模型源变更后标记历史输出。
  探索结果与写作包引用分别标记，展示不授予论文使用资格。
- 图册通过图约的 claim IDs 和小问/论证作用域建立关联；没有显式关联的图
  进入“未关联图”。支持实际 PNG/JPEG/WebP/PDF 预览和下载，SVG 仅下载。
  图约引用但未登记的文件可查看，并明确显示未登记/未验证。
- 生图示意图显示当前完整图约产生的 prompt，支持完整复制、图约查看、
  请求与收集命令。图约变更会标记旧请求；不完整图约不会生成完整 prompt。
  数据结果图必须由数据与绘图脚本生成，不提供生图 prompt。
- 页面和新接口保持只读。手动生图需要先确认 AI 规则和工具可用性，记录请求，
  外部生成并保存图片后再收集；披露、科学检查、视觉检查、最终尺寸图审仍需完成。

## 使用

在仓库根目录启动已有项目的控制台，然后点击“每问成果”：

```powershell
python dashboard/server.py --project 'D:\your-project' --port 8765
```

浏览器打开 `http://127.0.0.1:8765/`。将上面的项目路径替换成实际路径。
未声明小问或图约关联时，页面会呈现缺项；不会按文件名猜测或补造证据。

可以独立创建教学预览。第一条命令打印新建临时项目路径，将它填入第二条命令：

```powershell
python tests/_dashboard_atlas_fixture.py
python dashboard/server.py --project '<第一条命令输出的路径>' --port 8771
```

教学 fixture 实际执行整数二次函数示例，产生真实结果和验证回执；图约只是
待审 UI 输入，示意图没有生成图片。它不代表完成的正式数模项目。

## 验证记录

代码验证提交：`401958b`。全量期间 HEAD 保持固定，之后仅补本文记录。

| 验证 | 实际结果 |
| --- | --- |
| `python -m unittest discover -s tests -q` | 915 项，914 通过、1 跳过；1306.756 秒 |
| `python -m unittest tests.test_dashboard tests.test_question_assets tests.test_question_workbench -q` | 27 项通过 |
| `python evaluation/redteam.py --output <临时报告>` | 13 个场景符合预期，保留既有 documented gaps |
| `python scripts/harness.py agents check --json` | ok=true，7 个 agent 契约 |
| Ruff：改动的 Python 文件和相关测试 | All checks passed |
| `tests/dashboard_browser.cjs` | 原有导航、成果、主题、语言、复制、手机布局及错误状态通过 |
| `tests/dashboard_workflow_browser.cjs` | Q2、实际验证、源文件、日志、命令复制和手机布局通过 |
| `tests/dashboard_atlas_browser.cjs` | 实际数值、按问筛选、图片预览、完整 prompt 复制、数据图路由、深色和手机布局通过 |
| `git archive HEAD` 导出后运行图册和小问测试 | Windows 上 15 项通过；不替代 Linux 实测 |
| 凭据模式扫描、`git diff --check` | 11 个实现/设计/测试文件无所查凭据模式命中，diff 检查通过 |

浏览器采用本机 Edge/Playwright。已查看浅色成果页、prompt 详情、深色图册和
手机截图。主题截图等待按钮背景色完成过渡后再采集。
一次针对性运行发生本地 HTTP 连接中断，整组重跑及最终全量均通过；未添加网络回退。

本机日志：`%TEMP%\harness-atlas-full-20261002.log`；红队报告：
`%TEMP%\harness-atlas-redteam-20261002.json`。截图位于
`%TEMP%\harness-atlas-visual-preview`，可用浏览器脚本重新生成。

提交：`842e0ba`（只读图册与结果投影）、`6de7d16`（成果工作台）、
`401958b`（稳定主题截图）。未推送远端。

## 仍需验证的范围

没有 Linux 实测或陌生用户易用性研究。这轮证明来源投影、访问边界与页面交互，
不证明 LLM 建模质量或论文质量。正式写作资格继续由冻结、写作包和评审检查计算。
技术设计与预览接口见 `DASHBOARD_DESIGN.md`。
