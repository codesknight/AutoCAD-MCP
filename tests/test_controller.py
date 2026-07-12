"""cad/controller.py 的绘图/创建能力，跑在真实 AutoCAD 连接的空白 scratch 图纸上。"""
import win32com.client

from autocad_mcp.cad.controller import CADController
from autocad_mcp.cad.query import CADQuery


def test_draw_line(scratch_doc):
    ctrl = CADController(scratch_doc)
    oid = ctrl.draw_line((0, 0, 0), (10, 10, 0))
    assert isinstance(oid, int)


def test_draw_circle(scratch_doc):
    ctrl = CADController(scratch_doc)
    oid = ctrl.draw_circle((0, 0, 0), 5)
    entity = scratch_doc.document.ObjectIdToObject(oid)
    assert entity.Radius == 5


def test_draw_arc(scratch_doc):
    ctrl = CADController(scratch_doc)
    oid = ctrl.draw_arc((0, 0, 0), 5, 0, 1.0)
    assert isinstance(oid, int)


def test_draw_rectangle(scratch_doc):
    ctrl = CADController(scratch_doc)
    oid = ctrl.draw_rectangle((0, 0, 0), (10, 5, 0))
    assert isinstance(oid, int)


def test_draw_polyline_open_and_closed(scratch_doc):
    ctrl = CADController(scratch_doc)
    points = [(0, 0, 0), (10, 0, 0), (10, 10, 0)]
    oid_open = ctrl.draw_polyline(points, closed=False)
    oid_closed = ctrl.draw_polyline(points, closed=True)
    assert oid_open != oid_closed


def test_draw_text_and_mtext_use_cjk_style(scratch_doc):
    """draw_text/draw_mtext 必须用 MCP_CJK 样式，否则中文会在视图里显示成问号
    （见 devlog 2026-07-11 续八），这里直接校验 StyleName，防止回归。
    """
    ctrl = CADController(scratch_doc)
    query = CADQuery(scratch_doc)

    oid_text = ctrl.draw_text((0, 0, 0), "测试文字", 5)
    text_entity = scratch_doc.document.ObjectIdToObject(oid_text)
    assert text_entity.StyleName == "MCP_CJK"
    assert query.get_entity(oid_text)["text_string"] == "测试文字"

    oid_mtext = ctrl.draw_mtext((0, 20, 0), "10kV 进线", width=50, height=5)
    mtext_entity = scratch_doc.document.ObjectIdToObject(oid_mtext)
    assert mtext_entity.StyleName == "MCP_CJK"
    assert query.get_entity(oid_mtext)["text_string"] == "10kV 进线"


def test_draw_hatch(scratch_doc):
    ctrl = CADController(scratch_doc)
    oid = ctrl.draw_hatch([(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)])
    assert isinstance(oid, int)


def test_add_dimension(scratch_doc):
    ctrl = CADController(scratch_doc)
    oid = ctrl.add_dimension((0, 0, 0), (10, 0, 0), (5, -2, 0))
    assert isinstance(oid, int)


def test_create_layer_and_set_properties(scratch_doc):
    ctrl = CADController(scratch_doc)
    ctrl.create_layer("PYTEST_LAYER", color=1)
    ctrl.set_layer_properties("PYTEST_LAYER", locked=True, frozen=False, visible=True)
    layer = scratch_doc.document.Layers.Item("PYTEST_LAYER")
    assert layer.Color == 1
    assert layer.Lock is True


def test_insert_block_and_list_blocks(scratch_doc):
    ctrl = CADController(scratch_doc)
    doc = scratch_doc.document
    origin = win32com.client.VARIANT(win32com.client.pythoncom.VT_ARRAY | win32com.client.pythoncom.VT_R8, [0, 0, 0])
    doc.Blocks.Add(origin, "PYTEST_BLOCK")

    oid = ctrl.insert_block("PYTEST_BLOCK", (0, 0, 0))
    assert isinstance(oid, int)
    assert "PYTEST_BLOCK" in ctrl.list_blocks()
