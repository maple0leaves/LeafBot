# Skill Memory 效果评测报告

本文档记录 Skill Memory 功能的完整评测过程、实验结果和结论。

## 1. 评测目标

回答核心问题：**Skill Memory 是否为 agent 带来了可衡量的价值？**

评测分为两层：
- **检索层**：skill 检索和去重机制本身是否正确有效（确定性测试，无需 LLM）
- **执行层**：agent 实际执行任务时，有无 skill 的行为差异（端到端测试，需要 LLM API）

## 2. 评测设计

### 2.1 检索层评测

**测试文件**：`tests/test_skill_memory_evaluation.py`

| 维度 | 指标 | 说明 |
|------|------|------|
| 检索质量 | Recall@3, MRR, Precision@3 | 56 条 ground-truth 查询（48 正向 + 8 负向），覆盖 8 类任务领域 |
| 去重准确率 | Accuracy, F1, Precision, Recall | 12 条用例（5 真重复 + 7 非重复） |
| 效果提升 | Step Coverage A/B | 核心指标：有 skill 时检索出的步骤能覆盖理想 workflow 多少比例 vs 无 skill 时为 0% |
| 信息增益 | Prompt size delta, token count | 有 skill 时 prompt 增加了多少 actionable 信息 |
| 鲁棒性 | 边界用例 | 损坏 JSONL、空文件、时间戳自动添加、重复写入防护 |

**设计依据**：

- 评测集按任务领域分层：Web API、Docker、数据抓取、CI/CD、数据库、监控、PDF、虚拟环境
- 每类 5-8 条查询，包含同义改写，确保检索能力不依赖特定措辞
- 负向查询（"help me with homework"、"what time is it"等）验证噪声过滤
- Step Coverage A/B 是核心指标：直接对比有无 skill 时 agent 获得的 workflow 指导量

### 2.2 执行层评测

**测试文件**：`tests/test_skill_memory_e2e.py`

端到端 A/B 实验设计：

| 要素 | 说明 |
|------|------|
| 实验组 A | workspace 中有 SKILLS.jsonl（预置 skill） |
| 对照组 B | workspace 中无 SKILLS.jsonl |
| 控制变量 | 同一模型、同一 prompt 模板、同一任务、temperature=0 |
| 执行方式 | 完整 agent loop（LLM + 工具调用），通过 `_run_agent_loop` 执行 |
| 度量指标 | 关键步骤完成率、LLM 迭代次数、工具调用序列 |

**复杂任务设计**：

3 个多步任务，每个任务定义了 5-6 个"关键步骤"——代表最佳实践中容易被遗漏的环节：

1. **Python 包构建**（5 步）：创建目录 → 写模块 → 写测试 → 运行测试 → 验证通过
2. **数据处理管道**（5 步）：生成 JSON → 写处理脚本 → 执行 → 读取验证 CSV → 展示结果
3. **Shell 自动化备份**（6 步）：error handling → logging → 创建测试数据 → chmod+运行 → 验证日志 → 验证归档

**模型选择**：

| 模型 | 参数量 | 目的 |
|------|--------|------|
| moonshotai/kimi-k2.5 | 大模型 | 测试强模型下 skill-memory 的效果 |
| qwen/qwen3-8b | 8B | 测试小模型下 skill-memory 的效果 |

## 3. 检索层结果

运行命令：

```bash
pytest tests/test_skill_memory_evaluation.py -v -s
```

### 3.1 效果提升（核心指标）

| 指标 | 有 skill | 无 skill | 差异 |
|------|---------|---------|------|
| Step Coverage（48 条正向查询） | **95.8%** | 0.0% | **+95.8%** |
| Prompt 信息增益 | +514 chars / +463 tokens | — | — |
| Skill 注入命中率 | 47/48 = 97.9% | — | — |

分类别覆盖率：

| 领域 | 覆盖率 | 查询数 |
|------|--------|--------|
| Python web API | 100.0% | 8 |
| Docker 部署 | 85.7% | 7 |
| 网页数据抓取 | 100.0% | 6 |
| GitHub CI/CD | 100.0% | 6 |
| SQLite 数据库 | 100.0% | 6 |
| 服务器监控 | 80.0% | 5 |
| PDF 报告 | 100.0% | 5 |
| Python 虚拟环境 | 100.0% | 5 |

### 3.2 检索质量

| 指标 | 结果 |
|------|------|
| Recall@3 | **95.8%** |
| MRR (Mean Reciprocal Rank) | **0.952** |
| Precision@3 | 39.2% |
| 负向查询误报率 | 25.0% (2/8) |

注：Precision@3 受限于每条查询仅 1 个期望结果但返回 top-3，理论上限约 33%。实际 39.2% 说明部分查询返回不足 3 条。

