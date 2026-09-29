# Method Card: Sensitivity Analysis & Sobol Variance Decomposition (灵敏度分析与 Sobol 方差分解)

## 1. 解决什么问题
量化系统输出对不确定性输入参数的依赖程度、识别主导关键控制参数、检验模型在输入摄动下的稳定性与鲁棒性、指导模型参数简化与降阶。适用于任何黑盒仿真模型、微分方程系统、优化目标函数对不确定参数的敏感程度评估。

## 2. 不适合什么问题
- 确定性系统单点最优解求解（那是优化问题而非敏感性分析）；
- 参数维度极高（$d > 100$）且单次计算极耗时的黑盒仿真（此时宜先用 Morris 筛选法筛选主效应变量）。

## 3. 最低数据条件
- 参数基准值 $\mathbf{x}_0$ 与合理摄动区间 $[x_{i,\min}, x_{i,\max}]$ 或先验概率分布 $x_i \sim \mathcal{U}(a_i, b_i)$；
- 可调用的可重复模型黑盒映射函数 $y = f(\mathbf{x})$；
- 评价目标指标（如最优目标值、有效遮蔽时长、稳态温度、峰值到达时间）。

## 4. 核心数学结构
1. **局部敏感性指数（Local Sensitivity）**：
\[
S_{i}^{\text{local}} = \left. \frac{\partial y}{\partial x_i} \right|_{\mathbf{x}_0} \cdot \frac{x_{i,0}}{y_0} \approx \frac{f(\mathbf{x}_0 + \Delta x_i \mathbf{e}_i) - f(\mathbf{x}_0 - \Delta x_i \mathbf{e}_i)}{2 \Delta x_i} \cdot \frac{x_{i,0}}{y_0}
\]
2. **Sobol 全局方差分解（Global Sobol Indices）**：
将总方差分解为各阶正交方差分量：
\[
\text{Var}(y) = \sum_{i} V_i + \sum_{i<j} V_{ij} + \dots + V_{1,2,\dots,d}
\]
- 一阶主效应指数（First-order index）：$S_i = \frac{V_i}{\text{Var}(y)} = \frac{\text{Var}_{x_i}(\mathbb{E}_{\mathbf{x}_{\sim i}}[y \mid x_i])}{\text{Var}(y)}$
- 全效应敏感性指数（Total-effect index，包含 $x_i$ 及其与所有其他参数的高阶交互项）：$S_{Ti} = 1 - \frac{\text{Var}_{\mathbf{x}_{\sim i}}(\mathbb{E}_{x_i}[y \mid \mathbf{x}_{\sim i}])}{\text{Var}(y)}$

## 5. 参数来源要求
- 摄动范围必须说明现实工程物理含义（如制造公差 $\pm 5\%$、飞行测速误差 $\pm 2 \text{ m/s}$）；
- 蒙特卡洛/准随机采样的样本量 $N$ 与收敛判据必须明确记录。

## 6. 推荐 Baseline
- **单变量局部单因子摄动（OAT / One-At-a-Time Perturbation）**：每次只让一个参数变动 $\pm 5\%, \pm 10\%, \pm 20\%$，绘制蜘蛛图（Spider Plot）或龙卷风图（Tornado Plot）。

## 7. 必须验证的东西
- **一阶指数与总效应指数的数学相容性**：独立输入的总体指数满足 $0 \le S_i \le S_{Ti} \le 1$；有限样本估计可能暂时越界，应连同置信区间与收敛检查报告，不能静默裁剪成合法值；
- **总和检验**：若各参数近似线性独立无交互，则 $\sum_i S_i \approx 1$；若存在强非线性交互项，则 $\sum_i S_i < 1$ 且 $\sum_i S_{Ti} > 1$；
- **抽样收敛性检验（Bootstrap CI）**：通过 Bootstrap 自助重抽样给出各灵敏度指数的 $95\%$ 置信区间，确保关键参数排序在误差范围内不变。

## 8. 常见数学错误
- 将局部导数灵敏度混淆为全局非线性灵敏度，并在大范围变动时得出错误结论；
- 在参数相关/非独立的情形下直接应用经典独立 Sobol 方差分解（未做 Copula 变换或 Shapley 效应分解）；
- 归一化时除以接近 0 的极小基准值导致数值爆炸。

## 9. 常见代码错误
- `SALib` 采样矩阵 $A, B$ 的交叉行对齐错误导致高阶方差估计为负值；
- 采样矩阵生成后，模型函数批处理时输入特征列名与采样维度索引不匹配。

## 10. 论文表达规范
- 呈现龙卷风图（Tornado Diagram）按敏感程度降序展示各参数影响幅度；
- 呈现 Sobol 一阶与全效应柱状对比图，明确标出置信区间误差棒（Error Bars）；
- 给出对实际决策的稳健性建议（如“系统对弹体下沉速度最敏感，设计控制应首要保证引信定高精度”）。

## 11. 推荐实现入口
当前仓库没有 Sobol scaffold。可按 [SALib 官方采样与分析接口](https://salib.readthedocs.io/en/latest/)建立任务专用脚本，记录参数分布、采样器、样本矩阵摘要、样本量、随机种子、分析器与置信区间，并将运行产物绑定回执。
