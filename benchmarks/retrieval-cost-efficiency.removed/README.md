# Retrieval Cost-Efficiency Benchmark

一个**自包含、零依赖**的检索成本效率基准（harness），用来量化 RAG 检索栈的
「成本 / 质量」权衡。它真实跑出三个指标，全部来自确定性计算，不依赖任何外部
API 或向量库。

```
benchmarks/retrieval-cost-efficiency/
├── run.py                      # 入口：计算三项指标并写出 RESULTS.md
├── src/retrieval_bench/       # 纯 stdlib 实现
│   ├── dataset.py             # 内置 12 条带标签评测集（可替换）
│   ├── pricing.py             # 供应商定价表（可替换）
│   ├── retrievers.py          # Plain / Graph 检索模拟器 + token/成本核算
│   └── metrics.py             # 三项头条指标 + 报告渲染
├── tests/test_benchmark.py    # unittest，9 个用例
└── RESULTS.md                 # 最近一次运行结果（由 run.py 生成）
```

## 运行

```bash
# 需要 Python 3.10+（纯标准库，无需 venv）
python run.py                 # 计算并写出 RESULTS.md
python -m unittest discover -s tests -v   # 跑测试
```

## 三个指标

### 1. 边际成本效率（Graph 该不该默认开？）
```
边际成本效率 = ΔRecall@5 (百分点) / Δ成本 (%)
```
即「每多花 1% 成本，换来多少个百分点召回提升」。这是判断 Graph 是否默认开启的
唯一依据。结论：**factual 边际 ≈ 0（Graph 几乎不涨召回）→ 不该默认开；
comparative / procedural 边际 > 0 → 只对这两类意图默认开 Graph**。

### 2. 路由后混合成本（Query Router 值不值？）
```
混合成本 = Σ(意图占比 × 该意图所选方案的单次成本)
```
对比「全量开 Graph」的成本，得出路由省下的百分比——这是 Query Router 设计价值的
量化证明。结论：路由到每个意图「最便宜且够用」的方案，相较无脑全开 Graph 省
~18%（比例随流量画像与 Graph 溢价变化）。

### 3. 成本结构拆解 + topk 旋钮实验（降本方向）
- **成本结构**：输入 token 占总成本 ~93% → 降本杠杆是**裁剪上下文，不是压缩输出**。
- **旋钮实验**（固定 arm B = 纯向量检索，只调 `topk_to_llm`：10 → 5 → 3）：
  - 10 → 5：成本降 ~32%，Recall@5 不变（检索质量固定），引用准确率对「相关文档都在
    top-5 内」的查询（factual 为主）几乎不变；
  - 5 → 3：成本再降，但开始丢掉排在前 5 之外的相关文档，召回与引用准确率同时下滑。
  - 上下文越大（topk 更大 / chunk 更长），10→5 的降本越接近 ~50%。

> 这类「免费的午餐」是面试里最能体现成本敏感度的点：**先量成本结构，再拧最便宜
> 的旋钮**，比 Graph 的取舍更有说服力。

## ⚠️ 诚实标注（务必读）

本报告的数字由**确定性、参数化的检索质量模拟器**在 12 条内置评测集上算出。它的
价值在于**方法论与权衡形状**，不是生产遥测：

- `dataset.py` 的 gold 排名是手工构造的「典型意图画像」，不是真实用户查询；
- `pricing.py` 用的是示意定价，请替换为你的真实供应商费率；
- `retrievers.py` 的 token 模型是简化的（固定 chunk/prompt/输出长度）。

**如何拿到生产数字**：把 `dataset.py` 换成你的真实标注评测集，把 `retrievers.py`
的模拟器换成真实 retriever（返回真实 gold 排名），`pricing.py` 换成真实费率，
直接重跑 `run.py` 即可。公式与报告结构无需改动。

## 简历 / 面试可引用的诚实表述（模板）

> 为检索栈搭建了一套可复现的成本效率基准，量化三类权衡：
> (1) Graph 增强的**边际成本效率**（ΔRecall@5 / Δ成本），据此只对 comparative /
> procedural 意图默认开启 Graph，factual 走纯向量；
> (2) Query Router 的**混合成本**，相对全量开 Graph 节省 ~18%；
> (3) 成本结构显示输入 token 占 ~93%，据此做 `topk_to_llm` 旋钮实验，10→5 在召回
> 几乎不变下降本 ~32%。基准为纯 stdlib、零依赖、带单测，可接真实 retriever 与定价
> 复算。

**不要**写成「我把线上成本降了 X%」——除非你已用真实数据跑过上面的替换步骤。
