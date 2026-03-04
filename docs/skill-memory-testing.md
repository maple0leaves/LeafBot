# Skill Memory 功能测试指南

本文档记录如何测试 Nanobot 的 Skill Memory 功能，包括 SKILLS.jsonl 的生成与检索验证。

## 功能概述

Skill Memory 会在 agent 完成多步任务后，自动将 workflow 抽象为可复用模板并存入 `memory/SKILLS.jsonl`。当用户发送相似任务时，系统通过关键词匹配检索相关 skill，并注入到 agent 的 prompt 中。

详见架构文档：[skill-memory.md](./skill-memory.md)

---

## 前置条件

- Nanobot agent 已启动（如 `nanobot agent --logs`）
- 默认 workspace 为 `~/.nanobot/workspace`，SKILLS.jsonl 路径为 `{workspace}/memory/SKILLS.jsonl`
- 若需使用项目目录作为 workspace，可在 `~/.nanobot/config.json` 中配置 `agents.defaults.workspace`

---

## 测试一：生成 SKILLS.jsonl

### 1.1 触发条件

Skill 提取发生在 **memory consolidation** 时，需满足：

- 对话中有**多步任务**（使用多个工具，如 `exec`、`write_file`、`web_fetch` 等）
- 任务**成功完成**
- 触发 consolidation（见下）

### 1.2 触发 consolidation 的方式

| 方式 | 说明 |
|------|------|
| **发送 `/new`** | 推荐。完成多步任务后发送，立即触发 archive_all 模式 consolidation |
| **自动触发** | 当未归档消息数 ≥ `memory_window`（默认 100）时，下次收到消息自动 consolidation |

### 1.3 测试步骤

1. 启动 agent：`nanobot agent --logs`

2. 发送一个多步任务，例如：
   ```
   帮我做这几件事：1) 在项目根目录创建一个 test_skill 文件夹；2) 在里面新建 hello.txt，内容写 "Hello from skill test"；3) 用 ls 列出 test_skill 目录内容
   ```
   或更简短的：
   ```
   创建 demo 目录，在里面写一个 foo.txt 文件，然后 ls demo
   ```

3. 等待 agent 完成执行（会调用 `exec`、`write_file` 等工具）

4. 发送 `/new` 触发 consolidation 并提取 skill

5. 检查 SKILLS.jsonl 是否生成：
   ```bash
   cat ~/.nanobot/workspace/memory/SKILLS.jsonl
   ```
   或（若 workspace 为项目目录）：
   ```bash
   cat memory/SKILLS.jsonl
   ```

### 1.4 预期结果

- 日志中出现 `Skill saved: <task description>`
- `memory/SKILLS.jsonl` 存在且每行为一个 JSON 对象

**注意**：单步任务（如一次 `exec` 完成所有操作）可能不会被 LLM 识别为可复用 workflow，建议使用分步、多工具调用的任务。

---

## 测试二：验证 Skill 检索命中

### 2.1 检索机制

- 使用**关键词重叠**匹配：用户消息与 skill 的 `tags`、`task` 分词后取交集
- 当前实现为**精确 token 匹配**，不支持翻译
- **中文查询**与**英文 skill** 的 token 不重叠，无法命中

### 2.2 调试日志

代码中已添加 skill 检索日志（`nanobot/agent/memory.py`），当有 skill 被注入时会输出：

```
Skill retrieval: query='...' -> N skill(s) injected: ['task1', 'task2', ...]
```

若无此日志，说明当前查询未命中任何 skill。

### 2.3 测试步骤

1. 确保 SKILLS.jsonl 中已有 skill（完成测试一）

2. （可选）发送 `/new` 开新会话，便于观察 agent 是否依赖 skill 而非对话记忆

3. 发送**英文**相似任务，例如（假设已有 "Search for product prices" 类 skill）：
   ```
   Search for MacBook product prices
   ```

4. 查看日志，确认是否出现：
   ```
   Skill retrieval: query='  Search for MacBook product prices' -> 3 skill(s) injected: ['Search for product prices when search API unavailable', ...]
   ```

### 2.4 预期结果

- 日志中出现 `Skill retrieval: ... -> N skill(s) injected`
- agent 执行时可能参考 skill 中的 workflow 步骤（如先官网、再零售商等）

---

## 常见问题

### Q1：中文查询为什么没命中？

检索使用 token 精确匹配。中文「帮我查一下 MacBook 的价格」分词后为 `帮我查一下`、`macbook`、`的`、`价格`，与英文 skill 的 `product`、`search`、`price` 等无重叠，故不会命中。**测试检索时请使用英文查询**。

### Q2：SKILLS.jsonl 在哪个目录？

默认在 `~/.nanobot/workspace/memory/SKILLS.jsonl`。若配置了 `agents.defaults.workspace` 为项目路径，则在 `{项目路径}/memory/SKILLS.jsonl`。

### Q3：如何降低 consolidation 触发门槛？

在配置中设置 `agents.defaults.memory_window` 为较小值（如 30），使自动 consolidation 更早触发。

### Q4：如何确认 agent 是否真的用了 skill？

- **检索命中**：看 `Skill retrieval` 日志即可确认 skill 已注入 prompt
- **执行行为**：若 agent 按 skill 中的步骤顺序执行（如先官网、再零售商），可推断其参考了 skill；但 LLM 行为非确定性，无法 100% 断言

---

## 测试检查清单

- [ ] 多步任务完成并发送 `/new` 后，`Skill saved` 日志出现
- [ ] `memory/SKILLS.jsonl` 文件存在且格式正确
- [ ] 英文相似任务触发 `Skill retrieval` 日志
- [ ] 中文相似任务不触发 skill 检索（符合当前实现）

---

## 相关文件

| 文件 | 说明 |
|------|------|
| `docs/skill-memory.md` | Skill Memory 架构与设计 |
| `nanobot/agent/memory.py` | MemoryStore、skill 存储与检索 |
| `nanobot/agent/context.py` | 构建 prompt 时调用 `get_memory_context` |
