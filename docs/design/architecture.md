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

## 工具清单

目前共 **28 个** MCP 工具，全部在真实 AutoCAD 2026 上端到端验证通过（含真实 MCP 协议验证，不只是直接调 Python 函数）：

| 分组 | 工具 |
|---|---|
| 绘图/创建（`cad/controller.py` + `tools/drawing_tools.py`） | `draw_line`/`draw_circle`/`draw_arc`/`draw_rectangle`/`draw_text`/`draw_mtext`/`draw_polyline`/`draw_hatch`/`add_dimension`/`insert_block`/`create_layer`/`set_layer_properties` |
| 查询/编辑（`cad/query.py` + `tools/query_tools.py`） | `list_layers`/`list_blocks`/`query_entities`/`get_entity`/`delete_entity`/`move_entity`/`rotate_entity`/`copy_entity`/`scale_entity`/`mirror_entity`/`get_block_attributes`/`set_block_attribute` |
| 文档（`tools/document_tools.py`） | `save_drawing`/`export_current_view` |
| 图纸理解（`tools/vqa_tools.py`，转发到另一个毕设项目的本地 VQA 模型） | `ask_drawing_vqa`/`vqa_service_status` |

其中 `list_layers`/`query_entities`/`get_entity`/`delete_entity`（查询能力）以及 `insert_block`/变换操作/`ask_drawing_vqa`（图块 + 编辑 + 看图理解）都是相对参考项目 CAD-MCP 的创新点（CAD-MCP 只能从零画图元，不能编辑已有内容、不能用标准符号图块、没有图纸理解能力，见 [cad-mcp-analysis.md](../references/cad-mcp-analysis.md)）。详细实现记录（含踩过的 COM 坑）见 [devlog.md](../logs/devlog.md)。

## 环境信息

- AutoCAD 2026，安装路径 `D:\LiuYanhong\Apps\AutoCAD2026\AutoCAD 2026`。
- COM ProgID：`AutoCAD.Application.25.1`（注册表确认，注意通用 `AutoCAD.Application` 未注册）。
- conda 环境：`autocad-mcp`，Python 3.11，依赖 `pywin32` / `mcp[cli]` / `pydantic`。

## 网页 UI 集成路径（多大模型接入，仍保留 MCP 协议）

除了 Claude Desktop（stdio），项目还提供 `web/` 下的自建网页 UI + 后端，走一条独立的 MCP 集成路径：

```
浏览器            web/backend/app.py (FastAPI)
   │ POST /api/chat        │
   └──────────────────────▶│
                            ▼
                    agent_loop.py（编排循环）
                     │                │
                     ▼                ▼
              providers/*        mcp_client.py（MCP client，streamable-http）
           （多模型适配：Anthropic/          │
            OpenAI/OpenAI 兼容）             ▼
                                  server.py --http（新增的 HTTP 启动方式）
                                       │
                                       ▼
                                  cad/ 层（不变）→ AutoCAD
```

关键点：
- `server.py` 默认行为（stdio）完全不变，`--http` 只是多加的一种启动方式，两条路径（Claude Desktop / 网页 UI）可以同时跑，互不干扰，都复用同一套 `cad/`/`tools/`。
- 网页后端**不**直接 `import autocad_mcp` 的 `cad`/`tools` 模块，而是通过 `mcp` 官方 SDK 的 `streamable_http` client 连接 `server.py --http`，走真正的 MCP 协议——这是用户明确要求的设计（保留 MCP，而不是把 `cad/` 函数直接包成 tool schema 塞给大模型）。
- `providers/` 是多模型适配层：`base.py` 定义统一的 `LLMProvider.chat()` 接口，`anthropic_provider.py`/`openai_provider.py` 各自把 MCP 的 `Tool.inputSchema` 转成对应厂商的 tool schema 格式（Anthropic 几乎不用转，OpenAI 需要包一层 `{"type": "function", "function": {...}}`）。`openai_provider.py` 同时覆盖真 OpenAI 和国产 OpenAI 兼容模型（通义千问/DeepSeek/智谱等），靠 `base_url` 参数区分。
- 已知限制（记录在 README）：会话历史存进程内存、不落盘，没有鉴权，只适合本机单用户场景，不是生产方案。

## 开放问题 / 后续迭代方向

- 是否要支持多 CAD 后端（中望/浩辰）？参考项目支持，本项目当前只针对 AutoCAD 2026，若要跟进需要在 `config.json` 里加 `cad_type` 切换逻辑（骨架已预留字段）。
- 事务/撤销管理：AutoCAD COM 接口本身对事务支持有限，可能需要在 `controller.py` 里手动记录"本次会话创建的 ObjectID 列表"来实现简单撤销，或改走 .NET 插件方案获得真正的 Transaction 支持。
- **按区域批量选择/查询**：`query_entities` 目前是全表扫描，复杂图纸实体多的时候，需要"框选某个矩形区域内的实体"这类能力（对应 AutoCAD 的 `SelectionSet` + `SelectByPoint`/`SelectByPolygon`），而不是只能全表过滤或按单个 ObjectID 查。
- **标准图块符号库**：`insert_block` 支持传 .dwg 路径自动定义图块，但项目本身还没有一套现成的电力工程标准符号库（变压器/断路器/隔离开关等）——如果要让 AI"用标准符号组装图纸"而不是每次现找 .dwg 文件，需要整理一套符号库放进项目里。
- **图块属性批量填报**：`get_block_attributes`/`set_block_attribute` 目前一次只能查/改一个图块，复杂图纸里成百上千个设备图块的属性批量填报/校核还需要更高层的封装。
