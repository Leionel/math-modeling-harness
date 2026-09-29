# Method Card: Finite Difference PDE Numerical Modeling (有限差分法与偏微分方程数值解)

## 1. 解决什么问题
连续时空场演化系统、一维/多维热传导与对流扩散方程、移动边界热质交换、流体连续性与波动方程、烟幕浓度时空对流沉降场模拟。当物理过程依赖空间梯度 $\nabla u$ 与拉普拉斯算子 $\nabla^2 u$ 时适用。

## 2. 不适合什么问题
- 纯时间序列演化而无空间连续场分布的问题（应采用 ODE 动力学或状态空间模型）；
- 复杂不规则三维工程曲面拓扑（更适合有限元 FEM 或有限体积 FVM）；
- 缺乏明确偏微分物理机理与本构关系的纯数据驱动静态回归问题。

## 3. 最低数据条件
- 空间几何区域 $\Omega \subset \mathbb{R}^d$ 与时间域 $[0, T]$；
- 介质物理特性参数（热导率 $k$、热容 $c$、密度 $\rho$、热扩散率 $\alpha = k/(\rho c)$、扩散系数 $D$、对流速度 $\mathbf{v}$）；
- 初始条件 $u(\mathbf{x}, 0) = u_0(\mathbf{x})$；
- 确切的边界条件：Dirichlet（第一类，已知表面状态）、Neumann（第二类，已知热通量/通量梯度）或 Robin（第三类，对流换热边界）。

## 4. 核心数学结构
以一维带对流的抛物型传热/对流扩散方程为例：
\[
\frac{\partial u}{\partial t} + v \frac{\partial u}{\partial x} = \alpha \frac{\partial^2 u}{\partial x^2} + S(x, t), \quad x \in (0, L), \; t \in (0, T]
\]
边界条件：
\[
-k \left.\frac{\partial u}{\partial x}\right|_{x=0} = h_0 [u_{\text{ext}}(t) - u(0, t)], \quad \left.\frac{\partial u}{\partial x}\right|_{x=L} = 0
\]
时空网格离散（步长 $\Delta x$, $\Delta t$），采用隐式 Crank-Nicolson 或显式 FTCS 格式：
\[
\frac{u_i^{n+1} - u_i^n}{\Delta t} = \alpha \left[ \theta \frac{u_{i+1}^{n+1} - 2u_i^{n+1} + u_{i-1}^{n+1}}{\Delta x^2} + (1-\theta) \frac{u_{i+1}^n - 2u_i^n + u_{i-1}^n}{\Delta x^2} \right]
\]
其中 $\theta = 1/2$ 为二阶无条件稳定 Crank-Nicolson 格式；$\theta = 0$ 为显式格式。

## 5. 参数来源要求
- 介质物性常数（$\rho, c, k$）必须标明 `GIVEN`（赛题给定）或 `LITERATURE`（权威标准文献并注明源）；
- 对流换热系数 $h$ 若通过试验测定必须标明 `CALIBRATED`，并给出标定目标函数与残差统计。

## 6. 推荐 Baseline
- 稳态一维解析解基线（$\frac{\partial u}{\partial t} = 0$ 时的稳态线性温度分布）；
- 集总参数法（Lumped Capacitance Model，将空间平均化为单变量 ODE 基线）。

## 7. 必须验证的东西
- **网格收敛性检验（Grid Convergence / Independence）**：空间步长 $\Delta x \to \Delta x / 2$、时间步长 $\Delta t \to \Delta t / 2$，数值解相对 $L_2$ 范数变化须 $< 1\%$；
- **稳定性条件与 CFL 准则验证**：对于显式格式，严格检验 Fourier 稳定性数 $Fo = \alpha \Delta t / \Delta x^2 \le 1/2$ 与 Courant 数 $Cr = v \Delta t / \Delta x \le 1$；
- **能量/质量全局守恒律**：总热量变化 $\Delta E = \int_{\Omega} \rho c [u(x, T) - u(x, 0)] dx$ 必须与进出边界的热通量时间积分一致，相对守恒误差 $< 0.1\%$；
- **极值原理（Maximum Principle）检验**：无内部热源时，区域内极值必出现在初始时刻或边界上，禁止出现非物理的超温或低于环境温度的反常激波。

## 8. 常见数学错误
- 边界条件与内部微分方程在角点/边界点发生阶数不匹配或物理不相容；
- 对流项采用中心差分导致数值假振荡（未采用一阶迎风格式 Upwind 或 TVD 限制器）；
- 忽略不同多层介质交界面处的界面连续性条件（温度连续 $u_- = u_+$ 与热通量守恒 $k_- \frac{\partial u_-}{\partial x} = k_+ \frac{\partial u_+}{\partial x}$）。

## 9. 常见代码错误
- 显式时间推进步长过大导致数值发散溢出（`NaN` / `Inf`）；
- 三对角矩阵求解（Thomas 算法 / `scipy.linalg.solve_banded`）边界系数索引偏移；
- 矩阵拼接时空间网格边界点重复计算或漏算。

## 10. 论文表达规范
- 必须明确写出连续偏微分方程、定解条件（IC/BC）及无量纲化过程（若有）；
- 给出时空离散格式的截断误差阶数（如 $O(\Delta t^2 + \Delta x^2)$）；
- 附时空温度/浓度分布等高线热图（Contour Plot）与关键特征截面曲线。

## 11. 推荐实现入口
`scripts/scaffold/pde_finite_difference.py`
