# 数据分析

## 什么时候用

当用户提出以下类型的需求时使用：

- "帮我分析这个 CSV"
- "对这个数据做线性回归"
- "对这个数据做聚类并画图"
- "帮我看看这个数据集有什么规律"
- "做个统计分析"
- 用户上传一个数据文件（CSV / Excel）并问"这数据能看出什么"

## 核心原则

**逐步执行，每步汇报。** 不要一次性写完所有代码。

## 怎么用

你（Agent）自己编排步骤，用现有的工具：

- `terminal`：查看文件结构、运行 Python 脚本
- `python_repl`：交互式执行 Python 代码
- `read_rich_file`：读取 Excel 等文件
- `write_memory`：记录分析思路（可选）

## 标准流程

### 步骤 1：探查数据

先用 `terminal` 查看数据。例如：

```
dir <数据目录>
head -n 5 <数据文件>
```

了解：

- 文件数量
- 列名、数据类型
- 行数
- 缺失值

**告知用户**数据概况，并询问是否继续。

### 步骤 2：制定分析计划

根据用户需求和数据情况，确定分析方向：

- **描述性统计**：均值、中位数、分布、相关性
- **统计学习**：线性回归、逻辑回归、PCA、聚类
- **机器学习**：随机森林、SVM、XGBoost
- **深度学习**：MLP、CNN、RNN（数据量大时）

**告知用户**分析计划，确认后再执行。

### 步骤 3：逐步执行

每一步只做一件事：

1. **数据加载与清洗**：读数据、处理缺失值、编码分类变量
2. **探索性分析**：统计描述、相关性、分布图
3. **建模**：训练模型、输出指标
4. **评估与可视化**：画图、保存结果

**每步执行后，告知用户结果，并简要分析。**

### 步骤 4：保存产物

在用户指定的输出目录（默认 `analysis/{时间戳}/`）保存：

- `step1_prep.py` / `step2_model.py` 等：分步代码
- `results.txt`：运行结果
- `*.png`：图表
- `model.pkl`：训练好的模型（如需）
- `intermediate_*.csv`：中间数据

## 绘图规范

- **禁止 `plt.show()`** —— 会导致程序崩溃
- **必须用 `plt.savefig()`** 保存图片
- 坐标轴标签**用英文**（避免中文字体问题）
- 图片保存为高分辨率 PNG（`dpi=150`）

## 依赖安装

如果缺少 Python 包，用 `terminal` 安装。例如：

```
pip install pandas scikit-learn matplotlib seaborn
```

## 示例

用户说："帮我分析 summer.csv，做个回归预测"

你的流程应该是：

**第 1 步：探查**

用 `terminal` 执行 `head -n 5 summer.csv`。

然后说："数据有 1000 行 8 列，包含 age、income、score 等字段，无缺失值。要预测哪个字段？"

**第 2 步：确认计划**

用户确认后，说："好，用 income 和其他字段预测 score，用线性回归。开始。"

**第 3 步：加载与清洗**

用 `python_repl` 执行类似这样的代码：

```python
import pandas as pd
df = pd.read_csv('summer.csv')
X = df.drop('score', axis=1)
y = df['score']
```

然后说："数据加载完成，X 有 7 个特征。"

**第 4 步：建模**

用 `python_repl` 执行类似这样的代码：

```python
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
model = LinearRegression().fit(X_train, y_train)
print(model.score(X_test, y_test))
```

然后说："模型 R² = 0.83，拟合效果不错。"

**第 5 步：可视化**

用 `python_repl` 执行类似这样的代码：

```python
import matplotlib.pyplot as plt
plt.scatter(y_test, model.predict(X_test))
plt.xlabel('Actual')
plt.ylabel('Predicted')
plt.savefig('analysis/step3_prediction.png', dpi=150)
```

然后说："已生成预测对比图。"

**第 6 步：总结**

最后说："分析完成。主要发现是……"

## 注意

- **不要一次性跑完所有步骤** —— 每步都要汇报
- **不要跳过探查** —— 先了解数据再动手
- **不要用 `plt.show()`**
- **每步失败要告知用户**，不要静默重试
- **分析结果要有人话总结** —— 不要只丢一堆数字