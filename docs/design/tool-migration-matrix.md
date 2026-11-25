# 工具迁移矩阵（2026-11-18）

来源：固定基线 SHA `5e83798` 的 36 工具 schema，并经真实 stdio tools/list 核对。
所有 36 项均检查 schema；CAD 工具的 fake 协议测试不证明几何或 CAD 实机行为正确。

| MCP 工具 | 当前 COM 路径 | 本轮验证 | HTTP Bridge |
| --- | --- | --- | --- |
| `add_dimension` | 串行 STA adapter | 旧协议 fixture 保持 | 实机创建/定义点/测量值重读通过；共同 WCS Z 平面 |
| `analyze_reference_drawing` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `ask_drawing_vqa` | 独立 VQA HTTP 转发 | schema；未调用外部服务 | 不适用 |
| `bulk_get_block_attributes` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `bulk_set_block_attributes` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `copy_entity` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `create_layer` | 串行 STA adapter | 协议 fixture + 小规模实机 smoke | 实验支持；本轮实机重读通过 |
| `delete_entity` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `draw_arc` | 串行 STA adapter | 旧 schema 保持 | 新增 HTTP；实机批处理创建及角度/长度/端点重读通过 |
| `draw_circle` | 串行 STA adapter | 协议 fixture + 小规模实机 smoke | 实验支持；本轮实机重读通过 |
| `draw_hatch` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `draw_line` | 串行 STA adapter | 协议 fixture + 小规模实机 smoke | 实验支持；本轮实机重读通过 |
| `draw_mtext` | 串行 STA adapter | 旧协议 fixture 保持 | 实机文字/宽高/样式重读通过 |
| `draw_polyline` | 串行 STA adapter | 旧协议 fixture 保持 | 实机顶点/闭合重读通过；OCS XY/旧重量级类型 |
| `draw_rectangle` | 串行 STA adapter | 旧协议 fixture 保持 | 首轮原生失败保留；修复后四顶点/闭合重读通过 |
| `draw_text` | 串行 STA adapter | 旧协议 fixture 保持 | 实机文字/旋转/高度/MCP_CJK 重读通过 |
| `export_current_view` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `get_block_attributes` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `get_entity` | 串行 STA adapter | 协议 fixture + 小规模实机 smoke | 实验支持；本轮实机重读通过 |
| `insert_block` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `list_blocks` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `list_layers` | 串行 STA adapter | 协议 fixture + 小规模实机 smoke | 实验支持；本轮实机重读通过 |
| `list_reference_drawings` | 本地目录读取 | schema；未调用外部服务 | 不适用 |
| `list_symbol_library` | 本地目录读取 | schema；未调用外部服务 | 不适用 |
| `mirror_entity` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `move_entity` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `new_drawing` | 串行 STA adapter | 协议 fixture + 小规模实机 smoke | 实验支持；本轮实机重读通过 |
| `query_entities` | 串行 STA adapter | 协议 fixture + 小规模实机 smoke | 实验支持；本轮实机重读通过 |
| `query_entities_in_region` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `rotate_entity` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `save_drawing` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `scale_entity` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `set_block_attribute` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `set_layer_properties` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `validate_block_attributes` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `vqa_service_status` | 独立 VQA HTTP 转发 | schema；未调用外部服务 | 不适用 |

最新 HTTP 验收见 [http-bridge.md](http-bridge.md)。新增四项运行时工具，旧 36 项 schema 保持不变：

| MCP 工具 | COM | HTTP |
| --- | --- | --- |
| `get_backend_status` | 不启动 CAD 的生命周期元数据 | 实例、能力、文档和 revision |
| `get_job_status` | 明确不支持 | 查询 job，不重放写入 |
| `execute_atomic_batch` | 明确不支持 | 显式文档、1–200 步事务 |
| `query_entities_page` | 明确不支持 | 显式文档、过滤/字段裁剪、签名游标 |

设计与验证边界见 [mcp-runtime-tools.md](mcp-runtime-tools.md)。

首批绘图迁移及原生错误记录见 [http-drawing-migration.md](http-drawing-migration.md)。

## 受控工作图增量（2026-11-19）

旧 36 项 schema 不变；总数增至 44。新增 create_working_drawing/get_working_drawing/save_working_drawing/reopen_saved_drawing 均仅 HTTP 支持，COM 明确拒绝。旧 save_drawing/export_current_view 的 HTTP 迁移状态不变。

原子批处理现支持图层、直线、圆、圆弧、矩形、多段线、文字、多行文字和标注；文件操作独立于数据库事务。能力清单区分单次、批处理及保存/重开。

契约见 [controlled-working-drawings.md](controlled-working-drawings.md)，真实创建—绘制—保存—只读重开—独立查询证据见[实机报告](../validation/2026-11-19-controlled-documents.md)。


## 执行证据增量（2026-11-25）

新增 get_document_binding / execute_observed_operation / get_execution_status，总数 47；原 44 项工具签名和成功内容保持兼容。COM 文档检查改用生命周期身份，不再按名称放行；回执为显式 opt-in，不把旧工具返回值冒充新契约。HTTP 保留原生 journal，新增只读对账不依赖 CAD 主线程状态。精确后端矩阵、作用域和限制见[执行证据说明](execution-evidence.md)。
