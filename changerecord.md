1、原本nanobot 只支持brave search，现在添加了tavily search
   - 逻辑：Brave 优先，失败或未配置时自动用 Tavily
   - 改动文件：schema.py、web.py、commands.py、loop.py、subagent.py
   - 配置：~/.nanobot/config.json 中 tools.web.search.tavilyApiKey