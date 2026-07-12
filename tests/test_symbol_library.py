"""不需要真实 AutoCAD 连接的纯单元测试——symbol_library 只是解析 JSON + 拼路径。"""
from autocad_mcp.cad import symbol_library


def test_list_symbols_returns_list_of_dicts():
    result = symbol_library.list_symbols()
    assert isinstance(result, list)
    for entry in result:
        assert {"name_cn", "name_en", "file"} <= entry.keys()
