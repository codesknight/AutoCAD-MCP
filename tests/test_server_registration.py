"""server.py 的工具注册是纯 Python 函数装饰，不连接 AutoCAD——列出工具列表不需要
真实连接，可以无条件跑（不用 skip）。
"""
import asyncio

import autocad_mcp.server as srv


def test_all_expected_tools_registered():
    tools = asyncio.run(srv.mcp.list_tools())
    names = {t.name for t in tools}

    assert len(names) >= 34

    expected = {
        "new_drawing", "save_drawing", "export_current_view",
        "draw_line", "draw_circle", "draw_arc", "draw_rectangle",
        "draw_text", "draw_mtext", "draw_polyline", "draw_hatch", "add_dimension",
        "insert_block", "create_layer", "set_layer_properties",
        "list_layers", "list_blocks", "list_symbol_library",
        "query_entities", "query_entities_in_region", "get_entity", "delete_entity",
        "move_entity", "rotate_entity", "copy_entity", "scale_entity", "mirror_entity",
        "get_block_attributes", "set_block_attribute",
        "bulk_get_block_attributes", "bulk_set_block_attributes", "validate_block_attributes",
        "ask_drawing_vqa", "vqa_service_status",
    }
    assert expected <= names
