# 可执行教学流程

从 Harness checkout 根目录复制执行；先安装 `requirements-dev.txt`。脚本会创建并保留
唯一临时项目，不使用真实赛题项目，不覆盖已有文件。

PowerShell：

```powershell
./examples/user_walkthrough/run.ps1
```

Linux bash：

```bash
bash examples/user_walkthrough/run.sh
```

解释器需要指定时，PowerShell 用 `-Python '解释器绝对路径'`，bash 用 `PYTHON` 环境
变量。`run.py` 以自身位置找到 Harness，所以可以从仓库之外通过绝对路径启动。

## 实际执行什么

1. 公共 `harness init` 建控制面，读取产生的真实 run id。
2. `doctor --stage M1` 显示当前环境；`model` 建作者入口。
3. 写明确教学契约到 YAML，用 `model --compile` 生成 JSON；模板模型是九个整数点上的
   `(x-3)^2` 最小化，ready 只是教学作者合同声明。
4. `figure FIG-Q2 --semantic-type trend` 建图约。此步骤不声称产生了图片。
5. 通过 `execute` 运行求解器；生成真实 stdout/stderr 和选中 full receipt。
6. 通过另一次 `execute` 运行独立解析检验：平方非负，零值只在 x=3。检验报告由
   `validation/evaluate_obligations.py` 重算比较产生，不手填验证 PASS。
7. 完整 `freeze` 参数绑定模型、代码、独立验证报告、真实 selected full receipt
   与 active manifest；冻结本身也通过 `execute --stage freeze` 记录回执。
8. `status` 和 `check M1` 验证正式流程仍阻断，人工 checkpoint 仍未代填。

脚本逐条打印适用于当前 shell 的完整命令，记录真正的解释器和临时路径。失败时
打印最后一条命令与项目位置；成功时保留结果供看板浏览。

## 继续查看

程序打印的 `Project retained` 是这次真实目录。查看 `receipts/full.json` 的
`stdout_path`/`stderr_path`，或对该目录启动 `dashboard/server.py`。`harness questions`
显示按小问关联的任务、验证与论文资格。此教学流程没有完成规则核验、人工选型、
论文计划、writer package、独立论文评审或正式提交；这些不能从教学冻结结果推出。

完整交付依赖当前正式比赛规则、实际论文、构建回执、独立评审与显式人工决定。
这里故意保留阻断，而不是用内置演示审批模拟一条自动通过的正式链。

## 验证范围

`tests/test_user_walkthrough.py` 从仓库外、带空格/中文的临时目录执行同一公开脚本，
检查 CLI 退出码、实际文件、求解 stdout、验证报告和正式阻断。
CI 的 Ubuntu unit job 执行 bash 入口；windows-light 执行 PowerShell 入口。
Windows Git Bash 成功只证明该 shell 入口在 Windows 上工作，不替代 Linux 验证。
