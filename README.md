# AutoCAD MCP

通过 MCP（Model Context Protocol）让 AI 客户端（Claude Desktop / Cursor 等）用自然语言控制 AutoCAD 绘图。参考并改进自 [daobataotie/CAD-MCP](https://github.com/daobataotie/CAD-MCP)（差异见 [docs/references/cad-mcp-analysis.md](docs/references/cad-mcp-analysis.md)）。

## 环境要求

- Windows + 已安装 AutoCAD（本项目在 AutoCAD 2026 上开发，ProgID `AutoCAD.Application.25.1`，见 `src/autocad_mcp/config.json`）
- conda

## 快速开始

```bash
conda activate autocad-mcp
# 打开 AutoCAD 2026，然后：
mcp dev src/autocad_mcp/server.py    # 用 MCP Inspector 调试
```

接入 Claude Desktop：在 `claude_desktop_config.json`（Windows 上一般是 `%APPDATA%\Claude\claude_desktop_config.json`）里加入 `mcpServers`：

```json
{
  "mcpServers": {
    "autocad-mcp": {
      "command": "C:\\Users\\<用户名>\\.conda\\envs\\autocad-mcp\\python.exe",
      "args": ["-m", "autocad_mcp.server"]
    }
  }
}
```

（`command` 直接指向 conda 环境里的 `python.exe`，不要用 `conda run -n autocad-mcp ...`——后者在 Claude Desktop 拉起子进程时可能拿不到 conda 的 shell 初始化环境，也更容易碰到 Windows 控制台编码问题。前提是已经 `pip install -e .` 把本项目装进这个环境。）

## 网页 UI（自己选大模型，仍走 MCP 协议）

除了接 Claude Desktop，也可以用自带的网页界面，自己填 API Key、自己选大模型（Claude / OpenAI / OpenAI 兼容的国产模型如通义千问/DeepSeek/智谱 / 豆包（火山方舟 Ark））。网页后端是一个自建的 MCP client，通过 HTTP 连接 AutoCAD MCP server——`cad/`/`tools/` 两层完全复用，不是绕开 MCP 直接调 Python 函数。支持流式响应（SSE）：回复逐字显示，每个工具调用单独显示一行执行状态，不是等全部跑完才一次性返回。

先装网页相关依赖（装进同一个 `autocad-mcp` conda 环境，或者直接 `pip install -e ".[web]"`）：

```bash
"C:\Users\<用户名>\.conda\envs\autocad-mcp\python.exe" -m pip install anthropic openai fastapi "uvicorn[standard]" "volcengine-python-sdk[ark]"
```

需要同时起两个进程（**项目根目录**下执行，`web` 包不是通过 pip 装的，靠 `-m` 的当前目录解析）：

```bash
# 终端 1：AutoCAD MCP server，HTTP 模式，供网页后端连接（不影响 Claude Desktop 的 stdio 配置）
"C:\Users\<用户名>\.conda\envs\autocad-mcp\python.exe" -m autocad_mcp.server --http

# 终端 2：网页后端
"C:\Users\<用户名>\.conda\envs\autocad-mcp\python.exe" -m uvicorn web.backend.app:app --port 8000
```

打开 `http://127.0.0.1:8000`，选模型、填 API Key（只在当次请求里用，不落盘不写日志）、用自然语言聊天即可。**这是本地单用户场景的简化实现**：会话历史存在后端进程内存里（重启即丢），没有鉴权，只适合本机 `127.0.0.1` 访问，不要暴露到公网。

自动化测试/开发时如果需要真实模型的 API Key，不要手动填进网页表单——在项目根目录建一个 `.env`（已加入 `.gitignore`，不会被提交），格式参考：

```
doubao_base_url=https://ark.cn-beijing.volces.com/api/v3
doubao_model_name=ep-xxxxxxxx-xxxxx
doubao_api_key=你的真实key
```

然后写脚本直接读这个文件、程序化调用 `POST /api/chat/stream`（或 `/api/chat`）即可，不经过浏览器表单。

## 图纸理解（VQA，可选）

如果本机部署了配套的电力工程图纸理解模型（另一个毕设项目，InternVL3-8B + LoRA 微调，针对 110kV 变电站图纸场景），`ask_drawing_vqa`/`vqa_service_status` 这两个工具会转发到本地的 VQA API 服务（默认 `http://127.0.0.1:8933`）。没有部署这个模型也不影响其余功能——`vqa_tools.py` 只是一层薄的 HTTP 转发，服务没启动时会给出提示而不是报错崩溃。

## 项目结构

见 [docs/design/architecture.md](docs/design/architecture.md)。

## 开发文档 / 日志

- 设计方案：[docs/design/](docs/design/)
- 参考项目分析：[docs/references/](docs/references/)
- 开发日志（每次改动都会更新）：[docs/logs/devlog.md](docs/logs/devlog.md)
