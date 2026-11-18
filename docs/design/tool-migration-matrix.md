# 工具迁移矩阵（2026-11-18）

来源：固定基线 SHA `5e83798` 的 36 工具 schema，并经真实 stdio tools/list 核对。
所有 36 项均检查 schema；CAD 工具的 fake 协议测试不证明几何或 CAD 实机行为正确。

| MCP 工具 | 当前 COM 路径 | 本轮验证 | HTTP Bridge |
| --- | --- | --- | --- |
| `add_dimension` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `analyze_reference_drawing` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `ask_drawing_vqa` | 独立 VQA HTTP 转发 | schema；未调用外部服务 | 不适用 |
| `bulk_get_block_attributes` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `bulk_set_block_attributes` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `copy_entity` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `create_layer` | 串行 STA adapter | 协议 fixture + 小规模实机 smoke | 实验支持；本轮实机重读通过 |
| `delete_entity` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `draw_arc` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `draw_circle` | 串行 STA adapter | 协议 fixture + 小规模实机 smoke | 实验支持；本轮实机重读通过 |
| `draw_hatch` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `draw_line` | 串行 STA adapter | 协议 fixture + 小规模实机 smoke | 实验支持；本轮实机重读通过 |
| `draw_mtext` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `draw_polyline` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `draw_rectangle` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
| `draw_text` | 串行 STA adapter | 协议 fixture；未实机复测 | 未实现 |
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

最新 HTTP 验收见 [http-bridge.md](http-bridge.md)。批处理目前仅内部 Python API，未新增 MCP 工具。
