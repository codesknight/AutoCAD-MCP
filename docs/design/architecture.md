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
 ├─ document_tools.py
 └─ vqa_tools.py       转发到本地 VQA 模型服务（另一个毕设项目）
     │
     ▼
cad/                 ── COM 自动化层：只管跟 AutoCAD 说话，不知道 MCP 是什么
 ├─ connection.py     连接管理（GetActiveObject/Dispatch）
 ├─ geometry.py        坐标 -> VARIANT 转换
 ├─ controller.py       绘图操作
 ├─ query.py            实体/图层查询、区域查询、变换、图块属性
 └─ symbol_library.py   标准电力符号库目录解析
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
| 查询/修改能力 | 无 | `cad/query.py`（图层/实体查询、区域查询、变换、图块属性编辑，已实现） |
| 分层 | server + controller 两层 | server + tools + cad 三层，职责更清晰 |

## 工具清单

目前共 **34 个** MCP 工具，全部在真实 AutoCAD 2026 上端到端验证通过（含真实 MCP 协议验证，不只是直接调 Python 函数）：

| 分组 | 工具 |
|---|---|
| 绘图/创建（`cad/controller.py` + `tools/drawing_tools.py`） | `draw_line`/`draw_circle`/`draw_arc`/`draw_rectangle`/`draw_text`/`draw_mtext`/`draw_polyline`/`draw_hatch`/`add_dimension`/`insert_block`/`create_layer`/`set_layer_properties` |
| 查询/编辑（`cad/query.py` + `tools/query_tools.py`） | `list_layers`/`list_blocks`/`list_symbol_library`/`query_entities`/`query_entities_in_region`/`get_entity`/`delete_entity`/`move_entity`/`rotate_entity`/`copy_entity`/`scale_entity`/`mirror_entity`/`get_block_attributes`/`set_block_attribute`/`bulk_get_block_attributes`/`bulk_set_block_attributes`/`validate_block_attributes` |
| 文档（`tools/document_tools.py`） | `new_drawing`/`save_drawing`/`export_current_view` |
| 图纸理解（`tools/vqa_tools.py`，转发到另一个毕设项目的本地 VQA 模型） | `ask_drawing_vqa`/`vqa_service_status` |

其中 `list_layers`/`query_entities`/`get_entity`/`delete_entity`（查询能力）以及 `insert_block`/变换操作/`ask_drawing_vqa`（图块 + 编辑 + 看图理解）都是相对参考项目 CAD-MCP 的创新点（CAD-MCP 只能从零画图元，不能编辑已有内容、不能用标准符号图块、没有图纸理解能力，见 [cad-mcp-analysis.md](../references/cad-mcp-analysis.md)）。详细实现记录（含踩过的 COM 坑）见 [devlog.md](../logs/devlog.md)。

## 环境信息

- AutoCAD 2026，安装路径 `D:\LiuYanhong\Apps\AutoCAD2026\AutoCAD 2026`。
- COM ProgID：`AutoCAD.Application.25.1`（注册表确认，注意通用 `AutoCAD.Application` 未注册）。
- conda 环境：`autocad-mcp`，Python 3.11，依赖 `pywin32` / `mcp[cli]` / `pydantic`；网页 UI 额外依赖见 `pyproject.toml` 的 `[project.optional-dependencies].web`（`anthropic`/`openai`/`fastapi`/`uvicorn[standard]`/`volcengine-python-sdk[ark]`）。
- 需要真实模型 API Key 做开发测试时，用项目根目录的 `.env`（已在 `.gitignore` 里，不会被提交）存测试凭证，脚本直接读文件调用 `web/backend` 的 API，不通过浏览器表单填写。

## 网页 UI 集成路径（多大模型接入，仍保留 MCP 协议）

除了 Claude Desktop（stdio），项目还提供 `web/` 下的自建网页 UI + 后端，走一条独立的 MCP 集成路径：

```
浏览器            web/backend/app.py (FastAPI)
   │ POST /api/chat          （一次性返回）
   │ POST /api/chat/stream   （SSE 流式）
   └──────────────────────▶│
                            ▼
                    agent_loop.py（编排循环：run_turn / run_turn_stream）
                     │                │
                     ▼                ▼
              providers/*        mcp_client.py（MCP client，streamable-http）
           （多模型适配：Anthropic/          │
         OpenAI/OpenAI 兼容/豆包）           ▼
                                  server.py --http（新增的 HTTP 启动方式）
                                       │
                                       ▼
                                  cad/ 层（不变）→ AutoCAD
```

