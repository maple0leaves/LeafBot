1、原本leafbot 只支持brave search，现在添加了tavily search
   - 逻辑：Brave 优先，失败或未配置时自动用 Tavily
   - 改动文件：schema.py、web.py、commands.py、loop.py、subagent.py
   - 配置：~/.leafbot/config.json 中 tools.web.search.tavilyApiKey

2、【问题排查记录】Tavily 搜索不生效
   - 现象：配置了 tavilyApiKey，但 leafbot agent/gateway 运行时 web_search 返回
     "Search API not configured"，日志中无任何 Tavily 相关输出
   - 排查过程：
     a) 检查配置文件 ~/.leafbot/config.json → tavilyApiKey 已正确填写 ✓
     b) 检查 Pydantic 模型（alias_generator=to_camel）→ camelCase 到 snake_case 映射正常 ✓
     c) 直接用 Python 调用 WebSearchTool.execute() → Tavily 搜索成功返回结果 ✓
     d) 在 web.py 的 execute() 方法开头加 debug 日志 → 运行 leafbot agent --logs 后
        该日志完全没有出现，说明执行的不是这个文件的代码
     e) 关键发现：pip show leafbot-ai 显示安装路径为 /root/project/leafbot_my
        而修改的代码在 /root/project/leafbot_my，两个是不同目录！
   - 根本原因：
     leafbot CLI 通过 pip install -e 安装自 /root/project/leafbot_my/（旧版），
     旧版 web.py 只有 Brave Search，完全没有 Tavily 回退逻辑。
     用户在 /root/project/leafbot_my/ 中做的改动（加入 Tavily 支持）从未被安装。
   - 修复：在 leafbot_my 目录下执行 pip install -e . 重新安装
   - 额外注意：修复后 AI 仍可能不调用 web_search，因为对话记忆中缓存了
     "search API 不可用"的上下文，需要 /new 开启新会话才会正常触发