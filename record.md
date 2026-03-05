运行项目前  
先执行  ./Crashcore 挂着，然后执行 proxy  
启动项目 leafbot gateway，这个会加载配置机器人  
                leafbot agent , 这个是在终端测试用

---

## Tavily Search 集成记录

### 背景

leafbot 原生只支持 Brave Search API 做网页搜索。由于没有 Brave API key，改为支持 Tavily API，并实现了「Brave 优先，失败用 Tavily」的 fallback 机制。

### 改动文件（共 5 个）


| 文件                           | 改动内容                                       |
| ---------------------------- | ------------------------------------------ |
| `leafbot/config/schema.py`   | `WebSearchConfig` 新增 `tavily_api_key` 字段   |
| `leafbot/agent/tools/web.py` | `WebSearchTool` 增加 Tavily 搜索 + fallback 逻辑 |
| `leafbot/cli/commands.py`    | gateway 和 agent 命令传入 `tavily_api_key`      |
| `leafbot/agent/loop.py`      | 接收 `tavily_api_key` 并传给工具和子 agent          |
| `leafbot/agent/subagent.py`  | 接收 `tavily_api_key` 并传给子 agent 的搜索工具       |


### Fallback 逻辑

```
有 Brave key → 先调 Brave → 失败则用 Tavily
无 Brave key 但有 Tavily key → 直接用 Tavily
都没有 → 报错提示
```

### 配置方式（`~/.leafbot/config.json`）

```json
{
  "tools": {
    "web": {
      "proxy": "http://127.0.0.1:7890",
      "search": {
        "apiKey": "",
        "tavilyApiKey": "tvly-xxx",
        "maxResults": 5
      }
    }
  }
}
```

也支持环境变量：`BRAVE_API_KEY` / `TAVILY_API_KEY`

### 代理配置

leafbot 有两种网络请求，需要分别配置代理：


| 请求类型                   | 代理方式                                | 说明              |
| ---------------------- | ----------------------------------- | --------------- |
| LLM 调用（OpenRouter 等）   | 系统环境变量 `http_proxy` / `https_proxy` | 启动前 `export` 设置 |
| web_search / web_fetch | config 中 `tools.web.proxy`          | 写入 config.json  |


启动前必须执行：

```bash
export http_proxy=http://127.0.0.1:7890
export https_proxy=http://127.0.0.1:7890
```

### 验证方法

```bash
leafbot agent -m "搜索一下2026年最新AI新闻" --logs
```

看日志中出现 `Tavily search: proxy enabled` 即为成功。

### 已知问题：Telegram 中 LLM 不调用 web_search

**现象**：通过 Telegram 聊天时，LLM 倾向于直接用 `web_fetch`（猜 URL 抓取），不调用 `web_search`。

**原因**：Telegram 是持久 session，LLM 从历史对话中"记住"了 web_search 曾经不可用（改代码之前），所以自动避开。CLI 的 `-m` 模式每次是全新 session，不受影响。

**解决办法**：在 Telegram 中发送 `/new` 清空 session，开始新对话后 LLM 会正常使用 web_search。

### web_search vs web_fetch


| 工具           | 作用               | 需要 API key        | 需要 proxy |
| ------------ | ---------------- | ----------------- | -------- |
| `web_search` | 搜索关键词，返回标题+链接+摘要 | 是（Brave 或 Tavily） | 是        |
| `web_fetch`  | 抓取指定 URL 的网页内容   | 否                 | 是        |


LLM 自行决定用哪个工具。知道目标网址时倾向用 `web_fetch`，不确定去哪找时用 `web_search`。