关键点：
- `server.py` 默认行为（stdio）完全不变，`--http` 只是多加的一种启动方式，两条路径（Claude Desktop / 网页 UI）可以同时跑，互不干扰，都复用同一套 `cad/`/`tools/`。
- 网页后端**不**直接 `import autocad_mcp` 的 `cad`/`tools` 模块，而是通过 `mcp` 官方 SDK 的 `streamable_http` client 连接 `server.py --http`，走真正的 MCP 协议——这是用户明确要求的设计（保留 MCP，而不是把 `cad/` 函数直接包成 tool schema 塞给大模型）。
- `providers/` 是多模型适配层：`base.py` 定义统一的 `LLMProvider.chat()`/`chat_stream()` 接口，`anthropic_provider.py`/`openai_provider.py` 各自把 MCP 的 `Tool.inputSchema` 转成对应厂商的 tool schema 格式（Anthropic 几乎不用转，OpenAI 需要包一层 `{"type": "function", "function": {...}}`）。`openai_provider.py` 同时覆盖真 OpenAI 和国产 OpenAI 兼容模型（通义千问/DeepSeek/智谱等），靠 `base_url` 参数区分；`doubao_provider.py` 继承 `OpenAIProvider`，只覆盖 `_build_client()` 换成 Volcengine Ark 的 SDK（请求/响应结构和 OpenAI 一致，包括 `chat_stream()` 也直接复用继承）。
- `chat_stream()`/`run_turn_stream()` 逐步 yield 结构化事件（`text_delta`/`tool_call`/`tool_result`/`error`/`done`），前端用 SSE 逐字显示回复、每次工具调用单独一行状态，不再是笼统的"思考中..."计时器。**已知问题**：这套多层异步生成器 + `StreamingResponse` 组合，在当前 anyio/Starlette 版本下，无论请求成功还是失败，服务端日志里都会出现一条 `RuntimeError: Attempted to exit a cancel scope...`——排查确认过这只是日志噪音，不影响返回给前端的内容（每次都完整正确），根因没有连根拔起，详见 [devlog.md](../logs/devlog.md) 2026-07-11（续十五、续十六后的更正）。
- 已知限制（记录在 README）：会话历史存进程内存、不落盘，没有鉴权，只适合本机单用户场景，不是生产方案。

## 开放问题 / 后续迭代方向

- 是否要支持多 CAD 后端（中望/浩辰）？参考项目支持，本项目当前只针对 AutoCAD 2026，若要跟进需要在 `config.json` 里加 `cad_type` 切换逻辑（骨架已预留字段）。
- 事务/撤销管理：AutoCAD COM 接口本身对事务支持有限，可能需要在 `controller.py` 里手动记录"本次会话创建的 ObjectID 列表"来实现简单撤销，或改走 .NET 插件方案获得真正的 Transaction 支持。
- ~~按区域批量选择/查询~~：已实现，见 `query_entities_in_region`（[#25](https://github.com/codesknight/AutoCAD-MCP/issues/25)）。
- ~~标准图块符号库~~：已用真实数据集解决，见 `list_symbol_library`（[#26](https://github.com/codesknight/AutoCAD-MCP/issues/26)）。
- ~~图块属性批量填报~~：已实现，见 `bulk_get_block_attributes`/`bulk_set_block_attributes`/`validate_block_attributes`（[#27](https://github.com/codesknight/AutoCAD-MCP/issues/27)）。
- **连接层自愈**：`state.py` 里的 `_connection`/`_controller`/`_query` 单例只在第一次调用时建立，如果 AutoCAD 里的活动文档被外部途径（用户在 AutoCAD 界面里手动关掉、或别的进程关闭了文档）意外改变，服务器不会自动重连，会一直报底层 COM 错误（`RPC_E_DISCONNECTED` 之类），直到有人手动调用 `new_drawing` 强制刷新。已验证复现（见 devlog 2026-07-11 续十四），修复思路：在 `get_controller()`/`get_query()` 包一层，捕获到连接失效的 COM 错误时自动重新走 `_wait_for_document` 逻辑。
