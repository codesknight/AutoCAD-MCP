# 开发日志

> 追加式记录，按日期分节。每次对项目做出实质性修改后在这里加一条。

## 2026-07-10

- 分析参考项目 [daobataotie/CAD-MCP](https://github.com/daobataotie/CAD-MCP) 的架构与局限性，落盘到 [docs/references/cad-mcp-analysis.md](../references/cad-mcp-analysis.md)。
- 产出架构设计方案，见 [docs/design/architecture.md](../design/architecture.md)：三层架构（server / tools / cad），确定不自建 NLP 解析层，确定 ProgID 走配置。
- 确认本机环境：AutoCAD 2026 已安装，COM ProgID 为 `AutoCAD.Application.25.1`（注册表确认，通用 ProgID 未注册）。
- 搭建项目骨架：
  - 新建 conda 环境 `autocad-mcp`（Python 3.11），安装 `pywin32` / `mcp[cli]`（1.28.1）/ `pydantic`（2.13.4）/ `pytest`。
  - 建立目录结构：`src/autocad_mcp/{cad,tools}`、`docs/{design,references,logs}`、`tests/`。
  - 完整实现 `cad/connection.py`（COM 连接，支持 ProgID 回退）、`cad/geometry.py`（坐标转 VARIANT）。
  - `cad/controller.py` 只完整实现 `draw_line`，其余（`draw_circle`/`draw_arc`/`draw_polyline`/`draw_rectangle`/`draw_text`/`draw_hatch`/`add_dimension`/`save_drawing`）留 `NotImplementedError` 占位。
  - `cad/query.py` 全部留白（`list_layers`/`query_entities`/`get_entity`/`delete_entity`），是相对参考项目的创新点，下一阶段实现。
  - `tools/` 下按 drawing/query/document 三个模块注册 MCP 工具，`server.py` 汇总注册。
  - `tests/test_connection.py`：需要真实 AutoCAD 运行的手动集成测试。
  - 初始化本地 git 仓库。

**下一步 TODO**：
1. 实现 `draw_circle`/`draw_arc`/`draw_rectangle`/`draw_polyline`/`draw_text`/`draw_hatch`/`add_dimension`/`save_drawing`。
2. 实现 `cad/query.py`（图层列表、实体查询、按 ObjectID 取实体、删除实体）。
3. 用 MCP Inspector（`mcp dev`）跑通全部工具列表，实际连 AutoCAD 2026 验证 `draw_line`。
