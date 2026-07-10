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

## 项目结构

见 [docs/design/architecture.md](docs/design/architecture.md)。

## 开发文档 / 日志

- 设计方案：[docs/design/](docs/design/)
- 参考项目分析：[docs/references/](docs/references/)
- 开发日志（每次改动都会更新）：[docs/logs/devlog.md](docs/logs/devlog.md)
