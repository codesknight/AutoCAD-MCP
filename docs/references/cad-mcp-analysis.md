# 参考项目分析：daobataotie/CAD-MCP

仓库：https://github.com/daobataotie/CAD-MCP （分析时间 2026-07-10）

## 架构

```
MCP Client (Claude/Cursor/Windsurf)
     │  stdio, MCP 协议
     ▼
src/server.py        ── 暴露 ~11 个 MCP 工具
     │
     ▼
src/cad_controller.py ── 封装 COM 调用
     │
     ▼
AutoCAD/GstarCAD/ZWCAD .Application (COM)
```

- 纯 Python，仅 Windows，通过 pywin32 COM 自动化控制 AutoCAD 及兼容软件（中望 ZWCAD、浩辰 GCAD）。
- 连接方式：`win32com.client.GetActiveObject(prog_id)` 优先接现有实例，失败则 `Dispatch(prog_id)` 拉起新实例。
- 坐标传参必须包成 COM VARIANT 数组（`pythoncom.VT_ARRAY | pythoncom.VT_R8`），这是 AutoCAD COM 接口的硬性要求。
- 暴露的工具：`draw_line`、`draw_circle`、`draw_arc`、`draw_ellipse`、`draw_polyline`、`draw_rectangle`、`draw_text`、`draw_hatch`、`add_dimension`、`save_drawing`、`process_command`。
- 还有一个 `drawing://current` 资源和 `cad-assistant` prompt。

## 设计缺陷 / 局限性（本项目要规避或改进的点）

1. **自建 NLP 解析层是多余的**：项目里有 `nlp_processor.py`，自己做颜色词/图形关键词/动作关键词识别，再转成结构化调用。但在 MCP 语境下，MCP 客户端（如 Claude）本身就会做自然语言理解并直接调用带类型参数的工具 —— 这一层更像是项目从"独立自然语言建模工具"演化成 MCP 服务时留下的历史包袱，重新设计时不应该照搬。
2. **只能新建，不能查询/修改**：没有实体查询、选择集、修改、删除、撤销等能力，图纸只能单向"画"，无法读取已有内容或做增量编辑。
3. **没有事务/撤销管理**：批量绘图出错时无法整体回滚。
4. **ProgID 硬编码**：直接写死 `"AutoCAD.Application"`，但很多机器（包括本机 AutoCAD 2026）并未注册这个不带版本号的通用 ProgID，只注册了版本化的（如 `AutoCAD.Application.25.1`），这种写法换机器/换版本就会连接失败。

## 本项目（AutoCAD_MCP）的应对

- 不写独立 NLP 层，工具直接接收结构化参数。
- `cad/` 层新增 `query.py`，作为查询/修改能力的落地位置（后续实现）。
- ProgID 从 `config.json` 读取，且带 fallback 列表，见 [connection.py](../../src/autocad_mcp/cad/connection.py)。