### 3.3 去重准确率

| 指标 | 结果 |
|------|------|
| Accuracy | **100.0%** (12/12) |
| F1 Score | **1.000** |
| TP=5, FN=0, TN=7, FP=0 | |

### 3.4 鲁棒性

全部 5 项边界用例通过（损坏 JSONL 跳过、空文件处理、时间戳自动添加、重复写入防护、无文件场景）。

## 4. 执行层结果

运行命令：

```bash
pytest tests/test_skill_memory_e2e.py -v -s --run-e2e
```

### 4.1 强模型实验：kimi-k2.5

| | 有 skill | 无 skill |
|--|---------|---------|
| 关键步骤完成率 | 16/16 (100%) | 16/16 (100%) |
| 平均 LLM 迭代 | 3.0 | 2.7 |
| 平均工具调用 | 7.3 | 6.0 |

**结论**：强模型下，有无 skill 对任务完成无影响。kimi-k2.5 已经具备完成这些任务的能力，skill 注入未带来额外收益，反而因为 skill 中"verify"步骤的引导略增加了工具调用次数。

### 4.2 小模型实验：qwen3-8b（8B 参数）

| | 有 skill | 无 skill |
|--|---------|---------|
| 关键步骤完成率 | **16/16 (100%)** | **16/16 (100%)** |
| **平均 LLM 迭代** | **2.0** | **4.7** |
| 平均工具调用 | 4.3 | 4.7 |
| **迭代减少** | **-57%** | — |

分任务详情：

| 任务 | 有 skill 迭代 | 无 skill 迭代 | 减少 |
|------|:----------:|:-----------:|:----:|
| Python 包构建（5 步） | 2 | 6 | -67% |
| 数据处理管道（5 步） | 2 | 2 | 0% |
| Shell 备份自动化（6 步） | 2 | 6 | -67% |

**结论**：小模型下，skill-memory 的价值体现在**执行效率**而非正确性。有 skill 时 agent 行为更果断——参考 workflow 后一口气完成所有步骤，无需反复试探。无 skill 时同一个 8B 模型需要 3 倍的 LLM 迭代才能完成相同任务。

此外，有 skill 时 agent 更倾向使用标准工具（如用 `read_file` 读取文件），而无 skill 时更多使用 `exec cat` 等变通方式。

## 5. 综合结论

### Skill Memory 的价值定位

Skill Memory **不是让已经会做的事做得更好**，而是：

1. **提升小模型的执行效率** — 减少 57% 的 LLM 迭代，意味着更低延迟和 API 成本
2. **提供 workflow 指导** — 检索层验证 95.8% 的步骤覆盖率，确保 agent 获得完整的工作流参考
3. **跨会话知识复用** — 新会话中无历史消息，但 skill 保留了过去的成功经验
4. **无负面影响** — 强模型下不会降低性能，worst case 是中性

### 与 AWM 论文的对应

本项目的 Skill Memory 在架构上参考了 Agent Workflow Memory (ICML 2025) 的思路：

| AWM 论文 | Nanobot Skill Memory |
|---------|---------------------|
| Web 导航任务，812+ 任务 | CLI/工具调用任务，3 复杂任务 |
| 执行级评估（功能正确性） | 关键步骤检查 + LLM 迭代次数 |
| GPT-4o，成功率 +51.1% | qwen3-8b，迭代次数 -57% |
| 关键词 + 规则匹配检索 | 关键词重叠匹配检索 |
| JSONL workflow 存储 | JSONL workflow 存储 |

### 局限性

1. **端到端实验规模有限** — 仅 3 个复杂任务，统计置信度有限
2. **LLM 非确定性** — 即使 temperature=0，不同运行可能有微小差异
3. **任务领域覆盖** — 仅测试了文件操作/脚本类任务，未覆盖 web 交互等场景
4. **检索方法简单** — 基于关键词匹配，中文查询无法命中英文 skill

## 6. 测试文件清单

| 文件 | 说明 | 运行方式 |
|------|------|---------|
| `tests/test_skill_memory_evaluation.py` | 检索层评测（56 条 ground-truth，确定性） | `pytest tests/test_skill_memory_evaluation.py -v -s` |
| `tests/test_skill_memory_e2e.py` | 执行层 A/B（3 复杂任务，需 API key） | `pytest tests/test_skill_memory_e2e.py -v -s --run-e2e` |
| `tests/conftest.py` | pytest 配置（`--run-e2e` 参数注册） | — |
| `docs/skill-memory.md` | Skill Memory 架构设计 | — |
| `nanobot/agent/memory.py` | MemoryStore 核心实现 | — |
| `nanobot/agent/context.py` | Prompt 构建与 skill 注入 | — |
