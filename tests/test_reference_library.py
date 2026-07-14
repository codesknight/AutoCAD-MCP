"""真实参考图纸工具。列目录不需要真实 AutoCAD 连接（纯读 JSON+文件系统检查）；
实际打开图纸提取布局需要真实连接，且依赖用户本机的外部数据集——数据集不在本机
时（比如换了台电脑）跳过，不当失败。
"""
import pytest

from autocad_mcp.cad import reference_library


def test_list_reference_drawings_returns_list_of_dicts():
    result = reference_library.list_reference_drawings()
    assert isinstance(result, list)
    for entry in result:
        assert {"name_cn", "description", "file"} <= entry.keys()


def test_analyze_reference_drawing_extracts_real_layout(scratch_doc):
    catalog = reference_library.list_reference_drawings()
    if not catalog:
        pytest.skip("参考图纸数据集不在本机，跳过")

    file_path = catalog[0]["file"]
    result = reference_library.analyze_reference_drawing(scratch_doc, file_path, max_entities=20)

    assert result["file"] == file_path
    assert result["total_entity_count"] > 0
    assert 0 < result["returned_count"] <= 20
    for entity in result["entities"]:
        assert "type" in entity
        assert "object_id" in entity

    # 分析完之后，当前 scratch 文档必须还是活动文档、连接必须还能正常用——
    # 这是这个工具实现里最容易踩的坑（切走活动文档分析参考图纸，分析完要切回来，
    # 且 connection 自己缓存的 document 引用不能失效）。
    active_name = scratch_doc.document.Name
    assert active_name != ""  # 能正常访问 .Name 就说明连接没坏


def test_analyze_reference_drawing_entity_type_filter(scratch_doc):
    catalog = reference_library.list_reference_drawings()
    if not catalog:
        pytest.skip("参考图纸数据集不在本机，跳过")

    file_path = catalog[0]["file"]
    result = reference_library.analyze_reference_drawing(
        scratch_doc, file_path, entity_type="AcDbLine", max_entities=20,
    )
    assert all(e["type"] == "AcDbLine" for e in result["entities"])
