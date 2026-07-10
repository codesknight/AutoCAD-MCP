# 架构设计方案

## 目标

做一个 MCP（Model Context Protocol）服务，让 AI 客户端（Claude Desktop / Cursor / Windsurf 等）通过自然语言控制 AutoCAD 进行绘图操作，参考 [daobataotie/CAD-MCP](https://github.com/daobataotie/CAD-MCP)（分析见 [cad-mcp-analysis.md](../references/cad-mcp-analysis.md)），但修正其设计缺陷并补充查询/修改能力。

## 分层架构

```
MCP Client (Claude 等)
     │ stdio, MCP 协议
     ▼
server.py           ── FastMCP 实例，注册所有工具
     │
     ▼
tools/               ── MCP 工具层：参数校验、调用 cad/ 层、格式化返回
 ├─ drawing_tools.py
 ├─ query_tools.py
 └─ document_tools.py
     │
     ▼
cad/                 ── COM 自动化层：只管跟 AutoCAD 说话，不知道 MCP 是什么
 ├─ connection.py     连接管理（GetActiveObject/Dispatch）
 ├─ geometry.py        坐标 -> VARIANT 转换
 ├─ controller.py       绘图操作
 └─ query.py            实体/图层查询
     │
     ▼
AutoCAD.Application (COM, ProgID: AutoCAD.Application.25.1)
```

**为什么这样分层**：`cad/` 层完全不依赖 `mcp` 包，只依赖 `pywin32`；`tools/` 层完全不直接碰 COM。好处：
1. 以后想换后端（比如换成 AutoCAD .NET 插件 + IPC，能力更强、支持真正的事务/撤销）时，只需要重写 `cad/` 层，`tools/` 和 `server.py` 不用动。
2. `cad/` 层可以脱离 MCP 独立写单元测试/脚本调试。

## 与参考项目的关键差异

| | CAD-MCP（参考项目） | 本项目 |
|---|---|---|
| 自然语言解析 | 自己写 `nlp_processor.py` | 不写，交给 MCP 客户端（Claude 本身） |
| ProgID | 硬编码 `"AutoCAD.Application"` | 走 `config.json`，带版本回退列表 |
| 查询/修改能力 | 无 | `cad/query.py`（图层/实体查询，规划中） |
| 分层 | server + controller 两层 | server + tools + cad 三层，职责更清晰 |

## 工具清单（规划）

| 工具 | 状态 | 说明 |
|---|---|---|
| `draw_line` | ✅ 已实现 | 端到端打通，验证脚手架可用 |
| `draw_circle` | 🚧 骨架 | TODO |
| `draw_arc` | 🚧 骨架 | TODO |
| `draw_rectangle` | 🚧 骨架 | TODO |
| `draw_text` | 🚧 骨架 | TODO |
| `draw_polyline` | 🚧 骨架（cad 层已建方法，工具未注册） | TODO |
| `draw_hatch` | 🚧 骨架（cad 层已建方法，工具未注册） | TODO |
| `add_dimension` | 🚧 骨架（cad 层已建方法，工具未注册） | TODO |
| `save_drawing` | 🚧 骨架 | TODO |
| `list_layers` | 🚧 骨架 | 创新点：参考项目没有 |
| `query_entities` | 🚧 骨架 | 创新点：参考项目没有 |

## 环境信息

- AutoCAD 2026，安装路径 `D:\LiuYanhong\Apps\AutoCAD2026\AutoCAD 2026`。
- COM ProgID：`AutoCAD.Application.25.1`（注册表确认，注意通用 `AutoCAD.Application` 未注册）。
- conda 环境：`autocad-mcp`，Python 3.11，依赖 `pywin32` / `mcp[cli]` / `pydantic`。

## 开放问题 / 后续迭代方向

- 是否要支持多 CAD 后端（中望/浩辰）？参考项目支持，本项目当前只针对 AutoCAD 2026，若要跟进需要在 `config.json` 里加 `cad_type` 切换逻辑（骨架已预留字段）。
- 事务/撤销管理：AutoCAD COM 接口本身对事务支持有限，可能需要在 `controller.py` 里手动记录"本次会话创建的 ObjectID 列表"来实现简单撤销，或改走 .NET 插件方案获得真正的 Transaction 支持。
